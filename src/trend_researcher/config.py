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


def load_env() -> None:
    """プロジェクトの `.env` を読み込む（`load_dotenv` を呼ぶ唯一の場所）。

    環境変数・`.env` の解決は実行時設定の型に集約する（FR-013 / SET-002）。この関数が
    その読み込みの 1 経路であり、`Configuration.load()` と LLM 構築の境界
    （`tools/llm.py`）の両方が呼ぶ。後者が呼ぶのは、Studio のように
    `Configuration.load()` を通らない実行でも `OPENAI_API_KEY` などを `.env` から
    解決できるようにするためである（SET-009）。

    `load_dotenv` は既定で既存の環境変数を上書きしない（`override=False`）ため、
    複数回呼ばれても実行中の値は変わらない。
    """
    env_path = _REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

