"""nodes/fetch.py が返す `messages`（進捗行）の契約を固定する。

対象は `nodes/fetch.py` の**戻り値**。この契約は統合テスト（graph 経由）では
検証できない: LangGraph の `add_messages` が同一オブジェクトの id で畳み込む
ため、ノードが「開始」を二重に載せてもグラフの state では 1 行に潰れる
（`tasks.md` の T028「観測点」表 / 変異探針（3）で実測済み）。したがって
ノード単体の戻り値を直接見る以外に検出手段がない（LAYOUT-006-4）。

付加情報の取得境界（`providers.x.fetch_threads`）は conftest のフィクスチャで
差し替える（LAYOUT-003-3）。LLM は呼ばない。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig

from trend_researcher.models import Candidate, ResearchInstruction
from trend_researcher.nodes.fetch import fetch_node


def _config(**configurable: Any) -> RunnableConfig:
    return {"configurable": configurable}


def _candidate(idx: int) -> Candidate:
    return Candidate(
        platform="x",
        id=f"t{idx}",
        text=f"本文{idx}",
        url=f"https://example.test/{idx}",
        author_handle=f"user{idx}",
        author_name=f"ユーザー{idx}",
        like_count=10 * idx,
        published_at=datetime(2026, 1, idx, 9, 0, tzinfo=UTC),
        relevance_rank=idx,
    )


def _instruction(**overrides: Any) -> ResearchInstruction:
    base: dict[str, Any] = {
        "raw_text": "オタクの活動における困りごとを調査したい",
        "platform": "x",
        "topic": "オタクの困りごと",
    }
    base.update(overrides)
    return ResearchInstruction(**base)


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "instruction": _instruction(),
        "candidates": [_candidate(1), _candidate(2)],
        "notes": [],
    }
    base.update(overrides)
    return base


# --- 戻り値の契約（LAYOUT-006-3 / LAYOUT-006-4） ----------------------------


def test_progress_messages_report_start_then_finish(fake_x_threads: Any) -> None:
    """戻り値は [開始, 完了] の 2 件で、開始が重複しない。

    末尾の `progress_messages = emitter.get_messages()` を
    `progress_messages.extend(emitter.get_messages())` に戻すと、開始が 2 件に
    なってこの断言が落ちる（T047 の変異探針で実測）。

    詳細行は「コンテキスト取得 <件数> 件（追加文脈なし <件数> 件）」の二重括弧
    まで含めて固定する。付加情報が空の場合に `no_context` が増える経路は
    `test_full_flow.py` の縮退テストが持つため、ここでは通常経路の形だけを固定する。
    """
    out = fetch_node(_state(), _config())

    assert [m.content for m in out["messages"]] == [
        "[4/7] fetch ... 開始",
        "[4/7] fetch ... 完了（コンテキスト取得 2 件（追加文脈なし 0 件））",
    ]


def test_progress_messages_report_start_then_finish_without_candidates(fake_x_threads: Any) -> None:
    """候補 0 件でも戻り値は [開始, 完了] の 2 件のまま（行数が増減しない）。"""
    out = fetch_node(_state(candidates=[]), _config())

    assert [m.content for m in out["messages"]] == [
        "[4/7] fetch ... 開始",
        "[4/7] fetch ... 完了（コンテキスト取得 0 件（追加文脈なし 0 件））",
    ]
