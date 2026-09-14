# Contract: 実行時設定の宣言・検証・解決

**Feature**: `003-pipeline-hardening-and-evaluation` | **Date**: 2026-09-14

**対応要件**: FR-024 / FR-025 / FR-054 / FR-059 / FR-060 / FR-069（`Configuration` に足さない）/
SC-009 / SC-023 / SC-034 / SC-021

**境界**: `src/trend_researcher/configuration.py`（型・値域・解決）と
`src/trend_researcher/__main__.py`（起動時の拒否と終了コード）。

## 1. 宣言の契約

| 項目 | 契約 |
|---|---|
| 宣言する内容 | 型 / 値域または選択肢 / 既定値 / 説明（日本語） |
| 型 | 既存の注釈（`int` / `float` / `bool` / `str` / `str \| None`）＋ 選択肢は `Literal[...]` |
| 値域 | `Field(ge=..., le=...)`。**丸めない・既定値に置換しない** |
| 説明 | `Field(description="...")`。日本語で 1 文 |
| UI 表示 | `Field(json_schema_extra={"x_oap_ui_config": {"type": ..., "label": ..., "desc": ...}})` |
| 型の源 | `Configuration`（唯一の実行時設定型。原則 III）。別の設定クラスを作らない |
| 禁止 | `os.getenv` の直接参照（`tools/llm.py` の `OPENAI_API_KEY` / `OPENAI_BASE_URL` を除く。既存の例外） |

**宣言する全項目**（既存 7 ＋ 追加 11）は [data-model.md §1.1](../data-model.md) の表を参照。
`x_oap_ui_config` の `type` の対応は次のとおり。

| Pydantic の型 | `x_oap_ui_config.type` |
|---|---|
| `bool` | `"boolean"` |
| `int` | `"number"` |
| `float` | `"number"` |
| `str` / `Literal[...]` | `"text"` |
| `OutputFormat \| None` | `"select"`（`options` に `markdown` / `json`） |

## 2. 値域の契約

値域は [research.md R-20](../research.md) の表で確定する。
**既存テストが実際に使う値を必ず含む**（FR-035）。特に次の 3 点は変更できない。

| 制約 | 理由 |
|---|---|
| `max_results` は 1 以上（0 を弾く）が、既存テストが使う 1 / 2 / 3 / 5 / 10 を通す | `Configuration(max_results=...)` を直接使うテストがある |
| `analysis_concurrency` の既定は 2 | `tests/unit/test_analyze_content.py:421` が `max_in_flight == 2` を固定 |
| `sort_by` は `relevance` / `recency` の 2 択 | `providers/base.py:selection_note` と `__main__.py` の既存検証が 2 値 |

## 3. 拒否の契約（起動時）

| 項目 | 契約 |
|---|---|
| いつ | ノードを 1 つも実行する**前**（LLM・検索・ファイル読み書きの前） |
| どこで | `__main__.py` の `Configuration.load(...)` と CLI 上書きの適用後 |
| 例外 | `ConfigurationError`（`field` / `value` / `expected` / `message`） |
| 出力 | stderr に `設定が不正です: {field}={value}（期待: {expected}）` |
| 終了コード | **2**（引数エラーと同じ扱い。FR-024 / SC-023） |
| 禁止 | 丸め（`0` → `1`）、既定値への置換、警告のみで続行、例外の握りつぶし |
| `Configuration.load` の env 経由 | 値域外は `ConfigurationError`（`ValueError` を包む）。`int("abc")` の `ValueError` も包む |
| `from_runnable_config` 経由 | Pydantic の `ValidationError` → ノード実行時の例外 → `__main__.py` が捕捉して exit 1（起動時ではないため） |

**実装上の注意（実測に基づく）**: Pydantic v2 の `model_copy(update=...)` は
**検証を行わない**（実測）。したがって CLI 上書きの後には明示的な検証が必須である。
検証は `model_fields_set` を壊さない方法で行う（`Configuration.model_validate(model_dump())`
を**そのまま使えるかは実測で確定する**。`model_fields_set` が全項目になる場合、
`providers/x.py:48` と 3 つの既存テストが依存する優先順位が壊れるため、
各フィールドを検査する純粋関数（`_check_bounds(settings)`）を使う）。
→ research R-10 / 未解決事項表。

## 4. 解決の契約（単一経路）

```
.env / 環境変数
      │  (1) Configuration.load(env_prefix)
      ▼
Configuration（値域違反は ConfigurationError）
      │  (2) CLI 上書き（model_copy）＋ 明示の再検証
      ▼
Configuration（確定）
      │  (3) runnable_config = {"configurable": configuration.model_dump()}
      ▼
LangGraph 実行
      │  (4) Configuration.from_runnable_config(config)  ← ノード側の唯一の入口
      ▼
ノード
```

| # | 契約 |
|---|---|
| 単一性 | ノードは `from_runnable_config` 以外で設定を読まない。`os.environ` を直接読まない |
| 優先順位 | 明示指定（CLI / Studio の `configurable`）> 環境変数 > 既定値。`model_fields_set` で表現する |
| 全ノード共通 | 5 ノード（LLM を使う 4 ＋ `compile_report`）が同じ経路を使う |
| Studio | `langgraph.json` の `config_schema` が `Configuration` を指す（変更なし）。値域と説明が UI に出る（FR-060） |
| 評価の実走 | 同じ経路（`{"configurable": ...}` を `ainvoke` に渡す）。**別の解決経路を作らない**（FR-025） |

**要件対応**: FR-025（設定は 1 つの解決経路）/ FR-060（Studio から変更可・単一経路維持）/
SC-009（全設定が実行時に変更可能・不正値は起動時に拒否）。

## 5. `Configuration` に足してはならないもの

| 禁止 | 理由 |
|---|---|
| `eval_model` / `judge_model` | FR-069 が `Configuration` への項目追加を MUST NOT とする。`resolve_env("EVAL_MODEL", default=...)` で解決する |
| 評価専用の切り替え（`eval_self_review` 等） | FR-054 が「評価専用の切替手段を別に設けない」と定める（`self_review` を共有する） |
| プラットフォーム名の分岐用の項目 | 原則 IV（provider が宣言する） |

## 6. 凍結する契約（変更してはならない）

| # | 契約 | 実測による固定箇所 |
|---|---|---|
| 1 | `Configuration` の既存 7 フィールドの名前・型・既定値 | `tests/unit/test_config.py`（357 行）/ `tests/unit/test_configuration.py`（305 行） |
| 2 | `model_fields_set` の意味（明示指定 > env） | `providers/x.py:48`、`tests/unit/test_config.py:266`、`tests/unit/test_configuration.py:281` |
| 3 | `resolve_env` の解決順（`TR_{name}` → `{env_prefix}_{name}` → default。空文字は未設定扱い） | `tests/unit/test_configuration.py` |
| 4 | `cache_dir` のリポジトリ相対の解決（`_resolve_path`） | `tests/unit/test_configuration.py` |
| 5 | `from_runnable_config(None)` → `cls()`、`configurable` の `None` を除外 | `tests/unit/test_configuration.py` |
| 6 | 環境変数の名前の族（`TR_*` / `XTR_*` / `YTR_*`） | `providers/x.py` / `providers/youtube.py` / README |

## 7. 検証（この契約を固定するテスト）

| テスト | 何を固定するか |
|---|---|
| `tests/unit/test_configuration.py`（拡張） | 全項目の値域の宣言（`model_fields` を走査して `ge` / `le` / `Literal` の存在を確認）、`ConfigurationError` のメッセージ、`model_fields_set` の維持 |
| `tests/unit/test_config.py`（拡張） | env 経由の値域違反、`TR_*` と `{env_prefix}_*` の解決 |
| `tests/integration/test_cli_contract.py`（拡張） | 値域外の CLI 引数で exit 2 と stderr の文言、**LLM を 1 回も呼ばない**こと |
| `tests/unit/test_platform_scan.py`（不変） | コアに新しい `platform == "..."` が無いこと（規則 (a)+(b)） |
| `tests/unit/test_config_scan.py`（新規） | ノードと `tools/` が `os.environ` を直接読んでいないこと（`tools/llm.py` の 2 つを除く） |

**変異探針**:

| 変異 | 期待 |
|---|---|
| `max_results` の `ge` を削る | 値域のテストが落ちる |
| `__main__.py` の再検証を削る | exit 2 のテストが落ちる（exit 0 になる） |
| `ConfigurationError` を `ValueError` に変える | 捕捉の分岐テストが落ちる |
| `x_oap_ui_config` を 1 項目から削る | 宣言の走査テストが落ちる |
| `from_runnable_config` の経路を 1 ノードだけ変える | 走査テストが落ちる |
