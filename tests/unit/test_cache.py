"""`cache.py` の単体テスト（中間成果物の JSON 永続化）。

固定する契約:

- 書き込み: 親ディレクトリを作成し、`<cache_dir>/<name>.json` を返す
- 書き込み: UTF-8 の生バイトで保存し、非 ASCII をエスケープしない
- 書き込み: JSON 化できない値は `default=str` で文字列化して落ちない
- 書き込み: 既存ファイルは上書きする（追記でも連結でもない）
- 読み戻し: ファイルが無ければ例外ではなく `None`
- 読み戻し: 壊れた JSON は握りつぶさず例外にする（耐性は「欠落」のみ）

一時ディレクトリ（`tmp_path`）だけを使い、実リポジトリの `cache/` を汚さない
（LAYOUT-003-4）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trend_researcher.cache import read_json, write_json


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


def test_read_json_returns_none_when_file_is_missing(tmp_path: Path) -> None:
    """欠落は例外ではなく `None`（呼び出し側が存在確認なしで扱える）。"""
    assert read_json(tmp_path, "report") is None


def test_read_json_returns_none_when_directory_is_missing(tmp_path: Path) -> None:
    assert read_json(tmp_path / "not-created-yet", "report") is None


def test_read_json_round_trips_written_data(tmp_path: Path) -> None:
    original = {"topic": "日本語", "items": [1, 2, 3], "nested": {"ok": True}}
    write_json(tmp_path, "report", original)

    assert read_json(tmp_path, "report") == original


def test_read_json_reads_externally_written_file(tmp_path: Path) -> None:
    (tmp_path / "external.json").write_text('{"k": "値"}', encoding="utf-8")

    assert read_json(tmp_path, "external") == {"k": "値"}


def test_read_json_does_not_swallow_broken_json(tmp_path: Path) -> None:
    """壊れた JSON は `None` にせず例外にする（耐性は「欠落」だけに限定する）。"""
    (tmp_path / "broken.json").write_text("{壊れている", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        read_json(tmp_path, "broken")
