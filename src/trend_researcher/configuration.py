"""LangGraph の config_schema に対応した設定クラス（実行時設定の唯一の入口）。"""

from __future__ import annotations

import os

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from trend_researcher.config import _REPO_ROOT, _load_env_once, _resolve_path


def resolve_env(name: str, *, default: str, env_prefix: str | None = None) -> str:
    """環境変数を `TR_{name}` → `{env_prefix}_{name}` → `default` の順で解決する。

    空文字は「未設定」として次の候補へフォールバックする（旧 `Config._env()` と
    同じ規則）。`env_prefix` は provider が**引数として**渡す（`XTR` / `YTR` の
    リテラルはこのモジュールに書かない。SET-003）。
    """
    candidates = [f"TR_{name}"]
    if env_prefix:
        candidates.append(f"{env_prefix}_{name}")
    for key in candidates:
        value = os.getenv(key)
        if value:
            return value
    return default


class Configuration(BaseModel):
    """LangGraph Studio UI でパラメータ変更に対応する設定クラス。

    実行時設定の唯一の型（SET-001）。環境変数と `.env` の解決は `load()` に集約し、
    ノードは `from_runnable_config()` で受け取った値だけを使う（SET-004）。
    """

    platform: str = Field(
        default="", description="対象プラットフォーム（未指定時は既定のプラットフォーム）"
    )
    output_format: str | None = Field(default=None, description="出力形式（markdown/json）。未設定時は LLM が判断。")
    max_results: int = Field(default=5, description="解析対象件数")
    sort_by: str = Field(default="relevance", description="選定基準（relevance/likes）")
    transcript_language: str = Field(default="ja", description="字幕優先言語")
    cache_dir: str | None = Field(default=None, description="中間成果物の永続化先")
    published_after: str | None = Field(
        default=None,
        description="投稿日下限（ISO 8601）。CLI --since からのみ設定。",
    )

    @classmethod
    def from_runnable_config(cls, config: RunnableConfig | None = None) -> Configuration:
        """RunnableConfig から設定値を取得して Configuration インスタンスを生成する。"""
        if config is None:
            return cls()
        configurable = config.get("configurable", {})
        return cls(**{k: v for k, v in configurable.items() if v is not None})

    @classmethod
    def load(cls, env_prefix: str | None = None) -> Configuration:
        """環境変数と `.env` から実行時設定を解決する（SET-002 / SET-008 / SET-010）。

        - 解決する項目は `max_results` / `transcript_language` / `cache_dir` の 3 つ。
          それ以外は「Studio / CLI の明示指定のみ」で環境変数からは読まない
          （フィールドを増やさない。SET-005）
        - 相対パス（`cache_dir`）は**リポジトリ直下**基準で絶対パス化する
        - 明示指定（CLI オプション等）は呼び出し側が `model_copy(update=...)` で
          後から与える。その値は `model_fields_set` に載るため「明示指定 > 環境変数」
          の順を保てる（SET-002 / SET-006）
        - `lru_cache` を持たない（毎回環境変数を読む。キャッシュの破棄が不要）
        """
        _load_env_once()
        cache_dir = _resolve_path(
            resolve_env("CACHE_DIR", default=str(_REPO_ROOT / "cache"), env_prefix=env_prefix)
        )
        return cls(
            max_results=int(resolve_env("MAX_RESULTS", default="5", env_prefix=env_prefix)),
            transcript_language=resolve_env("TRANSCRIPT_LANG", default="ja", env_prefix=env_prefix),
            cache_dir=str(cache_dir),
        )