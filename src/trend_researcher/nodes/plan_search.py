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


def _parse_queries(raw: str) -> list[str]:
    """LLM の応答を行分割してクエリのリストにする（生成と点検で同じ経路を使う）。"""
    queries: list[str] = []
    for line in raw.splitlines():
        query = _clean_query(line)
        if query:
            queries.append(query)
    return queries


def _dedupe(queries: list[str]) -> list[str]:
    """正規化後の重複を除く。先に現れたものを残す（契約 §1 の規則 4）。"""
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            unique.append(query)
    return unique


def _apply_review(
    generated: list[str], reviewed: list[str], limit: int | None
) -> list[str]:
    """点検の結果を生成結果へ統合する（契約 §1 の規則 1〜5。この順序が契約）。

    - 規則 1 / 5: どちらかが 0 件なら生成結果のまま（点検しても件数を増やさない）
    - 規則 4: 点検の出力から重複を除く
    - 規則 2: 生成結果の件数を下回らないよう**生成結果から**補充する（創作はしない）
    - 規則 3: 上限（`max_search_queries`）で切り詰める。`None` は無制限
    """
    if not generated or not reviewed:
        merged = list(generated)
    else:
        merged = _dedupe(reviewed)
        for query in generated:
            if len(merged) >= len(generated):
                break
            if query not in merged:
                merged.append(query)
    if limit is not None:
        merged = merged[:limit]
    return merged


def plan_search(state: AgentState, config: RunnableConfig) -> dict:
    """指示から検索クエリを生成し、必要なら 1 回だけ自己点検する（X: 複数 / YouTube: 単一）。"""
    configurable = Configuration.from_runnable_config(config)
    # platform: ユーザー入力（state）> Configuration。以降 instruction.platform で上書きするため str として扱う
    platform: str = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    emitter = make_emitter()
    emitter.emit(NODE_PLAN_SEARCH, "開始", detail="LLM が検索クエリを生成中")
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

    queries = _parse_queries(raw)

    # クエリ数のハード上限（上限を持つプラットフォームにのみ適用）。LLM が 5 件を
    # 守らなくても安全に切り詰める。上限が `None` のプラットフォームは「単一クエリ」
    # 設計（呼び出し元で先頭1件のみ使用）を含め制限しない。上限値は provider が持つ。
    limit = provider.max_search_queries
    if limit is not None and len(queries) > limit:
        queries = queries[:limit]

    # 生成後の自己点検（US7 / FR-049〜053）。生成の**後**に 1 回だけ呼び、反復しない。
    if configurable.self_review:
        try:
            review_prompt = provider.review_search_prompt.format(
                topic=search_topic, queries="\n".join(queries)
            )
            reviewed = model.invoke(review_prompt)
            reviewed_raw = reviewed.content if hasattr(reviewed, "content") else str(reviewed)
            queries = _apply_review(queries, _parse_queries(reviewed_raw), limit)
        except Exception as exc:  # noqa: BLE001 - 点検の失敗は生成結果で継続する（FR-051）
            reason = str(exc).strip() or type(exc).__name__
            emitter.note(
                f"検索クエリの点検に失敗（{type(exc).__name__}: {reason}）。"
                "生成したクエリで継続します。"
            )

    emitter.emit(NODE_PLAN_SEARCH, "完了", detail=f'クエリ {len(queries)} 件: {", ".join(queries)}')
    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()
    return {"search_queries": queries, "messages": progress_messages}
