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

from trend_researcher.configuration import Configuration
from trend_researcher.graph import EXECUTION_TIMEOUT, render_report, trend_researcher
from trend_researcher.models import OutputFormat
from trend_researcher.providers import available_platforms, get_provider


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

    return await asyncio.wait_for(
        trend_researcher.ainvoke(initial_state, runnable_config),
        timeout=EXECUTION_TIMEOUT.total_seconds(),
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

    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            print(f"[エラー] --since は YYYY-MM-DD 形式で指定してください: {args.since}", file=sys.stderr, flush=True)
            return 2

    try:
        result = asyncio.run(_run_async(args, settings))
    except TimeoutError:
        print(
            f"[警告] リサーチが時間上限（{int(EXECUTION_TIMEOUT.total_seconds() / 60)}分）に達しました。途中結果を返します。",
            file=sys.stderr,
            flush=True,
        )
        # タイムアウト時は途中結果がないため、空のレポートを返す
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
        rendered = render_report(report)
    else:
        requested = report.instruction.max_results or settings.max_results
        if len(report.candidates) < requested:
            print(
                f"[情報] 要求件数 {requested} 件に対し、実際に見つかったのは "
                f"{len(report.candidates)} 件です。",
                file=sys.stderr,
                flush=True,
            )
        rendered = render_report(report)

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
