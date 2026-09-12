"""nodes/analyze_content.py の要約契約テスト（FR-012 / FR-007 / COV-004）。

対象: ソーステキストの整形（`_build_source_text`）、活用アイデア表の解析
（`_parse_angles_table`）、構造化ブロックが欠けた応答のフォールバック要約、
ノードの結線（並列上限 2・context の id 参照・進捗行）。

LLM 応答は `fake_model_factory` でノード単位に注入する（LAYOUT-004-4 / R-7）。
崩れた入力（列不足・見出しのみ・区切り行のみ・セル空）でも例外にせず、
採用できる行だけを拾う契約を固定する。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest import mock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from trend_researcher.models import Candidate, Context
from trend_researcher.nodes.analyze_content import (
    _build_source_text,
    _parse_angles_table,
    analyze_content,
)

#: プロンプトが要求する構造化応答（概要・活用アイデア表・引用）。
_STRUCTURED_RESPONSE = (
    "## 概要\n"
    "ブログでどう扱えるかの観点でまとめた要約。\n\n"
    "## ブログの活用アイデア\n"
    "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n"
    "|--------|--------------|---------------------|\n"
    "| 入門解説 | 初心者に刺さる | 「キーフレーズA」 |\n"
    "| 失敗談 | 共感を呼ぶ | 「キーフレーズB」 |\n\n"
    "## そのまま使える引用\n"
    "- 「引用1」（文脈1）\n"
    "- 「引用2」（文脈2）\n"
)
#: 概要を欠いた応答（切り口だけが取れる）。
_ANGLES_ONLY_RESPONSE = (
    "## ブログの活用アイデア\n"
    "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n"
    "|--------|--------------|---------------------|\n"
    "| 入門解説 | 初心者向け | 「キーフレーズ」 |\n"
    "| 失敗談 | 共感を呼ぶ | 「例」 |\n"
)


def _config(**configurable: Any) -> RunnableConfig:
    return {"configurable": configurable}


def _candidate(idx: int = 1, platform: str = "x", **overrides: Any) -> Candidate:
    """テスト用候補。index から決定的に導出する。"""
    base: dict[str, Any] = {"platform": platform, "id": f"t{idx}" if platform == "x" else f"v{idx}"}
    if platform == "x":
        base.update({"text": f"本文{idx}", "author_handle": f"user{idx}", "url": f"url{idx}"})
    else:
        base.update({"title": f"動画{idx}", "url": f"url{idx}"})
    base.update(overrides)
    return Candidate(**base)


def _context(cid: str, **overrides: Any) -> Context:
    base: dict[str, Any] = {"id": cid}
    base.update(overrides)
    return Context(**base)


def _run(
    fake_model_factory: Any,
    response: str,
    *,
    platform: str | None = "x",
    config: RunnableConfig | None = None,
    candidates: list[Candidate] | None = None,
    contexts: list[Context] | None = None,
) -> dict[str, Any]:
    """`analyze_content` をノード単位注入で 1 回実行し、出力 state を返す。"""
    node_state: dict[str, Any] = {
        "candidates": [_candidate(1)] if candidates is None else candidates,
        "contexts": [] if contexts is None else contexts,
    }
    if platform is not None:
        node_state["platform"] = platform
    with fake_model_factory.install({"analyze_content": response}):
        return analyze_content(node_state, _config() if config is None else config)


# --- 活用アイデア表の解析（FR-012） ---------------------------------------


def test_parse_angles_table_reads_three_columns():
    md = (
        "## ブログの活用アイデア\n"
        "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n"
        "|--------|--------------|---------------------|\n"
        "| 入門解説 | 初心者に刺さる | 「キーフレーズA」 |\n"
        "| 失敗談 | 共感を呼ぶ | 「キーフレーズB」 |\n"
    )
    angles = _parse_angles_table(md)
    assert [(a.angle, a.value, a.key_phrase) for a in angles] == [
        ("入門解説", "初心者に刺さる", "「キーフレーズA」"),
        ("失敗談", "共感を呼ぶ", "「キーフレーズB」"),
    ]


@pytest.mark.parametrize(
    "table",
    [
        "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n",
        "| 角度 | 価値 | フレーズ |\n",
        "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n|---|---|---|\n",
        "|:---|---:|---:|\n",
        "|   |   |   |\n",
    ],
    ids=["header-kirikuchi", "header-kakudo", "header-and-separator", "aligned", "blank-row"],
)
def test_parse_angles_table_skips_header_and_separator_rows(table: str):
    assert _parse_angles_table(table) == []


@pytest.mark.parametrize("table", ["| A | B |\n", "| A |\n", "本文だけの行\n", ""], ids=["two", "one", "text", "blank"])
def test_parse_angles_table_skips_rows_without_three_columns(table: str):
    assert _parse_angles_table(table) == []


@pytest.mark.parametrize(
    "table",
    [
        "| （必要なだけ繰り返す） | | |\n",
        "| A | | C |\n",
        "|  | B | C |\n",
    ],
    ids=["prompt-placeholder", "missing-value", "missing-angle"],
)
def test_parse_angles_table_skips_rows_with_empty_cells(table: str):
    # プロンプトの例示行（`| （必要なだけ繰り返す） | | |`）は形式の説明であって
    # データではない。3 列のどれかが空の行は「切り口 × 価値 × フレーズ」を
    # 満たさないため採用しない（採用すると key_points に空文字や指示文が混じる）。
    assert _parse_angles_table(table) == []


def test_parse_angles_table_keeps_only_first_three_columns():
    md = "| A | B | C | D |\n"
    assert [(a.angle, a.value, a.key_phrase) for a in _parse_angles_table(md)] == [("A", "B", "C")]


def test_parse_angles_table_keeps_valid_rows_between_broken_rows():
    md = (
        "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n"
        "|---|---|---|\n"
        "| A | B | C |\n"
        "| | | |\n"
        "| D | E | F |\n"
    )
    assert [a.angle for a in _parse_angles_table(md)] == ["A", "D"]


# --- ソーステキストの整形 -------------------------------------------------


@pytest.mark.parametrize(
    ("candidate", "context", "expected"),
    [
        (
            _candidate(1),
            _context("t1", text="親", thread_text="親スレッド", replies=["r1", "r2"]),
            (
                "[親ツイート（スレッド）]\n親スレッド"
                "\n\n[本文]\n本文1"
                "\n\n[代表的なリプライ]\n- r1\n- r2"
            ),
        ),
        (_candidate(1), None, "[本文]\n本文1"),
        (
            _candidate(1, text=""),
            _context("t1", text="親", thread_text="親スレッド", replies=["r1"]),
            "[親ツイート（スレッド）]\n親スレッド\n\n[代表的なリプライ]\n- r1",
        ),
        (_candidate(1, text=""), _context("t1", replies=["r"]), "[代表的なリプライ]\n- r"),
        (
            _candidate(1, platform="youtube"),
            _context("v1", text="字幕テキスト"),
            "[字幕]\n字幕テキスト",
        ),
        (_candidate(1, text=""), _context("t1", text=""), ""),
        (_candidate(1, platform="youtube"), _context("v1", text=""), ""),
        (
            # 本文があるときは字幕枠にフォールバックしない（YouTube 字幕は本文が空のときだけ）。
            _candidate(1),
            _context("t1", text="親"),
            "[本文]\n本文1",
        ),
    ],
    ids=[
        "x-full",
        "x-body-only",
        "x-thread-only",
        "x-replies-only",
        "youtube-caption",
        "all-empty",
        "youtube-empty-caption",
        "caption-not-used-with-body",
    ],
)
def test_build_source_text(candidate: Candidate, context: Context | None, expected: str):
    assert _build_source_text(candidate, context) == expected


# --- 構造化応答の展開 -----------------------------------------------------


def test_structured_response_is_expanded_into_finding(fake_model_factory):
    out = _run(fake_model_factory, _STRUCTURED_RESPONSE)
    finding = out["analyses"][0]
    assert finding.id == "t1"
    assert finding.summary == "ブログでどう扱えるかの観点でまとめた要約。"
    assert [a.angle for a in finding.angles] == ["入門解説", "失敗談"]
    assert finding.key_points == ["入門解説", "失敗談"]
    assert finding.evidence == ["「引用1」（文脈1）", "「引用2」（文脈2）"]


def test_analyses_keep_candidate_order_and_ids(fake_model_factory):
    candidates = [_candidate(i) for i in range(1, 6)]
    out = _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=candidates)
    assert [a.id for a in out["analyses"]] == [f"t{i}" for i in range(1, 6)]


def test_empty_candidate_list_yields_no_analyses(fake_model_factory):
    out = _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=[])
    assert out["analyses"] == []


# --- フォールバック要約（FR-012） -----------------------------------------


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("普通の段落A\n\n段落B\n", "普通の段落A"),
        ("# 見出しだけ\n\n本文段落\n", "本文段落"),
        ("\n\n\n本文段落\n", "本文段落"),
    ],
    ids=["plain", "heading-first", "blank-first"],
)
def test_summary_falls_back_to_first_body_paragraph(
    fake_model_factory, response: str, expected: str
):
    out = _run(fake_model_factory, response)
    assert out["analyses"][0].summary == expected


def test_summary_falls_back_to_angles(fake_model_factory):
    out = _run(fake_model_factory, _ANGLES_ONLY_RESPONSE)
    finding = out["analyses"][0]
    assert finding.summary == (
        "このコンテンツでは、入門解説などについて語られています。"
        "ほかにも失敗談といった観点が扱われており、ブログのネタとして活用できます。"
    )
    assert finding.key_points == ["入門解説", "失敗談"]


def test_summary_from_single_angle_has_no_second_sentence(fake_model_factory):
    response = (
        "## ブログの活用アイデア\n\n"
        "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n"
        "|---|---|---|\n"
        "| 入門解説 | 初心者向け | 「キーフレーズ」 |\n"
    )
    finding = _run(fake_model_factory, response)["analyses"][0]
    # 見出しと表の間に空行があっても、生の Markdown 表を summary にしない。
    assert finding.summary == "このコンテンツでは、入門解説などについて語られています。"
    assert finding.key_points == ["入門解説"]


def test_unstructured_response_does_not_raise(fake_model_factory):
    out = _run(fake_model_factory, "")
    finding = out["analyses"][0]
    assert finding.summary == ""
    assert finding.angles == []
    assert finding.key_points == []
    assert finding.evidence == []


# --- プロンプトへ渡すソース -------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"author_handle": "userA", "title": "題名", "url": "urlA"}, "userA"),
        ({"author_handle": "", "title": "題名", "url": "urlA"}, "題名"),
        ({"author_handle": "", "title": "", "url": "urlA"}, "urlA"),
    ],
    ids=["handle", "title", "url"],
)
def test_prompt_title_falls_back_from_handle_to_title_to_url(
    fake_model_factory, overrides: dict[str, str], expected: str
):
    candidates = [_candidate(1, **overrides)]
    _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=candidates)
    assert f"ツイート投稿者: {expected}" in fake_model_factory.prompts_for("analyze_content")[0]


def test_prompt_includes_context_text_matched_by_id(fake_model_factory):
    candidates = [_candidate(1), _candidate(2)]
    contexts = [_context("t1", text="親", thread_text="スレッド1"), _context("t2", text="親2")]
    _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=candidates, contexts=contexts)
    prompts = fake_model_factory.prompts_for("analyze_content")
    assert "[親ツイート（スレッド）]\nスレッド1" in prompts[0]
    assert "[本文]\n本文1" in prompts[0]
    assert "スレッド1" not in prompts[1]
    assert "[本文]\n本文2" in prompts[1]


def test_context_without_matching_candidate_is_ignored(fake_model_factory):
    _run(
        fake_model_factory,
        _STRUCTURED_RESPONSE,
        candidates=[_candidate(1)],
        contexts=[_context("t9", text="無関係")],
    )
    assert "無関係" not in fake_model_factory.prompts_for("analyze_content")[0]


def test_prompt_uses_placeholder_when_source_text_is_empty(fake_model_factory):
    candidates = [_candidate(1, text="")]
    _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=candidates)
    assert "（本文なし・メタデータのみ）" in fake_model_factory.prompts_for("analyze_content")[0]


def test_source_text_is_truncated_at_twenty_thousand_chars(fake_model_factory):
    # 位置ごとに異なる文字列にする（同一文字の繰り返しだと「切断された」ことを
    # 部分文字列の有無で判定できない）。
    candidate = _candidate(1, text="".join(f"{i:05d}" for i in range(5000)))
    _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=[candidate])
    prompt = fake_model_factory.prompts_for("analyze_content")[0]
    source = _build_source_text(candidate, None)  # "[本文]\n" + 25000 字
    assert len(source) == 25005
    assert source[:20000] in prompt
    # 20000 文字を超える部分（`source[20000:]`）はプロンプトに載らない。
    assert source[20000:] not in prompt


# --- ノードの結線 ---------------------------------------------------------


def test_platform_from_state_overrides_configurable(fake_model_factory):
    _run(
        fake_model_factory,
        _STRUCTURED_RESPONSE,
        platform="youtube",
        config=_config(platform="x"),
        candidates=[_candidate(1, platform="youtube")],
    )
    assert "動画タイトル: 動画1" in fake_model_factory.prompts_for("analyze_content")[0]


def test_platform_falls_back_to_configurable(fake_model_factory):
    _run(
        fake_model_factory,
        _STRUCTURED_RESPONSE,
        platform=None,
        config=_config(platform="youtube"),
        candidates=[_candidate(1, platform="youtube")],
    )
    assert "動画タイトル: 動画1" in fake_model_factory.prompts_for("analyze_content")[0]


def test_progress_messages_report_start_then_finish(fake_model_factory):
    out = _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=[_candidate(1), _candidate(2)])
    contents = [m.content for m in out["messages"]]
    assert contents == [
        "[5/7] analyze_content ... 開始（並列上限 2）",
        "[5/7] analyze_content ... 完了（2 件を要約）",
    ]


def test_progress_reports_zero_when_no_candidates(fake_model_factory):
    out = _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=[])
    assert [m.content for m in out["messages"]][-1] == (
        "[5/7] analyze_content ... 完了（0 件を要約）"
    )


class _TrackingLLM:
    """同時実行数を記録する計測用 LLM フェイク。

    `FakeModelFactory` のフェイクは即座に応答を返すため同時実行数が観測できない。
    差し替える境界（`build_model`）は R-7 と同じで、計測用の実装だけをここに置く。
    """

    def __init__(self) -> None:
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def ainvoke(self, prompt: str) -> AIMessage:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
        finally:
            self.in_flight -= 1
        return AIMessage(content=_STRUCTURED_RESPONSE)


def test_parallelism_is_capped_at_two():
    tracking = _TrackingLLM()
    candidates = [_candidate(i) for i in range(1, 6)]
    with mock.patch("trend_researcher.nodes.analyze_content.build_model", return_value=tracking):
        out = analyze_content(
            {"platform": "x", "candidates": candidates, "contexts": []}, _config()
        )
    assert tracking.calls == 5
    assert tracking.max_in_flight == 2
    assert len(out["analyses"]) == 5
