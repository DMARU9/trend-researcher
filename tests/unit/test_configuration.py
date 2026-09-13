"""`configuration.py` の設定解決を固定する（後継: `tests/test_configuration.py`）。

LangGraph の `RunnableConfig`（Studio UI / `__main__.py` が組み立てる
`{"configurable": {...}}`）から `Configuration` への解決は、ノードが
`Configuration.from_runnable_config(config)` で毎回読むため、パイプライン全体の
既定値の出所になる。ここでは次を固定する。

1. 宣言されたフィールドと既定値（`published_after` を含む 7 件。`use_trends` は T032 で削除済み）
2. `configurable` に指定された値がそのまま採用されること
3. 指定のない値・明示的な `None` は既定値へフォールバックすること
4. `configurable` 以外のキー・未知のキーがあっても例外にしないこと
   （LangGraph は `recursion_limit` や内部キーを同じ mapping に混ぜる）
5. JSON スキーマの宣言と `model_dump` の往復
"""

from __future__ import annotations

import pytest
from langchain_core.runnables import RunnableConfig

from trend_researcher import config as config_module
from trend_researcher.configuration import Configuration

#: 宣言された全フィールドと既定値。
DEFAULTS = {
    "platform": "",
    "output_format": None,
    "max_results": 5,
    "sort_by": "relevance",
    "transcript_language": "ja",
    "cache_dir": None,
    "published_after": None,
}


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """実 `.env` と `TR_*` / `XTR_*` / `YTR_*` を遮断し、検証を決定的にする。

    `load()` を検証するテストが実環境の `.env` の内容で変わると、「環境ごとに
    結果が違う」テストになり検証として成立しない。
    """
    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: None)
    for key in ("TR_", "XTR_", "YTR_"):
        monkeypatch.delenv(f"{key}MAX_RESULTS", raising=False)
        monkeypatch.delenv(f"{key}TRANSCRIPT_LANG", raising=False)
        monkeypatch.delenv(f"{key}CACHE_DIR", raising=False)
        monkeypatch.delenv(f"{key}SORT_BY", raising=False)
        monkeypatch.delenv(f"{key}PLATFORM", raising=False)
        monkeypatch.delenv(f"{key}OUTPUT_FORMAT", raising=False)


def test_defaults_cover_every_declared_field():
    """既定値の表が宣言された全フィールドを覆っている。

    `configuration.py` にフィールドを足したとき、この表（と下の既定値テスト）を
    更新し忘れれば落ちる。LangGraph Studio の入力欄はこの宣言から生成される。
    """
    config = Configuration()

    assert set(config.model_dump()) == set(DEFAULTS)
    assert {key: getattr(config, key) for key in DEFAULTS} == DEFAULTS


def test_use_trends_is_not_declared():
    """`use_trends` は宣言されていない（FR-009 / REM-003）。"""
    assert "use_trends" not in Configuration.model_fields


def test_custom_values_are_preserved():
    """明示した値はそのまま保持される。"""
    config = Configuration(
        platform="youtube",
        output_format="json",
        max_results=10,
        sort_by="likes",
        transcript_language="en",
        cache_dir="/tmp/cache",
        published_after="2025-01-01",
    )

    assert config.platform == "youtube"
    assert config.output_format == "json"
    assert config.max_results == 10
    assert config.sort_by == "likes"
    assert config.transcript_language == "en"
    assert config.cache_dir == "/tmp/cache"
    assert config.published_after == "2025-01-01"


def test_platform_is_not_validated_at_this_layer():
    """`platform` は文字列として受理し、検証は provider 解決側に任せる。

    未指定（空文字）は「既定のプラットフォーム」として `get_provider` が
    最初の登録に解決し、未知の値は「provider が見つからない」として CLI が
    終了コード 2 で扱う。ここで列挙型にすると、その終了コード契約より手前で
    例外になる。
    """
    unknown = Configuration(platform="bogus")

    assert unknown.platform == "bogus"


def test_platform_defaults_to_blank_so_the_registry_decides():
    """未指定は空文字のまま保持し、既定をコアが決めない（FR-007）。"""
    assert Configuration().platform == ""
    assert Configuration.from_runnable_config({"configurable": {}}).platform == ""


def test_from_runnable_config_uses_configurable_values():
    """`configurable` の値がすべて採用される。"""
    rc: RunnableConfig = {
        "configurable": {
            "platform": "youtube",
            "output_format": "json",
            "max_results": 10,
            "sort_by": "likes",
            "transcript_language": "en",
            "cache_dir": "/tmp/cache",
            "published_after": "2025-01-01",
        }
    }

    config = Configuration.from_runnable_config(rc)

    assert config.model_dump() == {
        "platform": "youtube",
        "output_format": "json",
        "max_results": 10,
        "sort_by": "likes",
        "transcript_language": "en",
        "cache_dir": "/tmp/cache",
        "published_after": "2025-01-01",
    }


def test_from_runnable_config_falls_back_for_partial_config():
    """指定のないキーは既定値になる。"""
    config = Configuration.from_runnable_config({"configurable": {"platform": "youtube"}})

    assert config.platform == "youtube"
    assert config.output_format is None  # 未指定時は None（LLM が判断）
    assert config.max_results == 5
    assert config.sort_by == "relevance"


def test_from_runnable_config_with_empty_config():
    """`configurable` が空でも既定値で生成できる。"""
    config = Configuration.from_runnable_config({"configurable": {}})

    assert config.model_dump() == DEFAULTS


def test_from_runnable_config_with_none():
    """`RunnableConfig` 自体が None でも既定値で生成できる。"""
    config = Configuration.from_runnable_config(None)

    assert config.model_dump() == DEFAULTS


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param("max_results", 0, id="zero"),
        pytest.param("published_after", "", id="empty-string"),
        pytest.param("cache_dir", "", id="empty-string-list"),
    ],
)
def test_falsy_values_are_treated_as_specified(key: str, value: object) -> None:
    """`0` / 空文字は「指定」として扱う。

    フィルタを `if v is not None` ではなく `if v` にすると、これらの指定が
    無言で既定値に戻る。
    """
    config = Configuration.from_runnable_config({"configurable": {key: value}})

    assert getattr(config, key) == value


def test_from_runnable_config_ignores_none_values():
    """明示的な `None` は既定値へフォールバックする（LangGraph が None を混ぜるため）。"""
    config = Configuration.from_runnable_config(
        {"configurable": {"platform": "youtube", "max_results": None, "cache_dir": None}}
    )

    assert config.platform == "youtube"
    assert config.max_results == 5
    assert config.cache_dir is None


def test_from_runnable_config_ignores_non_configurable_keys():
    """`configurable` 以外のキー（`recursion_limit` 等）は無視される。"""
    config = Configuration.from_runnable_config(
        {"configurable": {"platform": "youtube"}, "recursion_limit": 25}
    )

    assert config.platform == "youtube"
    assert config.max_results == 5


def test_from_runnable_config_ignores_unknown_keys():
    """未知のキーが混ざっても例外にしない（LangGraph は内部キーを同居させる）。"""
    config = Configuration.from_runnable_config(
        {"configurable": {"platform": "youtube", "__pregel_resuming": True, "unknown": "x"}}
    )

    assert config.platform == "youtube"
    assert not hasattr(config, "unknown")


def test_model_json_schema_declares_all_fields():
    """JSON スキーマが全フィールドと既定値を宣言する（Studio UI の入力欄の元）。"""
    schema = Configuration.model_json_schema()
    props = schema["properties"]

    assert set(props) == set(DEFAULTS)
    for key, value in DEFAULTS.items():
        if value is not None:
            assert props[key].get("default") == value, key


def test_model_dump_roundtrip():
    """`model_dump` → `Configuration` の往復で同値になる。"""
    original = Configuration(platform="youtube", max_results=10)

    assert Configuration(**original.model_dump()) == original


# --- 環境変数を読む範囲（SET-002 / SET-005）--------------------------------


def test_load_resolves_only_the_three_settings(monkeypatch: pytest.MonkeyPatch):
    """`load()` が環境変数から読むのは 3 項目だけ（他のフィールドは増やさない）。

    Studio の入力欄は宣言から生成されるため、環境変数から読む項目が増えると
    「宣言していないのに値が変わる」フィールドができる（SET-005）。
    """
    monkeypatch.setenv("TR_MAX_RESULTS", "9")
    monkeypatch.setenv("TR_TRANSCRIPT_LANG", "en")
    monkeypatch.setenv("XTR_CACHE_DIR", "/tmp/from-env")
    # 宣言はあるが環境変数からは読まない項目（未定義の環境変数として無視される）
    monkeypatch.setenv("TR_SORT_BY", "likes")
    monkeypatch.setenv("TR_PLATFORM", "youtube")
    monkeypatch.setenv("TR_OUTPUT_FORMAT", "json")

    config = Configuration.load(env_prefix="XTR")

    assert config.max_results == 9
    assert config.transcript_language == "en"
    assert config.cache_dir == "/tmp/from-env"
    assert config.sort_by == "relevance"
    assert config.platform == ""
    assert config.output_format is None


# --- 環境変数を読まない経路（SET-007）--------------------------------------


def test_from_runnable_config_does_not_read_environment(monkeypatch: pytest.MonkeyPatch):
    """`from_runnable_config` は環境変数を読まない。

    ノードが受け取る値は注入された 1 経路（`configurable`）だけで決まる（FR-014）。
    解決は呼び出し側（CLI / Studio）が `load()` で済ませておく。
    """
    monkeypatch.setenv("TR_MAX_RESULTS", "9")
    monkeypatch.setenv("TR_TRANSCRIPT_LANG", "en")

    config = Configuration.from_runnable_config({"configurable": {}})

    assert config.max_results == 5
    assert config.transcript_language == "ja"


def test_explicit_values_beat_environment_after_load(monkeypatch: pytest.MonkeyPatch):
    """`load()` の結果に明示指定を重ねると明示指定が残る（SET-006 の合成規則）。"""
    monkeypatch.setenv("TR_MAX_RESULTS", "9")

    config = Configuration.load(env_prefix="XTR").model_copy(update={"max_results": 3})

    assert config.max_results == 3
    assert "max_results" in config.model_fields_set


# --- パッケージの公開面（SET-012）------------------------------------------


def test_package_does_not_reexport_the_old_config_class():
    """旧 `Config` の re-export を削除した（SET-012 / REM-007）。

    実測では `Configuration` は `__init__.py` の公開面に存在せず、re-export されて
    いたのは旧 `Config` だけだった。したがって公開面を**広げず**、削除のみを行う。
    """
    import trend_researcher

    assert "Config" not in trend_researcher.__all__
    assert not hasattr(trend_researcher, "Config")


def test_package_keeps_the_graph_and_rendering_entry_points():
    """`trend_researcher`（グラフ本体）と `render_report` の re-export は維持する。"""
    import trend_researcher

    assert {"trend_researcher", "render_report", "ResearchReport", "Candidate"} <= set(
        trend_researcher.__all__
    )
