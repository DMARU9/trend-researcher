"""plan_search ノード（FR-003 対応）。X / YouTube 共通（プラットフォームで単数/複数を切替）。"""

from __future__ import annotations

import re

from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration
from trend_researcher.progress import NODE_PLAN_SEARCH, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState
from trend_researcher.tools.llm import build_model

#: 年号。`\b` は日本語（CJK も `\w`）と数字の間で境界にならないため、`2024年` の
#: 年号が残る。前後を「数字でない」条件で挟んで日本語に隣接する年号も拾う。
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)(?:\s*[のをはがにでとも])?")

#: 期間表現の数字。半角・全角・漢数字を許す（`3ヶ月` / `３ヶ月` / `三ヶ月` を同じ扱いにする）。
_DIGITS = r"[0-9０-９一二三四五六七八九十]+"
#: 期間表現（数字＋月/年・半年・最近 等）と、その直後に残る助詞（`最近のAI` → `AI`）。
_PERIOD_RE = re.compile(
    rf"(?:{_DIGITS}\s*[ヶカ]?月|(?:{_DIGITS})?\s*年|半年|本年|今年|最近|以内|以降|から|より)"
    r"(?:\s*[のをはがにでとも])?"
)

#: 除去後に残る括弧・引用符・空白（`（2024年）` が空クエリになるようにする）。
_STRIP_CHARS = "\"'（）() \t"


def _clean_query(query: str) -> str:
    """生成クエリから年号・期間表現（とその直後の助詞）を除去し、広く検索できるようにする。"""
    q = _YEAR_RE.sub("", query)
    q = _PERIOD_RE.sub("", q)
    q = re.sub(r"\s{2,}", " ", q).strip().strip(_STRIP_CHARS)
    return q


def plan_search(state: AgentState, config: RunnableConfig) -> dict:
    """指示から検索クエリを生成する（X: 複数 / YouTube: 単一）。"""
    configurable = Configuration.from_runnable_config(config)
    # platform: ユーザー入力（state）> Configuration。以降 instruction.platform で上書きするため str として扱う
    platform: str = state.get("platform") or configurable.platform
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

    model = build_model("research", provider.env_prefix)
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
    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()
    return {"search_queries": queries, "messages": progress_messages}
