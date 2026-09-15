"""`configuration.py` の設定解決を固定する（後継: `tests/test_configuration.py`）。

LangGraph の `RunnableConfig`（Studio UI / `__main__.py` が組み立てる
`{"configurable": {...}}`）から `Configuration` への解決は、ノードが
`Configuration.from_runnable_config(config)` で毎回読むため、パイプライン全体の
既定値の出所になる。ここでは次を固定する。

1. 宣言されたフィールドと既定値・値域（既存 7 ＋ data-model §1.1 の追加 11。
   `use_trends` は T032 で削除済み）
2. `configurable` に指定された値がそのまま採用されること
3. 指定のない値・明示的な `None` は既定値へフォールバックすること
4. `configurable` 以外のキー・未知のキーがあっても例外にしないこと
   （LangGraph は `recursion_limit` や内部キーを同じ mapping に混ぜる）
5. JSON スキーマの宣言と `model_dump` の往復
"""

from __future__ import annotations

from typing import Literal, get_args, get_origin

import pytest
from annotated_types import Ge, Le
from langchain_core.runnables import RunnableConfig
from pydantic import Field, ValidationError

from trend_researcher import config as config_module
from trend_researcher import configuration as configuration_module
from trend_researcher.configuration import Configuration, ConfigurationError
from trend_researcher.providers.x import _explicit_setting

#: 宣言された全フィールドと既定値（既存 7 ＋ data-model §1.1 の追加 11）。
DEFAULTS = {
    "platform": "",
    "output_format": None,
    "max_results": 5,
    "sort_by": "relevance",
    "transcript_language": "ja",
    "cache_dir": None,
    "published_after": None,
    # --- 追加分（data-model §1.1）----------------------------------------
    "analysis_concurrency": 2,
    "retry_max": 2,
    "retry_wait_seconds": 1.0,
    "compression_threshold": 20000,
    "compression_timeout_seconds": 60.0,
    "degrade_max_attempts": 3,
    "shrink_ratio": 0.9,
    "min_input_chars": 1000,
    "self_review": True,
    "include_intermediate": False,
    "structured_method": "function_calling",
}

#: 追加 11 項目が env から読む名前（`load()` の解決対象。data-model §1.3）
ADDED_ENV_NAMES = (
    "ANALYSIS_CONCURRENCY",
    "RETRY_MAX",
    "RETRY_WAIT_SECONDS",
    "COMPRESSION_THRESHOLD",
    "COMPRESSION_TIMEOUT_SECONDS",
    "DEGRADE_MAX_ATTEMPTS",
    "SHRINK_RATIO",
    "MIN_INPUT_CHARS",
    "SELF_REVIEW",
    "INCLUDE_INTERMEDIATE",
    "STRUCTURED_METHOD",
)


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
        for name in ADDED_ENV_NAMES:
            monkeypatch.delenv(f"{key}{name}", raising=False)


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

    assert config.model_dump() == DEFAULTS | {
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
        # `0` は値域内で偽になる唯一の項目（`retry_max` の `ge` は 0）。
        # `max_results` は値域が 1 以上になったため 0 を指定できない（T078・契約 §2）。
        pytest.param("retry_max", 0, id="zero"),
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


def test_load_resolves_the_three_settings_and_the_added_eleven(
    monkeypatch: pytest.MonkeyPatch,
):
    """`load()` が環境変数から読むのは 3 ＋ 11 = 14 項目だけ。

    Studio の入力欄は宣言から生成されるため、環境変数から読む項目が増えると
    「宣言していないのに値が変わる」フィールドができる（SET-005）。ここでは
    追加分が env 経由でも動くことを固定し、`sort_by` / `platform` /
    `output_format` は読まないままであることも同時に固定する。
    """
    monkeypatch.setenv("TR_MAX_RESULTS", "9")
    monkeypatch.setenv("TR_TRANSCRIPT_LANG", "en")
    monkeypatch.setenv("XTR_CACHE_DIR", "/tmp/from-env")
    monkeypatch.setenv("TR_ANALYSIS_CONCURRENCY", "4")
    monkeypatch.setenv("XTR_RETRY_MAX", "7")
    monkeypatch.setenv("TR_SHRINK_RATIO", "0.5")
    monkeypatch.setenv("TR_SELF_REVIEW", "false")
    monkeypatch.setenv("TR_STRUCTURED_METHOD", "function_calling")
    # 宣言はあるが環境変数からは読まない項目（未定義の環境変数として無視される）
    monkeypatch.setenv("TR_SORT_BY", "likes")
    monkeypatch.setenv("TR_PLATFORM", "youtube")
    monkeypatch.setenv("TR_OUTPUT_FORMAT", "json")

    config = Configuration.load(env_prefix="XTR")

    assert config.max_results == 9
    assert config.transcript_language == "en"
    assert config.cache_dir == "/tmp/from-env"
    assert config.analysis_concurrency == 4  # TR_ が XTR_ より優先される
    assert config.retry_max == 7
    assert config.shrink_ratio == 0.5
    assert config.self_review is False
    assert config.structured_method == "function_calling"
    assert config.sort_by == "relevance"
    assert config.platform == ""
    assert config.output_format is None


def test_load_keeps_the_other_added_fields_at_their_defaults(monkeypatch: pytest.MonkeyPatch):
    """env に無い追加項目は既定値のまま（env 読み取りが既定値を押しのけない）。"""
    config = Configuration.load(env_prefix="XTR")

    assert config.retry_wait_seconds == 1.0
    assert config.compression_threshold == 20000
    assert config.compression_timeout_seconds == 60.0
    assert config.degrade_max_attempts == 3
    assert config.min_input_chars == 1000
    assert config.include_intermediate is False


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


def test_the_three_levels_resolve_in_the_declared_order(monkeypatch: pytest.MonkeyPatch):
    """既定値 < 環境変数 < 明示指定の順で確定する（SET-002 / SET-006）。

    同じ 1 項目を 3 段階で与え、各段でどの値が残るかを 1 つのテストで固定する。
    `load()` が戻した値に CLI が重ねる順序が逆になると、ここで落ちる。
    """
    assert Configuration.load(env_prefix="XTR").max_results == 5  # 既定値

    monkeypatch.setenv("TR_MAX_RESULTS", "9")
    from_env = Configuration.load(env_prefix="XTR")
    assert from_env.max_results == 9  # 環境変数 > 既定値

    explicit = from_env.model_copy(update={"max_results": 3})
    assert explicit.max_results == 3  # 明示指定 > 環境変数


#: `load()` が環境変数と `.env` から解決する 14 項目（SET-002）。
#: `platform` / `output_format` / `sort_by` / `published_after` は CLI・Studio の
#: 明示指定のみで決まる（env からは読まない。SET-005）。
ENV_RESOLVED_FIELDS = frozenset(
    {
        "max_results",
        "transcript_language",
        "cache_dir",
        "analysis_concurrency",
        "retry_max",
        "retry_wait_seconds",
        "compression_threshold",
        "compression_timeout_seconds",
        "degrade_max_attempts",
        "shrink_ratio",
        "min_input_chars",
        "self_review",
        "include_intermediate",
        "structured_method",
    }
)

#: CLI・Studio からのみ与える項目（env からは読まない）。
RUNTIME_ONLY_FIELDS = frozenset({"platform", "output_format", "sort_by", "published_after"})


def test_load_does_not_mark_unresolved_fields_as_explicit(monkeypatch: pytest.MonkeyPatch):
    """`load()` の `model_fields_set` は解決した 14 項目だけで、増えも減りもしない。

    消費側は `providers/x.py` の `_explicit_setting`（同集合にある項目だけを
    「明示指定」とみなす）。`model_validate(model_dump())` のような「全項目を明示
    指定に変える」実装に置き換わると、CLI が渡していない項目まで確定値になり
    SET-006（明示指定 > 環境変数）の意味が変わる。
    """
    assert Configuration().model_fields_set == set()  # 既定は「未指定」

    monkeypatch.setenv("TR_MAX_RESULTS", "9")
    from_env = Configuration.load(env_prefix="XTR")

    assert from_env.model_fields_set == set(ENV_RESOLVED_FIELDS)
    # CLI・Studio 専用の項目は「明示指定された」ことにしない
    assert not (RUNTIME_ONLY_FIELDS & from_env.model_fields_set)

    # 上書きは集合に 1 項目だけ足す（`_check_bounds` は集合を変えない）
    explicit = configuration_module._check_bounds(
        from_env.model_copy(update={"max_results": 3})
    )
    assert explicit.model_fields_set == set(ENV_RESOLVED_FIELDS) | {"max_results"}
    # `_explicit_setting` から見た値は確定値と一致する（意味が壊れていない）
    assert _explicit_setting(explicit, "max_results") == "3"
    assert _explicit_setting(explicit, "max_results") == str(explicit.max_results)


def test_max_results_declares_its_range_and_rejects_zero():
    """`max_results` も値域を宣言する（0 を弾き、既存テストが使う値は通す。契約 §2）。

    宣言は 2 つの経路で効く。生成時は Pydantic が `ValidationError` を送出し
    （追加 11 項目と同じ規則）、CLI の上書きは `model_copy` が検証しないため
    `_check_bounds` が `ConfigurationError` を送出する（実測に基づく）。
    """
    assert _declared_bounds("max_results") == (1, 100)

    with pytest.raises(ValidationError):
        Configuration(max_results=0)

    with pytest.raises(ConfigurationError) as excinfo:
        configuration_module._check_bounds(
            Configuration().model_copy(update={"max_results": 0})
        )

    assert excinfo.value.message == "設定が不正です: max_results=0（期待: 1 以上 100 以下の整数）"
    # 既存テストが実際に使う値（1 / 2 / 3 / 5 / 10）と上限の 100 は通す（FR-035）
    for value in (1, 2, 3, 5, 10, 100):
        configuration_module._check_bounds(Configuration(max_results=value))


def test_max_results_is_not_rounded_nor_replaced_by_a_default():
    """値域外を丸めない・既定値に置換しない（FR-024 / SC-023）。"""
    bad = Configuration().model_copy(update={"max_results": 101})

    with pytest.raises(ConfigurationError) as excinfo:
        configuration_module._check_bounds(bad)

    assert excinfo.value.field == "max_results"
    assert excinfo.value.value == 101  # 丸めていない（100 にならない）
    assert excinfo.value.value != Configuration().max_results  # 既定値でもない


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


# --- 追加 11 項目の宣言（data-model §1.1 / settings-contract §1・§2） -----------

#: 追加項目 → (`ge`, `le`, `x_oap_ui_config.type`)。既定値は `DEFAULTS` の表が持つ。
#: 値域は `data-model.md` §1.1 と `research.md` §R-20 の表。
ADDED_FIELDS: dict[str, tuple[object, object, str]] = {
    "analysis_concurrency": (1, 16, "number"),
    "retry_max": (0, 10, "number"),
    "retry_wait_seconds": (0.0, 60.0, "number"),
    "compression_threshold": (1000, None, "number"),
    "compression_timeout_seconds": (1.0, 300.0, "number"),
    "degrade_max_attempts": (1, 10, "number"),
    "shrink_ratio": (0.1, 0.9, "number"),
    "min_input_chars": (100, None, "number"),
    "self_review": (None, None, "boolean"),
    "include_intermediate": (None, None, "boolean"),
    "structured_method": (None, None, "text"),
}

#: 選択肢を持つ項目（`Literal` で宣言する。settings-contract §1）
CHOICE_FIELDS = {"structured_method": ("json_schema", "function_calling")}


def _declared_bounds(name: str) -> tuple[object, object]:
    """`ge` / `le` の宣言値を取り出す（未宣言は `None`）。"""
    metadata = Configuration.model_fields[name].metadata
    ge = next((item.ge for item in metadata if isinstance(item, Ge)), None)
    le = next((item.le for item in metadata if isinstance(item, Le)), None)
    return ge, le


def _ui_config(name: str) -> dict[str, object]:
    """JSON スキーマ上の `x_oap_ui_config` を取り出す（Studio の表示元）。"""
    return Configuration.model_json_schema()["properties"][name]["x_oap_ui_config"]


def test_every_declared_field_has_a_description():
    """全項目に説明がある（Studio の入力欄に説明が出る。FR-060）。"""
    missing = [name for name, field in Configuration.model_fields.items() if not field.description]

    assert missing == []


def test_added_fields_declare_defaults_and_ui_type():
    """追加 11 項目の既定値と UI 上の型が表のとおり。

    既定値は現行の挙動と同じでなければならない（`analysis_concurrency` = 2 は現行の
    `asyncio.Semaphore(2)`、`compression_threshold` = 20000 は現行の
    `source_text[:20000]`）。
    """
    config = Configuration()

    for name, (_ge, _le, ui_type) in ADDED_FIELDS.items():
        assert name in Configuration.model_fields, name
        assert name in DEFAULTS, name
        assert getattr(config, name) == DEFAULTS[name], name
        assert Configuration.model_fields[name].description, name
        assert _ui_config(name)["type"] == ui_type, name


def test_added_numeric_fields_declare_their_range():
    """追加の数値項目が `ge` / `le` を宣言する（丸めない前提の宣言。FR-024）。"""
    declared = {name: _declared_bounds(name) for name in ADDED_FIELDS}
    expected = {name: (ge, le) for name, (ge, le, _type) in ADDED_FIELDS.items()}

    assert declared == expected


def test_added_fields_reject_out_of_range_values():
    """宣言した値域の外は `ValidationError` になる（丸めない・置換しない）。"""
    for name, (ge, le, _type) in ADDED_FIELDS.items():
        if ge is not None:
            with pytest.raises(ValidationError, match="greater than or equal"):
                Configuration(**{name: ge - 1})
        if le is not None:
            with pytest.raises(ValidationError, match="less than or equal"):
                Configuration(**{name: le + 1})


def test_structured_method_is_a_literal_choice():
    """選択肢は `Literal` で宣言する（T004 の実測で `function_calling` を既定に確定）。"""
    field = Configuration.model_fields["structured_method"]

    assert get_args(field.annotation) == CHOICE_FIELDS["structured_method"]
    assert Configuration().structured_method == "function_calling"
    with pytest.raises(ValidationError):
        Configuration(structured_method="auto")


def test_added_fields_declare_the_studio_ui_config():
    """追加項目が `x_oap_ui_config` を持つ（label と desc も出す。FR-060）。"""
    for name in ADDED_FIELDS:
        ui = _ui_config(name)
        assert set(ui) >= {"type", "label", "desc"}, name
        assert ui["label"], name
        assert ui["desc"], name


# --- 宣言の網羅（US8 / FR-059 / settings-contract §1） -----------------------

#: `x_oap_ui_config` を要求しない既存 7 項目（data-model §1.1「既存 7 フィールドは
#: **そのまま**」＋ 同 §1.1 の不変条件 4「**追加フィールドに** `json_schema_extra` を
#: 付ける」）。`max_results` は T078 で値域と UI の宣言を足したため対象に含める。
FROZEN_LEGACY_FIELDS = frozenset(
    {"platform", "output_format", "sort_by", "transcript_language", "cache_dir", "published_after"}
)


def _ui_config_or_none(name: str) -> dict[str, object] | None:
    """JSON スキーマ上の `x_oap_ui_config`（無ければ `None`）。"""
    return Configuration.model_json_schema()["properties"][name].get("x_oap_ui_config")


def test_every_field_declares_its_ui_config_except_the_frozen_legacy_ones():
    """凍結された既存項目を除く全項目が `x_oap_ui_config` を持つ（FR-060）。

    走査の対象を「凍結された既存 6 項目」だけに限定する。ここを限定しないと、
    既存の宣言（`data-model.md` §1.1 が「そのまま」と定める）を変更する要求に
    なってしまう。逆に、**新しい項目を凍結扱いにして宣言を省く**ことはできない
    （例外集合そのものを固定する）。
    """
    assert FROZEN_LEGACY_FIELDS <= set(Configuration.model_fields)

    missing = [
        name
        for name in Configuration.model_fields
        if name not in FROZEN_LEGACY_FIELDS and _ui_config_or_none(name) is None
    ]

    assert missing == []


def test_declared_ui_types_follow_the_contract_table():
    """`x_oap_ui_config.type` が契約の対応表のとおり（settings-contract §1）。"""
    expected_by_annotation = {bool: "boolean", int: "number", float: "number"}

    declared: dict[str, str] = {}
    for name, field in Configuration.model_fields.items():
        ui = _ui_config_or_none(name)
        if ui is None:
            continue
        kind = expected_by_annotation.get(field.annotation)
        if kind is None:
            kind = "text"  # `str` / `Literal[...]` は text（契約の表）
        declared[name] = str(ui["type"])
        assert ui["type"] == kind, name

    # 走査が空虚でない（両方の型が実際に宣言されている）
    assert {"number", "boolean", "text"} <= set(declared.values())
    assert declared["structured_method"] == "text"


def test_every_numeric_field_declares_a_range():
    """数値項目（`int` / `float`）は `ge` か `le` を宣言する（FR-024 / FR-059）。

    値域の無い数値項目は「いくつでも受け付ける」ことと同じで、起動時の拒否
    （`_check_bounds`）も効かない。宣言と検証を一致させる。
    """
    numeric = {
        name: field
        for name, field in Configuration.model_fields.items()
        if field.annotation in (int, float)
    }

    missing = [name for name in numeric if _declared_bounds(name) == (None, None)]

    assert missing == []
    assert {"max_results", "analysis_concurrency", "shrink_ratio"} <= set(numeric)


def test_every_choice_field_is_declared_with_literals():
    """選択肢を持つ項目は `Literal` で宣言する（settings-contract §1）。"""
    choices = {
        name: get_args(field.annotation)
        for name, field in Configuration.model_fields.items()
        if get_origin(field.annotation) is Literal
    }

    assert choices == {"structured_method": ("json_schema", "function_calling")}
    for name, values in choices.items():
        assert len(values) >= 2, name
        # 選択肢は無限の文字列を受け付けない（`Literal` 以外の注釈に逃げていない）
        with pytest.raises(ValidationError):
            Configuration(**{name: "自動で選ぶ"})


# --- Studio 経路（US8 / FR-060 / settings-contract §4） ---------------------


def test_studio_can_change_an_added_setting_within_its_range():
    """Studio の `configurable` から値域内の値へ変更できる（SC-009）。"""
    config = Configuration.from_runnable_config(
        {"configurable": {"analysis_concurrency": 4}}
    )

    assert config.analysis_concurrency == 4


def test_studio_cannot_escape_the_declared_range():
    """値域外は `from_runnable_config` の時点で `ValidationError`（FR-060 / §3）。"""
    with pytest.raises(ValidationError):
        Configuration.from_runnable_config({"configurable": {"analysis_concurrency": 99}})


def test_every_added_field_is_changeable_from_the_studio_config():
    """追加 11 項目の**すべて**が Studio の `configurable` で変更できる（FR-060）。

    変更前は「既定値と違う値域内の値」を 1 つ選び、その値がそのまま採用される
    ことを確かめる（丸めや既定値への置換が起きない。FR-024）。
    """
    changes = {
        name: _probe_value(name, ge, le, ui_type)
        for name, (ge, le, ui_type) in ADDED_FIELDS.items()
    }

    for name, value in changes.items():
        config = Configuration.from_runnable_config({"configurable": {name: value}})
        assert getattr(config, name) == value, name
        assert getattr(config, name) != DEFAULTS[name], name  # 実際に変わっている


def _probe_value(name: str, ge: object, le: object, ui_type: str) -> object:
    """値域内で既定値と異なる「変更後」の値（変更できることの探針）。"""
    if ui_type == "boolean":
        return not DEFAULTS[name]
    if ui_type == "text":
        # 選択肢は宣言された 2 択のうち既定でない方（既定を変えても探針が追随する）
        return next(c for c in CHOICE_FIELDS[name] if c != DEFAULTS[name])
    if le is not None and le != DEFAULTS[name]:
        return le
    if ge is not None:
        return ge
    raise AssertionError(f"{name}: 値域内の探針を作れません（宣言を確認してください）")


# --- `ConfigurationError` の形（data-model §1.2 / settings-contract §3） --------


def test_configuration_error_names_the_field_value_and_range():
    """`message` は契約の書式で、項目名・入力値・期待する値域を必ず含む。"""
    error = ConfigurationError(field="max_results", value=0, expected="1 以上 100 以下の整数")

    assert error.field == "max_results"
    assert error.value == 0
    assert error.expected == "1 以上 100 以下の整数"
    assert error.message == "設定が不正です: max_results=0（期待: 1 以上 100 以下の整数）"
    assert str(error) == error.message


def test_configuration_error_is_a_value_error():
    """`ValueError` を派生させる（env の型変換失敗を包んでも既存の捕捉が生きる）。

    `load()` は `int("abc")` の `ValueError` も包む契約である（settings-contract §3）。
    ここが `Exception` 直系だと、既存の `pytest.raises(ValueError)` が素通りしなくなる。
    """
    assert issubclass(ConfigurationError, ValueError)


def test_load_raises_configuration_error_for_out_of_range_env(monkeypatch: pytest.MonkeyPatch):
    """env 経由の値域違反は `ConfigurationError`（`ValidationError` のままにしない）。"""
    monkeypatch.setenv("TR_ANALYSIS_CONCURRENCY", "99")

    with pytest.raises(ConfigurationError) as exc:
        Configuration.load(env_prefix="XTR")

    assert exc.value.field == "analysis_concurrency"
    assert exc.value.value == 99  # 解釈後の値。丸めて通すのではなく拒否する
    assert exc.value.message == "設定が不正です: analysis_concurrency=99（期待: 1 以上 16 以下の整数）"


def test_load_rejects_a_non_numeric_env_value(monkeypatch: pytest.MonkeyPatch):
    """数値に解釈できない env 値も `ConfigurationError` に包む（settings-contract §3）。

    以前の `float()` の `ValueError` を原因として抱えるので、既存の
    `except ValueError` で捕まる（`ConfigurationError` は `ValueError` の派生）。
    """
    monkeypatch.setenv("TR_RETRY_WAIT_SECONDS", "しばらく")

    with pytest.raises(ConfigurationError) as exc:
        Configuration.load(env_prefix="XTR")

    assert exc.value.field == "retry_wait_seconds"
    assert exc.value.value == "しばらく"
    assert exc.value.expected == "0 以上 60 以下の実数"
    assert "could not convert string to float" in exc.value.message


def test_load_rejects_a_non_boolean_env_value(monkeypatch: pytest.MonkeyPatch):
    """真偽値として解釈できない値は既定値に落とさず拒否する。"""
    monkeypatch.setenv("TR_SELF_REVIEW", "maybe")

    with pytest.raises(ConfigurationError) as exc:
        Configuration.load(env_prefix="XTR")

    assert exc.value.field == "self_review"
    assert exc.value.expected == "true または false"


def test_load_rejects_an_unknown_structured_method(monkeypatch: pytest.MonkeyPatch):
    """選択肢外の env 値も拒否する（実測どおり `json_schema` を通す。T004）。"""
    monkeypatch.setenv("TR_STRUCTURED_METHOD", "auto")

    with pytest.raises(ConfigurationError) as exc:
        Configuration.load(env_prefix="XTR")

    assert exc.value.field == "structured_method"
    assert exc.value.expected == "json_schema または function_calling"


@pytest.mark.parametrize(
    ("annotation", "bounds", "expected"),
    [
        pytest.param(int, {"ge": 1, "le": 16}, "1 以上 16 以下の整数", id="integer-range"),
        pytest.param(float, {"ge": 0.1, "le": 0.9}, "0.1 以上 0.9 以下の実数", id="float-range"),
        pytest.param(int, {"ge": 100}, "100 以上の整数", id="lower-bound-only"),
        pytest.param(float, {"le": 0.9}, "0.9 以下の実数", id="upper-bound-only"),
        pytest.param(int, {}, "整数", id="no-bound"),
        pytest.param(
            Literal["json_schema", "function_calling"],
            {},
            "json_schema または function_calling",
            id="literal",
        ),
    ],
)
def test_expected_text_follows_the_declaration(annotation, bounds, expected):
    """「期待」の文言は宣言から組み立てる（stderr の書式を固定する）。

    文言を手で書くと値域の宣言と食い違うため `_expected()` が 1 か所で作る。
    """
    field = Field(**bounds)
    field.annotation = annotation

    assert configuration_module._expected(field) == expected


def test_check_bounds_accepts_valid_settings():
    """値域内なら同じ値がそのまま残る（置換・丸めをしない）。"""
    config = Configuration(analysis_concurrency=4, retry_max=8, shrink_ratio=0.5)

    checked = configuration_module._check_bounds(config)

    assert (checked.analysis_concurrency, checked.retry_max, checked.shrink_ratio) == (4, 8, 0.5)


def test_check_bounds_preserves_model_fields_set():
    """再検証が `model_fields_set` を壊さない（T007 の実測に基づく実装位置）。

    `model_validate(model_dump())` は全項目を `model_fields_set` に載せてしまい、
    `providers/x.py:48` の「明示指定 > 環境変数」が壊れる。
    """
    config = Configuration.load(env_prefix="XTR").model_copy(update={"max_results": 7})
    before = set(config.model_fields_set)

    checked = configuration_module._check_bounds(config)

    assert checked is config
    assert set(checked.model_fields_set) == before


def test_check_bounds_rejects_a_bad_override():
    """`model_copy(update=...)` は検証しないため、再検証が上書きを弾く（実測 T007）。"""
    bad = Configuration().model_copy(update={"shrink_ratio": 1.5})

    with pytest.raises(ConfigurationError) as exc:
        configuration_module._check_bounds(bad)

    assert exc.value.field == "shrink_ratio"
    assert exc.value.value == 1.5
