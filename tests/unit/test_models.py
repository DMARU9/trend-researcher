"""models.py の単体テスト（統合モデル）。

ここはモデルの**宣言**（既定値）を固定する層。出典（`sources`）が候補の URL から
構築されることは `nodes/compile_report.py` の責務であり、`tests/unit/test_compile_report.py`
がノード経由で検証する（LAYOUT-005-5: 同一の振る舞いを複数箇所で検証しない）。
旧 `test_report_sources_invariant` は断言が構築式（`[c.url for c in cands]`）と同一の
恒真アサートで、`compile_report` の出典構築を空にしても緑のままだった（LAYOUT-005-3）。
"""

from __future__ import annotations

import operator
from typing import Annotated, get_args, get_origin, get_type_hints

import pytest
from pydantic import ValidationError

from trend_researcher.models import (
    Candidate,
    CommonTheme,
    CompressedSource,
    Degradation,
    Failure,
    ModelUsage,
    OutputFormat,
    OutputSpec,
    ResearchInstruction,
    ResearchReport,
)
from trend_researcher.state import AgentInputState, AgentState


def test_output_spec_has_no_table_for():
    """`table_for` は宣言されていない（FR-008 / REM-004）。

    実行時に誰も読まないフィールドを残すと「どちらが正か」が読めなくなる。
    プラットフォームの型名は `provider.name` が担う。
    """
    assert "table_for" not in OutputSpec.model_fields


def test_research_instruction_has_no_use_trends():
    """`use_trends` は宣言されていない（FR-009 / REM-003）。"""
    assert "use_trends" not in ResearchInstruction.model_fields


def test_candidate_defaults():
    c = Candidate(platform="x", id="1", text="hello")
    assert c.relevance_rank == 0
    assert c.like_count is None
    assert c.url == ""


def test_research_instruction_defaults():
    inst = ResearchInstruction(raw_text="テスト指示", platform="youtube")
    assert inst.max_results == 5
    assert inst.output.format == OutputFormat.MARKDOWN
    assert inst.topic == ""
    assert inst.platform == "youtube"


def test_common_theme_fields():
    t = CommonTheme(theme="abc", supporting_ids=["1", "2"], example_quotes=["x"])
    assert t.theme == "abc"
    assert t.supporting_ids == ["1", "2"]


def test_report_defaults_are_empty_collections():
    """指示以外を渡さないレポートは出典・候補・要約・テーマ・備考がすべて空。

    既定にダミー要素を混ぜると、候補が 0 件のときに存在しない出典が
    レポートへ載る（`render_markdown` の「## 出典」が嘘になる）。
    """
    report = ResearchReport(instruction=ResearchInstruction(raw_text="x"))

    assert report.sources == []
    assert report.candidates == []
    assert report.analyses == []
    assert report.common_themes == []
    assert report.notes == []


def test_common_theme_description_defaults_to_empty_string():
    """説明のないテーマは空文字で描画される（`None` を混ぜない）。

    `compile_report._render_common_themes` は `t.description` をそのまま表へ
    埋めるため、既定が空文字でないと説明のないテーマの行の説明列が埋まる。
    """
    assert CommonTheme(theme="t").description == ""


# --- 追加モデル（data-model §3） --------------------------------------------


def test_compressed_source_requires_every_field():
    """`CompressedSource` の 5 項目はすべて必須（既定値で埋めない）。

    既定値を持たせると、記録もれが「0 文字を圧縮した」という嘘の観測になる。
    """
    with pytest.raises(ValidationError):
        CompressedSource(source_id="x1", input_chars=30000)  # type: ignore[call-arg]


def test_compressed_source_keeps_the_measured_sizes():
    src = CompressedSource(
        source_id="x1", input_chars=30000, output_chars=1200, applied=True, reason="compressed"
    )

    assert src.source_id == "x1"
    assert src.input_chars == 30000
    assert src.output_chars == 1200
    assert src.applied is True
    assert src.reason == "compressed"


def test_compressed_source_records_the_failure_reason_without_applying():
    """圧縮失敗時も記録する（`applied=False` ＋ 理由）。

    失敗の理由は `reason` に入り、実行は取代（生素材の切り詰め）で続く。
    """
    src = CompressedSource(
        source_id="x1", input_chars=30000, output_chars=20000, applied=False, reason="timeout"
    )

    assert src.applied is False
    assert src.reason == "timeout"


def test_degradation_requires_a_real_shrink():
    """縮小しない段は記録できない（`after_chars < before_chars`。R-4 の停止条件 2）。

    同じ長さの段を許すと「縮退した」という記録だけが増えて入力が減らない。
    """
    base = {"node_name": "analyze_content", "stage": 1, "reason": "token_limit", "limit_known": True}

    with pytest.raises(ValidationError):
        Degradation(**base, before_chars=100, after_chars=100)
    with pytest.raises(ValidationError):
        Degradation(**base, before_chars=100, after_chars=120)

    shrunk = Degradation(**base, before_chars=100, after_chars=90)
    assert shrunk.after_chars < shrunk.before_chars


def test_degradation_reason_is_pinned_to_the_token_limit():
    """縮退の理由は `token_limit` に固定される（圧縮と区別する。FR-019）。"""
    degraded = Degradation(
        node_name="analyze_content",
        stage=2,
        before_chars=100,
        after_chars=90,
        reason="token_limit",
        limit_known=False,
    )

    assert degraded.stage == 2
    assert degraded.limit_known is False


def test_failure_kind_is_restricted_to_the_two_stages():
    """`Failure.kind` は個別解析と追加文脈だけ（他の段は失敗を記録しない）。"""
    failure = Failure(kind="analysis", id="x1", error_type="RuntimeError", message="boom")
    assert failure.kind == "analysis"

    with pytest.raises(ValidationError):
        Failure(kind="search", id="x1", error_type="RuntimeError", message="boom")


def test_failure_requires_every_field():
    """無言の欠落を禁止するため、失敗の記録は項目を埋めて作る（FR-021）。"""
    with pytest.raises(ValidationError):
        Failure(kind="analysis", id="x1")  # type: ignore[call-arg]


def test_model_usage_allows_unknown_token_counts():
    """使用量を返さないエンドポイントでは 3 つのトークン数が `None` になる（FR-061）。

    `None` を 0 に潰すと「0 トークンで呼んだ」という嘘の集計になる。
    """
    usage = ModelUsage(
        node_name="analyze_content",
        role="research",
        model="openai:mimo-v2.5",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        structured=True,
    )

    assert usage.total_tokens is None
    assert usage.structured is True
    assert usage.model == "openai:mimo-v2.5"


def test_model_usage_keeps_the_numbers_when_present():
    usage = ModelUsage(
        node_name="plan_search",
        role="research",
        model="openai:mimo-v2.5",
        input_tokens=120,
        output_tokens=30,
        total_tokens=150,
        structured=False,
    )

    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (120, 30, 150)


# --- 状態フィールドの reducer（data-model §2.1） ---------------------------


def test_agent_state_declares_the_four_observation_fields():
    hints = get_type_hints(AgentState, include_extras=True)

    assert {"compressed", "degradations", "failures", "usage"} <= set(hints)
    assert hints["compressed"] == list[CompressedSource]
    assert hints["degradations"] == list[Degradation]
    assert hints["failures"] == list[Failure]


def test_usage_field_merges_by_concatenation():
    """`usage` だけが `operator.add` の reducer を持つ（他の 3 つは後勝ち）。

    **非空虚性**: 3 つを `not Annotated` で固定するため、誤って reducer を足しても落ちる。
    """
    hints = get_type_hints(AgentState, include_extras=True)
    usage = hints["usage"]

    assert get_origin(usage) is Annotated
    assert get_args(usage)[0] == list[ModelUsage]
    assert get_args(usage)[1] is operator.add

    for plain in ("compressed", "degradations", "failures"):
        assert get_origin(hints[plain]) is not Annotated, plain


def test_agent_input_state_stays_three_fields():
    """入力ステートは変えない（評価の実走は 3 項目だけを使う。FR-065）。"""
    hints = get_type_hints(AgentInputState)

    assert set(hints) == {"messages", "platform", "max_results"}
