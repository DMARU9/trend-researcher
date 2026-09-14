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
    CompressedSource,
    Context,
    Degradation,
    Failure,
    ModelUsage,
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


# ---------------------------------------------------------------------------
# US5: 状態の解放（FR-027 / R-8 / data-model §2.1・§4.3）
# ---------------------------------------------------------------------------

#: 既定で `cache/report.json` に載るキー（`ResearchReport` の全項目）。解放や中間
#: データの追加でここが増えたら、既定の出力が変わったことになる（SC-026）。
REPORT_JSON_KEYS = frozenset(
    {"instruction", "generated_at", "candidates", "analyses", "common_themes", "sources", "notes"}
)


def _context(cid: str, **overrides: Any) -> Context:
    base: dict[str, Any] = {
        "id": cid,
        "text": f"字幕{cid}",
        "thread_text": f"スレッド{cid}",
        "replies": [f"返信{cid}"],
    }
    base.update(overrides)
    return Context(**base)


def _released_state(tmp_path: Path | None = None) -> dict[str, Any]:
    """生データ（`text` / `thread_text` / `replies`）を持つ入力 state。"""
    state = _state(
        candidates=[_candidate(1, text="本文1"), _candidate(2, text="本文2")],
        contexts=[_context("t1"), _context("t2")],
        analyses=[_analysis("t1")],
        common_themes=[CommonTheme(theme="A", description="説明")],
    )
    if tmp_path is not None:
        state["cache_dir"] = str(tmp_path)
    return state


def test_raw_text_is_released_after_the_report_is_built() -> None:
    """生データの中身はレポート確定後に解放される（FR-027 / data-model §4.3）。

    解放の**順序**も同時に固定する。レポートは `Candidate` を参照するため、
    先に解放すると（`report.candidates` の中身が空になり）このテストが落ちる。
    """
    result = compile_report(_released_state(), _config())

    (context,) = result["contexts"][:1]
    assert context.id == "t1"  # レコードは残る（`contexts` を空にしない）
    assert (context.text, context.thread_text, context.replies) == ("", "", [])

    (candidate,) = result["candidates"][:1]
    assert candidate.id == "t1"
    assert candidate.text == ""
    assert candidate.url == "https://example.test/1"  # 参照（url）は解放しない

    # 解放はレポート組み立ての**後**（レポート側の中身は残る）
    assert [c.text for c in result["report"].candidates] == ["本文1", "本文2"]


def test_the_release_keeps_the_other_state_values() -> None:
    """解放しても `analyses` / `common_themes` / `report` は触らない（§2.1）。"""
    result = compile_report(_released_state(), _config())

    # 前提: 解放そのものは起きている（起きていなければこのテストは空虚になる）
    assert result["contexts"][0].text == ""
    assert result["candidates"][0].text == ""

    report = result["report"]
    assert [a.summary for a in report.analyses] == ["要約t1"]
    assert [t.theme for t in report.common_themes] == ["A"]
    assert len(report.candidates) == 2


def test_the_release_is_not_visible_in_the_written_report(tmp_path: Path) -> None:
    """解放しても `cache/report.json` の候補は本文を保つ（書き込みは解放の前）。"""
    result = compile_report(_released_state(tmp_path), _config())

    assert result["candidates"][0].text == ""  # 前提: 解放は起きている
    written = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert [c["text"] for c in written["candidates"]] == ["本文1", "本文2"]


def test_the_release_does_not_add_the_contexts_key_when_absent() -> None:
    """`contexts` を持たない入力に新しいキーを足さない（既定の出力を変えない）。"""
    result = compile_report(_state(candidates=[_candidate(1)]), _config())

    assert "contexts" not in result


# ---------------------------------------------------------------------------
# US5: 中間データの切り替え（FR-046 / SC-026 / 契約 §5）
# ---------------------------------------------------------------------------


def _intermediate_state(tmp_path: Path) -> dict[str, Any]:
    return _state(
        candidates=[_candidate(1)],
        analyses=[_analysis("t1")],
        compressed=[
            CompressedSource(
                source_id="t1", input_chars=25000, output_chars=9000, applied=True, reason="compressed"
            )
        ],
        degradations=[
            Degradation(
                node_name="analyze_content",
                stage=1,
                before_chars=25000,
                after_chars=22500,
                reason="token_limit",
                limit_known=False,
            )
        ],
        failures=[_failure(1)],
        cache_dir=str(tmp_path),
    )


def test_intermediate_data_is_written_when_enabled(tmp_path: Path) -> None:
    """`include_intermediate` が真なら圧縮・縮退・失敗を書き出す（契約 §5）。"""
    state = _intermediate_state(tmp_path)

    compile_report(state, _config(include_intermediate=True))

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "compressed.json",
        "degradations.json",
        "failures.json",
        "report.json",
        "usage.json",
    ]
    compressed = json.loads((tmp_path / "compressed.json").read_text(encoding="utf-8"))
    degradations = json.loads((tmp_path / "degradations.json").read_text(encoding="utf-8"))
    assert [c["source_id"] for c in compressed] == ["t1"]
    assert [d["stage"] for d in degradations] == [1]


def test_the_default_writes_no_new_files_and_keeps_the_report_keys(tmp_path: Path) -> None:
    """既定（偽）では `compressed` / `degradations` / `failures` を書かない。

    `usage.json` は `include_intermediate` に依存しない（使用量は利用者に出さない
    中間成果物であり、`cache_dir` があるときは常に書く。data-model §4.3 の段 4 /
    quickstart 3 節の `cache/` の表）。`report.json` の形は変わらない（SC-026）。
    """
    state = _intermediate_state(tmp_path)

    result = compile_report(state, _config())

    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.json", "usage.json"]
    written = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert set(written) == REPORT_JSON_KEYS
    assert written == result["report"].model_dump(mode="json")


def test_no_intermediate_files_without_a_cache_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cache_dir` が無ければ中間データも書かない（書き込みの判断は 1 か所）。"""
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        compile_report_module, "write_json", lambda *a, **k: calls.append((a, k))
    )
    state = _intermediate_state(Path("/tmp/does-not-matter"))
    state["cache_dir"] = None

    compile_report(state, _config(include_intermediate=True))

    assert calls == []


def test_the_breakdown_note_reports_compression_degradation_and_failures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """内訳（圧縮・縮退・失敗の件数）を補足行に 1 行で出す（T080）。"""
    compile_report(_intermediate_state(Path("/tmp/does-not-matter")), _config())

    err = capsys.readouterr().err
    assert err.count("[補足]") == 1
    assert "圧縮 1 件" in err and "縮退 1 段" in err and "失敗 1 件" in err


def test_no_breakdown_note_without_intermediate_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """内訳がすべて 0 なら補足行を出さない（既定の入力の stderr を変えない。FR-035）。"""
    compile_report(_state(candidates=[_candidate(1)], analyses=[_analysis("t1")]), _config())

    assert "[補足]" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# US8: 使用量の集約と記録（FR-061 / FR-062 / SC-022 / data-model §3.4・§4.3）
# ---------------------------------------------------------------------------

#: `cache/usage.json` に書く集計のキー（data-model §3.4 の派生値）。
USAGE_JSON_KEYS = frozenset(
    {
        "calls",
        "unknown_calls",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "by_node",
        "by_role",
    }
)


def _usage(
    node: str,
    *,
    role: str = "research",
    input_tokens: int | None = 120,
    output_tokens: int | None = 30,
    total_tokens: int | None = 150,
    structured: bool = False,
) -> ModelUsage:
    """使用量の記録 1 件（トークン数は `None` = 不明も作れる）。"""
    return ModelUsage(
        node_name=node,
        role=role,
        model="openai:mimo-2.5",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        structured=structured,
    )


def _usage_state(tmp_path: Path, usage: list[ModelUsage]) -> dict[str, Any]:
    """使用量の記録を持つ入力 state（レポートは空で足りる）。"""
    return _state(
        candidates=[_candidate(1)],
        analyses=[_analysis("t1")],
        usage=usage,
        cache_dir=str(tmp_path),
    )


def _written_usage(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))


def test_usage_json_records_the_calls_tokens_and_the_breakdowns(tmp_path: Path) -> None:
    """呼び出し回数・トークン合計・内訳が `cache/usage.json` に書かれる（FR-062）。"""
    state = _usage_state(
        tmp_path,
        [
            _usage("plan_search"),
            _usage("plan_search", structured=True, input_tokens=10, output_tokens=5, total_tokens=15),
            _usage("extract_common", role="summary", input_tokens=1, output_tokens=2, total_tokens=3),
        ],
    )

    compile_report(state, _config())

    written = _written_usage(tmp_path)
    assert set(written) == USAGE_JSON_KEYS
    assert written["calls"] == 3
    assert written["unknown_calls"] == 0
    assert written["input_tokens"] == 131
    assert written["output_tokens"] == 37
    assert written["total_tokens"] == 168
    assert written["by_node"] == {"plan_search": 2, "extract_common": 1}
    assert written["by_role"] == {"research": 2, "summary": 1}


def test_usage_json_marks_unknown_calls_and_leaves_them_out_of_the_totals(
    tmp_path: Path,
) -> None:
    """不明な呼び出しは `unknown_calls` に計上し、合計には 0 として足す（FR-061）。"""
    state = _usage_state(
        tmp_path,
        [
            _usage("plan_search"),
            _usage(
                "extract_common",
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                structured=True,
            ),
        ],
    )

    compile_report(state, _config())

    written = _written_usage(tmp_path)
    assert written["calls"] == 2
    assert written["unknown_calls"] == 1
    assert written["input_tokens"] == 120
    assert written["output_tokens"] == 30
    assert written["total_tokens"] == 150


def test_usage_json_is_written_even_when_no_llm_call_happened(tmp_path: Path) -> None:
    """記録が 0 件でもファイルは書く（「呼んでいない」ことの記録。FR-062）。

    `calls = 0` を書かないと、ファイルが無い実行と「LLM を呼ばずに完走した実行」を
    区別できない。
    """
    compile_report(_usage_state(tmp_path, []), _config())

    assert _written_usage(tmp_path) == {
        "calls": 0,
        "unknown_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "by_node": {},
        "by_role": {},
    }


def test_no_usage_json_without_a_cache_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cache_dir` が無ければ `usage.json` も書かない（data-model §4.3 の段 4）。"""
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        compile_report_module, "write_json", lambda *a, **k: calls.append((a, k))
    )
    state = _usage_state(Path("/tmp/does-not-matter"), [_usage("plan_search")])
    state["cache_dir"] = None

    compile_report(state, _config())

    assert calls == []


def test_usage_json_is_written_before_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`usage.json` は `report.json` より先に書く（data-model §4.3 の順序）。

    順序を固定しないと、書き込みの途中で失敗したときに「使用量が残っているのに
    レポートが無い」状態の理由が分からなくなる。
    """
    written: list[str] = []
    original = compile_report_module.write_json

    def _record(directory: Path, name: str, data: Any) -> Path:
        written.append(name)
        return original(directory, name, data)

    monkeypatch.setattr(compile_report_module, "write_json", _record)

    compile_report(_usage_state(tmp_path, [_usage("plan_search")]), _config())

    assert written == ["usage", "report"]


def test_the_usage_note_reports_the_calls_and_tokens(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """使用量は補足行 1 行で進捗に現れる（FR-062 / R-11 の文面）。"""
    compile_report(_usage_state(tmp_path, [_usage("plan_search")]), _config())

    err = capsys.readouterr().err
    assert err.count("[補足]") == 1
    assert "LLM 呼び出し合計 1 回（入力 120 / 出力 30 トークン）" in err


def test_the_usage_note_mentions_the_unknown_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """不明な呼び出しがあるときは「不明 N 回」を併記する（FR-061 / T084）。"""
    state = _usage_state(
        tmp_path,
        [
            _usage("plan_search"),
            _usage("extract_common", input_tokens=None, output_tokens=None, total_tokens=None),
        ],
    )

    compile_report(state, _config())

    err = capsys.readouterr().err
    assert "LLM 呼び出し合計 2 回（入力 120 / 出力 30 トークン、不明 1 回）" in err


def test_no_usage_note_when_no_call_was_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """記録が 0 件なら補足行を出さない（内訳の補足と同じ規則。FR-035）。"""
    compile_report(_usage_state(tmp_path, []), _config())

    assert "[補足]" not in capsys.readouterr().err


def test_the_usage_is_not_put_into_the_report(tmp_path: Path) -> None:
    """使用量はレポートに入れない（D-3。`report.notes` は本文に描画される）。"""
    result = compile_report(_usage_state(tmp_path, [_usage("plan_search")]), _config())

    report = result["report"]
    assert all("LLM 呼び出し合計" not in note for note in report.notes)
    assert set(report.model_dump(mode="json")) == REPORT_JSON_KEYS
    assert not hasattr(report, "usage")

