"""tools/llm.py の単体テスト（init_chat_model をモック）。

固定する契約（SET-009）:

- モデル名の解決順は `TR_MODEL` → `{env_prefix}_MODEL` → 既定 `openai:mimo-v2.5`
  （`resolve_env` と同じ規則。空文字は「未設定」として次の候補へ）
- 接頭辞は provider が**引数として**渡す（`env_prefix=None` のときは `TR_MODEL` のみ）
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` は `tools/llm.py`（境界）が解決する

実リポジトリの `.env` は読み込ませない（`.env` の内容で結果が変わると検証として
成立しない）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError

from trend_researcher import config as config_module
from trend_researcher.tools.llm import (
    ainvoke_structured,
    ainvoke_text,
    build_model,
    invoke_structured,
    invoke_text,
)

#: モデル解決に影響する環境変数。テストごとに全消しする。
_ENV_KEYS = ("TR_MODEL", "XTR_MODEL", "YTR_MODEL", "OPENAI_API_KEY", "OPENAI_BASE_URL")

#: 既定のモデル名（旧 `Config.model` から `tools/llm.py` へ残した値）。
_DEFAULT_MODEL = "openai:mimo-v2.5"


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` の読み込みとプロセス環境を遮断し、検証を決定的にする。

    `build_model` は `.env` を `config.load_env()` の 1 経路で読むため、遮断はその
    経路（`config.py` の `load_dotenv`）に対して行う。
    """
    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: None)
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _model_name(**kwargs: Any) -> Any:
    """`init_chat_model` に渡された第 1 引数（モデル名）を返す。"""
    with mock.patch("trend_researcher.tools.llm.init_chat_model") as m:
        m.return_value = "fake-model"
        build_model(**kwargs)
    return m.call_args.args[0]


def test_build_model_returns_callable():
    with mock.patch("trend_researcher.tools.llm.init_chat_model") as m:
        m.return_value = "fake-model"
        model = build_model("research")
    assert model == "fake-model"
    m.assert_called_once()
    _, kwargs = m.call_args
    assert "configurable_fields" in kwargs
    assert kwargs["configurable_fields"] == ("model", "max_tokens", "api_key")


# --- モデル名の解決順（SET-009）--------------------------------------------


def test_model_defaults_to_the_builtin_name() -> None:
    """どの環境変数も無いときは既定のモデル名を使う。"""
    assert _model_name() == _DEFAULT_MODEL


def test_model_uses_generic_tr_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """`TR_MODEL` は接頭辞付きの変数より優先される。"""
    monkeypatch.setenv("TR_MODEL", "openai:generic")
    monkeypatch.setenv("XTR_MODEL", "openai:platform")

    assert _model_name(env_prefix="XTR") == "openai:generic"


def test_model_uses_platform_prefix_when_generic_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """`TR_MODEL` が無いときは `{env_prefix}_MODEL` を使う。"""
    monkeypatch.setenv("XTR_MODEL", "openai:platform")

    assert _model_name(env_prefix="XTR") == "openai:platform"


def test_platform_prefix_is_not_read_without_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """`env_prefix=None` のときは `{prefix}_*` を見ない（接頭辞は provider が渡す）。"""
    monkeypatch.setenv("XTR_MODEL", "openai:platform")

    assert _model_name() == _DEFAULT_MODEL


def test_empty_model_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """空文字は「未設定」として扱い、既定へフォールバックする（`resolve_env` と同じ規則）。"""
    monkeypatch.setenv("TR_MODEL", "")

    assert _model_name(env_prefix="XTR") == _DEFAULT_MODEL


def test_env_loading_is_invoked_through_the_shared_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`build_model` は `.env` の読み込みを `config.load_env()` の 1 経路に委ねる。

    Studio のように `Configuration.load()` を通らない実行でも、この経路があるため
    `OPENAI_API_KEY` / `OPENAI_BASE_URL` を `.env` から解決できる（T071 / FR-013 /
    SET-002 / SET-009）。自前で `load_dotenv()` を呼ぶ実装に戻ると、`.env` を読む
    場所が 2 つになる。
    """
    calls: list[Path] = []
    monkeypatch.setattr(config_module, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(config_module, "load_dotenv", lambda path=None, **kw: calls.append(path))
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from-file\n", encoding="utf-8")

    _model_name()

    assert calls == [tmp_path / ".env"]


# --- 呼び出し境界（US2 / FR-009 / FR-010 / SC-005）-------------------------
#
# 固定する契約（contracts/llm-invocation-contract.md §3）:
#   - 試行回数は `1 + retry_max`（既定 `retry_max = 2` なので 3 回）
#   - 待機は `asyncio.sleep` を通す（`retry_wait_seconds` を再試行のたびに 1 回）
#   - 再試行の対象は「スキーマ違反 / 一時的なエラー（ネットワーク・レート制限・
#     タイムアウト）」。上限超過（4xx）と設定ミス系は対象外（US3 の縮退へ渡す）
#   - `asyncio.CancelledError` は再試行せずそのまま伝える
#   - 構造化出力の `method` は呼び出し側が指定した値（既定 `json_schema`）


class _Sample(BaseModel):
    """`ValidationError` を実測で作るための最小モデル。"""

    value: int


def _validation_error() -> ValidationError:
    """実際に投げられた `ValidationError` を返す（自作の例外は本物と挙動がずれる）。"""
    try:
        _Sample.model_validate({})
    except ValidationError as exc:
        return exc
    raise AssertionError("ValidationError が発生しなかった")


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.test/v1/chat/completions")


def _rate_limit_error() -> Exception:
    return openai.RateLimitError(
        message="429 Too Many Requests",
        response=httpx.Response(429, request=_request()),
        body=None,
    )


def _connection_error() -> Exception:
    return openai.APIConnectionError(request=_request())


def _context_length_error() -> Exception:
    """上限超過（400）を模す。再試行の対象外であることを固定する（US3 の前提）。"""
    return openai.BadRequestError(
        message="This endpoint's maximum context length is 1048576 tokens.",
        response=httpx.Response(400, request=_request()),
        body={"error": {"code": "context_length_exceeded"}},
    )


class _StubRunnable:
    """`ainvoke` の代役。`outcomes` を順に返し、例外なら投げる。"""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = outcomes
        self.calls = 0
        self.prompts: list[Any] = []

    async def ainvoke(self, prompt: Any) -> Any:
        self.prompts.append(prompt)
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _StubModel:
    """`build_model` の代役（テキスト・構造化の両経路を同じ runnable で受ける）。"""

    def __init__(self, outcomes: list[Any]) -> None:
        self.runnable = _StubRunnable(outcomes)
        self.options: dict[str, Any] = {}

    async def ainvoke(self, prompt: Any) -> Any:
        return await self.runnable.ainvoke(prompt)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> _StubRunnable:
        self.options = {"schema": schema, **kwargs}
        return self.runnable


def _patch_model(outcomes: list[Any]) -> tuple[_StubModel, Any]:
    """`build_model` を差し替えたスタブモデルと、その patch を返す。"""
    model = _StubModel(outcomes)
    return model, mock.patch("trend_researcher.tools.llm.build_model", return_value=model)


def test_text_call_is_retried_up_to_one_plus_retry_max(no_retry_sleep: Any) -> None:
    """合計試行回数は `1 + retry_max`、待機は再試行のたびに 1 回（既定 3 回試行）。"""
    model, patch = _patch_model([_connection_error()])
    with patch, pytest.raises(openai.APIConnectionError):
        asyncio.run(
            ainvoke_text(
                "prompt", env_prefix=None, retry_max=2, retry_wait_seconds=1.0
            )
        )

    assert model.runnable.calls == 3
    assert no_retry_sleep.sleeps == [1.0, 1.0]


def test_retry_max_zero_does_not_retry(no_retry_sleep: Any) -> None:
    """`retry_max = 0` は 1 回だけ試す（待機もしない）。"""
    model, patch = _patch_model([_connection_error()])
    with patch, pytest.raises(openai.APIConnectionError):
        asyncio.run(
            ainvoke_text("prompt", env_prefix=None, retry_max=0, retry_wait_seconds=5.0)
        )

    assert model.runnable.calls == 1
    assert no_retry_sleep.sleeps == []


def test_retry_stops_at_the_first_success(no_retry_sleep: Any) -> None:
    """再試行で成功したらその時点で打ち切る（待機は失敗した回数だけ）。"""
    model, patch = _patch_model([_validation_error(), _Sample(value=1)])
    with patch:
        result = asyncio.run(
            ainvoke_text("prompt", env_prefix=None, retry_max=2, retry_wait_seconds=0.5)
        )

    assert result == _Sample(value=1)
    assert model.runnable.calls == 2
    assert no_retry_sleep.sleeps == [0.5]


@pytest.mark.parametrize(
    "error_factory",
    [_validation_error, _rate_limit_error, _connection_error, TimeoutError],
)
def test_transient_and_schema_errors_are_retried(
    error_factory: Any, no_retry_sleep: Any
) -> None:
    """スキーマ違反・レート制限・ネットワーク断・タイムアウトは再試行の対象。"""
    model, patch = _patch_model([error_factory()])
    # 例外型は各 factory が決めるため `BaseException` で受けて後段で型を確かめる。
    with patch, pytest.raises(BaseException) as excinfo:
        asyncio.run(
            ainvoke_text("prompt", env_prefix=None, retry_max=1, retry_wait_seconds=1.0)
        )

    assert model.runnable.calls == 2
    assert isinstance(excinfo.value, type(error_factory()))
    assert len(no_retry_sleep.sleeps) == 1


def test_context_length_error_is_not_retried(no_retry_sleep: Any) -> None:
    """上限超過（4xx）は再試行しない（US3 の縮退へ渡す前提を先に固定する）。"""
    model, patch = _patch_model([_context_length_error()])
    with patch, pytest.raises(openai.BadRequestError):
        asyncio.run(
            ainvoke_text("prompt", env_prefix=None, retry_max=2, retry_wait_seconds=1.0)
        )

    assert model.runnable.calls == 1
    assert no_retry_sleep.sleeps == []


def test_cancellation_is_not_retried(no_retry_sleep: Any) -> None:
    """`CancelledError` は再試行せず伝える（キャンセルを握り潰すとグラフが止まらない）。"""
    model, patch = _patch_model([asyncio.CancelledError()])
    with patch, pytest.raises(asyncio.CancelledError):
        asyncio.run(
            ainvoke_text("prompt", env_prefix=None, retry_max=2, retry_wait_seconds=1.0)
        )

    assert model.runnable.calls == 1
    assert no_retry_sleep.sleeps == []


def test_structured_call_returns_the_validated_schema_instance() -> None:
    """構造化出力はスキーマで検証済みのインスタンスを返す。"""
    model, patch = _patch_model([_Sample(value=7)])
    with patch:
        result = asyncio.run(
            ainvoke_structured(
                _Sample,
                "prompt",
                env_prefix=None,
                retry_max=2,
                retry_wait_seconds=1.0,
            )
        )

    assert result == _Sample(value=7)
    assert model.options == {"schema": _Sample, "method": "json_schema"}


def test_structured_call_uses_the_configured_method() -> None:
    """`method` は設定値（`structured_method`）が境界まで届く。"""
    model, patch = _patch_model([_Sample(value=1)])
    with patch:
        asyncio.run(
            ainvoke_structured(
                _Sample,
                "prompt",
                env_prefix=None,
                retry_max=0,
                retry_wait_seconds=0.0,
                method="function_calling",
            )
        )

    assert model.options["method"] == "function_calling"


def test_structured_schema_violation_is_retried(no_retry_sleep: Any) -> None:
    """スキーマ違反も再試行し、規定回数内に成功すれば値が返る。"""
    model, patch = _patch_model([_validation_error(), _validation_error(), _Sample(value=3)])
    with patch:
        result = asyncio.run(
            ainvoke_structured(
                _Sample,
                "prompt",
                env_prefix=None,
                retry_max=2,
                retry_wait_seconds=1.0,
            )
        )

    assert result == _Sample(value=3)
    assert model.runnable.calls == 3
    assert no_retry_sleep.sleeps == [1.0, 1.0]


def test_sync_wrappers_use_the_same_path() -> None:
    """同期入口（同期ノード用）も同じ経路・同じ回数で動く。"""
    model, patch = _patch_model([_connection_error(), "text"])
    with patch:
        assert invoke_text("prompt", env_prefix=None, retry_max=1, retry_wait_seconds=0.0) == (
            "text"
        )

    assert model.runnable.calls == 2

    model, patch = _patch_model([_Sample(value=9)])
    with patch:
        assert invoke_structured(
            _Sample, "prompt", env_prefix=None, retry_max=1, retry_wait_seconds=0.0
        ) == _Sample(value=9)
