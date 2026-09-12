"""search ノード（FR-003/FR-004/FR-005 対応、X / YouTube 共通）。"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from trend_researcher.config import Config
from trend_researcher.configuration import Configuration
from trend_researcher.progress import NODE_SEARCH, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState


def search_node(state: AgentState, config: RunnableConfig) -> dict:
    """provider.search を呼び出し、上位 N 件の候補を選定する。"""
    configurable = Configuration.from_runnable_config(config)
    emitter = make_emitter()
    emitter.emit(3, NODE_SEARCH, "開始")
    progress_messages = emitter.get_messages()

    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    instruction = state["instruction"]
    queries = state.get("search_queries") or []
    cfg = Config.load(platform=platform)
    max_results = configurable.max_results if configurable.max_results != 5 else (instruction.max_results or 5)

    candidates = provider.search(
        queries=queries,
        max_results=max_results,
        published_after=instruction.published_after,
        sort_by=instruction.sort_by or "relevance",
        config=cfg,
    )

    emitter.emit(3, NODE_SEARCH, "完了", detail=f"{len(candidates)} 件を選定")
    progress_messages.extend(emitter.get_messages())
    # 検索クエリをユーザーに表示
    progress_messages.append(AIMessage(content=f"検索クエリ: {', '.join(queries)}"))
    return {"candidates": candidates, "published_after": instruction.published_after, "messages": progress_messages}
