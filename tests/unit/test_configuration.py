"""`configuration.py` の設定解決を固定する（後継: `tests/test_configuration.py`）。

LangGraph の `RunnableConfig`（Studio UI / `__main__.py` が組み立てる
`{"configurable": {...}}`）から `Configuration` への解決は、ノードが
`Configuration.from_runnable_config(config)` で毎回読むため、パイプライン全体の
既定値の出所になる。ここでは次を固定する。

1. 宣言されたフィールドと既定値（`published_after` を含む 8 件）
2. `configurable` に指定された値がそのまま採用されること
3. 指定のない値・明示的な `None` は既定値へフォールバックすること
4. `configurable` 以外のキー・未知のキーがあっても例外にしないこと
   （LangGraph は `recursion_limit` や内部キーを同じ mapping に混ぜる）
5. JSON スキーマの宣言と `model_dump` の往復
"""

from __future__ import annotations

import pytest
from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration

#: 宣言された全フィールドと既定値。
DEFAULTS = {
    "platform": "",
    "output_format": None,
    "max_results": 5,
    "sort_by": "relevance",
    "transcript_language": "ja",
    "use_trends": False,
    "cache_dir": None,
    "published_after": None,
}


def test_defaults_cover_every_declared_field():
    """既定値の表が宣言された全フィールドを覆っている。

    `configuration.py` にフィールドを足したとき、この表（と下の既定値テスト）を
    更新し忘れれば落ちる。LangGraph Studio の入力欄はこの宣言から生成される。
    """
    config = Configuration()

    assert set(config.model_dump()) == set(DEFAULTS)
    assert {key: getattr(config, key) for key in DEFAULTS} == DEFAULTS


def test_custom_values_are_preserved():
    """明示した値はそのまま保持される。"""
    config = Configuration(
        platform="youtube",
        output_format="json",
        max_results=10,
        sort_by="likes",
        transcript_language="en",
        use_trends=True,
        cache_dir="/tmp/cache",
        published_after="2025-01-01",
    )

    assert config.platform == "youtube"
    assert config.output_format == "json"
    assert config.max_results == 10
    assert config.sort_by == "likes"
    assert config.transcript_language == "en"
    assert config.use_trends is True
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
            "use_trends": True,
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
        "use_trends": True,
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
        pytest.param("use_trends", False, id="false"),
        pytest.param("cache_dir", "", id="empty-string-list"),
    ],
)
def test_falsy_values_are_treated_as_specified(key: str, value: object) -> None:
    """`0` / `False` / 空文字は「指定」として扱う。

    フィルタを `if v is not None` ではなく `if v` にすると、これらの指定が
    無言で既定値に戻る（`use_trends=False` が `False` のままなのは偶然一致）。
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
