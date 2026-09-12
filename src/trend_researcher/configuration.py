"""LangGraph の config_schema に対応した設定クラス。"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field


class Configuration(BaseModel):
    """LangGraph Studio UI でパラメータ変更に対応する設定クラス。"""

    platform: str = Field(default="x", description="対象プラットフォーム（x/youtube）")
    output_format: str | None = Field(default=None, description="出力形式（markdown/json）。未設定時は LLM が判断。")
    max_results: int = Field(default=5, description="解析対象件数")
    sort_by: str = Field(default="relevance", description="選定基準（relevance/likes）")
    transcript_language: str = Field(default="ja", description="字幕優先言語")
    use_trends: bool = Field(default=False, description="トレンドワード探索モード")
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