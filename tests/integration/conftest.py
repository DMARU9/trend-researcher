"""`tests/integration/` 層に固有のフィクスチャ（LAYOUT-001-5）。

層固有のフィクスチャは各層の `conftest.py` に置く（憲法 原則 I の配置規約）。
`tests/conftest.py` がスイート全体の共有フィクスチャ（境界モック・非決定性の
固定）を担うのに対し、このモジュールは統合層だけが必要とする実行基盤
（CLI のサブプロセス起動など）を置く場所である。
"""

from __future__ import annotations
