"""設定解決の単体テスト（環境変数・`.env`・優先順位）。

固定する契約:

- 優先順位は `TR_*`（一般） > `{env_prefix}_*`（プラットフォーム固有） > 既定値。
  接頭辞は provider が渡す（`get_provider(platform).env_prefix` で `XTR` / `YTR`）。
  `env_prefix=None` のときは `TR_*` のみを見る
- 空文字は「未設定」として扱い、次の優先順位へフォールバックする（`or` の意味）
- 相対パスはリポジトリ直下基準、`~` は展開、絶対パスはそのまま解決する
- 明示指定（`Configuration` の `model_fields_set` に残る値）は環境変数より強い
- `Configuration.load()` はプロセス内で共有しない（`lru_cache` を持たない）

実リポジトリの `.env` は読み込ませない。`.env` の内容でテスト結果が変わると、
「環境ごとに結果が違う」テストになり検証として成立しないためである
（`.env` を読む経路自体は `config.load_env()` の単体テストで固定する。読み込みが
`config.py` の 1 箇所であることも同節の走査テストで固定する）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trend_researcher import config as config_module
from trend_researcher.config import _REPO_ROOT, _resolve_path
from trend_researcher.configuration import Configuration, resolve_env

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


@pytest.fixture(autouse=True)
def isolated_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` の読み込みとプロセス環境を遮断し、検証を決定的にする。"""
    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: None)
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# --- 既定値 ---------------------------------------------------------------


def test_defaults_when_nothing_is_configured() -> None:
    config = Configuration.load()

    assert config.max_results == 5
    assert config.transcript_language == "ja"
    assert config.cache_dir == str((_REPO_ROOT / "cache").resolve())
    # 環境変数から解決しない項目は既定のまま（Studio の契約を変えない。SET-005）
    assert config.platform == ""
    assert config.sort_by == "relevance"
    assert config.output_format is None
    assert config.published_after is None


def test_unknown_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_UNKNOWN_SETTING", "1")

    assert Configuration.load().max_results == 5


# --- 優先順位（resolve_env）------------------------------------------------


def test_generic_tr_wins_over_platform_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_MODEL", "generic-model")
    monkeypatch.setenv("XTR_MODEL", "x-model")

    assert resolve_env("MODEL", default="fallback", env_prefix="XTR") == "generic-model"


def test_platform_prefix_is_used_when_generic_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_MODEL", "x-model")

    assert resolve_env("MODEL", default="fallback", env_prefix="XTR") == "x-model"


def test_platform_prefix_does_not_leak_across_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_MODEL", "x-model")
    monkeypatch.setenv("YTR_MODEL", "youtube-model")

    assert resolve_env("MODEL", default="fallback", env_prefix="XTR") == "x-model"
    assert resolve_env("MODEL", default="fallback", env_prefix="YTR") == "youtube-model"


def test_youtube_prefix_is_not_used_for_x(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTR_MODEL", "youtube-model")

    assert resolve_env("MODEL", default="fallback", env_prefix="XTR") == "fallback"


def test_default_is_used_when_neither_is_set() -> None:
    assert resolve_env("MODEL", default="fallback", env_prefix="YTR") == "fallback"


def test_resolve_env_without_prefix_ignores_platform_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`env_prefix=None` は `TR_*` のみを見る（ノードが接頭辞を知らない経路）。"""
    monkeypatch.setenv("XTR_MODEL", "x-model")

    assert resolve_env("MODEL", default="fallback") == "fallback"


# --- 優先順位（Configuration.load）----------------------------------------


def test_load_prefers_generic_tr_over_platform_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_MAX_RESULTS", "9")
    monkeypatch.setenv("XTR_MAX_RESULTS", "8")

    assert Configuration.load(env_prefix="XTR").max_results == 9


def test_load_uses_platform_prefix_when_generic_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTR_MAX_RESULTS", "7")

    assert Configuration.load(env_prefix="YTR").max_results == 7


def test_load_does_not_leak_across_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_MAX_RESULTS", "8")
    monkeypatch.setenv("YTR_MAX_RESULTS", "7")

    assert Configuration.load(env_prefix="XTR").max_results == 8
    assert Configuration.load(env_prefix="YTR").max_results == 7


def test_load_falls_back_to_the_default_without_env_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YTR_MAX_RESULTS", "7")

    assert Configuration.load().max_results == 5


def test_load_resolves_transcript_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_TRANSCRIPT_LANG", "en")

    assert Configuration.load(env_prefix="XTR").transcript_language == "en"


def test_load_keeps_no_process_wide_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """`lru_cache` を持たない（毎回環境変数を読む。SET-010）。"""
    first = Configuration.load()
    monkeypatch.setenv("TR_MAX_RESULTS", "9")

    assert first.max_results == 5
    assert Configuration.load().max_results == 9


# --- 空文字の扱い ---------------------------------------------------------


def test_empty_generic_falls_back_to_platform_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """空文字は「未設定」と同じ扱い（`os.getenv(...) or ...`）。"""
    monkeypatch.setenv("TR_MAX_RESULTS", "")
    monkeypatch.setenv("XTR_MAX_RESULTS", "8")

    assert Configuration.load(env_prefix="XTR").max_results == 8


def test_empty_generic_and_prefix_fall_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_MAX_RESULTS", "")
    monkeypatch.setenv("XTR_MAX_RESULTS", "")

    assert Configuration.load(env_prefix="XTR").max_results == 5


def test_empty_resolve_env_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_MODEL", "")

    assert resolve_env("MODEL", default="fallback", env_prefix="XTR") == "fallback"


# --- 数値の解釈 -----------------------------------------------------------


def test_numeric_setting_is_parsed_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_MAX_RESULTS", "9")

    assert Configuration.load().max_results == 9


def test_non_integer_numeric_setting_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """数値に解釈できない値は黙って既定へ落とさず、その場で失敗させる。

    実測（2026-09-13）: `SET-011` は「既定値 5（例外にしない。現行と同じ）」と
    しているが、現行実装は `int()` で `ValueError` になる（既存テスト
    `test_non_integer_numeric_setting_raises` が固定）。T039 の指示
    「期待値は変更前と同一」に従い例外を維持する。
    """
    monkeypatch.setenv("TR_MAX_RESULTS", "たくさん")

    with pytest.raises(ValueError, match="invalid literal"):
        Configuration.load()


# --- パス解決 -------------------------------------------------------------


def test_relative_cache_dir_is_resolved_against_repository_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TR_CACHE_DIR", "tmp/relative-cache")

    assert Configuration.load().cache_dir == str((_REPO_ROOT / "tmp/relative-cache").resolve())


def test_absolute_cache_dir_is_used_as_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "abs-cache"
    monkeypatch.setenv("TR_CACHE_DIR", str(target))

    assert Configuration.load().cache_dir == str(target.resolve())


def test_tilde_cache_dir_is_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_CACHE_DIR", "~/tr_cache_for_test")

    assert Configuration.load().cache_dir == str((Path.home() / "tr_cache_for_test").resolve())


def test_empty_cache_dir_falls_back_to_repository_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TR_CACHE_DIR", "")

    assert Configuration.load().cache_dir == str((_REPO_ROOT / "cache").resolve())


def test_platform_prefix_is_used_for_cache_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTR_CACHE_DIR", "cache-from-youtube")

    assert Configuration.load(env_prefix="YTR").cache_dir == str(
        (_REPO_ROOT / "cache-from-youtube").resolve()
    )


def test_resolve_path_expands_tilde_and_absolute(tmp_path: Path) -> None:
    assert _resolve_path("~").resolve() == Path.home()
    assert _resolve_path(str(tmp_path)) == tmp_path


# --- 明示指定（CLI などの上書き）------------------------------------------


def test_explicit_max_results_beats_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_MAX_RESULTS", "9")

    config = Configuration.load(env_prefix="XTR").model_copy(update={"max_results": 12})

    assert config.max_results == 12
    assert "max_results" in config.model_fields_set


def test_explicit_transcript_language_beats_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TR_TRANSCRIPT_LANG", "en")

    config = Configuration.load().model_copy(update={"transcript_language": "ja"})

    assert config.transcript_language == "ja"


def test_explicit_cache_dir_beats_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_CACHE_DIR", str(tmp_path / "from-env"))

    config = Configuration.load().model_copy(update={"cache_dir": str(tmp_path / "from-argument")})

    assert config.cache_dir == str(tmp_path / "from-argument")


# --- .env の読み込み ------------------------------------------------------


def test_load_env_reads_env_file_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(config_module, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(config_module, "load_dotenv", lambda path=None, **kw: calls.append(path))
    (tmp_path / ".env").write_text("TR_MODEL=from-file\n", encoding="utf-8")

    config_module.load_env()

    assert calls == [tmp_path / ".env"]


def test_load_env_does_nothing_when_env_file_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(config_module, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(config_module, "load_dotenv", lambda path=None, **kw: calls.append(path))

    config_module.load_env()

    assert calls == []


def test_dotenv_is_read_from_exactly_one_module() -> None:
    """`load_dotenv` を呼ぶのは `config.py` の 1 箇所だけ（FR-013 / SET-002）。

    LLM 構築の境界（`tools/llm.py`）も `config.load_env()` を通す。境界が自前で
    `.env` を読むと、Studio のように `Configuration.load()` を通らない実行で
    「どの値が効くのか」が 2 箇所に分かれる（T071）。
    """
    package_root = Path(config_module.__file__).resolve().parent
    hits = sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*.py")
        if "load_dotenv(" in path.read_text(encoding="utf-8")
    )

    assert hits == ["config.py"]


def test_config_load_invokes_env_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`Configuration.load()` は毎回 `load_env()` を通る（呼び出し側で事前準備が不要）。"""
    monkeypatch.setattr(config_module, "_REPO_ROOT", tmp_path)
    loads: list[int] = []
    monkeypatch.setattr(
        config_module, "load_dotenv", lambda path=None, **kw: loads.append(1)
    )
    (tmp_path / ".env").write_text("TR_MODEL=from-file\n", encoding="utf-8")

    Configuration.load()

    assert loads == [1]


# --- 旧設定型の削除（SC-003 / REM-006 / REM-007）--------------------------


def test_old_config_class_is_removed() -> None:
    """実行時設定の型は `Configuration` の 1 つだけ（旧 `Config` と `get_config` は無い）。

    `config.py` に残るのはパス解決と `.env` 読み込みのヘルパのみで、設定値の宣言
    （同名フィールド）は持たない（SC-003）。
    """
    assert not hasattr(config_module, "Config")
    assert not hasattr(config_module, "get_config")
    assert not hasattr(config_module, "lru_cache")
