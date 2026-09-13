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
    cfg = Config.load(env_prefix=provider.env_prefix)
    # 件数は parse_instruction が FR-011 の優先順位（state > Configuration > 自然言語 > LLM）
    # で解決済みの値を使う。ここで Configuration を再参照して `!= 5` のセンチネルで
    # 分岐すると、state と Configuration が食い違う入力で優先順位が逆転し、
    # 報告される件数（instruction.max_results）と実際に取得する件数がずれる
    # （T049 の実測: state=30 / configurable=20 で provider には 20 が渡っていた）。
    # `or 5` は 0 など falsy な件数を既定へ戻す既存の扱い（`__main__._print_summary` と同一）。
    max_results = instruction.max_results or 5

    candidates = provider.search(
        queries=queries,
        max_results=max_results,
        published_after=instruction.published_after,
        sort_by=instruction.sort_by or "relevance",
        config=cfg,
    )

    emitter.emit(3, NODE_SEARCH, "完了", detail=f"{len(candidates)} 件を選定")
    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()
    # 検索クエリをユーザーに表示
    progress_messages.append(AIMessage(content=f"検索クエリ: {', '.join(queries)}"))
    return {"candidates": candidates, "published_after": instruction.published_after, "messages": progress_messages}
