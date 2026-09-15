"""採点の受け取りスキーマと記録の形（FR-038 / FR-039 / FR-067）。

判定モデルから受け取る型（`AxisScore` / `OverallQualityScore`）と、結果に残す形
（`ScoredAxis`）を分ける。

**値域の宣言（`ge` / `le`）は置かない**（FR-067）。範囲外の点数はそのまま記録し、
評価の実行を止めない（記録に残るため集計時に気づける。SC-028）。型と必須項目は
このスキーマで保証し、型違い・欠落は「取得失敗」として**その観点だけ**未採点に
する（例外は送出しない。FR-039）。

観点の識別子は呼び出し側（`evaluators.AxisSpec`）が決める。判定モデルには申告
させない（どの観点を採点しているかは判定プロンプトが伝える）。
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field, ValidationError

#: 総合品質の下位基準（FR-038。参照実装の `OverallQualityScore` と同じ 6 つ）。
OVERALL_CRITERIA: tuple[str, ...] = (
    "research_depth",
    "source_quality",
    "analytical_rigor",
    "practical_value",
    "balance_and_objectivity",
    "writing_quality",
)


class AxisScore(BaseModel):
    """1 つの観点の点数（値域の制約を置かない: FR-067）。

    点数だけを残して理由を落とさないため、`reason` を必須にする（FR-039）。
    """

    score: int = Field(
        description="Integer score 1-5 (1 = doesn't meet at all, 5 = meets all criteria)"
    )
    reason: str = Field(
        description="The reason for the score, including specific examples from the report."
    )


class OverallQualityScore(BaseModel):
    """総合品質の 6 つの下位基準（FR-038）。

    総合点は 6 つの下位基準から**こちらで集約する**（判定モデルに総合点を
    聞かない。契約 §1）。
    """

    research_depth: int = Field(description="調査の深さ。Integer score 1-5")
    source_quality: int = Field(description="情報源の質。Integer score 1-5")
    analytical_rigor: int = Field(description="分析の厳密さ。Integer score 1-5")
    practical_value: int = Field(description="実用的価値。Integer score 1-5")
    balance_and_objectivity: int = Field(description="中立性と客観性。Integer score 1-5")
    writing_quality: int = Field(description="文章の質。Integer score 1-5")
    reason: str = Field(
        description="The reason for the scores, including specific examples from the report."
    )


class ScoredAxis(BaseModel):
    """結果に残す 1 観点の点数（未採点・対象外は `score` / `normalized` が `None`）。"""

    axis: str
    score: int | float | None = None
    normalized: float | None = None
    reason: str = ""
    #: 総合品質のみ: 6 つの下位基準の生の点数（FR-038）。
    sub_scores: dict[str, float] = Field(default_factory=dict)
    #: 正解（参照出力）を必要とする観点の「対象外」の表明（FR-038 / FR-074）。
    excluded: bool = False
    #: 取得失敗の理由（型違い・欠落・判定モデルの失敗）。
    error: str | None = None

    @property
    def scored(self) -> bool:
        """採点できたか（未採点・対象外は `False`）。"""
        return self.score is not None and not self.excluded


def normalize_score(score: float) -> float:
    """1〜5 の点数を 0〜1 に正規化する（`(score - 1) / 4`。契約 §1）。

    値域の検査はしない（FR-067）。範囲外の値はそのまま写し、実行を止めない。
    """
    return (score - 1) / 4


def aggregate_sub_scores(sub_scores: Mapping[str, float | None]) -> float | None:
    """下位基準の正規化値の平均（`None` は除外）。使える値が無ければ `None`。"""
    values = [normalize_score(value) for value in sub_scores.values() if value is not None]
    if not values:
        return None
    return statistics.fmean(values)


def to_scored_axis(axis: str, payload: object) -> ScoredAxis:
    """判定の応答を記録の形へ変換する（**例外を送出しない**。FR-039 / FR-067）。

    型違い・必須項目の欠落は「取得失敗」として未採点にし、`error` に理由を残す。
    """
    try:
        return _scored(axis, payload)
    except (ValueError, TypeError) as exc:  # `ValidationError` は `ValueError` の派生
        return ScoredAxis(axis=axis, error=f"判定結果を解釈できません: {_describe(exc)}")


def _scored(axis: str, payload: object) -> ScoredAxis:
    if isinstance(payload, OverallQualityScore):
        return _from_overall(axis, payload)
    if isinstance(payload, AxisScore):
        return _from_single(axis, payload)
    if isinstance(payload, Mapping):
        return _from_mapping(axis, payload)
    raise TypeError(f"判定結果がオブジェクトではありません（{type(payload).__name__}）")


def _from_mapping(axis: str, payload: Mapping[str, Any]) -> ScoredAxis:
    """素の辞書（構造化出力を使わない経路）を検証して取り込む。

    `strict=True` で型を確認する（`"5"` のような文字列を黙って数値にしない。
    FR-067）。
    """
    data = dict(payload)
    if set(OVERALL_CRITERIA) <= set(data):
        return _from_overall(axis, OverallQualityScore.model_validate(data, strict=True))
    return _from_single(axis, AxisScore.model_validate(data, strict=True))


def _from_single(axis: str, payload: AxisScore) -> ScoredAxis:
    return ScoredAxis(
        axis=axis,
        score=payload.score,
        normalized=normalize_score(payload.score),
        reason=payload.reason,
    )


def _from_overall(axis: str, payload: OverallQualityScore) -> ScoredAxis:
    sub_scores = {name: float(getattr(payload, name)) for name in OVERALL_CRITERIA}
    return ScoredAxis(
        axis=axis,
        score=statistics.fmean(sub_scores.values()),
        normalized=aggregate_sub_scores(sub_scores),
        reason=payload.reason,
        sub_scores=sub_scores,
    )


def _describe(exc: BaseException) -> str:
    """例外を 1 行の理由へまとめる（`ValidationError` は項目と理由を抜く）。"""
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "(ルート)"
        return f"{location}: {first.get('msg', '')}"
    return f"{type(exc).__name__}: {exc}"
