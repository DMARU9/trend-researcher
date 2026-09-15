"""LangGraph State 定義（X / YouTube 共通グラフ遷移に対応）。"""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, NotRequired

from langgraph.graph import MessagesState

from trend_researcher.models import (
    AnalysisFinding,
    Candidate,
    CommonTheme,
    CompressedSource,
    Context,
    Degradation,
    Failure,
    ModelUsage,
    OutputFormat,
    ResearchInstruction,
    ResearchReport,
)


class AgentInputState(MessagesState):
    """グラフの入力ステート。LangGraph Studio UI で表示される入力欄。

    TypedDict のキーに既定値は書けない（mypy `misc`）。入力の既定はどちらも
    `Configuration` が持っており（`platform` は未指定＝空文字で登録の先頭に解決、
    `max_results` は `default=5`）、各ノードは `state.get(...) or configurable....` で
    フォールバックするため、ここでは「省略可能」であることだけを表現する。
    """

    platform: NotRequired[str]
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

    platform: str
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
    sort_by: str
    transcript_language: str
    cache_dir: str | None

    # --- 実行中の観測（data-model §2.1。レポートには含めない。D-3） -----------
    # 圧縮した対象の記録（`analyze_content` が設定する）
    compressed: list[CompressedSource]
    # 縮退の段の記録（段ごとに追記される）
    degradations: list[Degradation]
    # 部分失敗（解析・追加文脈の取得）の記録
    failures: list[Failure]
    # LLM 呼び出し 1 回につき 1 要素。**並列ノードの結果を連結**する
    usage: Annotated[list[ModelUsage], operator.add]
