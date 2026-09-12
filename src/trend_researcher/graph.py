"""LangGraph グラフ構築と実行エントリ（FR-001/SC-005 対応、X / YouTube 共通）。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from langgraph.graph import END, StateGraph

from trend_researcher.models import ResearchReport
from trend_researcher.nodes.analyze_content import analyze_content
from trend_researcher.nodes.compile_report import (
    compile_report,
    render_json,
    render_markdown,
)
from trend_researcher.nodes.extract_common import extract_common
from trend_researcher.nodes.fetch import fetch_node
from trend_researcher.nodes.parse_instruction import parse_instruction
from trend_researcher.nodes.plan_search import plan_search
from trend_researcher.nodes.search import search_node
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentInputState, AgentState

EXECUTION_TIMEOUT = timedelta(minutes=100)


def build_graph() -> Any:
    """単一検索の StateGraph を構築する（プラットフォーム共通）。"""
    graph = StateGraph(AgentState, input_schema=AgentInputState)
    graph.add_node("parse_instruction", parse_instruction)
    graph.add_node("plan_search", plan_search)
    graph.add_node("search", search_node)
    graph.add_node("fetch", fetch_node)
    graph.add_node("analyze_content", analyze_content)
    graph.add_node("extract_common", extract_common)
    graph.add_node("compile_report", compile_report)

    graph.set_entry_point("parse_instruction")
    graph.add_edge("parse_instruction", "plan_search")
    graph.add_edge("plan_search", "search")
    graph.add_conditional_edges(
        "search",
        _route_after_search,
        {"skip": "compile_report", "continue": "fetch"},
    )
    graph.add_edge("fetch", "analyze_content")
    graph.add_edge("analyze_content", "extract_common")
    graph.add_edge("extract_common", "compile_report")
    graph.add_edge("compile_report", END)

    return graph.compile()


def _route_after_search(state: dict) -> str:
    candidates = state.get("candidates", [])
    return "skip" if not candidates else "continue"


# LangGraph Studio エントリポイント
trend_researcher = build_graph()


def render_report(report: "ResearchReport") -> str:
    """レポートを指示された形式（既定 markdown）で描画。"""
    from trend_researcher.models import ResearchReport as _RR

    fmt = report.instruction.output.format
    if fmt == "json":
        return render_json(report)
    provider = get_provider(report.instruction.platform)
    return render_markdown(report, provider)
