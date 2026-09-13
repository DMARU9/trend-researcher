"""中間成果物の JSON 永続化（DB なし、FR-012 対応）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(cache_dir: Path, name: str, data: Any) -> Path:
    """cache_dir 配下に name.json を書き出す。

    Args:
        cache_dir: キャッシュディレクトリ。
        name: ファイル名（拡張子なし）。
        data: シリアライズ可能なデータ。

    Returns:
        書き出したファイルのパス。
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return path
