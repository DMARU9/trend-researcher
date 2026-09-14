"""LLM 構築ヘルパ（OpenDeepResearch 設定を流用）。X / YouTube 共通。

この層が持つ境界は 3 つだけ（contracts/llm-invocation-contract.md）。

1. モデル構築（`build_model` / `resolve_model_name`）
2. 再試行（`_with_retry`。一時的な失敗だけを同じ入力で投げ直す）
3. 結退（`_invoke_with_degradation`。上限超過だけ入力を段階的に縮める。FR-015）

再試行と結退は排他。上限超過は「同じ入力を投げ直しても結果は変わらない」ため
再試行に回さず、縮小した入力で呼び直す（US3 シナリオ 4 / FR-015）。

使用量の記録（`UsageMeter` / FR-061）もこの層が担う。呼び出し側は `meter` を
渡すだけで、実際にどの試行が成功したかを知る必要がない（呼び出し側は「戻り値 1
つ = 記録 1 要素」として受け取る）。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, TypeVar, cast

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from openai import APIConnectionError, APITimeoutError, RateLimitError
from pydantic import BaseModel, ValidationError

from trend_researcher.config import load_env
from trend_researcher.configuration import resolve_env
from trend_researcher.models import ModelUsage
from trend_researcher.progress import make_emitter
from trend_researcher.tools.degradation import (
    DegradationError,
    DegradeOptions,
    Ladder,
    is_token_limit_exceeded,
)

Role = str

#: モデル未指定のときの既定（OpenDeepResearch 設定を流用）。
_DEFAULT_MODEL = "openai:mimo-v2.5"

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


def resolve_model_name(env_prefix: str | None = None) -> str:
    """役割に依らないモデル名を解決する（結退の上限表引きに使う）。

    解決規則は `build_model` と同一（SET-009）: `TR_MODEL` →
    `{env_prefix}_MODEL` → 既定。結退側で同じ値を引けるように、外部へ出す。
    """
    return resolve_env("MODEL", default=_DEFAULT_MODEL, env_prefix=env_prefix)


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
    model = resolve_model_name(env_prefix)
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


class UsageMeter:
    """1 つのノードの LLM 呼び出しの使用量を集める受け皿（FR-061 / data-model §3.4）。

    数えるのは**呼び出し境界**だけである（ノードは数えない）。ノードは自分の名前で
    受け皿を作り、境界呼び出しに渡し、`records` を `usage` として状態へ返す。

    粒度は「境界呼び出し 1 回（戻り値 1 つ）= 要素 1 つ」。失敗した試行には
    `usage_metadata` を読む対象（`AIMessage`）が存在しないため、再試行の途中経過は
    要素を増やさない（契約 §7 の「粒度」の読み方との差は実装メモ §5 に記録）。
    """

    def __init__(self, node_name: str) -> None:
        """ノード名（`ModelUsage.node_name` になる）を受け取る。"""
        self.node_name = node_name
        self.records: list[ModelUsage] = []

    def add(self, result: Any, *, role: Role, env_prefix: str | None, structured: bool) -> None:
        """戻り値 1 つ分の使用量を記録する（読めない値は `None` のまま。FR-061）。"""
        input_tokens, output_tokens, total_tokens = _usage_counts(result)
        self.records.append(
            ModelUsage(
                node_name=self.node_name,
                role=role,
                model=resolve_model_name(env_prefix),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                structured=structured,
            )
        )


def _as_int(value: Any) -> int | None:
    """整数ならその値、そうでなければ `None`（不明を 0 に潰さない）。"""
    return value if isinstance(value, int) else None


def _usage_counts(result: Any) -> tuple[int | None, int | None, int | None]:
    """応答から (入力, 出力, 合計) トークンを読む（読めない項目は `None`）。

    構造化出力（`with_structured_output` / `include_raw=False`）の戻り値は検証済みの
    インスタンスであり `usage_metadata` を持たない。その場合は 3 つとも `None` に
    なる（0 に潰すと「0 トークンで呼んだ」という嘘の集計になる）。
    """
    usage = getattr(result, "usage_metadata", None)
    if not isinstance(usage, dict):
        return (None, None, None)
    return (
        _as_int(usage.get("input_tokens")),
        _as_int(usage.get("output_tokens")),
        _as_int(usage.get("total_tokens")),
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


async def _invoke_with_degradation(
    ainvoke: Callable[[str], Awaitable[Any]],
    prompt: str,
    *,
    retry_max: int,
    retry_wait_seconds: float,
    degrade: DegradeOptions | None,
    env_prefix: str | None,
) -> Any:
    """再試行し、上限超過なら入力を段階的に縮めて呼び直す（FR-015 / 契約 §6）。

    流れは 2 段だけ。

    1. 元の入力で再試行する（一時的な失敗はここで回復する）。
    2. 上限超過（`is_token_limit_exceeded`）なら梯子（`Ladder`）を 1 段ずつ
       登ります。段ごとに同じ手順（再試行）で呼び直し、成功したら段の記録を
       補足行に出して終わる。

    段を使い切ったら `DegradationError` を送出する（呼び出し側が終了コード 1 に
    する）。引数の並べ替え・モデルの差し替えはしない（契約 §6 の禁止事項）。
    """
    try:
        return await _with_retry(
            lambda: ainvoke(prompt),
            retry_max=retry_max,
            retry_wait_seconds=retry_wait_seconds,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # 上限超過かどうかを自分で判定する
        if degrade is None or not is_token_limit_exceeded(exc):
            raise

    ladder = Ladder(prompt, degrade, model=resolve_model_name(env_prefix))
    while (shrunk := ladder.advance()) is not None:
        try:
            result = await _with_retry(
                partial(ainvoke, shrunk),
                retry_max=retry_max,
                retry_wait_seconds=retry_wait_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # 上限超過だけ段を進める
            if not is_token_limit_exceeded(exc):
                raise
            continue
        make_emitter().note(ladder.summary())
        return result

    make_emitter().note(ladder.summary())
    raise DegradationError(ladder)


async def ainvoke_text(
    prompt: str,
    *,
    role: Role = "research",
    env_prefix: str | None = None,
    model: Any | None = None,
    retry_max: int,
    retry_wait_seconds: float,
    degrade: DegradeOptions | None = None,
    meter: UsageMeter | None = None,
) -> Any:
    """テキスト応答を規定回数まで再試行して取得する（FR-010）。

    `model` を渡すとそのモデルをそのまま使う（ノードが `build_model` の差し替え
    点を持つための入口）。省略時は境界が `build_model` で構築する。

    失敗（再試行を使い切った場合）は最後の例外をそのまま伝える。フォールバックの
    判断はノード側が持つ（FR-011）。

    `degrade` を渡すと、上限超過（US3 / FR-015）だけは結退へ回す。省略時は既存の
    振る舞いのままで、上限超過もそのまま伝わる。

    `meter` を渡すと成功した呼び出し 1 回分の使用量を記録する（FR-061）。記録は
    使用量の読み取りに失敗しても例外にしない（呼び出しの成否を変えない）。
    """
    built = model if model is not None else build_model(role, env_prefix)
    result = await _invoke_with_degradation(
        built.ainvoke,
        prompt,
        retry_max=retry_max,
        retry_wait_seconds=retry_wait_seconds,
        degrade=degrade,
        env_prefix=env_prefix,
    )
    if meter is not None:
        meter.add(result, role=role, env_prefix=env_prefix, structured=False)
    return result


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
    degrade: DegradeOptions | None = None,
    meter: UsageMeter | None = None,
) -> _ModelT:
    """構造化出力を規定回数まで再試行して取得する（FR-009 / FR-010）。

    `method` は `Configuration.structured_method` の値（`function_calling` /
    `json_schema`）。スキーマ違反も再試行の対象に含めるため、再試行を使い
    切った場合は最後の例外が伝わる（ノードはそれを受けてフォールバックする）。

    `degrade` を渡したときの上限超過の扱いは `ainvoke_text` と同じ（FR-015）。

    `with_structured_output` は `Runnable[..., Any]` を返すため、検証済みの型は
    呼び出し側で `cast` して取り出す（`schema` に `with_structured_output` を
    渡している以上、実行時の戻り値は `schema` のインスタンスになる）。

    `None` は「構造化出力が得られなかった」失敗として扱う（下の `_invoke`）。

    `meter` の扱いは `ainvoke_text` と同じだが、戻り値が `AIMessage` ではないため
    トークン数は不明（`None`）のまま記録される（`structured=True`）。
    """
    built = model if model is not None else build_model(role, env_prefix)
    runnable = built.with_structured_output(schema, method=method)

    async def _invoke(text: str) -> Any:
        """構造化出力を 1 回呼び、`None` をパース失敗に正規化する。

        `function_calling` はツール呼び出しを返さなかったモデルに対して**例外ではなく
        `None`** を返す。素通しすると「成功時はスキーマのインスタンスを返す」という
        契約（contracts/llm-invocation-contract.md §2）が破れ、呼び出し側が属性参照で
        落ちる（実測: `parse_instruction` の
        `'NoneType' object has no attribute 'topic'` → 終了コード 1）。

        `OutputParserException` は再試行の対象（FR-010）なので、一時的な
        「ツール呼び出しの抜け」はここで回復し、規定回数を使い切ったときだけ
        決定的解析へフォールバックする（FR-011）。
        """
        value = await runnable.ainvoke(text)
        if value is None:
            raise OutputParserException(
                f"{role}: 構造化出力が得られませんでした"
                "（モデルがツール呼び出しを返していません）"
            )
        return value

    result = cast(
        "_ModelT",
        await _invoke_with_degradation(
            _invoke,
            prompt,
            retry_max=retry_max,
            retry_wait_seconds=retry_wait_seconds,
            degrade=degrade,
            env_prefix=env_prefix,
        ),
    )
    if meter is not None:
        meter.add(result, role=role, env_prefix=env_prefix, structured=True)
    return result


def invoke_text(
    prompt: str,
    *,
    role: Role = "research",
    env_prefix: str | None = None,
    model: Any | None = None,
    retry_max: int,
    retry_wait_seconds: float,
    degrade: DegradeOptions | None = None,
    meter: UsageMeter | None = None,
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
            degrade=degrade,
            meter=meter,
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
    degrade: DegradeOptions | None = None,
    meter: UsageMeter | None = None,
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
            degrade=degrade,
            meter=meter,
        )
    )
