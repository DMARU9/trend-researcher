# Contract: 実行時設定の一元化

**Feature**: `002-platform-extensibility-refactor` | **Date**: 2026-09-13

「設定がどこから来るか」を 1 箇所で説明できる状態を、検証可能な契約として固定する。

---

## SET-001: 実行時設定の型は 1 つ

| 契約 | 内容 |
|---|---|
| 唯一の型 | `trend_researcher.configuration.Configuration` |
| 削除する型 | `trend_researcher.config.Config` と `get_config()` |
| 同名項目の定義箇所 | 各項目につき 1 箇所（`Configuration` のフィールド定義） |
| 検証 | `src/` に `class Config` / `get_config` / `Config.load` が存在しないこと（grep）。`Configuration` のフィールド名が `Config` の旧フィールド名と重複しないこと |

**SC-003 の判定**: 「同名項目の定義箇所が 1 つ」= `Configuration` のフィールド定義の 1 箇所。

---

## SET-002: 環境変数・`.env` の解決場所

| 契約 | 内容 |
|---|---|
| 共通設定 | `configuration.py` の `resolve_env(name, *, default, env_prefix=None)` が `TR_{name}` → `{env_prefix}_{name}` → 既定 の順で解決する（既存 `Config._env()` の実装を移す） |
| 一括の入口 | `Configuration.load(env_prefix: str \| None = None)`（`.env` の読み込みもここで 1 回だけ行う） |
| `.env` | `python-dotenv` による読み込みを `Configuration.load()` の経路で 1 回行う |
| 優先順位 | 明示指定（`model_fields_set` に残る値） > `TR_*` > `{env_prefix}_*` > 既定値 |
| 空文字の扱い | 空文字の環境変数は「未設定」として扱う（現行 `Config._env()` と同じ） |
| 変数名 | `MODEL` / `MAX_RESULTS` / `SEARCH_POOL_SIZE` / `ACCOUNTS_DB` / `TRANSCRIPT_LANG` / `CACHE_DIR` / `MAX_RETRIES`（現行と同一。名前を変えない） |
| 検証 | `tests/unit/test_config.py` を `Configuration.load()` に対して実行し、既存の期待値を維持する |

---

## SET-003: プラットフォーム固有設定の解決

| 契約 | 内容 |
|---|---|
| 解決する場所 | 各 provider の内部（X は `providers/x.py` の `XSettings` / `XProvider.settings(configuration)`） |
| 環境変数 | `TR_{項目名}` → `{env_prefix}_{項目名}`（X: `TR_ACCOUNTS_DB` → `XTR_ACCOUNTS_DB` など）。実装は `configuration.resolve_env` の 1 か所 |
| フォールバック | 固有の変数が未設定なら、`TR_{項目名}`、次に `configuration` の値（既定を含む）を使う |
| 他プラットフォーム | その provider に存在しない設定は参照されない（例外にしない） |
| 禁止 | `configuration.py` / `config.py` / `nodes/**` に `XTR_` / `YTR_` のリテラルを書かない。provider は `self.env_prefix` を**引数として**使う |
| 検証 | 走査テスト（EXT-008）で `XTR_` / `YTR_` が `providers/` と `tools/` 以外に現れないこと |

---

## SET-004: ノードは設定を読まない

| 契約 | 内容 |
|---|---|
| 受け取り方 | `RunnableConfig` から `Configuration.from_runnable_config()` で取得した 1 つの値 |
| 禁止 | `os.getenv` / `load_dotenv` / `Config.load` / `open(".env")` をノード内で呼ばない |
| provider 固有設定 | provider の `settings()` の戻り値を通じて受け取る（環境変数は provider だけが読む） |
| 検証 | `tests/unit/test_platform_scan.py` の走査規則 (c) として実装する（**新しいテストファイルは増やさない**）。`nodes/**.py` を AST 走査し、`os.getenv` / `os.environ` / `load_dotenv` / `Config.load` の呼び出しが 0 件であることを確認する |

**SC-004 の判定**: 変更前は 2 ノード（`nodes/search.py:26`、`nodes/fetch.py:23`）が `Config.load()` を
呼んでいた。変更後は 0。

---

## SET-005: Studio の設定契約を変えない

| 契約 | 内容 |
|---|---|
| 対象 | `Configuration` の既存 **8 フィールド**（`platform` / `output_format` / `max_results` / `sort_by` / `transcript_language` / `use_trends` / `cache_dir` / `published_after`）のうち `use_trends` を除く 7 項目の**名前・型**（および**解決結果としての**既定値） |
| 禁止 | 既存フィールドの削除・改名・型変更（`use_trends` を除く。これは FR-009 の削除対象）。**新しいフィールドも追加しない**（Studio の入力欄を広げない） |
| 既定値の変更 | `platform` の既定値を `"x"` → `""` へ変更した（T017 / FR-002 / SC-002）。空文字は登録辞書の先頭（＝`x`）に解決されるため、**実行時の解決結果は変更前と同一**である。既定値の変更は、型にプラットフォーム名を埋め込まないために必須（`plan.md` の「解釈の記録」を参照）。他の 6 項目の既定値は変更していない |
| 注記 | `model` というフィールドは `Configuration` に**存在しない**（LLM のモデル名は `tools/llm.py` が環境変数から解決する） |
| 検証 | `tests/unit/test_configuration.py` の `DEFAULTS` から `use_trends` を除いた全キーが存在し、既定値が一致すること（`platform` は `""`。同ファイルの `test_platform_defaults_to_blank_so_the_registry_decides` が空文字の保持を固定する）。空文字が登録の先頭に解決されることは `tests/unit/test_providers.py::test_get_provider_resolves_blank_to_the_first_registration` が固定する |

**実測による確定（2026-09-14。T070）**: 初版の対象行は「7 項目の**名前・型・既定値**」と読める書き方
だったが、`platform` の既定値は T017 で `"x"` → `""` へ変更済みであり、字義どおりには充足しない。
契約の意図は「Studio の入力欄（フィールドの意味）と利用者が観測する解決結果を変えないこと」であり、
これは満たされている（`platform=""` は `get_provider()` の解決で `x` になる）。そこで対象行を
「名前・型（および解決結果としての既定値）」へ、変更内容を「既定値の変更」行へ明記した。

---

## SET-006: 設定値の優先順位（FR-015。変更しない）

```
1. CLI オプション（--platform / --output / --format / --max-results / --lang / --since / --cache-dir / --sort）
2. 環境変数（TR_* / {env_prefix}_*）
3. 指示本文の自然言語（parse_instruction.py の数値・期間の抽出）
4. LLM の解釈（parse_instruction.py のフォールバック）
```

| 契約 | 内容 |
|---|---|
| `max_results` の既定 | 5（`Configuration.max_results`） |
| `sort_by` の既定 | `"relevance"`（現行 `Configuration` の値。変更しない） |
| `transcript_language` の既定 | `"ja"` |
| `cache_dir` の既定 | `None`（解決時はリポジトリ直下の `cache/`） |
| 検証 | 既存の優先順位テストを `Configuration` の経路へ移して維持する（期待値は書き換えない） |

---

## SET-007: `Configuration.from_runnable_config` の挙動

| 契約 | 内容 |
|---|---|
| 入力 | `langgraph.config.RunnableConfig`（または `dict`） |
| 抽出 | `configurable` 以下の値。`None` は「未指定」として既定値を使う（現行の `if v is not None` を維持） |
| 追加 | `load()` を呼ぶかどうかは呼び出し側が決める（`from_runnable_config` は環境変数を読まない） |
| 検証 | `tests/unit/test_configuration.py` |

**設計上の注意**: `from_runnable_config` は状態に保存される値を返すため、`load()` の結果を混ぜる
場合も「明示指定 > 環境変数」の順を壊さないこと（SET-006）。

---

## SET-008: パス解決

| 契約 | 内容 |
|---|---|
| `cache_dir` の既定 | 未指定（`None` または空文字）のときは環境変数 `TR_CACHE_DIR` → `{env_prefix}_CACHE_DIR` を試し、いずれも無ければリポジトリ直下の `cache/` を使う。`configuration.py` に `XTR_` / `YTR_` の**リテラルは書かない**（接頭辞は provider から引数で受け取る。SET-003） |
| パス解決の実装 | `Configuration.load()` の内部で絶対パス化する（相対パスは実行時 CWD ではなく**リポジトリルート**を基準にする。現行 `_REPO_ROOT` と同じ） |
| 検証 | `tests/unit/test_config.py` の `_REPO_ROOT` 節を維持する |
| 変更 | `config.py` にパス解決のヘルパが残る場合、その関数は `Configuration.load()` から呼ばれる |

---

## SET-009: `openai_*` の扱い

| 契約 | 内容 |
|---|---|
| 契約の維持 | 環境変数 `OPENAI_API_KEY` / `OPENAI_BASE_URL`、`TR_MODEL` → `{env_prefix}_MODEL`（現行の直列と同じ順） |
| 解決場所 | `tools/llm.py`（境界）。`Configuration` に `model` フィールドは無く、追加もしない |
| 削除 | `Config.openai_api_key` / `Config.openai_base_url` / `Config.model`（`src/` からの参照が 0。実測。`Config` クラスごと削除する） |
| 検証 | `tests/unit/test_llm.py`（既存）が green であること |

---

## SET-010: 環境変数の読み取り回数と副作用

| 契約 | 内容 |
|---|---|
| 読み取り | `Configuration.load()` は毎回環境変数を読む（`lru_cache` を持たない） |
| 理由 | プロセス内共有が必要だったのは旧 `get_config()` の用途であり、ノードは実行時に注入された値を使う |
| テスト容易性 | `monkeypatch.setenv` によるテストが影響を受けない（キャッシュの `cache_clear()` が不要になる） |
| 検証 | `tests/unit/test_config.py` の `lru_cache` を固定していた節（`get_config is get_config` と `cache_clear()`）を削除し、同じ `TR_*` の解決を `Configuration.load()` に対して検証する節へ置き換える。**期待値（どの変数がどの値になるか）は維持**し、同一性（キャッシュ）の断言のみを落とす（根拠は REM-007） |

---

## SET-011: 未設定・空の扱い（Edge Case）

| 状況 | 契約 |
|---|---|
| `TR_MAX_RESULTS` が空文字 | 既定値 5 |
| `TR_MAX_RESULTS` が数値でない | **例外にする**（`ValueError`。既定値へ黙って落とさない） |
| `XTR_ACCOUNTS_DB` が未設定 | X の実行時は現行と同じ縮退（アカウント DB が見つからない場合のエラー経路を維持） |
| `platform` が空文字 | 登録辞書の先頭のプラットフォームとして解決 |
| 検証 | `tests/unit/test_config.py`（`test_non_integer_numeric_setting_raises`）/ `tests/unit/test_configuration.py` |

**実測による確定（2026-09-14。T070）**: 本契約の初版は「`TR_MAX_RESULTS` が数値でない → 既定値 5
（例外にしない。現行と同じ）」としていたが、**実測では `int()` が `ValueError: invalid literal for
int() with base 10: 'abc'` を投げる**（`TR_MAX_RESULTS=abc uv run python -c "from
trend_researcher.configuration import Configuration; Configuration.load()"`）。この挙動は変更前から
のもので、既存テスト `tests/unit/test_config.py` の `test_non_integer_numeric_setting_raises` が
固定している。T039 の指示「期待値は変更前と同一」に従い**例外を維持する**ため、契約の当該行を
実装に合わせて訂正した（`tasks.md` の「2. 基準値のずれ」に同じ判断を記録済み）。

---

## SET-012: 参照の更新（同一変更）

| 更新対象 | 内容 |
|---|---|
| `__init__.py` | `Config` の re-export を削除（`__all__` から除く） |
| `__main__.py` | `provider = get_provider(args.platform)` → `Configuration.load(env_prefix=provider.env_prefix)` で解決し、`configurable` としてグラフへ注入する |
| `nodes/search.py` / `nodes/fetch.py` | `Config.load(platform=...)` の呼び出しを `provider.settings(configuration)` の戻り値を返す provider メソッドの呼び出しへ置換 |
| `graph.py` | 変更なし（設定はノードが受け取る） |
| `README.md` | 環境変数の一覧を `TR_*` / `XTR_*` / `YTR_*` の 3 群で記載し、`--trends` を削除 |
