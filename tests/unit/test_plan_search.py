"""nodes/plan_search.py のクエリ生成契約テスト（FR-003 / FR-012）。

対象: 生成クエリからの年号・期間表現の除去、空になった行の破棄、X のみのクエリ数
上限、プロンプトへ渡すトピックの整形、投稿日フィルタの注記。LLM 応答は
`fake_model_factory` でノード単位に注入する（LAYOUT-004-4 / R-7）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest import mock

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


# --- US7: 生成後の自己点検（FR-049〜054 / 契約 §1） -------------------------


class _SequencedLLM:
    """呼び出しごとに違う応答を返すフェイク（生成と点検で応答を変える）。

    `fake_model_factory` はノード単位で 1 つの応答しか持たないため、生成と点検の
    出力を変えられない。点検の適用規則（契約 §1）を測るには順番つきの応答が要る。
    差し替える境界（`nodes.plan_search.build_model`）は既存のテストと同じ。
    """

    def __init__(self, responses: list[str], error_at: int | None = None) -> None:
        self.responses = list(responses)
        #: この番号（0 始まり）の呼び出しで例外を送出する（点検の失敗を作る）。
        self.error_at = error_at
        self.prompts: list[str] = []

    def invoke(self, prompt: str, *args: Any, **kwargs: Any) -> Any:
        return self._respond(prompt)

    async def ainvoke(self, prompt: str, *args: Any, **kwargs: Any) -> Any:
        """呼び出し境界（`tools/llm.py`）は `ainvoke` を使う（T078 で境界に載せた）。"""
        return self._respond(prompt)

    def _respond(self, prompt: str) -> Any:
        index = len(self.prompts)
        self.prompts.append(prompt)
        if self.error_at is not None and index == self.error_at:
            raise RuntimeError("点検が失敗しました")
        content = self.responses[min(index, len(self.responses) - 1)]
        return SimpleNamespace(content=content)


def _run_sequenced(
    responses: list[str],
    *,
    error_at: int | None = None,
    config: RunnableConfig | None = None,
    state: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], _SequencedLLM]:
    """生成と点検で応答を分けたフェイクで `plan_search` を 1 回実行する。"""
    llm = _SequencedLLM(responses, error_at=error_at)
    node_state = {"instruction": _instruction()} if state is None else state
    with mock.patch("trend_researcher.nodes.plan_search.build_model", return_value=llm):
        out = plan_search(node_state, _config() if config is None else config)
    return out, llm


def test_self_review_calls_the_model_twice():
    """`self_review` が真（既定）なら生成 1 ＋ 点検 1 の 2 回（FR-050 / SC-021）。"""
    _, llm = _run_sequenced(["クエリA\nクエリB", "クエリA\nクエリB"])

    assert len(llm.prompts) == 2


def test_self_review_can_be_turned_off():
    """`self_review = False` なら生成の 1 回だけ（SC-036）。"""
    _, llm = _run_sequenced(["クエリA\nクエリB"], config=_config(self_review=False))

    assert len(llm.prompts) == 1


def test_the_first_prompt_stays_the_generation_prompt(fake_model_factory):
    """点検を足しても `prompts_for(...)[0]` は生成プロンプトのまま（契約 §5-1/§5-2）。"""
    _run(fake_model_factory, "クエリA")

    prompts = fake_model_factory.prompts_for("plan_search")
    assert len(prompts) == 2
    assert "トピック: オタクの困りごと" in prompts[0]
    # 点検は生成の**後**。生成結果を材料として受け取る
    assert "クエリA" in prompts[1]


def test_the_review_does_not_repeat(fake_model_factory):
    """点検は 1 回だけでループしない（FR-050）。"""
    _run(fake_model_factory, "クエリA")

    assert len(fake_model_factory.prompts_for("plan_search")) == 2


def test_the_generation_prompt_is_not_the_review_prompt(fake_model_factory):
    """2 つのプロンプトが別物であること（取り違えると点検の意味が消える）。"""
    _run(fake_model_factory, "クエリA")

    generated, reviewed = fake_model_factory.prompts_for("plan_search")
    assert generated != reviewed


def test_rule_1_no_review_lines_keeps_the_generated_queries():
    """規則 1: 点検の出力が 0 行なら生成結果をそのまま採用（FR-051）。"""
    out, _ = _run_sequenced(["クエリA\nクエリB", ""])

    assert out["search_queries"] == ["クエリA", "クエリB"]


def test_rule_2_fewer_review_lines_are_filled_from_the_generated_queries():
    """規則 2: 点検が生成より少ないときは生成結果から補充する（D-1 / US7 シナリオ 1）。"""
    out, _ = _run_sequenced(["クエリA\nクエリB\nクエリC", "クエリA"])

    assert out["search_queries"] == ["クエリA", "クエリB", "クエリC"]


def test_rule_2_never_drops_below_the_generated_count():
    """規則 2: 補充の結果が生成の件数を下回らない。"""
    out, _ = _run_sequenced(["クエリA\nクエリB\nクエリC", "クエリB"])

    assert len(out["search_queries"]) == 3
    assert set(out["search_queries"]) == {"クエリA", "クエリB", "クエリC"}


def test_rule_3_more_review_lines_are_capped_for_x():
    """規則 3: 点検が生成より多いときは上限（X = 8）で切り詰める。"""
    reviewed = "\n".join(f"点検{i}" for i in range(1, 11))
    out, _ = _run_sequenced(["クエリA\nクエリB", reviewed])

    assert out["search_queries"] == [f"点検{i}" for i in range(1, 9)]


def test_rule_3_has_no_cap_for_youtube():
    """規則 3: YouTube は `max_search_queries = None` なので切り詰めない。"""
    reviewed = "\n".join(f"点検{i}" for i in range(1, 11))
    out, _ = _run_sequenced(
        ["クエリA", reviewed],
        config=_config(platform="youtube"),
        state={"instruction": _instruction(platform="youtube"), "platform": "youtube"},
    )

    assert out["search_queries"] == [f"点検{i}" for i in range(1, 11)]


def test_rule_4_duplicates_are_removed_keeping_the_first():
    """規則 4: 正規化後の重複は先に現れたものを残す。"""
    out, _ = _run_sequenced(["クエリA\nクエリB", "クエリA\nクエリA\nクエリA"])

    assert out["search_queries"] == ["クエリA", "クエリB"]


def test_rule_5_no_generated_queries_stays_empty():
    """規則 5: 生成が 0 件なら点検しても 0 件（固定件数まで増やさない。D-1）。"""
    out, _ = _run_sequenced(["", "点検1\n点検2"])

    assert out["search_queries"] == []


def test_a_review_failure_keeps_the_generated_queries():
    """点検が例外でも生成結果で継続する（FR-051。例外を送出しない）。"""
    out, _ = _run_sequenced(["クエリA\nクエリB"], error_at=1)

    assert out["search_queries"] == ["クエリA", "クエリB"]


def test_a_review_failure_is_reported_once_in_the_note(
    capsys: pytest.CaptureFixture[str],
):
    """点検の失敗は補足行に 1 行で出す（FR-051。stderr のみ）。"""
    _run_sequenced(["クエリA\nクエリB"], error_at=1)

    err = capsys.readouterr().err
    assert err.count("[補足] 検索クエリの点検に失敗") == 1
    assert "RuntimeError" in err


def test_no_review_note_when_the_review_succeeds(capsys: pytest.CaptureFixture[str]):
    """点検が成功したときは補足行を出さない（既定の入力の stderr を変えない。FR-035）。"""
    _run_sequenced(["クエリA\nクエリB", "クエリA\nクエリB"])

    assert "点検に失敗" not in capsys.readouterr().err


def test_the_review_result_is_not_used_when_self_review_is_off():
    """無効時は 2 つ目の応答を採用しない（呼び出しもしない）。"""
    out, llm = _run_sequenced(
        ["クエリA\nクエリB", "点検1\n点検2"], config=_config(self_review=False)
    )

    assert out["search_queries"] == ["クエリA", "クエリB"]
    assert len(llm.prompts) == 1


def test_the_note_does_not_grow_the_progress_messages(capsys: pytest.CaptureFixture[str]):
    """補足行は `messages`（進捗）に載せない（契約 §2-2 / FR-029）。"""
    out, _ = _run_sequenced(["クエリA\nクエリB"], error_at=1)

    assert "点検" not in "".join(m.content for m in out["messages"])
    capsys.readouterr()
