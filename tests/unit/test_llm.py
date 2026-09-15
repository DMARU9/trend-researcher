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
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError

from trend_researcher import config as config_module
from trend_researcher.tools.degradation import DegradationError, DegradeOptions
from trend_researcher.tools.llm import (
    UsageMeter,
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


def test_a_structured_none_is_retried(no_retry_sleep: Any) -> None:
    """`None` はパース失敗として再試行する（ツール呼び出しの抜けは一時的でありうる）。

    `function_calling` はツール呼び出しを返さないモデルに対して例外ではなく `None` を
    返す。境界はこれを `OutputParserException` へ正規化するので、再試行の対象になる
    （FR-010）。スキーマのインスタンスが返れば成功として扱う。
    """
    model, patch = _patch_model([None, None, _Sample(value=5)])
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

    assert result == _Sample(value=5)
    assert model.runnable.calls == 3
    assert no_retry_sleep.sleeps == [1.0, 1.0]


def test_an_exhausted_structured_none_raises_a_parse_error(no_retry_sleep: Any) -> None:
    """全試行が `None` なら `OutputParserException` を送出する（境界の契約）。

    契約 §2「成功時はモデルのインスタンスを返す」を守る。`None` を返すと、呼び出し側が
    属性参照で落ちるか、誤って「成功」として扱われる。
    """
    model, patch = _patch_model([None])
    with patch, pytest.raises(OutputParserException, match="構造化出力が得られませんでした"):
        asyncio.run(
            ainvoke_structured(
                _Sample,
                "prompt",
                env_prefix=None,
                retry_max=2,
                retry_wait_seconds=1.0,
            )
        )

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


# --- 段階的縮退との連携（US3 / FR-015〜019 / contract §6） ------------------
#
# 固定する契約:
#   - 上限超過と判定された呼び出しは**再試行しない**（縮退へ渡す。§3 / §6）
#   - 縮小して呼び直し、成功したら `Degradation` が段の数だけ記録される
#   - 段を使い切ったら `DegradationError`（理由に段数と縮小前後の長さ）を送出する
#   - 縮退した事実は `ProgressEmitter.note()` に 1 行で出る（`emit()` は変更しない）


def _degrade_options(**overrides: Any) -> DegradeOptions:
    """検証用の縮退の設定（`Configuration` の既定値と同じ値から始める）。"""
    values: dict[str, Any] = {
        "node_name": "analyze_content",
        "max_attempts": 3,
        "shrink_ratio": 0.9,
        "min_input_chars": 1000,
    }
    values.update(overrides)
    return DegradeOptions(**values)


#: 縮退の検証に使う入力（既定の `min_input_chars = 1000` で 3 段縮退できる長さ）
_LONG_PROMPT = "x" * 10000


def test_a_limit_error_is_degraded_instead_of_retried(no_retry_sleep: Any) -> None:
    """上限超過は再試行せず、入力を縮めて呼び直す（`retry_max` を消費しない）。"""
    options = _degrade_options()
    model, patch = _patch_model([_context_length_error(), "text"])
    with patch:
        result = asyncio.run(
            ainvoke_text(
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=2,
                retry_wait_seconds=1.0,
                degrade=options,
            )
        )

    assert result == "text"
    # 初回（上限超過）＋ 縮小後の 1 回。再試行の 3 回にはならない
    assert model.runnable.calls == 2
    assert no_retry_sleep.sleeps == []
    assert len(options.records) == 1
    assert options.records[0].before_chars == 10000
    assert options.records[0].after_chars == 9000


def test_the_shrunk_input_keeps_the_head_of_the_original() -> None:
    """縮小した入力は元の入力の先頭（末尾を落とす。contract §6）。"""
    options = _degrade_options(max_attempts=2)
    model, patch = _patch_model([_context_length_error()])
    with patch, pytest.raises(DegradationError):
        asyncio.run(
            ainvoke_text(
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=2,
                retry_wait_seconds=0.0,
                degrade=options,
            )
        )

    prompts = model.runnable.prompts
    assert [len(prompt) for prompt in prompts] == [10000, 9000, 8100]
    assert prompts[1] == prompts[0][:9000]
    assert prompts[2] == prompts[0][:8100]


def test_exhausting_the_ladder_raises_the_reason() -> None:
    """段を使い切ったら理由つきの例外を送出する（`__main__.py` が exit 1 にする）。"""
    options = _degrade_options(max_attempts=2)
    model, patch = _patch_model([_context_length_error()])
    with patch, pytest.raises(DegradationError) as excinfo:
        asyncio.run(
            ainvoke_text(
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=2,
                retry_wait_seconds=0.0,
                degrade=options,
            )
        )

    # 初回＋2 段。段数は `degrade_max_attempts` を超えない
    assert model.runnable.calls == 3
    assert excinfo.value.stages == 2
    assert excinfo.value.before_chars == 10000
    assert excinfo.value.after_chars == 8100
    assert "上限超過のため生成できませんでした" in str(excinfo.value)
    assert "試した段数: 2" in str(excinfo.value)
    assert "縮小前: 10000 文字 → 縮小後: 8100 文字" in str(excinfo.value)


def test_a_non_limit_error_on_a_shrunk_call_is_propagated() -> None:
    """縮小後の呼び出しでも、上限超過以外の失敗はそのまま伝える（誤認の禁止）。"""
    options = _degrade_options()
    model, patch = _patch_model([_context_length_error(), _connection_error()])
    with patch, pytest.raises(openai.APIConnectionError):
        asyncio.run(
            ainvoke_text(
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=0,
                retry_wait_seconds=0.0,
                degrade=options,
            )
        )

    assert model.runnable.calls == 2
    assert len(options.records) == 1


def test_a_limit_error_without_degrade_options_is_propagated() -> None:
    """縮退の設定が無い経路では従来どおり例外を伝える（既定の挙動を変えない）。"""
    model, patch = _patch_model([_context_length_error()])
    with patch, pytest.raises(openai.BadRequestError):
        asyncio.run(
            ainvoke_text(
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=2,
                retry_wait_seconds=1.0,
            )
        )

    assert model.runnable.calls == 1


def test_a_structured_limit_error_is_degraded_too() -> None:
    """構造化出力の経路でも同じ縮退が働く（§1 の 3 形態で挙動を揃える）。"""
    options = _degrade_options()
    model, patch = _patch_model([_context_length_error(), _Sample(value=5)])
    with patch:
        result = asyncio.run(
            ainvoke_structured(
                _Sample,
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=0,
                retry_wait_seconds=0.0,
                degrade=options,
            )
        )

    assert result == _Sample(value=5)
    assert model.runnable.calls == 2
    assert len(options.records) == 1
    assert options.records[0].after_chars == 9000


def test_the_degradation_is_reported_once_as_a_note(capsys: pytest.CaptureFixture[str]) -> None:
    """縮退は `note()` の 1 行で実行後に確認できる（段数・縮小前後の長さ。FR-017）。"""
    options = _degrade_options()
    _model, patch = _patch_model([_context_length_error(), "text"])
    with patch:
        asyncio.run(
            ainvoke_text(
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=0,
                retry_wait_seconds=0.0,
                degrade=options,
            )
        )

    err = capsys.readouterr().err
    assert err.count("[補足]") == 1
    assert "縮退" in err
    assert "9000" in err
    assert "[1/7]" not in err  # `emit()` は呼ばない（進捗の契約を変えない）


def test_no_note_is_emitted_when_nothing_is_degraded(capsys: pytest.CaptureFixture[str]) -> None:
    """縮退が起きない呼び出しでは補足行を出さない（既定の入力の出力を変えない）。"""
    _model, patch = _patch_model(["text"])
    with patch:
        asyncio.run(
            ainvoke_text(
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=0,
                retry_wait_seconds=0.0,
                degrade=_degrade_options(),
            )
        )

    assert capsys.readouterr().err == ""


# --- 使用量の記録（US8 / FR-061 / FR-062 / contract §7） --------------------
#
# 固定する契約:
#   - 使用量は**呼び出し境界**で数える（`invoke` / `ainvoke` / 構造化呼び出しの
#     すべて。ノードは数えない）。受け皿は `UsageMeter` で、戻り値 1 つにつき
#     `ModelUsage` 1 要素を記録する
#   - トークン数は `AIMessage.usage_metadata` から読む。読めない場合は `None` の
#     まま記録する（0 に潰さない。FR-061）
#   - 記録するモデル名は `build_model` が `init_chat_model` に渡す文字列と同じ

#: 差分応答の `usage_metadata` の例（research R-11 の実測値と同じ形）。
_USAGE = {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}


class _UsageMessage:
    """`usage_metadata` を持つ応答（実 API の `AIMessage` の代役）。"""

    def __init__(self, content: str, usage_metadata: dict[str, int] | None) -> None:
        self.content = content
        self.usage_metadata = usage_metadata


def test_a_text_call_records_one_usage_element() -> None:
    """テキスト呼び出し 1 回につき `ModelUsage` が 1 要素（契約 §7 の粒度）。"""
    _model, patch = _patch_model([_UsageMessage("text", _USAGE)])
    meter = UsageMeter("plan_search")

    with patch:
        result = asyncio.run(
            ainvoke_text(
                "prompt",
                env_prefix=None,
                retry_max=0,
                retry_wait_seconds=0.0,
                meter=meter,
            )
        )

    assert result.content == "text"
    assert [record.model_dump() for record in meter.records] == [
        {
            "node_name": "plan_search",
            "role": "research",
            "model": _DEFAULT_MODEL,
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "structured": False,
        }
    ]


def test_the_recorded_model_name_follows_the_resolution_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """記録するモデル名は `build_model` の解決結果（`TR_MODEL` → 接頭辞 → 既定）。"""
    monkeypatch.setenv("XTR_MODEL", "openai:platform")
    _model, patch = _patch_model([_UsageMessage("text", _USAGE)])
    meter = UsageMeter("plan_search")

    with patch:
        asyncio.run(
            ainvoke_text(
                "prompt",
                env_prefix="XTR",
                retry_max=0,
                retry_wait_seconds=0.0,
                meter=meter,
            )
        )

    assert [record.model for record in meter.records] == ["openai:platform"]


def test_a_structured_call_is_counted_through_the_same_path() -> None:
    """構造化呼び出しも同じ経路で数える（`structured=True` と役割を残す）。

    `with_structured_output(...)` の戻り値は `AIMessage` ではなく検証済みの
    インスタンスである（`include_raw=False` の既定）。したがって `usage_metadata`
    を読む対象が無く、トークン数は `None`（不明）のまま記録する（FR-061）。
    0 に潰すと「0 トークンで呼んだ」という嘘の集計になる。
    """
    _model, patch = _patch_model([_Sample(value=7)])
    meter = UsageMeter("extract_common")

    with patch:
        asyncio.run(
            ainvoke_structured(
                _Sample,
                "prompt",
                role="summary",
                env_prefix=None,
                retry_max=0,
                retry_wait_seconds=0.0,
                meter=meter,
            )
        )

    assert len(meter.records) == 1
    record = meter.records[0]
    assert (record.node_name, record.role, record.structured) == ("extract_common", "summary", True)
    assert (record.input_tokens, record.output_tokens, record.total_tokens) == (None, None, None)


def test_a_response_without_usage_is_recorded_as_unknown() -> None:
    """`usage_metadata` が無い応答は「不明」として記録する（0 ではない。FR-061）。"""
    _model, patch = _patch_model([_UsageMessage("text", None)])
    meter = UsageMeter("plan_search")

    with patch:
        asyncio.run(
            ainvoke_text(
                "prompt", env_prefix=None, retry_max=0, retry_wait_seconds=0.0, meter=meter
            )
        )

    assert len(meter.records) == 1
    assert (meter.records[0].input_tokens, meter.records[0].total_tokens) == (None, None)


def test_partial_usage_metadata_does_not_invent_the_missing_counts() -> None:
    """一部のキーしか無い応答では、無いキーだけを `None` にする（補完しない）。"""
    _model, patch = _patch_model([_UsageMessage("text", {"input_tokens": 5})])
    meter = UsageMeter("plan_search")

    with patch:
        asyncio.run(
            ainvoke_text(
                "prompt", env_prefix=None, retry_max=0, retry_wait_seconds=0.0, meter=meter
            )
        )

    record = meter.records[0]
    assert (record.input_tokens, record.output_tokens, record.total_tokens) == (5, None, None)


def test_failed_attempts_do_not_add_usage_elements(no_retry_sleep: Any) -> None:
    """失敗した試行は要素を増やさない（戻り値が無く `usage_metadata` を読めないため）。

    契約 §3 の「試行ごとの記録」は、失敗した試行に `AIMessage` が存在しない
    （= 読む対象が無い）ため、**境界呼び出し 1 回（戻り値 1 つ）につき 1 要素**として
    実装する。再試行が起きたことは `note()` と `degradations` から確認できる
    （FR-013 / FR-017）。実装メモ §5 の乖離表を参照。
    """
    _model, patch = _patch_model([_connection_error(), _UsageMessage("text", _USAGE)])
    meter = UsageMeter("plan_search")

    with patch:
        asyncio.run(
            ainvoke_text(
                "prompt", env_prefix=None, retry_max=2, retry_wait_seconds=1.0, meter=meter
            )
        )

    assert no_retry_sleep.sleeps == [1.0]
    assert len(meter.records) == 1


def test_a_degraded_call_records_only_the_successful_call(no_retry_sleep: Any) -> None:
    """縮退（上限超過 → 縮小して再試行）でも、成功した呼び出しの 1 要素だけを記録する。"""
    options = _degrade_options()
    _model, patch = _patch_model([_context_length_error(), _UsageMessage("text", _USAGE)])
    meter = UsageMeter("analyze_content")

    with patch:
        asyncio.run(
            ainvoke_text(
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=0,
                retry_wait_seconds=0.0,
                degrade=options,
                meter=meter,
            )
        )

    assert len(options.records) == 1  # 縮退は 1 段（既存の契約は変わらない）
    assert len(meter.records) == 1


def test_calls_without_a_meter_record_nothing() -> None:
    """受け皿を渡さない呼び出しは従来どおり（境界を直接使うテストを壊さない）。"""
    _model, patch = _patch_model([_UsageMessage("text", _USAGE)])

    with patch:
        result = asyncio.run(
            ainvoke_text("prompt", env_prefix=None, retry_max=0, retry_wait_seconds=0.0)
        )

    assert result.content == "text"


def test_the_sync_wrapper_records_the_same_way() -> None:
    """同期入口（同期ノード用）も同じ受け皿に記録する（経路は 1 つ）。"""
    _model, patch = _patch_model([_UsageMessage("text", _USAGE)])
    meter = UsageMeter("parse_instruction")

    with patch:
        invoke_text(
            "prompt", env_prefix=None, retry_max=0, retry_wait_seconds=0.0, meter=meter
        )

    assert [record.input_tokens for record in meter.records] == [120]


# --- 分岐カバレッジの棚卸しで見つかった未実行の分岐（T104） --------------------


def test_the_session_id_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """`TR_SESSION_ID` があればそれを使う（無いときだけプロセス内で 1 つ生成する）。

    セッション ID の**生成**（`x-opencode-session` が毎回同じ値になること）は既存の
    検査が固定している。ここは環境変数から来る側（分岐カバレッジで未実行だった行）を
    固定する（T104）。
    """
    monkeypatch.setenv("TR_SESSION_ID", "session-from-env")

    with mock.patch("trend_researcher.tools.llm.init_chat_model") as m:
        m.return_value = "fake-model"
        build_model("research")

    _, kwargs = m.call_args
    assert kwargs["default_headers"] == {"x-opencode-session": "session-from-env"}


def test_cancellation_during_a_degraded_call_is_propagated(no_retry_sleep: Any) -> None:
    """縮退の段の呼び直し中のキャンセルも握り潰さない（T104）。

    初回の上限超過で梯子に入り、1 段目の呼び直しでキャンセルされる経路。キャンセルを
    縮退のループで握り潰すと、グラフを外から止められなくなる（既存の
    `test_cancellation_is_not_retried` は初回呼び出し側だけを固定している）。
    """
    options = _degrade_options()
    model, patch = _patch_model([_context_length_error(), asyncio.CancelledError()])

    with patch, pytest.raises(asyncio.CancelledError):
        asyncio.run(
            ainvoke_text(
                _LONG_PROMPT,
                env_prefix=None,
                retry_max=2,
                retry_wait_seconds=0.0,
                degrade=options,
            )
        )

    # 初回（上限超過）＋ 1 段目（キャンセル）。再試行も次の段も起こらない
    assert model.runnable.calls == 2
    assert [len(prompt) for prompt in model.runnable.prompts] == [10000, 9000]
