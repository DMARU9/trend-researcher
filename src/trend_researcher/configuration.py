"""LangGraph の config_schema に対応した設定クラス（実行時設定の唯一の入口）。"""

from __future__ import annotations

import os
from typing import Any, Literal, get_args, get_origin

from annotated_types import Ge, Le
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo

from trend_researcher.config import _REPO_ROOT, _resolve_path, load_env

#: `_expected()` が「期待する値域」の文言に使う型名
#: （キーを `object` にしているのは `FieldInfo.annotation`（`type | None`）で引くため）
_KIND_NAMES: dict[object, str] = {int: "整数", float: "実数"}


class ConfigurationError(ValueError):
    """設定の値域・選択肢の違反（data-model §1.2 / settings-contract §3）。

    `message` は `field` / `value` / `expected` から組み立てる。契約の書式
    （`設定が不正です: {field}={value}（期待: {expected}）`）を 3 つの属性から
    必ず得られるようにするため、呼び出し側に文を書かせない。

    `ValueError` を派生させるのは、env の型変換失敗（`int("たくさん")`）を
    `cause` に包んでも、既存の `except ValueError` が生きるようにするためである
    （settings-contract §3）。
    """

    def __init__(self, field: str, value: object, expected: str, *, cause: str = "") -> None:
        self.field = field
        self.value = value
        self.expected = expected
        self.message = f"設定が不正です: {field}={value}（期待: {expected}）"
        if cause:
            self.message = f"{self.message}。原因: {cause}"
        super().__init__(self.message)


def resolve_env(name: str, *, default: str, env_prefix: str | None = None) -> str:
    """環境変数を `TR_{name}` → `{env_prefix}_{name}` → `default` の順で解決する。

    空文字は「未設定」として次の候補へフォールバックする（旧 `Config._env()` と
    同じ規則）。`env_prefix` は provider が**引数として**渡す（`XTR` / `YTR` の
    リテラルはこのモジュールに書かない。SET-003）。
    """
    candidates = [f"TR_{name}"]
    if env_prefix:
        candidates.append(f"{env_prefix}_{name}")
    for key in candidates:
        value = os.getenv(key)
        if value:
            return value
    return default


def _bounds(field: FieldInfo) -> tuple[object, object]:
    """項目の `ge` / `le` の宣言値（未宣言は `None`）。"""
    ge = next((item.ge for item in field.metadata if isinstance(item, Ge)), None)
    le = next((item.le for item in field.metadata if isinstance(item, Le)), None)
    return ge, le


def _expected(field: FieldInfo) -> str:
    """「期待する値域」の文言を**宣言から**組み立てる（settings-contract §3）。

    文言を手で書くと値域の宣言と食い違うため、`Literal` と `ge` / `le` から作る。
    """
    if get_origin(field.annotation) is Literal:
        return " または ".join(str(item) for item in get_args(field.annotation))
    ge, le = _bounds(field)
    kind = _KIND_NAMES.get(field.annotation, "値")
    if ge is not None and le is not None:
        return f"{ge} 以上 {le} 以下の{kind}"
    if ge is not None:
        return f"{ge} 以上の{kind}"
    if le is not None:
        return f"{le} 以下の{kind}"
    return kind


def _declared_default(field: str) -> str:
    """宣言された既定値を、env のフォールバック用の文字列として取り出す。

    既定値の出所を `Configuration` の宣言 1 か所に保つ（同じ数を env 側にも
    書くと、片方だけ直したときに既定値が 2 つになる）。
    """
    return str(Configuration.model_fields[field].default)


def _int_env(field: str, name: str, env_prefix: str | None) -> int:
    """整数項目を env から解決する（解釈できない値は既定値に落とさず拒否する）。"""
    raw = resolve_env(name, default=_declared_default(field), env_prefix=env_prefix)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(
            field=field,
            value=raw,
            expected=_expected(Configuration.model_fields[field]),
            cause=str(exc),
        ) from exc


def _float_env(field: str, name: str, env_prefix: str | None) -> float:
    """実数項目を env から解決する（解釈できない値は既定値に落とさず拒否する）。"""
    raw = resolve_env(name, default=_declared_default(field), env_prefix=env_prefix)
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(
            field=field,
            value=raw,
            expected=_expected(Configuration.model_fields[field]),
            cause=str(exc),
        ) from exc


def _bool_env(field: str, name: str, env_prefix: str | None) -> bool:
    """真偽項目を env から解決する（`true` / `false` 系のみ受理する）。"""
    raw = resolve_env(name, default=_declared_default(field), env_prefix=env_prefix)
    lowered = raw.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    raise ConfigurationError(field=field, value=raw, expected="true または false")


def _setting(
    default: object,
    *,
    ui_type: str,
    label: str,
    description: str,
    ge: float | None = None,
    le: float | None = None,
) -> Any:
    """値域・説明・Studio の表示を 1 か所で宣言する（settings-contract §1）。

    `description` を JSON スキーマの説明と `x_oap_ui_config.desc` の両方に配るため、
    UI の説明が宣言と食い違わない。返り値を `Any` としているのは、`Field()` が
    `Any` を返すためである（注釈の型はクラス側が与える）。
    """
    return Field(
        default=default,
        ge=ge,
        le=le,
        description=description,
        json_schema_extra={
            "x_oap_ui_config": {"type": ui_type, "label": label, "desc": description}
        },
    )


class Configuration(BaseModel):
    """LangGraph Studio UI でパラメータ変更に対応する設定クラス。

    実行時設定の唯一の型（SET-001）。環境変数と `.env` の解決は `load()` に集約し、
    ノードは `from_runnable_config()` で受け取った値だけを使う（SET-004）。
    """

    platform: str = Field(
        default="", description="対象プラットフォーム（未指定時は既定のプラットフォーム）"
    )
    output_format: str | None = Field(default=None, description="出力形式（markdown/json）。未設定時は LLM が判断。")
    max_results: int = _setting(
        5,
        ge=1,
        le=100,
        ui_type="number",
        label="解析対象件数",
        description="解析する候補の上限（1〜100）。値域外は起動時に拒否される",
    )
    sort_by: str = Field(default="relevance", description="選定基準（relevance/likes）")
    transcript_language: str = Field(default="ja", description="字幕優先言語")
    cache_dir: str | None = Field(default=None, description="中間成果物の永続化先")
    published_after: str | None = Field(
        default=None,
        description="投稿日下限（ISO 8601）。CLI --since からのみ設定。",
    )

    # --- 追加 11 項目（data-model §1.1 / FR-024 / FR-060）--------------------
    # 値域は丸めない・既定値に置換しない。違反は `ConfigurationError`（起動時に拒否）。
    analysis_concurrency: int = _setting(
        2,
        ge=1,
        le=16,
        ui_type="number",
        label="同時実行数",
        description="個別解析の同時実行数",
    )
    retry_max: int = _setting(
        2,
        ge=0,
        le=10,
        ui_type="number",
        label="再試行回数",
        description="LLM 応答が契約を満たさないときの再試行回数（初回を除く）",
    )
    retry_wait_seconds: float = _setting(
        1.0,
        ge=0,
        le=60,
        ui_type="number",
        label="再試行の待機秒数",
        description="再試行の前に待つ秒数",
    )
    compression_threshold: int = _setting(
        20000,
        ge=1000,
        ui_type="number",
        label="圧縮のしきい値",
        description="素材がこの文字数を超えたら LLM で圧縮する",
    )
    compression_timeout_seconds: float = _setting(
        60.0,
        ge=1,
        le=300,
        ui_type="number",
        label="圧縮のタイムアウト",
        description="圧縮 1 回あたりのタイムアウト秒",
    )
    degrade_max_attempts: int = _setting(
        3,
        ge=1,
        le=10,
        ui_type="number",
        label="縮退の最大段数",
        description="上限超過のときに入力を縮小して再試行する最大段数",
    )
    shrink_ratio: float = _setting(
        0.9,
        ge=0.1,
        le=0.9,
        ui_type="number",
        label="縮退の入力長比率",
        description="縮退 1 段あたりの入力長の比率",
    )
    min_input_chars: int = _setting(
        1000,
        ge=100,
        ui_type="number",
        label="縮退の下限文字数",
        description="縮退を打ち切る入力長の下限",
    )
    self_review: bool = _setting(
        True,
        ui_type="boolean",
        label="検索クエリの自己点検",
        description="検索クエリを生成直後に点検するか",
    )
    include_intermediate: bool = _setting(
        False,
        ui_type="boolean",
        label="中間データの書き出し",
        description="圧縮・縮退・失敗の中間データを cache に書き出すか",
    )
    structured_method: Literal["json_schema", "function_calling"] = _setting(
        "function_calling",
        ui_type="text",
        label="構造化出力の方式",
        description="構造化出力の方式",
    )

    @classmethod
    def from_runnable_config(cls, config: RunnableConfig | None = None) -> Configuration:
        """RunnableConfig から設定値を取得して Configuration インスタンスを生成する。"""
        if config is None:
            return cls()
        configurable = config.get("configurable", {})
        return cls(**{k: v for k, v in configurable.items() if v is not None})

    @classmethod
    def load(cls, env_prefix: str | None = None) -> Configuration:
        """環境変数と `.env` から実行時設定を解決する（SET-002 / SET-008 / SET-010）。

        - 解決する項目は既存 3（`max_results` / `transcript_language` / `cache_dir`）と
          追加 11 の合計 14。それ以外は「Studio / CLI の明示指定のみ」で環境変数からは
          読まない（フィールドを増やさない。SET-005）
        - 相対パス（`cache_dir`）は**リポジトリ直下**基準で絶対パス化する
        - 値域・選択肢の違反と、数値に解釈できない値は `ConfigurationError`。
          丸めない・既定値に置換しない（FR-024 / SC-023）
        - 明示指定（CLI オプション等）は呼び出し側が `model_copy(update=...)` で
          後から与える。その値は `model_fields_set` に載るため「明示指定 > 環境変数」
          の順を保てる（SET-002 / SET-006）
        - `lru_cache` を持たない（毎回環境変数を読む。キャッシュの破棄が不要）
        """
        load_env()
        cache_dir = _resolve_path(
            resolve_env("CACHE_DIR", default=str(_REPO_ROOT / "cache"), env_prefix=env_prefix)
        )
        values: dict[str, object] = {
            "max_results": _int_env("max_results", "MAX_RESULTS", env_prefix),
            "transcript_language": resolve_env(
                "TRANSCRIPT_LANG",
                default=_declared_default("transcript_language"),
                env_prefix=env_prefix,
            ),
            "cache_dir": str(cache_dir),
            "analysis_concurrency": _int_env(
                "analysis_concurrency", "ANALYSIS_CONCURRENCY", env_prefix
            ),
            "retry_max": _int_env("retry_max", "RETRY_MAX", env_prefix),
            "retry_wait_seconds": _float_env("retry_wait_seconds", "RETRY_WAIT_SECONDS", env_prefix),
            "compression_threshold": _int_env(
                "compression_threshold", "COMPRESSION_THRESHOLD", env_prefix
            ),
            "compression_timeout_seconds": _float_env(
                "compression_timeout_seconds", "COMPRESSION_TIMEOUT_SECONDS", env_prefix
            ),
            "degrade_max_attempts": _int_env(
                "degrade_max_attempts", "DEGRADE_MAX_ATTEMPTS", env_prefix
            ),
            "shrink_ratio": _float_env("shrink_ratio", "SHRINK_RATIO", env_prefix),
            "min_input_chars": _int_env("min_input_chars", "MIN_INPUT_CHARS", env_prefix),
            "self_review": _bool_env("self_review", "SELF_REVIEW", env_prefix),
            "include_intermediate": _bool_env(
                "include_intermediate", "INCLUDE_INTERMEDIATE", env_prefix
            ),
            "structured_method": resolve_env(
                "STRUCTURED_METHOD",
                default=_declared_default("structured_method"),
                env_prefix=env_prefix,
            ),
        }
        # `cls(**values)` ではなく `model_copy` を使う: env 経由と CLI 上書きを
        # **同じ 1 つの検証経路**（`_check_bounds`）に通すため。型は `_*_env` が作る。
        return _check_bounds(cls().model_copy(update=values))


def _check_bounds(settings: Configuration) -> Configuration:
    """宣言した値域と選択肢を検査し、違反なら `ConfigurationError` を送出する。

    `model_copy(update=...)` は検証しない（実測 T007）。したがって env 解決の直後と
    CLI 上書きの直後にこれを呼ぶ。`model_validate(model_dump())` は使わない
    （全項目が `model_fields_set` に載り「明示指定 > 環境変数」が壊れる）。
    値域内の値はそのまま返す（丸めない・置換しない）。
    """
    for name, field in Configuration.model_fields.items():
        value = getattr(settings, name)
        if value is None:
            continue
        ge, le = _bounds(field)
        if (ge is not None and value < ge) or (le is not None and value > le):
            raise ConfigurationError(field=name, value=value, expected=_expected(field))
        if get_origin(field.annotation) is Literal:
            choices = get_args(field.annotation)
            if value not in choices:
                raise ConfigurationError(field=name, value=value, expected=_expected(field))
    return settings