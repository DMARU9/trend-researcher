"""`config.py` の単体テスト（環境変数・`.env` からの設定解決）。

固定する契約:

- 優先順位は `TR_*`（一般） > `XTR_*` / `YTR_*`（プラットフォーム固有） > 既定値
- 空文字は「未設定」として扱い、次の優先順位へフォールバックする（`or` の意味）
- 相対パスはリポジトリ直下基準、`~` は展開、絶対パスはそのまま解決する
- `cache_dir` と `max_results` の引数上書きは環境変数より強い
- `get_config()` はプロセス内で共有される（`lru_cache`）

実リポジトリの `.env` は読み込ませない。`.env` の内容でテスト結果が変わると、
「環境ごとに結果が違う」テストになり検証として成立しないためである
（`.env` を読む経路自体は `_load_env_once` の単体テストで固定する）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trend_researcher import config as config_module
from trend_researcher.config import _REPO_ROOT, Config, _resolve_path, get_config

#: 設定解決に影響する環境変数（`.env` のキーに対応）。テストごとに全消しする。
_ENV_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    *(f"{prefix}_{name}" for prefix in ("TR", "XTR", "YTR") for name in (
        "MODEL",
        "MAX_RESULTS",
        "SEARCH_POOL_SIZE",
        "ACCOUNTS_DB",
        "TRANSCRIPT_LANG",
        "CACHE_DIR",
        "MAX_RETRIES",
    )),
)

DEFAULT_MODEL = "openai:mimo-v2.5"
DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"


@pytest.fixture(autouse=True)
def isolated_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` の読み込みとプロセス環境を遮断し、検証を決定的にする。"""
    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: None)
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    get_config.cache_clear()


# --- 既定値 ---------------------------------------------------------------


def test_defaults_when_nothing_is_configured() -> None:
    config = Config.load()

    assert config.model == DEFAULT_MODEL
    assert config.openai_base_url == DEFAULT_BASE_URL
    assert config.openai_api_key == ""
    assert config.max_results == 5
    assert config.search_pool_size == 50
    assert config.transcript_language == "ja"
    assert config.max_retries == 3
    assert config.cache_dir == (_REPO_ROOT / "cache").resolve()
    assert config.accounts_db == (_REPO_ROOT / "accounts.db").resolve()


def test_unknown_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_UNKNOWN_SETTING", "1")

    assert Config.load().model == DEFAULT_MODEL


# --- 優先順位 -------------------------------------------------------------


def test_generic_tr_wins_over_platform_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_MODEL", "generic-model")
    monkeypatch.setenv("XTR_MODEL", "x-model")

    assert Config.load(platform="x").model == "generic-model"


def test_platform_prefix_is_used_when_generic_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_MODEL", "x-model")

    assert Config.load(platform="x").model == "x-model"


def test_platform_prefix_does_not_leak_across_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_MODEL", "x-model")
    monkeypatch.setenv("YTR_MODEL", "youtube-model")

    assert Config.load(platform="x").model == "x-model"
    assert Config.load(platform="youtube").model == "youtube-model"


def test_youtube_prefix_is_not_used_for_x(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTR_MODEL", "youtube-model")

    assert Config.load(platform="x").model == DEFAULT_MODEL


def test_default_is_used_when_neither_is_set() -> None:
    assert Config.load(platform="youtube").model == DEFAULT_MODEL


# --- 空文字の扱い ---------------------------------------------------------


def test_empty_generic_falls_back_to_platform_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """空文字は「未設定」と同じ扱い（`os.getenv(...) or ...`）。"""
    monkeypatch.setenv("TR_MODEL", "")
    monkeypatch.setenv("XTR_MODEL", "x-model")

    assert Config.load(platform="x").model == "x-model"


def test_empty_generic_and_prefix_fall_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_MODEL", "")
    monkeypatch.setenv("XTR_MODEL", "")

    assert Config.load(platform="x").model == DEFAULT_MODEL


def test_empty_string_is_kept_for_unprefixed_openai_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """`OPENAI_BASE_URL` は `or` を使わないため、空文字がそのまま残る（非対称）。"""
    monkeypatch.setenv("OPENAI_BASE_URL", "")

    assert Config.load().openai_base_url == ""


def test_openai_variables_are_not_prefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """`OPENAI_*` は接頭辞の対象外（`TR_` / `XTR_` 版は読まれない）。"""
    monkeypatch.setenv("TR_OPENAI_BASE_URL", "https://tr.example/v1")
    monkeypatch.setenv("XTR_OPENAI_BASE_URL", "https://xtr.example/v1")

    assert Config.load(platform="x").openai_base_url == DEFAULT_BASE_URL


def test_openai_api_key_and_base_url_are_read_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://zen.example/v1")

    config = Config.load()

    assert config.openai_api_key == "sk-test"
    assert config.openai_base_url == "https://zen.example/v1"


# --- 数値の解釈 -----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value", "field"),
    [
        ("TR_MAX_RESULTS", "9", "max_results"),
        ("TR_SEARCH_POOL_SIZE", "80", "search_pool_size"),
        ("TR_MAX_RETRIES", "1", "max_retries"),
    ],
)
def test_numeric_settings_are_parsed_from_env(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, field: str
) -> None:
    monkeypatch.setenv(name, value)

    assert getattr(Config.load(), field) == int(value)


def test_non_integer_numeric_setting_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """数値に解釈できない値は黙って既定へ落とさず、その場で失敗させる。"""
    monkeypatch.setenv("TR_MAX_RESULTS", "たくさん")

    with pytest.raises(ValueError, match="invalid literal"):
        Config.load()


# --- パス解決 -------------------------------------------------------------


def test_relative_cache_dir_is_resolved_against_repository_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TR_CACHE_DIR", "tmp/relative-cache")

    assert Config.load().cache_dir == (_REPO_ROOT / "tmp/relative-cache").resolve()


def test_absolute_cache_dir_is_used_as_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "abs-cache"
    monkeypatch.setenv("TR_CACHE_DIR", str(target))

    assert Config.load().cache_dir == target.resolve()


def test_tilde_cache_dir_is_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_CACHE_DIR", "~/tr_cache_for_test")

    assert Config.load().cache_dir == (Path.home() / "tr_cache_for_test").resolve()


def test_accounts_db_uses_platform_prefix_and_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`XTR_ACCOUNTS_DB` は X でだけ読まれ、相対パスはリポジトリ直下基準で解決される。"""
    monkeypatch.setenv("XTR_ACCOUNTS_DB", "data/accounts.db")

    assert Config.load(platform="x").accounts_db == (_REPO_ROOT / "data/accounts.db").resolve()
    assert Config.load(platform="youtube").accounts_db == (_REPO_ROOT / "accounts.db").resolve()


def test_resolve_path_expands_tilde_and_absolute(tmp_path: Path) -> None:
    assert _resolve_path("~").resolve() == Path.home()
    assert _resolve_path(str(tmp_path)) == tmp_path


# --- 引数による上書き -----------------------------------------------------


def test_cache_dir_argument_beats_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_CACHE_DIR", str(tmp_path / "from-env"))

    assert Config.load(cache_dir=str(tmp_path / "from-argument")).cache_dir == (
        tmp_path / "from-argument"
    ).resolve()


def test_cache_dir_argument_expands_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Config.load(cache_dir="~/tr_arg_cache").cache_dir == (
        Path.home() / "tr_arg_cache"
    ).resolve()


def test_max_results_argument_beats_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_MAX_RESULTS", "9")

    assert Config.load(max_results=12).max_results == 12


def test_max_results_argument_none_keeps_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TR_MAX_RESULTS", "9")

    assert Config.load(max_results=None).max_results == 9


# --- .env の読み込み ------------------------------------------------------


def test_load_env_once_reads_env_file_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(config_module, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(config_module, "load_dotenv", lambda path=None, **kw: calls.append(path))
    (tmp_path / ".env").write_text("TR_MODEL=from-file\n", encoding="utf-8")

    config_module._load_env_once()

    assert calls == [tmp_path / ".env"]


def test_load_env_once_does_nothing_when_env_file_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(config_module, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(config_module, "load_dotenv", lambda path=None, **kw: calls.append(path))

    config_module._load_env_once()

    assert calls == []


def test_config_load_invokes_env_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`Config.load()` は毎回 `_load_env_once()` を通る（呼び出し側で事前準備が不要）。"""
    monkeypatch.setattr(config_module, "_REPO_ROOT", tmp_path)
    loads: list[int] = []
    monkeypatch.setattr(
        config_module, "load_dotenv", lambda path=None, **kw: loads.append(1)
    )
    (tmp_path / ".env").write_text("TR_MODEL=from-file\n", encoding="utf-8")

    Config.load()

    assert loads == [1]


# --- プロセス内共有 -------------------------------------------------------


def test_get_config_is_cached_and_uses_x_defaults() -> None:
    first = get_config()

    assert first is get_config()
    assert first.model == DEFAULT_MODEL


def test_get_config_cache_can_be_cleared() -> None:
    first = get_config()
    get_config.cache_clear()
    second = get_config()

    assert first is not second
