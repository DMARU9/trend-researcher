"""fetch ノード（FR-006 対応、X: スレッド/リプライ / YouTube: 字幕、共通）。"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from trend_researcher.config import Config
from trend_researcher.configuration import Configuration
from trend_researcher.progress import NODE_FETCH, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState


def fetch_node(state: AgentState, config: RunnableConfig) -> dict:
    """provider.fetch_contexts を呼び出し、要約用ソースを取得する。"""
    configurable = Configuration.from_runnable_config(config)
    emitter = make_emitter()
    emitter.emit(4, NODE_FETCH, "開始")
    progress_messages = emitter.get_messages()

    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    cfg = Config.load(platform=platform)
    candidates = state.get("candidates", [])
    instruction = state.get("instruction")
    sort_by = (instruction.sort_by if instruction else None) or "relevance"
    contexts, notes = provider.fetch_contexts(candidates, cfg)

    # tweet_details で正確な like_count 等が確定したので、fetch 後に並び替える
    if candidates:
        candidates = provider.resort(candidates, sort_by)

    notes = list(state.get("notes", [])) + notes
    no_context = sum(1 for c in contexts if not c.text.strip() and not c.thread_text and not c.replies)
    emitter.emit(
        4,
        NODE_FETCH,
        "完了",
        detail=f"コンテキスト取得 {len(contexts)} 件（追加文脈なし {no_context} 件）",
    )
    progress_messages.extend(emitter.get_messages())
    return {"candidates": candidates, "contexts": contexts, "notes": notes, "messages": progress_messages}
