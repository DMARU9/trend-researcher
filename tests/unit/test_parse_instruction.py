"""nodes/parse_instruction.py の指示解釈テスト（FR-011 / US3）。

対象: 件数・投稿日下限・出力形式・トピックの優先順位（明示設定 > 本文の自然言語 >
LLM の解釈）と、自然言語の期間表現・日付表現の解釈。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from trend_researcher.models import OutputFormat, ResearchInstruction
from trend_researcher.nodes.parse_instruction import (
    _extract_count_from_text,
    _extract_published_after_from_text,
    _parse_date_from_text,
    parse_instruction,
)
from trend_researcher.state import AgentInputState, AgentState


def test_use_trends_is_not_in_the_state_declarations():
    """ステートの宣言に `use_trends` が無い（FR-009 / REM-003）。

    入力ステートは CLI が組み立て、実行ステートはノードが読み書きする。
    どちらも実行時の参照が 0 になった項目は残さない（値が「宣言されているのに
    誰も読まない」状態を許さない）。
    """
    assert "use_trends" not in AgentInputState.__annotations__
    assert "use_trends" not in AgentState.__annotations__

#: LLM が構造化ブロックを返すときの応答（既定値とは別の値にして優先順位を判定する）。
LLM_JSON = (
    "```json\n"
    '{"topic": "LLM のトピック", "max_results": 3, "output_format": "json"}\n'
    "```"
)
#: 構造化ブロックを返さない応答。
LLM_PLAIN = "特に指定はありません"


def _config(**configurable: Any) -> RunnableConfig:
    return {"configurable": configurable}


def _run(
    fake_model_factory: Any,
    raw: str,
    *,
    response: str = LLM_JSON,
    platform: str | None = "x",
    config: RunnableConfig | None = None,
    **state: Any,
) -> dict[str, Any]:
    """`parse_instruction` をノード単位注入で 1 回実行し、出力 state を返す。"""
    node_state: dict[str, Any] = {"messages": [HumanMessage(content=raw)], "platform": platform}
    node_state.update(state)
    with fake_model_factory.install({"parse_instruction": response}):
        return parse_instruction(node_state, config if config is not None else _config())


# --- 期間表現（自然言語） -------------------------------------------------------


def test_half_year_within_backs_off_182_days(frozen_now: Any) -> None:
    result = _extract_published_after_from_text("半年以内に公開された機械学習動画")
    assert result is not None
    assert (frozen_now.now - result).days == 182


def test_digit_month_within_uses_calendar_months(frozen_now: Any) -> None:
    result = _extract_published_after_from_text("3ヶ月以内のAI解説")
    assert result == datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)


def test_kanji_month_within_is_resolved_like_digits(frozen_now: Any) -> None:
    """漢数字の月数も算用数字と同じに解決される。

    以前は「三ヶ月以内」がどの分岐にも当たらず、例外も出ずに投稿日下限が
    未設定になっていた（FR-023）。
    """
    expected = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
    assert _extract_published_after_from_text("三ヶ月以内のAI解説") == expected
    assert _extract_published_after_from_text("三カ月以内のAI解説") == expected


def test_twelve_kanji_months_backs_off_a_year(frozen_now: Any) -> None:
    result = _extract_published_after_from_text("十二ヶ月以内の動画")
    assert result == datetime(2025, 8, 27, 12, 0, 0, tzinfo=UTC)


def test_one_year_within_backs_off_365_days(frozen_now: Any) -> None:
    result = _extract_published_after_from_text("1年以内のチュートリアル")
    assert result is not None
    assert (frozen_now.now - result).days == 365


def test_this_year_starts_on_january_first(frozen_now: Any) -> None:
    expected = datetime(2026, 1, 1, tzinfo=UTC)
    assert _extract_published_after_from_text("今年公開の動画") == expected
    assert _extract_published_after_from_text("本年公開の動画") == expected


def test_recent_n_days_backs_off_that_many_days(frozen_now: Any) -> None:
    result = _extract_published_after_from_text("最近7日のニュース")
    assert result is not None
    assert (frozen_now.now - result).days == 7


@pytest.mark.parametrize(
    "text",
    [
        "機械学習の基礎を解説している動画",
        "最近の動画",
        "サービス終了のお知らせ",
        "二三十月以内の動画",  # 位取りが壊れた漢数字
    ],
)
def test_unrecognized_period_is_not_a_filter(text: str) -> None:
    assert _extract_published_after_from_text(text) is None


# --- 明示的な日付 --------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2025-01-01以降の動画",
        "2025-01-01 から公開された動画",
        "2025-01-01より後の動画",
        "2025-01-01以後の動画",
    ],
)
def test_explicit_date_is_resolved(text: str) -> None:
    assert _parse_date_from_text(text) == datetime(2025, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "text",
    [
        "2025-13-45以降",  # 存在しない日付
        "2025/01/01以降",  # 区切りが違う
        "以降のみ",  # 日付がない
        "2025-01-01 公開の動画",  # 下限を表す語がない
    ],
)
def test_date_is_not_an_exception_and_resolves_to_none(text: str) -> None:
    assert _parse_date_from_text(text) is None


# --- 件数（自然言語） ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5件の動画を調べて", 5),
        ("10本の記事が欲しい", 10),
        ("3 つだけ選んで", 3),
        ("３件の動画", 3),
        ("五件の動画", 5),
        ("一件だけ", 1),
        ("十件の動画", 10),
        ("十二件の動画", 12),
    ],
)
def test_count_with_unit_is_extracted(text: str, expected: int) -> None:
    assert _extract_count_from_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "たくさん調べて",
        "なるべく多くの動画",
        "百件の動画",  # 一〜九十九のみ対応し、百は対象外（LLM/既定値に委ねる）
        "五の動画",  # 単位がない漢数字は件数と見なさない
        "二三十件の動画",  # 位取りが壊れた漢数字
    ],
)
def test_count_without_unit_or_unsupported_numeral_is_none(text: str) -> None:
    assert _extract_count_from_text(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2025年の動画を10件調べて", 10),
        ("2025年の動画", None),
        ("半年以内の動画を5件", 5),
        ("3年以内の動画", None),
        ("最近30日の動画を7件", 7),
        ("5月の動画を3件", 3),
        ("10年分の動画を3件", 3),
    ],
)
def test_year_and_period_expressions_are_not_counts(text: str, expected: int | None) -> None:
    """年号・期間表現を件数として拾わない。

    以前は「2025年の動画を調べて」が 2025 件と解釈されていた（FR-023）。
    """
    assert _extract_count_from_text(text) == expected


# --- 件数の優先順位: 明示設定 > 本文の自然言語 > LLM -----------------------------


def test_explicit_state_count_beats_instruction_text(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "20件の動画を調べて", max_results=8)
    assert out["instruction"].max_results == 8


def test_explicit_state_count_of_five_beats_instruction_text(fake_model_factory: Any) -> None:
    """既定値と同じ 5 でも、明示指定なら本文の「20件」より優先される（FR-023）。"""
    out = _run(fake_model_factory, "20件の動画を調べて", max_results=5)
    assert out["instruction"].max_results == 5


def test_configurable_count_beats_instruction_text(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "20件の動画を調べて", config=_config(max_results=10))
    assert out["instruction"].max_results == 10


def test_instruction_text_count_beats_llm(fake_model_factory: Any) -> None:
    # LLM 応答は max_results: 3 を返すが、本文の「20件」が優先される
    out = _run(fake_model_factory, "20件の動画を調べて")
    assert out["instruction"].max_results == 20


def test_llm_count_is_used_when_instruction_has_no_number(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "機械学習の動画を調べて")
    assert out["instruction"].max_results == 3


def test_default_count_is_five_when_nothing_specifies(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "機械学習の動画を調べて", response=LLM_PLAIN)
    assert out["instruction"].max_results == 5


# --- トピック ---------------------------------------------------------------


def test_topic_comes_from_structured_block(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "オタクの困りごとを調査したい")
    assert out["instruction"].topic == "LLM のトピック"


def test_topic_falls_back_to_whole_instruction_without_block(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "オタクの困りごとを調査したい", response=LLM_PLAIN)
    assert out["instruction"].topic == "オタクの困りごとを調査したい"
    assert out["instruction"].max_results == 5  # 既定値で続行する


@pytest.mark.parametrize("response", ["[1, 2]", '"AI"', "5"], ids=["array", "string", "number"])
def test_non_object_json_response_is_treated_as_no_block(
    fake_model_factory: Any, response: str
) -> None:
    # JSON ではあるがオブジェクトでない応答。`extract_json_block` がそのまま返すと
    # `.get()` で `AttributeError` になりノードごと落ちるため、ブロック無しとして
    # 扱い指示本文全体にフォールバックする。
    out = _run(fake_model_factory, "オタクの困りごとを調査したい", response=response)
    assert out["instruction"].topic == "オタクの困りごとを調査したい"
    assert out["instruction"].max_results == 5


def test_empty_messages_are_treated_as_empty_instruction(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "", response=LLM_PLAIN, messages=[])
    assert out["instruction"].topic == ""


# --- 出力形式: Configuration > CLI/run（state）> 自然言語/LLM ---------------------


def test_configurable_output_format_beats_state_and_llm(fake_model_factory: Any) -> None:
    out = _run(
        fake_model_factory,
        "オタクの困りごとを調査したい",
        config=_config(output_format="markdown"),
        output_format=OutputFormat.JSON,
    )
    assert out["instruction"].output.format is OutputFormat.MARKDOWN


def test_state_output_format_beats_llm(fake_model_factory: Any) -> None:
    out = _run(
        fake_model_factory,
        "オタクの困りごとを調査したい",
        output_format=OutputFormat.MARKDOWN,
    )
    assert out["instruction"].output.format is OutputFormat.MARKDOWN


def test_llm_output_format_is_used_when_not_specified(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "オタクの困りごとを調査したい")
    assert out["instruction"].output.format is OutputFormat.JSON


def test_output_format_defaults_to_markdown(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "オタクの困りごとを調査したい", response=LLM_PLAIN)
    assert out["instruction"].output.format is OutputFormat.MARKDOWN


# --- 投稿日下限: Configuration > CLI/run（state）> 自然言語 ----------------------


def test_configurable_published_after_beats_instruction_text(fake_model_factory: Any) -> None:
    out = _run(
        fake_model_factory,
        "半年以内の動画を調べて",
        config=_config(published_after="2025-01-01"),
    )
    assert out["instruction"].published_after == datetime(2025, 1, 1, tzinfo=UTC)


def test_state_published_after_beats_instruction_text(fake_model_factory: Any) -> None:
    since = datetime(2024, 12, 31, tzinfo=UTC)
    out = _run(fake_model_factory, "半年以内の動画を調べて", published_after=since)
    assert out["instruction"].published_after == since


def test_instruction_date_beats_relative_period(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "2025-01-01以降の動画を調べて", response=LLM_PLAIN)
    assert out["instruction"].published_after == datetime(2025, 1, 1, tzinfo=UTC)


def test_instruction_relative_period_is_resolved(
    fake_model_factory: Any, frozen_now: Any
) -> None:
    out = _run(fake_model_factory, "半年以内の動画を調べて", response=LLM_PLAIN)
    assert out["instruction"].published_after == frozen_now.now - timedelta(days=182)


def test_published_after_is_none_when_nothing_specifies(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "機械学習の動画を調べて", response=LLM_PLAIN)
    assert out["instruction"].published_after is None


# --- platform・ソート・トレンド・字幕言語 ---------------------------------------


def test_state_platform_beats_configurable(fake_model_factory: Any) -> None:
    out = _run(
        fake_model_factory,
        "機械学習の動画を調べて",
        platform="youtube",
        config=_config(platform="x"),
    )
    assert out["instruction"].platform == "youtube"


def test_configurable_platform_is_used_without_state(fake_model_factory: Any) -> None:
    out = _run(
        fake_model_factory,
        "機械学習の動画を調べて",
        platform=None,
        config=_config(platform="youtube"),
    )
    assert out["instruction"].platform == "youtube"


def test_configurable_sort_by_beats_state(fake_model_factory: Any) -> None:
    out = _run(
        fake_model_factory,
        "機械学習の動画を調べて",
        config=_config(sort_by="likes"),
        sort_by="relevance",
    )
    assert out["instruction"].sort_by == "likes"


def test_configurable_use_trends_and_transcript_language(fake_model_factory: Any) -> None:
    """`--trends` を削除した後は `transcript_language` だけを固定する（REM-003）。"""
    out = _run(
        fake_model_factory,
        "機械学習の動画を調べて",
        config=_config(transcript_language="en"),
    )
    assert out["instruction"].transcript_language == "en"


def test_defaults_for_language_and_sort(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "機械学習の動画を調べて")
    instruction = out["instruction"]
    assert instruction.transcript_language == "ja"
    assert instruction.sort_by == "relevance"
    assert instruction.raw_text == "機械学習の動画を調べて"


def test_list_content_is_stringified(fake_model_factory: Any) -> None:
    """`messages[-1].content` が本文ブロックのリストでも文字列化して扱う。

    LangChain のメッセージ `content` はテキスト以外に本文ブロックのリストを取りうる
    （マルチモーダル形式）。本ノードは以降を正規表現と `ResearchInstruction.raw_text: str`
    で扱うため、`str` 以外は文字列化する。文字列化を外すと `re.search` が `TypeError`
    で落ちる。件数抽出が文字列化後のテキストに効いていることも併せて固定する。
    """
    node_state: dict[str, Any] = {
        "messages": [HumanMessage(content=[{"type": "text", "text": "20件の動画を調べて"}])],
        "platform": "x",
    }
    with fake_model_factory.install({"parse_instruction": LLM_PLAIN}):
        out = parse_instruction(node_state, _config())

    raw_text = out["instruction"].raw_text
    assert isinstance(raw_text, str)
    assert "20件の動画を調べて" in raw_text
    assert out["instruction"].max_results == 20


# --- 進捗メッセージ -----------------------------------------------------------


def test_progress_messages_report_topic_and_count(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "20件の動画を調べて")
    contents = [m.content for m in out["messages"]]
    assert contents == [
        "[1/7] parse_instruction ... 開始",
        '[1/7] parse_instruction ... 完了（トピック: "LLM のトピック" / 件数: 20）',
    ]


# --- US2: 構造化出力とフォールバック（FR-009 / FR-011 / FR-012） ----------------
#
# 正常系（構造化出力が成功）とフォールバック（決定的解析）の**両方**を固定する。

#: 構造化出力で受け取る指示。`raw_text` はスキーマが必須とするため埋めるが、
#: ノードは状態から組み立てるため使わない（値が混ざらないことを下のテストで見る）。
_STRUCTURED_INSTRUCTION: dict[str, Any] = {
    "raw_text": "（LLM が返した指示文。ノードは使わない）",
    "topic": "LLM のトピック",
    "max_results": 3,
    "output": {"format": "json"},
}


def _run_structured(
    fake_model_factory: Any,
    raw: str,
    *,
    structured: dict[str, Any],
    response: str = LLM_JSON,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """構造化出力を注入して 1 回実行する（テキスト応答も注入しておく）。"""
    node_state: dict[str, Any] = {"messages": [HumanMessage(content=raw)], "platform": "x"}
    with fake_model_factory.install(
        {"parse_instruction": response}, structured={"parse_instruction": structured}
    ):
        return parse_instruction(node_state, config if config is not None else _config())


def test_structured_output_matches_the_fallback_parse(
    fake_model_factory: Any, capsys: Any
) -> None:
    """構造化出力が成功しても、同じ値なら既存の解析と同一の `ResearchInstruction`。

    LLM の推定で決まってよいのは `topic` / `max_results` / `output_format` だけ。
    `raw_text` / `platform` / `published_after` / `sort_by` は状態・Configuration・
    自然言語から決まる（構造化出力の値で揺れない）。
    """
    raw = "AI 動画の動向を調べたい"

    structured_out = _run_structured(
        fake_model_factory, raw, structured=_STRUCTURED_INSTRUCTION
    )
    assert "[補足]" not in capsys.readouterr().err

    fallback_out = _run(fake_model_factory, raw)

    assert structured_out["instruction"] == fallback_out["instruction"]
    assert structured_out["instruction"].raw_text == raw
    assert structured_out["instruction"].platform == "x"


def test_structured_failure_falls_back_and_is_reported(
    fake_model_factory: Any, capsys: Any
) -> None:
    """規定回数失敗したら JSON ブロック解析へ切り替え、補足行に残す（FR-011 / FR-012）。"""
    out = _run(fake_model_factory, "AI 動画の動向を調べたい")

    err = capsys.readouterr().err
    assert (
        "[補足] 構造化出力を取得できなかったため簡易解析へ切り替えました"
        "（OutputParserException）" in err
    )
    # フォールバックでも LLM の値は使える（既存の優先順位規則はそのまま）
    assert out["instruction"].topic == "LLM のトピック"
    # 試行回数 = 1 + retry_max（既定 3）。テキスト呼び出しは 1 回だけ
    assert len(fake_model_factory.structured_prompts_for("parse_instruction")) == 3
    assert len(fake_model_factory.prompts_for("parse_instruction")) == 1


def test_fallback_does_not_add_progress_lines(fake_model_factory: Any) -> None:
    """フォールバックは進捗行を増やさない（補足は stderr のみ。既定の出力は不変）。"""
    out = _run(fake_model_factory, "AI 動画の動向を調べたい")

    contents = [m.content for m in out["messages"]]
    assert len(contents) == 2
    assert not any("補足" in c or "構造化出力" in c for c in contents)


def test_retry_max_zero_makes_a_single_structured_attempt(fake_model_factory: Any) -> None:
    """`retry_max = 0` では 1 回で確定し、失敗なら即フォールバックする（FR-010 / FR-024）。"""
    node_state: dict[str, Any] = {
        "messages": [HumanMessage(content="AI 動画の動向を調べたい")],
        "platform": "x",
    }
    with fake_model_factory.install({"parse_instruction": LLM_PLAIN}):
        out = parse_instruction(node_state, _config(retry_max=0))

    assert len(fake_model_factory.structured_prompts_for("parse_instruction")) == 1
    assert out["instruction"].topic == "AI 動画の動向を調べたい"


def test_fallback_with_a_plain_response_uses_the_raw_text(fake_model_factory: Any) -> None:
    """JSON ブロックが無い応答にフォールバックしたら、トピックは指示本文になる。"""
    out = _run(fake_model_factory, "AI 動画の動向を調べたい", response=LLM_PLAIN)

    assert out["instruction"].topic == "AI 動画の動向を調べたい"


def test_structured_method_comes_from_the_configuration(fake_model_factory: Any) -> None:
    """`structured_method` の設定値が境界まで届く（既定値と同じでも配線を固定する）。"""
    _run_structured(
        fake_model_factory,
        "AI 動画の動向を調べたい",
        structured=_STRUCTURED_INSTRUCTION,
        config=_config(structured_method="function_calling"),
    )

    options = fake_model_factory.structured_options_for("parse_instruction")
    assert options and options[0]["method"] == "function_calling"
    assert options[0]["schema"] is ResearchInstruction
