"""LangGraph State 定義（X / YouTube 共通グラフ遷移に対応）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, NotRequired

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
    """グラフの入力ステート。LangGraph Studio UI で表示される入力欄。

    TypedDict のキーに既定値は書けない（mypy `misc`）。入力の既定はどちらも
    `Configuration` が持っており（`platform` は `default="x"`、`max_results` は
    `default=5`）、各ノードは `state.get(...) or configurable....` でフォールバック
    するため、ここでは「省略可能」であることだけを表現する。
    """

    platform: NotRequired[Literal["x", "youtube"]]
    max_results: NotRequired[int]


class AgentState(MessagesState):
    """リサーチ実行中の状態。

    parse_instruction → plan_search → search → fetch
    → analyze_content → extract_common → compile_report の各ノード間で受け渡す。
    messages フィールドはユーザー入力・AI応答・進捗メッセージを格納する。

    provider / config はランタイムオブジェクトなのでステートに持たせず、
    各ノードが Configuration から都度生成する。

    `platform` は入力ステート（`AgentInputState`）と `Configuration` の両方から
    供給され、各ノードが `state.get("platform") or configurable.platform` で解決する。
    ノードの引数型を `str` に確定させるため、実行ステート側にも宣言する。
    """

    platform: Literal["x", "youtube"]
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
