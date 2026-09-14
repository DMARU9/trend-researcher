"""compile_report ノードの組み立てと描画契約を固定する（FR-009 / CLI-004-8）。

対象は `nodes/compile_report.py`。LLM は呼ばず、確定済みの state から
ResearchReport を組み立てる純粋な変換だけを検証する。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trend_researcher.models import (
    AnalysisFinding,
    Candidate,
    CommonTheme,
    Failure,
    ResearchInstruction,
    ResearchReport,
)
from trend_researcher.nodes import compile_report as compile_report_module
from trend_researcher.nodes.compile_report import compile_report
from trend_researcher.providers import get_provider
from trend_researcher.rendering import render_markdown


def _candidate(idx: int = 1, platform: str = "x", **overrides: Any) -> Candidate:
    """テスト用候補。counts は idx から決定的に導出する。"""
    base: dict[str, Any] = {
        "platform": platform,
        "id": f"t{idx}" if platform == "x" else f"v{idx}",
        "url": f"https://example.test/{idx}",
        "relevance_rank": idx,
    }
    if platform == "x":
        base.update(
            {
                "text": f"本文{idx}",
                "author_handle": f"user{idx}",
                "author_name": f"ユーザー{idx}",
                "author_followers": 100 * idx,
                "like_count": 10 * idx,
                "retweet_count": 2 * idx,
                "quote_count": idx,
                "published_at": datetime(2026, 1, idx, 9, 0, tzinfo=UTC),
            }
        )
    else:
        base.update(
            {
                "title": f"動画{idx}",
                "author_name": f"チャンネル{idx}",
                "view_count": 100 * idx,
                "published_at": datetime(2026, 1, idx, 9, 0, tzinfo=UTC),
            }
        )
    base.update(overrides)
    return Candidate(**base)


def _analysis(cid: str, **overrides: Any) -> AnalysisFinding:
    base: dict[str, Any] = {"id": cid, "summary": f"要約{cid}"}
    base.update(overrides)
    return AnalysisFinding(**base)


def _instruction(platform: str = "x", **overrides: Any) -> ResearchInstruction:
    base: dict[str, Any] = {
        "raw_text": "AI の最新動向を調べて",
        "platform": platform,
        "topic": "AI 動向",
    }
    base.update(overrides)
    return ResearchInstruction(**base)


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "messages": [],
        "instruction": _instruction(),
        "candidates": [],
        "analyses": [],
        "common_themes": [],
        "notes": [],
    }
    base.update(overrides)
    return base


def _config(
    platform: str = "x", cache_dir: str | None = None, **options: Any
) -> dict[str, Any]:
    return {"configurable": {"platform": platform, "cache_dir": cache_dir, **options}}


def _report(platform: str = "x", **overrides: Any) -> ResearchReport:
    base: dict[str, Any] = {
        "instruction": _instruction(platform),
        "candidates": [_candidate(1, platform)],
        "analyses": [_analysis(_candidate(1, platform).id)],
        "common_themes": [],
        "sources": ["https://example.test/1"],
        "notes": [],
    }
    base.update(overrides)
    return ResearchReport(**base)


def _markdown(report: ResearchReport) -> str:
    return render_markdown(report, get_provider(report.instruction.platform))


# ---------------------------------------------------------------------------
# レポート組み立て
# ---------------------------------------------------------------------------


def test_compile_report_returns_report_with_state_contents() -> None:
    c1, c2 = _candidate(1), _candidate(2)
    a1 = _analysis("t1")
    theme = CommonTheme(theme="A", description="説明", supporting_ids=["t1"], example_quotes=["引用"])
    state = _state(candidates=[c1, c2], analyses=[a1], common_themes=[theme])

    result = compile_report(state, _config())

    report = result["report"]
    assert isinstance(report, ResearchReport)
    assert report.instruction is state["instruction"]
    assert [c.id for c in report.candidates] == ["t1", "t2"]
    assert [a.id for a in report.analyses] == ["t1"]
    assert [t.theme for t in report.common_themes] == ["A"]
    assert report.sources == ["https://example.test/1", "https://example.test/2"]


def test_compile_report_excludes_candidates_without_url_from_sources() -> None:
    with_url = _candidate(1)
    without_url = _candidate(2, url="")
    state = _state(candidates=[with_url, without_url])

    report = compile_report(state, _config())["report"]

    assert report.sources == ["https://example.test/1"]
    # 候補自体はレポートに残る（出典だけが URL なしを除外する）
    assert [c.id for c in report.candidates] == ["t1", "t2"]


def test_compile_report_copies_state_notes_without_mutating_state() -> None:
    state = _state(notes=["既存メモ"])

    report = compile_report(state, _config())["report"]

    assert report.notes[0] == "既存メモ"
    assert state["notes"] == ["既存メモ"]  # ノードが state のリストを破壊しない


# ---------------------------------------------------------------------------
# 備考（選定基準 / 投稿日フィルタ / 候補 0 件）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sort_by", "expected"),
    [("relevance", "いいね数の少ない順"), ("likes", "いいね数の多い順"), ("", "いいね数の少ない順")],
)
def test_notes_record_x_selection_criterion(sort_by: str, expected: str) -> None:
    """空文字の sort_by は relevance にフォールバックする。"""
    instruction = _instruction().model_copy(update={"sort_by": sort_by})
    report = compile_report(_state(instruction=instruction), _config())["report"]

    assert f"選定基準: 検索結果から{expected}に上位 N 件を採用" in report.notes


def test_notes_record_youtube_selection_criterion() -> None:
    state = _state(platform="youtube", instruction=_instruction("youtube"))

    report = compile_report(state, _config()) ["report"]

    assert "選定基準: 検索結果の関連度順に上位 N 件を採用" in report.notes
    assert not any("いいね数の少ない順" in n for n in report.notes)


def test_notes_follow_state_platform_not_instruction_platform() -> None:
    """備考のプラットフォーム判定は state / config の platform で行われる。

    instruction.platform は見ない（CLI は全経路で同じ値を渡すため通常は一致する）。
    一方 render_markdown は instruction.platform で表を描くため、両者が食い違うと
    備考と表がずれる。ここでは「備考側の入力は state/config」という現状を固定する。
    """
    state = _state(platform="x", instruction=_instruction("youtube"))

    report = compile_report(state, _config("x"))["report"]

    assert report.instruction.platform == "youtube"
    assert any("いいね数の少ない順" in n for n in report.notes)


def test_notes_record_published_after_filter() -> None:
    instruction = _instruction().model_copy(
        update={"published_after": datetime(2026, 1, 5, 12, 0, tzinfo=UTC)}
    )
    report = compile_report(_state(instruction=instruction), _config())["report"]

    assert "投稿日フィルタ: 2026-01-05 以降に公開された投稿を対象" in report.notes


def test_notes_omit_published_after_filter_when_unset() -> None:
    report = compile_report(_state(), _config())["report"]

    assert not any("投稿日フィルタ" in n for n in report.notes)


@pytest.mark.parametrize(
    ("platform", "subject"),
    [("x", "ツイート"), ("youtube", "動画")],
)
def test_notes_record_empty_result_with_platform_specific_subject(platform: str, subject: str) -> None:
    state = _state(instruction=_instruction(platform))

    report = compile_report(state, _config(platform))["report"]

    assert report.candidates == []
    assert any(f"該当する{subject}が見つかりませんでした" in n for n in report.notes)


def test_notes_do_not_mention_empty_result_when_candidates_exist() -> None:
    state = _state(candidates=[_candidate(1)])

    report = compile_report(state, _config())["report"]

    assert not any("見つかりませんでした" in n for n in report.notes)


def test_state_platform_overrides_config_platform() -> None:
    """state の platform が優先される（config はフォールバック）。"""
    state = _state(platform="youtube", instruction=_instruction("x"))

    report = compile_report(state, _config("x"))["report"]

    assert report.instruction.platform == "x"
    assert "選定基準: 検索結果の関連度順に上位 N 件を採用" in report.notes


def test_config_platform_used_when_state_platform_is_absent() -> None:
    state = _state(instruction=_instruction("youtube"))

    report = compile_report(state, _config("youtube"))["report"]

    assert "選定基準: 検索結果の関連度順に上位 N 件を採用" in report.notes


# ---------------------------------------------------------------------------
# キャッシュ書き込み（成功 / 失敗時の縮退）
# ---------------------------------------------------------------------------


def test_report_is_persisted_when_cache_dir_is_set(tmp_path: Path) -> None:
    state = _state(candidates=[_candidate(1)], cache_dir=str(tmp_path))

    report = compile_report(state, _config())["report"]

    written = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert written == report.model_dump(mode="json")


def test_no_cache_write_when_cache_dir_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        compile_report_module, "write_json", lambda *a, **k: calls.append((a, k))
    )

    compile_report(_state(cache_dir=None), _config())

    assert calls == []


def test_cache_write_failure_is_reported_and_execution_continues(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom(*_a: Any, **_k: Any) -> Path:
        raise OSError("ディスク満杯")

    monkeypatch.setattr(compile_report_module, "write_json", _boom)
    state = _state(candidates=[_candidate(1)], cache_dir="/tmp/does-not-matter")

    result = compile_report(state, _config())

    report = result["report"]
    assert isinstance(report, ResearchReport)
    assert len(report.candidates) == 1  # 縮退してもレポートは返る
    assert "キャッシュ書き込み失敗: ディスク満杯" in capsys.readouterr().err
    assert any("キャッシュ書き込み失敗: ディスク満杯" in m.content for m in result["messages"])


def test_cache_write_failure_does_not_add_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    """書き込み失敗は進捗メッセージとして表面化し、備考（notes）は選定基準のみ。"""
    monkeypatch.setattr(
        compile_report_module, "write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("x"))
    )

    report = compile_report(_state(cache_dir="/tmp/does-not-matter"), _config())["report"]

    assert not any("キャッシュ" in n for n in report.notes)


# ---------------------------------------------------------------------------
# US4: 失敗の可視化（FR-021 / FR-023 / 契約 §3・§5）
# ---------------------------------------------------------------------------


def _failure(idx: int = 1, kind: str = "analysis") -> Failure:
    return Failure(
        kind=kind,
        id=f"t{idx}",
        error_type="RuntimeError",
        message=f"{idx} 件目の解析に失敗しました",
    )


def test_partial_failure_does_not_add_a_report_note() -> None:
    """一部の失敗は `report.notes` に足さない（既定の出力を変えない。FR-035 / FR-021）。"""
    state = _state(
        candidates=[_candidate(1), _candidate(2)],
        analyses=[_analysis("t1")],
        failures=[_failure(2)],
    )

    report = compile_report(state, _config())["report"]

    assert not any("解析できなかった" in n or "すべて失敗" in n for n in report.notes)


def test_all_candidates_failing_adds_exactly_one_note() -> None:
    """全件失敗のときだけ「解析 0 件（すべて失敗: N 件）」を 1 行足す（US4 シナリオ 3）。"""
    state = _state(
        candidates=[_candidate(i) for i in (1, 2, 3)],
        analyses=[],
        failures=[_failure(i) for i in (1, 2, 3)],
    )

    report = compile_report(state, _config())["report"]

    lines = [n for n in report.notes if "すべて失敗" in n]
    assert lines == ["解析 0 件（すべて失敗: 3 件）"]


def test_the_all_failed_note_is_not_added_when_there_are_no_candidates() -> None:
    """候補 0 件は「全件失敗」ではない（既存の該当なしの行だけが載る）。"""
    report = compile_report(_state(candidates=[], analyses=[]), _config())["report"]

    assert not any("すべて失敗" in n for n in report.notes)
    assert any("見つかりませんでした" in n for n in report.notes)


def test_failures_json_is_written_only_when_intermediate_is_enabled(tmp_path: Path) -> None:
    """`include_intermediate` が真のときだけ `cache/failures.json` を書く（契約 §5）。"""
    state = _state(
        candidates=[_candidate(1), _candidate(2)],
        analyses=[_analysis("t1")],
        failures=[_failure(2)],
        cache_dir=str(tmp_path),
    )

    compile_report(state, _config())
    assert not (tmp_path / "failures.json").exists()

    compile_report(state, _config(include_intermediate=True))
    written = json.loads((tmp_path / "failures.json").read_text(encoding="utf-8"))

    assert written == [_failure(2).model_dump(mode="json")]


def test_no_failures_json_without_a_cache_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        compile_report_module, "write_json", lambda *a, **k: calls.append((a, k))
    )

    compile_report(
        _state(candidates=[_candidate(1)], failures=[_failure(1)], cache_dir=None),
        _config(include_intermediate=True),
    )

    assert calls == []


# ---------------------------------------------------------------------------
# 進捗メッセージ
# ---------------------------------------------------------------------------


def test_progress_messages_end_with_summary_and_rendered_markdown() -> None:
    candidates = [_candidate(1), _candidate(2)]
    themes = [CommonTheme(theme="A", description="説明")]
    state = _state(candidates=candidates, common_themes=themes)

    result = compile_report(state, _config())

    messages = result["messages"]
    # 先頭は「開始 → 完了」の順で重複しない。`any(...)` で探す形では、開始行が
    # 二重に載っても（`progress_messages.extend(...)` への差し戻し）気づけない（T047）。
    assert [m.content for m in messages[:2]] == [
        "[7/7] compile_report ... 開始",
        "[7/7] compile_report ... 完了",
    ]
    # 中間に余計な行が入らないことまで固定する（開始の重複や書き込み失敗行の混入）。
    assert len(messages) == 4
    assert messages[-2].content == "レポート完了: 2 件の候補を分析し、1 件の共通テーマを抽出しました。"
    assert messages[-1].content == _markdown(result["report"])
