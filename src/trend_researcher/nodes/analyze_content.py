"""analyze_content ノード（FR-007 対応、並列上限は設定値（既定 2）、X / YouTube 共通）。"""

from __future__ import annotations

import asyncio
import re

from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration
from trend_researcher.models import (
    AnalysisFinding,
    BlogAngle,
    Candidate,
    CompressedSource,
    Context,
    Failure,
)
from trend_researcher.progress import NODE_ANALYZE_CONTENT, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.providers.base import Provider
from trend_researcher.state import AgentState
from trend_researcher.tools import compression
from trend_researcher.tools.degradation import (
    DegradationError,
    DegradeOptions,
    options_for,
)
from trend_researcher.tools.llm import (
    UsageMeter,
    ainvoke_structured,
    ainvoke_text,
    build_model,
)
from trend_researcher.tools.parse import extract_list_items, extract_section

#: `Failure.message` の上限（data-model §3.3「先頭 200 文字に切り詰める」）
_FAILURE_MESSAGE_CHARS = 200


def _analysis_failure(candidate: Candidate, exc: BaseException) -> Failure:
    """解析 1 件の失敗を記録する（無言で欠落させない。FR-021）。

    `id` は候補の識別子にする。失敗した対象が分からないと「どの素材が解析できて
    いないか」を後から辿れない（FR-023）。
    """
    message = str(exc).strip() or type(exc).__name__
    return Failure(
        kind="analysis",
        id=candidate.id,
        error_type=type(exc).__name__,
        message=message[:_FAILURE_MESSAGE_CHARS],
    )


def _failure_note(failures: list[Failure]) -> str:
    """失敗の件数と理由の 1 行（FR-023。候補ごとではなく 1 行にまとめる）。

    理由は**重複を除いて**並べる。同じ原因で 10 件落ちたときに同じ文を 10 回
    出しても読めない。
    """
    reasons = sorted({f"{f.error_type}: {f.message}" for f in failures})
    return f"解析できなかった対象 {len(failures)} 件（{' / '.join(reasons)}）"


def _parse_angles_table(markdown_table: str) -> list[BlogAngle]:
    """「ブログの活用アイデア」表を解析。"""
    angles: list[BlogAngle] = []
    for line in markdown_table.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|[\s:|-]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or not all(cells[:3]):
            # 3 列そろっていない行は採用しない。空セルを許すと、プロンプトの例示行
            # （`| （必要なだけ繰り返す） | | |`）や空文字の切り口がそのまま
            # `key_points` / 報告書の表に混じるため。
            continue
        if cells[0] in ("切り口", "角度"):
            continue
        angles.append(BlogAngle(angle=cells[0], value=cells[1], key_phrase=cells[2]))
    return angles


def _build_source_text(candidate: Candidate, context: Context | None) -> str:
    """ツイート本文＋スレッド＋リプライ、または字幕をソーステキストに整形。"""
    parts: list[str] = []
    body = candidate.text
    thread = getattr(context, "thread_text", "") if context else ""
    replies = getattr(context, "replies", []) if context else []
    if thread:
        parts.append(f"[親ツイート（スレッド）]\n{thread}")
    if body:
        parts.append(f"[本文]\n{body}")
    if replies:
        parts.append("[代表的なリプライ]\n" + "\n".join(f"- {r}" for r in replies))
    if not body and not thread and not replies and context and context.text:
        # YouTube 字幕
        parts.append(f"[字幕]\n{context.text}")
    return "\n\n".join(parts)


async def _structured_finding(
    prompt: str,
    *,
    model: object,
    retry_max: int,
    retry_wait_seconds: float,
    method: str,
    env_prefix: str | None,
    degrade: DegradeOptions,
    meter: UsageMeter | None = None,
) -> AnalysisFinding | None:
    """構造化出力で 1 件を解析する（規定回数を使い切ったら `None`）。

    例外は送出しない。`None` を返して呼び出し側を既存の決定的解析へ切り替える
    （FR-011 / FR-012）。`AnalysisFinding` の `id` / `title` は素材（候補）が正
    なので、ここでは上書きしない（呼び出し側で揃える）。

    例外なのが縮退の使い切りだけ。これは送出して実行を終わらせる（FR-015）。
    """
    try:
        return await ainvoke_structured(
            AnalysisFinding,
            prompt,
            model=model,
            env_prefix=env_prefix,
            retry_max=retry_max,
            retry_wait_seconds=retry_wait_seconds,
            method=method,
            degrade=degrade,
            meter=meter,
        )
    except DegradationError:
        raise
    except Exception:  # noqa: BLE001 - 失敗は決定的解析で継続する（FR-011）
        return None


async def _analyze_one(
    candidate: Candidate,
    source_text: str,
    provider: Provider,
    *,
    max_chars: int,
    timeout: float,
    instruction: str,
    retry_max: int,
    retry_wait_seconds: float,
    method: str,
    degrade: DegradeOptions,
    meter: UsageMeter,
) -> tuple[AnalysisFinding, CompressedSource | None, bool]:
    """1 件を解析する。返り値は `(解析結果, 圧縮の記録（無ければ None）, フォールバックしたか)`。

    圧縮はここで完結させる。後続段（`extract_common` / `compile_report`）は生の素材を
    参照しないため、圧縮した本文を解析に渡して解析結果を残せば足りる（FR-026）。

    使用量（FR-061）は圧縮も含めて `meter` に記録する。並列実行でも 1 つの受け皿を
    共有するため、どの呼び出しも漏れない（`analyze_content` 名でまとまる）。
    """
    model = build_model("research", provider.env_prefix)
    material, compressed = await compression.compress_source(
        source_text,
        env_prefix=provider.env_prefix,
        max_chars=max_chars,
        timeout=timeout,
        instruction=instruction,
        source_id=candidate.id,
        meter=meter,
    )
    prompt = provider.analyze_content_prompt.format(
        title=candidate.author_handle or candidate.title or candidate.url,
        transcript=material or "（本文なし・メタデータのみ）",
    )
    structured = await _structured_finding(
        prompt,
        model=model,
        retry_max=retry_max,
        retry_wait_seconds=retry_wait_seconds,
        method=method,
        env_prefix=provider.env_prefix,
        degrade=degrade,
        meter=meter,
    )
    if structured is not None:
        # LLM には素材の識別子を渡していないため、`id` / `title` は候補から入れる
        # （入れないとレポートの紐づけが壊れる）。他の項目はモデルの値をそのまま使う。
        return (
            structured.model_copy(update={"id": candidate.id, "title": candidate.title}),
            compressed,
            False,
        )

    result = await ainvoke_text(
        prompt,
        model=model,
        env_prefix=provider.env_prefix,
        retry_max=retry_max,
        retry_wait_seconds=retry_wait_seconds,
        degrade=degrade,
        meter=meter,
    )
    text = result.content if hasattr(result, "content") else str(result)

    summary = extract_section(text, "概要")
    angles = _parse_angles_table(extract_section(text, "ブログの活用アイデア"))
    evidence = extract_list_items(extract_section(text, "そのまま使える引用"))

    if not summary.strip():
        for para in text.split("\n\n"):
            para = para.strip()
            # 見出し行と表の行は要約に使わない。見出しと表の間に空行がある応答
            # （`## ブログの活用アイデア` + 空行 + 表）で生の Markdown 表が
            # `summary` になり、下の切り口ベースの合成が使われなくなるため。
            if para and not para.startswith(("#", "|")):
                summary = para
                break
    if not summary.strip() and angles:
        summary = f"このコンテンツでは、{angles[0].angle}などについて語られています。" + (
            f"ほかにも{angles[1].angle}といった観点が扱われており、ブログのネタとして活用できます。"
            if len(angles) > 1 else ""
        )

    key_points = [a.angle for a in angles] if angles else []
    return (
        AnalysisFinding(
            id=candidate.id,
            title=candidate.title,
            summary=summary,
            angles=angles,
            key_points=key_points,
            evidence=evidence,
        ),
        compressed,
        True,
    )


async def _analyze_all(
    candidates: list[Candidate],
    contexts_by_id: dict[str, Context],
    provider: Provider,
    *,
    concurrency: int,
    max_chars: int,
    timeout: float,
    instruction: str,
    retry_max: int,
    retry_wait_seconds: float,
    method: str,
    degrade: DegradeOptions,
    meter: UsageMeter,
) -> tuple[list[AnalysisFinding], list[CompressedSource], int, list[Failure]]:
    """全件を `concurrency` 件ずつ並列に解析し、`(解析結果, 圧縮の記録, フォールバック件数, 失敗)` を返す。

    並列数は設定（`analysis_concurrency`。既定 2）から受け取る。ここに固定値を
    書くと、実行 1 回あたりの上限が設定を無視して 2 に張り付く（FR-005 / FR-028）。

    縮退の記録（`degrade`）は候補をまたいで共有する。1 ノード実行＝1 本の梯子
    （FR-017）。並列実行なので、段のカウンタを候補ごとに増やすと上限が
    候補数倍になってしまう。

    失敗は隔離する。`gather(return_exceptions=True)` で候補ごとの例外を受け取り、
    成功分を `analyses`、失敗分を `failures` に分ける（FR-020）。1 件の失敗でレポート
    全体を失わせない。**サービス終了要求（`asyncio.CancelledError`）だけは例外**で、
    部分失敗として飲み込まずに再送出する（原則 V / 契約 §3）。
    """
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(cand: Candidate) -> tuple[AnalysisFinding, CompressedSource | None, bool]:
        source_text = _build_source_text(cand, contexts_by_id.get(cand.id))
        async with sem:
            return await _analyze_one(
                cand,
                source_text,
                provider,
                max_chars=max_chars,
                timeout=timeout,
                instruction=instruction,
                retry_max=retry_max,
                retry_wait_seconds=retry_wait_seconds,
                method=method,
                degrade=degrade,
                meter=meter,
            )

    outcomes = await asyncio.gather(*[_bounded(c) for c in candidates], return_exceptions=True)

    analyses: list[AnalysisFinding] = []
    compressed: list[CompressedSource] = []
    failures: list[Failure] = []
    fallen_back = 0
    for candidate, outcome in zip(candidates, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            failures.append(_analysis_failure(candidate, outcome))
            continue
        finding, record, fell_back = outcome
        analyses.append(finding)
        if record is not None:
            compressed.append(record)
        fallen_back += fell_back
    return analyses, compressed, fallen_back, failures


def _compression_note(records: list[CompressedSource]) -> str:
    """圧縮の件数と縮小率の 1 行（FR-029。既存の進捗文言は変えない）。"""
    applied = sum(1 for r in records if r.applied)
    before = sum(r.input_chars for r in records)
    after = sum(r.output_chars for r in records)
    reduction = 1 - (after / before) if before else 0.0
    return (
        f"長文素材 {len(records)} 件を圧縮（成功 {applied}/{len(records)}、"
        f"平均 {reduction:.1%} 削減）"
    )


def _fallback_note(count: int) -> str:
    """解析のフォールバック件数の 1 行（FR-029。既存の進捗文言は変えない）。"""
    return f"構造化出力を取得できなかったため見出し表の解析へ切り替えました（{count} 件）"


def analyze_content(state: AgentState, config: RunnableConfig) -> dict:
    """各コンテンツを「ブログ執筆の参考」として要約する（並列上限は設定値。既定 2）。"""
    configurable = Configuration.from_runnable_config(config)
    emitter = make_emitter()
    # 表示する並列上限も同じ設定値を映す（既定は 2 なので既存の文言は変わらない。FR-035）
    emitter.emit(
        NODE_ANALYZE_CONTENT, "開始", detail=f"並列上限 {configurable.analysis_concurrency}"
    )
    progress_messages = emitter.get_messages()

    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    candidates = state.get("candidates", [])
    contexts_by_id = {c.id: c for c in state.get("contexts", [])}
    # 圧縮プロンプトへ載せる元の指示文（R-5）。無い実行（単体テスト）でも動くようにする。
    instruction = getattr(state.get("instruction"), "raw_text", "") or ""
    # 縮退（US3）は 1 ノード実行につき 1 つの梯子を使い、記録を状態へ返す（FR-017）
    degrade = options_for(configurable, NODE_ANALYZE_CONTENT)
    # 使用量は 1 ノード実行につき 1 つの受け皿へ集める（FR-061）。並列でも 1 つ
    meter = UsageMeter(NODE_ANALYZE_CONTENT)
    analyses, compressed, fallen_back, failed = asyncio.run(
        _analyze_all(
            candidates,
            contexts_by_id,
            provider,
            concurrency=configurable.analysis_concurrency,
            max_chars=configurable.compression_threshold,
            timeout=configurable.compression_timeout_seconds,
            instruction=instruction,
            retry_max=configurable.retry_max,
            retry_wait_seconds=configurable.retry_wait_seconds,
            method=configurable.structured_method,
            degrade=degrade,
            meter=meter,
        )
    )

    emitter.emit(NODE_ANALYZE_CONTENT, "完了", detail=f"{len(analyses)} 件を要約")
    if compressed:
        # 追加の観測は `note()` に出す（`emit()` の書式と `messages` は不変。FR-030 / D-3）
        emitter.note(_compression_note(compressed))
    if fallen_back:
        # 同じく補足行。件数で 1 行にまとめる（候補ごとに 1 行出すと既定の入力で増えすぎる）
        emitter.note(_fallback_note(fallen_back))
    if failed:
        # 失敗の件数と理由（FR-023）。件数で 1 行にまとめる（理由は重複を除く）
        emitter.note(_failure_note(failed))
    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()
    return {
        "analyses": analyses,
        "compressed": compressed,
        "degradations": degrade.records,
        # 前の段（`fetch`）の記録を上書きしない。`failures` は通常フィールド
        # （reducer なし）なので、返す値に前の段の分を含めておかないと消える
        "failures": list(state.get("failures", [])) + failed,
        # 使用量は reducer（`operator.add`）で連結される（FR-061 / data-model §2.1）
        "usage": meter.records,
        "messages": progress_messages,
    }
