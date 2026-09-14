"""評価基盤の採点ロジックの契約テスト（FR-038〜041 / FR-048 / FR-067 / FR-068 / SC-015 / SC-016 / SC-028）。

対象は `tests/eval/` の補助（採点スキーマ・判定ロジック・判定プロンプト・対応表）。
LLM は呼ばず、判定は**注入した呼び出し可能オブジェクト**で駆動する（実走をテストの
合否条件に含めない。FR-044 / SC-018）。

固定する契約:

- 観点は 5 つ以上を採点し、`correctness` は**対象外として明示**する（FR-038）
- 点数は 1〜5 で受け取り 0〜1 に正規化する。**値域の追加検査はしない**（FR-067 / SC-028）
- 型違い・必須項目の欠落は「取得失敗」にしてその観点だけ未採点にする（FR-039）
- 総合品質は 6 つの下位基準の平均（`None` は除外）で、判定モデルに総合点を聞かない
- 1 観点の失敗で全体を落とさない（FR-039 / FR-068）
- 提示順はランダム化でき、使った順序を結果に残す（FR-041）
- 比較は保存済みの結果だけで行い、生成も判定もしない（FR-041 / SC-016）
"""

from __future__ import annotations

import asyncio
import importlib
import random
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

#: リポジトリルート（`tests/unit/` から 2 つ上）。
REPO_ROOT = Path(__file__).resolve().parents[2]

#: `tests/eval/`（テストで固定する評価の補助。`test_*.py` は置かない）。
EVAL_DIR = REPO_ROOT / "tests" / "eval"

#: 生成側のプロンプト定義（制約が実在することの確認に使う。FR-048）。
PROMPTS_PATH = REPO_ROOT / "src" / "trend_researcher" / "prompts.py"

#: 判定プロンプトが自己記述する観点の識別子の行頭。
MARKER = "観点の識別子: "


def _eval_module(name: str) -> ModuleType:
    """`tests/eval/<name>.py` を読み込む（`tests/` はパッケージではないため）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    return importlib.import_module(f"tests.eval.{name}")


schemas = _eval_module("schemas")
evaluators = _eval_module("evaluators")
judge_prompts = _eval_module("judge_prompts")

#: 採点する観点の応答（偽の判定モデルが返すもの）。
SINGLE: dict[str, Any] = {"score": 4, "reason": "基準を満たしている"}


def _overall(**overrides: int) -> dict[str, Any]:
    """総合品質の応答（6 つの下位基準＋理由）。"""
    sub = dict.fromkeys(schemas.OVERALL_CRITERIA, 4)
    sub.update(overrides)
    return {**sub, "reason": "6 つの下位基準から判断した"}


def _payloads() -> dict[str, Any]:
    payloads: dict[str, Any] = {spec.axis: dict(SINGLE) for spec in evaluators.scored_axes()}
    payloads["overall_quality"] = _overall()
    return payloads


def _axis_of(prompt: str) -> str:
    """判定プロンプトから観点の識別子を取り出す（プロンプトが自己記述している）。"""
    line = next(line for line in prompt.splitlines() if line.startswith(MARKER))
    return line[len(MARKER) :].strip()


class RecordingJudge:
    """観点ごとの応答を返す偽の判定モデル（LLM を呼ばない。FR-044）。"""

    def __init__(
        self,
        payloads: Mapping[str, Any] | None = None,
        *,
        failures: Mapping[str, Exception] | None = None,
    ) -> None:
        self.payloads = dict(payloads or _payloads())
        self.failures = dict(failures or {})
        self.prompts: list[str] = []
        self.schemas: list[type[Any]] = []

    def __call__(self, prompt: str, schema: type[Any]) -> object:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        axis = _axis_of(prompt)
        if axis in self.failures:
            raise self.failures[axis]
        return self.payloads[axis]


def _score(
    payloads: Mapping[str, Any] | None = None,
    *,
    failures: Mapping[str, Exception] | None = None,
    order: Sequence[str] | None = None,
) -> tuple[dict[str, Any], RecordingJudge]:
    judge = RecordingJudge(payloads, failures=failures)
    return evaluators.score_report("## 見出し\n本文", judge=judge, order=order), judge


def _axes_of(result: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {row["axis"]: row for row in result["axes"]}


# --- 観点の構成（FR-038 / SC-015） -----------------------------------------


def test_axes_cover_at_least_five_scored_axes() -> None:
    """5 観点以上を実際に採点する（`correctness` の対象外表明と両立する）。"""
    axes = [spec.axis for spec in evaluators.scored_axes()]
    assert len(axes) >= 5
    assert len(set(axes)) == len(axes)  # 識別子の重複を作らない
    assert {"overall_quality", "relevance", "structure", "groundedness", "completeness"} <= set(
        axes
    )

    result, _ = _score()
    scored = [row for row in result["axes"] if row["score"] is not None]
    assert len(scored) >= 5


def test_correctness_is_recorded_as_out_of_scope() -> None:
    """正解（参照出力）が無い観点は黙って落とさず、対象外として記録する（FR-038 / FR-074）。"""
    spec = next(spec for spec in evaluators.AXIS_SPECS if spec.axis == "correctness")
    assert spec.excluded is True
    assert "正解" in spec.excluded_reason

    result, judge = _score()
    rows = _axes_of(result)
    assert rows["correctness"]["excluded"] is True
    assert rows["correctness"]["score"] is None
    assert result["excluded_axes"] == ["correctness"]
    # 対象外の観点は判定モデルへ投げない（投げる数は採点する観点の数）。
    assert len(judge.prompts) == len(evaluators.scored_axes())
    assert "correctness" not in {_axis_of(prompt) for prompt in judge.prompts}


# --- 受け取りと正規化（FR-039 / FR-067 / SC-028） --------------------------


@pytest.mark.parametrize(("score", "expected"), [(1, 0.0), (3, 0.5), (5, 1.0)])
def test_scores_are_normalized_to_zero_one(score: int, expected: float) -> None:
    """1〜5 を 0〜1 に正規化する（契約 §1 の `(score - 1) / 4`）。"""
    assert schemas.normalize_score(score) == pytest.approx(expected)


@pytest.mark.parametrize(("score", "expected"), [(7, 1.5), (0, -0.25), (-1, -0.5)])
def test_out_of_range_scores_are_recorded_without_checks(score: int, expected: float) -> None:
    """値域外の点数はそのまま記録し、実行を止めない（FR-067 / SC-028）。"""
    axis = schemas.to_scored_axis("relevance", {"score": score, "reason": "範囲外"})

    assert axis.score == score
    assert axis.normalized == pytest.approx(expected)
    assert axis.error is None


def test_the_schemas_declare_no_range_limits() -> None:
    """スキーマに `ge` / `le`（JSON Schema の minimum / maximum）を置かない（FR-067）。"""
    single = schemas.AxisScore.model_json_schema()["properties"]["score"]
    assert "minimum" not in single
    assert "maximum" not in single

    overall = schemas.OverallQualityScore.model_json_schema()["properties"]
    for name in schemas.OVERALL_CRITERIA:
        assert "minimum" not in overall[name]
        assert "maximum" not in overall[name]


@pytest.mark.parametrize(
    "payload",
    [
        {"score": "高い", "reason": "型違い（文字列）"},
        {"score": 4.5, "reason": "型違い（実数）"},
        {"score": 4},
        {"reason": "点数が欠落"},
        {"research_depth": 4, "reason": "下位基準が欠落"},
        "ただの文字列",
        None,
    ],
    ids=[
        "str-score",
        "float-score",
        "missing-score",
        "missing-reason",
        "broken-overall",
        "not-a-mapping",
        "none",
    ],
)
def test_type_mismatch_and_missing_fields_become_unscored(payload: object) -> None:
    """型違い・欠落は取得失敗にして未採点にする（例外は送出しない。FR-039 / FR-067）。"""
    axis = schemas.to_scored_axis("relevance", payload)

    assert axis.axis == "relevance"
    assert axis.score is None
    assert axis.normalized is None
    assert axis.error  # 理由が残る（黙って落とさない）


# --- 総合品質（FR-038 / 契約 §1） -----------------------------------------


def test_overall_quality_is_the_mean_of_the_sub_criteria() -> None:
    """総合品質は 6 観点（下位基準）の平均で、`None` は除外する。"""
    scores: dict[str, int | None] = dict.fromkeys(schemas.OVERALL_CRITERIA, 5)
    assert schemas.aggregate_sub_scores(scores) == pytest.approx(1.0)

    scores["writing_quality"] = 1
    # 6 基準のうち 5 つが 5（=1.0）で 1 つが 1（=0.0）。None が混ざっても除外して平均する。
    assert schemas.aggregate_sub_scores(scores) == pytest.approx(5 * 1.0 / 6)

    mixed: dict[str, int | None] = dict.fromkeys(schemas.OVERALL_CRITERIA, None)
    mixed["research_depth"] = 1
    assert schemas.aggregate_sub_scores(mixed) == pytest.approx(0.0)
    assert schemas.aggregate_sub_scores(dict.fromkeys(schemas.OVERALL_CRITERIA, None)) is None


def test_overall_quality_axis_records_the_sub_criteria() -> None:
    """総合品質の観点には 6 つの下位基準の生の点数と理由を残す（FR-038 / FR-039）。"""
    result, _ = _score()

    row = _axes_of(result)["overall_quality"]
    assert set(row["sub_scores"]) == set(schemas.OVERALL_CRITERIA)
    assert row["reason"] == "6 つの下位基準から判断した"
    assert result["overall_quality"] == pytest.approx(
        schemas.aggregate_sub_scores(row["sub_scores"])
    )
    assert row["score"] == pytest.approx(4.0)


def test_overall_quality_keeps_raw_scores_when_the_judge_is_extreme() -> None:
    """総合品質の集約は値域外でも止まらない（平均をそのまま写す。FR-067）。"""
    payloads = _payloads()
    payloads["overall_quality"] = _overall(research_depth=9, writing_quality=1)
    result, _ = _score(payloads)

    row = _axes_of(result)["overall_quality"]
    assert row["sub_scores"]["research_depth"] == 9
    assert row["normalized"] == pytest.approx(schemas.aggregate_sub_scores(row["sub_scores"]))


# --- レコードをまたいだ集約（FR-042 / SC-016） -----------------------------


def test_aggregating_records_averages_each_axis() -> None:
    """データセットの複数レコードは観点ごとに平均して 1 つの構成の点数にする。"""
    first, _ = _score()
    payloads = _payloads()
    payloads["relevance"] = {"score": 2, "reason": "関連性が低い"}
    second, _ = _score(payloads)

    aggregated = evaluators.aggregate_scored([first, second])
    rows = {row["axis"]: row for row in aggregated["axes"]}

    assert rows["relevance"]["normalized"] == pytest.approx((0.75 + 0.25) / 2)
    assert rows["relevance"]["scored_records"] == 2
    assert rows["overall_quality"]["normalized"] == pytest.approx(0.75)
    assert aggregated["overall_quality"] == pytest.approx(0.75)
    assert aggregated["scored_records"] == 2
    assert aggregated["excluded_axes"] == ["correctness"]

    # 1 件だけならその 1 件の値と一致する（集約が値を歪めない）。
    single = evaluators.aggregate_scored([first])
    assert {row["axis"]: row["normalized"] for row in single["axes"]} == {
        row["axis"]: row["normalized"] for row in first["axes"]
    }


def test_aggregating_records_excludes_unscored_and_out_of_scope() -> None:
    """未採点（判定の失敗）と対象外は平均から除外する（0 とみなさない）。"""
    ok, _ = _score()
    failed, _ = _score(failures={"relevance": RuntimeError("判定モデルが失敗")})

    rows = {row["axis"]: row for row in evaluators.aggregate_scored([ok, failed])["axes"]}

    assert rows["relevance"]["normalized"] == pytest.approx(0.75)
    assert rows["relevance"]["scored_records"] == 1
    assert rows["correctness"]["normalized"] is None
    assert rows["correctness"]["excluded"] is True

    with pytest.raises(ValueError, match="採点結果がありません"):
        evaluators.aggregate_scored([])


# --- 失敗の隔離（FR-039 / FR-068） -----------------------------------------


def test_one_axis_failure_does_not_stop_the_others() -> None:
    """1 観点の判定失敗・壊れた応答があっても、他の観点の採点を続ける（FR-039 / FR-068）。"""
    payloads = _payloads()
    payloads["structure"] = {"score": "壊れた応答", "reason": "型違い"}
    result, judge = _score(payloads, failures={"completeness": RuntimeError("判定モデルが失敗")})

    rows = _axes_of(result)
    assert rows["structure"]["error"]
    assert rows["completeness"]["error"]
    assert rows["relevance"]["score"] == 4
    assert rows["overall_quality"]["score"] == pytest.approx(4.0)
    # すべての採点対象の観点を 1 回ずつ呼ぶ（1 観点の失敗で打ち切らない）。
    assert len(judge.prompts) == len(evaluators.scored_axes())


def test_the_retry_rule_is_the_same_for_every_axis() -> None:
    """再試行の規則は全観点で同一（判定の回数は観点ごとに 1 回。FR-068）。"""
    _, judge = _score()
    axes = [_axis_of(prompt) for prompt in judge.prompts]

    assert sorted(axes) == sorted(spec.axis for spec in evaluators.scored_axes())


# --- 実走の入口が使う非同期経路（FR-041 / FR-045 / FR-068） -----------------


def test_the_async_path_uses_the_same_contract() -> None:
    """実走が使う非同期の採点も同じ契約（点数・順序・失敗の隔離。FR-045 / FR-068）。"""
    order = evaluators.shuffled_order(rng=random.Random(3))
    calls: list[str] = []

    async def judge(prompt: str, schema: type[Any]) -> object:
        calls.append(_axis_of(prompt))
        if _axis_of(prompt) == "groundedness":
            raise RuntimeError("判定モデルが失敗")
        payloads = _payloads()
        return payloads[_axis_of(prompt)]

    result = asyncio.run(evaluators.ascore_report("## 見出し\n本文", judge=judge, order=order))

    rows = _axes_of(result)
    assert calls == order  # 提示順どおりに 1 回ずつ呼ぶ
    assert rows["groundedness"]["error"]
    assert rows["relevance"]["normalized"] == pytest.approx(0.75)
    assert result["overall_quality"] == pytest.approx(0.75)


def test_the_sync_path_refuses_an_async_judge() -> None:
    """非同期の判定モデルを同期的な採点へ渡した場合は、記録せずその場で知らせる。"""

    async def judge(prompt: str, schema: type[Any]) -> object:
        return dict(SINGLE)

    with pytest.raises(TypeError, match="ascore_report"):
        evaluators.score_report("本文", judge=judge)


# --- 提示順（FR-041） ------------------------------------------------------


def test_axis_order_can_be_randomized_and_is_recorded() -> None:
    """提示順をランダム化し、使った順序を結果に残す（順序効果を隠さない。FR-041）。"""
    first = evaluators.shuffled_order(rng=random.Random(0))
    second = evaluators.shuffled_order(rng=random.Random(1234))
    natural = [spec.axis for spec in evaluators.scored_axes()]

    assert sorted(first) == sorted(natural)
    assert first != natural
    assert first != second

    result, judge = _score(order=first)
    assert result["axis_order"] == first
    assert [_axis_of(prompt) for prompt in judge.prompts] == first


def test_an_incomplete_order_is_rejected() -> None:
    """提示順はすべての観点を 1 回ずつ含める（黙って観点を落とさない）。"""
    with pytest.raises(ValueError, match="提示順"):
        evaluators.score_report("本文", judge=RecordingJudge(), order=["relevance"])


# --- 判定プロンプトと制約（FR-040 / FR-048） --------------------------------


def test_every_scored_axis_has_a_dedicated_prompt() -> None:
    """採点する観点には専用の判定プロンプトがある（FR-040）。"""
    axes = [spec.axis for spec in evaluators.scored_axes()]
    assert sorted(judge_prompts.JUDGE_PROMPTS) == sorted(axes)

    for axis in axes:
        prompt = judge_prompts.build_judge_prompt(axis, "## 見出し\n本文")
        assert prompt.count(MARKER) == 1
        assert _axis_of(prompt) == axis
        assert "## 見出し\n本文" in prompt


def test_the_judge_prompts_include_the_generation_constraints() -> None:
    """判定プロンプトは生成側のプロンプトが課す制約を反映する（FR-040 / FR-048）。"""
    prompts_text = PROMPTS_PATH.read_text(encoding="utf-8")

    for axis, constraints in judge_prompts.AXIS_CONSTRAINTS.items():
        assert constraints, f"{axis} は測る制約を持たない"
        prompt = judge_prompts.build_judge_prompt(axis, "本文")
        for constraint in constraints:
            assert judge_prompts.CONSTRAINTS[constraint] in prompt

    # 制約は生成側のプロンプトに実際に現れる（実在しない制約を作らない）。
    for constraint, evidence in judge_prompts.CONSTRAINT_EVIDENCE.items():
        assert constraint in judge_prompts.CONSTRAINTS
        for text in evidence:
            assert text in prompts_text, f"{constraint} の根拠 {text!r} が prompts.py にない"


def test_every_declared_constraint_is_measured_by_an_axis() -> None:
    """制約を書いたまま測らない状態を作らない（FR-048）。"""
    measured = {
        constraint
        for constraints in judge_prompts.AXIS_CONSTRAINTS.values()
        for constraint in constraints
    }

    assert measured == set(judge_prompts.CONSTRAINTS)


def test_the_axes_table_documents_axes_constraints_and_defects() -> None:
    """対応表が観点・制約・参照実装の実測済み欠陥 6 件を載せている（FR-074 / R-21）。

    対応表は文章なので、観点や制約を足したときに黙って古くならないよう、実装側の
    識別子が表に現れることを固定する（欠陥の一覧は 6 件であること）。
    """
    table = (EVAL_DIR / "axes.md").read_text(encoding="utf-8")

    missing_axes = [spec.axis for spec in evaluators.AXIS_SPECS if f"`{spec.axis}`" not in table]
    missing_constraints = [item for item in judge_prompts.CONSTRAINTS if f"`{item}`" not in table]

    assert not missing_axes, f"対応表に載っていない観点: {missing_axes}"
    assert not missing_constraints, f"対応表に載っていない制約: {missing_constraints}"
    # 参照実装の実測済み欠陥（R-21 の 6 件）が 1 つの表に並んでいる。
    defects = table.split("参照実装の実測済み欠陥とその扱い")[1]
    assert len(re.findall(r"^\| [1-6] \|", defects, flags=re.MULTILINE)) == 6


# --- 比較（FR-041 / SC-016） ----------------------------------------------


def _saved(axis_scores: Mapping[str, float], **overrides: Any) -> dict[str, Any]:
    """保存済みの結果（1 ファイル分）を組み立てる。"""
    record: dict[str, Any] = {
        "dataset": "tr-basic",
        "dataset_fingerprint": "abc123",
        "config_name": "baseline",
        "records": 2,
        "articles_empty": 0,
        "axes": [{"axis": axis, "normalized": value} for axis, value in axis_scores.items()],
    }
    record.update(overrides)
    return record


def test_comparison_uses_only_the_saved_scores() -> None:
    """比較は保存済みの点数だけで行う（生成も判定もしない。SC-016）。"""
    left = _saved({"relevance": 0.8, "structure": 0.4})
    right = _saved({"relevance": 0.5, "structure": 0.4}, config_name="candidate")

    result = evaluators.compare_results(left, right)

    rows = {row["axis"]: row for row in result["axes"]}
    assert rows["relevance"]["preference"] == "left"
    assert rows["structure"]["preference"] == "tie"
    assert rows["relevance"]["left"] == pytest.approx(0.8)
    assert rows["relevance"]["right"] == pytest.approx(0.5)
    assert result["winner"] == "left"
    assert result["comparable"] is True


def test_comparison_of_equal_scores_is_a_tie() -> None:
    """両方の提示順を入れ替えても差が無い場合は引き分けとして記録する（差異を消さない）。"""
    result = evaluators.compare_results(_saved({"relevance": 0.5}), _saved({"relevance": 0.5}))

    assert result["winner"] == "tie"
    assert result["ties"] == 1
    assert result["decisive"] == {"left": 0, "right": 0}


def test_comparison_flips_when_the_sides_are_swapped() -> None:
    """左右を入れ替えると選好の向きも入れ替わる（提示順に依存しない。FR-041）。"""
    left = _saved({"relevance": 0.8, "groundedness": 0.2})
    right = _saved({"relevance": 0.2, "groundedness": 0.8})

    forward = evaluators.compare_results(left, right)
    backward = evaluators.compare_results(right, left)

    assert forward["winner"] == "tie"  # 1 勝 1 敗
    assert backward["winner"] == forward["winner"]
    rows = {row["axis"]: row for row in backward["axes"]}
    assert rows["relevance"]["preference"] == "right"
    assert rows["groundedness"]["preference"] == "left"


def test_comparison_records_the_presentation_order() -> None:
    """比較でも提示順をランダム化し、使った順序を残す（FR-041 / SC-016）。"""
    left = _saved({"relevance": 0.8, "structure": 0.4, "completeness": 0.6})
    right = _saved({"relevance": 0.5, "structure": 0.4, "completeness": 0.6})

    result = evaluators.compare_results(left, right, rng=random.Random(7))

    assert sorted(result["axis_order"]) == ["completeness", "relevance", "structure"]
    assert [row["axis"] for row in result["axes"]] == result["axis_order"]


def test_comparison_refuses_two_different_datasets() -> None:
    """別のデータセットの結果は比較しない（同じ指標で測った結果だけを比べる。FR-073）。"""
    left = _saved({"relevance": 0.8})
    right = _saved({"relevance": 0.5}, dataset="tr-other", dataset_fingerprint="zzz999")

    with pytest.raises(evaluators.ComparisonError) as excinfo:
        evaluators.compare_results(left, right)

    assert "tr-basic" in str(excinfo.value)
    assert "tr-other" in str(excinfo.value)


def test_comparison_refuses_a_changed_dataset_fingerprint() -> None:
    """同じ名前でも中身（指紋）が変わった結果は同一視しない（FR-073 / SC-032）。"""
    left = _saved({"relevance": 0.8})
    right = _saved({"relevance": 0.5}, dataset_fingerprint="changed01")

    with pytest.raises(evaluators.ComparisonError, match="指紋"):
        evaluators.compare_results(left, right)


def test_comparison_with_an_empty_report_is_not_comparable() -> None:
    """片方の生成が失敗（レポートが空）したら勝敗を付けない（FR-041）。"""
    left = _saved({"relevance": 0.8}, articles_empty=2)
    right = _saved({"relevance": 0.5}, config_name="candidate")

    result = evaluators.compare_results(left, right)

    assert result["comparable"] is False
    assert result["winner"] is None
    assert "空" in result["reason"]
    assert "baseline" in result["reason"]


def test_comparison_without_scores_is_not_comparable() -> None:
    """採点結果が無い結果ファイルでは勝敗を付けない（判定をやり直さない）。"""
    result = evaluators.compare_results(_saved({}), _saved({}, config_name="candidate"))

    assert result["comparable"] is False
    assert result["winner"] is None
    assert "採点" in result["reason"]
