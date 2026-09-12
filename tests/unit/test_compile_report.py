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
    BlogAngle,
    Candidate,
    CommonTheme,
    ResearchInstruction,
    ResearchReport,
)
from trend_researcher.nodes import compile_report as compile_report_module
from trend_researcher.nodes.compile_report import compile_report, render_json, render_markdown
from trend_researcher.providers import get_provider


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


def _config(platform: str = "x", cache_dir: str | None = None) -> dict[str, Any]:
    return {"configurable": {"platform": platform, "cache_dir": cache_dir}}


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
# 進捗メッセージ
# ---------------------------------------------------------------------------


def test_progress_messages_end_with_summary_and_rendered_markdown() -> None:
    candidates = [_candidate(1), _candidate(2)]
    themes = [CommonTheme(theme="A", description="説明")]
    state = _state(candidates=candidates, common_themes=themes)

    result = compile_report(state, _config())

    messages = result["messages"]
    assert messages[-2].content == "レポート完了: 2 件の候補を分析し、1 件の共通テーマを抽出しました。"
    assert messages[-1].content == _markdown(result["report"])
    assert any("[7/7] compile_report ... 開始" in m.content for m in messages)
    assert any("[7/7] compile_report ... 完了" in m.content for m in messages)


# ---------------------------------------------------------------------------
# Markdown 描画
# ---------------------------------------------------------------------------


def test_render_markdown_uses_topic_as_title() -> None:
    report = _report()

    assert _markdown(report).startswith("# リサーチレポート: AI 動向\n")


def test_render_markdown_truncates_raw_text_to_40_chars_when_topic_is_empty() -> None:
    instruction = _instruction().model_copy(update={"topic": "", "raw_text": "あ" * 50})
    report = _report(instruction=instruction)

    assert f"# リサーチレポート: {'あ' * 40}\n" in _markdown(report)


@pytest.mark.parametrize(
    ("platform", "title_line", "header"),
    [
        ("x", "## 選定ツイートリスト（上位 N 件）", "| # | 本文抜粋 | 投稿者 | いいね | RT | 引用 | URL |"),
        (
            "youtube",
            "## 選定動画リスト（関連度順上位 N 件）",
            "| # | タイトル | チャンネル | 再生数 | URL |",
        ),
    ],
)
def test_render_markdown_candidates_table_differs_by_platform(
    platform: str, title_line: str, header: str
) -> None:
    report = _report(platform)

    body = _markdown(report)

    assert title_line in body
    assert header in body


def test_render_markdown_flattens_newlines_in_snippet_and_angles() -> None:
    candidate = _candidate(1, text="1行目\n2行目")
    analysis = _analysis(
        "t1",
        angles=[BlogAngle(angle="切り口\n改行", value="価値\n改行", key_phrase="フレーズ\n改行")],
    )
    report = _report(candidates=[candidate], analyses=[analysis])

    body = _markdown(report)

    assert "| 切り口 改行 | 価値 改行 | フレーズ 改行 |" in body
    # 表の 1 行目（本文抜粋）は改行を潰して表を分断しない
    row = next(line for line in body.splitlines() if line.startswith("| 1 |"))
    assert "| 1 | 1行目 2行目 |" in row
    # 本文ブロックは原文のまま（改行を保持）
    assert "\n1行目\n2行目\n" in body


def test_render_markdown_renders_evidence_as_list() -> None:
    report = _report(analyses=[_analysis("t1", evidence=["引用A", "引用B"])])

    body = _markdown(report)

    assert "**そのまま使える引用**" in body
    assert "- 引用A\n- 引用B\n" in body


def test_render_markdown_places_missing_analysis_placeholder() -> None:
    """解析結果のない候補は「（解析なし）」で穴を埋め、他の候補の描画は続ける。"""
    c1, c2 = _candidate(1), _candidate(2)
    report = _report(candidates=[c1, c2], analyses=[_analysis("t1", summary="要約t1あり")])

    body = _markdown(report)

    assert "- 要約: （解析なし）" in body
    assert "要約t1あり" in body
    # プレースホルダ候補のブロックには概要表題を出さない
    without_analysis = body.split("### 2.")[1].split("## 共通ネタ")[0]
    assert "**概要**" not in without_analysis
    assert "**ブログの活用アイデア**" not in without_analysis


def test_render_markdown_youtube_block_has_no_body_section() -> None:
    report = _report("youtube")

    body = _markdown(report)

    assert "### 1. 動画1" in body
    assert "**本文**" not in body


def test_render_markdown_omits_meta_block_when_all_fields_are_empty() -> None:
    candidate = Candidate(platform="youtube", id="v1", title="", url="", relevance_rank=1)
    report = _report(
        "youtube", candidates=[candidate], analyses=[], sources=[], common_themes=[]
    )

    body = _markdown(report)

    assert "### 1. " in body
    assert not any(line.startswith("> ") for line in body.splitlines())


def test_render_markdown_renders_meta_line_for_x() -> None:
    report = _report()

    body = _markdown(report)

    assert "> 投稿者: ユーザー1 ｜ フォロワー: 100 ｜ いいね: 10 ｜ RT: 2 ｜ 公開日: 2026-01-01" in body


# ---------------------------------------------------------------------------
# 共通テーマ表
# ---------------------------------------------------------------------------


def test_render_common_themes_table_rows_use_platform_label() -> None:
    themes = [
        CommonTheme(theme="テーマA", description="説明A", supporting_ids=["t1"], example_quotes=["引用A"]),
        CommonTheme(theme="テーマB", description="説明B"),
    ]
    report = _report(common_themes=themes)

    body = _markdown(report)

    assert "| テーマ | 説明 | 該当ツイート | 代表抜粋 |" in body
    assert "| テーマA | 説明A | t1 | 引用A |" in body
    # 空リストは "-" で埋める（列がずれない）
    assert "| テーマB | 説明B | - | - |" in body


def test_render_common_themes_table_uses_youtube_label() -> None:
    report = _report("youtube", common_themes=[CommonTheme(theme="A", description="B")])

    assert "| テーマ | 説明 | 該当動画 | 代表抜粋 |" in _markdown(report)


def test_render_markdown_marks_when_no_common_themes() -> None:
    report = _report(common_themes=[])

    assert "（特筆すべき共通点なし）" in _markdown(report)


def test_render_markdown_omits_notes_section_when_notes_are_empty() -> None:
    report = _report(notes=[])

    assert "## 備考" not in _markdown(report)


def test_render_markdown_includes_notes_and_sources_sections() -> None:
    report = _report(sources=["https://a.test", "https://b.test"], notes=["メモ1", "メモ2"])

    body = _markdown(report)

    assert "## 出典" in body
    assert "- https://a.test\n- https://b.test\n" in body
    assert "## 備考" in body
    assert "- メモ1\n- メモ2\n" in body


def test_render_markdown_resolves_provider_from_report_not_argument() -> None:
    """第 2 引数の provider は使われず、instruction.platform から解決される。"""
    report = _report("youtube")

    body = render_markdown(report, get_provider("x"))

    assert "## 選定動画リスト（関連度順上位 N 件）" in body


# ---------------------------------------------------------------------------
# JSON 描画
# ---------------------------------------------------------------------------


def test_render_json_excludes_none_fields() -> None:
    candidate = _candidate(1, retweet_count=None, quote_count=None, author_followers=None)
    report = _report(candidates=[candidate], analyses=[_analysis("t1")])

    parsed = json.loads(render_json(report))

    assert parsed["candidates"][0]["id"] == "t1"
    assert all(v is not None for v in parsed["candidates"][0].values())
    assert "retweet_count" not in parsed["candidates"][0]


def test_render_json_round_trips_report_payload() -> None:
    report = _report(notes=["メモ"], sources=["https://example.test/1"])

    parsed = json.loads(render_json(report))

    assert parsed == json.loads(report.model_dump_json(indent=2, exclude_none=True))
    assert parsed["notes"] == ["メモ"]
    assert parsed["sources"] == ["https://example.test/1"]
