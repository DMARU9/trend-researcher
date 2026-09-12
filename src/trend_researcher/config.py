"""設定管理（OpenDeepResearch の設定を流用した形。X / YouTube 共通）。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

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


class Config(BaseModel):
    """Trend Researcher の実行設定（X / YouTube 共通）。"""

    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://opencode.ai/zen/go/v1")
    model: str = Field(default="openai:mimo-v2.5")
    max_results: int = Field(default=5)
    # いいね順ソート用に検索で取得するプールサイズ（X 用。最少値）
    search_pool_size: int = Field(default=50)
    # twscrape が使用するアカウント DB（X 用）
    accounts_db: Path = Field(default_factory=lambda: _resolve_path(str(_REPO_ROOT / "accounts.db")))
    # 字幕取得の優先言語（YouTube 用）
    transcript_language: str = Field(default="ja")
    cache_dir: Path = Field(default_factory=lambda: _resolve_path(str(_REPO_ROOT / "cache")))
    max_retries: int = Field(default=3)

    @classmethod
    def load(
        cls,
        *,
        platform: str = "x",
        cache_dir: str | None = None,
        max_results: int | None = None,
    ) -> Config:
        """環境変数／.env から設定を読み込む。

        Args:
            platform: "x" | "youtube"。環境変数プレフィックス（XTR_/YTR_）の解決に使用。
            cache_dir: CLI 等からの上書き（任意）。
            max_results: CLI 等からの上書き（任意）。
        """
        _load_env_once()
        # プラットフォーム固有プレフィックス。.env / tools/llm.py の表記に合わせる
        # （"x" -> "XTR", "youtube" -> "YTR"）。
        prefix = "XTR" if platform == "x" else "YTR"

        def _env(name: str, default: str) -> str:
            # 一般 TR_* を優先し、なければプラットフォーム固有（XTR_/YTR_）を見る
            return os.getenv(f"TR_{name}") or os.getenv(f"{prefix}_{name}") or default

        config = cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://opencode.ai/zen/go/v1"),
            model=_env("MODEL", "openai:mimo-v2.5"),
            max_results=int(_env("MAX_RESULTS", "5")),
            search_pool_size=int(_env("SEARCH_POOL_SIZE", "50")),
            accounts_db=_resolve_path(_env("ACCOUNTS_DB", str(_REPO_ROOT / "accounts.db"))),
            transcript_language=_env("TRANSCRIPT_LANG", "ja"),
            cache_dir=Path(cache_dir).expanduser().resolve()
            if cache_dir
            else _resolve_path(_env("CACHE_DIR", str(_REPO_ROOT / "cache"))),
            max_retries=int(_env("MAX_RETRIES", "3")),
        )
        if max_results is not None:
            config.max_results = max_results
        return config


@lru_cache(maxsize=1)
def get_config() -> Config:
    """プロセス内で共有する Config を取得（既定: x）。"""
    return Config.load()
