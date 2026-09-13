"""`cache.py` の単体テスト（中間成果物の JSON 永続化）。

固定する契約:

- 書き込み: 親ディレクトリを作成し、`<cache_dir>/<name>.json` を返す
- 書き込み: UTF-8 の生バイトで保存し、非 ASCII をエスケープしない
- 書き込み: JSON 化できない値は `default=str` で文字列化して落ちない
- 書き込み: 既存ファイルは上書きする（追記でも連結でもない）
- 読み戻し API を持たない（`read_json` は REM-001 で削除。実行時の参照が 0 だった）

一時ディレクトリ（`tmp_path`）だけを使い、実リポジトリの `cache/` を汚さない
（LAYOUT-003-4）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trend_researcher import cache
from trend_researcher.cache import write_json


def test_read_json_is_removed():
    """読み戻し API は存在しない（FR-010 / REM-001）。

    実行時の参照が 0 のまま残すと「使えるが使われていない API」として
    `TOTAL` と同じ二重定義の温床になる。書き込み（`write_json`）は残す。
    """
    assert not hasattr(cache, "read_json")
    assert hasattr(cache, "write_json")


def test_write_json_creates_parent_directory_and_returns_path(tmp_path: Path) -> None:
    cache_dir = tmp_path / "nested" / "cache"

    path = write_json(cache_dir, "report", {"topic": "テーマ"})

    assert path == cache_dir / "report.json"
    assert path.exists()
    assert cache_dir.is_dir()


def test_write_json_creates_missing_parent_directories_recursively(tmp_path: Path) -> None:
    """2 階層以上存在しなくても一気に作る（`parents=True`）。"""
    cache_dir = tmp_path / "a" / "b" / "c"

    write_json(cache_dir, "report", [])

    assert (cache_dir / "report.json").is_file()


def test_write_json_writes_raw_utf8_without_escaping_non_ascii(tmp_path: Path) -> None:
    """`ensure_ascii=False` なので、日本語はそのままのバイト列で保存される。"""
    path = write_json(tmp_path, "report", {"topic": "AI 動画のトレンド"})

    raw = path.read_bytes()
    assert "AI 動画のトレンド".encode() in raw
    assert b"\\u" not in raw


def test_write_json_is_readable_as_utf8_json(tmp_path: Path) -> None:
    path = write_json(tmp_path, "report", {"themes": ["自動化", "効率化"]})

    assert json.loads(path.read_text(encoding="utf-8")) == {"themes": ["自動化", "効率化"]}


def test_write_json_serializes_unsupported_values_with_str(tmp_path: Path) -> None:
    """`default=str` により、JSON 化できない値でも書き込みが失敗しない。"""
    path = write_json(tmp_path, "report", {"path": Path("/tmp/example"), "n": 3})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["path"] == str(Path("/tmp/example"))
    assert data["n"] == 3


def test_write_json_overwrites_existing_file(tmp_path: Path) -> None:
    write_json(tmp_path, "report", {"step": 1})
    path = write_json(tmp_path, "report", {"step": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"step": 2}


@pytest.mark.parametrize("data", [[], {}, {"a": [1, {"b": None}]}, "文字列", 0])
def test_write_json_accepts_any_json_serializable_value(tmp_path: Path, data: object) -> None:
    path = write_json(tmp_path, "payload", data)

    assert json.loads(path.read_text(encoding="utf-8")) == data
