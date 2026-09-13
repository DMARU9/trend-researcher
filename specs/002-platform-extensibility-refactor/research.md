# Phase 0 Research: 新しいプラットフォームを追加しやすくするリファクタリング

**Feature**: `002-platform-extensibility-refactor` | **Date**: 2026-09-13

Technical Context に `NEEDS CLARIFICATION` は 0 件（spec の Clarifications 5 件で解消済み）。
本章は、設計に必要な判断を **Decision / Rationale / Alternatives considered** の形で確定する。
すべての実測は 2026-09-13 に本リポジトリで実行した。

---

## R-1: プラットフォーム差を表す拡張点（provider のフック）

**Decision**: `Provider` Protocol に次の 5 つを追加し、コアに残っている差をすべてここへ移す。

| 追加するフック | 型 | X の値 | YouTube の値 | 移設元 |
|---|---|---|---|---|
| `env_prefix` | `str` | `"XTR"` | `"YTR"` | `config.py:71` |
| `max_search_queries` | `int \| None` | `8` | `None`（制限なし） | `nodes/plan_search.py:76` |
| `content_noun` | `str` | `"ツイート"` | `"動画"` | `nodes/compile_report.py:45`、`__main__.py:148` |
| `candidates_section_title` | `str` | `"## 選定ツイートリスト（上位 N 件）"` | `"## 選定動画リスト（関連度順上位 N 件）"` | `nodes/compile_report.py:85` |
| `selection_note(sort_by)` | `str` | いいね数の多い順／少ない順 | 関連度順 | `nodes/compile_report.py:37` |

既存のフック（`search` / `fetch_contexts` / `candidate_table_header` / `render_candidate_row` /
`render_block_title` / `render_block_meta` / `common_theme_supporting_label` / 4 つのプロンプト /
`resort`）はそのまま維持する。**7 つ目のフックを足さない**（YAGNI。残る差は
`_render_analysis_block` の「本文があるか」だけで、これはプラットフォーム名の分岐ではなく
データの有無による分岐である）。

**Rationale**: 追加するフックはすべて「現在コアにハードコードされている差」の移設先であり、
新機能ではない。`content_noun` は 2 か所（ノードと CLI）で同じ文字列を別々に持っているため、
1 つのプロパティに統合すると同時に重複も消える。

**Alternatives considered**:
- `selection_note` ではなく「ラベルだけ」を返す案 → 文の組み立てがコアに残り、`notes` の文言が
  プラットフォームごとに変えられない。FR-004 は「出力文言」を provider 側と定めている。
- レンダリング全体を provider のメソッドにする案（`provider.render_report(report)`）→ 表・見出し・
  出典・備考という共通構造まで provider が持つことになり、4 章の分離（rendering.py）と衝突する。
  差は「行・見出し・注記」の単位に留めるのが正しい粒度。

---

## R-2: プラットフォームの登録方式

**Decision**: 登録辞書は `providers/__init__.py` の `_PROVIDERS` に置いたままとする（移動しない）。
追加の API として `register_provider(cls)` を設け、辞書への追加を 1 箇所で行えるようにする。
エラー文言は辞書から生成し、プラットフォーム名のリテラルを含めない。

```python
_PROVIDERS: dict[str, type[Provider]] = {
    "x": XProvider,
    "youtube": YouTubeProvider,
}
```

**Rationale**: 走査テストの目標は「許容リスト 2 行のみ」であり、許容リストは登録の定義そのものである。
`providers/registry.py` へ移すと、憲法 IV の「`providers/__init__.py` への登録」という記載と、
走査テストの許容リスト（ファイル名）が二重に動く。移動の利得はなく、churn だけが増える。

**FR-005 の解釈**: 「プラットフォームの登録は、既存の登録定義の書き換えを伴わない追加で完了 MUST」を
「**既存のエントリを書き換えず、登録の構造を変更せずにエントリを 1 つ追加する**」と読む（FR-001 が
「実装＋登録＋単体テストの追加」を要求していること、SC-002 が「登録の定義 2 箇所は拡張点として許容」と
定めていること、の両方と整合する唯一の読み方）。エントリの追加は `dict` への 1 行追加または
`register_provider()` の呼び出しであり、既存行・既存ロジック・コアのいずれも書き換えない。

**Alternatives considered**:
- `pkgutil` による自動探索（ファイルを置くだけで登録）→ 登録箇所が 0 になり、SC-002 の
  「2 箇所（登録の定義のみ）」と食い違う。また探索の失敗が「静かに無効化される」欠陥クラスを生む。
- `importlib.metadata` のエントリポイント検出 → spec の Assumptions が「導入しない（YAGNI）」と明記。

---

## R-3: 走査テストの判定規則とその較正

**Decision**: 走査テストは **AST を用いた行単位の検出器** とし、次の規則で判定する。

| 項目 | 内容 |
|---|---|
| 走査範囲 | `src/trend_researcher/**/*.py` |
| 除外 | `providers/x.py`・`providers/youtube.py`・`providers/base.py`（プラットフォーム実装＝拡張点の内側）、`tools/x_search.py`・`tools/youtube_search.py`・`tools/transcript.py`（プラットフォーム固有の外部境界）、`prompts.py`（本文のみのデータ） |
| 検出 | (a) 文字列リテラルが登録済みプラットフォーム名（`"x"` / `"youtube"`）と一致する定数、(b) 識別子または文字列リテラルが登録済み env プレフィックス `^(XTR|YTR)_` に一致するもの。**docstring の行は除外**する |
| 許容リスト | `providers/__init__.py` の登録辞書の 2 行。**行番号ではなく（ファイル名・正規化した行内容）の組**で照合する |
| 判定 | 検出結果の集合が許容リストと一致すること（= 2 件） |

**実測（2026-09-13、検出器を現行ツリーに対して実行）**: **16 行**。内訳は
`state.py` 2 / `configuration.py` 1 / `models.py` 2 / `config.py` 2 / `tools/llm.py` 1 /
`providers/__init__.py` 2（許容） / `nodes/compile_report.py` 3 / `nodes/plan_search.py` 2 /
`__main__.py` 1。目標は **2 行**（許容リストのみ）。

**較正で確かめた 2 点**:
1. `^(XTR|YTR)_` の境界が必要。部分一致にすると `NODE_EXTRACT_COMMON`（`EXTRA` の中に `XTR` が
   現れる）を誤検出し、`progress.py` の 2 行が偽陽性になる（実測で確認）。
2. プラットフォーム固有の `tools/` モジュールを除外する必要がある。除外しないと
   `tools/x_search.py:62` の `platform="x"` と `tools/youtube_search.py:30` の `platform="youtube"` を
   拾って 18 行になる。spec の基準値 15 も `tools/` を数えていない。

**基準値の差（15 vs 16）**: spec の 15 は**文単位**の集計で、`config.py:57` の引数既定値
（`Config.load(platform: str = "x")`）が spec の内訳（既定値 3 = `configuration.py` 1 + `models.py` 2）に
数えられていない。差は 1 件で、残り 15 は完全に対応する。走査テストは**終状態（2 件）**を判定し、
spec の数値は変更しない（差は `plan.md` の「基準値のずれ」節と implementation notes に記録する）。

**Rationale**: 「箇所」を行で数えるのは、許容リストを行番号ではなく (ファイル, 行内容) の組にできるため
保守的である（行がずれても許容リストが壊れない）。AST を使うのは、コメント・docstring・文字列中の
部分一致を確実に排除するため。`state.py` の `Literal["x", "youtube"]` は 1 行で 2 つの名前を含むが、
1 行 = 1 箇所として数える（spec の「状態定義 2」は 2 行を指しており一致する）。

**Alternatives considered**:
- 正規表現のみで行を走査 → コメント・docstring を除外できず、`state.py` の docstring（`default="x"`）を
  誤検出する。
- 許容リストを行番号で持つ → 実装中に必ずずれる（001 の `Verification` 節で繰り返し発生した欠陥クラス）。

---

## R-4: 設定の一元化（FR-003 と FR-013 の整合）

**Decision**: 実行時設定は **`Configuration` の 1 型だけ**とする。

- `Configuration` = LangGraph Studio の設定入力の型（既存 8 フィールドの契約は変更しない。`use_trends` のみ削除）+ 共通の実行時設定。
- 環境変数・`.env` の**解決の実装**は `configuration.py` の 1 か所に集約する（次の 2 つ）。
  - `Configuration.load(env_prefix: str | None = None) -> Configuration`: 解決済みの設定を返す一括の入口。
    `.env` の読み込み（`load_dotenv`）もここで 1 回だけ行う。
  - `resolve_env(name, *, default, env_prefix=None) -> str`: `TR_{name}` → `{env_prefix}_{name}` → 既定 の
    順で解決する汎用のヘルパ。`env_prefix` は**引数**であり、`configuration.py` にプラットフォーム名は現れない。
- **プラットフォーム固有**の値（X の `accounts_db` / `search_pool_size` / `max_retries`）は、
  provider が `resolve_env(..., env_prefix=self.env_prefix)` で解決する（`providers/` は外部 I/O の境界。憲法 II）。
- **解決を呼び出すのは「消費する側」だけ**とする。CLI は `get_provider(platform).env_prefix` を使って
  解決済みの `Configuration` を組み立て、`RunnableConfig` 経由でグラフへ注入する。ノードは
  `os.getenv` / `load_dotenv` / `Config.load` を呼ばず、解決済みの値（または `provider.settings(configuration)` の戻り値）を使う。
  Studio のように CLI を経由しない実行では、設定値を持つ側である provider が `provider.settings(configuration)` の
  中で未指定項目を解決する（`configuration` の明示指定は常に優先する）。
- **明示指定と既定値の区別**は Pydantic v2 の `model_fields_set`（コンストラクタで渡されたキーの集合）で行う。
  `from_runnable_config` は現行の `if v is not None` フィルタを維持し、渡されたキーは `model_fields_set` に残る。

**Rationale**: FR-013（環境変数の解決を唯一の型の読み込み処理へ集約 MUST）と FR-003（設定の解決に
プラットフォーム名の条件分岐を書かず、固有設定はプラットフォーム自身が解決 MUST）は、対象が違う
（共通設定と固有設定）ため両立できる。両方を `Configuration.load()` に寄せると、設定解決の側に
「どのプレフィックスを読むか」を決めるプラットフォーム名の分岐が必要になり、FR-003 と SC-002 に
違反する。したがって「同じ型の読み込み処理」は **共通設定の 1 経路**を指すと解釈する
（`Config` と `Configuration` のように 2 つの型が別々の読み込み経路を持つ状態を解消する、が趣旨）。

**実測に基づく必要性**（2026-09-13、両クラスのフィールドを直接読んで確認）: 同名で重複している
項目は **3 つ**（`max_results` / `transcript_language` / `cache_dir`）である。`platform` は
`Configuration` のフィールドであると同時に `Config.load()` の**引数**として現れる（計 4 箇所の重複）。
それ以外は片方にしかない（`Config`: `openai_api_key` / `openai_base_url` / `model` /
`search_pool_size` / `accounts_db` / `max_retries`、`Configuration`: `output_format` / `sort_by` /
`use_trends` / `published_after`）。同じ名前が 2 つの型に現れる状態は「どちらが正か」を都度調べさせる。

> **spec の基準値との差**: spec.md の現状分析は「7 項目が重複」と記すが、実測は **3 フィールド**
> （＋引数としての `platform`）である。SC-003 の判定は「同名項目の定義箇所が 1 つになる」という
> **終状態**で行うため、この差は合否に影響しない。差は `plan.md` の「基準値のずれ」に記録する。
> なお `Config.load()` は既定値まで含めて 9 フィールドを定義し、重複の実体は
> 「同じ値を 2 つの型が別々の既定値・別々の解決経路で持つ」ことにある（`cache_dir` は
> `Config` では解決済みの `Path`、`Configuration` では `str | None = None`）。

**Alternatives considered**:
- `Configuration` に `Config` のインスタンスを持たせる → `RunnableConfig` に渡す値が
  シリアライズ不能なオブジェクトを含み、Studio の入力スキーマが壊れる。憲法 III は provider /
  Config などのランタイムオブジェクトを State に持たせることを禁じており、同種の理由で避ける。
- provider に `Configuration` を渡さず、必要な値をすべて引数で渡す → 引数が増え、`transcript_language`
  のような Studio 由来の値の経路が分断される。`Configuration` を 1 つ渡す現行の形を維持する。

---

## R-5: 旧 `Config` フィールドの再配置

**Decision**: `Config` クラスと `get_config()`（`lru_cache`）を削除し、フィールドを次のように移す。

| 旧 `Config` フィールド | 移設先 | 環境変数 | 根拠（実測） |
|---|---|---|---|
| `max_results` | `Configuration.max_results`（**既存**。既定 5 を維持） | `TR_MAX_RESULTS` → `{env_prefix}_MAX_RESULTS` | 同名重複の解消。解決は `resolve_env` に一本化 |
| `transcript_language` | `Configuration.transcript_language`（**既存**。既定 `"ja"` を維持） | `TR_TRANSCRIPT_LANG` → `{env_prefix}_TRANSCRIPT_LANG` | 同上。YouTube が使う |
| `cache_dir` | `Configuration.cache_dir`（**既存**。`str \| None = None` を維持し、解決時に絶対パス文字列を入れる） | `TR_CACHE_DIR` → `{env_prefix}_CACHE_DIR` | 同上 |
| （`platform`） | `Configuration.platform`（**既存**。既定を `"x"` → `""` に変更し、空文字は登録の先頭として解決） | — | 既定値のリテラルを `configuration.py` から除く（FR-002） |
| `openai_api_key` / `openai_base_url` / `model` | `tools/llm.py`（境界）が引き続き解決する | `OPENAI_*` / `TR_MODEL` → `{env_prefix}_MODEL` | 実測: `src/` から `Config.openai_api_key`・`Config.openai_base_url`・`Config.model` を読む箇所は 0（`llm.py` が環境変数を直接読む）。`Configuration` に `model` フィールドは**存在しない**ため移設先も存在しない |
| `search_pool_size` | `XProvider` が解決（`XSettings`） | `TR_SEARCH_POOL_SIZE` → `XTR_SEARCH_POOL_SIZE` | X 固有。`providers/x.py` のみが読む |
| `accounts_db` | `XProvider` が解決（`XSettings`） | `TR_ACCOUNTS_DB` → `XTR_ACCOUNTS_DB` | X 固有（認証情報の場所。FR-003 の例示そのもの） |
| `max_retries` | `XProvider` が解決（`XSettings`） | `TR_MAX_RETRIES` → `XTR_MAX_RETRIES` | X 固有（`tools/x_search.py` のリトライ） |

**Rationale**: 「同名項目を複数の型で定義しない」を満たすには、重複しているフィールドを
`Configuration` の 1 定義にする（`max_results` / `transcript_language` / `cache_dir` は既に存在するため
**移設ではなく解決経路の統合**になる）。重複していない項目はそれぞれの責務へ戻す（X 固有 3 → provider、
LLM 3 → `tools/llm.py`）。`get_config()` は `Config` のプロセス内共有のためだけに存在し、`src/` からの
参照が 0（テストの `cache_clear()` のみ）なので、型の削除と同時に削除する（REM-007）。

**Alternatives considered**:
- `Config` を残して `Configuration` を削除する → ユーザー回答（clarify Q4）が「現行の `Configuration` を
  残す（Studio の設定契約を維持する）」と確定しているため不可。
- X 固有設定を `Configuration` の任意フィールドにする → Studio の入力欄が増え、「Studio の設定契約を
  変更しない MUST」（FR-013）に抵触する。FR-007 が許容するのは**共通モデル**への任意フィールド追加で
  あり、設定型の契約はこれと別である。
- 環境変数の解決を provider ではなくノードで行う（現行の `Config.load(platform=...)` の置き換えとして
  `resolve_env(..., env_prefix=provider.env_prefix)` を各ノードで呼ぶ）→ 環境変数を読む場所が
  `nodes/` に広がり、SC-004（ノードからの直接アクセス 0）と FR-014（注入された 1 経路）の意図に反する。

---

## R-6: 描画の分離（FR-016 / FR-017 の解釈）

**Decision**: 整形処理（`_render_candidates_table` / `_render_analysis_block` / `_render_common_themes` /
`render_markdown` / `render_json`、約 120 行）を `nodes/compile_report.py` から新モジュール
`rendering.py` へ移す。`render_report(report, provider)` を `rendering.py` に置き、
`graph.py` からは描画の参照を完全に削除する（`graph.py` は `build_graph()` と `_route_after_search` だけ）。

- `nodes/compile_report.py` は `rendering.render_markdown(report, provider)` を呼ぶ
  （チャット表示用メッセージの本文に必要）。**graph は描画を参照しない**。
- `render_markdown` は**引数の provider を使う**。内部で `get_provider(report.instruction.platform)`
  を呼び直さない（現行 `compile_report.py:158` の不具合の解消。FR-017）。
- `__main__.py` は `rendering.render_report(report, provider)` を呼ぶ。provider は CLI が
  `--platform` から明示的に解決する（描画の内部で解決し直すのではなく、呼び出し側が渡す）。

**Rationale**: FR-016 の MUST NOT は「パイプラインの骨格が描画機能を参照すること」に掛かっている。
ノードが描画関数を呼ぶこと自体は、整形がノードの進行から独立して検証できる（ノードを実行せずに
`rendering.py` を直接テストできる）ため、Acceptance Scenario 2-1（「パイプラインのノード実行を伴わずに
検証できる」）を満たす。`graph.py` の参照を外すことで、骨格を読み替えるだけで描画の変更リスクが
読めるようになる（US4 の Why）。

**Alternatives considered**:
- `rendering/` パッケージに分割（`markdown.py` / `json.py`）→ 120 行に対して過剰（YAGNI）。
- 描画を provider へ移す → R-1 と同じ理由で却下。
- ノードが Markdown を生成しない（メッセージに raw JSON を入れる）→ 観測可能な出力が変わる（FR-018 / SC-006）。

---

## R-7: 進捗の単一化（FR-012）

**Decision**: `ProgressEmitter.emit(node_name, phase, detail="")` とし、表示番号と総数を
`NODE_ORDER` から導出する。

```python
class ProgressEmitter:
    def emit(self, node_name: str, phase: str, detail: str = "") -> None:
        index = NODE_ORDER.index(node_name) + 1
        total = len(NODE_ORDER)
        line = f"[{index}/{total}] {node_name} ... {phase}{suffix}"
```

- `ProgressEmitter.TOTAL = 7` の手書きを廃止し、`make_emitter()` は `len(NODE_ORDER)` を使う。
- `total` はインスタンス変数のまま残し、`total=...` の上書き（テスト用）の余地を保つ。
- 進捗行の**文字列は 1 文字も変えない**（`[i/total] name ... phase（detail）`）。

**Rationale**: 「手書きの番号 1〜7」と「`TOTAL = 7`」の 2 つが同じ事実を別々に持っている状態を解消する
（FR-012）。ノード名は既に定数（`NODE_SEARCH` 等）で渡しているので、呼び出し側の変更は
「番号引数を落とす」だけであり、差分が小さい。

**Alternatives considered**:
- グラフのノード一覧から総数を導出（`build_graph()` のノード数）→ グラフ構築（LangGraph の
  `StateGraph`）を進捗表示が参照することになり、依存の向きが逆になる。`NODE_ORDER` は既に
  「順序の固定定義」として存在するため、その単一の定義を使うのが素直。
- ノードに番号を持たせたまま `TOTAL` だけを導出 → 手書きの番号が残り、FR-012 を満たさない。

---

## R-8: `state.platform` の Literal 廃止に伴う入口検証（spec の保留事項 D-1）

**Decision**: `AgentInputState.platform` / `AgentState.platform` を `str` にし、**入口（Studio）での
検証は行わない**。検証は `get_provider()` の 1 箇所に残す（未登録名は `ValueError`）。

- **CLI**: `--platform` の `choices=available_platforms()` により、未知の値はこれまでどおり
  引数エラー（終了コード 2）になる。**契約は変わらない**（SC-007 の対象は CLI のみ）。
- **Studio**: 未登録名を指定した場合はノード実行時に `ValueError` になる。これは変更前と
  「失敗する」点で同じであり、失敗の見え方（LangGraph の例外表示）も同じ経路である
  （変更前は `Literal` により入力段階で弾かれていた）。
- `Configuration.platform` の既定は空文字（未指定）とし、`get_provider("")` は
  **登録辞書の先頭のプラットフォーム**を返す（`DEFAULT_PLATFORM = next(iter(_PROVIDERS))` 相当の
  解決を登録側で行う。名前のリテラルは増やさない）。これにより Studio で platform を指定せずに
  実行した場合の挙動（X として動く）が維持される。

**Rationale**: spec の Assumptions は「既存の観測可能な挙動を変えないことを優先する」と定める。
`Literal` を外すと Studio の入力検証だけが失われるが、(a) 失敗するという結果は同じ、(b) CLI の
契約（唯一のテストで固定された契約）は変わらない、(c) 検証を状態定義に戻すと FR-002 に違反する。
したがって「入口の検証は登録側の 1 箇所（`get_provider`）に寄せる」が最もリスクの低い解である。

**Alternatives considered**:
- `field_validator` で `Configuration.platform` を登録辞書に対して検証する → `configuration.py` が
  provider の登録を参照することになり、設定層がプラットフォーム実装に依存する（循環の温床）。
- Pydantic の `Literal` を動的生成 → 型検査（mypy）が効かず、`Literal` を廃止する目的にも反する。
- Studio の既定を「未指定ならエラー」に変える → 観測可能な挙動の変更であり、本機能の最優先事項に反する。

---

## R-9: 出力一致（SC-006）の検証方法

**Decision**: 実装の**前**に、代表入力の Markdown / JSON を golden として採取し、
`tests/unit/test_rendering.py` で byte 比較する。

- 採取手順は `quickstart.md` 手順 4 に固定する（固定の `ResearchReport` を組み立てて
  `render_markdown` / `render_json` を呼び、出力を `tests/unit/golden/` 配下へ保存）。
- 比較は `json.dumps(..., ensure_ascii=False)`（JSON）と文字列一致（Markdown）。
- **JSON には削除対象フィールドの意図的な差分が生じる**: `render_json` は
  `report.model_dump_json(indent=2, exclude_none=True)` であるため、`ResearchInstruction.use_trends`
  （REM-003 / FR-009）と `OutputSpec.table_for`（REM-004 / FR-008）が JSON から消える。
  比較時は当該 2 キーを両側で除去してから byte 比較する（RND-003）。Markdown 側には現れないため
  byte 一致を維持する。**これは「削除の副作用」ではなく「削除要件の帰結」**であり、SC-006 の
  文言は変更しない。
- golden の採取は **変更前の `src/` に対して実行**する。上記 2 キー以外の差分が出たら、それは
  観測可能な出力の変更であり、実装を直す（テストを書き換えない）。

**Rationale**: 「分離の前後で出力が同一」を確かめる唯一の機械的な方法である。CLI 経由の比較
（`tests/integration/test_cli_contract.py`）では LLM 応答のフェイクに依存して網羅が落ちるため、
描画だけを固定入力で検証する層を別に持つ。`_render_analysis_block` の分岐（本文あり／なし、
要約なし、アイデアあり／なし、引用あり／なし）を代表させるため、golden は **3 入力**
（X の完全形・YouTube の完全形・欠落形）を用意する。

**Alternatives considered**:
- 変更前に CLI を実行して real な出力を採る → LLM とネットワークが要る（FR-023 に反する）。
- 事後（変更後）に golden を採る → 分離の前後一致を検証できない（自己言及的で無効なテストになる）。

---

## R-10: 削除対象の確定と、それに伴い更新する参照

**Decision**: 削除対象を次の 5 件 + `Config` 一式に確定し、参照を同一変更で更新する。

| # | 削除対象 | 実行時の参照（実測） | 同一変更で更新する参照 |
|---|---|---|---|
| 1 | `cache.read_json`（`cache.py:28`） | 0（`tests/unit/test_cache.py` の 5 件のみ） | 当該テスト節の削除 |
| 2 | `prompts.COMPILE_REPORT_PROMPT`（`prompts.py:175`） | 0 | なし（テストからの参照も 0） |
| 3 | `--trends` 一式（CLI フラグ / `Configuration.use_trends` / `ResearchInstruction.use_trends` / `AgentState.use_trends` / `parse_instruction.py:191`） | 0（分岐に寄与しない）。ただし `ResearchInstruction.use_trends` は **JSON 出力に現れる**（下記の注記） | `README.md:168`、`--help`（argparse の定義）、`tests/unit/test_configuration.py`、`tests/unit/test_parse_instruction.py`、`tests/integration/test_cli_contract.py`、`specs/001-test-suite-hardening/contracts/cli-contract.md:128` |
| 4 | `OutputSpec.table_for`（`models.py:25`） | 0。ただし `table_for` は `ResearchInstruction.output` 経由で **JSON 出力に現れる**（下記の注記） | `tests/unit/test_models.py`（既定値の断言があれば） |
| 5 | `tools/x_search.fetch_thread`（`x_search.py:165`） | 0（`tests/unit/test_x_search.py` の 11 件のみ。`fetch_threads` は `_fetch_threads_async` を直接使う） | 当該テスト節の削除（`fetch_threads` のテストは維持） |
| 6 | `Config` / `get_config` | `Config` は `src/` 9 ファイルから、`get_config` は 0 | R-5 の表に従う。`__init__.py` の `__all__` も更新 |

**Rationale**: 削除は最後の段階に置く（他の 3 本の柱の作業中に削除済みコードを触らないため）。

> **注記（実測 2026-09-13）**: 「実行時の参照 0」は**分岐・制御フローへの寄与がない**ことを指す。
> `ResearchInstruction.use_trends` と `OutputSpec.table_for` は `render_json`
> （`report.model_dump_json`）を通じて **JSON レポートに現れる**ため、削除すると JSON の出力が
> 変わる。これは FR-008 / FR-009 の削除に必然的に伴う**意図的な差分**であり、R-9 / RND-003 の
> とおり当該 2 キーを除外して byte 比較する。

`specs/001-test-suite-hardening/` のうち **`contracts/cli-contract.md` は現行の CLI 契約を定める
文書**なので更新する（憲法 VI「改名・削除は同一変更内で全参照（実装・テスト・README / spec / tasks）を
更新する MUST」）。`plan.md` / `tasks.md` / `research.md` は完了済み機能の**履歴**であり書き換えない
（当時の判断の記録を失うため。差は本機能の `removal-rationale.md` が引き受ける）。

**Alternatives considered**:
- `--trends` を「予約」として残す → spec の Assumptions と FR-009 が削除を MUST と定めている。
- `fetch_thread` を public API として残す → `src` からの参照 0 であり、FR-008 が削除を MUST とする
  （`fetch_threads` が同等の機能を提供している）。

---

## R-11: プロンプト本文の置き場所

**Decision**: プロンプト本文（`prompts.py`、177 行）は**動かさない**。`providers/x.py` /
`providers/youtube.py` のプロパティが引き続き選択する。走査テストの対象外にする理由を
`contracts/platform-extensibility-contract.md` に明記する（**データであり分岐を持たない**）。

**Rationale**: FR-004 の「差はプラットフォーム側で表現 MUST」は、差の**選択**が provider の
プロパティで行われているため満たされている。本文を各 provider へ移すと、(a) 2 ファイルが
プロンプト本文で膨張し、コードとしての読みやすさが落ちる、(b) リスク最小を最優先とする本機能で
無価値な churn が増える。spec の基準値 15 も `prompts.py` を数えていない（データは分岐ではない）。

**Alternatives considered**:
- `providers/x_prompts.py` / `providers/youtube_prompts.py` へ分割 → 長所は概念的な純度のみで、
  測定可能な成功基準（SC-001〜SC-010）に寄与しない。
- `prompts.py` を削除して各 provider のファイル末尾に置く → レビュー時の差分が本文だけで埋まり、
  フックの実装変更が読みにくくなる。

---

## R-12: 憲法の改正要否（spec の保留事項への回答）

**Decision**: **原則の追加・削除・再定義は不要**。ただし本機能の完了に伴い、憲法の**記述 3 箇所**が
実態と食い違うため、**実装完了後に `/speckit.constitution` で PATCH 改正する**（憲法 Governance の
改正手続きに従う。`tasks.md` T065 に含める）。

| # | 箇所 | 現行の記述 | 改正後 | 対応する要求 |
|---|---|---|---|---|
| 1 | 原則 IV | 「既存のプラットフォーム分岐（`nodes/compile_report.py` などに残存）は、そのファイルを変更する際に provider のフックへ寄せる SHOULD」 | 「コアにプラットフォーム名の列挙・比較を残してはならない MUST NOT」 | FR-001〜FR-004 / SC-002 |
| 2 | 原則 V | 「`NODE_ORDER`・**`ProgressEmitter.TOTAL`**・グラフのノード数の一致を保つ MUST」 | 「`NODE_ORDER` とグラフのノード数を一致させ、総数と表示番号は単一の定義（`NODE_ORDER`）から導出する MUST（手書きの定数を置かない）」 | FR-012（T035 で `TOTAL = 7` を削除する） |
| 3 | 技術制約と品質基準 | 「実行条件は `.env` と **`Config`** から供給し、コードにハードコードしてはならない MUST NOT」 | 「`.env` と **`Configuration`**（唯一の実行時設定型）から供給し」 | FR-013（T042 で `Config` を削除する） |

**Rationale**: 原則 IV が要求するのは「コアはプラットフォーム非依存」「差は `providers/` に実装」
「新プラットフォームは Provider の実装＋登録＋単体テストで追加できる」であり、本計画はこれを
**強化する**方向（分岐を追加せず削除する）。したがって射程の拡大は改正を要しない。一方で、
本機能の完了によって**前提が消える記述が 3 箇所**生じる。

- #1 は「残存する分岐を SHOULD で寄せる」という前提が消える（寄せ終わるため）。
- #2 は `ProgressEmitter.TOTAL` の維持を MUST としているが、FR-012 は「総数と表示番号を単一の
  定義から導出 MUST」を要求しており、両者は両立しない（`TOTAL = 7` の手書きが二重管理の実体）。
- #3 は FR-013 が削除する `Config` を供給元として名指ししている。

いずれも**方針の変更ではなく記載の追随**であり、バージョニング規約では PATCH（文言修正）に相当する
（1.2.0 → 1.2.1）。#2 と #3 は `plan.md` の Constitution Check で「改正対象」として記録する。

**順序の制約**: 改正は US1〜US4 の実装完了後に行う（先に改正すると、残存分岐が実在する間は
改正後の記述が実態と食い違う）。ただし T035 / T042 は T065 と同一の変更一式として完了させ、
憲法と実装を同時に green にする。

**Alternatives considered**:
- 実装前に改正する → 実装が完了するまで「残存分岐」が存在するため、改正後の記述が一時的に
  実態と食い違う（順序が逆）。
- 改正せず放置する → 憲法が「SHOULD」と言い続け、次のレビューで「なぜ残っていないのか」の
  説明を毎回要する（001 のレビュー往復で繰り返し発生した「記載と実態の乖離」の欠陥クラス）。
- 原則 V / 技術制約の記述を「改正不要」として放置する → FR-012 / FR-013 の完了時点で
  **憲法違反が確定する**。方針の変更ではなく記載の追随であるため PATCH で解消する。
