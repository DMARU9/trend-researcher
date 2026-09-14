"""CLI エントリ（python -m trend_researcher）。X / YouTube 共通。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration, ConfigurationError, _check_bounds
from trend_researcher.models import OutputFormat
from trend_researcher.providers import available_platforms, get_provider
from trend_researcher.rendering import render_report
from trend_researcher.tools.degradation import DegradationError

#: グラフ側に属する公開名（`_graph` がモジュール属性として解決する）
_GRAPH_NAMES = ("EXECUTION_TIMEOUT", "trend_researcher")


def __getattr__(name: str) -> Any:
    """グラフ（重い import）を参照された時だけ読み込む（SC-013 / T099）。

    `mock.patch("trend_researcher.__main__.EXECUTION_TIMEOUT", …)` や
    `mock.patch("trend_researcher.__main__.trend_researcher", …)`（統合テストの
    ハーネス）のようにモジュール属性として差し替えられる必要があるため、PEP 562 の
    モジュール level `__getattr__` で公開する。初回参照で実体を作り、以後は通常の
    属性として扱われる（差し替えの後始末も mock の既定動作のまま）。
    """
    if name in _GRAPH_NAMES:
        from trend_researcher.graph import EXECUTION_TIMEOUT, trend_researcher

        return EXECUTION_TIMEOUT if name == "EXECUTION_TIMEOUT" else trend_researcher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _graph() -> tuple[Any, Any]:
    """時間上限とグラフ本体をモジュール属性として解決する（遅延 import。T099）。

    関数ローカルで `from trend_researcher.graph import …` すると、ハーネスが
    `trend_researcher.__main__` に当てた差し替えを無視して実物を使ってしまう。
    モジュール属性として読むことで、差し替え（無ければ `__getattr__` の遅延読み込み）
    の結果をそのまま使う。
    """
    # `Any` 経由の属性アクセス（`getattr` の定数名は ruff B009 が禁じる）
    module: Any = sys.modules[__name__]
    return module.EXECUTION_TIMEOUT, module.trend_researcher


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="trend_researcher",
        description="自然言語指示から自律的にトレンドリサーチレポートを生成する CLI（X / YouTube 対応）。",
    )
    parser.add_argument("instruction", help="自然言語のリサーチ指示")
    parser.add_argument(
        "--platform",
        choices=available_platforms(),
        required=True,
        help="対象プラットフォーム（利用可能な値は choices の一覧）",
    )
    parser.add_argument("--output", help="レポート書き込み先ファイル（省略時は stdout）")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="最終レポートの出力形式（既定: markdown）",
    )
    parser.add_argument("--max-results", type=int, default=None, help="解析対象件数（既定 5）")
    parser.add_argument("--lang", default=None, help="字幕取得の優先言語（YouTube 用、既定: ja）")
    parser.add_argument(
        "--since",
        default=None,
        help="投稿日下限（YYYY-MM-DD）。この日以降に公開された投稿のみ対象",
    )
    parser.add_argument("--cache-dir", default=None, help="中間成果物の永続化先（既定: cache/）")
    parser.add_argument(
        "--sort",
        choices=["relevance", "likes"],
        default="relevance",
        help="選定基準（X 用。relevance=関連度順／likes=いいね数順）",
    )
    return parser.parse_args(argv)


async def _run_async(args: argparse.Namespace, settings: Configuration) -> dict:
    """非同期でリサーチを実行し、結果辞書を返す。

    `settings` は `Configuration.load()` で解決済みの実行時設定（明示指定 >
    環境変数 > 既定）。グラフへは**この値**を `RunnableConfig` で渡す（SET-006）。
    """
    platform = args.platform
    output_format = OutputFormat.JSON if args.format == "json" else OutputFormat.MARKDOWN

    since: datetime | None = None
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=UTC)

    # CLI が決める値（プラットフォーム・出力形式・選定基準・投稿日下限）を載せて
    # グラフへ渡す。設定の解決（環境変数・既定値）は Settings 側で完了している。
    configuration = settings.model_copy(
        update={
            "platform": platform,
            "output_format": output_format.value,
            "sort_by": args.sort,
            "published_after": since.isoformat() if since else None,
        }
    )

    runnable_config: RunnableConfig = {
        "configurable": configuration.model_dump(),
    }

    # ユーザー入力は messages + platform + max_results。設定は RunnableConfig（Configuration）経由で渡す。
    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content=args.instruction)],
        "platform": platform,
    }
    if args.max_results is not None:
        # 明示指定のみを state に載せる。未指定と「5 件指定」を区別するため（FR-011）。
        initial_state["max_results"] = args.max_results

    execution_timeout, graph = _graph()
    return await asyncio.wait_for(
        graph.ainvoke(initial_state, runnable_config),
        timeout=execution_timeout.total_seconds(),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI メイン。戻り値は終了コード（0/1/2）。"""
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:
            raise
        return 2

    # 空文字・空白のみの指示は引数エラーとして扱う（外部接続より前に判定する）
    if not args.instruction.strip():
        print("[エラー] 指示を指定してください。", file=sys.stderr, flush=True)
        return 2

    platform = args.platform
    # 登録済みプラットフォームの解決は引数検証直後に 1 回だけ行う（差は provider が持つ）
    provider = get_provider(platform)
    # 実行時設定は単一の型で解決する（FR-013 / SET-002）。明示指定（CLI）は
    # `model_copy(update=...)` で与え、`model_fields_set` に載せて環境変数より
    # 優先させる（SET-006 / SET-007）。
    #
    # 検証は**起動時**（LLM・検索・ファイル読み書きの前）に済ませる。値域外は
    # 丸めず・既定値に置換せず、引数エラーと同じ exit 2 で拒否する（FR-024 / SC-023 /
    # settings-contract §3）。`model_copy(update=...)` は検証しないため、上書きの
    # 直後に宣言した値域でもう一度検査する（実測: Pydantic v2 は update を検証しない）。
    try:
        settings = Configuration.load(env_prefix=provider.env_prefix)
        overrides: dict[str, Any] = {}
        if args.max_results is not None:
            overrides["max_results"] = args.max_results
        if args.lang is not None:
            overrides["transcript_language"] = args.lang
        if args.cache_dir is not None:
            # 明示指定のパスは実行時の CWD 基準で解決する（現行の `--cache-dir` と同じ）
            overrides["cache_dir"] = str(Path(args.cache_dir).expanduser().resolve())
        if overrides:
            settings = settings.model_copy(update=overrides)
        settings = _check_bounds(settings)
    except ConfigurationError as exc:
        # 文言は `ConfigurationError.message` が 1 か所で組み立てる（契約の書式）
        print(exc.message, file=sys.stderr, flush=True)
        return 2

    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            print(f"[エラー] --since は YYYY-MM-DD 形式で指定してください: {args.since}", file=sys.stderr, flush=True)
            return 2

    try:
        result = asyncio.run(_run_async(args, settings))
    except TimeoutError:
        # 時間上限は差し替えられ得るので、モジュール属性として読む（`_graph` と同じ）
        execution_timeout, _ = _graph()
        print(
            f"[警告] リサーチが時間上限（{int(execution_timeout.total_seconds() / 60)}分）に達しました。途中結果を返します。",
            file=sys.stderr,
            flush=True,
        )
        # タイムアウト時は途中結果がないため、空のレポートを返す
        return 1
    except DegradationError as exc:
        # 上限超過で入力を縮小し切っても生成できなかった（FR-015 / 契約 §6）。
        # 理由（試した段数・縮小前後の長さ）をそのまま出す（握り潰すと原因が消える）。
        print(f"[エラー] {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[エラー] リサーチ実行中に問題が発生しました: {exc}", file=sys.stderr, flush=True)
        return 1

    report = result.get("report")
    if report is None:
        print("[エラー] レポートが生成されませんでした。", file=sys.stderr, flush=True)
        return 1

    if not report.candidates:
        print(
            f"該当なし: 指定された指示に一致する{provider.content_noun}が見つかりませんでした。",
            file=sys.stderr,
            flush=True,
        )
        rendered = render_report(report, provider)
    else:
        requested = report.instruction.max_results or settings.max_results
        if len(report.candidates) < requested:
            print(
                f"[情報] 要求件数 {requested} 件に対し、実際に見つかったのは "
                f"{len(report.candidates)} 件です。",
                file=sys.stderr,
                flush=True,
            )
        rendered = render_report(report, provider)

    if args.output:
        try:
            Path(args.output).write_text(rendered, encoding="utf-8")
        except OSError as exc:
            print(
                f"[エラー] レポートを {args.output} に書き出せませんでした: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return 1
        print(f"[完了] レポートを {args.output} に書き出しました。", file=sys.stderr, flush=True)
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    sys.exit(main())
