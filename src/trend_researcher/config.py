"""設定解決の共通ヘルパ（パス解決と `.env` の読み込み。X / YouTube 共通）。

実行時設定の**型**は `configuration.Configuration` の 1 つである（SC-003）。この
モジュールはその型が使う下位ヘルパだけを持ち、設定値の宣言（同名フィールド）は
持たない。
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# リポジトリルートを解決
# src/trend_researcher/config.py → parents[0]=trend_researcher, [1]=src, [2]=リポジトリ直下
# 例: /home/takumi/github/trend-researcher
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(value: str) -> Path:
    """環境変数由来のパスを絶対パスに解決する。

    相対パスは「リポジトリ直下」基準で解決する。これにより
    `TR_CACHE_DIR=cache` のような設定が実行時 CWD に依存しなくなる。
    """
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path.resolve()


def _load_env_once() -> None:
    """プロジェクトの .env を一度だけ読み込む。"""
    env_path = _REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

