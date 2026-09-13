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

from typing import Any
from unittest import mock

import pytest

from trend_researcher import config as config_module
from trend_researcher.tools import llm
from trend_researcher.tools.llm import build_model

#: モデル解決に影響する環境変数。テストごとに全消しする。
_ENV_KEYS = ("TR_MODEL", "XTR_MODEL", "YTR_MODEL", "OPENAI_API_KEY", "OPENAI_BASE_URL")

#: 既定のモデル名（旧 `Config.model` から `tools/llm.py` へ残した値）。
_DEFAULT_MODEL = "openai:mimo-v2.5"


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` の読み込みとプロセス環境を遮断し、検証を決定的にする。"""
    monkeypatch.setattr(llm, "load_dotenv", lambda *args, **kwargs: None)
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


def test_env_loading_is_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    """`build_model` は `.env` の読み込みを通す（環境変数の出所を保つ）。"""
    called: list[bool] = []
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: called.append(True))
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **k: None)

    _model_name()

    assert called == [True]
