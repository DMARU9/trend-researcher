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
from unittest import mock

from langchain_core.runnables import RunnableConfig

from trend_researcher.models import Candidate, Context, Failure, ResearchInstruction
from trend_researcher.nodes.fetch import fetch_node
from trend_researcher.tools.transcript import Transcript


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


# --- US4: 追加文脈の取得失敗（FR-022 / FR-021 / 契約 §3） -------------------


def _contexts_missing_the_first(candidates: list[Candidate]) -> list[Context]:
    """1 件目だけ空の文脈を返す（追加文脈が取れなかった候補を作る）。"""
    return [
        Context(id=c.id, text="" if idx == 0 else f"{c.text} のスレッド")
        for idx, c in enumerate(candidates)
    ]


def test_unavailable_context_is_recorded_as_a_failure() -> None:
    """追加文脈が取れなかった候補は `Failure(kind="context")` として残る（FR-022 / FR-021）。

    取得できた候補の解析は続く（`contexts` は両方返る）。無言で消さないことが
    この層の役目で、解析を止めないことは `analyze_content` 側の契約。
    """
    candidates = [_candidate(1), _candidate(2)]

    with mock.patch(
        "trend_researcher.providers.x.fetch_threads",
        new=lambda cands, **kw: _contexts_missing_the_first(cands),
    ):
        out = fetch_node(_state(candidates=candidates), _config())

    (failure,) = out["failures"]
    assert failure.kind == "context"
    assert failure.id == "t1"
    # 例外が伴わない失敗（provider の内側で握られて空の Context になる）なので、
    # 例外型名ではなく失敗の種類を示す固定の名前が入る
    assert failure.error_type == "MissingContext"
    assert "追加文脈" in failure.message
    assert [c.id for c in out["contexts"]] == ["t1", "t2"]


def test_a_second_context_failure_is_appended_to_the_existing_records() -> None:
    """既存の `failures`（前の段の記録）を上書きせず追記する（後勝ちにしない）。"""
    candidates = [_candidate(1)]

    with mock.patch(
        "trend_researcher.providers.x.fetch_threads",
        new=lambda cands, **kw: _contexts_missing_the_first(cands),
    ):
        out = fetch_node(
            _state(candidates=candidates, failures=[Failure(kind="analysis", id="old", error_type="RuntimeError", message="前の段")]),
            _config(),
        )

    assert [f.id for f in out["failures"]] == ["old", "t1"]


def test_no_context_failure_when_every_context_has_content(fake_x_threads: Any) -> None:
    """追加文脈が取れていれば `failures` は増えない（既定の入力の出力を変えない）。"""
    out = fetch_node(_state(), _config())

    assert out["failures"] == []
    assert out["notes"] == []


def test_the_existing_note_wording_is_kept_when_the_batch_fetch_fails() -> None:
    """一括取得の失敗は既存の `notes` の文言のまま（変更禁止。契約 §7-1 / FR-022）。

    このとき `contexts` は候補の本文で代替される（非空）。したがって「追加文脈が
    1 つも取れなかった候補」は生まれず、`failures` には載せない（既存の `notes`
    が失敗を伝えているため無言の欠落にはならない）。
    """

    def _boom(cands: list[Candidate], **kw: Any) -> list[Context]:
        raise RuntimeError("X API が失敗しました")

    with mock.patch("trend_researcher.providers.x.fetch_threads", new=_boom):
        out = fetch_node(_state(), _config())

    assert out["notes"] == ["スレッド取得に失敗しました（本文のみで解析）: X API が失敗しました"]
    assert out["failures"] == []
    assert [c.text for c in out["contexts"]] == ["本文1", "本文2"]


def test_a_missing_transcript_is_recorded_as_a_context_failure() -> None:
    """YouTube 側でも同じ規則で記録する（判定は provider に依存しない）。"""
    videos = [
        Candidate(platform="youtube", id=f"v{i}", title=f"動画{i}", url=f"u{i}", relevance_rank=i)
        for i in (1, 2)
    ]

    def _transcript(video_id: str, language: str = "ja") -> Transcript:
        return Transcript(video_id=video_id, language=language, text="" if video_id == "v1" else "字幕")

    with mock.patch("trend_researcher.providers.youtube.fetch_transcript", new=_transcript):
        out = fetch_node(
            _state(candidates=videos, platform="youtube"), _config(platform="youtube")
        )

    (failure,) = out["failures"]
    assert (failure.kind, failure.id) == ("context", "v1")
    assert out["notes"] == ["字幕取得不可: 動画1 (v1) - メタデータのみで解析"]
