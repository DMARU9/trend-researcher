#!/usr/bin/env python3
"""評価の実走（LLM 呼び出しを伴う手動の確認。FR-065 / FR-066 / SC-035）。

既存 CLI（`python -m trend_researcher`）とは別の**独立した入口**である。生成は
出荷パッケージの公開 API を **in-process** で呼び（`trend_researcher.ainvoke` →
`render_report`）、`subprocess` で CLI を起動しない（中間データは戻り値にしか
現れないため。FR-046 / FR-065）。

初期状態に載せるのは CLI と同じ最小の 3 項目（`messages` 1 件 / `platform` /
明示指定時の `max_results`）に限る。CLI の引数解釈（`--since` の解析など）は
再実装しない（FR-065）。

使い方:

    uv run python script/evaluate.py --platform x \
        --config baseline.json --config candidate.json \
        --config-name baseline --config-name candidate
    uv run python script/evaluate.py --judge-only artifacts/eval/tr-basic__baseline__<commit>__<model>.jsonl

`--config` のファイルは `Configuration` の項目の上書き（JSON オブジェクト）。
`--config` も `--judge-only` も無い実行は引数エラー。判定モデルは `--judge-model`
→ `TR_EVAL_MODEL` → 既定の順で解決し、生成と同じモデルで採点した場合はその事実を
結果に記録する（FR-069）。

終了コード: 0 = 完了 / 1 = 実行の失敗（レポートを 1 件も得られなかった）/
2 = 引数・前提の不足（資格情報なし・データセットや構成が見つからない）。

このファイルは `testpaths = ["tests"]` の収集対象外である（FR-066）。契約は
`tests/unit/test_evaluation_entrypoint.py` が固定し、採点ロジックは `tests/eval/`
側のテストが担う。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from trend_researcher import render_report, trend_researcher
from trend_researcher.configuration import Configuration, resolve_env
from trend_researcher.providers import get_provider
from trend_researcher.tools.llm import ainvoke_structured, build_model

# リポジトリ直下を import パスに足してから評価の補助を読む（`tests/eval/` は出荷
# パッケージに含めないため。FR-065）。
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.eval import datasets, evaluators, records

#: 生成の既定モデル（`tools/llm.py` の `build_model` と同じ解決順・同じ既定。
#: T006 の実測値。結果の設定識別子へ記録するために同じ規則で解決する。FR-069）。
DEFAULT_MODEL = "openai:mimo-v2.5"

#: 判定の既定モデル（生成とは別に `TR_EVAL_MODEL` で指定できる。FR-069）。
DEFAULT_JUDGE_MODEL = DEFAULT_MODEL

#: 終了コード。
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

#: 生成に使ったコミットが分からない場合の記録。
UNKNOWN_COMMIT = "unknown"

#: 結果へ書く使用量の項目（`records.USAGE_KEYS`）と、パイプラインが記録する項目
#: （`ModelUsage`）の対応（FR-042）。結果の項目名は保存済みの結果と同じに保つ。
#: `calls` は並びの要素数そのものなので元の項目を持たない（`None`）。
USAGE_SOURCES: dict[str, str | None] = {
    "calls": None,
    "prompt_tokens": "input_tokens",
    "completion_tokens": "output_tokens",
    "total_tokens": "total_tokens",
}


# --- 前提の解決（引数または環境変数。FR-066） ------------------------------


def resolve_judge_model(explicit: str | None = None) -> str:
    """判定モデルを解決する（引数 → `TR_EVAL_MODEL` → 既定。FR-069）。"""
    return explicit or resolve_env("EVAL_MODEL", default=DEFAULT_JUDGE_MODEL)


def resolve_generation_model(env_prefix: str | None = None) -> str:
    """生成に使うモデル名を、出荷側と同じ解決順で求める（FR-069）。

    `build_model` は `TR_MODEL` → `{env_prefix}_MODEL` → 既定の順で解決する。
    結果の設定識別子に含めるために同じ規則で解決する（部分文字列で判定しない）。
    """
    return resolve_env("MODEL", default=DEFAULT_MODEL, env_prefix=env_prefix)


def resolve_platform(explicit: str | None = None) -> str:
    """対象プラットフォームを解決する（引数 → `TR_PLATFORM`。FR-066）。"""
    return explicit or resolve_env("PLATFORM", default="")


def build_judge(model_name: str, *, env_prefix: str | None = None) -> Any:
    """判定モデルを既存の経路（`tools/llm.py` の `build_model`）で構築する（FR-045 / FR-069）。

    `build_model` はモデル名を `TR_MODEL` → `{env_prefix}_MODEL` → 既定の順で
    解決するため、判定モデル名は**構築のあいだだけ** `TR_MODEL` に置き、直後に
    元の値へ戻す。`ChatOpenAI` を直接構築すると接続設定（`OPENAI_BASE_URL` と
    セッションのヘッダー）を迂回してしまうため、必ずこの経路を通す。
    """
    previous = os.environ.get("TR_MODEL")
    os.environ["TR_MODEL"] = model_name
    try:
        return build_model(role="summary", env_prefix=env_prefix)
    finally:
        if previous is None:
            os.environ.pop("TR_MODEL", None)
        else:
            os.environ["TR_MODEL"] = previous


def resolve_commit(explicit: str | None = None) -> str:
    """対象コミットの識別子を解決する（引数 → `TR_EVAL_COMMIT` → `.git` の読み取り）。

    `subprocess` を使わないため `git` コマンドは起動せず、`.git` を直接読む
    （FR-065）。解決できない場合は `unknown` を記録し、実行は止めない。
    """
    if explicit:
        return explicit
    from_env = resolve_env("EVAL_COMMIT", default="")
    if from_env:
        return from_env
    return _commit_from_git_dir() or UNKNOWN_COMMIT


def _git_dir() -> Path | None:
    """リポジトリの `.git`（worktree では `gitdir:` の指す先）。"""
    marker = REPO_ROOT / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        line = marker.read_text(encoding="utf-8").strip()
        if line.startswith("gitdir:"):
            return (REPO_ROOT / line[len("gitdir:") :].strip()).resolve()
    return None


def _commit_from_git_dir() -> str | None:
    """`HEAD` から短いコミット識別子を得る（分からなければ `None`）。"""
    git_dir = _git_dir()
    if git_dir is None:
        return None
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head:
        return None
    if not head.startswith("ref:"):
        return head[:7]  # detached HEAD
    ref = head[len("ref:") :].strip()
    try:
        return (git_dir / ref).read_text(encoding="utf-8").strip()[:7]
    except OSError:
        return _packed_ref(git_dir, ref)


def _packed_ref(git_dir: Path, ref: str) -> str | None:
    """`packed-refs` から ref の解決を試みる（clone 直後の状態）。"""
    try:
        lines = (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            return parts[0][:7]
    return None


def load_config(path: str | Path) -> dict[str, Any]:
    """構成の定義（`Configuration` の項目の上書き）を読む（FR-072 の識別子を作る単位）。"""
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"構成ファイルが見つかりません: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"構成ファイルを JSON として読めません: {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"構成ファイルは項目の上書き（JSON オブジェクト）にしてください: {source}")
    unknown = sorted(set(payload) - set(Configuration.model_fields))
    if unknown:
        raise ValueError(f"構成ファイルの項目が設定クラスにありません: {unknown}（{source}）")
    return payload


def plan_configs(args: argparse.Namespace) -> list[tuple[str, dict[str, Any]]]:
    """構成の識別子と上書きの組（`--config` と同じ順で `--config-name` を対応させる）。"""
    if len(args.config_name) > len(args.config):
        raise ValueError("--config-name は --config と同じ数だけ指定してください。")
    plans: list[tuple[str, dict[str, Any]]] = []
    for index, path in enumerate(args.config):
        name = args.config_name[index] if index < len(args.config_name) else Path(path).stem
        if not name:
            raise ValueError(f"構成の識別子が空です: {path}")
        plans.append((name, load_config(path)))
    names = [name for name, _ in plans]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise ValueError(
            f"構成の識別子が重複しています: {duplicated}"
            "（同じ名前の結果が別の構成を指さないようにしてください。FR-072）"
        )
    return plans


# --- 実走（生成 → 判定 → 記録） -------------------------------------------


async def run_evaluation(args: argparse.Namespace) -> int:
    """実走の本体。生成は公開 API、判定は `tools/llm.py` の経路で行う。"""
    platform = resolve_platform(args.platform)
    provider = get_provider(platform)
    settings = Configuration.load(env_prefix=provider.env_prefix)
    judge_name = resolve_judge_model(args.judge_model)
    judge_model = build_judge(judge_name, env_prefix=provider.env_prefix)
    generation_model = resolve_generation_model(provider.env_prefix)
    commit = resolve_commit(args.commit)
    # 提示順はランダム化し、使った順序を結果に残す（FR-041）。
    order = evaluators.shuffled_order(rng=random.Random())
    dataset = datasets.load_dataset(args.dataset)

    if args.judge_only:
        return await _judge_only(args, settings=settings, judge_model=judge_model, order=order)

    saved: list[Path] = []
    empty_total = 0
    for name, overrides in plan_configs(args):
        generated, usage = await _generate(
            dataset, settings, overrides=overrides, platform=platform, provider=provider
        )
        judged = {
            row["id"]: await evaluators.ascore_report(
                row["article"], judge=_judge_callable(judge_model, settings), order=order
            )
            for row in generated
        }
        aggregated = evaluators.aggregate_scored(list(judged.values()))
        target, count = records.write_result(
            records.RunContext(
                dataset=dataset.name,
                dataset_fingerprint=dataset.fingerprint,
                config_name=name,
                commit=commit,
                platform=platform,
                model=generation_model,
                judge_model=judge_name,
                judge_model_is_generator=judge_name == generation_model,
                config=overrides,
                axes=aggregated["axes"],
                axis_order=aggregated["axis_order"],
                excluded_axes=aggregated["excluded_axes"],
                overall_quality=aggregated["overall_quality"],
                usage=records.usage_summary(usage),
                scores=judged,
            ),
            generated,
            out_dir=args.out,
            overwrite=args.overwrite,
        )
        saved.append(target)
        empty = sum(1 for row in generated if not row["article"])
        empty_total += empty
        print(
            f"[完了] {target} に {count} 件のレコードと採点を保存しました"
            f"（空のレポート: {empty} 件 / 総合品質: {aggregated['overall_quality']}）。",
            flush=True,
        )

    if len(saved) >= 2:
        _report_comparison(saved[0], saved[1], out_dir=args.out)
    if saved and empty_total >= len(dataset.entries) * len(saved):
        print("[エラー] レポートを 1 件も生成できませんでした。", file=sys.stderr, flush=True)
        return EXIT_FAILURE
    return EXIT_OK


async def _judge_only(
    args: argparse.Namespace,
    *,
    settings: Configuration,
    judge_model: Any,
    order: Sequence[str],
) -> int:
    """保存済みの結果に対して判定だけをやり直す（生成を繰り返さない。FR-041）。"""
    target = records.find_result(args.judge_only, out_dir=args.out)
    context = records.load_result(target)
    saved_records = records.load_records(target)
    judge = _judge_callable(judge_model, settings)
    judged: dict[str, Any] = {}
    for record in saved_records:
        judged[record.id] = await evaluators.ascore_report(record.article, judge=judge, order=order)
    aggregated = evaluators.aggregate_scored(list(judged.values()))
    run = records.RunContext(
        dataset=str(context.get("dataset", "")),
        dataset_fingerprint=str(context.get("dataset_fingerprint", "")),
        config_name=str(context.get("config_name", target.stem)),
        commit=str(context.get("commit", UNKNOWN_COMMIT)),
        platform=str(context.get("platform", "")),
        model=str(context.get("model", "")),
        judge_model=str(context.get("judge_model", "")),
        judge_model_is_generator=bool(context.get("judge_model_is_generator", False)),
        config=context.get("config", {}),
        axes=aggregated["axes"],
        axis_order=aggregated["axis_order"],
        excluded_axes=aggregated["excluded_axes"],
        overall_quality=aggregated["overall_quality"],
        # 生成をやり直していないため、使用量は保存済みの値を引き継ぐ（FR-042）。
        usage=context.get("usage", {}),
        scores=judged,
    )
    written, count = records.write_result(
        run, saved_records, out_dir=target.parent, overwrite=False
    )
    if written != target:
        raise records.ResultError(f"保存先が既存の結果と一致しません: {written} != {target}")
    print(f"[完了] {target} に判定だけをやり直した結果を追記しました（{count} 件）。", flush=True)
    return EXIT_OK


async def _generate(
    dataset: datasets.Dataset,
    settings: Configuration,
    *,
    overrides: Mapping[str, Any],
    platform: str,
    provider: Any,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """データセットの全指示を生成する（1 件の失敗で全体を止めない）。"""
    configuration = settings.model_copy(
        update={**overrides, "platform": platform, "output_format": "markdown"}
    )
    runnable_config = {"configurable": configuration.model_dump()}
    usage: dict[str, int] = {}
    generated: list[dict[str, str]] = []
    for entry in dataset.entries:
        state: dict[str, Any] = {
            "messages": [HumanMessage(content=entry.prompt)],
            "platform": platform,
        }
        if overrides.get("max_results") is not None:
            # 明示指定のみを state に載せる（未指定と既定値を区別する。FR-065）。
            state["max_results"] = overrides["max_results"]
        article = ""
        try:
            result = await trend_researcher.ainvoke(state, runnable_config)
        except Exception as exc:  # noqa: BLE001 - 1 件の失敗で実行全体を止めない
            print(
                f"[警告] {entry.id} の生成に失敗しました: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
        else:
            report = result.get("report")
            if report is not None:
                article = render_report(report, provider)
            _add_usage(usage, result.get("usage"))
        generated.append({"id": entry.id, "prompt": entry.prompt, "article": article})
    return generated, usage


def _add_usage(usage: dict[str, int], recorded: object) -> None:
    """パイプラインが記録した使用量を足し込む（FR-042 / FR-061）。

    `state["usage"]` は **LLM 呼び出し 1 回につき 1 要素**の並び
    （`Annotated[list[ModelUsage], operator.add]`）であり、辞書ではない。要素数を
    そのまま呼び出し回数として数え、判明しているトークンだけを足す。

    不明なトークン数（`None`）は 0 に潰さない。項目を作らないままにすると
    `records.usage_summary` が「不明」として記録する（FR-061）。並びが得られない
    場合（キーが無い・形が違う）も何も足さない。
    """
    if not isinstance(recorded, Sequence) or isinstance(recorded, (str, bytes)):
        return
    # 呼び出し回数は要素数そのもの（元の項目を持たない）。
    usage["calls"] = usage.get("calls", 0) + len(recorded)
    for entry in recorded:
        for key, source in USAGE_SOURCES.items():
            if source is None:
                continue
            value = getattr(entry, source, None)
            if isinstance(value, int):
                usage[key] = usage.get(key, 0) + value


def _judge_callable(model: Any, settings: Configuration) -> evaluators.Judge:
    """判定モデルの呼び出し（既存の `tools/llm.py` の経路。FR-045）。"""

    async def judge(prompt: str, schema: type[BaseModel]) -> object:
        return await ainvoke_structured(
            schema,
            prompt,
            role="summary",
            model=model,
            retry_max=settings.retry_max,
            retry_wait_seconds=settings.retry_wait_seconds,
            method=settings.structured_method,
        )

    return judge


def _report_comparison(left: Path, right: Path, *, out_dir: str | None) -> None:
    """保存済みの 2 つの結果を比較して表示する（生成も判定もしない。SC-016）。"""
    try:
        comparison = records.compare_saved(left, right, out_dir=out_dir)
    except records.ResultError as exc:
        print(f"[警告] 比較できませんでした: {exc}", file=sys.stderr, flush=True)
        return
    if not comparison["comparable"]:
        print(f"[情報] 比較不能: {comparison['reason']}", file=sys.stderr, flush=True)
        return
    print(
        f"[比較] 勝敗: {comparison['winner']}"
        f"（左 {comparison['decisive']['left']} / 右 {comparison['decisive']['right']}"
        f" / 引き分け {comparison['ties']}）",
        flush=True,
    )


# --- 入口 ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """引数の定義（contracts/evaluation-contract.md §4 のオプション集合。FR-066）。"""
    parser = argparse.ArgumentParser(
        prog="script/evaluate.py",
        description="レポートの品質を採点し、2 つの構成を比較する（実走）。",
    )
    parser.add_argument(
        "--dataset",
        default=datasets.DEFAULT_DATASET,
        help=f"評価対象のデータセット名（既定: {datasets.DEFAULT_DATASET}）",
    )
    parser.add_argument(
        "--platform", default=None, help="対象プラットフォーム（既定: TR_PLATFORM）"
    )
    parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="構成の定義（実行時設定の上書きを書いた JSON。複数指定可）",
    )
    parser.add_argument(
        "--config-name",
        action="append",
        default=[],
        dest="config_name",
        help="構成の識別子（--config と同じ順で対応させる。既定: ファイル名）",
    )
    parser.add_argument("--judge-model", default=None, help="判定モデル（既定: TR_EVAL_MODEL）")
    parser.add_argument("--out", default=None, help="結果の保存先（既定: artifacts/eval/）")
    parser.add_argument("--overwrite", action="store_true", help="同名の既存の結果を置き換える")
    parser.add_argument(
        "--judge-only", default=None, help="保存済みの結果に対して判定だけをやり直す"
    )
    parser.add_argument(
        "--commit", default=None, help="対象コミットの識別子（既定: TR_EVAL_COMMIT / .git）"
    )
    return parser


def _usage_error(message: str) -> int:
    """引数・前提の不足を知らせて終了する（実走を始めない）。"""
    print(f"[エラー] {message}", file=sys.stderr, flush=True)
    return EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    """実走の入口。戻り値は終了コード（0 / 1 / 2）。"""
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:
            raise
        return EXIT_USAGE

    if not args.config and not args.judge_only:
        return _usage_error("--config（複数可）または --judge-only を指定してください。")
    if not os.getenv("OPENAI_API_KEY"):
        # 資格情報の不足は実行を始める前に知らせる（途中まで採点した結果を確定扱いにしない）。
        return _usage_error(
            "生成と判定に使う資格情報がありません（OPENAI_API_KEY を設定してください）。"
        )
    if not args.judge_only:
        if not resolve_platform(args.platform):
            return _usage_error(
                "--platform または TR_PLATFORM で対象プラットフォームを指定してください。"
            )
        try:
            datasets.load_dataset(args.dataset)
            plan_configs(args)
        except (datasets.DatasetError, TypeError, ValueError) as exc:
            return _usage_error(str(exc))

    try:
        return asyncio.run(run_evaluation(args))
    except KeyboardInterrupt:
        return EXIT_FAILURE
    except (records.ResultError, OSError, TypeError, ValueError) as exc:
        return _usage_error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
