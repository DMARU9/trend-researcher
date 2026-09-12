"""analyze_content ノード（FR-007 対応、並列上限 2、X / YouTube 共通）。"""

from __future__ import annotations

import asyncio
import re

from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration
from trend_researcher.models import AnalysisFinding, BlogAngle
from trend_researcher.progress import NODE_ANALYZE_CONTENT, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState
from trend_researcher.tools.llm import build_model
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
        if len(cells) < 3:
            continue
        if cells[0] in ("切り口", "角度"):
            continue
        angles.append(BlogAngle(angle=cells[0], value=cells[1], key_phrase=cells[2]))
    return angles


def _build_source_text(candidate: "Candidate", context: "Context | None") -> str:  # noqa: F821
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


async def _analyze_one(candidate: "Candidate", source_text: str, provider: "Provider") -> AnalysisFinding:  # noqa: F821
    model = build_model("research")
    prompt = provider.analyze_content_prompt.format(
        title=candidate.author_handle or candidate.title or candidate.url,
        transcript=source_text[:20000] or "（本文なし・メタデータのみ）",
    )
    result = await model.ainvoke(prompt)
    text = result.content if hasattr(result, "content") else str(result)

    summary = extract_section(text, "概要")
    angles = _parse_angles_table(extract_section(text, "ブログの活用アイデア"))
    evidence = extract_list_items(extract_section(text, "そのまま使える引用"))

    if not summary.strip():
        for para in text.split("\n\n"):
            para = para.strip()
            if para and not para.startswith("#"):
                summary = para
                break
    if not summary.strip() and angles:
        summary = f"このコンテンツでは、{angles[0].angle}などについて語られています。" + (
            f"ほかにも{angles[1].angle}といった観点が扱われており、ブログのネタとして活用できます。"
            if len(angles) > 1 else ""
        )

    key_points = [a.angle for a in angles] if angles else []
    return AnalysisFinding(
        id=candidate.id,
        title=candidate.title,
        summary=summary,
        angles=angles,
        key_points=key_points,
        evidence=evidence,
    )


async def _analyze_all(candidates: list["Candidate"], contexts_by_id: dict[str, "Context"], provider: "Provider") -> list[AnalysisFinding]:  # noqa: F821
    sem = asyncio.Semaphore(2)

    async def _bounded(cand: "Candidate") -> AnalysisFinding:
        source_text = _build_source_text(cand, contexts_by_id.get(cand.id))
        async with sem:
            return await _analyze_one(cand, source_text, provider)

    return await asyncio.gather(*[_bounded(c) for c in candidates])


def analyze_content(state: AgentState, config: RunnableConfig) -> dict:
    """各コンテンツを「ブログ執筆の参考」として要約する（並列上限 2）。"""
    configurable = Configuration.from_runnable_config(config)
    emitter = make_emitter()
    emitter.emit(5, NODE_ANALYZE_CONTENT, "開始", detail="並列上限 2")
    progress_messages = emitter.get_messages()

    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    candidates = state.get("candidates", [])
    contexts_by_id = {c.id: c for c in state.get("contexts", [])}
    analyses = asyncio.run(_analyze_all(candidates, contexts_by_id, provider))

    emitter.emit(5, NODE_ANALYZE_CONTENT, "完了", detail=f"{len(analyses)} 件を要約")
    progress_messages.extend(emitter.get_messages())
    return {"analyses": analyses, "messages": progress_messages}
