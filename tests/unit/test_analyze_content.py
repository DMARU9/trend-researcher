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


def test_over_threshold_source_is_compressed_not_silently_truncated(fake_model_factory):
    """しきい値超過の素材は先頭だけで切り捨てず、**全体**を圧縮してから載せる。

    旧 `test_source_text_is_truncated_at_twenty_thousand_chars` の置き換え。
    FR-001 の MUST NOT「先頭のみを無言で切り捨ててはならない」により期待する
    振る舞いが変わる唯一の既存テスト（実装メモ §6）。圧縮の入力には 25,005 文字の
    **全体**が渡り、解析プロンプトには圧縮結果が載る（生素材は載らない）。
    """
    # 位置ごとに異なる文字列にする（同一文字の繰り返しだと「切られた」ことを
    # 部分文字列の有無で判定できない）。
    candidate = _candidate(1, text="".join(f"{i:05d}" for i in range(5000)))
    source = _build_source_text(candidate, None)  # "[本文]\n" + 25000 字
    assert len(source) == 25005

    with fake_model_factory.install(
        {"analyze_content": _STRUCTURED_RESPONSE}, compression=_COMPRESSION_RESPONSE
    ):
        analyze_content(_node_state(candidate), _config())

    compression_prompt = fake_model_factory.compression_prompts[0]
    assert source[:20000] in compression_prompt
    assert source[20000:] in compression_prompt  # 後半も捨てない（FR-001）

    analyze_prompt = fake_model_factory.prompts_for("analyze_content")[0]
    assert _TAIL_KEYWORD in analyze_prompt  # 圧縮結果の固有語が載る
    assert source[20000:] not in analyze_prompt  # 生素材は載らない


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


# --- 長文素材の圧縮（US1 / FR-001〜008 / SC-001〜004） ---------------------

#: 圧縮の応答（`COMPRESSION_PROMPT` の出力契約: `<summary>` ＋ `<key_excerpts>`）
_COMPRESSION_RESPONSE = (
    "<summary>素材全体の要点。後半で「独自用語XYZ」が語られている。</summary>\n"
    "<key_excerpts>- 独自用語XYZ は後半にのみ現れる</key_excerpts>"
)

#: 後半にだけ現れる固有語（旧実装の `source_text[:20000]` では落ちていた）
_TAIL_KEYWORD = "独自用語XYZ"

#: 既定のしきい値（20,000 文字）を超え、固有語が 20,000 文字より後にある素材
_OVER_THRESHOLD_SOURCE = "埋め草" * 7000 + _TAIL_KEYWORD


def _node_state(candidate: Candidate) -> dict[str, Any]:
    return {"candidates": [candidate], "contexts": [], "platform": "x"}


def test_compressed_source_reaches_the_analyze_prompt(fake_model_factory):
    """しきい値超過の素材は圧縮されてから解析プロンプトに載る（FR-001 / FR-007）。

    素材の**後半**にある固有語がプロンプトに現れること、逆に生素材（20,000 文字を
    超える塊）がそのまま載っていないことの両方を見る。片方だけでは「圧縮せずに
    全体を渡した」実装でも緑になる。
    """
    candidate = _candidate(1, text=_OVER_THRESHOLD_SOURCE)

    with fake_model_factory.install(
        {"analyze_content": _STRUCTURED_RESPONSE},
        compression=_COMPRESSION_RESPONSE,
    ):
        out = analyze_content(_node_state(candidate), _config())

    compression_prompts = fake_model_factory.compression_prompts
    assert len(compression_prompts) == 1  # 素材 1 件につき 1 回（FR-001）
    assert _TAIL_KEYWORD in compression_prompts[0]  # 素材全体を渡している（FR-001）

    analyze_prompt = fake_model_factory.prompts_for("analyze_content")[0]
    assert _TAIL_KEYWORD in analyze_prompt
    assert _OVER_THRESHOLD_SOURCE not in analyze_prompt  # 生素材は載らない

    records = out["compressed"]
    assert len(records) == 1
    assert (records[0].applied, records[0].reason) == (True, "compressed")
    assert records[0].input_chars == len(_build_source_text(candidate, None))
    assert records[0].output_chars <= 20000


def test_below_threshold_source_is_passed_unchanged(fake_model_factory):
    """しきい値以下では追加の呼び出しをせず、素材をそのまま渡す（FR-008 / SC-003）。"""
    candidate = _candidate(1, text="短い本文")

    with fake_model_factory.install({"analyze_content": _STRUCTURED_RESPONSE}):
        out = analyze_content(_node_state(candidate), _config())

    assert fake_model_factory.compression_prompts == []
    assert "短い本文" in fake_model_factory.prompts_for("analyze_content")[0]
    assert out["compressed"] == []


def test_the_threshold_comes_from_the_configuration(fake_model_factory):
    """しきい値は実行時設定から取る（FR-005。コードに固定値を持たない）。"""
    candidate = _candidate(1, text="あ" * 1200)  # 本文の長さは 1205 文字（接頭辞込み）

    with fake_model_factory.install(
        {"analyze_content": _STRUCTURED_RESPONSE}, compression=_COMPRESSION_RESPONSE
    ):
        triggered = analyze_content(_node_state(candidate), _config(compression_threshold=1000))
        not_triggered = analyze_content(
            _node_state(candidate), _config(compression_threshold=1205)
        )

    assert len(fake_model_factory.compression_prompts) == 1
    assert triggered["compressed"] and not_triggered["compressed"] == []


def test_compression_failure_keeps_the_analysis_running(fake_model_factory):
    """圧縮がタイムアウトしても解析は続き、理由が記録される（FR-003 / FR-004）。"""
    candidate = _candidate(1, text=_OVER_THRESHOLD_SOURCE)

    with fake_model_factory.install(
        {"analyze_content": _STRUCTURED_RESPONSE}, compression_error=TimeoutError()
    ):
        out = analyze_content(_node_state(candidate), _config())

    assert len(out["analyses"]) == 1
    records = out["compressed"]
    assert [(r.applied, r.reason) for r in records] == [(False, "timeout")]
    # 縮退は生素材を（先頭から）しきい値で切ったもの。素材全体は載らない。
    prompt = fake_model_factory.prompts_for("analyze_content")[0]
    assert "埋め草" in prompt
    assert _TAIL_KEYWORD not in prompt
    assert len(prompt) < len(_OVER_THRESHOLD_SOURCE)


def test_progress_note_reports_how_many_were_compressed(
    fake_model_factory, capsys: pytest.CaptureFixture[str]
):
    """圧縮した件数は追加の観測として stderr に 1 行で出す（FR-029 / D-3）。"""
    candidates = [_candidate(1, text=_OVER_THRESHOLD_SOURCE), _candidate(2, text="短い本文")]

    with fake_model_factory.install(
        {"analyze_content": _STRUCTURED_RESPONSE}, compression=_COMPRESSION_RESPONSE
    ):
        analyze_content(
            {"candidates": candidates, "contexts": [], "platform": "x"}, _config()
        )

    err = capsys.readouterr().err
    assert "[補足]" in err
    assert "1 件" in err


def test_no_note_when_nothing_was_compressed(
    fake_model_factory, capsys: pytest.CaptureFixture[str]
):
    """圧縮が 0 件なら追加行を出さない（既定入力の stderr を変えない。FR-035）。"""
    with fake_model_factory.install({"analyze_content": _STRUCTURED_RESPONSE}):
        analyze_content(_node_state(_candidate(1, text="短い本文")), _config())

    assert "[補足]" not in capsys.readouterr().err


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
