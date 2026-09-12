"""LLM 構築ヘルパ（OpenDeepResearch 設定を流用）。X / YouTube 共通。"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

Role = str

# 役割ごとの max_tokens（research.md R-3 を流用）
_ROLE_MAX_TOKENS: dict[str, int] = {
    "research": 10000,
    "summary": 8192,
    "final": 10000,
    "compression": 8192,
}


def build_model(role: Role = "research"):
    """指示された役割で LLM を構築する。

    OpenDeepResearch 同様 `openai:mimo-v2.5` を OpenAI 互換エンドポイントで利用。
    `configurable_fields` で実行時上書き（model/max_tokens/api_key）を許容。
    """
    load_dotenv()
    model = os.getenv("TR_MODEL", os.getenv("XTR_MODEL", os.getenv("YTR_MODEL", "openai:mimo-v2.5")))
    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "https://opencode.ai/zen/go/v1")
    max_tokens = _ROLE_MAX_TOKENS.get(role, 10000)

    return init_chat_model(
        model,
        max_tokens=max_tokens,
        api_key=api_key,
        base_url=base_url,
        tags=["langsmith:nostream"],
        configurable_fields=("model", "max_tokens", "api_key"),
    )
