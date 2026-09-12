"""nodes/plan_search.py のクエリ生成契約テスト（FR-003 / FR-012）。

対象: 生成クエリからの年号・期間表現の除去、空になった行の破棄、X のみのクエリ数
上限、プロンプトへ渡すトピックの整形、投稿日フィルタの注記。LLM 応答は
`fake_model_factory` でノード単位に注入する（LAYOUT-004-4 / R-7）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig

from trend_researcher.models import ResearchInstruction
from trend_researcher.nodes.plan_search import _clean_query, plan_search

#: 上限（8 件）を超える行数を持つ LLM 応答（X 用の切り詰めを検証する）。
TWELVE_LINES = "\n".join(f"クエリ{i}" for i in range(1, 13))

_RAW = "オタクの活動における困りごとを調査したい"


def _config(**configurable: Any) -> RunnableConfig:
    return {"configurable": configurable}


def _instruction(**overrides: Any) -> ResearchInstruction:
    base: dict[str, Any] = {"raw_text": _RAW, "platform": "x", "topic": "オタクの困りごと"}
    base.update(overrides)
    return ResearchInstruction(**base)


def _run(
    fake_model_factory: Any,
    response: str,
    *,
    platform: str | None = None,
    instruction: ResearchInstruction | None = None,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """`plan_search` をノード単位注入で 1 回実行し、出力 state を返す。"""
    node_state: dict[str, Any] = {"instruction": _instruction() if instruction is None else instruction}
    if platform is not None:
        node_state["platform"] = platform
    with fake_model_factory.install({"plan_search": response}):
        return plan_search(node_state, _config() if config is None else config)


# --- 年号・期間表現の除去（FR-012） ----------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # `\b` は日本語と数字の間で境界にならないため、年号が残っていた（G1）。
        ("2024年のオタク 困りごと", "オタク 困りごと"),
        ("オタク 2024 困りごと", "オタク 困りごと"),
        ("2024のAI", "AI"),
        ("2024年から2025年の動画", "動画"),
        ("2024年1月の動画", "動画"),
        # 期間表現の数字を伴う形（半角・全角・漢数字）を取りこぼしていた（G2）。
        ("最近のAI", "AI"),
        ("最近はAI ツール", "AI ツール"),
        ("3ヶ月以内のAI", "AI"),
        ("３ヶ月以内のAI", "AI"),
        ("三ヶ月以内のAI", "AI"),
        ("3カ月以内のAI", "AI"),
        ("半年以内のAI", "AI"),
        ("本年 の AI", "AI"),
        ("AI ツール 2024年 最新", "AI ツール 最新"),
    ],
)
def test_clean_query_removes_year_and_period(query: str, expected: str):
    assert _clean_query(query) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("月刊誌 特集", "月刊誌 特集"),  # 数字を伴わない「月」は期間表現ではない
        ("100日間チャレンジ", "100日間チャレンジ"),  # 日付は期間表現として扱わない
        ("12024 AI", "12024 AI"),  # 5 桁の数字の一部を年号と誤認しない
    ],
)
def test_clean_query_keeps_words_without_period_expression(query: str, expected: str):
    assert _clean_query(query) == expected


@pytest.mark.parametrize("query", ["2024", "（2024年）", "2024年"])
def test_clean_query_returns_empty_when_only_period(query: str):
    # 空になったクエリは呼び出し側で破棄される（空行と同じ扱い）。
    assert _clean_query(query) == ""


def test_clean_query_normalizes_quotes_and_spaces():
    assert _clean_query('"オタク 困りごと"') == "オタク 困りごと"
    assert _clean_query("AI  ツール   比較") == "AI ツール 比較"
    assert _clean_query("  オタク 困りごと  ") == "オタク 困りごと"


# --- クエリの生成と切り詰め（FR-003 / FR-012） ------------------------------


def test_x_returns_one_query_per_line(fake_model_factory):
    out = _run(fake_model_factory, "オタク 困りごと\n推し活 大変\n同人 在庫")
    assert out["search_queries"] == ["オタク 困りごと", "推し活 大変", "同人 在庫"]


def test_blank_and_cleaned_away_lines_are_dropped(fake_model_factory):
    out = _run(fake_model_factory, "2024 オタク\n\n   \n最近 AI\n2024年\n")
    assert out["search_queries"] == ["オタク", "AI"]


def test_x_caps_queries_at_eight(fake_model_factory):
    out = _run(fake_model_factory, TWELVE_LINES)
    assert out["search_queries"] == [f"クエリ{i}" for i in range(1, 9)]


def test_youtube_has_no_cap(fake_model_factory):
    out = _run(
        fake_model_factory,
        TWELVE_LINES,
        instruction=_instruction(platform="youtube"),
        config=_config(platform="youtube"),
    )
    assert len(out["search_queries"]) == 12


def test_cap_applies_when_instruction_platform_is_empty(fake_model_factory):
    # `instruction.platform or "x"` により、未設定は X として上限が適用される。
    out = _run(fake_model_factory, TWELVE_LINES, instruction=_instruction(platform=""))
    assert len(out["search_queries"]) == 8


def test_empty_response_yields_no_queries(fake_model_factory):
    out = _run(fake_model_factory, "")
    assert out["search_queries"] == []


# --- プロンプト（トピック整形と投稿日フィルタ） -----------------------------


def test_topic_has_parenthesized_part_removed(fake_model_factory):
    _run(fake_model_factory, "q", instruction=_instruction(topic="オタクの困りごと（2024年）"))
    assert "トピック: オタクの困りごと\n" in fake_model_factory.prompts_for("plan_search")[0]


def test_topic_keeps_original_when_cleaning_empties_it(fake_model_factory):
    _run(fake_model_factory, "q", instruction=_instruction(topic="（補足）"))
    assert "トピック: （補足）" in fake_model_factory.prompts_for("plan_search")[0]


def test_topic_falls_back_to_raw_text(fake_model_factory):
    _run(fake_model_factory, "q", instruction=_instruction(topic=""))
    assert f"トピック: {_RAW}" in fake_model_factory.prompts_for("plan_search")[0]


def test_date_hint_is_added_when_published_after_is_set(fake_model_factory):
    instruction = _instruction(published_after=datetime(2024, 1, 1, tzinfo=UTC))
    _run(fake_model_factory, "q", instruction=instruction)
    prompt = fake_model_factory.prompts_for("plan_search")[0]
    assert "※投稿日フィルタ（2024-01-01 以降）が別途適用されます。" in prompt
    assert "古い年号を付けずに" in prompt


def test_date_hint_is_absent_without_published_after(fake_model_factory):
    _run(fake_model_factory, "q")
    assert "投稿日フィルタ" not in fake_model_factory.prompts_for("plan_search")[0]


# --- 進捗と結線 -------------------------------------------------------------


def test_progress_messages_report_start_then_finish(fake_model_factory):
    out = _run(fake_model_factory, "オタク 困りごと\n推し活 大変")
    assert [m.content for m in out["messages"]] == [
        "[2/7] plan_search ... 開始（LLM が検索クエリを生成中）",
        "[2/7] plan_search ... 完了（クエリ 2 件: オタク 困りごと, 推し活 大変）",
    ]


def test_progress_reports_zero_queries(fake_model_factory):
    out = _run(fake_model_factory, "")
    assert [m.content for m in out["messages"]][-1] == "[2/7] plan_search ... 完了（クエリ 0 件: ）"
