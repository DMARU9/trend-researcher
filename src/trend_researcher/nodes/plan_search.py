"""plan_search ノード（FR-003 対応）。X / YouTube 共通（プラットフォームで単数/複数を切替）。"""

from __future__ import annotations

import re

from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration
from trend_researcher.progress import NODE_PLAN_SEARCH, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState
from trend_researcher.tools.llm import build_model

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_PERIOD_RE = re.compile(r"(半年|三?ヶ?月|1?年|本年|今年|最近|以内|以降|から|より)\s*")


def _clean_query(query: str) -> str:
    """生成クエリから年号・期間表現を除去し、広く検索できるようにする。"""
    q = _YEAR_RE.sub("", query)
    q = _PERIOD_RE.sub("", q)
    q = re.sub(r"\s{2,}", " ", q).strip().strip('"').strip("'")
    return q


def plan_search(state: AgentState, config: RunnableConfig) -> dict:
    """指示から検索クエリを生成する（X: 複数 / YouTube: 単一）。"""
    configurable = Configuration.from_runnable_config(config)
    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    emitter = make_emitter()
    emitter.emit(2, NODE_PLAN_SEARCH, "開始", detail="LLM が検索クエリを生成中")
    progress_messages = emitter.get_messages()

    instruction = state["instruction"]
    search_topic = re.sub(r"[（(].*?[）)]", "", instruction.topic or instruction.raw_text)
    search_topic = _PERIOD_RE.sub("", search_topic).strip() or (instruction.topic or instruction.raw_text)

    published_after = instruction.published_after
    if published_after is not None:
        date_hint = (
            f"\n※投稿日フィルタ（{published_after.date()} 以降）が別途適用されます。"
            "そのため、古い年号を付けずに最新の投稿も含めて広く検索してください。"
        )
    else:
        date_hint = ""

    model = build_model("research")
    prompt = provider.plan_search_prompt.format(topic=search_topic, date_hint=date_hint)
    result = model.invoke(prompt)
    raw = result.content if hasattr(result, "content") else str(result)

    queries: list[str] = []
    for line in raw.splitlines():
        q = _clean_query(line)
        if q:
            queries.append(q)

    # クエリ数のハード上限（X のみ適用）。LLM が 5 件を守らなくても安全に切り詰める。
    # YouTube は「単一クエリ」設計（呼び出し元で先頭1件のみ使用）のため制限しない。
    platform = (instruction.platform or "x").lower()
    if platform == "x" and len(queries) > 8:
        queries = queries[:8]

    emitter.emit(2, NODE_PLAN_SEARCH, "完了", detail=f'クエリ {len(queries)} 件: {", ".join(queries)}')
    progress_messages.extend(emitter.get_messages())
    return {"search_queries": queries, "messages": progress_messages}
