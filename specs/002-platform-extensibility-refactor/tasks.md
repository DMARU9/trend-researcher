---

description: "Task list for 002-platform-extensibility-refactor"
---

# Tasks: 新しいプラットフォームを追加しやすくするリファクタリング

**Input**: Design documents from `/specs/002-platform-extensibility-refactor/`

**Prerequisites**: `plan.md`（必須）, `spec.md`（必須・ユーザーストーリー）, `research.md`（R-1〜R-12）,
`data-model.md`, `contracts/`（EXT / SET / RND / REM）, `quickstart.md`, `.specify/memory/constitution.md`

**Tests**: **必須**（憲法 原則 I「テスト必須（NON-NEGOTIABLE）」）。各ユーザーストーリーは、
そのストーリー単体で検証できるテストを最低 1 つ含む。テストは実装より先に書き、**赤になることを確認**する。

**Organization**: ユーザーストーリー単位でフェーズを分ける。優先度順（US1 → US2 → US3 → US4）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 並行実行可（別ファイル・未完のタスクへの依存なし）
- **[Story]**: US1〜US4（`spec.md` のユーザーストーリーに対応）
- すべてのタスクに具体的なファイルパスを含める

## パスの規約

- 単一プロジェクト（`src/` レイアウト）。ソースは `src/trend_researcher/`、テストは `tests/`。
- リポジトリルートは `/home/takumi/github/trend-researcher`。

## このリファクタリング固有の注意（全タスク共通）

- **観測可能な挙動を変えない**（最優先）。stdout = レポートのみ / stderr = 進捗・ログ・エラー /
  終了コード 0・1・2 / レポートの Markdown・JSON は byte 一致 / 進捗行は 7 行。
- **後方互換シムを残さない**（憲法 原則 VI / FR-020）。旧名の別名・非推奨ラッパー・二重実装を作らない。
- テストはネットワーク・実認証情報なしで完走する（FR-023）。新規依存を追加しない（FR-024）。
- **テストスイート全体は 60 秒以内**（SC-010）。基準は 49.67 秒なので、増加に使える余地は約 10 秒。
- 走査テストの目標は「許容リストの 2 行のみ」。**`platform` のフォールバックや既定値のリテラルを
  新たに書かない**こと（書いた瞬間に SC-002 が崩れる）。
- 各フェーズのチェックポイントで `uv run pytest -q`（カバレッジ計測込み）を通し、
  **547 passed から落ちていない**ことと**カバレッジ 90% 以上**を確認する。
- 走査テストは 5 つの検出規則で構成する（(a) 名の完全一致 / (b) `env_prefix` の接頭辞 /
  (c) ノードの環境変数読み込み / (d) ヘルプ文の名前列挙 / (e) プラットフォームの集合型）。
  **規則 (c) は US3 の T038 で追加する**（US1 の時点では `Config` が実在するため）。

---

## Phase 1: Setup（共有の準備）

**Purpose**: 変更前の安全網を確定する。コードは変更しない。

- [ ] T001 `plan.md` の「基準値のずれ」と Constitution Check に記録した基準値（547 passed /
      カバレッジ 95.29% / `ruff` 0 件 / `mypy` 0 件 / 49.67 秒）を、ブランチ
      `002-platform-extensibility-refactor` の作業ツリーで `uv run pytest -q`、
      `uv run ruff check .`、`uv run mypy src` により再現し、作業ツリーが clean であることを
      `git status --short` で確認する（記録先: `specs/002-platform-extensibility-refactor/tasks.md`
      の「実装メモ」節）
- [ ] T002 [P] 遅いテストを把握して時間予算を確保する。`uv run pytest -q --no-cov --durations=15` を実行し、
      上位 15 件の所要時間を「実装メモ」節に控える（SC-010 の 60 秒以内を守るため、追加する 3 テストの
      上限を決める根拠にする）
- [ ] T003 [P] オフライン制約を実測する。`env -u OPENAI_API_KEY -u XTR_ACCOUNTS_DB -u YTR_ACCOUNTS_DB
      uv run pytest -q --no-cov` を実行し、認証情報なしでも 547 passed のままであることを確認する
      （FR-023 の基準。ここで赤が出る場合は既存テストの問題として記録し、本機能では触らない）

---

## Phase 2: Foundational（全ストーリーの前提・ブロッキング）

**Purpose**: 出力一致（SC-006）の golden を**変更前のツリー**から採取し、US1〜US4 を通じて
出力の不変を継続的に検証できる状態にする。**golden は変更後に採ると自己言及的なテストになり無効**なため、
必ずこのフェーズ（最初のコード変更より前）で行う。

**⚠️ CRITICAL**: このフェーズが完了するまで US1〜US4 のどの実装タスクも開始しない。

- [ ] T004 `tests/unit/test_rendering.py` を作成し、golden の入力を作る関数
      `build_golden_cases() -> dict[str, tuple[ResearchReport, Provider]]` のみを書く。
      キーは `x_full`（X・完全形）/ `youtube_full`（YouTube・完全形）/ `sparse`（文脈・分析・
      共通テーマが空）の 3 件。`ResearchReport` / `ResearchInstruction` / `Candidate` /
      `AnalysisFinding` / `CommonTheme` を直接組み立て、LLM・LangGraph・境界モックを使わない。
      **3 件すべてで既定値に依存する値を明示する**（`platform` / `output.format` など。
      US1 で `platform` の既定が `"x"` → `""` に変わるため、既定に依存すると golden が
      意図せず変化する）。この時点では描画関数を import しない（`_render_*` の対象が見えないようにするため）
- [ ] T005 `tests/unit/test_rendering.py` に、golden ファイルと byte 比較する検証を追加する。
      比較対象は `tests/unit/golden/{x_full,youtube_full,sparse}.{md,json}`。
      **変更前の所在である `from trend_researcher.nodes.compile_report import render_json, render_markdown`
      を import する**（US4 の T052 で `trend_researcher.rendering` へ切り替える）。
      このタスクは T004 と T006 の後に行い、golden が無い状態では赤になることを確認する
- [ ] T006 `quickstart.md` の手順 4-1 のコマンドを実行し、**変更前のツリー**から
      `tests/unit/golden/` の 6 ファイル（3 入力 × md/json）を採取する。採取後、`uv run pytest
      tests/unit/test_rendering.py -q` が緑になることを確認する
- [ ] T007 決定論を確認する。T006 の採取をもう一度実行して `git status --short tests/unit/golden/`
      が空（byte 一致）であることを確かめる。差が出る場合は golden を採る対象（`render_json` の
      キー順、時刻の埋め込み）を特定し、「実装メモ」節に記録してから比較方法を確定する
      （決定論でない出力を byte 比較すると flaky なテストになる）

**Checkpoint**: golden が確定し、`tests/unit/test_rendering.py` が緑。以降のすべてのフェーズで
「レポート出力が変わっていない」ことが自動で検証される。

---

## Phase 3: User Story 1 - 新しいプラットフォームをコア変更なしで追加できる (Priority: P1) 🎯 MVP

**Goal**: プラットフォーム差の表現先を provider のフックに集約し、コアからプラットフォーム名の
列挙・比較を消す（走査 16 行 → 2 行）。試験用プラットフォームを登録するだけでパイプラインが完走する。

**Independent Test**: `tests/unit/test_platform_scan.py`（検出 2 行）と
`tests/unit/test_platform_extension.py`（試験用プラットフォームの完走）の 2 本で完結する。
あわせて既存 2 プラットフォームのテストが緑のままであることを確認する。

### Tests for User Story 1（憲法 原則 I により必須）⚠️

> **NOTE: 実装より先に書き、赤になることを確認する。** ネットワーク・実認証情報を使わない。

- [ ] T008 [P] [US1] `tests/unit/test_platform_scan.py` を作成する。AST 走査の検出器を実装し、
      **現行ツリーに対して 16 行を検出**しつつ、許容リスト（`providers/__init__.py` の登録辞書 2 行）
      との不一致で**赤**になることを確認する。仕様は `data-model.md` 4 節と
      `contracts/platform-extensibility-contract.md` の EXT-008 に従う:
      (a) 文字列定数が登録済みプラットフォーム名と一致、(b) 文字列定数または識別子が
      登録済み `env_prefix` の `^(XTR|YTR)_` に一致（正規表現は `get_provider(name).env_prefix` から
      **動的に組み立てる**）、除外は `providers/{x,youtube,base}.py` /
      `tools/{x_search,youtube_search,transcript}.py` / `prompts.py` / docstring、
      許容リストは `_PROVIDERS` の dict リテラルを AST から見つけて**そのキーの行**を
      ソースから取得する（リテラルをハードコードしない）。違反時はファイル・行・内容を列挙して失敗させる。
      同じファイルに追加の検出規則も入れる:
      **(d)** `help=` / `description=` のキーワード引数に**登録済みプラットフォーム名を部分文字列として
      含む**文字列が 0 件であること（SC-002 の「列挙」を説明文にも広げる。完全一致の規則 (a) では
      説明文を取り逃すため。**現行は `__main__.py` の `--platform` ヘルプ 1 件 → T022 で 0 件**なので、
      この時点で**赤**になることを確認する）、
      **(e)** プラットフォームの集合を扱う型（`list[Provider]` / プラットフォーム名をキーとする
      `dict[str, ...]`）が 0 件であること（FR-026。**現行も 0 件なので回帰ガード**であり、赤にはならない。
      非空虚性は T024 の変異探針で確認する）。
      **(c)**（`nodes/**.py` に環境変数読み込みが 0 件）は **US3 の T038 で追加する**
      （US1 の時点では `Config.load` がまだ存在し、検出対象が実在するため）
- [ ] T009 [P] [US1] `tests/unit/test_platform_extension.py` を作成する。`Provider` Protocol を満たす
      試験用プラットフォーム（`name="dummy"` など、`env_prefix` を含む追加フック 5 つを実装）を
      `register_provider()` で登録し、境界（`search` / `fetch_contexts` / LLM）をテスト内のフェイクで
      置き換えて `build_graph()` のパイプラインを完走させる。検証は「`report` が生成される」
      「進捗が 7 行」「レポートに試験用プラットフォームの `content_noun` /
      `candidates_section_title` / `selection_note` が反映される」の 3 点。
      **後始末で登録を解除し、他のテストへ影響を残さない**（フィクスチャの `finally` で行う）。
      実装前はフックが存在しないため**赤**になることを確認する
- [ ] T010 [US1] T008 / T009 が**期待どおりの理由で**赤であることを確認し、「実装メモ」節に記録する
      （T008 は「16 行検出」、T009 は「`register_provider` が無い」または「フックが無い」）

### Implementation for User Story 1

- [ ] T011 [US1] `src/trend_researcher/providers/base.py` の `Provider` Protocol に追加フック 5 つを
      定義する（`env_prefix: str` / `max_search_queries: int | None` / `content_noun: str` /
      `candidates_section_title: str` / `selection_note(self, sort_by: str) -> str`）。
      docstring に「コアは値を解釈しない（差の表現のみを担う）」旨を記す。既存 13 メンバは変更しない
- [ ] T012 [P] [US1] `src/trend_researcher/providers/x.py` にフックを実装する。
      `env_prefix = "XTR"`、`max_search_queries = 8`、`content_noun = "ツイート"`、
      `candidates_section_title = "## 選定ツイートリスト（上位 N 件）"`、
      `selection_note(sort_by)`（`sort_by == "likes"` なら「いいね数の多い順」、それ以外は
      「いいね数の少ない順」を使った `nodes/compile_report.py:37` と同じ文）
- [ ] T013 [P] [US1] `src/trend_researcher/providers/youtube.py` にフックを実装する。
      `env_prefix = "YTR"`、`max_search_queries = None`、`content_noun = "動画"`、
      `candidates_section_title = "## 選定動画リスト（関連度順上位 N 件）"`、
      `selection_note(sort_by)` は `sort_by` を使わず「検索結果の関連度順に上位 N 件を採用」
      （現行 `compile_report.py:41` と同じ文）
- [ ] T014 [US1] `src/trend_researcher/providers/__init__.py` に `register_provider(cls)` を追加し、
      `get_provider()` のエラー文言を登録キーから生成する（プラットフォーム名のリテラルを含めない）。
      **空文字・空白のみの名前は登録辞書の先頭のプラットフォームとして解決する**
      （`Configuration.platform` の既定を空文字にするため。research.md R-8 / EXT-007）。
      `available_platforms()` は現行どおり登録順のキー一覧を返す
- [ ] T015 [US1] `src/trend_researcher/state.py` の `platform` 2 箇所（`AgentInputState` /
      `AgentState`）を `Literal["x", "youtube"]` から `str` へ変更する（FR-002）。
      `Literal` の import が不要になれば削除する
- [ ] T016 [US1] `src/trend_researcher/models.py` の `platform` 2 箇所
      （`ResearchInstruction` / `Candidate`）の既定を `"x"` から `""` へ変更する（FR-002）。
      docstring に「空文字は登録済みプラットフォームの先頭として解決される」旨を追記する
- [ ] T017 [US1] `src/trend_researcher/configuration.py` の `platform` の既定を `"x"` から `""` へ変更し、
      `description` を「対象プラットフォーム（未指定時は既定のプラットフォーム）」に更新する
      （FR-002。フィールドの追加・削除はしない）
- [ ] T018 [US1] `src/trend_researcher/config.py` の `Config.load()` の引数 `platform: str = "x"` を
      `env_prefix: str | None = None` に置き換え、`prefix = "XTR" if platform == "x" else "YTR"` の行を
      **削除**して `env_prefix` をそのまま使う（`env_prefix` が `None` のときは `TR_*` のみを見る）。
      併せて呼び出し側（`src/trend_researcher/__main__.py`、`src/trend_researcher/nodes/search.py`、
      `src/trend_researcher/nodes/fetch.py`）を `get_provider(platform).env_prefix` を渡す形へ変更する。
      **注意**: `Config` クラス自体の削除は US3（T046）であり、ここでは引数の形だけを変える
- [ ] T019 [US1] `src/trend_researcher/tools/llm.py` の `build_model(role="research", env_prefix: str | None = None)`
      へ変更し、`TR_MODEL` → `{env_prefix}_MODEL` → 既定（`openai:mimo-v2.5`）の順にする
      （`XTR_MODEL` / `YTR_MODEL` の直列を排除）。呼び出し側
      （`nodes/parse_instruction.py` / `nodes/plan_search.py` / `nodes/analyze_content.py` /
      `nodes/extract_common.py`）で `provider.env_prefix` を渡すようにする
- [ ] T020 [US1] `src/trend_researcher/nodes/plan_search.py` の
      `platform = (instruction.platform or "x").lower()` と
      `if platform == "x" and len(queries) > 8:` を、`provider.max_search_queries` による上限適用へ
      置き換える（`None` は無制限）。既存コメント（X のみ適用・YouTube は単一クエリ）を残しつつ、
      プラットフォーム名を書かない形に書き直す
- [ ] T021 [US1] `src/trend_researcher/nodes/compile_report.py` の分岐 3 箇所
      （`:37` 選定基準の注記 / `:45` の名詞 / `:85` の表題）を provider のフック
      （`selection_note` / `content_noun` / `candidates_section_title`）へ置き換える。
      **出力文字列は 1 文字も変えない**（golden で検証される）
- [ ] T022 [US1] `src/trend_researcher/__main__.py` の
      `subject = "ツイート" if platform == "x" else "動画"` を `get_provider(platform).content_noun` に
      置き換える。`get_provider` は `try` の外（引数検証済みの位置）で 1 回だけ解決する。
      併せて `--platform` のヘルプ本文にあるプラットフォーム名の列挙
      （`"対象プラットフォーム（x=X/Twitter、youtube=YouTube）"`）を削除し、利用可能な値の提示は
      `choices=available_platforms()` に委ねる（登録の追加だけでヘルプが正しくなる状態にする。
      T008 の検出規則 (d) を 0 件にする）。`--help` の終了コードと出力先の契約は変えない
      （`tests/integration/test_cli_contract.py` が終了コードのみを固定していることは実測済み）
- [ ] T023 [US1] `uv run pytest tests/unit/test_platform_scan.py -q` を実行し、**規則 (a)+(b) の検出が
      2 行**（許容リストのみ）になり、**規則 (d) が 0 件**（T022 のヘルプ汎用化で解消）・
      **規則 (e) が 0 件**であることを確認する。「実装メモ」節に検出結果の内訳
      （(a)+(b): 16 → 2、(d): 1 → 0、(e): 0 → 0）を記録する
- [ ] T024 [US1] 走査テストの**非空虚性**を変異探針で確認する。(1) `src/trend_researcher/graph.py` に
      一時的に `_PLATFORM_HINT = "x"` の行を追加 → `uv run pytest tests/unit/test_platform_scan.py -q`
      が**赤**になる、(2) `src/trend_researcher/__main__.py` の `--platform` のヘルプに `"x"` を
      一時的に含める → 規則 (d) が**赤**になる、(3) `src/trend_researcher/providers/__init__.py` に
      一時的に `_ALL: list[Provider] = []` を追加 → 規則 (e) が**赤**になる。
      各探針は `git checkout -- <file>` で復元し、**復元後に 3 つとも緑に戻る**ことを確認する。
      さらに復元後の sha256 が探針前と一致することを確かめる（`sha256sum` で比較）。
      結果（赤のログの要点）を「実装メモ」節に記録する
- [ ] T025 [US1] 影響を受ける既存テストを追随させる。`tests/unit/test_config.py`
      （`Config.load(platform=...)` → `env_prefix=...`。**期待値は変えず、`XTR_*` / `YTR_*` の
      解決結果の断言を維持する**）、`tests/unit/test_providers.py`（追加フックの存在）、
      `tests/unit/test_plan_search.py`（上限が provider 由来になったこと）、
      `tests/unit/test_compile_report.py`（出力文字列が不変であること）。
      追随で消える網羅があれば、同等の入力を残して補う
- [ ] T026 [US1] `uv run pytest -q` を実行して全件緑を確認する。併せて `quickstart.md` 手順 3 の
      diff 確認（コアに追加の差分が出ていないこと）を行い、走査・拡張の 2 テストと既存 2
      プラットフォームのテストが同時に緑であることを確認する（SC-001 / FR-006）

**Checkpoint**: US1 が単体で完成。コアからプラットフォーム名が消え、試験用プラットフォームを
登録するだけで完走する。既存 X / YouTube の挙動は不変（golden と CLI 契約で担保）。

---

## Phase 4: User Story 2 - 不要なものを取り除き、重複した定義を 1 つにする (Priority: P2)

**Goal**: 実行時の参照が 0 の機能（5 件）を削除し、進捗表示の番号と総数を単一の定義
（`NODE_ORDER`）から導出する。

**Independent Test**: 削除対象の不在と進捗の導出を検証するテスト、および CLI 契約テストが緑で
あることで完結する。観測可能な出力（進捗行の書式・行数）は不変であることを確認する。

### Tests for User Story 2（憲法 原則 I により必須）⚠️

- [ ] T027 [P] [US2] `tests/unit/test_progress.py` を新しい形へ書き換える。検証内容:
      (a) `emit(node_name, phase, detail)` の 1 引数化に伴い、表示番号が
      `NODE_ORDER.index(node_name) + 1`、総数が `len(NODE_ORDER)` になること、
      (b) 進捗行の書式 `[i/total] name ... phase（detail）` が現行と一致すること、
      (c) 未登録のノード名は `ValueError` になること、
      (d) **導出の非空虚性**: `monkeypatch.setattr(progress, "NODE_ORDER", [...])` で順序・件数を
      変えると出力が追随すること（手書きの番号に戻したら落ちるテストにする）
- [ ] T028 [US2] 削除対象の不在を固定する。既存テストに次の断言を追加する:
      `tests/unit/test_cache.py`（`hasattr(cache, "read_json")` が偽）、
      `tests/unit/test_models.py`（`OutputSpec` に `table_for` が無い）、
      `tests/unit/test_x_search.py`（`hasattr(x_search, "fetch_thread")` が偽）、
      `tests/unit/test_providers.py` または `tests/unit/test_parse_instruction.py`
      （`Configuration.model_fields` / `ResearchInstruction.model_fields` / `AgentState.__annotations__`
      に `use_trends` が無い）。実装前は赤になることを確認する
- [ ] T029 [US2] T027 / T028 が期待どおり赤であることを確認し、「実装メモ」節に記録する

### Implementation for User Story 2

- [ ] T030 [US2] `src/trend_researcher/cache.py` から `read_json` を削除し、docstring の
      「将来の途中再開等に備えて用意」の記述を削除する。`write_json` は変更しない（REM-001）
- [ ] T031 [P] [US2] `src/trend_researcher/prompts.py` から `COMPILE_REPORT_PROMPT` を削除する
      （REM-002。他のプロンプト本文は変更しない）
- [ ] T032 [US2] `--trends` 一式を削除する（REM-003）:
      `src/trend_researcher/__main__.py` の `--trends` 定義と `use_trends=args.trends`、
      `src/trend_researcher/configuration.py` の `use_trends` フィールド、
      `src/trend_researcher/models.py` の `ResearchInstruction.use_trends`、
      `src/trend_researcher/state.py` の `use_trends`、
      `src/trend_researcher/nodes/parse_instruction.py` の `use_trends=...`。
      **同一変更で更新する参照**: `README.md`（`--trends` の記載と環境変数一覧）、
      `specs/001-test-suite-hardening/contracts/cli-contract.md`（129 行付近の `--trends`）、
      `tests/unit/test_configuration.py`（`DEFAULTS`）、
      `tests/unit/test_parse_instruction.py`（該当節）、
      `tests/integration/test_cli_contract.py`（`--trends` の受理）。
      **`specs/001-test-suite-hardening/` の `plan.md` / `tasks.md` / `research.md` /
      `data-model.md` / `quickstart.md` は履歴のため書き換えない**
- [ ] T033 [P] [US2] `src/trend_researcher/models.py` から `OutputSpec.table_for` を削除する
      （REM-004）
- [ ] T034 [US2] `src/trend_researcher/tools/x_search.py` から `fetch_thread` を削除する（REM-005）。
      **失われる網羅を補う**: `fetch_threads` のテストに「1 件だけ返る場合」のケースを追加し、
      本文の連結が同じ経路で検証されるようにする
- [ ] T035 [US2] `src/trend_researcher/progress.py` を単一の定義へ変更する（FR-012 / REM-008）。
      `emit(self, node_name: str, phase: str, detail: str = "")` にし、
      `index = NODE_ORDER.index(node_name) + 1` を計算して行を組み立てる。総数は `self.total`
      （`ProgressEmitter.__init__` の既定値）を使い、既定値の算出元を `len(NODE_ORDER)` にする。
      `ProgressEmitter.TOTAL = 7` は削除し、`total` の上書き（テスト用）は引き続き可能にする。
      **進捗行の文字列は 1 文字も変えない**。
      **注意**: 憲法 原則 V が `ProgressEmitter.TOTAL` の維持を MUST としているため、T065 と
      **同一の変更一式**として完了させる（片方だけを適用した状態は憲法違反になる。C1）
- [ ] T036 [US2] 7 ノードの `emitter.emit(...)` 呼び出しから数値の番号引数を削除する
      （`nodes/parse_instruction.py` / `nodes/plan_search.py` / `nodes/search.py` /
      `nodes/fetch.py` / `nodes/analyze_content.py` / `nodes/extract_common.py` /
      `nodes/compile_report.py`）
- [ ] T037 [US2] `uv run pytest -q` を実行し、削除に伴う赤を解消する。
      `tests/unit/test_cache.py` / `tests/unit/test_x_search.py` / `tests/unit/test_models.py` の
      削除対象を固定していた節を削除し、`tests/integration/test_full_flow.py` の進捗 7 行の断言を
      **維持したまま**通す。削除したテストごとに「何を固定していたか」を
      `contracts/removal-rationale.md` の REM-001〜REM-008 と突き合わせて確認する（SC-008）

**Checkpoint**: US2 完了。実行時の参照が 0 の機能が消え、進捗は単一定義から導出される。
US1 の機能（走査・拡張）と golden は赤くなっていない。

---

## Phase 5: User Story 3 - 実行時設定の出所を 1 つにする (Priority: P3)

**Goal**: 設定型を `Configuration` の 1 つにし、環境変数・`.env` の解決を
`configuration.py` に集約する。ノードは環境変数を読まなくなる（2 ノード → 0）。

**Independent Test**: 設定の優先順位（明示指定 > `TR_*` > `{env_prefix}_*` > 既定）のテストと、
「ノードが環境変数を読まない」走査テストが緑であることで完結する。

### Tests for User Story 3（憲法 原則 I により必須）⚠️

- [ ] T038 [P] [US3] `tests/unit/test_platform_scan.py` に
      `test_nodes_do_not_read_environment` を追加する（SET-004 / SC-004）。`src/trend_researcher/nodes/**`
      を AST 走査し、`os.getenv` / `os.environ` / `load_dotenv` / `Config.load` の呼び出しが
      **0 件**であることを確認する。実装前は 2 件（`nodes/search.py` / `nodes/fetch.py`）で**赤**
      になることを確認する
- [ ] T039 [P] [US3] `tests/unit/test_config.py` を `Configuration.load()` /
      `resolve_env(..., env_prefix=...)` の経路へ移行する。**期待値（どの変数がどの値になるか）は
      変更前と同一に保つ**。追加する検証: `Configuration.load(env_prefix="XTR")` が
      `TR_MAX_RESULTS` > `XTR_MAX_RESULTS` > 既定 5 の順で解決すること、
      明示指定（`Configuration(max_results=30)` を渡した `model_fields_set`）が環境変数より優先されること、
      `get_config` / `cache_clear` を固定していた節は削除すること。
      **T025 で `env_prefix=` に移した箇所を、本タスクで `Configuration.load()` の経路へ再度移す**
      （期待値は変えない。2 段階に分かれるのは US1 では `Config` がまだ存在するため）。
      実装前は import エラーで**赤**になることを確認する
- [ ] T040 [US3] T038 / T039 が期待どおり赤であることを確認し、「実装メモ」節に記録する

### Implementation for User Story 3

- [ ] T041 [US3] `src/trend_researcher/configuration.py` に
      `resolve_env(name, *, default, env_prefix=None) -> str`（`TR_{name}` → `{env_prefix}_{name}` →
      既定。空文字は未設定扱い）と `Configuration.load(env_prefix: str | None = None) -> Configuration`
      を追加する。`.env` の読み込み（`load_dotenv`）とパス解決（`config.py` の `_REPO_ROOT` /
      `_resolve_path` を再利用）もこの経路で 1 回だけ行う。`Configuration` に**フィールドを追加しない**
- [ ] T042 [US3] `src/trend_researcher/config.py` から `Config` クラスと `get_config()` を削除する
      （REM-006 / REM-007）。残すのは `_REPO_ROOT` / `_resolve_path` / `_load_env_once`（または
      `configuration.py` へ移したうえでモジュールごと削除）。`lru_cache` の使用をやめる。
      **`src/` から `Config` / `get_config` の参照を 0 にする**。
      **注意**: 憲法の「技術制約と品質基準」が実行条件の供給元を `Config` と明記しているため、
      T065 と**同一の変更一式**として完了させる（片方だけを適用した状態は憲法違反になる。C2）
- [ ] T043 [P] [US3] `src/trend_researcher/providers/x.py` に固有設定の解決を実装する（FR-003 / SET-003）。
      `@dataclass(frozen=True) class XSettings`（`accounts_db: Path` / `search_pool_size: int` /
      `max_retries: int`）と `XProvider.settings(configuration: Configuration) -> XSettings` を追加し、
      `resolve_env(..., env_prefix=self.env_prefix)` で解決する。`configuration.model_fields_set` に
      含まれる値は環境変数より優先する。`search` / `fetch_contexts` の引数型を `Config` から
      `Configuration` へ変更し、内部で `self.settings(configuration)` を使う。
      `providers/__init__.py` の `_PROVIDERS` の 2 行は**変更しない**（走査の許容リスト）
- [ ] T044 [P] [US3] `src/trend_researcher/providers/youtube.py` と
      `src/trend_researcher/providers/base.py` の `config: Config` を
      `configuration: Configuration` へ変更する（YouTube は固有設定を持たないため、共通値を
      `Configuration` から読む）
- [ ] T045 [US3] `src/trend_researcher/nodes/search.py` から `cfg = Config.load(platform=platform)` を
      削除し、`provider.search(..., configuration=configurable)` の形へ変更する。`max_results` の
      解決（`instruction.max_results or 5`）と既存コメント（FR-011 の優先順位）は**変更しない**。
      **ノードは `Configuration` を渡すだけで、`provider.settings(configuration)` は呼ばない**
      （固有設定の解決は provider の内部。ノードが設定型を知る範囲を広げない。data-model.md 2 節）
- [ ] T046 [US3] `src/trend_researcher/nodes/fetch.py` から `cfg = Config.load(platform=platform)` を
      削除し、`provider.fetch_contexts(candidates, configurable)` の形へ変更する。
      `settings()` の呼び出しは provider の内部に閉じる（T045 と同じ方針）
- [ ] T047 [US3] `src/trend_researcher/__main__.py` を `Configuration.load(env_prefix=provider.env_prefix)`
      の経路へ変更する（`Config` の import と `Config.load(...)` を削除）。`--cache-dir` /
      `--max-results` の明示指定は `Configuration` のフィールドとして与え、`RunnableConfig` に載せる
      （SET-006 の優先順位を維持）。**`config` を参照する残り 2 箇所も同時に置換する**:
      `lang = args.lang or config.transcript_language`（字幕言語。`--lang` を維持）と
      `requested = report.instruction.max_results or config.max_results`（件数の表示）。
      `Config` の削除後に `config.` 参照が **0 件**になることを `grep -n 'config\.' src/trend_researcher/__main__.py`
      で確認する（`__main__.py` はカバレッジ 46% でテストの網が薄いため実測で確かめる）
- [ ] T048 [P] [US3] `src/trend_researcher/__init__.py` の `Config` re-export を削除する
      （`__all__` の更新を含む）。`Configuration` と `render_report` の re-export は維持する
- [ ] T049 [P] [US3] `src/trend_researcher/tools/llm.py` の環境変数解決を `resolve_env` に寄せる
      （`build_model(role, env_prefix)` の内部で `resolve_env("MODEL", default="openai:mimo-v2.5",
      env_prefix=env_prefix)` を使う）。`TR_MODEL` → `{env_prefix}_MODEL` → 既定の順を変えない
- [ ] T050 [US3] `tests/integration/test_full_flow.py` の `Config` / `get_config` / `cache_clear` の
      参照を `Configuration` へ追随させる（**進行・件数・出力の断言は変更しない**）。
      `tests/unit/test_configuration.py` の `DEFAULTS` から `use_trends` を除き、`load()` の解決規則の
      節を追加する
- [ ] T051 [US3] `uv run pytest -q` で全件緑を確認し、`quickstart.md` の手順 6（設定型が 1 つ /
      ノードの環境変数 0 / 優先順位）を実行する。あわせて変異探針として `nodes/search.py` に
      一時的に `os.getenv("TR_MAX_RESULTS")` を書いて T038 が**赤**になることを確認し、復元後に
      緑へ戻ることを「実装メモ」節に記録する

**Checkpoint**: US3 完了。設定型が 1 つになり、ノードは環境変数を読まない。
US1 / US2 のテストは緑のまま。

---

## Phase 6: User Story 4 - レポート描画をパイプラインから分離する (Priority: P4)

**Goal**: 整形処理を `rendering.py` へ移し、`graph.py` から描画への参照を外す。描画は
**渡された provider** を使う（現行の「引数を捨てて解決し直す」不具合を解消）。

**Independent Test**: golden 比較（byte 一致）、渡された provider が使われることの検証、
`graph.py` が描画を参照しないことの走査が緑であることで完結する。

### Tests for User Story 4（憲法 原則 I により必須）⚠️

- [ ] T052 [P] [US4] `tests/unit/test_rendering.py` の import を
      `trend_researcher.nodes.compile_report` から `trend_researcher.rendering` へ切り替える。
      この時点で**赤**（モジュールが無い）になることを確認する。golden の比較内容は変更しない
- [ ] T053 [P] [US4] `tests/unit/test_rendering.py` に
      `test_markdown_uses_passed_provider` を追加する（FR-017 / RND-007）。
      X の `ResearchReport` と **YouTube の provider** の組で `render_markdown(report, provider)` を呼び、
      出力の名詞・表題・注記が**渡された YouTube の provider** のものになることを断言する。
      現行実装は引数を無視して `report.instruction.platform` から解決し直すため、このテストは
      **実装前は赤**になる（= 欠陥を実際に検出するテストであることの確認を兼ねる）
- [ ] T054 [P] [US4] `tests/unit/test_rendering.py` に
      `test_graph_does_not_reference_rendering` を追加する（FR-016）。`src/trend_researcher/graph.py` を
      AST 走査し、`rendering` の import・参照が 0 件であることと、
      `render_report` / `render_markdown` / `render_json` の名前が現れないことを確認する。
      実装前は**赤**になることを確認する
- [ ] T055 [US4] T052 / T053 / T054 が期待どおり赤であることを確認し、「実装メモ」節に記録する
      （T053 は「引数が無視されている」という**現行の不具合**を示す赤であることを明記する）

### Implementation for User Story 4

- [ ] T056 [US4] `src/trend_researcher/rendering.py` を新規作成し、
      `src/trend_researcher/nodes/compile_report.py` から
      `render_markdown` / `render_json` / `render_report` / `_render_candidates_table` /
      `_render_analysis_block` / `_render_common_themes` を**移動**する（コピーではない）。
      変更点は 2 つだけ: (a) `render_markdown` の先頭にある
      `provider = get_provider(report.instruction.platform)` を削除して**引数の provider を使う**、
      (b) `render_report(report, provider)` を置き、`format == "json"` なら `render_json(report)` を
      呼ぶ。**出力文字列は 1 文字も変えない**。`render_json(report)` の署名は変更しない
- [ ] T057 [US4] `src/trend_researcher/nodes/compile_report.py` から移動済みの関数を削除し、
      `from trend_researcher.rendering import render_markdown` を使って
      `rendered = render_markdown(report, provider)` を呼ぶ形にする。ノードの責務
      （`report` の組み立て / `cache.write_json` / 進捗 / メッセージ）は変更しない（RND-005）
- [ ] T058 [US4] `src/trend_researcher/graph.py` から描画関連の import と `render_report` を削除する。
      残すのは `build_graph()` / `_route_after_search` / `trend_researcher` / `EXECUTION_TIMEOUT`
      （FR-016 / RND-001）
- [ ] T059 [US4] `src/trend_researcher/__main__.py` で `render_report` を
      `trend_researcher.rendering` から import し、`render_report(report, provider)` を呼ぶようにする。
      `provider` は `main()` で 1 回だけ解決して再利用する（描画の内部で解決し直さない）
- [ ] T060 [P] [US4] `src/trend_researcher/__init__.py` の `render_report` の re-export 元を
      `rendering.py` へ変更する（`__all__` は維持）
- [ ] T061 [US4] `tests/unit/test_compile_report.py` の描画の断言を `tests/unit/test_rendering.py` へ
      移し、ノード側には「`report` が状態に入る」「`cache.write_json` が呼ばれる」「描画が
      呼ばれる（メッセージ本文にレポートが含まれる）」を残す。**観測可能な断言は削除しない**
      （移動である。REM-009 / SC-008）
- [ ] T062 [US4] `uv run pytest tests/unit/test_rendering.py -q` を実行し、golden 3 件が
      **byte 一致**であること、T053 / T054 が緑であることを確認する。
      比較は **Markdown は完全一致、JSON は `use_trends` / `table_for` の 2 キーのみ除外**（RND-003。
      FR-008 / FR-009 の削除に伴う意図的な差分。`removal-rationale.md` REM-003 / REM-004）。
      それ以外の差が出た場合は**実装を直す**（golden を書き換えない）。その後 `uv run pytest -q` で全件緑を確認する

**Checkpoint**: 全 4 ストーリーが独立に検証可能な状態。描画はノード実行なしで検証でき、
骨格は描画を参照しない。

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 仕様・文書・ゲートの最終確認。

- [ ] T063 [P] `README.md` を更新する。`--trends` の記載を削除し、環境変数を `TR_*`（共通）/
      `XTR_*`（X 固有）/ `YTR_*`（YouTube 固有）の 3 群で整理する。`--platform` の説明は変更しない
- [ ] T064 [P] `specs/002-platform-extensibility-refactor/quickstart.md` の手順 1〜7 を通しで実行し、
      各手順の実測値を「実装メモ」節に記録する（とくに手順 2 の検出 2 行、手順 3 の完走、
      手順 4 の byte 一致、手順 7 の 3 ゲートと実行時間）
- [ ] T065 憲法の文言を PATCH 改正する（research.md R-12 / plan.md の Constitution Check に
      記録した改正対象 3 点）。`.specify/memory/constitution.md` に対して次を行う。
      1. **原則 IV**: 「既存のプラットフォーム分岐（`nodes/compile_report.py` などに残存）は、
         そのファイルを変更する際に provider のフックへ寄せる SHOULD」を「コアにプラットフォーム名の
         列挙・比較を残してはならない MUST NOT」へ改める。
      2. **原則 V**: 「`NODE_ORDER`・`ProgressEmitter.TOTAL`・グラフのノード数の一致を保つ MUST」を
         「`NODE_ORDER` とグラフのノード数を一致させ、総数と表示番号は単一の定義（`NODE_ORDER`）
         から導出する MUST（手書きの定数を置かない）」へ改める（**T035 の前提**。放置すると
         FR-012 の完了時点で憲法違反が確定する）。
      3. **技術制約と品質基準**: 「実行条件は `.env` と `Config` から供給し」を「実行条件は `.env` と
         `Configuration`（唯一の実行時設定型）から供給し」へ読み替える（**T042 の前提**）。
         環境変数の一覧（`TR_*` / `XTR_*` / `YTR_*`）と「ハードコードしてはならない MUST NOT」は
         変えない。
      `/speckit.constitution` の手続き（Sync Impact Report / `Version` / `Last Amended` / History の
      追記）に従い、`Version` を PATCH（1.2.0 → 1.2.1）として更新する。
      **原則 I〜III・VI の文言は変更しない**。改正は US1〜US4 の実装完了後に行う（先に改正すると、
      残存分岐が実在する間は記述と実態が食い違う）。ただし T035 / T042 は**本タスクと同一の変更一式**
      として完了させる（憲法と実装を同時に green にし、片方だけを適用した状態を残さない）
- [ ] T066 後方互換シムの不在を確認する（FR-020 / 憲法 原則 VI）。`grep -rn "deprecated\|後方互換\|alias\|別名" src/` と
      `grep -rn "Config\b" src/ tests/` を実行し、旧名の別名・非推奨ラッパー・二重実装が 0 件で
      あることを確認する（`Configuration` は残ってよいが `Config` は 0 件）
- [ ] T067 削除の証跡を確定する（SC-005 / SC-008）。`contracts/removal-rationale.md` の
      REM-001〜REM-009 と実際の変更を突き合わせ、各項目の (a) 実行時の参照件数、(b) 削除理由、
      (c) 同一変更で更新した参照、(d) 更新／削除したテストが固定していた内容、を実測値で確定する。
      未記載の参照や未更新のテストがあればこのタスクで直す
- [ ] T068 一時ファイル・探針の後始末をする。`git status --short` で意図しないファイル
      （探針用の一時変更、`/tmp` 以外に残った作業ファイル、`tests/unit/golden_support.py` のような
      追加ヘルパ）が無いことを確認する。`tests/unit/golden/` の golden 6 ファイルだけが新規データとして残る
- [ ] T069 最終ゲートを通す。`uv run pytest -q`（カバレッジ `fail_under = 90` 以上。**実行時間
      60 秒の判定もこのコマンドで行う**。SC-010）、`uv run ruff check .`（0 件）、
      `uv run mypy src`（0 件）。3 つすべてが緑であることを「実装メモ」節に記録し、
      未達なら該当タスクへ戻る。併せて **FR-024（新しい実行時依存を追加しない）** を
      `git diff -- pyproject.toml` で確認し、`[project].dependencies` / `optional-dependencies` に
      差分が無いこと（`[dependency-groups]` / `uv.lock` の既存依存の解決差分は許容）を記録する
      （テスト・Lint・型検査では検出できないため独立に確認する）。
      **部分適用・`# noqa` の追加による回避は行わない**（憲法の品質ゲート）

---

## 実装メモ（実装中に記録する）

実装者はこの節に実測値を記入する（未記入のまま完了としない）。

### 1. 検出と変異探針の結果

| 項目 | 記録内容 | 実測 |
|---|---|---|
| 走査テストの検出（変更前） | 規則 (a)+(b) の行数と内訳 | （未記入。基準: 16 行） |
| 走査テストの検出（変更後） | 規則 (a)+(b) の行数と内訳 | （未記入。目標: 2 行） |
| 走査テストの検出（変更前） | 規則 (d) `help=` / `description=` の名前列挙 | （未記入。基準: `__main__.py` の `--platform` ヘルプ 1 件） |
| 走査テストの検出（変更後） | 規則 (d) / 規則 (e) | （未記入。目標: ともに 0 件） |
| T024 変異探針（走査） | `graph.py` に `_PLATFORM_HINT = "x"` を追加 → 赤 / 復元 → 緑 | （未記入） |
| T051 変異探針（ノードの env） | `nodes/search.py` に `os.getenv` を追加 → 赤 / 復元 → 緑 | （未記入） |
| T027 導出の非空虚性 | `NODE_ORDER` を差し替え → 出力が追随 | （未記入） |
| T053 引数の使用 | 実装前は「引数が無視される」ことで赤 | （未記入） |
| 規則 (d) の非空虚性 | `__main__.py` のヘルプに `"x"` を一時追加 → 赤 / 復元 → 緑（sha256 一致） | （未記入） |
| 規則 (e) の非空虚性 | `providers/__init__.py` に `_ALL: list[Provider] = []` を一時追加 → 赤 / 復元 → 緑 | （未記入） |

### 2. 基準値のずれ（spec は変更しない）

| 論点 | spec の記述 | 実測 | 対応 |
|---|---|---|---|
| プラットフォーム名の混入 | 15 箇所（文単位） | 走査で 16 行（`config.py` の引数既定値 1 件が集計外） | SC-002 の判定は終状態 2 行で行う（`plan.md` の「基準値のずれ」） |
| 設定の重複項目 | 7 項目 | 3 フィールド（`max_results` / `transcript_language` / `cache_dir`）＋ 引数 `platform` 1 | SC-003 の判定は「同名項目の定義箇所が 1 つ」の終状態で行う |
| レポート出力の一致（SC-006） | 「変更前と完全に一致」（Markdown と JSON の両方） | `render_json` は `report.model_dump_json` のため、FR-008 / FR-009 で削除する `use_trends` と `table_for` が JSON から消える | Markdown は byte 一致を維持。JSON は当該 2 キーのみ除外して比較し、**意図的な差分**として記録（RND-003 / REM-003 / REM-004） |
| `platform` の既定値（FR-007） | 既存フィールドの「型・**意味**」を変えてはならない MUST NOT | `ResearchInstruction.platform` / `Candidate.platform` の既定を `"x"` → `""` にする | FR-002 / SC-002 を満たすための必要な例外。空文字は登録の先頭（= `x`）として解決され**実行時の結果は同一**（`plan.md` の「設計上の解釈」）。golden は既定に依存させない（T004） |

### 3. golden の決定論（T007）

| 項目 | 記録内容 | 実測 |
|---|---|---|
| 2 回採取の一致 | `git status --short tests/unit/golden/` | （未記入） |
| 判定方法 | Markdown は byte 比較 / JSON は `use_trends` / `table_for` の 2 キーを両側で除去してから byte 比較 | （未記入） |
| 除外キーの正当性 | 除外は RND-003 の 2 キーのみ。他のキーの差は失敗として扱う | （未記入） |

### 4. 更新・削除したテスト（SC-008）

| テスト | 固定していた内容 | 処置 | REM |
|---|---|---|---|
| `tests/unit/test_cache.py` | JSON の往復 | `read_json` の節を削除 | REM-001 |
| `tests/unit/test_x_search.py` | 1 件取得時の本文連結 | `fetch_thread` の節を削除し、1 件ケースを `fetch_threads` へ移す | REM-005 |
| `tests/unit/test_config.py` | `TR_*` > `XTR_*`/`YTR_*` > 既定 | 対象を `Configuration.load` へ移行（期待値は維持） | REM-006 / REM-007 |
| `tests/unit/test_configuration.py` | `DEFAULTS` 8 キー | `use_trends` を削除 | REM-003 |
| `tests/unit/test_progress.py` | 進捗行の書式と `TOTAL` | 新シグネチャへ追随（書式の断言は維持） | REM-008 |
| `tests/unit/test_compile_report.py` | レポート本文 | 描画の断言を `test_rendering.py` へ移動 | REM-009 |
| `tests/integration/test_cli_contract.py` | `--trends` の受理 | 当該節を削除（他は維持） | REM-003 |
| `tests/integration/test_full_flow.py` | 進行・7 行・件数 | `Config` 依存のみ追随 | REM-006 / REM-007 |

### 5. 最終ゲート（T069）

| ゲート | 基準 | 実測 |
|---|---|---|
| `uv run pytest -q` | 全件 green・カバレッジ 90% 以上・**60 秒以内**（SC-010） | （未記入。基準 547 passed / 95.29% / 49.67 秒） |
| `uv run ruff check .` | 0 件 | （未記入） |
| `uv run mypy src` | 0 件 | （未記入） |
| `git diff -- pyproject.toml` | `[project].dependencies` / `optional-dependencies` に差分なし（FR-024） | （未記入） |

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**: 依存なし。`T001` が他タスクの前提（基準値の確認）
- **Foundational（Phase 2）**: Setup 完了後。**T006（golden 採取）は最初のコード変更より前が必須**。
  以降 US1〜US4 の全実装タスクは T006 の完了を前提にする（出力の不変を golden で検証するため）
- **User Story 1（Phase 3）**: Foundational 完了後。他のストーリーへの依存なし
- **User Story 2（Phase 4）**: Foundational 完了後。**US1 の完了後を推奨**（`configuration.py` /
  `models.py` / `state.py` / `__main__.py` / `nodes/*` を US1 と共有するため、並行すると衝突する）
- **User Story 3（Phase 5）**: **US1 と US2 の完了後**。`Config` クラス自体を削除するため、
  US1 の `env_prefix` 化（T018）と US2 の `use_trends` 削除（T032）が前提になる
- **User Story 4（Phase 6）**: Foundational 完了後に着手可能（golden があるため）。
  ただし推奨は US1 の完了後（US1 が `compile_report.py` の分岐をフックへ置き換えるため、
  先に US4 を進めると同じファイルを 2 回大きく動かすことになる）
- **Polish（Phase 7）**: すべてのストーリーの完了後。`T065`（憲法の PATCH 改正）は**実装の完了後**に行う
  （先に改正すると、残存分岐が実在する間は改正後の記述が実態と食い違う）。ただし **T035（`TOTAL` 削除）
  と T042（`Config` 削除）は T065 と同一の変更一式**として完了させる（憲法 原則 V と技術制約が
  それぞれ `ProgressEmitter.TOTAL` と `Config` の維持を前提にしているため、片方だけを適用した
  状態は憲法違反になる）

### クリティカルパス

```
T001 → T004 → T005 → T006 → T007
  → T008/T009 → T011 → T012/T013 → T014〜T022 → T023 → T024 → T025 → T026
  → T027/T028 → T030〜T036 → T037
  → T038/T039 → T041 → T042/T043/T044 → T045〜T049 → T050 → T051
  → T052〜T054 → T056 → T057〜T060 → T061 → T062
  → T063〜T068 → T069
```

### ストーリー間の依存（実装上の共有ファイル）

| ファイル | US1 | US2 | US3 | US4 |
|---|---|---|---|---|
| `configuration.py` | 既定値の変更 | `use_trends` 削除 | `load` / `resolve_env` 追加 | — |
| `models.py` | `platform` 既定の変更 | `use_trends` / `table_for` 削除 | — | — |
| `state.py` | `Literal` → `str` | `use_trends` 削除 | — | — |
| `__main__.py` | 名詞のフック化 | `--trends` 削除 | `Configuration.load` へ移行 | 描画の入口変更 |
| `nodes/*.py` | 分岐のフック化 | `emit` の引数削除 | `Config.load` 削除 | `compile_report` の整形移設 |
| `compile_report.py` | 分岐のフック化 | `emit` の引数削除 | — | 整形の移設 |

**共有ファイルが多いため、US1 → US2 → US3 は順に実施する**（並行実行は同一ファイルの衝突を招く）。
US4 は Foundational 完了後であれば US1 と並行可能だが、`compile_report.py` を共有するため
US1 の完了後を推奨する。

### Within Each User Story

- テストを先に書き、**赤を確認**してから実装する（憲法 原則 I）
- モデル・型 → サービス（provider / ノード）→ 入口（CLI）の順
- 各ストーリーのチェックポイントで `uv run pytest -q` を通す
- リファクタリングは旧経路を完全に削除する（互換シムを残さない。憲法 原則 VI）

### Parallel Opportunities

- `T002` / `T003`（Setup の実測）
- `T008` / `T009`（US1 の新規テスト 2 本は別ファイル）
- `T012` / `T013`（`providers/x.py` と `providers/youtube.py`）
- `T027` / `T028`（US2 のテスト）
- `T031` / `T033`（`prompts.py` と `models.py`）
- `T038` / `T039`（US3 のテスト）
- `T043` / `T044`（provider の実装）
- `T048` / `T049`（`__init__.py` と `tools/llm.py`）
- `T052` / `T053` / `T054`（US4 の新規テスト。同一ファイル内だが関数単位で独立）
- `T063` / `T064`（`README.md` と quickstart の実行）

---

## Parallel Example: User Story 1

```bash
# US1 のテスト 2 本を並行して書く:
Task: "Create tests/unit/test_platform_scan.py (AST 走査・許容リスト方式)"
Task: "Create tests/unit/test_platform_extension.py (試験用プラットフォームの完走)"

# US1 の provider 実装を並行して進める:
Task: "Implement hooks in src/trend_researcher/providers/x.py"
Task: "Implement hooks in src/trend_researcher/providers/youtube.py"
```

---

## Implementation Strategy

### MVP First（User Story 1 のみ）

1. Phase 1（Setup）を完了する
2. Phase 2（Foundational）を完了する（**golden の採取が必須**）
3. Phase 3（US1）を完了する
4. **STOP and VALIDATE**: 走査テスト（2 行）と拡張テスト（完走）を単独で確認する
5. ここで「新しいプラットフォームをコア変更なしで追加できる」という本機能の目的が達成される

### Incremental Delivery

1. Setup + Foundational → 安全網（基準値・golden）が揃う
2. US1 → 検証 → **MVP**（拡張性の確立）
3. US2 → 検証 → 読むべき範囲が狭まる（不要物と重複の除去）
4. US3 → 検証 → 設定の出所が 1 つになる
5. US4 → 検証 → 描画が独立して検証できる
6. 各段階で golden・CLI 契約・走査テストが緑のままであることを確認する（前の段階を壊さない）

### 注意事項

- `[P]` は「別ファイル・未完タスクへの依存なし」を表す。同一ファイルを触るタスクには付けない
- 各チェックポイントで `uv run pytest -q`（カバレッジ計測込み）を通し、547 passed から落ちていないこととカバレッジ 90% 以上を確認する
- コミットはストーリー単位、または論理的なまとまりごとに行う
- 避けること: 曖昧なタスク、同一ファイルの同時編集、ストーリーの独立性を壊す依存
