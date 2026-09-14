"""LLM 構築ヘルパ（OpenDeepResearch 設定を流用）。X / YouTube 共通。"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from openai import APIConnectionError, APITimeoutError, RateLimitError
from pydantic import BaseModel, ValidationError

from trend_researcher.config import load_env
from trend_researcher.configuration import resolve_env

Role = str

#: 構造化出力のスキーマ（Pydantic モデル）の型変数。
_ModelT = TypeVar("_ModelT", bound=BaseModel)

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


#: 再試行の対象になる例外（contracts/llm-invocation-contract.md §3 と US2 シナリオ 3）。
#:
#: - `OutputParserException` / `ValidationError`: 構造化出力のスキーマ違反
#: - `APIConnectionError` / `APITimeoutError` / `TimeoutError`: ネットワーク・タイムアウト
#: - `RateLimitError`: レート制限（シナリオ 3 の「一時的なエラー」。契約 §3 の列挙には
#:   無いが、仕様のシナリオが再試行対象を要求しているため加える）
#:
#: **含めない**もの: 上限超過（`BadRequestError` 等の 4xx）と設定ミス系。同じ入力を
#: 投げ直しても結果は変わらず、上限超過は縮退（US3 / FR-015）へ渡す。
RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    OutputParserException,
    ValidationError,
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    TimeoutError,
)


async def _with_retry(
    call: Callable[[], Awaitable[Any]],
    *,
    retry_max: int,
    retry_wait_seconds: float,
) -> Any:
    """`call` を最大 `1 + retry_max` 回呼ぶ（待機は `asyncio.sleep` を通す）。

    待機を `asyncio.sleep` に通すのは、テストが実時間を消費せず回数と値を観測
    できるようにするため（LAYOUT-004-2）。キャンセルは再試行せずそのまま伝える。
    """
    attempt = 0
    while True:
        try:
            return await call()
        except asyncio.CancelledError:
            raise
        except RETRYABLE_ERRORS:
            if attempt >= retry_max:
                raise
            attempt += 1
            await asyncio.sleep(retry_wait_seconds)


async def ainvoke_text(
    prompt: str,
    *,
    role: Role = "research",
    env_prefix: str | None = None,
    model: Any | None = None,
    retry_max: int,
    retry_wait_seconds: float,
) -> Any:
    """テキスト応答を規定回数まで再試行して取得する（FR-010）。

    `model` を渡すとそのモデルをそのまま使う（ノードが `build_model` の差し替え
    点を持つための入口）。省略時は境界が `build_model` で構築する。

    失敗（再試行を使い切った場合）は最後の例外をそのまま伝える。フォールバックの
    判断はノード側が持つ（FR-011）。
    """
    built = model if model is not None else build_model(role, env_prefix)
    return await _with_retry(
        lambda: built.ainvoke(prompt),
        retry_max=retry_max,
        retry_wait_seconds=retry_wait_seconds,
    )


async def ainvoke_structured(
    schema: type[_ModelT],
    prompt: str,
    *,
    role: Role = "research",
    env_prefix: str | None = None,
    model: Any | None = None,
    retry_max: int,
    retry_wait_seconds: float,
    method: str = "json_schema",
) -> _ModelT:
    """構造化出力を規定回数まで再試行して取得する（FR-009 / FR-010）。

    `method` は `Configuration.structured_method` の値（`json_schema` /
    `function_calling`）。スキーマ違反も再試行の対象に含めるため、再試行を使い
    切った場合は最後の例外が伝わる（ノードはそれを受けてフォールバックする）。

    `with_structured_output` は `Runnable[..., Any]` を返すため、検証済みの型は
    呼び出し側で `cast` して取り出す（`schema` に `with_structured_output` を
    渡している以上、実行時の戻り値は `schema` のインスタンスになる）。
    """
    built = model if model is not None else build_model(role, env_prefix)
    runnable = built.with_structured_output(schema, method=method)
    return cast(
        "_ModelT",
        await _with_retry(
            lambda: runnable.ainvoke(prompt),
            retry_max=retry_max,
            retry_wait_seconds=retry_wait_seconds,
        ),
    )


def invoke_text(
    prompt: str,
    *,
    role: Role = "research",
    env_prefix: str | None = None,
    model: Any | None = None,
    retry_max: int,
    retry_wait_seconds: float,
) -> Any:
    """`ainvoke_text` の同期入口（同期ノード用）。経路は 1 つに保つ。"""
    return asyncio.run(
        ainvoke_text(
            prompt,
            role=role,
            env_prefix=env_prefix,
            model=model,
            retry_max=retry_max,
            retry_wait_seconds=retry_wait_seconds,
        )
    )


def invoke_structured(
    schema: type[_ModelT],
    prompt: str,
    *,
    role: Role = "research",
    env_prefix: str | None = None,
    model: Any | None = None,
    retry_max: int,
    retry_wait_seconds: float,
    method: str = "json_schema",
) -> _ModelT:
    """`ainvoke_structured` の同期入口（同期ノード用）。経路は 1 つに保つ。"""
    return asyncio.run(
        ainvoke_structured(
            schema,
            prompt,
            role=role,
            env_prefix=env_prefix,
            model=model,
            retry_max=retry_max,
            retry_wait_seconds=retry_wait_seconds,
            method=method,
        )
    )
