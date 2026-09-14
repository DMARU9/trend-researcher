"""評価結果の記録（ファイル名・文脈・JSONL の読み書き・保存済み結果の比較）。

契約は `specs/003-pipeline-hardening-and-evaluation/contracts/evaluation-contract.md` §3。

- 1 行 1 レコードの JSONL。UTF-8、`ensure_ascii=False`（`cache.py` と同じ方針。FR-043）
- レコードの行は `{"id", "prompt", "article"}` の 3 項目（FR-071）
- 実行の文脈（設定・データセット名と指紋・コミット識別子・判定モデル名・
  トークン数と呼び出し回数）は同じファイルの**実行の行**に書く（FR-042 / FR-043 / FR-073）
- ファイル名は `{dataset}__{config_name}__{commit}__{model_slug}.jsonl`（FR-072）
- 既定の保存先は `artifacts/eval/`（追跡外）。`--out` / `TR_EVAL_OUT_DIR` で変更（FR-043）
- 書き込みは既定で**追記**。既存を置き換えるには `overwrite=True` が要る（SC-027）
- 比較は保存済みの結果を**名前で指定**して読み、生成も判定もしない（FR-041 / SC-016）
"""

from __future__ import annotations

import json
import os
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from tests.eval import evaluators
from trend_researcher.configuration import resolve_env

#: 既定の保存先（リポジトリの成果物置き場。追跡対象外。FR-043）。
DEFAULT_OUT_DIR = Path("artifacts/eval")

#: ファイル名の区切り（`{dataset}__{config_name}__{commit}__{model_slug}.jsonl`）。
SEPARATOR = "__"

#: 結果ファイルの拡張子。
SUFFIX = ".jsonl"

#: 実行の行とレコードの行を区別する印（実行の行のみが持つ。FR-071 の 3 項目を崩さない）。
RUN_KIND = "run"

#: 使用量が得られなかった場合の記録（FR-061。「不明」として記録し、実行は失敗させない）。
UNKNOWN = "不明"

#: 使用量の項目（FR-042 / FR-061）。
USAGE_KEYS: tuple[str, ...] = ("calls", "prompt_tokens", "completion_tokens", "total_tokens")


class ResultError(Exception):
    """結果ファイルを読み書きできない。"""


class MissingResultError(ResultError):
    """名前で指定した結果ファイルが存在しない（比較を開始しない。FR-041 のシナリオ）。"""


class Record(BaseModel):
    """結果の 1 行（指示文と成果物を識別子で結ぶ最小の組。FR-071）。

    `article` は生成に失敗した場合に空文字になりうる（空のレポートは比較不能として
    扱う。FR-041）。余分な項目は受け付けない（記録する文脈は実行の行に持つ）。
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    prompt: str
    article: str


def model_slug(model: str) -> str:
    """モデル名をファイル名に使える形へ変換する（`openai:mimo-v2.5` → `openai-mimo-v2.5`）。"""
    return re.sub(r"[^0-9A-Za-z._-]+", "-", model).strip("-")


def result_filename(*, dataset: str, config_name: str, commit: str, model: str) -> str:
    """結果ファイルの名前（FR-072: データセット名と対象の識別子を含む）。"""
    parts = (dataset, config_name, commit, model_slug(model))
    return SEPARATOR.join(parts) + SUFFIX


def resolve_out_dir(out_dir: str | Path | None = None) -> Path:
    """保存先を解決する（引数 → `TR_EVAL_OUT_DIR` → 既定 `artifacts/eval/`。FR-043）。"""
    if out_dir is not None:
        return Path(out_dir)
    return Path(resolve_env("EVAL_OUT_DIR", default=str(DEFAULT_OUT_DIR)))


def result_path(
    *,
    dataset: str,
    config_name: str,
    commit: str,
    model: str,
    out_dir: str | Path | None = None,
) -> Path:
    """結果ファイルのパス（保存先が未作成でもパスだけは返す）。"""
    directory = resolve_out_dir(out_dir)
    return directory / result_filename(
        dataset=dataset, config_name=config_name, commit=commit, model=model
    )


def usage_summary(usage: Mapping[str, Any] | None) -> dict[str, Any]:
    """使用量を結果へ記録する形にまとめる（FR-042 / FR-061）。

    使用量が得られない場合は項目を `None` にして `status` を「不明」にする。
    記録できないことを理由に実行を失敗させない。
    """
    if not usage:
        return {"status": UNKNOWN, **dict.fromkeys(USAGE_KEYS)}
    summary: dict[str, Any] = {"status": "取得"}
    for key in USAGE_KEYS:
        value = usage.get(key)
        summary[key] = value if isinstance(value, (int, float)) else None
    if all(summary[key] is None for key in USAGE_KEYS):
        summary["status"] = UNKNOWN
    return summary


@dataclass(frozen=True)
class RunContext:
    """1 回の評価実行の文脈（FR-042 / FR-043 / FR-069 / FR-073）。"""

    dataset: str
    dataset_fingerprint: str
    config_name: str
    commit: str
    platform: str
    model: str
    judge_model: str
    judge_model_is_generator: bool
    config: Mapping[str, Any] = field(default_factory=dict)
    axes: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    axis_order: Sequence[str] = field(default_factory=tuple)
    excluded_axes: Sequence[str] = field(default_factory=tuple)
    overall_quality: float | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    #: レコードごとの採点（レコードの識別子で結び付ける。FR-039 / FR-071）。
    scores: Mapping[str, Any] = field(default_factory=dict)

    @property
    def filename(self) -> str:
        """結果ファイルの名前。"""
        return result_filename(
            dataset=self.dataset,
            config_name=self.config_name,
            commit=self.commit,
            model=self.model,
        )

    def to_dict(self, *, records: int, articles_empty: int) -> dict[str, Any]:
        """実行の行（記録する文脈のすべて）。"""
        return {
            "kind": RUN_KIND,
            "dataset": self.dataset,
            "dataset_fingerprint": self.dataset_fingerprint,
            "config_name": self.config_name,
            "commit": self.commit,
            "platform": self.platform,
            "model": self.model,
            "judge_model": self.judge_model,
            "judge_model_is_generator": self.judge_model_is_generator,
            "config": dict(self.config),
            "axes": [dict(axis) for axis in self.axes],
            "axis_order": list(self.axis_order),
            "excluded_axes": list(self.excluded_axes),
            "overall_quality": self.overall_quality,
            "scores": {key: dict(value) for key, value in self.scores.items()},
            "usage": dict(self.usage),
            "records": records,
            "articles_empty": articles_empty,
        }


def record_line(record: Mapping[str, Any] | Record) -> str:
    """レコードを 1 行の JSON にする（3 項目・`ensure_ascii=False`。FR-071）。"""
    try:
        validated = record if isinstance(record, Record) else Record.model_validate(dict(record))
    except ValidationError as exc:
        raise ResultError(f"レコードの形が不正です: {exc}") from exc
    return json.dumps(validated.model_dump(), ensure_ascii=False)


def write_result(
    run: RunContext,
    records: Sequence[Mapping[str, Any] | Record],
    *,
    out_dir: str | Path | None = None,
    overwrite: bool = False,
) -> tuple[Path, int]:
    """結果を JSONL で書く（既定は追記。`overwrite=True` のときだけ置き換える。SC-027）。

    保存先のディレクトリが無ければ作成する（FR-043）。戻り値は書き込んだ
    ファイルのパスと、この呼び出しで書いたレコードの件数（FR-043 の「保存先と
    件数を知らせる」）。
    """
    path = result_path(
        dataset=run.dataset,
        config_name=run.config_name,
        commit=run.commit,
        model=run.model,
        out_dir=out_dir,
    )
    validated = [
        record if isinstance(record, Record) else Record.model_validate(dict(record))
        for record in records
    ]
    articles_empty = sum(1 for record in validated if not record.article)
    run_line = json.dumps(
        run.to_dict(records=len(validated), articles_empty=articles_empty),
        ensure_ascii=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    # 既存の結果は消さない。置き換えるのは `overwrite=True` を明示したときだけ。
    mode = "w" if overwrite or not path.exists() else "a"
    try:
        with path.open(mode, encoding="utf-8") as handle:
            handle.write(run_line + "\n")
            for record in validated:
                handle.write(record_line(record) + "\n")
    except OSError as exc:
        raise ResultError(f"結果を書き込めません: {path}: {exc}") from exc
    return path, len(validated)


def load_runs(path: str | Path) -> list[dict[str, Any]]:
    """結果ファイルの実行の行（追記された分だけ）を古い順に読む。"""
    runs = [line for line in _load_lines(path) if line.get("kind") == RUN_KIND]
    if not runs:
        raise ResultError(f"実行の文脈が見つかりません: {path}")
    return runs


def load_result(path: str | Path) -> dict[str, Any]:
    """最新の実行の文脈を読む（`compare_results` へそのまま渡せる形）。"""
    return load_runs(path)[-1]


def load_records(path: str | Path) -> list[Record]:
    """レコードの行を読む（実行の行は含めない）。"""
    records: list[Record] = []
    for line in _load_lines(path):
        if line.get("kind") == RUN_KIND or "id" not in line:
            continue
        try:
            records.append(Record.model_validate(line))
        except ValidationError as exc:
            raise ResultError(f"レコードの形が不正です: {path}: {exc}") from exc
    return records


def _load_lines(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise MissingResultError(f"結果ファイルがありません: {source}")
    lines: list[dict[str, Any]] = []
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResultError(f"結果ファイルを読めません: {source}: {exc}") from exc
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise ResultError(
                f"結果ファイルの {number} 行目が JSON ではありません: {source}"
            ) from exc
        if not isinstance(payload, dict):
            raise ResultError(f"結果ファイルの {number} 行目がオブジェクトではありません: {source}")
        lines.append(payload)
    return lines


def find_result(name: str | Path, *, out_dir: str | Path | None = None) -> Path:
    """名前（またはパス）で結果ファイルを解決する（FR-041 / SC-016）。

    見つからない場合は `MissingResultError`（**存在する片方だけで勝敗を付けない**。
    不足している対象を名指しする）。
    """
    given = Path(name)
    candidates = [given]
    if given.suffix != SUFFIX:
        candidates.append(given.with_suffix(SUFFIX))
    directory = resolve_out_dir(out_dir)
    candidates.extend([directory / given, directory / f"{given}{SUFFIX}"])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise MissingResultError(
        "結果ファイルが見つかりません: "
        + str(name)
        + "（探した場所: "
        + ", ".join(os.fspath(candidate) for candidate in candidates)
        + "）"
    )


def compare_saved(
    left: str | Path,
    right: str | Path,
    *,
    out_dir: str | Path | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """保存済みの 2 つの結果を**名前で指定**して比較する（FR-041 / SC-016）。

    生成も判定もしない（読むだけ）。片方が見つからなければ比較を開始しない。
    """
    left_path = find_result(left, out_dir=out_dir)
    right_path = find_result(right, out_dir=out_dir)
    result = evaluators.compare_results(load_result(left_path), load_result(right_path), rng=rng)
    result["files"] = {"left": os.fspath(left_path), "right": os.fspath(right_path)}
    return result
