"""nodes/search.py が返す `messages`（進捗行と検索クエリ行）の契約を固定する。

対象は `nodes/search.py` の**戻り値**。この契約は統合テスト（graph 経由）では
検証できない: LangGraph の `add_messages` が同一オブジェクトの id で畳み込む
ため、ノードが「開始」を二重に載せてもグラフの state では 1 行に潰れる
（`tasks.md` の T028「観測点」表 / 変異探針（3）で実測済み）。したがって
ノード単体の戻り値を直接見る以外に検出手段がない（LAYOUT-006-4）。

検索境界（`providers.x.search_tweets`）は conftest のフィクスチャで差し替える
（LAYOUT-003-3）。LLM は呼ばない。
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from trend_researcher.models import ResearchInstruction
from trend_researcher.nodes.search import search_node


def _config(**configurable: Any) -> RunnableConfig:
    return {"configurable": configurable}


def _instruction(**overrides: Any) -> ResearchInstruction:
    base: dict[str, Any] = {
        "raw_text": "オタクの活動における困りごとを調査したい",
        "platform": "x",
        "topic": "オタクの困りごと",
    }
    base.update(overrides)
    return ResearchInstruction(**base)


def _state(queries: list[str] | None = None, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "instruction": _instruction(),
        "search_queries": ["オタク 困りごと", "推し活 大変"] if queries is None else queries,
    }
    base.update(overrides)
    return base


# --- 戻り値の契約（LAYOUT-006-3 / LAYOUT-006-4） ----------------------------


def test_progress_messages_report_start_then_finish(fake_x_search: Any) -> None:
    """戻り値は [開始, 完了, 検索クエリ行] の 3 件で、開始が重複しない。

    末尾の `progress_messages = emitter.get_messages()` を
    `progress_messages.extend(emitter.get_messages())` に戻すと、開始が 2 件に
    なってこの断言が落ちる（T047 の変異探針で実測）。

    候補数は「クエリごとに返る 3 件（conftest の既定応答）を id で重複除去した
    3 件」。詳細行の件数まで固定するのは、進捗行が件数を報告する契約だからである。
    """
    out = search_node(_state(), _config())

    assert [m.content for m in out["messages"]] == [
        "[3/7] search ... 開始",
        "[3/7] search ... 完了（3 件を選定）",
        "検索クエリ: オタク 困りごと, 推し活 大変",
    ]


def test_progress_messages_report_zero_candidates(fake_x_search: Any) -> None:
    """候補 0 件でも戻り値は [開始, 完了, 検索クエリ行] の 3 件のまま。

    検索 0 件は後続をスキップする縮退経路（FR-007）であり、`emitter` に
    エラー行が足される経路ではない。ゼロ件でも行数が増減しないことを固定する。
    """
    fake_x_search.returns([])

    out = search_node(_state(queries=[]), _config())

    assert [m.content for m in out["messages"]] == [
        "[3/7] search ... 開始",
        "[3/7] search ... 完了（0 件を選定）",
        "検索クエリ: ",
    ]
