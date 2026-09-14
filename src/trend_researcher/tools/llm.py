"""LLM 構築ヘルパ（OpenDeepResearch 設定を流用）。X / YouTube 共通。"""

from __future__ import annotations

import os
import uuid

from langchain.chat_models import init_chat_model

from trend_researcher.config import load_env
from trend_researcher.configuration import resolve_env

Role = str

# 役割ごとの max_tokens（research.md R-3 を流用）
_ROLE_MAX_TOKENS: dict[str, int] = {
    "research": 10000,
    "summary": 8192,
    "final": 10000,
    "compression": 8192,
}

#: 会話ごとに安定したセッション ID を要求するエンドポイント（OpenCode Go）向けの
#: ヘッダー名。無いと 400 `MissingSessionID` が返る。
_SESSION_HEADER = "x-opencode-session"

#: プロセス内で使い回す既定のセッション ID。1 回の CLI 実行 = 1 会話なので、
#: ノードごとに `build_model` が呼ばれても同じ値を使う（プロンプトキャッシュの
#: ルーティングが会話単位で効くようにするため）。
_DEFAULT_SESSION_ID: str | None = None


def _session_headers(env_prefix: str | None) -> dict[str, str]:
    """`x-opencode-session` ヘッダーを組み立てる。

    値は `TR_SESSION_ID` → `{env_prefix}_SESSION_ID` の順で解決し、どちらも
    未設定ならプロセス内で 1 つ生成して使い回す。
    """
    global _DEFAULT_SESSION_ID
    session_id = resolve_env("SESSION_ID", default="", env_prefix=env_prefix)
    if not session_id:
        if _DEFAULT_SESSION_ID is None:
            _DEFAULT_SESSION_ID = f"trend-researcher-{uuid.uuid4().hex}"
        session_id = _DEFAULT_SESSION_ID
    return {_SESSION_HEADER: session_id}


def build_model(role: Role = "research", env_prefix: str | None = None):
    """指示された役割で LLM を構築する。

    OpenDeepResearch 同様 `openai:mimo-v2.5` を OpenAI 互換エンドポイントで利用。
    `configurable_fields` で実行時上書き（model/max_tokens/api_key）を許容。

    Args:
        role: 役割（`_ROLE_MAX_TOKENS` のキー）。
        env_prefix: プラットフォーム固有の環境変数接頭辞（例: `XTR` / `YTR`）。
            provider が渡す。解決順は `TR_MODEL` → `{env_prefix}_MODEL` → 既定。
    """
    # `.env` の読み込みは `config.load_env()` の 1 経路に集約する（FR-013 / SET-002）。
    # Studio のような `Configuration.load()` を通らない実行でも、ここで境界として
    # `OPENAI_API_KEY` / `OPENAI_BASE_URL` の出所を確保する（SET-009）。
    load_env()
    # 解決規則は `resolve_env` に一本化する（SET-009。`TR_MODEL` → `{env_prefix}_MODEL`
    # → 既定。接頭辞は provider が引数で渡す）
    model = resolve_env("MODEL", default="openai:mimo-v2.5", env_prefix=env_prefix)
    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "https://opencode.ai/zen/go/v1")
    max_tokens = _ROLE_MAX_TOKENS.get(role, 10000)

    return init_chat_model(
        model,
        max_tokens=max_tokens,
        api_key=api_key,
        base_url=base_url,
        default_headers=_session_headers(env_prefix),
        tags=["langsmith:nostream"],
        configurable_fields=("model", "max_tokens", "api_key"),
    )
