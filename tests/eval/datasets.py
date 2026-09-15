"""名前付きデータセットの解決と指紋（FR-070 / FR-071 / FR-073 / SC-032）。

データセットは**指標の集合を同一に保つ単位**である（FR-070）。名前を変えると
比較対象が変わるため、結果には名前と内容の指紋の両方を記録する（FR-073）。

既定のデータセットはリポジトリ内の固定ファイル（`tests/eval/fixtures/tr-basic.json`）
として持ち、外部サービスを必須にしない（FR-045 / FR-070）。外部のデータセット名を
指定して到達できなかった場合は、**既定へ黙って切り替えず**失敗を明示する
（FR-070 のシナリオ）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

#: 既定のデータセット名。
DEFAULT_DATASET = "tr-basic"

#: 既定のフィクスチャ置き場（リポジトリ内の固定ファイル）。
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


class DatasetError(Exception):
    """データセットを解決できない（名前が無い・中身が壊れている）。"""


class DatasetEntry(BaseModel):
    """1 件の指示（結果のレコードに `article` を足した形の元。FR-071）。"""

    id: str = Field(description="結果のレコードと採点を結ぶ識別子")
    prompt: str = Field(description="パイプラインへ渡す指示文")


class Dataset(BaseModel):
    """名前付きの指示セット（名前と内容の指紋を結果へ記録する。FR-070 / FR-073）。"""

    name: str
    description: str = ""
    entries: list[DatasetEntry]

    @property
    def fingerprint(self) -> str:
        """内容の指紋（`id` と `prompt` を並べた SHA-256 の先頭 16 文字）。"""
        return fingerprint(self.entries)


def fingerprint(entries: Sequence[DatasetEntry]) -> str:
    """指示セットの内容の指紋を計算する（FR-073 / SC-032）。

    `id` と `prompt` を 1 件ずつ改行で区切って並べ、SHA-256 の先頭 16 文字を
    とる。名前だけでは中身の変化を検出できないため、内容から計算する。
    """
    joined = "\n".join(f"{entry.id}\n{entry.prompt}" for entry in entries)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def fixture_path(name: str = DEFAULT_DATASET, *, fixtures_dir: Path | None = None) -> Path:
    """データセット名に対応するフィクスチャのパス（`fixtures_dir` の下の `<name>.json`）。"""
    return (fixtures_dir or FIXTURE_DIR) / f"{name}.json"


def load_dataset(name: str = DEFAULT_DATASET, *, fixtures_dir: Path | None = None) -> Dataset:
    """名前でデータセットを読み込む（FR-070。

    到達できない名前は `DatasetError` にする（既定へ黙って切り替えない）。
    """
    path = fixture_path(name, fixtures_dir=fixtures_dir)
    if not path.is_file():
        raise DatasetError(
            f"データセット {name!r} が見つかりません: {path}（既定の {DEFAULT_DATASET!r} へは切り替えません）"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        dataset = Dataset.model_validate(payload)
    except (ValidationError, ValueError, OSError) as exc:
        raise DatasetError(f"データセット {name!r} を読み込めません: {path}: {exc}") from exc
    if dataset.name != name:
        raise DatasetError(
            f"データセットの名前が一致しません: 指定={name!r} / ファイル={dataset.name!r}（{path}）"
        )
    if not dataset.entries:
        raise DatasetError(f"データセット {name!r} に指示がありません: {path}")
    duplicated = _duplicated_ids(dataset.entries)
    if duplicated:
        raise DatasetError(f"データセット {name!r} に識別子の重複があります: {duplicated}")
    return dataset


def _duplicated_ids(entries: Sequence[DatasetEntry]) -> list[str]:
    seen: set[str] = set()
    duplicated: list[str] = []
    for entry in entries:
        if entry.id in seen and entry.id not in duplicated:
            duplicated.append(entry.id)
        seen.add(entry.id)
    return duplicated
