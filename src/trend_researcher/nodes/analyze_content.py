"""analyze_content ノード（FR-007 対応、並列上限 2、X / YouTube 共通）。"""

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
from trend_researcher.tools.llm import ainvoke_structured, ainvoke_text, build_model
from trend_researcher.tools.parse import extract_list_items, extract_section


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
) -> tuple[AnalysisFinding, CompressedSource | None, bool]:
    """1 件を解析する。返り値は `(解析結果, 圧縮の記録（無ければ None）, フォールバックしたか)`。

    圧縮はここで完結させる。後続段（`extract_common` / `compile_report`）は生の素材を
    参照しないため、圧縮した本文を解析に渡して解析結果を残せば足りる（FR-026）。
    """
    model = build_model("research", provider.env_prefix)
    material, compressed = await compression.compress_source(
        source_text,
        env_prefix=provider.env_prefix,
        max_chars=max_chars,
        timeout=timeout,
        instruction=instruction,
        source_id=candidate.id,
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
    max_chars: int,
    timeout: float,
    instruction: str,
    retry_max: int,
    retry_wait_seconds: float,
    method: str,
    degrade: DegradeOptions,
) -> tuple[list[AnalysisFinding], list[CompressedSource], int]:
    """全件を並列上限 2 で解析し、`(解析結果, 圧縮の記録, フォールバック件数)` を返す。

    縮退の記録（`degrade`）は候補をまたいで共有する。1 ノード実行＝1 本の梯子
    （FR-017）。並列実行なので、段のカウンタを候補ごとに増やすと上限が
    候補数倍になってしまう。
    """
    sem = asyncio.Semaphore(2)

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
            )

    outcomes = await asyncio.gather(*[_bounded(c) for c in candidates])
    analyses = [finding for finding, _, _ in outcomes]
    compressed = [record for _, record, _ in outcomes if record is not None]
    fallen_back = sum(1 for _, _, fell_back in outcomes if fell_back)
    return analyses, compressed, fallen_back


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
    """各コンテンツを「ブログ執筆の参考」として要約する（並列上限 2）。"""
    configurable = Configuration.from_runnable_config(config)
    emitter = make_emitter()
    emitter.emit(NODE_ANALYZE_CONTENT, "開始", detail="並列上限 2")
    progress_messages = emitter.get_messages()

    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    candidates = state.get("candidates", [])
    contexts_by_id = {c.id: c for c in state.get("contexts", [])}
    # 圧縮プロンプトへ載せる元の指示文（R-5）。無い実行（単体テスト）でも動くようにする。
    instruction = getattr(state.get("instruction"), "raw_text", "") or ""
    # 縮退（US3）は 1 ノード実行につき 1 つの梯子を使い、記録を状態へ返す（FR-017）
    degrade = options_for(configurable, NODE_ANALYZE_CONTENT)
    analyses, compressed, fallen_back = asyncio.run(
        _analyze_all(
            candidates,
            contexts_by_id,
            provider,
            max_chars=configurable.compression_threshold,
            timeout=configurable.compression_timeout_seconds,
            instruction=instruction,
            retry_max=configurable.retry_max,
            retry_wait_seconds=configurable.retry_wait_seconds,
            method=configurable.structured_method,
            degrade=degrade,
        )
    )

    emitter.emit(NODE_ANALYZE_CONTENT, "完了", detail=f"{len(analyses)} 件を要約")
    if compressed:
        # 追加の観測は `note()` に出す（`emit()` の書式と `messages` は不変。FR-030 / D-3）
        emitter.note(_compression_note(compressed))
    if fallen_back:
        # 同じく補足行。件数で 1 行にまとめる（候補ごとに 1 行出すと既定の入力で増えすぎる）
        emitter.note(_fallback_note(fallen_back))
    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()
    return {
        "analyses": analyses,
        "compressed": compressed,
        "degradations": degrade.records,
        "messages": progress_messages,
    }
