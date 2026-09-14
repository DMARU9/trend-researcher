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

import httpx
import openai
import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from trend_researcher.models import AnalysisFinding, Candidate, Context
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
    structured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`analyze_content` をノード単位注入で 1 回実行し、出力 state を返す。

    `structured` を渡すと構造化出力が成功する（省略時は必ず失敗し、US2 の
    フォールバック経路を通る）。
    """
    node_state: dict[str, Any] = {
        "candidates": [_candidate(1)] if candidates is None else candidates,
        "contexts": [] if contexts is None else contexts,
    }
    if platform is not None:
        node_state["platform"] = platform
    injected = {} if structured is None else {"analyze_content": structured}
    with fake_model_factory.install({"analyze_content": response}, structured=injected):
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
    # 長さはプロンプト全体ではなく**素材の部分**で見る（プロンプト全体には
    # テンプレートの文面も含まれ、その量は FR-055〜058 で増減しうるため）。
    prompt = fake_model_factory.prompts_for("analyze_content")[0]
    assert "埋め草" in prompt
    assert _TAIL_KEYWORD not in prompt
    assert prompt.count("埋め草") < _OVER_THRESHOLD_SOURCE.count("埋め草")


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
    # US2 のフォールバックの補足行と混同しないよう、圧縮の文言で固定する
    assert "[補足] 長文素材 1 件を圧縮（成功 1/1" in err


def test_no_note_when_nothing_was_compressed(
    fake_model_factory, capsys: pytest.CaptureFixture[str]
):
    """圧縮が 0 件なら圧縮の追加行を出さない（既定入力の stderr を変えない。FR-035）。

    US2 で「構造化出力のフォールバック」の補足行も出るようになったため、このテストは
    圧縮の補足行に限定して確認する（フォールバックの補足行は別の契約）。
    """
    with fake_model_factory.install({"analyze_content": _STRUCTURED_RESPONSE}):
        analyze_content(_node_state(_candidate(1, text="短い本文")), _config())

    assert "長文素材" not in capsys.readouterr().err


class _TrackingLLM:
    """同時実行数を記録する計測用 LLM フェイク。

    `FakeModelFactory` のフェイクは即座に応答を返すため同時実行数が観測できない。
    差し替える境界（`build_model`）は R-7 と同じで、計測用の実装だけをここに置く。
    構造化出力は常に失敗させ、計測対象をテキスト呼び出し（フォールバック）に
    絞る。
    """

    def __init__(self) -> None:
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        raise OutputParserException("計測用フェイクは構造化出力を返さない")

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


# --- US2: 構造化出力とフォールバック（FR-009 / FR-011 / FR-012） -------------

#: 構造化出力で受け取る解析結果。`id` / `title` は候補が正なので上書きされる。
_STRUCTURED_FINDING: dict[str, Any] = {
    "id": "（LLM が返した id。候補の id で上書きされる）",
    "title": "（LLM が返したタイトル）",
    "summary": "モデルが返した要約",
    "angles": [
        {"angle": "入門解説", "value": "初心者に刺さる", "key_phrase": "「モデルA」"},
        {"angle": "失敗談", "value": "共感を呼ぶ", "key_phrase": "「モデルB」"},
    ],
    "key_points": ["入門解説", "失敗談"],
    "evidence": ["「モデルの引用」"],
}


def test_structured_finding_is_used_with_the_candidate_identity(
    fake_model_factory: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """構造化出力が成功したらその内容を使い、`id` / `title` だけ候補で揃える。

    LLM には素材の識別子を渡していないため、`id` を上書きしないとレポートの
    紐づけが壊れる（`compile_report` は候補と解析を id で突き合わせる）。
    """
    out = _run(
        fake_model_factory,
        _STRUCTURED_RESPONSE,
        candidates=[_candidate(1)],
        structured=_STRUCTURED_FINDING,
    )

    finding = out["analyses"][0]
    assert finding.summary == "モデルが返した要約"
    assert finding.id == "t1"
    assert finding.title == ""
    assert [a.angle for a in finding.angles] == ["入門解説", "失敗談"]
    assert finding.key_points == ["入門解説", "失敗談"]
    assert finding.evidence == ["「モデルの引用」"]
    # 成功時は決定的解析を走らせない（テキスト呼び出し 0 回）
    assert fake_model_factory.prompts_for("analyze_content") == []
    assert len(fake_model_factory.structured_prompts_for("analyze_content")) == 1
    assert "[補足]" not in capsys.readouterr().err


def test_structured_output_keeps_candidate_id_for_every_candidate(fake_model_factory: Any) -> None:
    """複数件でも `id` は候補ごとに揃う（同じ id が並ぶとレポートが壊れる）。"""
    candidates = [_candidate(1), _candidate(2), _candidate(3)]

    out = _run(
        fake_model_factory,
        _STRUCTURED_RESPONSE,
        candidates=candidates,
        structured=_STRUCTURED_FINDING,
    )

    assert [f.id for f in out["analyses"]] == ["t1", "t2", "t3"]


def test_structured_failure_uses_the_existing_parser(
    fake_model_factory: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """規定回数失敗したら見出し表の解析へ切り替え、件数を補足行に残す（FR-011）。"""
    out = _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=[_candidate(1)])

    err = capsys.readouterr().err
    assert (
        "[補足] 構造化出力を取得できなかったため見出し表の解析へ切り替えました（1 件）" in err
    )
    finding = out["analyses"][0]
    assert finding.summary == "ブログでどう扱えるかの観点でまとめた要約。"
    assert [a.angle for a in finding.angles] == ["入門解説", "失敗談"]
    # 試行回数 = 1 + retry_max（既定 3）。テキスト呼び出しはフォールバックの 1 回だけ
    assert len(fake_model_factory.structured_prompts_for("analyze_content")) == 3
    assert len(fake_model_factory.prompts_for("analyze_content")) == 1


def test_fallback_note_counts_every_candidate(fake_model_factory: Any) -> None:
    """フォールバックは候補ごとに 1 行ではなく、まとめて 1 行にする。"""
    candidates = [_candidate(i) for i in range(1, 4)]

    with fake_model_factory.install({"analyze_content": _STRUCTURED_RESPONSE}):
        analyze_content(
            {"candidates": candidates, "contexts": [], "platform": "x"}, _config()
        )

    assert len(fake_model_factory.prompts_for("analyze_content")) == 3


def test_fallback_does_not_add_progress_lines(fake_model_factory: Any) -> None:
    """フォールバックは進捗行を増やさない（補足は stderr のみ。既定の出力は不変）。"""
    out = _run(fake_model_factory, _STRUCTURED_RESPONSE, candidates=[_candidate(1)])

    contents = [m.content for m in out["messages"]]
    assert len(contents) == 2
    assert not any("補足" in c or "構造化出力" in c for c in contents)


def test_structured_method_comes_from_the_configuration(fake_model_factory: Any) -> None:
    """`structured_method` の設定値が境界まで届く（既定値と同じでも配線を固定する）。"""
    _run(
        fake_model_factory,
        _STRUCTURED_RESPONSE,
        config=_config(structured_method="function_calling"),
        structured=_STRUCTURED_FINDING,
    )

    options = fake_model_factory.structured_options_for("analyze_content")
    assert options and options[0]["method"] == "function_calling"
    assert options[0]["schema"] is AnalysisFinding


# --- US4: 部分失敗の隔離（FR-020 / FR-021 / FR-023 / SC-007） ----------------

#: 失敗させる候補の目印。素材（プロンプト）にこの文字列が含まれる候補だけが失敗する。
_FAILURE_MARKER = "壊れた素材"


class _SelectiveLLM:
    """目印を含む素材だけを失敗させる計測用フェイク（US4 の隔離の観測）。

    `FakeModelFactory` のフェイクは「ノード単位で 1 つの応答」しか持てないため、
    「10 件中 3 件だけ失敗」を作れない。`_TrackingLLM` と同じく、差し替える境界
    （`build_model`）は R-7 のまま、候補ごとの成否を判定する実装だけをここに置く。

    失敗は構造化出力とテキスト呼び出しの**両方**で起こす。片方だけだと
    `_structured_finding` のフォールバックがもう片方を呼び、失敗が消えてしまう
    （隔離のテストが「フォールバックで救えた」経路に化ける）。
    """

    def __init__(self, marker: str = _FAILURE_MARKER, error: BaseException | None = None) -> None:
        self.marker = marker
        self.error = error if error is not None else RuntimeError(f"{marker} を解析できません")
        self.structured_calls = 0
        self.text_calls = 0

    def _decide(self, prompt: str) -> None:
        if self.marker in prompt:
            raise self.error

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        return _SelectiveStructured(self, schema)

    async def ainvoke(self, prompt: str) -> AIMessage:
        self.text_calls += 1
        self._decide(prompt)
        return AIMessage(content=_STRUCTURED_RESPONSE)


class _SelectiveStructured:
    """`with_structured_output` の戻り（目印の判定だけを行う runnable）。"""

    def __init__(self, llm: _SelectiveLLM, schema: Any) -> None:
        self._llm = llm
        self._schema = schema

    async def ainvoke(self, prompt: str) -> Any:
        self._llm.structured_calls += 1
        self._llm._decide(prompt)
        return self._schema.model_validate({"id": "目印", "summary": "構造化の要約"})


def _run_selective(
    candidates: list[Candidate], llm: _SelectiveLLM
) -> dict[str, Any]:
    """隔離用のフェイクで `analyze_content` を 1 回実行し、出力 state を返す。"""
    with mock.patch("trend_researcher.nodes.analyze_content.build_model", return_value=llm):
        return analyze_content(
            {"candidates": candidates, "contexts": [], "platform": "x"}, _config()
        )


def _partial_candidates(total: int = 10, failing: tuple[int, ...] = (2, 5, 9)) -> list[Candidate]:
    """`failing` に挙げた番号の候補だけ素材に目印を入れる（SC-007 の 10 中 3）。"""
    return [
        _candidate(i, text=f"{_FAILURE_MARKER} {i}" if i in failing else f"本文{i}")
        for i in range(1, total + 1)
    ]


def test_one_failed_candidate_does_not_stop_the_others() -> None:
    """10 件中 3 件が失敗しても 7 件の解析が得られる（FR-020 / SC-007）。"""
    out = _run_selective(_partial_candidates(), _SelectiveLLM())

    assert len(out["analyses"]) == 7
    assert len(out["failures"]) == 3


def test_every_candidate_ends_up_in_analyses_or_failures() -> None:
    """成功と失敗の和集合が候補全体と一致する（無言の欠落の禁止。FR-021）。"""
    candidates = _partial_candidates()
    out = _run_selective(candidates, _SelectiveLLM())

    covered = {a.id for a in out["analyses"]} | {f.id for f in out["failures"]}
    assert covered == {c.id for c in candidates}
    assert {f.id for f in out["failures"]} == {"t2", "t5", "t9"}


def test_the_failure_record_carries_the_id_and_the_reason() -> None:
    """失敗は `kind` / `id` / 例外型 / 理由が分かる形で残る（FR-021 / FR-023）。"""
    out = _run_selective(_partial_candidates(total=1, failing=(1,)), _SelectiveLLM())

    (failure,) = out["failures"]
    assert failure.kind == "analysis"
    assert failure.id == "t1"
    assert failure.error_type == "RuntimeError"
    assert _FAILURE_MARKER in failure.message


def test_all_candidates_failing_still_completes() -> None:
    """全件失敗でも例外にせず、失敗の事実と理由を残す（US4 シナリオ 3）。"""
    out = _run_selective(_partial_candidates(total=1, failing=(1,)), _SelectiveLLM())

    assert out["analyses"] == []
    assert [f.id for f in out["failures"]] == ["t1"]


def test_cancellation_is_not_swallowed_as_a_partial_failure() -> None:
    """`asyncio.CancelledError` は部分失敗として飲み込まず再送出する（原則 V / 契約 §3）。

    `CancelledError` は `BaseException` なので `except Exception` では捕まらない。
    `return_exceptions=True` を付けた `gather` は**戻り値として**返してくるため、
    明示的に再送出しないと「キャンセルされたのに正常完了」になる。
    """
    candidates = _partial_candidates(total=2, failing=(1,))
    llm = _SelectiveLLM(error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        _run_selective(candidates, llm)


# --- US4: 失敗の可視化（FR-023） ------------------------------------------


def test_the_failure_note_reports_the_count_and_the_reasons(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """失敗の件数と理由を補足行に 1 行で出す（FR-023。stderr のみ）。"""
    _run_selective(_partial_candidates(), _SelectiveLLM())

    err = capsys.readouterr().err
    assert "[補足] 解析できなかった対象 3 件" in err
    assert err.count("[補足] 解析できなかった") == 1
    assert "RuntimeError" in err


def test_no_failure_note_when_nothing_failed(capsys: pytest.CaptureFixture[str]) -> None:
    """失敗が無ければ補足行を出さない（既定の入力の stderr を変えない。FR-035）。"""
    _run_selective([_candidate(1), _candidate(2)], _SelectiveLLM())

    assert "解析できなかった" not in capsys.readouterr().err


# --- US5: 実行時設定の注入（FR-005 / FR-010 / FR-015 / FR-025） --------------
#
# このノードが読む値（同時実行数・再試行・縮退）は**すべて** `Configuration` から
# 来る。コードに固定値を残すと、Studio / CLI から変更しても挙動が変わらない
# （FR-025）。ここでは値そのものではなく「設定を変えると観測が変わること」を
# 固定する。


@pytest.mark.parametrize("concurrency", [1, 2])
def test_the_concurrency_limit_comes_from_the_configuration(concurrency: int) -> None:
    """同時実行数は設定から注入される（`Semaphore(2)` の固定値を持たない）。

    `analysis_concurrency = 1` で同時実行数が 1 にならなければ、値は配線されて
    いない（既定の 2 と一致してしまうため、既定値だけでは検出できない）。
    """
    tracking = _TrackingLLM()
    candidates = [_candidate(i) for i in range(1, 6)]

    with mock.patch("trend_researcher.nodes.analyze_content.build_model", return_value=tracking):
        out = analyze_content(
            {"platform": "x", "candidates": candidates, "contexts": []},
            _config(analysis_concurrency=concurrency),
        )

    assert tracking.calls == 5
    assert tracking.max_in_flight == concurrency
    assert len(out["analyses"]) == 5


def test_the_start_line_reports_the_configured_concurrency(fake_model_factory: Any) -> None:
    """開始行の同時実行数は設定値を映す（既定 2 の文言は変えない。FR-035）。"""
    out = _run(fake_model_factory, _STRUCTURED_RESPONSE, config=_config(analysis_concurrency=3))

    assert out["messages"][0].content == "[5/7] analyze_content ... 開始（並列上限 3）"


class _StructuredFailingLLM:
    """構造化出力だけが失敗する計測用フェイク（再試行の回数を数える）。

    テキスト経路は 1 回で成功させる。両方を失敗させると再試行の回数が
    「構造化 ＋ フォールバック」の合計になり、どちらの配線が効いたのか分からなく
    なるため。
    """

    def __init__(self) -> None:
        self.structured_calls = 0
        self.text_calls = 0

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        return _StructuredFailingRunnable(self)

    async def ainvoke(self, prompt: Any) -> AIMessage:
        self.text_calls += 1
        return AIMessage(content=_STRUCTURED_RESPONSE)


class _StructuredFailingRunnable:
    """`with_structured_output` の戻り（毎回 `OutputParserException` を送出）。"""

    def __init__(self, llm: _StructuredFailingLLM) -> None:
        self._llm = llm

    async def ainvoke(self, prompt: Any) -> Any:
        self._llm.structured_calls += 1
        raise OutputParserException("スキーマに一致しません")


@pytest.mark.parametrize(("retry_max", "expected_calls"), [(0, 1), (2, 3)])
def test_the_retry_count_comes_from_the_configuration(
    retry_max: int, expected_calls: int
) -> None:
    """`retry_max` が試行回数（1 + retry_max）になる（FR-010 / FR-025）。"""
    llm = _StructuredFailingLLM()

    with mock.patch("trend_researcher.nodes.analyze_content.build_model", return_value=llm):
        out = analyze_content(
            {"platform": "x", "candidates": [_candidate(1)], "contexts": []},
            _config(retry_max=retry_max, retry_wait_seconds=0.5),
        )

    assert llm.structured_calls == expected_calls
    assert llm.text_calls == 1
    assert len(out["analyses"]) == 1


def test_the_wait_between_retries_comes_from_the_configuration(no_retry_sleep: Any) -> None:
    """`retry_wait_seconds` が待機として境界へ届く（FR-010 / FR-025）。"""
    llm = _StructuredFailingLLM()

    with mock.patch("trend_researcher.nodes.analyze_content.build_model", return_value=llm):
        analyze_content(
            {"platform": "x", "candidates": [_candidate(1)], "contexts": []},
            _config(retry_max=2, retry_wait_seconds=0.5),
        )

    # 2 回の再試行の前だけ待つ（成功したフォールバックでは待たない）
    assert no_retry_sleep.sleeps == [0.5, 0.5]


def _context_length_error() -> Exception:
    """上限超過（400 ＋ `context_length_exceeded`）を模した例外（契約 §5）。"""
    return openai.BadRequestError(
        message="This endpoint's maximum context length is 1048576 tokens.",
        response=httpx.Response(400, request=httpx.Request("POST", "https://example.test/v1")),
        body={"error": {"code": "context_length_exceeded"}},
    )


class _LimitErrorLLM:
    """構造化出力が常に上限超過になる計測用フェイク（縮退の段数を数える）。

    上限超過は再試行の対象ではないため、呼び出し回数がそのまま「初回 ＋ 段数」に
    なる（契約 §3 の対象外）。
    """

    def __init__(self) -> None:
        self.calls = 0

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        return self

    async def ainvoke(self, prompt: Any) -> AIMessage:
        self.calls += 1
        raise _context_length_error()


@pytest.mark.parametrize(("max_attempts", "expected_stages"), [(1, 1), (3, 3)])
def test_the_degrade_stages_come_from_the_configuration(
    max_attempts: int, expected_stages: int
) -> None:
    """`degrade_max_attempts` が縮退の段数になる（FR-015 / FR-025）。

    素材は縮小の下限（`min_input_chars` の既定 1000）より十分に長くし、段数が
    設定値で決まるようにする。段を使い切った `DegradationError` は部分失敗として
    記録され、ノードは完了する（FR-020。US3 の exit 1 は CLI が捕捉して作る）。
    """
    llm = _LimitErrorLLM()

    with mock.patch("trend_researcher.nodes.analyze_content.build_model", return_value=llm):
        out = analyze_content(
            {"platform": "x", "candidates": [_candidate(1, text="あ" * 5000)], "contexts": []},
            _config(degrade_max_attempts=max_attempts, retry_max=0),
        )

    assert llm.calls == 1 + expected_stages
    assert [d.stage for d in out["degradations"]] == list(range(1, expected_stages + 1))
    (failure,) = out["failures"]
    assert failure.error_type == "DegradationError"
    assert f"試した段数: {expected_stages}" in failure.message
