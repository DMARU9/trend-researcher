"""extract_common ノード（FR-008 対応、X / YouTube 共通）。"""

from __future__ import annotations

import re

from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration
from trend_researcher.models import AnalysisFinding, CommonTheme
from trend_researcher.progress import NODE_EXTRACT_COMMON, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState
from trend_researcher.tools.llm import build_model
from trend_researcher.tools.parse import extract_list_items, extract_section


def _format_analyses(analyses: list[AnalysisFinding]) -> str:
    lines = []
    for a in analyses:
        lines.append(f"### コンテンツ {a.id}")
        lines.append(f"要約: {a.summary}")
        lines.append("ポイント: " + " / ".join(a.key_points))
        lines.append("根拠: " + " / ".join(a.evidence))
        lines.append("")
    return "\n".join(lines)


def extract_common(state: AgentState, config: RunnableConfig) -> dict:
    """コンテンツ間の共通ネタを抽出する。"""
    configurable = Configuration.from_runnable_config(config)
    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    emitter = make_emitter()
    emitter.emit(6, NODE_EXTRACT_COMMON, "開始")
    progress_messages = emitter.get_messages()

    analyses = state.get("analyses", [])
    model = build_model("research")
    prompt = provider.extract_common_prompt.format(analyses=_format_analyses(analyses))
    result = model.invoke(prompt)
    text = result.content if hasattr(result, "content") else str(result)

    themes = _parse_themes(text, [a.id for a in analyses])

    emitter.emit(6, NODE_EXTRACT_COMMON, "完了", detail=f"{len(themes)} 件の共通テーマ")
    progress_messages.extend(emitter.get_messages())
    return {"common_themes": themes, "messages": progress_messages}


def _split_sections(text: str) -> list[list[str]]:
    heading_re = re.compile(r"^#{3,4}\s+(.*)$")
    sections: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if heading_re.match(line):
            if current:
                sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)
    return sections


def _parse_themes(text: str, ids: list[str]) -> list[CommonTheme]:
    themes: list[CommonTheme] = []
    heading_re = re.compile(r"^#{3,4}\s+(.*)$")

    idx = 0
    for sec in _split_sections(text):
        hm = heading_re.match(sec[0])
        if not hm:
            continue
        theme_name = hm.group(1).strip()
        if theme_name in ("共通テーマ", "テーマ", "テーマ名") or "特筆" in theme_name:
            continue
        body = "\n".join(sec[1:]).strip()
        if not body and theme_name:
            body = theme_name
        idx += 1
        desc = extract_section(body, "説明") or body
        supporting = ids
        quotes = extract_list_items(extract_section(body, "代表抜粋")) or extract_list_items(body)
        themes.append(
            CommonTheme(
                theme=theme_name or f"共通テーマ{idx}",
                description=desc,
                supporting_ids=supporting,
                example_quotes=quotes,
            )
        )
    return themes
