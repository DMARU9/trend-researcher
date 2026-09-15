"""観点ごとの判定と 2 構成の比較（FR-038〜041 / FR-068 / SC-015 / SC-016）。

判定モデルの呼び出しは**注入された呼び出し可能オブジェクト**（`Judge`）経由に
する。テストは LLM を呼ばずに判定ロジックを固定し、実走（`script/evaluate.py`）は
`tools/llm.py` の経路（`ainvoke_structured`）を注入する（FR-044 / FR-045）。

このモジュールは次を守る。

- 1 観点の失敗（例外・型違い・欠落）で全体を落とさない（FR-039 / FR-068）
- 点数は 1〜5 で受け取り 0〜1 に正規化する。値域の追加検査をしない（FR-067）
- 総合品質は 6 つの下位基準の平均（判定モデルに総合点を聞かない。契約 §1）
- 提示順はランダム化でき、使った順序を結果に残す（FR-041）
- 比較は保存済みの結果だけで行い、生成も判定もしない（FR-041 / SC-016）
"""

from __future__ import annotations

import inspect
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from tests.eval import judge_prompts
from tests.eval.schemas import AxisScore, OverallQualityScore, ScoredAxis, to_scored_axis

#: 判定モデルの呼び出し。(判定プロンプト, 受け取りスキーマ) を受けて結果を返す。
#: `ascore_report` に渡す場合は待機可能な値を返してよい（`tools/llm.py` の経路を
#: 注入すると非同期になる）。
Judge = Callable[[str, type[BaseModel]], object]


@dataclass(frozen=True)
class AxisSpec:
    """1 つの観点の定義（識別子・表示名・受け取りスキーマ・対象外の理由）。"""

    axis: str
    label: str
    schema: type[BaseModel]
    excluded: bool = False
    excluded_reason: str = ""

    @property
    def constraints(self) -> tuple[str, ...]:
        """この観点が測る生成側の制約（FR-040 / FR-048）。"""
        return judge_prompts.axis_constraints(self.axis)


#: 観点の一覧。参照実装の 6 評価を基盤に、`correctness` は**対象外として明示**する
#: （FR-038 / FR-074。正解（参照出力）を必要とし、対象の指示には一意の正解を
#: 用意できないため採点しない）。残る 6 観点を採点する。
AXIS_SPECS: tuple[AxisSpec, ...] = (
    AxisSpec("overall_quality", "総合品質（6 つの下位基準の集約）", OverallQualityScore),
    AxisSpec("relevance", "関連性", AxisScore),
    AxisSpec("structure", "構造", AxisScore),
    AxisSpec("groundedness", "根拠性", AxisScore),
    AxisSpec("completeness", "網羅性", AxisScore),
    AxisSpec("output_language", "出力言語の一致", AxisScore),
    AxisSpec(
        "correctness",
        "正しさ（対象外）",
        AxisScore,
        excluded=True,
        excluded_reason=(
            "参照出力（正解）を必要とするが、対象の指示（「〜のトレンドを 5 件」等）には"
            "一意の正解を用意できないため対象外（FR-038 / FR-074）"
        ),
    ),
)

#: 総合品質の観点の識別子（集約の対象）。
OVERALL_AXIS = "overall_quality"


class ComparisonError(Exception):
    """比較できない 2 件（データセットや指紋が違う）を指定した。"""


def scored_axes(specs: Sequence[AxisSpec] = AXIS_SPECS) -> list[AxisSpec]:
    """採点する観点（対象外を除く）。"""
    return [spec for spec in specs if not spec.excluded]


def excluded_axes(specs: Sequence[AxisSpec] = AXIS_SPECS) -> list[AxisSpec]:
    """対象外として明示する観点。"""
    return [spec for spec in specs if spec.excluded]


def shuffled_order(specs: Sequence[AxisSpec] = AXIS_SPECS, *, rng: random.Random) -> list[str]:
    """採点する観点の提示順をランダム化する（FR-041）。

    乱数は注入する（テストは種を固定して順序を固定できる）。対象外の観点は
    判定しないため含まない。
    """
    axes = [spec.axis for spec in scored_axes(specs)]
    rng.shuffle(axes)
    return axes


def evaluate_axis(spec: AxisSpec, report: str, judge: Judge) -> ScoredAxis:
    """1 観点を採点する（**例外を送出しない**。FR-039 / FR-068）。

    対象外の観点は判定モデルへ投げず、対象外であることを記録する。`judge` が
    非同期の場合は `ascore_report` を使う（同期的な採点に混ぜない）。
    """
    if spec.excluded:
        return ScoredAxis(axis=spec.axis, excluded=True, reason=spec.excluded_reason)
    try:
        payload = judge(judge_prompts.build_judge_prompt(spec.axis, report), spec.schema)
    except Exception as exc:  # noqa: BLE001 - 1 観点の失敗で全体を落とさない（FR-039）
        return ScoredAxis(axis=spec.axis, error=f"判定に失敗しました: {type(exc).__name__}")
    if inspect.isawaitable(payload):
        # 呼び出し側の取り違え（実走は `ascore_report` を使う）。判定結果として
        # 記録せず、その場で気づけるようにする。
        if inspect.iscoroutine(payload):
            payload.close()
        raise TypeError("判定モデルが非同期です。採点には ascore_report を使ってください")
    return to_scored_axis(spec.axis, payload)


async def aevaluate_axis(spec: AxisSpec, report: str, judge: Judge) -> ScoredAxis:
    """`evaluate_axis` の非同期版（実走の入口が `ainvoke_structured` を注入する）。

    失敗の扱いは同期版と同一（1 観点の失敗で全体を落とさない。FR-039 / FR-068）。
    """
    if spec.excluded:
        return ScoredAxis(axis=spec.axis, excluded=True, reason=spec.excluded_reason)
    try:
        payload = judge(judge_prompts.build_judge_prompt(spec.axis, report), spec.schema)
        if inspect.isawaitable(payload):
            payload = await payload
    except Exception as exc:  # noqa: BLE001 - 1 観点の失敗で全体を落とさない（FR-039）
        return ScoredAxis(axis=spec.axis, error=f"判定に失敗しました: {type(exc).__name__}")
    return to_scored_axis(spec.axis, payload)


def score_report(
    report: str,
    *,
    judge: Judge,
    specs: Sequence[AxisSpec] = AXIS_SPECS,
    order: Sequence[str] | None = None,
) -> dict[str, Any]:
    """レポートを全観点で採点し、結果に残す形へまとめる（同期）。

    `order` は採点する観点の提示順（FR-041）。省略時は `specs` の順。対象外の
    観点は順序に関係なく `excluded` として記録する。
    """
    axes = [evaluate_axis(spec, report, judge) for spec in _plan(specs, order)]
    return _assemble(axes)


async def ascore_report(
    report: str,
    *,
    judge: Judge,
    specs: Sequence[AxisSpec] = AXIS_SPECS,
    order: Sequence[str] | None = None,
) -> dict[str, Any]:
    """`score_report` の非同期版（1 観点ずつ順に判定する。FR-041 / FR-068）。

    提示順は `order` に従い、判定は**逐次**行う（観点ごとに独立した呼び出しで
    あることを結果から読み取れるようにする）。
    """
    axes = [await aevaluate_axis(spec, report, judge) for spec in _plan(specs, order)]
    return _assemble(axes)


def _plan(specs: Sequence[AxisSpec], order: Sequence[str] | None) -> list[AxisSpec]:
    """採点する順に並べた観点（採点する観点 → 対象外の観点）。"""
    return _ordered(scored_axes(specs), order) + excluded_axes(specs)


def _assemble(axes: Sequence[ScoredAxis]) -> dict[str, Any]:
    """採点した観点を結果に残す形へまとめる。"""
    return {
        "axes": [axis.model_dump() for axis in axes],
        "overall_quality": overall_quality(axes),
        "axis_order": [axis.axis for axis in axes if not axis.excluded],
        "excluded_axes": [axis.axis for axis in axes if axis.excluded],
    }


def overall_quality(axes: Sequence[ScoredAxis]) -> float | None:
    """総合品質（`overall_quality` 観点の正規化値）。未採点なら `None`。"""
    overall = next((axis for axis in axes if axis.axis == OVERALL_AXIS), None)
    if overall is None:
        return None
    return overall.normalized


def aggregate_scored(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """複数レコードの採点を観点ごとに平均する（比較と記録の単位。FR-042 / SC-016）。

    データセットの全レコードを採点した結果を 1 つの構成の点数へまとめる。未採点
    （型違い・欠落・判定の失敗）と対象外の観点は除外して平均する（`None` を 0 と
    みなさない）。提示順と対象外の観点は各レコードで同一なので先頭から取る。
    """
    if not results:
        raise ValueError("採点結果がありません（1 件以上を渡してください）")
    first = results[0]
    axes: list[dict[str, Any]] = []
    for row in first["axes"]:
        axis = str(row["axis"])
        values = [
            value
            for value in (_normalized_at(result, axis) for result in results)
            if value is not None
        ]
        axes.append(
            {
                "axis": axis,
                "normalized": statistics.fmean(values) if values else None,
                "scored_records": len(values),
                "excluded": bool(row.get("excluded")),
            }
        )
    overall = next((row["normalized"] for row in axes if row["axis"] == OVERALL_AXIS), None)
    return {
        "axes": axes,
        "overall_quality": overall,
        "axis_order": list(first.get("axis_order", ())),
        "excluded_axes": list(first.get("excluded_axes", ())),
        "scored_records": len(results),
    }


def _normalized_at(result: Mapping[str, Any], axis: str) -> float | None:
    """1 レコードの採点結果から観点の正規化値（未採点・対象外は `None`）。"""
    row = next((row for row in result.get("axes", ()) if row.get("axis") == axis), None)
    if row is None:
        return None
    value = row.get("normalized")
    return float(value) if isinstance(value, (int, float)) else None


def _ordered(specs: Sequence[AxisSpec], order: Sequence[str] | None) -> list[AxisSpec]:
    """提示順どおりに並べ替える（観点の取りこぼし・重複は拒否する）。"""
    if order is None:
        return list(specs)
    by_axis = {spec.axis: spec for spec in specs}
    if sorted(order) != sorted(by_axis):
        raise ValueError(
            "提示順はすべての観点を 1 回ずつ含める必要があります: "
            f"提示順={sorted(order)} / 観点={sorted(by_axis)}"
        )
    return [by_axis[axis] for axis in order]


# --- 2 構成の比較（保存済みの結果だけで行う。FR-041 / SC-016） ---------------


def compare_results(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """保存済みの 2 つの結果を比較する（**生成も判定もしない**。SC-016）。

    比較できるのは同じデータセット（同じ指紋）で測った結果だけである。片方の
    生成が失敗している（レポートが空）場合と採点結果が無い場合は、勝敗を
    付けずに理由を残す（FR-041）。提示順は `rng` を与えたときだけランダム化し、
    使った順序を `axis_order` に残す。
    """
    _check_same_dataset(left, right)
    dataset = {
        "dataset": left.get("dataset"),
        "dataset_fingerprint": left.get("dataset_fingerprint"),
        "configs": {"left": left.get("config_name"), "right": right.get("config_name")},
    }
    reason = _incomparable_reason(left, right)
    if reason is not None:
        return {
            "comparable": False,
            "reason": reason,
            "winner": None,
            "axes": [],
            "axis_order": [],
            "decisive": {"left": 0, "right": 0},
            "ties": 0,
            **dataset,
        }

    order = _comparison_axes(left, right, rng=rng)
    rows = [_compare_axis(axis, left, right) for axis in order]
    decisive = {
        "left": sum(row["preference"] == "left" for row in rows),
        "right": sum(row["preference"] == "right" for row in rows),
    }
    return {
        "comparable": True,
        "reason": None,
        "winner": _winner(decisive),
        "axes": rows,
        "axis_order": order,
        "decisive": decisive,
        "ties": sum(row["preference"] == "tie" for row in rows),
        **dataset,
    }


def _check_same_dataset(left: Mapping[str, Any], right: Mapping[str, Any]) -> None:
    """データセット名と指紋が一致することを確かめる（FR-073 / SC-032）。"""
    if left.get("dataset") != right.get("dataset"):
        raise ComparisonError(
            "データセットが異なる結果は比較できません: "
            f"left={left.get('dataset')!r} / right={right.get('dataset')!r}"
        )
    if left.get("dataset_fingerprint") != right.get("dataset_fingerprint"):
        raise ComparisonError(
            "データセットの指紋が異なる結果は比較できません（中身が変わっています）: "
            f"left={left.get('dataset_fingerprint')!r} / right={right.get('dataset_fingerprint')!r}"
        )


def _incomparable_reason(left: Mapping[str, Any], right: Mapping[str, Any]) -> str | None:
    """勝敗を付けない条件とその理由（付けられる場合は `None`）。"""
    for side, record in (("left", left), ("right", right)):
        empty = int(record.get("articles_empty") or 0)
        total = int(record.get("records") or 0)
        if total and empty >= total:
            return f"生成に失敗した結果とは比較できません（{side}: {record.get('config_name')} のレポートが空）"
    if not left.get("axes") or not right.get("axes"):
        return f"採点結果が無い結果とは比較できません（{left.get('config_name')} / {right.get('config_name')}）"
    return None


def _comparison_axes(
    left: Mapping[str, Any], right: Mapping[str, Any], *, rng: random.Random | None
) -> list[str]:
    """比較する観点（両方に現れる観点。`rng` があれば提示順をランダム化）。"""
    right_axes = {row["axis"] for row in right["axes"]}
    axes = sorted(row["axis"] for row in left["axes"] if row["axis"] in right_axes)
    if rng is not None:
        rng.shuffle(axes)
    return axes


def _compare_axis(axis: str, left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """1 観点の選好（勝敗を付けられない場合は `tie`）。"""
    left_score = _normalized(left, axis)
    right_score = _normalized(right, axis)
    if left_score is None or right_score is None:
        preference = "tie"
    elif left_score > right_score:
        preference = "left"
    elif right_score > left_score:
        preference = "right"
    else:
        preference = "tie"
    return {
        "axis": axis,
        "left": left_score,
        "right": right_score,
        "preference": preference,
    }


def _normalized(record: Mapping[str, Any], axis: str) -> float | None:
    row = next((row for row in record["axes"] if row["axis"] == axis), None)
    if row is None:
        return None
    value = row.get("normalized")
    return float(value) if isinstance(value, (int, float)) else None


def _winner(decisive: Mapping[str, int]) -> str:
    """勝敗を付ける観点の多数決（同数・0 件は引き分け。FR-041）。"""
    if decisive["left"] > decisive["right"]:
        return "left"
    if decisive["right"] > decisive["left"]:
        return "right"
    return "tie"
