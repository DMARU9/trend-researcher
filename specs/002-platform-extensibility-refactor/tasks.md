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

- [X] T001 `plan.md` の「基準値のずれ」と Constitution Check に記録した基準値（547 passed /
      カバレッジ 95.29% / `ruff` 0 件 / `mypy` 0 件 / 49.67 秒）を、ブランチ
      `002-platform-extensibility-refactor` の作業ツリーで `uv run pytest -q`、
      `uv run ruff check .`、`uv run mypy src` により再現し、作業ツリーが clean であることを
      `git status --short` で確認する（記録先: `specs/002-platform-extensibility-refactor/tasks.md`
      の「実装メモ」節）
- [X] T002 [P] 遅いテストを把握して時間予算を確保する。`uv run pytest -q --no-cov --durations=15` を実行し、
      上位 15 件の所要時間を「実装メモ」節に控える（SC-010 の 60 秒以内を守るため、追加する 3 テストの
      上限を決める根拠にする）
- [X] T003 [P] オフライン制約を実測する。`env -u OPENAI_API_KEY -u XTR_ACCOUNTS_DB -u YTR_ACCOUNTS_DB
      uv run pytest -q --no-cov` を実行し、認証情報なしでも 547 passed のままであることを確認する
      （FR-023 の基準。ここで赤が出る場合は既存テストの問題として記録し、本機能では触らない）

---

## Phase 2: Foundational（全ストーリーの前提・ブロッキング）

**Purpose**: 出力一致（SC-006）の golden を**変更前のツリー**から採取し、US1〜US4 を通じて
出力の不変を継続的に検証できる状態にする。**golden は変更後に採ると自己言及的なテストになり無効**なため、
必ずこのフェーズ（最初のコード変更より前）で行う。

**⚠️ CRITICAL**: このフェーズが完了するまで US1〜US4 のどの実装タスクも開始しない。

- [X] T004 `tests/unit/test_rendering.py` を作成し、golden の入力を作る関数
      `build_golden_cases() -> dict[str, tuple[ResearchReport, Provider]]` のみを書く。
      キーは `x_full`（X・完全形）/ `youtube_full`（YouTube・完全形）/ `sparse`（文脈・分析・
      共通テーマが空）の 3 件。`ResearchReport` / `ResearchInstruction` / `Candidate` /
      `AnalysisFinding` / `CommonTheme` を直接組み立て、LLM・LangGraph・境界モックを使わない。
      **3 件すべてで既定値に依存する値を明示する**（`platform` / `output.format` など。
      US1 で `platform` の既定が `"x"` → `""` に変わるため、既定に依存すると golden が
      意図せず変化する）。この時点では描画関数を import しない（`_render_*` の対象が見えないようにするため）
- [X] T005 `tests/unit/test_rendering.py` に、golden ファイルと byte 比較する検証を追加する。
      比較対象は `tests/unit/golden/{x_full,youtube_full,sparse}.{md,json}`。
      **変更前の所在である `from trend_researcher.nodes.compile_report import render_json, render_markdown`
      を import する**（US4 の T052 で `trend_researcher.rendering` へ切り替える）。
      このタスクは T004 と T006 の後に行い、golden が無い状態では赤になることを確認する
- [X] T006 `quickstart.md` の手順 4-1 のコマンドを実行し、**変更前のツリー**から
      `tests/unit/golden/` の 6 ファイル（3 入力 × md/json）を採取する。採取後、`uv run pytest
      tests/unit/test_rendering.py -q` が緑になることを確認する
- [X] T007 決定論を確認する。T006 の採取をもう一度実行して `git status --short tests/unit/golden/`
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

- [X] T008 [P] [US1] `tests/unit/test_platform_scan.py` を作成する。AST 走査の検出器を実装し、
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
- [X] T009 [P] [US1] `tests/unit/test_platform_extension.py` を作成する。`Provider` Protocol を満たす
      試験用プラットフォーム（`name="dummy"` など、`env_prefix` を含む追加フック 5 つを実装）を
      `register_provider()` で登録し、境界（`search` / `fetch_contexts` / LLM）をテスト内のフェイクで
      置き換えて `build_graph()` のパイプラインを完走させる。検証は「`report` が生成される」
      「進捗が 7 行」「レポートに試験用プラットフォームの `content_noun` /
      `candidates_section_title` / `selection_note` が反映される」の 3 点。
      **後始末で登録を解除し、他のテストへ影響を残さない**（フィクスチャの `finally` で行う）。
      実装前はフックが存在しないため**赤**になることを確認する
- [X] T010 [US1] T008 / T009 が**期待どおりの理由で**赤であることを確認し、「実装メモ」節に記録する
      （T008 は「16 行検出」、T009 は「`register_provider` が無い」または「フックが無い」）

### Implementation for User Story 1

- [X] T011 [US1] `src/trend_researcher/providers/base.py` の `Provider` Protocol に追加フック 5 つを
      定義する（`env_prefix: str` / `max_search_queries: int | None` / `content_noun: str` /
      `candidates_section_title: str` / `selection_note(self, sort_by: str) -> str`）。
      docstring に「コアは値を解釈しない（差の表現のみを担う）」旨を記す。既存 13 メンバは変更しない
- [X] T012 [P] [US1] `src/trend_researcher/providers/x.py` にフックを実装する。
      `env_prefix = "XTR"`、`max_search_queries = 8`、`content_noun = "ツイート"`、
      `candidates_section_title = "## 選定ツイートリスト（上位 N 件）"`、
      `selection_note(sort_by)`（`sort_by == "likes"` なら「いいね数の多い順」、それ以外は
      「いいね数の少ない順」を使った `nodes/compile_report.py:37` と同じ文）
- [X] T013 [P] [US1] `src/trend_researcher/providers/youtube.py` にフックを実装する。
      `env_prefix = "YTR"`、`max_search_queries = None`、`content_noun = "動画"`、
      `candidates_section_title = "## 選定動画リスト（関連度順上位 N 件）"`、
      `selection_note(sort_by)` は `sort_by` を使わず「検索結果の関連度順に上位 N 件を採用」
      （現行 `compile_report.py:41` と同じ文）
- [X] T014 [US1] `src/trend_researcher/providers/__init__.py` に `register_provider(cls)` を追加し、
      `get_provider()` のエラー文言を登録キーから生成する（プラットフォーム名のリテラルを含めない）。
      **空文字・空白のみの名前は登録辞書の先頭のプラットフォームとして解決する**
      （`Configuration.platform` の既定を空文字にするため。research.md R-8 / EXT-007）。
      `available_platforms()` は現行どおり登録順のキー一覧を返す
- [X] T015 [US1] `src/trend_researcher/state.py` の `platform` 2 箇所（`AgentInputState` /
      `AgentState`）を `Literal["x", "youtube"]` から `str` へ変更する（FR-002）。
      `Literal` の import が不要になれば削除する
- [X] T016 [US1] `src/trend_researcher/models.py` の `platform` 2 箇所
      （`ResearchInstruction` / `Candidate`）の既定を `"x"` から `""` へ変更する（FR-002）。
      docstring に「空文字は登録済みプラットフォームの先頭として解決される」旨を追記する
- [X] T017 [US1] `src/trend_researcher/configuration.py` の `platform` の既定を `"x"` から `""` へ変更し、
      `description` を「対象プラットフォーム（未指定時は既定のプラットフォーム）」に更新する
      （FR-002。フィールドの追加・削除はしない）
- [X] T018 [US1] `src/trend_researcher/config.py` の `Config.load()` の引数 `platform: str = "x"` を
      `env_prefix: str | None = None` に置き換え、`prefix = "XTR" if platform == "x" else "YTR"` の行を
      **削除**して `env_prefix` をそのまま使う（`env_prefix` が `None` のときは `TR_*` のみを見る）。
      併せて呼び出し側（`src/trend_researcher/__main__.py`、`src/trend_researcher/nodes/search.py`、
      `src/trend_researcher/nodes/fetch.py`）を `get_provider(platform).env_prefix` を渡す形へ変更する。
      **注意**: `Config` クラス自体の削除は US3（T046）であり、ここでは引数の形だけを変える
- [X] T019 [US1] `src/trend_researcher/tools/llm.py` の `build_model(role="research", env_prefix: str | None = None)`
      へ変更し、`TR_MODEL` → `{env_prefix}_MODEL` → 既定（`openai:mimo-v2.5`）の順にする
      （`XTR_MODEL` / `YTR_MODEL` の直列を排除）。呼び出し側
      （`nodes/parse_instruction.py` / `nodes/plan_search.py` / `nodes/analyze_content.py` /
      `nodes/extract_common.py`）で `provider.env_prefix` を渡すようにする
- [X] T020 [US1] `src/trend_researcher/nodes/plan_search.py` の
      `platform = (instruction.platform or "x").lower()` と
      `if platform == "x" and len(queries) > 8:` を、`provider.max_search_queries` による上限適用へ
      置き換える（`None` は無制限）。既存コメント（X のみ適用・YouTube は単一クエリ）を残しつつ、
      プラットフォーム名を書かない形に書き直す
- [X] T021 [US1] `src/trend_researcher/nodes/compile_report.py` の分岐 3 箇所
      （`:37` 選定基準の注記 / `:45` の名詞 / `:85` の表題）を provider のフック
      （`selection_note` / `content_noun` / `candidates_section_title`）へ置き換える。
      **出力文字列は 1 文字も変えない**（golden で検証される）
- [X] T022 [US1] `src/trend_researcher/__main__.py` の
      `subject = "ツイート" if platform == "x" else "動画"` を `get_provider(platform).content_noun` に
      置き換える。`get_provider` は `try` の外（引数検証済みの位置）で 1 回だけ解決する。
      併せて `--platform` のヘルプ本文にあるプラットフォーム名の列挙
      （`"対象プラットフォーム（x=X/Twitter、youtube=YouTube）"`）を削除し、利用可能な値の提示は
      `choices=available_platforms()` に委ねる（登録の追加だけでヘルプが正しくなる状態にする。
      T008 の検出規則 (d) を 0 件にする）。`--help` の終了コードと出力先の契約は変えない
      （`tests/integration/test_cli_contract.py` が終了コードのみを固定していることは実測済み）
- [X] T023 [US1] `uv run pytest tests/unit/test_platform_scan.py -q` を実行し、**規則 (a)+(b) の検出が
      2 行**（許容リストのみ）になり、**規則 (d) が 0 件**（T022 のヘルプ汎用化で解消）・
      **規則 (e) が 0 件**であることを確認する。「実装メモ」節に検出結果の内訳
      （(a)+(b): 16 → 2、(d): 1 → 0、(e): 0 → 0）を記録する
- [X] T024 [US1] 走査テストの**非空虚性**を変異探針で確認する。(1) `src/trend_researcher/graph.py` に
      一時的に `_PLATFORM_HINT = "x"` の行を追加 → `uv run pytest tests/unit/test_platform_scan.py -q`
      が**赤**になる、(2) `src/trend_researcher/__main__.py` の `--platform` のヘルプに `"x"` を
      一時的に含める → 規則 (d) が**赤**になる、(3) `src/trend_researcher/providers/__init__.py` に
      一時的に `_ALL: list[Provider] = []` を追加 → 規則 (e) が**赤**になる。
      各探針は `git checkout -- <file>` で復元し、**復元後に 3 つとも緑に戻る**ことを確認する。
      さらに復元後の sha256 が探針前と一致することを確かめる（`sha256sum` で比較）。
      結果（赤のログの要点）を「実装メモ」節に記録する
- [X] T025 [US1] 影響を受ける既存テストを追随させる。`tests/unit/test_config.py`
      （`Config.load(platform=...)` → `env_prefix=...`。**期待値は変えず、`XTR_*` / `YTR_*` の
      解決結果の断言を維持する**）、`tests/unit/test_providers.py`（追加フックの存在）、
      `tests/unit/test_plan_search.py`（上限が provider 由来になったこと）、
      `tests/unit/test_compile_report.py`（出力文字列が不変であること）。
      追随で消える網羅があれば、同等の入力を残して補う
- [X] T026 [US1] `uv run pytest -q` を実行して全件緑を確認する。併せて `quickstart.md` 手順 3 の
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

- [X] T027 [P] [US2] `tests/unit/test_progress.py` を新しい形へ書き換える。検証内容:
      (a) `emit(node_name, phase, detail)` の 1 引数化に伴い、表示番号が
      `NODE_ORDER.index(node_name) + 1`、総数が `len(NODE_ORDER)` になること、
      (b) 進捗行の書式 `[i/total] name ... phase（detail）` が現行と一致すること、
      (c) 未登録のノード名は `ValueError` になること、
      (d) **導出の非空虚性**: `monkeypatch.setattr(progress, "NODE_ORDER", [...])` で順序・件数を
      変えると出力が追随すること（手書きの番号に戻したら落ちるテストにする）
- [X] T028 [US2] 削除対象の不在を固定する。既存テストに次の断言を追加する:
      `tests/unit/test_cache.py`（`hasattr(cache, "read_json")` が偽）、
      `tests/unit/test_models.py`（`OutputSpec` に `table_for` が無い）、
      `tests/unit/test_x_search.py`（`hasattr(x_search, "fetch_thread")` が偽）、
      `tests/unit/test_providers.py` または `tests/unit/test_parse_instruction.py`
      （`Configuration.model_fields` / `ResearchInstruction.model_fields` / `AgentState.__annotations__`
      に `use_trends` が無い）。実装前は赤になることを確認する
- [X] T029 [US2] T027 / T028 が期待どおり赤であることを確認し、「実装メモ」節に記録する

### Implementation for User Story 2

- [X] T030 [US2] `src/trend_researcher/cache.py` から `read_json` を削除し、docstring の
      「将来の途中再開等に備えて用意」の記述を削除する。`write_json` は変更しない（REM-001）
- [X] T031 [P] [US2] `src/trend_researcher/prompts.py` から `COMPILE_REPORT_PROMPT` を削除する
      （REM-002。他のプロンプト本文は変更しない）
- [X] T032 [US2] `--trends` 一式を削除する（REM-003）:
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
- [X] T033 [P] [US2] `src/trend_researcher/models.py` から `OutputSpec.table_for` を削除する
      （REM-004）
- [X] T034 [US2] `src/trend_researcher/tools/x_search.py` から `fetch_thread` を削除する（REM-005）。
      **失われる網羅を補う**: `fetch_threads` のテストに「1 件だけ返る場合」のケースを追加し、
      本文の連結が同じ経路で検証されるようにする
- [X] T035 [US2] `src/trend_researcher/progress.py` を単一の定義へ変更する（FR-012 / REM-008）。
      `emit(self, node_name: str, phase: str, detail: str = "")` にし、
      `index = NODE_ORDER.index(node_name) + 1` を計算して行を組み立てる。総数は `self.total`
      （`ProgressEmitter.__init__` の既定値）を使い、既定値の算出元を `len(NODE_ORDER)` にする。
      `ProgressEmitter.TOTAL = 7` は削除し、`total` の上書き（テスト用）は引き続き可能にする。
      **進捗行の文字列は 1 文字も変えない**。
      **注意**: 憲法 原則 V が `ProgressEmitter.TOTAL` の維持を MUST としているため、T065 と
      **同一の変更一式**として完了させる（片方だけを適用した状態は憲法違反になる。C1）
- [X] T036 [US2] 7 ノードの `emitter.emit(...)` 呼び出しから数値の番号引数を削除する
      （`nodes/parse_instruction.py` / `nodes/plan_search.py` / `nodes/search.py` /
      `nodes/fetch.py` / `nodes/analyze_content.py` / `nodes/extract_common.py` /
      `nodes/compile_report.py`）
- [X] T037 [US2] `uv run pytest -q` を実行し、削除に伴う赤を解消する。
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

- [X] T038 [P] [US3] `tests/unit/test_platform_scan.py` に
      `test_nodes_do_not_read_environment` を追加する（SET-004 / SC-004）。`src/trend_researcher/nodes/**`
      を AST 走査し、`os.getenv` / `os.environ` / `load_dotenv` / `Config.load` の呼び出しが
      **0 件**であることを確認する。実装前は 2 件（`nodes/search.py` / `nodes/fetch.py`）で**赤**
      になることを確認する
- [X] T039 [P] [US3] `tests/unit/test_config.py` を `Configuration.load()` /
      `resolve_env(..., env_prefix=...)` の経路へ移行する。**期待値（どの変数がどの値になるか）は
      変更前と同一に保つ**。追加する検証: `Configuration.load(env_prefix="XTR")` が
      `TR_MAX_RESULTS` > `XTR_MAX_RESULTS` > 既定 5 の順で解決すること、
      明示指定（`Configuration(max_results=30)` を渡した `model_fields_set`）が環境変数より優先されること、
      `get_config` / `cache_clear` を固定していた節は削除すること。
      **T025 で `env_prefix=` に移した箇所を、本タスクで `Configuration.load()` の経路へ再度移す**
      （期待値は変えない。2 段階に分かれるのは US1 では `Config` がまだ存在するため）。
      実装前は import エラーで**赤**になることを確認する
- [X] T040 [US3] T038 / T039 が期待どおり赤であることを確認し、「実装メモ」節に記録する

### Implementation for User Story 3

- [X] T041 [US3] `src/trend_researcher/configuration.py` に
      `resolve_env(name, *, default, env_prefix=None) -> str`（`TR_{name}` → `{env_prefix}_{name}` →
      既定。空文字は未設定扱い）と `Configuration.load(env_prefix: str | None = None) -> Configuration`
      を追加する。`.env` の読み込み（`load_dotenv`）とパス解決（`config.py` の `_REPO_ROOT` /
      `_resolve_path` を再利用）もこの経路で 1 回だけ行う。`Configuration` に**フィールドを追加しない**
- [X] T042 [US3] `src/trend_researcher/config.py` から `Config` クラスと `get_config()` を削除する
      （REM-006 / REM-007）。残すのは `_REPO_ROOT` / `_resolve_path` / `_load_env_once`（または
      `configuration.py` へ移したうえでモジュールごと削除）。`lru_cache` の使用をやめる。
      **`src/` から `Config` / `get_config` の参照を 0 にする**。
      **注意**: 憲法の「技術制約と品質基準」が実行条件の供給元を `Config` と明記しているため、
      T065 と**同一の変更一式**として完了させる（片方だけを適用した状態は憲法違反になる。C2）
- [X] T043 [P] [US3] `src/trend_researcher/providers/x.py` に固有設定の解決を実装する（FR-003 / SET-003）。
      `@dataclass(frozen=True) class XSettings`（`accounts_db: Path` / `search_pool_size: int` /
      `max_retries: int`）と `XProvider.settings(configuration: Configuration) -> XSettings` を追加し、
      `resolve_env(..., env_prefix=self.env_prefix)` で解決する。`configuration.model_fields_set` に
      含まれる値は環境変数より優先する。`search` / `fetch_contexts` の引数型を `Config` から
      `Configuration` へ変更し、内部で `self.settings(configuration)` を使う。
      `providers/__init__.py` の `_PROVIDERS` の 2 行は**変更しない**（走査の許容リスト）
- [X] T044 [P] [US3] `src/trend_researcher/providers/youtube.py` と
      `src/trend_researcher/providers/base.py` の `config: Config` を
      `configuration: Configuration` へ変更する（YouTube は固有設定を持たないため、共通値を
      `Configuration` から読む）
- [X] T045 [US3] `src/trend_researcher/nodes/search.py` から `cfg = Config.load(platform=platform)` を
      削除し、`provider.search(..., configuration=configurable)` の形へ変更する。`max_results` の
      解決（`instruction.max_results or 5`）と既存コメント（FR-011 の優先順位）は**変更しない**。
      **ノードは `Configuration` を渡すだけで、`provider.settings(configuration)` は呼ばない**
      （固有設定の解決は provider の内部。ノードが設定型を知る範囲を広げない。data-model.md 2 節）
- [X] T046 [US3] `src/trend_researcher/nodes/fetch.py` から `cfg = Config.load(platform=platform)` を
      削除し、`provider.fetch_contexts(candidates, configurable)` の形へ変更する。
      `settings()` の呼び出しは provider の内部に閉じる（T045 と同じ方針）
- [X] T047 [US3] `src/trend_researcher/__main__.py` を `Configuration.load(env_prefix=provider.env_prefix)`
      の経路へ変更する（`Config` の import と `Config.load(...)` を削除）。`--cache-dir` /
      `--max-results` の明示指定は `Configuration` のフィールドとして与え、`RunnableConfig` に載せる
      （SET-006 の優先順位を維持）。**`config` を参照する残り 2 箇所も同時に置換する**:
      `lang = args.lang or config.transcript_language`（字幕言語。`--lang` を維持）と
      `requested = report.instruction.max_results or config.max_results`（件数の表示）。
      `Config` の削除後に `config.` 参照が **0 件**になることを `grep -n 'config\.' src/trend_researcher/__main__.py`
      で確認する（`__main__.py` はカバレッジ 46% でテストの網が薄いため実測で確かめる）
- [X] T048 [P] [US3] `src/trend_researcher/__init__.py` の `Config` re-export を削除する
      （`__all__` の更新を含む）。`Configuration` と `render_report` の re-export は維持する
- [X] T049 [P] [US3] `src/trend_researcher/tools/llm.py` の環境変数解決を `resolve_env` に寄せる
      （`build_model(role, env_prefix)` の内部で `resolve_env("MODEL", default="openai:mimo-v2.5",
      env_prefix=env_prefix)` を使う）。`TR_MODEL` → `{env_prefix}_MODEL` → 既定の順を変えない
- [X] T050 [US3] `tests/integration/test_full_flow.py` の `Config` / `get_config` / `cache_clear` の
      参照を `Configuration` へ追随させる（**進行・件数・出力の断言は変更しない**）。
      `tests/unit/test_configuration.py` の `DEFAULTS` から `use_trends` を除き、`load()` の解決規則の
      節を追加する
- [X] T051 [US3] `uv run pytest -q` で全件緑を確認し、`quickstart.md` の手順 6（設定型が 1 つ /
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

- [X] T052 [P] [US4] `tests/unit/test_rendering.py` の import を
      `trend_researcher.nodes.compile_report` から `trend_researcher.rendering` へ切り替える。
      この時点で**赤**（モジュールが無い）になることを確認する。golden の比較内容は変更しない
- [X] T053 [P] [US4] `tests/unit/test_rendering.py` に
      `test_markdown_uses_passed_provider` を追加する（FR-017 / RND-007）。
      X の `ResearchReport` と **YouTube の provider** の組で `render_markdown(report, provider)` を呼び、
      出力の名詞・表題・注記が**渡された YouTube の provider** のものになることを断言する。
      現行実装は引数を無視して `report.instruction.platform` から解決し直すため、このテストは
      **実装前は赤**になる（= 欠陥を実際に検出するテストであることの確認を兼ねる）
- [X] T054 [P] [US4] `tests/unit/test_rendering.py` に
      `test_graph_does_not_reference_rendering` を追加する（FR-016）。`src/trend_researcher/graph.py` を
      AST 走査し、`rendering` の import・参照が 0 件であることと、
      `render_report` / `render_markdown` / `render_json` の名前が現れないことを確認する。
      実装前は**赤**になることを確認する
- [X] T055 [US4] T052 / T053 / T054 が期待どおり赤であることを確認し、「実装メモ」節に記録する
      （T053 は「引数が無視されている」という**現行の不具合**を示す赤であることを明記する）

### Implementation for User Story 4

- [X] T056 [US4] `src/trend_researcher/rendering.py` を新規作成し、
      `src/trend_researcher/nodes/compile_report.py` から
      `render_markdown` / `render_json` / `render_report` / `_render_candidates_table` /
      `_render_analysis_block` / `_render_common_themes` を**移動**する（コピーではない）。
      変更点は 2 つだけ: (a) `render_markdown` の先頭にある
      `provider = get_provider(report.instruction.platform)` を削除して**引数の provider を使う**、
      (b) `render_report(report, provider)` を置き、`format == "json"` なら `render_json(report)` を
      呼ぶ。**出力文字列は 1 文字も変えない**。`render_json(report)` の署名は変更しない
- [X] T057 [US4] `src/trend_researcher/nodes/compile_report.py` から移動済みの関数を削除し、
      `from trend_researcher.rendering import render_markdown` を使って
      `rendered = render_markdown(report, provider)` を呼ぶ形にする。ノードの責務
      （`report` の組み立て / `cache.write_json` / 進捗 / メッセージ）は変更しない（RND-005）
- [X] T058 [US4] `src/trend_researcher/graph.py` から描画関連の import と `render_report` を削除する。
      残すのは `build_graph()` / `_route_after_search` / `trend_researcher` / `EXECUTION_TIMEOUT`
      （FR-016 / RND-001）
- [X] T059 [US4] `src/trend_researcher/__main__.py` で `render_report` を
      `trend_researcher.rendering` から import し、`render_report(report, provider)` を呼ぶようにする。
      `provider` は `main()` で 1 回だけ解決して再利用する（描画の内部で解決し直さない）
- [X] T060 [P] [US4] `src/trend_researcher/__init__.py` の `render_report` の re-export 元を
      `rendering.py` へ変更する（`__all__` は維持）
- [X] T061 [US4] `tests/unit/test_compile_report.py` の描画の断言を `tests/unit/test_rendering.py` へ
      移し、ノード側には「`report` が状態に入る」「`cache.write_json` が呼ばれる」「描画が
      呼ばれる（メッセージ本文にレポートが含まれる）」を残す。**観測可能な断言は削除しない**
      （移動である。REM-009 / SC-008）
- [X] T062 [US4] `uv run pytest tests/unit/test_rendering.py -q` を実行し、golden 3 件が
      **byte 一致**であること、T053 / T054 が緑であることを確認する。
      比較は **Markdown は完全一致、JSON は `use_trends` / `table_for` の 2 キーのみ除外**（RND-003。
      FR-008 / FR-009 の削除に伴う意図的な差分。`removal-rationale.md` REM-003 / REM-004）。
      それ以外の差が出た場合は**実装を直す**（golden を書き換えない）。その後 `uv run pytest -q` で全件緑を確認する

**Checkpoint**: 全 4 ストーリーが独立に検証可能な状態。描画はノード実行なしで検証でき、
骨格は描画を参照しない。

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 仕様・文書・ゲートの最終確認。

- [X] T063 [P] `README.md` を更新する。`--trends` の記載を削除し、環境変数を `TR_*`（共通）/
      `XTR_*`（X 固有）/ `YTR_*`（YouTube 固有）の 3 群で整理する。`--platform` の説明は変更しない
- [X] T064 [P] `specs/002-platform-extensibility-refactor/quickstart.md` の手順 1〜7 を通しで実行し、
      各手順の実測値を「実装メモ」節に記録する（とくに手順 2 の検出 2 行、手順 3 の完走、
      手順 4 の byte 一致、手順 7 の 3 ゲートと実行時間）
- [X] T065 憲法の文言を PATCH 改正する（research.md R-12 / plan.md の Constitution Check に
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
- [X] T066 後方互換シムの不在を確認する（FR-020 / 憲法 原則 VI）。`grep -rn "deprecated\|後方互換\|alias\|別名" src/` と
      `grep -rn "Config\b" src/ tests/` を実行し、旧名の別名・非推奨ラッパー・二重実装が 0 件で
      あることを確認する（`Configuration` は残ってよいが `Config` は 0 件）
- [X] T067 削除の証跡を確定する（SC-005 / SC-008）。`contracts/removal-rationale.md` の
      REM-001〜REM-009 と実際の変更を突き合わせ、各項目の (a) 実行時の参照件数、(b) 削除理由、
      (c) 同一変更で更新した参照、(d) 更新／削除したテストが固定していた内容、を実測値で確定する。
      未記載の参照や未更新のテストがあればこのタスクで直す
- [X] T068 一時ファイル・探針の後始末をする。`git status --short` で意図しないファイル
      （探針用の一時変更、`/tmp` 以外に残った作業ファイル、`tests/unit/golden_support.py` のような
      追加ヘルパ）が無いことを確認する。`tests/unit/golden/` の golden 6 ファイルだけが新規データとして残る
- [X] T069 最終ゲートを通す。`uv run pytest -q`（カバレッジ `fail_under = 90` 以上。**実行時間
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

### 0. 基準値（T001〜T003）

| 項目 | 実測（2026-09-13、ブランチ `specs/002-platform-extensibility-refactor`） |
|---|---|
| `uv run pytest -q` | **547 passed / カバレッジ 95.29% / 49.79 秒**（`fail_under = 90` を満たす） |
| `uv run ruff check .` | `All checks passed!`（0 件） |
| `uv run mypy src` | `Success: no issues found in 26 source files` |
| `git status --short` | 空（作業ツリー clean） |
| 遅いテスト上位（T002） | `--no-cov --durations=15` の実測は下欄「T002」に記載 |
| オフライン制約（T003） | 認証情報を外しても 547 passed（下欄「T003」に記載） |

#### T002: 遅いテスト上位 15 件（`uv run pytest -q --no-cov --durations=15`）

```
1.55s  test_cli_contract.py::test_cli_002_07_output_matches_stdout_rendering
0.86s  test_cli_contract.py::test_cli_001_06_help_exits_zero
0.84s  test_cli_contract.py::test_cli_002_05_002_03_stderr_only_for_diagnostics[error]
0.83s  test_cli_contract.py::test_cli_001_10_unknown_platform
0.82s  test_cli_contract.py::test_cli_002_05_information_messages_go_to_stderr
0.82s  test_cli_contract.py::test_cli_001_17_blank_instruction[spaces]
0.81s  test_cli_contract.py::test_cli_001_13_invalid_since
0.81s  test_cli_contract.py::test_cli_004_05_sources_are_listed[youtube]
0.81s  test_cli_contract.py::test_cli_005_enums_are_case_sensitive[sort-capitalized]
0.81s  test_cli_contract.py::test_cli_003_05_json_has_no_markdown_headings
0.81s  test_graph_wiring.py::test_success_path_progress_line_count
0.80s  test_graph_wiring.py::test_success_path_runs_all_nodes
0.80s  test_cli_contract.py::test_cli_001_04_output_json_file
0.80s  test_cli_contract.py::test_cli_001_01_x_likes_sort_records_criterion
0.80s  test_graph_wiring.py::test_zero_candidate_progress_line_count
547 passed in 47.94s
```

**時間予算の判断**: 遅いテストはすべて `tests/integration/` の subprocess 起動テスト（各 0.8〜1.55 秒）で、
`tests/unit/` の最上位は 15 件に入っていない。新規 3 テスト（走査・拡張・golden）はいずれも
`tests/unit/` のプロセス内テストであり、golden 比較は描画のみ（RND-007: 1 秒未満）で、
拡張テストも既存の境界モック 1 回に留まる。増加見込みは 1〜2 秒で、
`uv run pytest -q` の上限 60 秒（基準 49.79 秒）に対する余地 約 10 秒に収まる。

#### T003: オフライン制約（`env -u OPENAI_API_KEY -u XTR_ACCOUNTS_DB -u YTR_ACCOUNTS_DB uv run pytest -q --no-cov`）

```
547 passed in 47.94s
```

認証情報（`OPENAI_API_KEY` / アカウント DB）を外しても 547 passed のまま。既存テストは
外部 SDK をすべてモックしており、FR-023 の基準を満たす。修正は不要。

### 1. 検出と変異探針の結果

| 項目 | 記録内容 | 実測 |
|---|---|---|
| 走査テストの検出（変更前） | 規則 (a)+(b) の行数と内訳 | **16 行**（`__main__.py` 1 / `config.py` 2 / `configuration.py` 1 / `models.py` 2 / `nodes/compile_report.py` 3 / `nodes/plan_search.py` 2 / `providers/__init__.py` 2 / `state.py` 2 / `tools/llm.py` 1）。許容リストは `_PROVIDERS` の登録 2 行 → **違反 14 行で赤**（T008 実測） |
| 走査テストの検出（変更後） | 規則 (a)+(b) の行数と内訳 | **2 行**（`providers/__init__.py:12` `"x": XProvider,` / `:13` `"youtube": YouTubeProvider,` = 許容リストそのもの）→ **違反 0 件で緑**（T023 実測） |
| 走査テストの検出（変更前） | 規則 (d) `help=` / `description=` の名前列挙 | **1 件**（`__main__.py:32` の `--platform` ヘルプ）で赤。規則 (e) は 0 件（回帰ガード、緑） |
| 走査テストの検出（変更後） | 規則 (d) / 規則 (e) | **ともに 0 件**（T023 実測。(d) は T022 のヘルプ汎用化で解消、(e) は回帰ガードのまま） |
| T024 変異探針（走査） | `graph.py` に `_PLATFORM_HINT = "x"` を追加 → 赤 / 復元 → 緑 | 赤: `test_platform_literals_are_confined_to_registry` のみ失敗（`1 failed, 2 passed`）。復元後 `3 passed`、sha256 一致、`git status` 空（T024 実測） |
| T051 変異探針（ノードの env） | `nodes/search.py` に `os.getenv` を追加 → 赤 / 復元 → 緑 | 赤: `import os` ＋ `_probe = os.getenv("TR_MAX_RESULTS")` を一時追加すると `test_nodes_do_not_read_environment` のみ失敗（`nodes/search.py:33` を検出、`1 failed, 3 deselected`）。復元後 `1 passed`、sha256 一致、`git status` に search.py の差なし（T051 実測） |
| T027 導出の非空虚性 | `NODE_ORDER` を差し替え → 出力が追随 | （未記入） |
| T053 引数の使用 | 実装前は「引数が無視される」ことで赤 | 赤: X のレポート ＋ YouTube の provider を渡すと `assert '## 選定動画リスト（関連度順上位 N 件）' in passed` で失敗（出力は「## 選定ツイートリスト（上位 N 件）」）。`provider = get_provider(report.instruction.platform)` が引数を上書きしている**現行の不具合**を示す赤（T055 実測） |
| 規則 (d) の非空虚性 | `__main__.py` のヘルプに `"x"` を一時追加 → 赤 / 復元 → 緑（sha256 一致） | 赤: `test_help_text_does_not_enumerate_platforms` のみ失敗。復元後 `3 passed`、sha256 一致（T024 実測） |
| 規則 (e) の非空虚性 | `providers/__init__.py` に `_ALL: list[Provider] = []` を一時追加 → 赤 / 復元 → 緑 | 赤: `test_platform_collections_are_absent` のみ失敗。復元後 `3 passed`、sha256 一致（T024 実測） |

#### T010: 実装前の赤の理由（T008 / T009 実測）

| テスト | 赤の理由（実測） | 期待する緑化の条件 |
|---|---|---|
| `test_platform_scan.py` | `test_platform_literals_are_confined_to_registry` が「計 14 件」で失敗（検出 16 行 − 許容 2 行）。`test_help_text_does_not_enumerate_platforms` が `__main__.py:32` の 1 件で失敗。`test_platform_collections_are_absent` は緑（回帰ガード） | T011〜T022 の実装後に (a)+(b) が 0 件・(d) が 0 件になる（T023） |
| `test_platform_extension.py` | 収集時に `ImportError: cannot import name 'register_provider' from 'trend_researcher.providers'`（T014 で追加）。加えて T011 の追加フック 5 つが未定義 | T011〜T022 の実装後に 4 テストが緑になる（T026） |

#### T025: 既存テストの追随（実測）

| ファイル | 追随の内容 | 件数 |
|---|---|---|
| `tests/unit/test_config.py` | `Config.load(platform="x"\|"youtube")` → `Config.load(env_prefix="XTR"\|"YTR")`。`XTR_MODEL` / `YTR_MODEL` の解決結果・優先順位の断言は**そのまま維持**（変更なし）。`test_get_config_is_cached_and_uses_x_defaults` → `test_get_config_is_cached_without_env_prefix` に改名（既定が `x` 固定でなくなったため） | 11 箇所 / 30 passed |
| `tests/unit/test_providers.py` | (1) 未知プラットフォームのパラメータから `""` / `"   "` を除外（空文字は「登録の先頭」へ解決する仕様になったため）、(2) エラー文言の断言を `"'x' または 'youtube'"` → `"'x'、'youtube' のいずれかを指定してください"`（登録キーからの生成）へ、(3) `test_provider_exposes_the_full_interface` に新フック 5 つ（`env_prefix` / `max_search_queries` / `content_noun` / `candidates_section_title` / `selection_note`）の存在確認を追加 | 追加 3 / 修正 2 |
| `tests/unit/test_configuration.py` | `DEFAULTS["platform"]` を `"x"` → `""`。`test_platform_is_not_validated_at_this_layer` の docstring から削除済みの `Literal["x","youtube"]` の記述を除去し、**空文字＝登録の先頭**という新仕様のテスト（`test_platform_defaults_to_blank_so_the_registry_decides`）を追加 | 修正 2 / 追加 1 |
| `tests/unit/test_fixtures.py` | `Config.load(platform="youtube")` → `Config.load(env_prefix="YTR")` | 1 箇所 |
| `tests/integration/test_full_flow.py` | `Config.load(platform="x", ...)` → `Config.load(env_prefix="XTR", ...)`（3 箇所）。**新規に `test_llm_nodes_receive_the_platform_env_prefix` を追加**（4 ノードが `provider.env_prefix` を `build_model` に渡していること。X=`XTR` / YouTube=`YTR` の 2 パラメータ） | 修正 3 / 追加 1 |
| `tests/conftest.py` | `FakeModelFactory._build_model` の内側 `_build` を `(role="research", env_prefix=None)` に拡大し、呼び出しごとの `env_prefix` を `env_prefix_log` に記録（`env_prefixes_for(node)` で観測）。第 2 位置引数を受けないための `TypeError` で `test_plan_search.py` 13 件が落ちていたのを解消 | 記録用の観測点を追加 |
| `tests/unit/test_plan_search.py` | **変更不要**（`fake_model_factory` の引数拡大のみで緑に復帰）。上限が provider 由来（`max_search_queries`）になったことは既存の切り詰めテストがそのまま通ることで確認 | 0 箇所 |
| `tests/unit/test_compile_report.py` | **変更不要**（45 passed のまま）。T021 の分岐→フック移設で出力文字列が不変であることをこの無修正が担保 | 0 箇所 |

- 追随で消えた網羅は「空文字・空白のみの解決」の 1 項目（`""` / `"   "` は旧テストでは**例外**を期待していた）。同等以上の入力を `test_get_provider_resolves_blank_to_the_first_registration`（`""` / `"   "` の 2 パラメータ → 登録の先頭クラスを返す）として残した。
- **T025 の変異探針**（各探針後に復元 → 緑復帰 → sha256 一致 → `git status` に src の差分なし）:

| 探針 | 変異 | 赤になったテスト |
|---|---|---|
| P1 | `nodes/parse_instruction.py` の `build_model("research", provider.env_prefix)` → `build_model("research")` | `test_llm_nodes_receive_the_platform_env_prefix` **2 failed** → 復元後 2 passed |
| P2 | `providers/__init__.py` の `_resolve_key` の `return next(iter(_PROVIDERS))` → `raise ValueError(platform)` | `test_get_provider_resolves_blank_to_the_first_registration` **2 failed** → 復元後 2 passed |
| P3 | `providers/__init__.py` の `choices = "、".join(f"'{name}'" for name in _PROVIDERS)` → 固定文字列 | `test_unknown_platform_message_enumerates_every_registration` **1 failed** → 復元後 1 passed |

- 実測値: `tests/unit/test_config.py` 30 passed / スイート全体 **567 passed**（47 秒）/ `ruff check .` 0 / `mypy --no-incremental src` 0（26 files）。
- 注記: `nodes/search.py` / `nodes/fetch.py` の `Config.load(env_prefix=provider.env_prefix)` の配線は、境界がフェイクのため既存テストでは観測できない。この経路の網羅は T051（ノードの env 読みの変異探針）で行う。

#### T026: US1 の受け入れ確認（実測）

| 確認 | コマンド | 実測 |
|---|---|---|
| フルスイート（カバレッジ込み・実行時間の判定コマンド） | `uv run pytest -q` | **567 passed**、カバレッジ **95.24%**（`fail_under = 90` を満たす）、**48.79 秒**（上限 60 秒以内・SC-010） |
| 走査＋拡張の 2 テスト | `uv run pytest tests/unit/test_platform_scan.py tests/unit/test_platform_extension.py -q` | **7 passed**（走査 3 / 拡張 4）。既存 X / YouTube のテストと**同時に**緑 |
| 手順 3 の diff 確認 | `git diff --name-only -- src/trend_researcher/graph.py src/trend_researcher/state.py src/trend_researcher/models.py src/trend_researcher/configuration.py src/trend_researcher/nodes/ src/trend_researcher/rendering.py` | **0 ファイル**（出力なし）。試験用プラットフォームの追加はテスト内の登録だけで完結し、コアに追加編集が発生していない（SC-001） |

- 進捗行 7 行（各ノード `開始` / `完了`）とレポート本文の不変は、`tests/integration/test_full_flow.py` の進捗断言と `tests/unit/test_rendering.py` の golden 比較（byte 一致）が同時に緑であることで担保した。
- 基準値（手順 1）との差: 547 → **567 passed**（+20 は T008 / T009 の 7 件と T025 の追加 13 件）、カバレッジ 95.29% → **95.24%**（新規テストで分母も増えたため。ゲートは 90%）。

#### T027 / T028: 実装前の赤（T029 実測）

| テストファイル | 赤の理由（実測） | 期待する緑化の条件 |
|---|---|---|
| `tests/unit/test_progress.py` | 旧シグネチャ `emit(node_index, node_name, phase, detail)` のため `TypeError: ProgressEmitter.emit() missing 1 required positional argument: 'phase'`（8 件）。加えて `test_total_is_not_duplicated_as_a_class_constant` は `ProgressEmitter.TOTAL` が実在するため失敗、`test_emit_derives_the_index_from_node_order` / `test_emitted_index_follows_the_current_node_order` / `test_emit_rejects_unknown_node_name` も同名の `TypeError`。→ **11 failed, 2 passed**（T027 実測） | T035（`emit(node_name, phase, detail)` 化＋`TOTAL` 削除）と T036（呼び出し側の数値引数削除）で緑 |
| `tests/unit/test_cache.py` | `test_read_json_is_removed` が `AssertionError`（`hasattr(cache, "read_json")` が真） | T030 の削除で緑（**T037 で赤になる節の削除も完了**） |
| `tests/unit/test_models.py` | `test_output_spec_has_no_table_for` / `test_research_instruction_has_no_use_trends` が `AssertionError` | T033 / T032 の削除で緑 |
| `tests/unit/test_x_search.py` | `test_fetch_thread_is_removed` が `AssertionError`（`hasattr(x_search, "fetch_thread")` が真）。**収集時に `ImportError` にはならない**（`from trend_researcher.tools import x_search` に変更したため） | T034 の削除で緑（11 件の `fetch_thread` テストは T034 で `fetch_threads` の 1 件経路へ移した） |
| `tests/unit/test_configuration.py` | `test_use_trends_is_not_declared` が `AssertionError` | T032 の削除で緑 |
| `tests/unit/test_parse_instruction.py` | `test_use_trends_is_not_in_the_state_declarations` が `AssertionError`（`AgentState.__annotations__` に `use_trends` が実在） | T032 の削除で緑 |

計 **6 failed, 67 passed**（対象 6 ファイル・T028 実測）。削除対象 5 件に対し断言は 6 件
（`use_trends` を `Configuration` / `ResearchInstruction` / `AgentState` の 3 宣言で個別に固定したため）。

#### T038 / T039: 実装前の赤（T040 実測）

| テストファイル | 赤の理由（実測） | 緑化の条件 |
|---|---|---|
| `tests/unit/test_platform_scan.py` | `test_nodes_do_not_read_environment` が `AssertionError`。検出 **2 件**（`nodes/fetch.py:23` / `nodes/search.py:26` の `cfg = Config.load(env_prefix=provider.env_prefix)`）。同ファイルの既存 3 テストは緑のまま（**1 failed, 3 passed**） | T045 / T046 で `Config.load()` の呼び出しを消し、T042 で `Config` を削除すると 0 件になる |
| `tests/unit/test_config.py` | collection error。`ImportError: cannot import name 'resolve_env' from 'trend_researcher.configuration'` | T041 の `resolve_env` / `Configuration.load()` の追加で緑 |

- 旧「引数による上書き」の節（`Config.load(cache_dir=..., max_results=...)`）は、明示指定を `model_copy(update=...)` で与える形（明示指定 > 環境変数）へ置き換えた。`model_copy(update=...)` の値が `model_fields_set` に載ることは T039 のテストで固定した（SET-002 / SET-006）。
- `OPENAI_*` と `model` の解決は `Config` のフィールドだったため、この節からは落ちた。SET-009 のとおり契約は `tools/llm.py` が担い、`tests/unit/test_llm.py` が検証する（T049 で `TR_MODEL` → `{env_prefix}_MODEL` を `resolve_env` へ寄せる際に期待値を確認する）。

#### T047 / T050: CLI の設定経路とテストの追随（実測）

| 確認項目 | コマンド / テスト | 実測 |
|---|---|---|
| 旧型の参照 | `grep -n 'config\.' src/trend_researcher/__main__.py` | **0 件**（grep の終了コード 1 = 一致なし）。解決済みの設定は `settings` という名前で保持する |
| 環境変数が実行まで届く | `tests/unit/test_cli_entry.py::test_environment_variable_reaches_runnable_config` | 実装前は `5 == 9` で赤 → 緑。**同じ赤が `XTR_MAX_RESULTS` の節でも出る（`5 == 7`）** |
| 明示指定 > 環境変数 | `tests/unit/test_cli_entry.py::test_explicit_cli_options_override_environment` | `TR_MAX_RESULTS=9` ＋ `--max-results 3` → `configurable["max_results"] == 3`。`--lang` / `--cache-dir` も同様 |
| フルスイート | `uv run pytest -q` | **588 passed**、カバレッジ **96.48%**、**48.36 秒**（SC-010 の 60 秒以内） |
| lint / 型 | `uv run ruff check .` / `uv run mypy --no-incremental src` | **0 件** / 26 ファイルで **0 件** |
| 薄いモジュールのカバレッジ | `uv run pytest -q` の `__main__.py` 行 | 46% → **67%**（95 stmts / 31 miss。`test_cli_entry.py` の 6 件が `main()` / `_run_async` の配線を通すため） |

- **T047**: `_run_async(args, settings: Configuration)` へ変更。CLI の明示指定は `main()` で
  `settings.model_copy(update=...)` として与え（`model_fields_set` に載せて SET-006 / SET-007 の
  順序を保つ）、`RunnableConfig` には**解決済みの 1 つの `Configuration`** を載せる
  （`platform` / `output_format` / `sort_by` / `published_after` は CLI が上書き）。`--cache-dir` の
  明示指定だけは現行と同じく実行時 CWD 基準で絶対パス化する（`Path(...).expanduser().resolve()`）。
- **T050**: `tests/integration/test_full_flow.py` から `Config` / `get_config` / `cache_clear` を外した
  （`get_config.cache_clear()` の 2 箇所は SET-010 により不要。**進捗・件数・出力の断言は不変**）。
  併せて `tests/unit/test_configuration.py` に 3 件追加（`load()` が読むのは 3 項目のみ =
  `TR_SORT_BY` / `TR_PLATFORM` / `TR_OUTPUT_FORMAT` は無視される、`from_runnable_config` は
  環境変数を読まない、`load()` に明示指定を重ねると明示指定が残る）。
#### T048: パッケージの公開面（実測）

| 確認項目 | コマンド / テスト | 実測 |
|---|---|---|
| 公開面の現状 | `uv run python -c "import trend_researcher; print(hasattr(trend_researcher, 'Configuration'))"` | **False**。re-export されていたのは旧 `Config` **のみ**で、`Configuration` は `__init__.py` の公開面に存在しない（→ §2 の「基準値のずれ」に記録） |
| 削除の赤 | `tests/unit/test_configuration.py::test_package_does_not_reexport_the_old_config_class` | `assert 'Config' not in __all__` で**赤** → `__init__.py` から `Config` の import と `__all__` の 1 行を削除して緑 |
| 維持した公開面 | `test_package_keeps_the_graph_and_rendering_entry_points` | `trend_researcher`（グラフ）/ `render_report` / モデル群の re-export は不変 |
| フルスイート | `uv run pytest -q` | **596 passed**、カバレッジ **96.55%**、**48.72 秒** |

- `Configuration` を新たに `__init__.py` へ公開する変更は行わない（未公開のまま。設定の入口を広げる変更は本リファクタリングの範囲外であり、SC-003 の「同名項目の定義箇所が 1 つ」はモジュール単位で満たしている）。

#### T049: LLM のモデル解決（実測）

| 確認項目 | コマンド / テスト | 実測 |
|---|---|---|
| 解決規則 | `tests/unit/test_llm.py` の 7 件 | `TR_MODEL` → `{env_prefix}_MODEL` → 既定 `openai:mimo-v2.5`、空文字は未設定扱い、`env_prefix=None` では接頭辞を見ない、`.env` 読み込みは維持 |
| 変異探針 1 | `llm.py` の `env_prefix=env_prefix` を**削除**して実行 | **1 failed, 6 passed**（`test_model_uses_platform_prefix_when_generic_is_unset` が `AssertionError`）→ 復元（sha256 一致）後に **7 passed** |
| lint / 型 | `uv run ruff check .` / `uv run mypy --no-incremental src` | **0 件** / 26 ファイルで **0 件** |

- **T049 の赤は存在しない**（旧実装と `resolve_env` は同値。`os.getenv` の falsy 判定と「空文字は未設定扱い」が同じ規則）。したがって「実装前 red」ではなく**変異探針**でテストの非空虚性を示した（憲法 原則 I の「テストが空でないこと」の担保）。記録として残す: 上記の変異で赤になるため、追加した 7 件は解決順を実際に固定している。
- 変異探針の戻し忘れ防止のため、復元後に sha256 の一致と**フルスイート 1 回**（`uv run pytest -q` → **596 passed / 96.55% / 48.83 秒**。T048 / T049 のテスト追加を含む）を確認した。

#### T042: 旧設定型の削除（実測。コミットは T065 と同一変更一式）

| 確認項目 | コマンド / テスト | 実測 |
|---|---|---|
| 削除の赤 | `tests/unit/test_config.py::test_old_config_class_is_removed` | `hasattr(config_module, "Config")` で **赤**（`1 failed, 31 passed`）→ `Config` / `get_config` を削除して **32 passed** |
| 残したヘルパ | `src/trend_researcher/config.py` | `_REPO_ROOT` / `_resolve_path` / `_load_env_once` の 3 つのみ（`Configuration.load()` が使う）。モジュール docstring を「設定解決の共通ヘルパ」へ変更し、`lru_cache` / `os` / `BaseModel` / `Field` の import を削除 |
| 残存参照 | 追随したファイル | `tests/unit/test_fixtures.py`（`Config.load` → `Configuration.load`。`cache_dir` は `str` 比較）、`tests/conftest.py`（`tmp_cache_dir` の docstring）、`src/trend_researcher/tools/x_search.py`（docstring の `Config.accounts_db` → `XSettings.accounts_db`） |
| 走査4の判定 | `grep -rn "class Config\b\|def get_config\|Config\.load" src/` | 素のコマンドでは `src/trend_researcher/__pycache__/config.cpython-312.pyc` が `binary file matches`（生成物）を返すため、`--include=*.py` を付けて **OK: 0 件**。検出規則の `Config.load`（`test_platform_scan.py`）は**再導入の回帰ガード**として残す |
| フルスイート | `uv run pytest -q` | **597 passed**、カバレッジ **96.63%**、**48.26 秒** |

#### T051: US3 完了検証（実測。T042 の削除は適用済み・コミットは T065 待ち）

| 手順 | コマンド | 実測 |
|---|---|---|
| 6-1 設定型が 1 つ | `grep -rn --include=*.py "class Config\b\|def get_config\|Config\.load" src/` | **OK: 0 件**（`--include=*.py` なしでは `__pycache__` の古い bytecode が `binary file matches` を返すため明示する） |
| 6-2 ノードの環境変数 0 | `uv run pytest tests/unit/test_platform_scan.py -q -k "nodes_do_not_read"` | **1 passed**（検出 **2 件 → 0 件**） |
| 6-3 設定の解決と優先順位 | `uv run pytest tests/unit/test_config.py tests/unit/test_configuration.py -q` | **54 passed** |
| 固有設定の所在 | `grep -rn "XTR_\|YTR_" src/ --include=*.py \| grep -v providers/ \| grep -v tools/` | **OK: 固有設定は provider / tools のみ** |
| 変異探针 | — | §1 の `T051 変異探针（ノードの env）` 行に記録 |
| 品質ゲート | `uv run pytest -q` / `uv run ruff check .` / `uv run mypy --no-incremental src` | **597 passed / 96.63% / 48.26 秒**、**0 件**、26 ファイルで **0 件** |

- T051 の検証は **T042 の削除を適用した作業ツリー**で行った（C2 によりコミットは T065 と同一変更一式）。T069 の最終ゲートで 6-1 を**再実行**して確定させる。

#### T052 / T053 / T054: 実装前の赤（T055 実測）

| タスク | 赤の実測 | 赤の理由 |
|---|---|---|
| T052 import の切り替え | `uv run pytest tests/unit/test_rendering.py -q --no-cov` → `ModuleNotFoundError: No module named 'trend_researcher.rendering'`（collection error 1 件） | 描画の置き場所（`rendering.py`）が未作成。**T056 の作成で解消**する |
| T053 引数の使用 | 現行 `nodes.compile_report.render_markdown` に対し `test_markdown_uses_passed_provider` のみ実行 → `assert '## 選定動画リスト（関連度順上位 N 件）' in passed` で失敗（出力は「## 選定ツイートリスト（上位 N 件）」） | 現行実装が先頭で `provider = get_provider(report.instruction.platform)` と**引数を上書き**している。すなわち引数は飾りで、レポート側のプラットフォームが常に勝つ（FR-017 / RND-007 が潰すべき**現行の不具合**） |
| T054 骨格の無参照 | 同テストのみ実行 → `assert not (RENDERING_NAMES & referenced)` で失敗（`referenced` に `render_report` / `render_markdown` / `render_json` が出現） | `graph.py` が `nodes.compile_report` から 3 名を import し、`render_report()` を自前で定義している（FR-016 / RND-001 違反） |

- 計測手順: T052 の import 切り替えで collection error になるため、T053 / T054 は**一時的に import を `nodes.compile_report` に戻した作業ツリー**で `-k "uses_passed_provider or graph_does_not"` を実行して赤を採取した（`2 failed, 7 deselected`）。復元は `cp /tmp/tr_rendering.bak` で行い、sha256 が `eb79949a689632bc32a98a2b34c6ec006011a33d5abe64540375d6773b02855e` と一致することを確認した。
- 注記: 赤の間は `uv run ruff check .` が `I001`（import の並び）を報告する。ruff は未存在モジュールを first-party と判定できないためで、T056 で `rendering.py` が生えると解消する（T062 で確認）。

#### T062: golden の byte 一致（実測）

| 検証 | コマンド | 実測 |
|---|---|---|
| golden 3 件の一致（Markdown 完全一致 / JSON は 2 キーのみ除外） | `uv run pytest tests/unit/test_rendering.py -q` | **26 passed**（golden 6 件 ＝ Markdown 3 ＋ JSON 3、`test_markdown_uses_passed_provider`（T053）、`test_graph_does_not_reference_rendering`（T054）を含む）。golden ファイルは**無修正** |
| カバレッジ gate の注意 | 同上 | サブセット実行では総合カバレッジ 43.37% となり `FAIL Required test coverage of 90.0% not reached` が出る（判定は全体実行で行う）。**テスト自体は 26 passed** |
| 全件緑 | `uv run pytest -q` | **598 passed / 96.63% / 48.60 秒**（SC-010 の 60 秒以内） |
| ruff | `uv run ruff check .` | **All checks passed!**（赤の間に出ていた `I001` は `rendering.py` の生成で解消） |

- 移設の内訳: `test_rendering.py` 26 件（golden 6 ＋ 新規 2 ＋ 旧 `test_compile_report.py` から 18 件）／`test_compile_report.py` 20 件。
- **T053 は実装前の赤（引数の無視）→ 実装後は緑**であることを同じテストで確認した（golden は変更していないため、`render_markdown` が provider を引数で受けるようになっても出力文字列は 1 文字も変わらないことが byte 比較で担保される）。

#### T063: README の更新（実測）

| 確認 | コマンド | 実測 |
|---|---|---|
| `--trends` の記載 | `grep -c -- '--trends' README.md` | **0**（削除対象の記載は README に元から存在しなかった。§4 の「`test_cli_contract.py` に該当節なし」と同じ状態） |
| 環境変数の 3 群 | — | `TR_MODEL` / `TR_MAX_RESULTS` / `TR_TRANSCRIPT_LANG` / `TR_CACHE_DIR`（共通）、`XTR_ACCOUNTS_DB` / `XTR_SEARCH_POOL_SIZE` / `XTR_MAX_RETRIES`（X 固有）、`YTR_TRANSCRIPT_LANG`（YouTube 固有）、`OPENAI_API_KEY` / `OPENAI_BASE_URL`（LLM 接続）を表で追加。解決順序は `contracts/settings-contract.md` の SET-006 どおり **明示指定 > `TR_*` > `{env_prefix}_*` > 既定値** |
| `--platform` の説明 | — | 変更なし（FR-021 / FR-027） |

#### T064: quickstart 手順 1〜7 の通し実行（実測）

| 手順 | コマンド | 実測 |
|---|---|---|
| 1 | `uv run pytest -q` | **598 passed / 96.63% / 49.15 秒**（基準 547 / 95.29% / 49.67 秒。SC-010 の 60 秒以内） |
| 1 | `uv run pytest -q --no-cov --durations=15` | **598 passed / 49.20 秒**。最遅は `test_cli_contract.py::test_cli_002_07_output_matches_stdout_rendering` **1.78 秒**（上位 15 件はすべて `test_cli_contract.py`） |
| 1 | `uv run ruff check .` | **All checks passed!** |
| 1 | `uv run mypy src` | **Success: no issues found in 27 source files**（26 → **27**。`rendering.py` の追加ぶん。§2 の「mypy の対象ファイル数」に記録） |
| 2 | `uv run pytest tests/unit/test_platform_scan.py -q` | **4 passed**。規則 (a)+(b) の検出は **2 行**（`providers/__init__.py` の `"x": XProvider,` / `"youtube": YouTubeProvider,`）で**違反 0 件**、規則 (c) / (d) / (e) は **0 件**（走査関数を直接呼んで計数） |
| 3 | `uv run pytest tests/unit/test_platform_extension.py -q` | **4 passed**（コアを編集せず試験用プラットフォームが完走） |
| 3 | `git diff --name-only -- <コア 6 パス>` | 実行の**前後で同一**（`nodes/{analyze_content,compile_report,extract_common,parse_instruction,plan_search}.py` の 5 件）。**新たな差分は 0**。この 5 件は T035 / T036 の未コミット変更（C1 により T065 と同一変更一式で入る）で、手順 3 が生んだものではない |
| 4 | `uv run pytest tests/unit/test_rendering.py -q` | **26 passed**。golden 3 件は Markdown 完全一致 / JSON は 2 キー除外で一致。サブセット実行のため `FAIL Required test coverage of 90.0% not reached (43.37%)` の行が出る（判定は全体実行で行う） |
| 5 | `uv run pytest tests/integration/test_cli_contract.py -q` | **54 passed**（`--help` の終了コード / 未登録 `--platform` / 7 行の進捗 / stdout と stderr の分離 / 削除した `--trends` の不受理を含む） |
| 5 | `uv run python -m trend_researcher --help \| grep -c -- "--trends"` | **0** |
| 5 | `uv run python -m trend_researcher --platform bogus > /dev/null; echo $?` | **exit=2**（stdout は空） |
| 6-1 | `grep -rn "class Config\b\|def get_config\|Config\.load" src/ --include=*.py` | **OK: 0 件**（`--include=*.py` 必須。付けないと `__pycache__` の古い bytecode が `binary file matches` を返す） |
| 6-2 | `uv run pytest tests/unit/test_platform_scan.py -q -k "nodes_do_not_read"` | **1 passed, 3 deselected** |
| 6-3 | `uv run pytest tests/unit/test_config.py tests/unit/test_configuration.py -q` | **54 passed** |
| 6 | `grep -rn "XTR_\|YTR_" src/ --include=*.py \| grep -v providers/ \| grep -v tools/` | **OK: 固有設定は provider / tools のみ** |
| 7 | `uv run pytest -q` / `uv run ruff check .` / `uv run mypy src` | 上記 1 と同じ（598 / 96.63% / 49.15 秒、0 件、27 ファイルで 0 件） |
| 7 | `git diff -- pyproject.toml` | **空**（`[project].dependencies` / `optional-dependencies` に差分なし。FR-024） |
| 7 | `env -u OPENAI_API_KEY -u XTR_ACCOUNTS_DB -u YTR_ACCOUNTS_DB uv run pytest -q --no-cov` | **598 passed / 47.68 秒**（認証情報なし・オフラインで完走。FR-023） |

- 手順 2 の非空虚性（探針 → 赤 → 復元）は T024 で実施済み（§1 の `T024 変異探針（走査）` 行）。手順 4 の golden 採取は T006 で実施済み（§3）。
- 表の「基準」は手順 1 の期待値（`quickstart.md` に記載の 2026-09-13 の値）。テスト件数は 547 → **598**、カバレッジは 95.29% → **96.63%**、実行時間は 49.67 秒 → **49.15 秒**。

#### T065: 憲法の PATCH 改正（実測。T035 / T036 / T042 と同一変更一式）

| 改正点 | 改正前 → 改正後 | 改正後の実測（同一コミットに含めた実装） |
|---|---|---|
| 原則 IV（プラットフォーム抽象） | 「既存の分岐はファイルを変更する際に provider へ寄せる **SHOULD**」→「コアに**プラットフォーム名の列挙・比較を残してはならない MUST NOT**（許容は `providers/__init__.py` の登録辞書のみ、機械走査で 0 件を保つ）」 | 走査規則 (a)+(b) の検出は **2 行**（`providers/__init__.py` の `"x"` / `"youtube"` のみ）／違反 **0 件**、規則 (d) / (e) も 0 件（T064 手順 2 実測） |
| 原則 V（CLI 出力契約と観測可能性） | 「`NODE_ORDER`・**`ProgressEmitter.TOTAL`**・グラフのノード数の一致」→「`NODE_ORDER` とグラフのノード数を一致させ、**総数と表示番号は単一の定義（`NODE_ORDER`）から導出する MUST（手書きの定数を置かない）**」 | `assert not hasattr(ProgressEmitter, "TOTAL")`（`tests/unit/test_progress.py`）、`progress.py` の `total = len(NODE_ORDER)`／`node_index = NODE_ORDER.index(node_name) + 1`、7 ノードの `emitter.emit` は 14 箇所すべて `(NODE_X, phase, detail=...)` の 2〜3 引数（数値引数 0 件） |
| 技術制約と品質基準 | 「実行条件は `.env` と **`Config`** から供給」→「`.env` と **`Configuration`（唯一の実行時設定型）** から供給」。環境変数の 3 群（`TR_*` / `XTR_*` / `YTR_*`）とハードコード禁止 MUST NOT は不変 | `grep -rn "class Config\b\|def get_config\|Config\.load" src/ --include=*.py` → **OK: 0 件**（T064 手順 6-1 実測）。`Config` / `get_config` / `lru_cache` の削除を `tests/unit/test_config.py` の `test_old_config_class_is_removed` が固定 |
| バージョン・記録 | `Version` 1.2.0 → **1.2.1**（PATCH）、Sync Impact Report の Modified principles / Changed sections / History / Follow-up TODOs を追記。**原則 I〜III・VI の文言は変更しない** | `grep -n "^### \|^**Version**" .specify/memory/constitution.md` で原則 I〜VI の見出しが 6 件のまま（欠落・追加なし）を確認 |

- 憲法と実装を**同時に** green にするため、T035（`progress.py` の単一定義化）/ T036（7 ノードの emit から数値引数を削除）/ T042（`Config` / `get_config` の削除）を**このコミットに同梱**した（C1 / C2）。片方だけを適用した状態は残していない。
- 同梱したファイル: `src/trend_researcher/progress.py`、`src/trend_researcher/nodes/{parse_instruction,plan_search,analyze_content,extract_common,compile_report}.py`（`search.py` / `fetch.py` の emit 追随は T043〜T046 のコミットに含まれる）、`src/trend_researcher/config.py`、`src/trend_researcher/tools/x_search.py`（T042 の追随）、`tests/{conftest.py,unit/test_config.py,unit/test_fixtures.py}`（T042 の追随）、`.specify/memory/constitution.md`、`tasks.md`。
- ゲート（このコミットの内容で実測）: `uv run pytest -q` → **598 passed / 96.63% / 49.15 秒**、`uv run ruff check .` → **All checks passed!**、`uv run mypy src` → **0 件（27 ファイル）**。

#### T066: 後方互換シムの不在の確認（FR-020 / 原則 VI。実測）

| 確認 | コマンド | 実測 |
|---|---|---|
| 非推奨の表明 | `grep -rn "deprecated\|後方互換\|alias\|別名" src/` | **OK: 0 件**（`src` 全体で 1 件も出ない） |
| 旧名 `Config` | `grep -rnP '(?<![A-Za-z_])Config(?![A-Za-z_])' src/ tests/ --include=*.py` | ヒット 10 件。**すべてコメント・docstring・削除を主張するテスト**で、代入・再定義・再エクスポートは 0 件（下表） |
| 旧名 `get_config` | `grep -rn "get_config" src/` | **0 件**（`tests/unit/test_config.py::test_old_config_class_is_removed` が `assert not hasattr(config_module, "get_config")` で固定） |
| 非推奨警告 | `grep -rn "Deprecat\|deprecat\|warnings\.warn" src/ tests/ --include=*.py` | **OK: 0 件** |
| 別名代入 | `grep -rnE "^[A-Za-z_]+ = (render_markdown\|render_report\|Configuration\|get_provider\|Config)$"` | **OK: 0 件** |
| 実行時の旧名 | `uv run python -c "import trend_researcher as tr; ..."` | `hasattr(tr, "Config")` → **False**、`config` モジュールの残存メンバ → **[]** |
| 公開面 | `grep -n "__all__" src/` + `tests/unit/test_configuration.py` | `__all__` の定義は `__init__.py:17` の 1 箇所のみ。`assert "Config" not in trend_researcher.__all__` と `assert not hasattr(trend_researcher, "Config")` が旧 re-export の不在を固定（SET-012 / REM-007） |
| 二重実装 | `grep -rn "^def render_report\|^def render_markdown\|^def render_json" src/ --include=*.py` | 定義は `rendering.py:13 / :20 / :54` の 3 件のみ。`nodes/compile_report.py` は `render_markdown` を import して使うだけ（自前定義なし）、`graph.py` の `render` 参照は **0 件** |

- 走査の落とし穴: 素の `grep -rn "Config\b"` は `RunnableConfig`（語末が `Config`）と `Configuration` を拾うため単独識別子の判定に使えない。PERL 風正規表現 `(?<![A-Za-z_])Config(?![A-Za-z_])` で前後を識別子文字から除外して初めて「実在する旧名」を数えられる。
- 単独識別子 `Config` のヒット 10 件の内訳（すべて実装ではない）: `configuration.py:16`（削除済み `Config._env()` を語る docstring）／`test_configuration.py:288,291,295,296`（旧 re-export の削除と `__all__` の不在を固定）／`test_platform_scan.py:16,332,359`（規則 (c) の**検出対象文字列** `"Config.load"` とその説明）／`test_config.py:332,337`（`Configuration` 単一性を固定）／`test_llm.py:28`（既定モデル名の出所を語るコメント）。
- 削除を固定しているテスト: `tests/unit/test_config.py::test_old_config_class_is_removed`（`Config` / `get_config` / `lru_cache` の不在）、`tests/unit/test_configuration.py::test_package_does_not_reexport_the_old_config_class`（`__all__` と `hasattr` の不在）、`tests/unit/test_platform_scan.py` の規則 (c)（ノードは `Config.load` を読まない）。3 ファイルの実行は **54 passed**。

#### T067: 削除の証跡の確定（SC-005 / SC-008。実測）

| REM | (a) 実行時の参照件数（削除後の実測） | 実測コマンド |
|---|---|---|
| REM-001 `cache.read_json` | `src/` **0 件**、`tests/` は不在の断言 1 件のみ | `grep -rn "read_json" src/ tests/ --include=*.py` |
| REM-002 `prompts.COMPILE_REPORT_PROMPT` | `src/` **0 件**、`tests/` **0 件** | `grep -rn "COMPILE_REPORT_PROMPT" src/ tests/ --include=*.py` |
| REM-003 `--trends` 一式 | `src/` の `use_trends` **0 件**、`tests/` は不在の断言 4 件 | `grep -rn "use_trends" src/ tests/ --include=*.py` |
| REM-004 `OutputSpec.table_for` | `src/` **0 件**、`tests/` は不在の断言 1 件（＋ golden の除外キー） | `grep -rn "table_for" src/ tests/ --include=*.py` |
| REM-005 `tools/x_search.fetch_thread` | `src/` **0 件**、`tests/` は不在の断言 1 件のみ | `grep -rn "fetch_thread\b" src/ tests/ --include=*.py` |
| REM-006 `Config` | `src/` **0 件**、実行時 `hasattr` → False | T066 参照 |
| REM-007 `get_config()` | `src/` **0 件**（`config` モジュールの残存メンバ → `[]`） | T066 参照 |
| REM-008 手書き番号と `TOTAL` | `src/` の `TOTAL` **0 件**、emit 14 箇所すべて数値引数なし | T065 参照 |
| REM-009 描画関数群 | 定義は `rendering.py` の 6 件のみ、`graph.py` の `render` 参照 **0 件** | `grep -rn "^def _render_\|^def render_" src/ --include=*.py` |

- 契約文書の突き合わせで判明した**記載のずれ**（REM-003 の (c)）: `README.md` と `tests/integration/test_cli_contract.py` は**元から `--trends` の記載／節が存在しなかった**（`grep -c -- '--trends' README.md` → **0**、`grep -rn -- "--trends" tests/` → **0 件**）。ファイルは無修正とし、`contracts/removal-rationale.md` の REM-003 (c) を実測に合わせて訂正した。
- `specs/001-test-suite-hardening/contracts/cli-contract.md` は REM-003 (c) のとおり**更新済み**（同ディレクトリの `--trends` は **0 件**）。
- 契約文書に「## 実測による確定（T067 / SC-005 / SC-008）」節を追加し、9 項目すべての (a) 参照件数 / (c) 参照の更新状態 / (d) テストが固定していた内容と固定先を実測値で確定した。「位置」欄は**削除前の座標**であることを明記した。
- 結論: 未更新の参照・未更新のテストは 0 件。ずれは REM-003 の (c) に記載した 2 ファイルが元から対象外だった 1 点のみで、文書側を訂正した。
- REM-005 の 1 件取得ケースの移設先: `tests/unit/test_x_search.py:409` の `_threads()`（「1 件だけの `fetch_threads` 呼び出し（旧 `fetch_thread` と同一の経路）」）を `test_fetch_threads_*` 13 件が通す。

#### T068: 一時ファイル・探針の後始末（実測）

| 確認 | コマンド | 実測 |
|---|---|---|
| 作業ツリー | `git status --short --untracked-files=all` | **出力なし**（未コミットの変更・未追跡ファイルが 0 件） |
| golden | `git ls-files tests/unit/golden/ \| wc -l` | **6**（`x_full.md/json`、`youtube_full.md/json`、`sparse.md/json`）。導入は `28578f5`（T006）。**新規データとして残るのはこの 6 ファイルのみ** |
| 追加ヘルパ | `find . -name "golden_support*"` | **0 件** |
| 探針の残骸（ソース） | `find . -name "*probe*" -not -path "./.venv/*"` | **0 件**（探針は `/tmp` の `.bak` と python の in-place 置換のみで行い、リポジトリ内にスクラッチを作らない） |
| 探針の残骸（バイトコード） | 上記に加え `find . -name "*probe*" -not -name "*.pyc"` | ソースは 0 件だが `__pycache__` に**孤立した pyc 2 件**が残っていた（`tests/unit/__pycache__/test_t006_probe.cpython-311-pytest-9.1.1.pyc`、`tests/integration/__pycache__/test_t009_probe.cpython-311-pytest-9.1.1.pyc`）。**削除した**（`.gitignore` 対象で追跡外のため git の差分は出ない） |
| バックアップの残骸 | `find . -name "*.bak" -o -name "*.orig" -o -name "*.rej"` | **0 件** |
| スクラッチ領域 | `.gitignore` | `/tmp/` が無視対象として宣言済み（`# Scratch space (temporary scripts and generated files)`） |
| 後始末後の全件 | `uv run pytest -q` | **598 passed / 96.63% / 49.57 秒**（pyc 削除の影響なし＝テストはソースから再生成される） |

#### T070: 契約文書の訂正（実測。`spec.md` は変更しない）

| 論点 | 訂正前（契約） | 実測 | 訂正内容 |
|---|---|---|---|
| `TR_MAX_RESULTS` が数値でない（SET-011） | 「既定値 5（例外にしない。現行と同じ）」 | `TR_MAX_RESULTS=abc` → `ValueError: invalid literal for int() with base 10: 'abc'`。`tests/unit/test_config.py::test_non_integer_numeric_setting_raises` が固定 | 表の行を「**例外にする**（`ValueError`。既定値へ黙って落とさない）」へ変更し、「実測による確定」段落で根拠を明記 |
| `platform` の既定値を含む 7 項目（SET-005） | 対象を「名前・型・**既定値**」とし、「既存フィールドの削除・改名・型変更」を禁止 | `Configuration.platform` の既定は T017 で `"x"` → `""`（`src/trend_researcher/configuration.py:37-39`） | 対象を「名前・型（および**解決結果としての**既定値）」へ変更し、「既定値の変更」行を追加（`platform` のみ。他の 6 項目は不変） |

- 併せて SET-005 の検証行の参照先を実測に合わせた（空文字の**保持**は
  `test_configuration.py::test_platform_defaults_to_blank_so_the_registry_decides`、空文字の**解決**は
  `test_providers.py::test_get_provider_resolves_blank_to_the_first_registration`。初稿では前者を
  「同じファイルが `get_provider("")` の解決を固定する」と書いていたが、それは後者のテストであるため訂正した）。
- `spec.md` / `plan.md` は変更していない（`use_trends` の削除は FR-009 の対象であり、他の 6 項目の既定値は
  不変。`platform` は plan.md の「解釈の記録」で扱いを決めている）。
- 判定は「終状態」で行い、契約の意図（Studio の入力欄と利用者が観測する解決結果を変えない）は充足していると確認した。

#### T071: `.env` の読み込みの 1 経路化（実測）

| 論点 | 変更前（実測） | 変更後 |
|---|---|---|
| `load_dotenv` の呼び出し箇所 | 2 箇所（`config.py:36` の `_load_env_once` と `tools/llm.py:34` の引数なし `load_dotenv()`） | `src/trend_researcher/config.py:46` の **1 箇所のみ**（`grep -rn "load_dotenv(" src/ --include=*.py`） |
| 関数名 | `config._load_env_once()`（private。`load()` のみが呼ぶ） | `config.load_env()`（public。`Configuration.load()` と `tools/llm.py` の両方が呼ぶ）。T071 のタスク文の `config._load_env_once()` ではなく**この名前**にした（境界から呼ぶ公開の 1 経路として命名し直した。旧名を残さない。FR-020） |
| 検証 | `test_env_loading_is_invoked` が `llm.load_dotenv` を直接見ていた（実装の内部構造に依存） | 走査テスト `test_dotenv_is_read_from_exactly_one_module`（`load_dotenv(` を含む `src/trend_researcher/**.py` が `config.py` のみ）＋ `test_env_loading_is_invoked_through_the_shared_loader`（`config.load_env()` が読むパス） |

- 呼び出しが 2 箇所になること自体は維持する（Studio のように `Configuration.load()` を通らない実行でも
  `.env` から `OPENAI_API_KEY` / `OPENAI_BASE_URL` を解決する必要があるため）。「1 経路」とは
  **`load_dotenv` を呼ぶ場所が 1 つ（`config.load_env()`）** であることを指す。契約 SET-002 の
  「`Configuration.load()` の経路で 1 回」という記述はこの意味へ更新した。
- `load_dotenv` は既定（`override=False`）で既存の環境変数を上書きしないため、2 回呼ばれても
  実行中の値は変わらない（挙動不変）。
- `tests/unit/test_llm.py` の autouse フィクスチャの遮断先を `llm.load_dotenv` から
  `config_module.load_dotenv` へ変更した（前者は存在しなくなるため。実リポジトリの `.env` を
  読ませない隔离は維持）。
- **変異探針**（復元後に sha256 一致を確認）: `tools/llm.py` を「自前で `load_dotenv()` を呼ぶ」
  形へ戻すと 3 件が失敗（`test_dotenv_is_read_from_exactly_one_module` /
  `test_env_loading_is_invoked_through_the_shared_loader` /
  `test_model_uses_platform_prefix_when_generic_is_unset`）→ 走査テストは非空虚。
- `env -u OPENAI_API_KEY -u XTR_ACCOUNTS_DB -u YTR_ACCOUNTS_DB uv run pytest -q --no-cov` →
  **599 passed / 46.77 秒**（FR-023）。

#### T072: `quickstart.md` 手順 6-1 の走査コマンドの偽陽性（実測）

| 論点 | 修正前（実測） | 修正後 |
|---|---|---|
| 手順 6-1 | `grep -rn "class Config\b\|def get_config\|Config\.load" src/` → **stderr に `grep: src/trend_researcher/__pycache__/config.cpython-312.pyc: binary file matches`、stdout は空、終了コード 0**。`|| echo "OK: 0 件"` が発火せず、期待表の `OK: 0 件` が現れない | `--include='*.py'` を付与 → **`OK: 0 件`**（`grep` が 0 件で終了コード 1 → `||` が発火） |
| 手順 6-2（現 226 行目） | 既に `--include=*.py` があり汚染なし。ただしシェルの glob 展開で `--include=<cwd の .py>` に化け得る | `--include='*.py'` へクォートを揃えた（同種の欠陥クラスのため同一文書内で統一） |
| 他の走査コマンド | quickstart 内の走査系コマンドは 6-1 / 6-2 の 2 件のみ（`grep` / `rg` / `find` / `ack` を全文検索）。他は pytest と `git diff` だけで、`__pycache__` の影響を受けない | 変更なし |

- **偽陽性の正体**: `grep -r` はバイナリファイルに一致すると stdout へ何も出さず、**終了コード 0** とstderr の
  `binary file matches` だけを返す。つまり「削除済みの `Config` クラス」が古い bytecode に残っている限り、
  手順どおりに実行すると成功・失敗のどちらとも読めない出力になる（＝検証として機能しない）。
- **辿り着けなかった理由**: `tasks.md` の過去メモ（T064 / T066 の実測表。`## 実装メモ` の 681 / 688 / 743 行など）
  は当時から `--include=*.py` 必須と記録していたが、`quickstart.md` の本文へは反映されていなかった。
- **非空虚性（探針・復元済み）**: `src/trend_researcher/state.py` へ一時的に `class Config:` を追記すると
  修正後のコマンドが `src/trend_researcher/state.py:66:class Config:  # probe` を出力する（＝走査が生きている）。
  `git checkout -- src/trend_researcher/state.py` で復元し、`git status --short` が空であることを確認した。
- **過去タスクの測定記録は変更しない**: T066 のタスク文（477-478 行）や削除確認表（773 行など）にある
  `--include` なしのコマンドは「その時点で実行したコマンドの記録」であり、当時の事実として残す
  （`converge` の append-only 方針。既存タスクの書き換えはしない）。
- 行番号のずれ: T072 のタスク文は「6-2 は 224 行目」と書いているが、本タスク自身の追記で 2 行繰り上がり
  **226 行目**になった（過去の実測記録として残す）。

#### T073: `env_prefix` の暫定表の削除とガードの追加（実測）

| 論点 | 変更前（実測） | 変更後 |
|---|---|---|
| 暫定表 | `_ENV_PREFIX_FALLBACK = {"x": "XTR", "youtube": "YTR"}`（旧 57 行目）を `_env_prefixes()` のフォールバックに使用 | **削除**（定義・参照とも 0 件。`grep -rn "_ENV_PREFIX_FALLBACK" tests/ src/ --include=*.py` → 0 件） |
| 解決できない `env_prefix` | 暫定表で補い、`if prefix:` で**黙ってスキップ**（規則 (b) の対象から外れる） | `AssertionError` を送出して**走査を中断**（材料が欠けた状態で「0 件」を返さない） |
| 検証 | なし（暫定表を空にしても 4 passed ＝ 死んだ経路） | `test_env_prefix_guard_fails_loudly_when_unresolvable` を追加（`get_provider` を `env_prefix` を持たないスタブへ差し替え `pytest.raises(AssertionError, match="env_prefix")`。計 44 passed） |

- **T008 / FR-025 の未達理由**: 規則 (b) の正規表現は `get_provider(name).env_prefix` から組み立てる、が要件で
  あったが、暫定表を残していたため「provider が接頭辞を宣言していなくても走査が成立する」状態だった。
  `XProvider.env_prefix = "XTR"`（`providers/x.py:88`）と `YouTubeProvider.env_prefix = "YTR"`
  （`providers/youtube.py:23`）が既に実装済みのため、暫定表は不要である。
- **変異探針1**（復元後に sha256 一致を確認）: `providers/x.py` の `env_prefix = "XTR"` を `None` へ置換 →
  `AssertionError: provider 'x' の env_prefix を解決できませんでした…` で
  `test_platform_literals_are_confined_to_registry` が**失敗**（ガードが実際に効くことを確認。他の 3 件は passed）。
- **変異探針2**（同）: `_env_prefixes()` の `raise` を黙って `return prefixes` する形へ戻すと
  `test_env_prefix_guard_fails_loudly_when_unresolvable` が**失敗**（追加テストは非空虚）。
- 復元後は毎回フルスイートを再実行して確認した（`600 passed / 96.63% / 46.51 秒`。探針1 の前は 599 passed、
  テストを 1 件追加して 600 件になった）。

### 2. 基準値のずれ（spec は変更しない）

| 論点 | spec の記述 | 実測 | 対応 |
|---|---|---|---|
| `TR_MAX_RESULTS` の到達範囲（FR-015） | 「設定値の優先順位（明示指定 > 環境変数 > 指示本文の自然言語 > LLM の解釈）を維持 MUST」 | 変更前の `__main__.py` はグラフへ `max_results=args.max_results or 5` を渡しており、環境変数は `config.max_results`（stderr の「要求件数」表示のみ）に効いていた。変更後は `Configuration.load()` の解決値（環境変数を含む）が `configurable` に載るため、**`--max-results` 未指定かつ `TR_MAX_RESULTS` / `XTR_MAX_RESULTS` 設定時**は解析件数がその値になる | T047 で設定を `Configuration` の 1 経路に統一した結果。FR-015 が定める順序（環境変数 > 指示本文）へ**整列する方向**であり、CLI オプションを指定したときの結果・stdout / stderr の分離・終了コード・golden は不変（golden 採取時は `TR_*` / `XTR_*` / `YTR_*` を遮断している。T004 / T050） |
| mypy の対象ファイル数 | plan.md / quickstart.md は `26 source files` | `rendering.py` の追加で **27 source files**（T064 実測） | 判定条件（0 件）は不変。数を固定している記述は spec ではなく実行時の出力であるため、ここに差分として記録する |
| テスト件数・カバレッジ・実行時間（SC-010） | 基準 547 passed / 95.29% / 49.67 秒 | 598 passed / **96.63%** / **49.15 秒**（T064 実測。60 秒以内） | 追加 51 件（US1〜US4 の新規テスト）に対して増加は 1.34 ポイント、時間はむしろ短縮。判定は `uv run pytest -q`（カバレッジ込み）で行う |
| プラットフォーム名の混入 | 15 箇所（文単位） | 走査で 16 行（`config.py` の引数既定値 1 件が集計外） | SC-002 の判定は終状態 2 行で行う（`plan.md` の「基準値のずれ」） |
| 設定の重複項目 | 7 項目 | 3 フィールド（`max_results` / `transcript_language` / `cache_dir`）＋ 引数 `platform` 1 | SC-003 の判定は「同名項目の定義箇所が 1 つ」の終状態で行う |
| レポート出力の一致（SC-006） | 「変更前と完全に一致」（Markdown と JSON の両方） | `render_json` は `report.model_dump_json` のため、FR-008 / FR-009 で削除する `use_trends` と `table_for` が JSON から消える | Markdown は byte 一致を維持。JSON は当該 2 キーのみ除外して比較し、**意図的な差分**として記録（RND-003 / REM-003 / REM-004） |
| `platform` の既定値（FR-007） | 既存フィールドの「型・**意味**」を変えてはならない MUST NOT | `ResearchInstruction.platform` / `Candidate.platform` の既定を `"x"` → `""` にする | FR-002 / SC-002 を満たすための必要な例外。空文字は登録の先頭（= `x`）として解決され**実行時の結果は同一**（`plan.md` の「設計上の解釈」）。golden は既定に依存させない（T004） |
| 数値でない `TR_MAX_RESULTS`（SET-011） | 「既定値 5（例外にしない。現行と同じ）」 | 現行実装は `int()` で `ValueError: invalid literal for int()` になる（既存テスト `test_non_integer_numeric_setting_raises` が固定） | T039 の指示「期待値は変更前と同一」に従い**例外を維持**する（挙動を変えない）。SET-011 の記述を根拠に黙って既定へ落とすと既存テストと矛盾する |
| パッケージの公開面（SET-012 / T048） | 「`Config` の re-export を削除（`__all__` から除く）」。T048 の指示は「`Configuration` と `render_report` の re-export は**維持**する」 | 実測では `Configuration` は `__init__.py` で re-export されておらず（`hasattr(trend_researcher, "Configuration")` が `False`）、公開されているのは旧 `Config` のみ | `Config` の削除のみを行い、`Configuration` の公開は**追加しない**（公開面を広げる変更は範囲外）。T048 の「維持」は「現状を変えない」と読む |

### 3. golden の決定論（T007）

| 項目 | 記録内容 | 実測 |
|---|---|---|
| 2 回採取の一致 | `git status --short tests/unit/golden/` | **空（byte 一致。決定論を確認）** |
| 判定方法 | Markdown は byte 比較 / JSON は `use_trends` / `table_for` の 2 キーを両側で除去してから byte 比較 | 実装どおり（`tests/unit/test_rendering.py` の `_normalize_json` / `JSON_EXCLUDED_KEYS`） |
| 除外キーの正当性 | 除外は RND-003 の 2 キーのみ。他のキーの差は失敗として扱う | `JSON_EXCLUDED_KEYS = frozenset({"use_trends", "table_for"})` のみ。他キーの差は比較に残る |

**決定論の担保（T007 の実測で判明した唯一の非決定要因）**: `ResearchReport.generated_at` は
`default_factory=datetime.now` であり、`render_json` は `model_dump_json` を返すため
**そのままでは JSON が毎回変わる**。`build_golden_cases()` が `FIXED_GENERATED_AT`
（`2026-01-01T00:00:00Z`）を明示的に渡すことで決定論にしている（T004 で対応済み）。
Markdown 側は `generated_at` を出力しないため影響しない。

### 4. 更新・削除したテスト（SC-008）

T037 で `contracts/removal-rationale.md` の REM-001〜REM-009 と実測を突き合わせた結果（削除した
テストと、その後に追加した不在断言の件数）:

| テスト | 固定していた内容 | 処置（実測） | REM |
|---|---|---|---|
| `tests/unit/test_cache.py` | JSON の往復 | `read_json` の節 **5 件を削除**し、契約の列挙から読み戻しを除いた。不在断言 1 件を追加（計 12 passed） | REM-001 |
| `tests/unit/test_x_search.py` | 1 件取得時の本文連結 | `fetch_thread` の節 **11 件を削除**し、**同じ 11 件を `fetch_threads` の 1 件経路（`_threads()` ヘルパ）へ移設**（リプライ上限 5 → 既定 3）。不在断言 1 件を追加。T043 で `config=` → `configuration=` へ追随し、`Config(search_pool_size=50, max_retries=2)` は環境変数（`XTR_MAX_RETRIES=2`）へ移した（テスト名も `..._come_from_settings` へ変更）＋ `XSettings` の解決テスト 6 件を追加 | REM-005 / SET-003 |
| `tests/unit/test_config.py` | `TR_*` > `XTR_*`/`YTR_*` > 既定 | T025 で `Config.load(env_prefix=...)` へ、T039 で `Configuration.load()` / `resolve_env()` へ移行。`get_config` / `cache_clear` の節（2 件）と `OPENAI_*` / `model` の節（3 件）を削除し、`load()` のキャッシュ無し・明示指定優先の節（計 30 passed）へ置換 | REM-006 / REM-007 / SET-002 / SET-010 |
| `tests/unit/test_youtube_search.py` / `tests/unit/test_platform_extension.py` | provider の `config` 引数 | 引数名を `configuration` へ追随（署名とテストの語彙のみ。期待値は不変） | SET-001 |
| `tests/unit/test_configuration.py` | `DEFAULTS` 8 キー | `use_trends` を `DEFAULTS` と 3 テストから削除し、falsy パラメータを `published_after` へ差し替え。不在断言 1 件を追加 | REM-003 |
| `tests/unit/test_progress.py` | 進捗行の書式と `TOTAL` | 新シグネチャへ書き換え（書式の断言は維持、2 件追加で 13 件） | REM-008 |
| `tests/unit/test_parse_instruction.py` | `use_trends` と `transcript_language` の優先順位 | `transcript_language` のみを残して整理し、不在断言（`AgentInputState` / `AgentState`）を追加 | REM-003 |
| `tests/unit/test_models.py` | 既定値の宣言 | 該当なし（`table_for` を固定していた節は存在しなかった）。不在断言 2 件を追加 | REM-004 |
| `tests/unit/test_compile_report.py` | レポート本文 | T021 の移設後も**無修正で 45 passed**（出力不変の証跡）。US4 で `test_rendering.py` へ移動 | REM-009 |
| `tests/unit/test_compile_report.py` | 描画の断言 16 件 | **T061 で `tests/unit/test_rendering.py` へ移動**（断言は 1 件も削除せず、必要なヘルパ `_candidate` / `_analysis` / `_render_report` / `_markdown` も同伴。`_instruction` は golden 用ヘルパと衝突するため `_render_instruction` に改名）。ノード側に残した 3 件は「`report` が状態に入る」「`cache.write_json` が呼ばれる（`test_report_is_persisted_when_cache_dir_is_set`）」「描画が呼ばれる（`test_progress_messages_end_with_summary_and_rendered_markdown`）」。移動後 `test_rendering.py` 26 件 ＋ `test_compile_report.py` 20 件が緑 | REM-009 / SC-008 |
| `tests/unit/test_compile_report.py` | `test_render_markdown_resolves_provider_from_report_not_argument` | **削除**（FR-017 により引数の provider が使われるようになった。旧挙動＝欠陥を固定していた断言で、T053 が同箇所を逆方向に固定する。他の描画断言は上記のとおり移動） | REM-009 |
| `tests/integration/test_full_flow.py` | `render_report(report)` の 4 箇所 | 描画の入口が `render_report(report, provider)` になったため、テスト側に `_render(report)`（`report.instruction.platform` から provider を解決）を追加して置換（描画の断言内容は不変） | REM-006 / REM-007 |
| `tests/unit/test_platform_extension.py` | `from trend_researcher.graph import render_report` | import 元を `trend_researcher.rendering` へ変更し、既存の `provider = get_provider(dummy_platform)` をそのまま引数に渡す | REM-006 |
| `tests/unit/test_cli_entry.py` | `cli.render_report` のスタブ | 1 引数の lambda を 2 引数（`report, provider`）へ変更（呼び出し契約が変わったため） | REM-006 |
| `tests/integration/test_cli_contract.py` | `--trends` の受理 | **該当節は存在しなかった**（`grep -rn -- "--trends" tests/` が 0 件）。T032 の記載とのずれとしてここに記録し、ファイルは無修正 | REM-003 |
| `tests/unit/test_config.py` | `.env` を読むヘルパの名前（`_load_env_once`）と `Configuration.load()` からの呼び出し | T071 で `load_env` へ改名（calls 3 件 ＋ テスト名 2 件を追随）。呼び出しが `config.py` の 1 箇所であることを固定する走査テスト **1 件を追加**（計 41 passed） | SET-002 / FR-013 |
| `tests/unit/test_llm.py` | `build_model` が自前で `load_dotenv()` を呼ぶこと | T071 で `test_env_loading_is_invoked` を `test_env_loading_is_invoked_through_the_shared_loader` へ置換（境界が `config.load_env()` を通ることを固定）。autouse フィクスチャの遮断先を `config_module.load_dotenv` へ変更 | SET-002 / SET-009 |
| `tests/unit/test_platform_scan.py` | `env_prefix` の暫定表 `_ENV_PREFIX_FALLBACK`（US1 時点の暫定。T008 の「`get_provider(name).env_prefix` から組み立てる」が未達になる） | T073 で暫定表とフォールバック分岐を削除し、`env_prefix` を解決できない provider があれば**走査を中断して失敗**させる。ガードの非空虚性を固定するテスト **1 件を追加**（計 44 passed） | T008 / FR-025 |
| `tests/integration/test_full_flow.py` | 進行・7 行・件数 | `Config` 依存のみ追随（`env_prefix=` へ）。進捗 7 行の断言は**維持したまま緑** | REM-006 / REM-007 |

**削除対象 5 件の残存参照（T037 実測）**: `src/` は全件 **0**。`tests/` に残るのは不在断言と
説明コメントのみ（`read_json` 3 / `COMPILE_REPORT_PROMPT` 0 / `use_trends` 14 / `table_for` 6 /
`fetch_thread` 3 / `--trends` 1）。

### 5. 最終ゲート（T069）

**Date**: 2026-09-13。判定コマンドは `uv run pytest -q`（カバレッジ込み。実行時間の判定もこのコマンドで行う。SC-010）。

| ゲート | 基準 | 実測 |
|---|---|---|
| `uv run pytest -q` | 全件 green・カバレッジ 90% 以上・**60 秒以内**（SC-010 / `fail_under = 90`） | **598 passed / 96.63%（TOTAL 97%）/ 48.44 秒**（wall 計測 49.75 秒。exit=0）。基準（547 passed / 95.29% / 49.67 秒）に対し **+51 件・+1.34 ポイント・−1.23 秒** |
| `uv run ruff check .` | 0 件 | **All checks passed!**（exit=0） |
| `uv run mypy src` | 0 件 | **Success: no issues found in 27 source files**（plan / quickstart の表記は 26 だが、`rendering.py` の追加で 27。§2 のずれ表に記録済み） |
| `git diff -- pyproject.toml` | `[project].dependencies` / `optional-dependencies` に差分なし（FR-024） | **差分なし**（`git diff $(git merge-base HEAD main)..HEAD -- pyproject.toml` が空）。現在値: `dependencies` 7 件（`langgraph` / `langchain` / `langchain-openai` / `twscrape` / `yt-dlp` / `pydantic` / `python-dotenv`）、`optional-dependencies.dev` 8 件。**新しい実行時依存は追加していない** |
| quickstart 6-1 の再実行 | 旧設定型（`Config` / `get_config` / `Config.load`）が 0 件 | **OK: 0 件**（`grep -rn "class Config\b\|def get_config\|Config\.load" src/ --include=*.py`） |
| 作業ツリー | 意図しないファイルなし | `git status --short --untracked-files=all` → **出力なし** |
| CLI の不変条件（参考） | `--help` に `--trends` が無い／未登録プラットフォームは exit 2 | `grep -c -- "--trends"` → **0**、`--platform bogus` → **exit=2** |

- **部分適用・`# noqa` による回避は行っていない**（ruff は 0 件、mypy も 0 件で、抑制コメントの追加なし）。
- 結論: 4 つのゲートすべてが基準を満たし、US1〜US4 の成果がこの作業ツリーで同時に緑である。

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

---

## Phase 8: Convergence

> T069 のゲート green 後に、`spec.md` / `plan.md` / `tasks.md` を意図の唯一の出所として現状の
> コードを評価した結果、未達・部分達成と判定した残作業（実測 2026-09-14）。既存タスクの
> 書き換え・再番号付けはしていない。`spec.md` / `plan.md` は変更しない。

- [X] T070 `contracts/settings-contract.md` の記述を実装の実態に合わせて訂正する per SET-011 / SET-005 (contradicts)
      （実測: 非数値の `TR_MAX_RESULTS` は `ValueError: invalid literal for int() with base 10: 'abc'` を投げ、
      `tests/unit/test_config.py:197 test_non_integer_numeric_setting_raises` がそれを固定している。T039 の指示
      「期待値は変更前と同一」に従い**例外を維持**する判断は `## 実装メモ` の「2. 基準値のずれ」に記録済みだが、
      SET-011 の「既定値 5（例外にしない。現行と同じ）」は実装と矛盾したまま残っている。同じく SET-005 は
      「既存 7 項目の名前・型・既定値」を不変としているが、`Configuration.platform` の既定は `"x"` → `""` へ
      変更済み（FR-002 / SC-002。空文字は登録の先頭＝`x` に解決されるため解決結果は変わらない）。契約の当該行を
      「例外を維持する」「既定値は解決結果を変えない範囲で変更した」へ訂正する。`spec.md` は触らない）
- [X] T071 `.env` の読み込みを 1 経路に寄せる、または境界の例外として契約に明記する per FR-013 (partial)
      （実測: `load_dotenv` の呼び出しは 2 箇所 — `config.py:36` の `_load_env_once` と `tools/llm.py:34` の
      引数なし `load_dotenv()`。FR-013 は「環境変数・`.env` の解決も同じ型の読み込み処理に集約 MUST」、
      SET-002 は「`.env` は `Configuration.load()` の経路で 1 回」とし、SET-009 が境界として認めているのは
      `OPENAI_*` の解決である。`tools/llm.py` の `.env` 読み込みを `config._load_env_once()` へ寄せて呼び出しを
      1 経路にし、Studio 経路（`Configuration.load()` を通らない実行）でも `.env` が読まれることをテストで
      固定する。寄せない場合は `settings-contract.md` に例外として明記する）
- [X] T072 `quickstart.md` 手順 6-1 の検証コマンドを偽陽性にならない形へ直す per SC-003 (partial)
      （実測: 手順 6-1 の `grep -rn "class Config\b\|def get_config\|Config\.load" src/` は
      `src/trend_researcher/__pycache__/config.cpython-312.pyc` に一致して **exit 0** になり、
      `|| echo "OK: 0 件"` が発火しない＝手順どおりに実行すると失敗して見える。同じ節の 6-2（224 行目）には
      `--include=*.py` が付いており 6-1 だけが漏れている。`--include=*.py` を付けると 0 件。quickstart 内の
      他のディレクトリ走査コマンドも、テスト実行後（`__pycache__` が存在する状態）のツリーで成立することを点検する）
- [X] T073 `tests/unit/test_platform_scan.py` の暫定表 `_ENV_PREFIX_FALLBACK` を削除する per T008 / FR-025 (partial)
      （実測（変異探針・復元確認済み）: `_ENV_PREFIX_FALLBACK = {"x": "XTR", "youtube": "YTR"}`（57 行目）を
      空 dict に置き換えても `test_platform_scan.py` は 4 passed ＝ 死んだ経路。`XProvider.env_prefix = "XTR"`
      （`providers/x.py:88`）と `YouTubeProvider.env_prefix = "YTR"`（`providers/youtube.py:23`）が実装済みで、
      T008 が要求した「正規表現は `get_provider(name).env_prefix` から動的に組み立てる」が成立する。暫定表を
      削除し、`env_prefix` を解決できない provider が現れた場合は走査側が明示的に失敗して規則 (b) の対象から
      黙って外れないようにする。削除後に走査テスト・`tests/unit/test_providers.py` が緑であることを確認する）
- [ ] T074 `tests/unit/test_configuration.py` の件数の記述を実態に合わせる per FR-019 (partial)
      （実測: module docstring の「1. 宣言されたフィールドと既定値（`published_after` を含む **8 件**）」に対し、
      `DEFAULTS` は 7 キー（`use_trends` は T032 で削除済み）。挙動には影響しないが、内部構造の更新に追随して
      いない記述であり、`## 実装メモ` の「4. 更新・削除したテスト」に記録した更新内容（`DEFAULTS` から
      `use_trends` を削除）と食い違っているため 7 件へ直す）
