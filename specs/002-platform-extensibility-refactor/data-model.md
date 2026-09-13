# Phase 1 Data Model: 新しいプラットフォームを追加しやすくするリファクタリング

**Feature**: `002-platform-extensibility-refactor` | **Date**: 2026-09-13

本機能はデータ構造を新設しない。ここで定義するのは「プラットフォームを追加するときに触る面」＝
**拡張点の型・設定の配置・描画の境界・走査の判定規則・削除と移行の一覧**である。

---

## 1. 拡張点（Provider 契約）

`providers/base.py` の `Provider` Protocol。**太字**が本機能で追加するメンバで、
移設元は research.md R-1。

| # | メンバ | 型 | X の値 | YouTube の値 | 備考 |
|---|---|---|---|---|---|
| 1 | `name` | `str` | `"x"` | `"youtube"` | 変更なし（登録キー） |
| 2 | `env_prefix` | **`str`** | `"XTR"` | `"YTR"` | 固有の環境変数の接頭辞。コアは値を解釈しない |
| 3 | `max_search_queries` | **`int \| None`** | `8` | `None` | `None` は無制限。`plan_search.py` は比較のみ行う |
| 4 | `content_noun` | **`str`** | `"ツイート"` | `"動画"` | レポート本文と CLI の完了メッセージで使う名詞 |
| 5 | `candidates_section_title` | **`str`** | `"## 選定ツイートリスト（上位 N 件）"` | `"## 選定動画リスト（関連度順上位 N 件）"` | 候補一覧の見出し |
| 6 | `selection_note(sort_by)` | **`(str) -> str`** | いいね数順の説明文 | 関連度順の説明文 | 選定基準の注記 1 行 |
| 7 | `search` | `(queries: list[str], max_results: int, published_after: datetime \| None, sort_by: str, config: Config) -> list[Candidate]` | `config` の型のみ `Configuration` へ | 同左 | 外部 I/O。FR-007 により**引数の意味と戻り値は変えない**（T043 / T044） |
| 8 | `fetch_contexts` | `(candidates: list[Candidate], config: Config) -> tuple[list[Context], list[str]]` | `config` の型のみ `Configuration` へ | 同左 | 外部 I/O。戻り値は `dict[str, str]` ではなく **`(contexts, notes)` のタプル**（実測 2026-09-13） |
| 9 | `candidate_table_header` | `() -> tuple[str, str]` | 変更なし | 変更なし | 表のヘッダ行（タイトル行, 区切り行）の **2 要素**を返す |
| 10 | `render_candidate_row` | `(c: Candidate) -> str` | 変更なし | 変更なし | 表の 1 行。**添字は受け取らない** |
| 11 | `render_block_title` | `(c: Candidate) -> str` | 変更なし | 変更なし | 詳細ブロックの見出し。**添字は受け取らない**（`### N.` の N は provider が `relevance_rank` などから作る） |
| 12 | `render_block_meta` | `(c: Candidate) -> list[str]` | 変更なし | 変更なし | 詳細ブロックの補足行。**`list[str]` を返す** |
| 13 | `common_theme_supporting_label` | `str` | `"該当ツイート"` | `"該当動画"` | 共通テーマの根拠表示 |
| 14 | `resort(candidates, sort_by)` | `(list[Candidate], str) -> list[Candidate]` | 変更なし | 変更なし | 並び替え |
| 15-18 | `*_prompt`（4 種） | `str`（property） | 変更なし | 変更なし | プロンプト本文は `prompts.py` に置く（R-11） |

**追加しないメンバ**（検討して却下したもの）: 「分析本文があるか」で分岐するための述語
（データの有無で決まるため provider の責務ではない）、プラットフォーム固有設定の解決メソッドの
共通化（X のみが持つため Protocol に置かない。4 章を参照）。

### 登録の契約

| 項目 | 契約 |
|---|---|
| 登録の場所 | `providers/__init__.py` の `_PROVIDERS: dict[str, type[Provider]]`（憲法 IV の記載どおり） |
| 追加の方法 | 辞書への 1 エントリ追加、または `register_provider(cls)` の呼び出し |
| エラー | 未登録名は `ValueError`。文言は `_PROVIDERS` のキーから生成（リテラルを含めない） |
| 既定の解決 | `Configuration.platform` が空文字のとき、`_PROVIDERS` の最初のキーを使う（`Literal` の既定 `"x"` を置き換える） |
| 一覧 API | `available_platforms() -> list[str]`（変更なし。CLI の `choices` が使う） |

---

## 2. 状態とモデルの変更

### `state.py`

| フィールド | 変更前 | 変更後 | 根拠 |
|---|---|---|---|
| `platform`（`AgentInputState`） | `NotRequired[Literal["x", "youtube"]]` | `NotRequired[str]` | FR-002 |
| `platform`（`AgentState`） | `Literal["x", "youtube"]` | `str` | FR-002 |
| `use_trends` | `bool` | （削除） | FR-009 |

その他のフィールド（`instruction` / `candidates` / `contexts` / `analyses` / `themes` /
`report` / `errors` / `counts`）は変更しない。**provider や設定のオブジェクトを状態に追加しない**
（憲法 III）。

### `models.py`

| 項目 | 変更 |
|---|---|
| `ResearchInstruction.platform` | `str = "x"` → `str = ""`（既定は登録の先頭で解決。FR-002） |
| `Candidate.platform` | `str = "x"` → `str = ""`（同上） |
| `ResearchInstruction.use_trends` | 削除（FR-009） |
| `OutputSpec.table_for` | 削除（FR-008 / REM-004） |
| 既存フィールドの型・意味 | 変更しない（FR-007） |
| 追加する任意フィールド | なし（本機能では追加しない。将来の追加は許容） |

### `configuration.py`（唯一の実行時設定）

既存 8 フィールドのうち 1 つを削除し、7 フィールドになる（**新しいフィールドは追加しない**。
Studio の入力スキーマを広げないため）。既定値は Studio の契約を維持する。

| フィールド | 変更前 | 変更後 | 環境変数（`Configuration.load`） | 備考 |
|---|---|---|---|---|
| `platform` | `str = "x"` | `str = ""` | — | 空文字は「登録済みプラットフォームの先頭」として解決（現行の `"x"` と同じ結果） |
| `output_format` | `str \| None = None` | 変更なし | — | 解決しない（Studio / CLI の明示指定のみ） |
| `max_results` | `int = 5` | 変更なし（既定 5） | `TR_MAX_RESULTS` → `{env_prefix}_MAX_RESULTS` | `Config.max_results` の重複解消 |
| `sort_by` | `str = "relevance"` | 変更なし（既定 `"relevance"`） | — | `Configuration` のみが持つ（`Config` には無い） |
| `transcript_language` | `str = "ja"` | 変更なし（既定 `"ja"`） | `TR_TRANSCRIPT_LANG` → `{env_prefix}_TRANSCRIPT_LANG` | YouTube が使う |
| `use_trends` | `bool = False` | **削除** | — | FR-009 / REM-003 |
| `cache_dir` | `str \| None = None` | 変更なし（型は `str \| None`）。解決時に絶対パスの文字列を入れる | `TR_CACHE_DIR` → `{env_prefix}_CACHE_DIR` | `Config.cache_dir`（`Path`）との重複解消 |
| `published_after` | `str \| None = None` | 変更なし | — | `Configuration` のみが持つ（`Config` には無い） |

- `Configuration.from_runnable_config(...)` は現行の `if v is not None` フィルタを維持する。
  渡されたキーは Pydantic v2 の `model_fields_set` に残るため、「明示指定」と「既定値」を区別できる。
- `Configuration.load(env_prefix: str | None = None) -> Configuration` を追加する。`.env` の読み込み
  もこの 1 経路で行う（実装は `config.load_env()`。T071 で `tools/llm.py` も同じ関数を通す）。
- `resolve_env(name, *, default, env_prefix=None) -> str` を `configuration.py` に置く（`TR_{name}` →
  `{env_prefix}_{name}` → 既定）。既存 `Config._env()` と同じ規則・同じ変数名
  （`MODEL` / `MAX_RESULTS` / `SEARCH_POOL_SIZE` / `ACCOUNTS_DB` / `TRANSCRIPT_LANG` / `CACHE_DIR` /
  `MAX_RETRIES`）を引き継ぐ。`env_prefix` は引数であり、`configuration.py` にプラットフォーム名は現れない。
- `Config` クラス・`get_config()`・`Config.load()` は削除する（SET-001 / REM-006 / REM-007）。
- 実測（2026-09-13）: `Configuration` と同名で重複していたのは 3 フィールド
  （`max_results` / `transcript_language` / `cache_dir`）＋ `Config.load()` の引数 `platform` である。
  残る `Config` のフィールド（`openai_api_key` / `openai_base_url` / `model` / `search_pool_size` /
  `accounts_db` / `max_retries`）は `Configuration` に同名が無いため、重複ではなく**責務の移動**である。

**環境変数の優先順位（FR-015 / FR-021 で不変）**

```
1. 明示指定（CLI オプション / RunnableConfig の値）
2. 環境変数（TR_* は全プラットフォーム共通、{env_prefix}_* はプラットフォーム固有）
3. 指示本文の自然言語（parse_instruction.py）
4. LLM の解釈（parse_instruction.py）
```

**プラットフォーム固有設定の置き場所（FR-003）**

| 設定 | 解決する場所 | 環境変数 | X 以外の実行での扱い |
|---|---|---|---|
| `accounts_db` | `providers/x.py` の `XSettings` | `TR_ACCOUNTS_DB` → `XTR_ACCOUNTS_DB` | 参照されない（その provider が持たない） |
| `search_pool_size` | `providers/x.py` の `XSettings` | `TR_SEARCH_POOL_SIZE` → `XTR_SEARCH_POOL_SIZE` | 同上 |
| `max_retries` | `providers/x.py` の `XSettings` | `TR_MAX_RETRIES` → `XTR_MAX_RETRIES` | 同上 |

`XSettings` は `providers/x.py` 内の `dataclass(frozen=True)` とし、`XProvider.settings(configuration)` から取得する。
`settings(configuration)` の戻り値には、共通値（`max_results` / `transcript_language` / `cache_dir`）も
**解決済みの形**で含める（`configuration` の明示指定 > `TR_*` > `{env_prefix}_*` > 既定）。
配線の向きは **1 つに固定する**: `nodes/search.py` / `nodes/fetch.py` は `provider.search(...)` /
`provider.fetch_contexts(...)` に `Configuration` を**渡すだけ**であり、`settings()` を呼ぶのは
**provider の内部**である（ノードが `provider.settings(...)` を直接呼ぶ形にしない。provider 固有設定の
解決範囲をノードへ漏らさないため）。
**ノードは `os.getenv` / `os.environ` / `load_dotenv` / `Config.load` を呼ばない**（FR-014 / SC-004）。

> 環境変数の解決の**実装**は `configuration.py` の `resolve_env` 1 か所であり、呼び出すのは
> 境界に位置する provider だけである（憲法 II）。ノードは解決の実装にも環境にも触れない。

### `tools/llm.py`

| 変更前 | 変更後 |
|---|---|
| `os.getenv("TR_MODEL", os.getenv("XTR_MODEL", os.getenv("YTR_MODEL", 既定)))` | `build_model(role, env_prefix: str \| None = None)` とし、`TR_MODEL` → `{env_prefix}_MODEL` → 既定（`env_prefix` が `None` のときは共通のみ） |

呼び出し側（`nodes/parse_instruction.py` / `nodes/plan_search.py` / `nodes/analyze_content.py` /
`nodes/extract_common.py`）は provider を受け取っているため、`provider.env_prefix` を渡す。

---

## 3. 描画のモデル（`rendering.py`）

| 関数 | 引数 | 戻り値 | 呼び出し元 |
|---|---|---|---|
| `render_markdown(report, provider)` | `ResearchReport`, `Provider` | `str` | CLI（stdout）/ `nodes/compile_report.py`（メッセージ本文） |
| `render_json(report)` | `ResearchReport` | `str` | CLI（`--output` 用）/ `cache.write_json` の入力。provider を取らない（署名は現行どおり） |
| `render_report(report, provider)` | `ResearchReport`, `Provider` | `str` | CLI / `__init__.py` の re-export。`format == "json"` なら `render_json(report)` へ委譲 |
| `_render_candidates_table(report, provider)` | 同上 | `list[str]` | 内部 |
| `_render_analysis_block(c, a, provider)` | 同上 + `AnalysisFinding \| None` | `list[str]` | 内部 |
| `_render_common_themes(report, provider)` | 同上 | `list[str]` | 内部 |

**不変条件**:
1. 描画は **渡された `provider` のみ**を使う。`get_provider()` を呼ばない（FR-017）。
   現行の `render_markdown` は引数を捨てて `get_provider(report.instruction.platform)` を
   呼び直しており（`nodes/compile_report.py:158`）、この不変条件は US4 で初めて満たされる。
2. `graph.py` は `rendering` を import しない（FR-016）。
3. 出力の文字列は分離前と 1 文字も変えない（FR-018 / SC-006。検証は golden 比較）。
   ただし **JSON には削除対象フィールドの差分が 1 つだけ生じる**: `ResearchReport` は
   `ResearchInstruction` を入れ子で持つため、`use_trends`（FR-009 で削除）と `table_for`
   （FR-008 で削除）が JSON から消える。これは **意図的な差分**であり、RND-003 のとおり
   当該 2 フィールドを除外して比較する（Markdown は byte 一致を維持する）。
4. 描画は外部 I/O を行わない（憲法 II）。`report` と `provider` だけで完結する。

**出力構造（不変）**

```
# <title_line>
（生成日時の行）
<selection_note の行>
<candidates_section_title>
| <provider.candidate_table_header>
| <provider.render_candidate_row(c, i)> ...
（各候補の詳細ブロック: render_block_title / render_block_meta / 本文）
<共通テーマ節: provider.common_theme_supporting_label を使う>
<出典・免責の行>
```

---

## 4. 走査の判定規則（SC-001 (2) / SC-002）

| 項目 | 定義 |
|---|---|
| 実装ファイル | `tests/unit/test_platform_scan.py` |
| 走査対象 | `src/trend_researcher/**/*.py` |
| 解析方法 | `ast.parse` による AST 走査。`ast.Constant`（`str`）と `ast.Name` / `ast.Attribute` を対象 |
| 検出規則 (a) | `str` 定数が**登録済みプラットフォーム名**と完全一致（`"x"` / `"youtube"`）。登録辞書から動的に取得する |
| 検出規則 (b) | `str` 定数または識別子が `^(XTR|YTR)_` に一致（登録済みの `env_prefix` から正規表現を組み立てる） |
| 除外 (1) | プラットフォーム実装: `providers/x.py`, `providers/youtube.py`, `providers/base.py` |
| 除外 (2) | プラットフォーム固有の外部境界: `tools/x_search.py`, `tools/youtube_search.py`, `tools/transcript.py` |
| 除外 (3) | プロンプト本文のみのデータ: `prompts.py` |
| 除外 (4) | docstring（`ast.get_docstring` で得られる行）とコメント |
| 許容リスト | `providers/__init__.py` の登録辞書の 2 行。**(ファイル名, 正規化した行内容)** の組で照合する |
| 判定 | 検出集合 == 許容リスト（= 2 件）。違反があれば、ファイル・行・内容を列挙して失敗する |
| 検出規則 (c) | 別のテスト関数 `test_nodes_do_not_read_environment` として、`nodes/**.py` に `os.getenv` / `os.environ` / `load_dotenv` / `Config.load` の呼び出しが **0 件**であることを確認する（設定読み込みの禁止。SET-004） |
| 検出規則 (d) | 別のテスト関数として、`help=` / `description=` のキーワード引数に渡された文字列が**登録済みプラットフォーム名を部分文字列として含まない**こと（**0 件**）を確認する。規則 (a) の完全一致では説明文（`"対象プラットフォーム（x=X/Twitter、youtube=YouTube）"`）を取り逃すため、SC-002 の「列挙」を説明文にも広げる。現行は `__main__.py` の `--platform` ヘルプ **1 件** → T022 で 0 件 |
| 検出規則 (e) | 別のテスト関数として、プラットフォームの**集合**を扱う型（`list[Provider]` / プラットフォーム名をキーとする `dict[str, ...]`）が **0 件**であることを確認する（FR-026。1 実行 = 1 プラットフォーム） |

**現行ツリーに対する検出（実測 2026-09-13）**: 規則 (a)+(b) で 16 行（許容 2 を含む）、
規則 (d) で 1 件（`__main__.py` のヘルプ）、規則 (e) で 0 件。
内訳は `state.py` 2 / `configuration.py` 1 / `models.py` 2 / `config.py` 2 / `tools/llm.py` 1 /
`providers/__init__.py` 2 / `nodes/compile_report.py` 3 / `nodes/plan_search.py` 2 / `__main__.py` 1。
**変更後は 2 行（`providers/__init__.py` のみ）**、規則 (d) は **0 件**、規則 (e) は **0 件**に
なることをテストで固定する。

---

## 5. 削除対象の一覧

| ID | 対象 | 参照（実測） | 同一変更で更新する参照 | 対応する要件 | 更新種別 |
|---|---|---|---|---|---|
| REM-001 | `cache.read_json`（`cache.py:28`） | 実行時 0 / テスト 5 件 | `tests/unit/test_cache.py` の当該節 | FR-008 / FR-010 | テスト削除 |
| REM-002 | `prompts.COMPILE_REPORT_PROMPT`（`prompts.py:175`） | 0 | なし | FR-008 | — |
| REM-003 | `--trends` 一式（CLI フラグ / `Configuration.use_trends` / `ResearchInstruction.use_trends` / `AgentState.use_trends` / `parse_instruction.py:191`） | 実行時 0（分岐・制御フローに寄与しない）。ただし `ResearchInstruction.use_trends` は **JSON に出力される**（`render_json` は `model_dump_json`。下欄参照） | `README.md:168`、argparse のヘルプ、`tests/unit/test_configuration.py`、`tests/unit/test_parse_instruction.py`、`tests/integration/test_cli_contract.py`、`specs/001-test-suite-hardening/contracts/cli-contract.md:128` | FR-009 | 文書 + テスト更新（**JSON の意図差分 1**） |
| REM-004 | `OutputSpec.table_for`（`models.py:25`） | 0。ただし `OutputSpec` 経由で **JSON に出力される**（`"table_for": ["common_points"]`。下欄参照） | `tests/unit/test_models.py`（該当があれば） | FR-008 | テスト更新（**JSON の意図差分 2**） |
| REM-005 | `tools/x_search.fetch_thread`（`x_search.py:165`） | 実行時 0 / テスト 11 件 | `tests/unit/test_x_search.py` の当該節（`fetch_threads` の節は維持） | FR-008 / FR-010 | テスト削除 |
| REM-006 | `Config`（`config.py`） | `src/` 9 ファイル | R-5 の表のとおり移設。`tests/unit/test_config.py`（307 行）を `Configuration.load` へ移行 | FR-013 | テスト移行 |
| REM-007 | `get_config()`（`@lru_cache`） | 実行時 0（テストは `cache_clear()` のみ） | `tests/integration/test_full_flow.py`、`tests/unit/test_config.py` | FR-013 | テスト更新 |
| REM-008 | `ProgressEmitter.TOTAL` の手書きと `emit` の番号引数 | — | `tests/unit/test_progress.py`、7 ノードすべての呼び出し | FR-012 | 呼び出し更新 |
| REM-009 | `nodes/compile_report.py` の整形関数群（約 120 行） | `graph.py:69` から参照 | `rendering.py` へ移設。`tests/unit/test_compile_report.py` の描画節を `test_rendering.py` へ移す | FR-016 | 移動 |

**更新してはならない参照**: `specs/001-test-suite-hardening/plan.md` / `tasks.md` / `research.md` /
`data-model.md` / `quickstart.md`（完了済み機能の履歴。書き換えると当時の判断の記録が失われる）。

---

## 6. テストの移行対象一覧

| テスト | 固定している内容 | 移行の内容 | 期待値の扱い |
|---|---|---|---|
| `tests/unit/test_config.py`（307 行） | `TR_*` > `XTR_*`/`YTR_*` > 既定、パス解決、`lru_cache` | 対象を `Configuration.load()` / `resolve_env(..., env_prefix=...)` に替える。`_REPO_ROOT` の解決は `config.py` に残る関数を検証 | **期待値は維持**（FR-019 の観測可能な契約）。`lru_cache` の節は削除する（`cache_clear()` の呼び出しと「同一インスタンスを返す」断言は SET-010 / REM-007 のとおり落とし、**値の解決結果の断言のみ**を `Configuration.load()` に対して維持する） |
| `tests/unit/test_configuration.py` | `DEFAULTS` 8 キー、`from_runnable_config` のフィルタ、「この層では platform を検証しない」 | `use_trends` を削除し、`load()` の解決規則の節を追加 | 内部構造（フィールド一覧）のため更新可（削除根拠に記録） |
| `tests/unit/test_progress.py` | 進捗行の書式、`TOTAL` | `emit(name, phase, detail)` の新シグネチャへ。`NODE_ORDER` との整合を追加 | 書式の断言は維持 |
| `tests/unit/test_cache.py` | `write_json` / `read_json` | `read_json` の節を削除 | 削除可（REM-001） |
| `tests/unit/test_x_search.py` | `fetch_thread` / `fetch_threads` / リトライ | `fetch_thread` の節を削除。X 固有設定の解決（`XSettings`）の節を追加 | 削除可（REM-005）。`fetch_threads` の節は維持 |
| `tests/unit/test_providers.py` | 登録・`get_provider` のエラー・`_StubProvider` | フック 5 つの契約（既定値・型）と `register_provider` の節を追加。`_PROVIDERS` の import は維持 | 追加中心 |
| `tests/unit/test_compile_report.py` | ノードの出力（メッセージ・`report` のキャッシュ） | 描画の断言は `test_rendering.py` へ移し、ノード側は「描画が呼ばれる」「`report` が状態に入る」に絞る | 観測可能な部分は維持 |
| `tests/integration/test_cli_contract.py` | 終了コード 0/1/2、stdout/stderr の分離、`--help` の語 | `--trends` の受理に関する節を削除。他の断言は維持 | **維持**（削除は REM-003 のみ） |
| `tests/integration/test_full_flow.py` | パイプラインの完走、7 ノード、進捗 7 行 | `Config` / `get_config` の参照を `Configuration` へ。進行の断言は維持 | 内部構造の参照のみ更新 |
| 新規 `tests/unit/test_platform_scan.py` | 走査（16 → 2 行） | — | 新規 |
| 新規 `tests/unit/test_platform_extension.py` | 試験用プラットフォームの完走（コア差分 0） | — | 新規 |
| 新規 `tests/unit/test_rendering.py` | golden 3 入力（X 完全形 / YouTube 完全形 / 欠落形）の byte 一致 | — | 新規 |

**削除根拠の記録（FR-019 / SC-008）**: 上表の「削除可」「更新可」とした各テストについて、
`removal-rationale.md` の REM-001〜REM-009 に「何を固定していたテストか」「なぜ対象になったか」を
記す。

**JSON 出力に生じる意図的な差分（SC-006 の適用範囲）**: `render_json` は
`report.model_dump_json(indent=2, exclude_none=True)` を返すため、`ResearchReport` →
`ResearchInstruction` → `OutputSpec` の入れ子で伝わる `use_trends`（REM-003）と `table_for`
（REM-004）が JSON から消える。これは FR-008 / FR-009 の削除に必然的に伴う**意図的な差分**であり、
RND-003 のとおり当該 2 キーについてのみ差分を許容する（Markdown は byte 一致を維持）。
**spec の SC-006 の文言は変更せず**、この例外を `removal-rationale.md` と golden 比較の手順に記録する。
