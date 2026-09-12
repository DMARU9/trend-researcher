"""LangGraph State 定義（X / YouTube 共通グラフ遷移に対応）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from langgraph.graph import MessagesState

from trend_researcher.models import (
    AnalysisFinding,
    Candidate,
    CommonTheme,
    Context,
    OutputFormat,
    ResearchInstruction,
    ResearchReport,
)


class AgentInputState(MessagesState):
    """グラフの入力ステート。LangGraph Studio UI で表示される入力欄。"""

    platform: Literal["x", "youtube"] = "x"
    max_results: int = 5


class AgentState(MessagesState):
    """リサーチ実行中の状態。

    parse_instruction → plan_search → search → fetch
    → analyze_content → extract_common → compile_report の各ノード間で受け渡す。
    messages フィールドはユーザー入力・AI応答・進捗メッセージを格納する。

    provider / config はランタイムオブジェクトなのでステートに持たせず、
    各ノードが Configuration から都度生成する。
    """

    instruction: ResearchInstruction
    search_query: str
    search_queries: list[str]
    published_after: datetime | None
    max_results: int
    output_format: OutputFormat
    candidates: list[Candidate]
    contexts: list[Context]
    analyses: list[AnalysisFinding]
    common_themes: list[CommonTheme]
    report: ResearchReport
    notes: list[str]
    use_trends: bool
    sort_by: str
    transcript_language: str
    cache_dir: str | None
