---

description: "Task list for テスト拡充によるパイプライン信頼性の向上"
---

# Tasks: テスト拡充によるパイプライン信頼性の向上

**Input**: Design documents from `/specs/001-test-suite-hardening/`

**Prerequisites**: `plan.md`（必須）, `spec.md`（必須・4 ユーザーストーリー）, `research.md`（R-1〜R-9）, `data-model.md`（エンティティと契約）, `contracts/`（CLI-001〜006 / LAYOUT-001〜006 / COV-001〜006）, `quickstart.md`（受け入れ手順）

**Tests**: **必須**（憲法 原則 I「テスト必須（NON-NEGOTIABLE）」）。本機能の成果物そのものがテストであるため、全ユーザーストーリーのテストタスクは省略できない。

**Organization**: ユーザーストーリー単位で構成し、各ストーリーを独立に実装・検証できるようにする。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 並列実行可能（異なるファイル・未完了タスクへの依存なし）
- **[Story]**: 所属するユーザーストーリー（US1 / US2 / US3 / US4）
- すべてのタスクに正確なファイルパスを記載

## Path Conventions

単一プロジェクト（`src/` レイアウト）。パスはリポジトリルート（`/home/takumi/github/trend-researcher`）からの相対。

## 全体像

| Phase | 内容 | タスク | 対応要件 |
|-------|------|--------|----------|
| 1 | Setup（テスト基盤） | T001〜T004 | FR-018 |
| 2 | Foundational（共有フィクスチャ） | T005〜T007 | FR-001 / FR-010 / FR-021 |
| 3 | **US1: CLI 外部契約（P1）🎯 MVP** | T008〜T018 | FR-002〜FR-008 / FR-015 / FR-023 / FR-025 |
| 4 | US2: 外部境界の失敗経路（P2） | T019〜T026 | FR-009 / FR-010 / FR-013 / FR-014 / FR-024 |
| 5 | US3: LLM 自由文の解釈（P3） | T027〜T031 | FR-011 / FR-012 |
| 6 | US4: テスト有効性の監査（P4） | T032〜T039 | FR-016 / FR-017 / SC-004 / SC-006 |
| 7 | Polish（横断・品質ゲート） | T040〜T046 | FR-018〜FR-022 / 憲法 V / 憲法（開発ワークフローと品質ゲート） |

**合計 46 タスク** / 並列可能 18 タスク

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: テスト基盤の初期化と依存の追加。既存テストは変更しない。

- [X] T001 `pyproject.toml` の `[project.optional-dependencies].dev` に `pytest-cov>=5.0.0` を追加し、`[tool.pytest.ini_options].testpaths = ["tests"]` を設定して `uv sync --extra dev` を実行する（COV-001-4 / LAYOUT-001-7）
- [X] T002 [P] `tests/conftest.py` を新規作成する（共有フィクスチャの置き場所。docstring と import のみ。憲法 原則 I の配置規約 / LAYOUT-001-5）
- [X] T003 [P] `tests/integration/conftest.py` を新規作成する（層固有フィクスチャの置き場所。憲法 原則 I の配置規約 / LAYOUT-001-5）
- [X] T004 変更前のベースラインを記録する（`uv run pytest -q` が 61 passed、`uv run pytest -q --cov=trend_researcher --cov-report=term-missing` の合計が **82%（1,206 文 / 未実行 214）**、`uv run pytest -q --collect-only | grep -c "::"` が 61 件。`research.md` R-2 / R-4 と `contracts/coverage-policy.md` COV-003 の値に一致することを確認し、`## Implementation Notes` に記録する）

**Checkpoint**: テスト基盤が用意され、ベースラインが再現する

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 全ユーザーストーリーが使う共有フィクスチャ。この Phase が完了するまでストーリーの作業を始められない。

**⚠️ CRITICAL**: 境界モックと非決定性の固定が不十分なままテストを書くと、憲法 原則 II（オフライン）と FR-021（決定性）に違反するテストが量産される。必ず先に完了させる。

- [X] T005 `tests/conftest.py` に境界モックフィクスチャ 5 種（`fake_x_search` / `fake_x_threads` / `fake_yt_search` / `fake_yt_transcript` / `fake_model_factory`）を実装する。差し替え対象は `tools/` / `providers/` の境界に限定し、`nodes/` の内部関数は差し替えない（data-model 1.2 / LAYOUT-003-3）。`fake_model_factory` はノード単位で応答を指定できる形にし、プロンプト本文の部分一致によるディスパッチを実装しない（R-7 / LAYOUT-004-4）
- [X] T006 `tests/conftest.py` に非決定性固定フィクスチャ 3 種（`frozen_now` / `no_retry_sleep` / `tmp_cache_dir`）を実装する。`frozen_now` は `MagicMock(wraps=datetime)` で `now` のみ固定し `fromisoformat` は実物へ委譲する。`no_retry_sleep` は `trend_researcher.tools.x_search.asyncio.sleep` をスパイし、観測した待機値を断言できるようにする。`tmp_cache_dir` は実リポジトリの `cache/` を汚さない（data-model 1.2 / FR-010 / LAYOUT-003-4 / LAYOUT-004-1）
- [X] T007 `tests/unit/test_fixtures.py` を新規作成し、T005・T006 の各フィクスチャが**実際に境界を差し替えている**ことを検証する（例: `fake_x_search` 適用中に本物の境界を呼ぶと失敗すること、`no_retry_sleep` 適用中に実時間が消費されないこと）。静かに無効化されたフィクスチャは憲法 原則 I の「収集されない fixture」と同じ欠陥クラスである（FR-016 の「無効なテストの排除」/ LAYOUT-005-3）

**Checkpoint**: 共有フィクスチャが動作し、実効性がテストで担保された

---

## Phase 3: User Story 1 - CLI の外部契約を回帰から守る (Priority: P1) 🎯 MVP

**Goal**: CLI の終了コード 0/1/2 と stdout/stderr の分離を、**実行プロセスの観測結果**として固定する。あわせて進捗総数とグラフのノード数の整合を固定し、既知の実装欠陥 2 件（`--output` 書き込み失敗の Traceback / 空指示の素通し）を最小修正する。

**Independent Test**: `uv run pytest -q tests/integration/test_cli_contract.py tests/integration/test_graph_wiring.py tests/unit/test_progress.py` が完走する。外部 I/O は模擬され、ネットワークと認証情報を要求しない。

**契約**: `contracts/cli-contract.md`（CLI-001〜006）、`contracts/test-layout.md`（LAYOUT-004 / LAYOUT-006）

### Tests for User Story 1 (MANDATORY - 憲法 原則 I) ⚠️

> **NOTE**: `main()` の戻り値だけの検証は契約の検証とみなさない（FR-002）。終了コード・stdout・stderr は必ず実行プロセスから観測する。

- [X] T008 [US1] `tests/integration/cli_harness.py` を新規作成する。境界モックを注入してから CLI の `main()` を呼ぶ起動スクリプト。ファイル名を `test_` で始めないことで pytest の収集対象から外し、シナリオは環境変数で選択する（LAYOUT-001-6 / plan.md Structure Decision）
- [X] T009 [US1] `tests/integration/conftest.py` に `cli_runner` フィクスチャを実装する。`sys.executable tests/integration/cli_harness.py <CLI 引数>` を `subprocess.run` で起動し、`(exit_code, stdout, stderr)` を返す。環境変数は呼び出しごとに明示的に組み立て、実認証情報を継承しない（data-model 1.2 / LAYOUT-004）
- [X] T010 [P] [US1] `tests/integration/test_cli_contract.py` を新規作成し、**層 A（引数エラー経路）**の契約テストを書く。モック不要で `sys.executable -m trend_researcher` を直接起動（`python` は使わない。LAYOUT-003 の実行環境依存を避ける）し、CLI-001-6（`--help` → 0）、CLI-001-10〜16（未知プラットフォーム / 位置引数欠落 / `--platform` 欠落 / `--since` 不正 / 未知 `--format` / 未知 `--sort` / `--max-results` 非整数 → いずれも 2）、CLI-001-17（空文字・空白のみの指示 → 2。**T017 で修正するまで失敗する**）、**列挙値の大文字小文字を正規化しない**こと（`--platform X` → 2）、CLI-002-3（stdout が 0 バイト）を固定する。各テストの docstring に契約 ID を書く（FR-004 / SC-003 / LAYOUT-002-1〜4）
- [X] T011 [US1] `tests/integration/test_cli_contract.py` に**層 B（成功経路）**の契約テストを追加する。CLI-001-1（0）、CLI-002-1 / CLI-002-2（stdout = レポートのみ・進捗行なし）、CLI-002-4（stderr に 7 ノード分の進捗）、CLI-002-5（stderr にログ・情報・警告）、CLI-003-1〜5（`--format json` が単一の JSON で `instruction.output.format == "json"`、Markdown の見出しが混入しない）、CLI-004-1〜5 / CLI-004-7（レポートの見出しと出典）を固定する。実グラフ + 境界モックで検証する（FR-003 / SC-003 / plan.md Complexity Tracking）
- [X] T012 [US1] `tests/integration/test_cli_contract.py` に**層 B（0 件・件数不足・出力先）**の契約テストを追加する。CLI-001-2（0 件 → 0）、CLI-001-3（件数不足 → 0）、CLI-004-6（共通テーマ 0 件 → `（特筆すべき共通点なし）`）、CLI-001-4 / CLI-002-6 / CLI-002-7（`--output` → stdout 0 バイト・ファイルに書き出し・stderr に完了メッセージ）を固定する（FR-006 / FR-007 / FR-008 / SC-003）
- [X] T013 [US1] `tests/integration/test_cli_contract.py` に**層 B（実行時エラー）**の契約テストを追加する。CLI-001-7（例外 → 1）、CLI-001-8（時間上限 → 1）、CLI-001-9（レポート欠落 → 1）を固定し、いずれも stdout が 0 バイトで stderr に `[エラー]` / `[警告]` が出ることを検証する。CLI-002-5（stderr にログ・情報・警告・エラーが出る）もあわせて固定する（FR-005 / SC-003）
- [X] T014 [US1] `tests/integration/test_cli_contract.py` に**出力先の書き込み失敗**（CLI-001-5）の契約テストを追加する。存在しない親ディレクトリと既存ディレクトリを指定し、終了コード 1・stdout 0 バイト・stderr に `[エラー]` 形式のメッセージが出て **`Traceback` を含まない**ことを固定する。**この時点でテストが失敗することを確認する**（research.md R-9 の欠陥を先に固定する）
- [X] T015 [P] [US1] `tests/unit/test_progress.py` を新規作成し、`ProgressEmitter` の出力形式（開始・完了）、`get_messages()` の蓄積、`TOTAL == len(NODE_ORDER)` を固定する。`TOTAL` を変更すると落ちること（data-model 1.6 の M3 の対）を確認する（LAYOUT-006-1 / LAYOUT-006-4）
- [X] T016 [P] [US1] `tests/integration/test_graph_wiring.py` を新規作成し、ノード順（`parse_instruction` → … → `compile_report`）、`search` の 0 件ルーティング（`skip` / `continue` の両分岐）、`len(NODE_ORDER)` とグラフに `add_node` されたノード数の一致、成功経路の進捗行数を固定する。`tests/test_graph.py` の後継である（FR-015 / LAYOUT-006-2 / LAYOUT-006-3）

### Implementation for User Story 1

- [X] T017 [US1] `src/trend_researcher/__main__.py` の `main()` を**2 箇所**最小修正する。（1）`--output` 書き込み（`Path(args.output).write_text(...)`）を `try/except OSError` で捕捉し、`[エラー] レポートを <PATH> に書き出せませんでした: <理由>` を stderr に出して `1` を返す（捕捉型は `OSError` に統一し、`FileNotFoundError` と `IsADirectoryError` の非対称を作らない。FR-023 / research.md R-9）。（2）引数解析の直後（外部接続より前）に、指示が空文字または空白のみなら `[エラー] 指示を指定してください。` を stderr に出して `2` を返す（FR-025 / CLI-001-17）
- [X] T018 [US1] `uv run pytest -q tests/integration/test_cli_contract.py` が green になることを確認し、続けて **T017 の 2 箇所をそれぞれ戻すと対応するテストが落ちる**ことを 1 件ずつ実測する（（1）は T014、（2）は T010 の CLI-001-17。変異探針の手順: 改変 → 失敗確認 → 復元 → `sha256sum` 一致 → スイート再実行 → `git status` 清浄。quickstart 手順 5.1。**2 箇所を同時に戻さない**）

**Checkpoint**: US1 完了。CLI の外部契約が独立に検証でき、既知の実装欠陥 2 件（`--output` 書き込み失敗の Traceback / 空指示の素通し）が修正されて回帰防止が入った

---

## Phase 4: User Story 2 - 外部サービスの失敗経路でも壊れないことを保証する (Priority: P2)

**Goal**: X の検索・スレッド取得、YouTube の字幕取得、中間成果物の書き込み、環境設定の解決が失敗したときに、パイプラインが落ちずに縮退し、理由が利用者へ伝わることを固定する。

**Independent Test**: `uv run pytest -q tests/unit/test_x_search.py tests/unit/test_transcript.py tests/unit/test_youtube_search.py tests/unit/test_cache.py tests/unit/test_config.py tests/unit/test_compile_report.py tests/unit/test_providers.py tests/integration/test_full_flow.py` が完走する。各境界を例外・空応答・部分応答で呼び出し、戻り値と通知のみを検証する。

**契約**: `contracts/test-layout.md`（LAYOUT-003-1〜5）、`contracts/coverage-policy.md` COV-004 の未実行行表

- [X] T019 [P] [US2] `tests/unit/test_x_search.py` を強化する。リトライ枯渇（`attempts=3` と `sleeps=[1, 2, 4]` をスパイで観測し実時間を消費しない。`no_retry_sleep` を使う）、`fetch_threads` の失敗、likes プール（`search_pool_size`）、`Providers` の描画を追加する。**あわせて FR-024**: 複数クエリで同一 `id` が返る場合の重複除去（先勝ち）と取得順の維持、除去後のみ要求件数へ截断することを固定する（FR-009 / FR-010 / FR-024 / COV-004 の `tools/x_search.py` 未実行行・`providers/x.py` 未実行行）
- [X] T020 [P] [US2] `tests/unit/test_transcript.py` を強化する。json3 形式の `data.events` 経由の解析、`requested_subtitles` の欠落、`DownloadError`、空文字・空白のみの字幕、インラインタグとタイムスタンプの除去を固定する。副作用のない `Transcript` コンストラクタ検証は本物の分岐を通らないため削除候補とする（FR-013 / data-model 1.7）
- [X] T021 [P] [US2] `tests/unit/test_youtube_search.py` を強化する。投稿日の欠落、不正形式、未来日付、`None` の扱いを追加し、件数制限の重複ケースを統合する。YouTube は単一クエリのみを検索するため重複除去を要求しない（FR-024 の非対称）ことも固定する（FR-009 / FR-017）
- [X] T022 [P] [US2] `tests/unit/test_cache.py` を新規作成する。書き込み契約（配置・UTF-8・非 ASCII・`default=str`）と読み戻し契約（存在しない場合は例外ではなく `None`）を固定する（FR-014 / COV-004 の `cache.py` 未実行行 21-25 / 34-38）
- [X] T023 [P] [US2] `tests/unit/test_config.py` を新規作成する。環境変数の優先順位（`TR_*` > `XTR_*` / `YTR_*` > 既定）、`cache_dir` と `accounts_db` のパス解決、未設定・空文字の扱いを固定する（FR-019 の対象範囲 / COV-004 の `config.py` 未実行行）
- [X] T024 [P] [US2] `tests/unit/test_compile_report.py` を新規作成する。Markdown / JSON の描画、共通テーマが 0 件の場合の `（特筆すべき共通点なし）`、備考の選定基準と投稿日フィルタ（CLI-004-8）、候補 0 件の空レポート、**キャッシュ書き込み失敗を備考に記録して継続する**縮退を固定する（FR-009 / COV-004 の `nodes/compile_report.py` 未実行行 34 / 44-45 / 62-65 / 105-107 / 136-141）
- [X] T025 [US2] `tests/unit/test_providers.py` を新規作成する。provider レジストリ、未知プラットフォームの拒否、行描画（表ヘッダ・ラベル・件名）の差分を固定する（FR-009 / 憲法 原則 IV）
- [X] T026 [US2] `tests/integration/test_full_flow.py` を強化する。`_FakeModel` の**プロンプト部分一致ディスパッチを廃止**し、`fake_model_factory` によるノード単位の応答注入へ変更する（現状は `extract_common` のプロンプトが「関連」を含むため検索クエリ応答が返り、共通テーマが 0 件になる。R-7）。あわせて境界の失敗経路（部分応答・例外）を含む経路を追加する（FR-009 / data-model 1.3 のマトリクス）

**Checkpoint**: US2 完了。外部境界と永続化の失敗経路が独立に検証できる

---

## Phase 5: User Story 3 - LLM の自由文出力に対する決定的な解釈を固定する (Priority: P3)

**Goal**: LLM が返す揺れのある自由文から、件数・投稿日下限・出力形式・検索クエリ・共通テーマをどう解釈するかを分岐ごとに固定する。

**Independent Test**: `uv run pytest -q tests/unit/test_parse_instruction.py tests/unit/test_extract_common.py tests/unit/test_analyze_content.py tests/unit/test_parse.py tests/unit/test_plan_search.py` が完走する。固定の入力（指示文・LLM 応答の模擬）を与え、解釈結果のみを検証する。

**契約**: `contracts/test-layout.md`（LAYOUT-004-4）、`contracts/coverage-policy.md` COV-004 の未実行行表

- [X] T027 [P] [US3] `tests/unit/test_parse_instruction.py` を強化する。優先順位の 3 分岐（明示設定 > 本文の自然言語 > LLM の解釈）、漢数字と期間表現（「5件」「半年以内」）、明示的な日付（「2025-01-01 以降」）、解釈できない日付文字列（例外にしない）、構造化ブロックを返さない応答（トピック＝指示本文全体＋既定値）を固定する。`frozen_now` で時刻を固定する（FR-011 / COV-004 の `nodes/parse_instruction.py` 未実行行 54 / 61-64 / 72 / 75 / 102 / 112-117）
- [X] T028 [P] [US3] `tests/unit/test_extract_common.py` を新規作成する。見出しと本文のみの出力からのテーマ名・説明の抽出と全コンテンツへの紐づけ、空出力（テーマ一覧が空）、崩れた出力（見出しのみ・本文欠落）、表形式と箇条書きの両方の解釈を固定する（FR-012 / COV-004 の `nodes/extract_common.py` 未実行行 57-59 / 76-86）
- [X] T029 [P] [US3] `tests/unit/test_analyze_content.py` を新規作成する。ソースの整形、活用アイデア表の解析、列不足・見出しのみ・区切り行のみの行破棄（例外にしない）、構造化ブロックがない場合のフォールバック要約を固定する（FR-012 / COV-004 の `nodes/analyze_content.py` 未実行行 30 / 44 / 48 / 72-73）
- [X] T030 [P] [US3] `tests/unit/test_parse.py` を強化する。崩れた表（列不足・区切り行のみ・見出しのみ）と JSON ブロックを含まない応答を追加し、見出し・区切り行のスキップを検証する既存の重複ケースを統合する（FR-012 / FR-017）
- [X] T031 [P] [US3] `tests/unit/test_plan_search.py` を強化する。検索クエリからの年号・期間表現の除去、空になった行の破棄、クエリ数の上限を固定する（FR-012 / COV-004 の `nodes/plan_search.py` 未実行行 42 / 64）

**Checkpoint**: US3 完了。LLM 自由文の解釈が分岐ごとに独立して検証できる

---

## Phase 6: User Story 4 - 既存テストが「落ちるべきときに落ちる」ことを保証する (Priority: P4)

**Goal**: 既存・新規テストが対象の振る舞いを実際に検証していることを変異探針で確認し、無効なテストを強化・統合・削除して、その判断を記録する。

**Independent Test**: `uv run pytest -q` を実行し、各探針の改変でスイートが落ちることを確認する（改変は必ず元に戻す：復元 → `sha256sum` 一致 → 再実行 → `git status` 清浄）。

**依存**: US1（`test_graph_wiring.py` / `test_progress.py`）と US2（`test_compile_report.py`）の完了後に実施する。探針は**作業ツリーを改変するため、複数の探針を同時に実行してはならない**（結果が汚染され、判定を誤る）。

- [X] T032 [US4] `tests/unit/test_models.py` の恒真アサートを置換する。`test_report_sources_invariant` は断言が構築式と同一であり、`compile_report` の出典構築を `[]` にしても緑のままだった（M1 未検出）。`compile_report` の描画経路を通して `sources` を検証する形へ置き換える（data-model 1.7 / LAYOUT-005-3）
- [X] T033 [US4] **変異探針 M1** を実施する。`src/trend_researcher/nodes/compile_report.py` の出典構築を `[]` に改変し、`uv run pytest -q` が落ちることを確認して復元する。落ちなければ T032 / T024 を強化する（data-model 1.6）
- [X] T034 [US4] **変異探針 M2** を実施する。`src/trend_researcher/graph.py` の `_route_after_search` を常に `continue` に改変し、スイートが落ちることを確認して復元する。落ちなければ T016 を強化する（FR-015 / data-model 1.6）
- [X] T035 [US4] **変異探針 M3** を実施する。`src/trend_researcher/progress.py` の `ProgressEmitter.TOTAL` を 8 に改変し、スイートが落ちることを確認して復元する。落ちなければ T015 を強化する（FR-015 / data-model 1.6）
- [X] T036 [US4] 縮退処理に対する追加の探針を実施する（quickstart 手順 5.3）。リトライループの打ち切り、`tools/transcript.py` の形式判定を `_parse_vtt` のみに、`nodes/compile_report.py` のキャッシュ書き込みの `try` 除去、`cache.read_json` の例外化、`providers/x.py` の重複除去（`seen` 判定）の除去。5 件すべてが検出されることを確認する（SC-004）
- [ ] T037 [US4] 重複テストを統合し、旧ファイルを削除する。`tests/test_graph.py` の配線検証は `tests/integration/test_graph_wiring.py` へ、`tests/test_configuration.py` の設定検証は `tests/unit/test_configuration.py`（新規作成。旧ファイルの内容を吸収して強化）へ移したことを確認してから両ファイルを削除する。互換シムは残さない（FR-017 / 憲法 原則 VI / data-model 1.7）
- [ ] T038 [US4] 無効テストの判定記録を実績で更新する。`specs/001-test-suite-hardening/data-model.md` 1.7 の `resolution` 列（`strengthened` / `merged` / `removed` / `kept_with_reason`）と `evidence` 列を、実際の処置と変異探針の結果で埋める（FR-016 / SC-006）
- [ ] T039 [US4] テストの収集範囲と配置を監査する。`uv run pytest -q --collect-only` で件数を確認し、`tests/integration/cli_harness.py` が収集されていないこと、ルート直下にテストファイルが残っていないこと、`tests/unit/` と `tests/integration/` の 2 層に収まっていることを確認する（FR-016 / LAYOUT-001-1〜3 / LAYOUT-001-6 / LAYOUT-001-7）

**Checkpoint**: US4 完了。スイートの有効性が実測で担保され、無効テストの判断が記録された

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 品質ゲートと受け入れ判定。カバレッジ設定の有効化はこの Phase で行う（COV-001 のタスク順序制約）。

- [ ] T040 `pyproject.toml` に `[tool.coverage.run] source = ["trend_researcher"]`、`[tool.coverage.report] fail_under = 90` と除外設定、`[tool.pytest.ini_options].addopts = "--cov=trend_researcher --cov-report=term-missing"` を追加する。**カバレッジが目標に到達してから有効化する**（先行して有効化すると全テスト実行が赤になる。COV-001-1〜4 / COV-002）
- [ ] T041 `uv run pytest -q` を実行し、対象範囲の**合計**行カバレッジが 90% 以上であることを確認する。未達の場合は `contracts/coverage-policy.md` COV-004 の未実行行表に沿って該当ストーリーのテストを追加・強化する（個別モジュールの下限は要求しない。FR-019 / SC-002）
- [ ] T042 [P] `uv run ruff check .` を実行する。本機能で変更・新規作成したファイル（`tests/` 全体、`pyproject.toml`、`src/trend_researcher/__main__.py`）が違反 0 件であり、リポジトリ全体の違反件数がベースライン（40 件）から増えていないことを確認する（憲法 品質ゲート）
- [ ] T043 [P] `uv run mypy src` を実行する。`__main__.py` が違反 0 件であり、全体の件数がベースライン（37 件 / 12 ファイル）から増えていないことを確認する（憲法 品質ゲート）
- [ ] T044 `README.md` を契約に合わせて更新する。終了コード（0 / 1 / 2）、出力チャネルの分離（stdout = レポートのみ / stderr = 進捗・ログ・エラー）、`--output` の書き込み失敗時の挙動を `contracts/cli-contract.md` と一致させる（憲法 原則 V）
- [ ] T045 憲法 `TODO(BASELINE-BURNDOWN)` の追跡タスクを起票する。ベースライン（`ruff` 40 件 / `mypy` 37 件）と、`UP037` の自動修正が import 追加とセットで必要な点（`nodes/analyze_content.py` / `nodes/compile_report.py`）を記載する。本機能の完了条件には含めない（research.md R-8）
- [ ] T046 `quickstart.md` の受け入れ判定を全手順実施する。とくに（1）`uv run pytest -q` が全件 pass かつ **60 秒以内**（FR-020 / SC-001）、（2）`unshare -rn uv run pytest -q` が全件 pass（FR-001 / LAYOUT-003-1 / CLI-006-1〜3。CLI-006-3 は実測どおり `uv run pytest -q` が空の `OPENAI_API_KEY` で起動できることも確認する）、（3）単独実行・全体実行・順序変更で同一結果（FR-021 / SC-005）、（4）実行後に `git status --short` が清浄（テストが実リポジトリを汚さない）、（5）テスト件数が**純増**であり追加分を CLI 契約・失敗経路・LLM 解釈分岐の領域別に説明できる（SC-005）、（6）`git diff` で既存テストの期待値を実装の挙動へ書き換えていないこと（`tests/` の差分が「無効テストの強化・統合」と「新規テスト」に限られること。FR-022）

**Checkpoint**: すべての品質ゲートと受け入れ判定が green

---

## Dependencies & Execution Order

### Phase の依存関係

```text
Phase 1 (Setup)
    ↓
Phase 2 (Foundational)  ← ここまで全ストーリーのブロッカー
    ↓
    ├── Phase 3 (US1 / P1) 🎯 MVP
    ├── Phase 4 (US2 / P2)
    └── Phase 5 (US3 / P3)     ← US1・US2・US3 は相互に独立（並列可）
            ↓
        Phase 6 (US4 / P4)     ← US1（test_graph_wiring / test_progress）と
                                  US2（test_compile_report）の完了が必要
            ↓
        Phase 7 (Polish)
```

### ストーリー間の依存

| ストーリー | 依存 | 理由 |
|------------|------|------|
| US1（P1） | Phase 2 | 境界モックと `cli_runner` の基盤が必要 |
| US2（P2） | Phase 2 | 境界モックと非決定性固定が必要 |
| US3（P3） | Phase 2 | `fake_model_factory` と `frozen_now` が必要 |
| US4（P4） | **US1・US2** | 変異探針の対象テスト（`test_graph_wiring.py` / `test_progress.py` / `test_compile_report.py`）が存在して初めて「検出できるか」を測れる |
| Polish | 全ストーリー | カバレッジ設定の有効化は目標到達後（COV-001） |

### タスク内の依存

| タスク | 先行 | 理由 |
|--------|------|------|
| T005, T006 | T002 | `tests/conftest.py` が存在すること |
| T007 | T005, T006 | 検証対象のフィクスチャが必要 |
| T015, T016 | T009 | `cli_runner` と境界モックが必要（T015 は `TOTAL`、T016 はグラフ配線） |
| T010〜T014 | T009 | `cli_runner` が必要 |
| T011〜T014 | T010 | 同一ファイル（`test_cli_contract.py`）へ追記するため順序が固定 |
| T017 | T010, T014 | 失敗するテスト（CLI-001-17 と CLI-001-5）が揃ってから修正する（Red → Green） |
| T018 | T017 | 修正の green 化と 2 箇所の変異確認 |
| T033 | T032, T024 | M1 の探針は置換後のテストに対して行う |
| T034 | T016 | M2 の探針は配線テストに対して行う |
| T035 | T015 | M3 の探針は進捗テストに対して行う |
| T037 | T016, T027 以降 | 移設先のテストが揃ってから旧ファイルを削除する |
| T038 | T033〜T037 | 探針と統合の結果を記録する |
| T040, T041 | T019〜T039 | カバレッジ到達後にしきい値を有効化する（COV-001） |
| T046 | T040〜T045 | 最終の受け入れ判定 |

### ⚠️ 並列実行できないタスク（明示）

- **T005 と T006**: 同一ファイル `tests/conftest.py` を編集する。
- **T010 〜 T014**: 同一ファイル `tests/integration/test_cli_contract.py` を編集する。TDD の順序（引数エラー → 成功 → 0 件 → 実行時エラー → 書き込み失敗）を保つ。
- **T033 〜 T036**: 変異探針は `src/` を作業ツリー上で改変するため、同時に走らせると他方の改変が混入して判定が汚染される（crewcorp の実測で確認済みの失敗）。**必ず 1 件ずつ、復元と `sha256sum` 一致確認を挟んで直列に実施する。**
- **T042 と T043**: 独立しているが、T042 で自動修正を当てた場合は T043 の前に再実行する。

---

## Parallel Execution Examples

### Phase 1（Setup）

```bash
# T002 と T003 は別ファイル
# 並列グループ A
T002: tests/conftest.py を作成
T003: tests/integration/conftest.py を作成
```

### Phase 3（US1）— 最初の並列グループ

```bash
# T010 / T015 / T016 は別ファイル（T011 以降は T010 と同じファイルのため直列）
T010: tests/integration/test_cli_contract.py（層 A）
T015: tests/unit/test_progress.py
T016: tests/integration/test_graph_wiring.py
```

### Phase 4（US2）— 最大の並列グループ

```bash
# T019〜T024 はすべて別ファイル
T019: tests/unit/test_x_search.py
T020: tests/unit/test_transcript.py
T021: tests/unit/test_youtube_search.py
T022: tests/unit/test_cache.py
T023: tests/unit/test_config.py
T024: tests/unit/test_compile_report.py
# T025（test_providers.py）と T026（test_full_flow.py）は新規・既存が別ファイルのため同グループに追加可
```

### Phase 5（US3）— 全タスクが並列可能

```bash
# T027〜T031 はすべて別ファイル
T027: tests/unit/test_parse_instruction.py
T028: tests/unit/test_extract_common.py
T029: tests/unit/test_analyze_content.py
T030: tests/unit/test_parse.py
T031: tests/unit/test_plan_search.py
```

### Phase 7（Polish）

```bash
# T042 と T043 は別ツール・別対象
T042: uv run ruff check .
T043: uv run mypy src
```

### ⚠️ 直列実行が必須

```bash
# 変異探針（T033〜T036）は必ず 1 件ずつ。各件で以下を全部やる。
sha256sum <対象ファイル>          # 改変前
# 1 箇所だけ改変
uv run pytest -q                   # 落ちること
# 復元
sha256sum <対象ファイル>          # 一致を確認（不一致なら判定は無効）
uv run pytest -q                   # green に戻ったこと
git status --short                 # 残骸がないこと
```

---

## Implementation Strategy

### MVP First（US1 のみ）

1. **Phase 1（Setup）** を完了する（T001〜T004）。
2. **Phase 2（Foundational）** を完了する（T005〜T007）。ここが全ストーリーのブロッカー。
3. **Phase 3（US1）** を完了する（T008〜T018）。
4. **停止して検証**: `uv run pytest -q tests/integration/test_cli_contract.py tests/integration/test_graph_wiring.py tests/unit/test_progress.py` が完走し、T017 の 2 箇所の修正（空指示の拒否で T010 の CLI-001-17、`--output` の捕捉で T014）がそれぞれ green になることを確認する。
5. **この時点で価値が出る**: CLI の外部契約（終了コード 0/1/2 と stdout/stderr の分離）が回帰から守られ、検出済みの実装欠陥 2 件が修正される。仕様の P1 が満たされる。
6. **MVP の検証範囲**: FR-002〜FR-008 / FR-015 / FR-023 / FR-025（US1 のシナリオ 1〜9 と、空指示の拒否）。

### Incremental Delivery

1. Setup + Foundational → 基盤完成。
2. **US1** → CLI 契約が固定される（MVP）。`__main__.py` の欠陥も修正される。
3. **US2** → 外部境界の失敗経路が固定される（US2 単体で検証可能。US1 と並列でも可）。
4. **US3** → LLM 自由文の解釈分岐が固定される（US1・US2 と並列でも可）。
5. **US4** → スイート全体の有効性が実測で担保される（US1・US2 の完了後）。
6. **Polish** → カバレッジ 90%（合計）・実行時間 60 秒以内・静的品質・README 同期・受け入れ判定。

### タスクの粒度と注意点

- **各テストタスクは「書いて終わり」ではない**。そのタスクで追加したテストが対象の振る舞いを変異させると落ちることを、可能な範囲でその場で確認する（憲法 原則 I の「落ちるべきときに落ちる」テストのみを認める）。
- **失敗経路のテストは縮退処理を 1 つ取り除いて落ちることを確認する**。落ちなければ、そのテストは無効である（FR-016）。
- **`src/` の変更は `src/trend_researcher/__main__.py` の `main()` 内の 2 箇所（T017）のみ**である（`--output` 書き込み失敗の捕捉と、空指示の拒否）。それ以外の `src/` ファイルを変更しない。変異探針による一時改変は必ず復元し、`sha256sum` と `git status` で確認する。
- **カバレッジは合計値で判定する**（FR-019 / SC-002）。モジュール別の値は、合計 90% を満たすためにどの領域を埋めるかを示す目安であり、個別の下限ではない。ただし合計値の達成を理由に CLI 契約や失敗経路の検証を省略してはならない。
- **テスト件数は純増で判定する**（SC-005）。T037 の統合・削除により総件数が減ることは許容し、追加分を「CLI 契約 / 失敗経路 / LLM 解釈分岐」の領域別に説明できれば足りる。

---

## Notes

- **[P] の意味**: 異なるファイルを扱い、未完了タスクへの依存がない場合のみ付与。同一ファイルを編集するタスクには付けていない。
- **憲法 原則 I（NON-NEGOTIABLE）** により、全ストーリーにテストタスクを必須として置いた。省略は不可。
- **憲法 原則 II**: テストはネットワークと実認証情報なしで完走する。外部呼び出しの差し替えは `tools/` / `providers/` の境界でのみ行う（LAYOUT-003）。
- **憲法 原則 VI**: 旧テストファイルへの互換シムを残さない（T037）。
- 各 Phase の Checkpoint で停止し、独立に検証してから次へ進む。
- 検出した仕様・計画のずれは、実装中に本ファイル末尾の `## Implementation Notes` へ記録する。

---

## Implementation Notes

実装中に判明した仕様・計画のずれをここに記録する（実装完了時点では空）。

| 発見日 | 対象 | 仕様・計画の記述 | 実際 | 対処 |
|--------|------|------------------|------|------|
| — | — | — | — | — |

### T004: 変更前のベースライン（2026-09-12 実測）

| 観測項目 | 実測値 | 計画値（research.md R-2 / R-4、COV-003） | 一致 |
|----------|--------|------------------------------------------|------|
| `uv run pytest -q` | **61 passed**（0.48 秒） | 61 passed / 1.5 秒 | ✓ |
| `--cov=trend_researcher --cov-report=term-missing` の TOTAL | **1206 文 / 未実行 214 / 82%** | 1,206 文 / 214 未実行 / 82% | ✓ |
| `--collect-only` の件数（`grep -c "::"`） | **61** | 61 | ✓ |

実測に用いたコマンド:

```bash
uv run pytest -q
uv run pytest -q --cov=trend_researcher --cov-report=term-missing
uv run pytest -q --collect-only | grep -c "::"
```

### T018: 変異探針 — T017 の 2 箇所を個別に戻す（2026-09-12 実測）

**1 件ずつ実施**し、各件で「改変 → 失敗確認 → 復元 → `sha256sum` 一致 → フルスイート再実行 → `git status --short` 清浄」を完了させた。2 箇所を同時には戻していない。

| 変異 | 落ちるテスト | 実測 |
|------|--------------|------|
| （1）`--output` 書き込みの `try/except OSError` を外す | T014: `test_cli_001_05_output_write_failure[missing-parent]` / `[existing-directory]` / `test_cli_001_05_write_failure_has_single_error_line` | **3 failed / 150 passed** |
| （2）空指示ガード（`if not args.instruction.strip(): ... return 2`）を削除する | T010: `test_cli_001_17_blank_instruction[empty]` / `[spaces]` / `[tabs-and-newline]` / `[ideographic-space]` | **4 failed / 149 passed** |

復元後の `sha256sum` はいずれも変異前と一致（`286b5921953b24a816c7d42a31358ee5aba67b1fa168cb274a1fac96ef026390`）。復元後のフルスイートは両件とも **153 passed**。すなわち T017 の 2 箇所はそれぞれ独立したテストに守られている。

CLI-001-5 / CLI-001-17 は「実装を直す前に red を確認した」唯一の契約であり、変更前のベースライン（T004: 61 passed）でも対応するテストは存在しなかった。

### FR-024 修正: likes モードの重複除去漏れ（2026-09-13 実測）

T026 の統合テストで「複数クエリが同じ `id` を返す」境界応答（data-model 1.3 の `x_search` partial）を設計している最中に検出した。FR-023 に基づき本機能の範囲で修正した。

| 項目 | 内容 |
|------|------|
| 仕様（FR-024） | 「同一の識別子を持つ候補が複数の検索クエリの結果として重複して返る場合、X の検索は重複を除去し、取得順（関連度順）を維持 MUST」 |
| 修正前の実装 | 重複除去は relevance 分岐にのみ実装され、likes 分岐は `_sort_by_likes(pool)` で整列してから截断していた |
| 影響 | `--sort likes` で同一ツイートが複数の枠を占め、要求件数に達しない（5 件要求でも実質 3 件になる等） |
| 対処 | `_dedupe()` を切り出し、両分岐で「取得順の先勝ち・統合なし」の除去を適用 |
| 検証 | `tests/unit/test_x_search.py::test_x_provider_likes_dedupes_pool_before_sorting`。`_sort_by_likes(_dedupe(pool))` を `_sort_by_likes(pool)` に戻すと **1 failed / 38 passed**（修正前の状態を再現） |

### T026 で検出した未配線: `--cache-dir` がレポート永続化に届かない（2026-09-13 実測）

T026 のファイルシステム境界テスト（data-model 1.3 の `cache_dir ok / raises`）を設計している最中に検出した。FR-023 に基づき本機能の範囲で修正した。

| 項目 | 内容 |
|------|------|
| 仕様（FR-012 / FR-014） | `--cache-dir`（`Configuration.cache_dir`）に `report.json` を書き出す |
| 修正前の実装 | `compile_report` が `state.get("cache_dir")` だけを見ていた。`AgentInputState` に `cache_dir` の宣言が無く、`__main__._run_async` も `configurable` にしか入れないため、**CLI 経路では常に `None`**（実測: グラフ出力の `out.get("cache_dir")` → `None`） |
| 影響 | `--cache-dir` がレポート永続化に対して無効（フラグが黙って効かない） |
| 対処 | `state.get("cache_dir") or configurable.cache_dir` に変更（Studio 入力や途中再開による上書きは state を優先） |
| 検証 | `tests/integration/test_full_flow.py::test_report_is_written_to_the_configured_cache_dir`。`or configurable.cache_dir` を戻すと **2 failed / 17 passed**（`test_unwritable_cache_dir_is_recorded_and_the_run_succeeds` も併せて落ちる = 書き込み試行自体が起きていない証拠） |

同種の欠陥クラス（`state` だけを見て `configurable` にフォールバックしない読み取り）を全ノードで確認した: `platform` / `max_results` / `output_format` / `published_after` / `use_trends` / `sort_by` / `transcript_language` はいずれも `configurable` 優先または `state` フォールバックを持つ。該当したのは `cache_dir` のみ。

### T026: `prompts_for` が複数インスタンスのプロンプトを捨てる（2026-09-13 実測）

| 項目 | 内容 |
|------|------|
| 現象 | `analyze_content` は候補ごとに `build_model` を呼ぶが、`FakeModelFactory` は `self.models[node] = model` で最後の 1 インスタンスだけを保持し、`prompts_for` は 1 件しか返さなかった（実測: `prompts_for("analyze_content")` → 1 件） |
| 影響 | 「候補ごとに 1 回プロンプトが渡る」ことを固定できず、ノード単位注入（R-7）の検証が弱い |
| 対処 | ノード単位の共有リスト（`prompt_log`）を `_FakeLLM` に注入し、`prompts_for` は全インスタンス分を返す |
| 検証 | `test_node_responses_are_recorded_per_node`（`len(...) == 5`）。修正前は同テストが 1 件で失敗 |

### T026: 変異探針（2026-09-13 実測）

**1 件ずつ実施**し、各件で「改変 → 失敗確認 → 復元 → `sha256sum` 一致 → フルスイート再実行 → `git status --short`」を完了させた。

| 変異 | 落ちるテスト | 実測 |
|------|--------------|------|
| （1）`_route_after_search` を常に `"continue"` に固定（空検索の skip 分岐を除去） | `test_empty_search_skips_the_rest_of_the_pipeline[x-x_flow-ツイート]` / `[youtube-youtube_flow-動画]` | **2 failed / 17 passed** |
| （2）`cache_dir = state.get("cache_dir") or configurable.cache_dir` から後半を除去 | `test_report_is_written_to_the_configured_cache_dir` / `test_unwritable_cache_dir_is_recorded_and_the_run_succeeds` | **2 failed / 17 passed** |

復元後の `sha256sum` はいずれも変異前と一致（`graph.py`: `35552d6f9f4ab8e189cfab8f24c555bc90f0a2b2863f635d95a2c26919646252` / `compile_report.py`: `6ba5f03dec3f15d6bf1ecfaca3a85fe5d28ee5eca5b2d5f3a13bc40c893d26dd`）。復元後のフルスイートは **354 passed**（T025 完了時点は 339 passed）。

### T027 で検出した件数抽出の誤り（2026-09-13 実測）

`tests/unit/test_parse_instruction.py` の入力表を作るために `_extract_count_from_text` / `_extract_published_after_from_text` / `_period_to_date` を実測したところ、4 クラスの誤りが出た。いずれも FR-011（明示設定 > 本文の自然言語 > LLM の解釈）に反するか、解釈の取りこぼしになる。FR-023 に基づき本機能の範囲で修正した。

| 入力 | 修正前 | 修正後 | 原因 |
|------|--------|--------|------|
| `"2025年の動画"` | `2025` | `None` | `_extract_count_from_text` が本文中の最初の数字を無条件に拾っていた |
| `"5月の動画を3件"` | `5` | `3` | 同上（期間表現の月数を件数と誤認） |
| `"2025年の動画を10件調べて"` | `2025` | `10` | 同上（年号を件数と誤認） |
| `"十二件の動画"` | `2` | `12` | 漢数字が `一〜十` の 1 文字ずつの辞書で、`二` が先に一致していた |
| `"二三十件の動画"` | `2` | `None` | 位取りとして不正な数字列を解釈していた（`_to_number` が `None`、単位必須の正規表現で不一致） |
| `"三カ月以内の動画"` | `None`（期間が効かない） | カレンダー 3 か月前 | `_extract_published_after_from_text` が `三ヶ月\|3ヶ月\|三カ月\|3カ月` の列挙で、`十二ヶ月` など生成できない組み合わせを取りこぼしていた |

対処:
- `_to_number(text)`（算用数字／漢数字一〜九・十・十一〜九十九）を追加。`tens_text` / `ones_text` が 2 文字以上なら位取りとして不正とみなし `None`。
- `_PERIOD_EXPRESSION_RE` を追加し、件数抽出の**前**に年号・期間表現（`2025年` / `半年` / `最近30日` / `三カ月` など）を取り除く。取り除いたうえで `([0-9０-９]+)\s*(?:単位)?`、次に `([一二三四五六七八九十]+)\s*(?:単位)` を探す（漢数字は単位必須。`_COUNT_UNITS = "個|件|本|つ|カ国|か国|社|人"`）。
- 期間表現の正規表現を列挙から `[0-9０-９一二三四五六七八九十]+[ヶカ]?月` へ一般化（期間判定・件数除去で同じ語彙を使う）。

実装中に自分で入れた正規表現の不具合も検出している: `r"(?:半年|...|最近\s*[0-9０-９]+日)(?:\s*以内)?"` を最初 `r"\s*以内?"` と書いたため `\s*` と `?` の適用範囲がずれ、コンパイル済みのグループが `2025年` に一致しなくなっていた（`(?:\s*以内)?` に修正）。

### T027 で検出した FR-011 の取り違え: 明示指定 5 が未指定として扱われる（2026-09-13 実測）

| 項目 | 内容 |
|------|------|
| 現象 | `parse_instruction` の優先順位が `if input_max is not None and input_max != 5:` で、**state の明示指定が既定値と同じ 5 のときだけ**「未指定」と同一視され、本文の自然言語（例「20件」）に負けていた |
| 併存していた配線 | `__main__._run_async` が `initial_state["max_results"] = args.max_results or 5` と、**未指定でも常に 5 を state に載せていた**。「未指定」と「5 件指定」を区別する手段が state に存在しなかった |
| 対処 | （a）`__main__` は `args.max_results is not None` のときだけ `initial_state` に載せる（キー不在＝未指定。FR-011）。（b）`parse_instruction` の条件から `and input_max != 5` を除去 |
| 検証 | `test_explicit_state_count_of_five_beats_instruction_text`（単体）＋ `test_cli_omits_max_results_from_state_when_not_given` / `test_cli_passes_explicit_max_results_even_when_it_is_the_default`（CLI 配線、`tests/integration/test_full_flow.py`） |

同クラスの点検: `platform` / `output_format` / `published_after` / `use_trends` / `sort_by` / `transcript_language` は `state` → `configurable` → 既定の順にフォールバックしておりセンチネルを持たない。**Configuration 側の `elif configurable.max_results != 5:` は残している**（`Configuration.max_results` は `default=5` の `int` で「未設定」を表現できないため。CLI 経由の明示 5 は上記 (a) で state 側が先に捕まえるので、CLI から到達できる不整合は解消済み）。Configuration スキーマを `int | None` へ変える案は公開設定の意味を変えるため本機能の範囲外と判断した。

### T027: 変異探針（2026-09-13 実測）

**1 件ずつ実施**し、各件で「改変 → 失敗確認 → 復元 → `sha256sum` 一致 → フルスイート再実行 → `git status --short`」を完了させた。

| 変異 | 落ちるテスト | 実測 |
|------|--------------|------|
| （1）`if input_max is not None:` に `and input_max != 5` を戻す | `test_explicit_state_count_of_five_beats_instruction_text` | **1 failed / 62 passed** |
| （2）`_period_to_date` / `_extract_published_after_from_text` の月数を算用数字のみに戻す | `test_kanji_month_within_is_resolved_like_digits` / `test_twelve_kanji_months_backs_off_a_year` | **2 failed / 61 passed** |
| （3）`text = _PERIOD_EXPRESSION_RE.sub("", text)` を削除 | `test_year_and_period_expressions_are_not_counts`（`2025年` / `3年以内` / `最近30日を7件` / `5月を3件` / `10年分を3件`） | **6 failed / 57 passed** |
| （4）漢数字の件数走査を 1 文字ずつの辞書ループ（旧実装）に戻す | `test_count_with_unit_is_extracted[十二件の動画-12]` / `test_count_without_unit_or_unsupported_numeral_is_none[二三十件の動画]` | **2 failed / 61 passed** |
| （5）`__main__` を `initial_state["max_results"] = args.max_results or 5`（常に載せる）に戻す | `test_cli_omits_max_results_from_state_when_not_given` | **1 failed / 1 passed** |

復元後の `sha256sum` はいずれも変異前と一致（`nodes/parse_instruction.py`: `aa9e4a8358f4f65bd74e78fbe0de85f2a80c06957fca97889b98d2685ce22af` / `__main__.py`: `22935b81d82cd1e5af1c52af501e26226dec7c45b27a00708aeebe8c205988db`）。復元後のフルスイートは **413 passed**（T026 完了時点は 354 passed。内訳: `test_parse_instruction.py` が 6 → 63 件、`test_full_flow.py` に CLI 配線 2 件を追加）。

`nodes/parse_instruction.py` のカバレッジは 107 stmts / 1 miss / **99%**。未実行は `_period_to_date` 末尾の `return None`（101 行目）で、**正規表現由来のラベルは必ず月表現か `_RELATIVE_PERIOD_DAYS` のキーに一致するため到達しない**防御行（唯一の呼び出し元は `_extract_published_after_from_text` で、そのラベルは `(半年|[0-9０-９一二三四五六七八九十]+[ヶカ]?月|1年|年|本年|今年|最近)` のいずれか）。位取り不正の漢数字（`二三十月以内`）は同じ関数の `if months is None: return None` で先に `None` になるため、そちらは `test_unrecognized_period_is_not_a_filter` で実行済み。COV-004 の目標（既定値で 90%）は満たす。`ruff check` は変更 4 ファイルすべて clean、`mypy src/trend_researcher` は **36 errors / 12 files**（本セッション開始時のベースライン 37 errors / 12 files から増加なし）。

### T028 で検出した節分割の不整合: `#### 説明` が別テーマになる（2026-09-13 実測）

`tests/unit/test_extract_common.py` の入力表を作るために `_split_sections` / `_parse_themes` を実測したところ、`### テーマ` の下に `#### 説明` / `#### 代表抜粋` を置く形（コード自身が `extract_section(body, "説明")` / `extract_section(body, "代表抜粋")` で解釈しようとしている形）で、次の 2 つが同時に起きていた。

| 入力（`### テーマA` + `#### 説明` + `#### 代表抜粋`） | 修正前 | 修正後 |
|----------------------------------------------------|--------|--------|
| 生成されるテーマ数 | **3**（`テーマA` / `説明` / `代表抜粋`） | **1**（`テーマA`） |
| `テーマA` の `description` | `テーマA`（見出し名へフォールバック） | `説明A` |
| `テーマA` の `example_quotes` | `[]` | `["抜粋A1", "抜粋A2"]` |
| `_parse_themes` の `extract_section(body, "説明")` | **到達不能**（`body` に見出し行が残らない） | 到達する |

原因は `_split_sections` が `#{3,4}` のすべてを見出し境界にしていたこと。節の先頭以外に見出し行が残らないため、`_parse_themes` が本文から `説明` / `代表抜粋` を探す経路は必ず空振りし、逆にその見出しが独立したテーマとして抽出されていた（宣言と実装の不一致。FR-023）。

対処: `_split_sections` を「現在の節と同じか浅い見出しだけを節境界にし、深い見出しは同じ節に残す」実装へ変更（見出しレベルを追跡。前書き＝見出しで始まらない塊は従来どおり `hm` 不一致で破棄）。プロンプトが要求する形式（`### テーマ` + `- 説明:`）の結果は変更前と同一であることを実測で確認済み。

### T028 で検出した進捗メッセージの重複: ノードの戻り値に「開始」が 2 行入る（2026-09-13 実測）

`test_progress_messages_report_the_theme_count` で `len(out["messages"]) == 2` が失敗して検出した。7 ノードすべてが同じ形（`progress_messages = emitter.get_messages()` で「開始」まで取得 → 完了 emit 後に `extend(emitter.get_messages())` で「開始」を再び足す）で、戻り値は `[開始, 開始, 完了]` になっていた。

| 観測点 | 修正前 | 修正後 |
|--------|--------|--------|
| ノード単体の戻り値（`extract_common`） | 3 件（`開始` が重複） | **2 件**（`開始` / `完了`） |
| グラフ実行後の `state["messages"]` の進捗行 | **14 行**（7 ノード × 2） | 14 行（同じ） |

グラフの state で重複が消えていたのは LangGraph `add_messages` が**同一オブジェクトの id で畳み込む**ため（`ProgressEmitter.get_messages()` は同じ `AIMessage` インスタンスを返すリストのコピーなので、2 回目は同一 id として置換される）。つまり進捗表示は「オブジェクト同一性による畳み込み」に依存して正しく見えていた。`extend` を `= emitter.get_messages()`（コピーの取り直し）に変え、依存を外した。同一オブジェクトを返す実装を変える（毎回新しい `AIMessage` を作る等）と、進捗行が 2 倍に膨らむ状態だった。

変異探針（後述の 3）で確認したとおり、**統合テスト（graph 経由）ではこの重複を検出できない**（畳み込みが先に効く）。検出できるのはノード単体の戻り値を見るテストだけなので、`tests/unit/test_extract_common.py` と `tests/unit/test_parse_instruction.py` の進捗テストを「戻り値の完全一致」にした。あわせて `tests/integration/test_full_flow.py` の `_progress_labels`（連続する同一ノードを畳む）を `_node_phases`（畳まない）＋ `_all_phases` へ置き換え、進捗が 14 行（7 ノード × 開始/完了）であることを重複・欠落なく固定した。

### T028: 変異探針（2026-09-13 実測）

**1 件ずつ実施**し、各件で「改変 → 失敗確認 → 復元 → `sha256sum` 一致 → フルスイート再実行 → `git status --short`」を完了させた。

| 変異 | 落ちるテスト | 実測 |
|------|--------------|------|
| （1）`if current and (level == 0 or line_level <= level):` から深さ比較を除去（旧 `_split_sections`） | `test_nested_explanation_heading_is_used_as_description` / `test_nested_field_headings_do_not_become_themes` / `test_quotes_come_from_nested_excerpt_heading` | **3 failed / 27 passed** |
| （2）`extract_common` の進捗を `extend` に戻す | `test_progress_messages_report_the_theme_count` / `test_progress_messages_report_zero_themes` | **2 failed / 28 passed** |
| （3）`search` の進捗を `extend` に戻す | なし（`test_x_flow_progress_messages_follow_node_order` は **1 passed**） | **検出不能**（`add_messages` の同一オブジェクト畳み込みが先に効くため。上の「観測点」表を参照） |
| （4）`supporting = ids` を空リストに固定 | `test_supporting_ids_are_all_analyses` / `test_supporting_ids_follow_the_analysis_order` | **2 failed / 28 passed** |
| （5）本文欠落時のフォールバック（`if not body and theme_name: body = theme_name`）を削除 | `test_theme_name_only_uses_the_heading_as_description` | **1 failed / 29 passed** |

復元後の `sha256sum` はいずれも変異前と一致（`nodes/extract_common.py`: `fc344384ef11be48a4ef7cea02a32289a91e7c7af5bf987588508ad41cb304c3` / `nodes/search.py`: `e5a876690307a531f571b1dc069525866603bcaf7f78d541e730dc5b7677afef`）。復元後のフルスイートは **443 passed**（T027 完了時点は 413 passed。`test_extract_common.py` 30 件を新規追加）。`nodes/extract_common.py` のカバレッジは 73 stmts / 0 miss / **100%**。

### T028 のスコープ外とした点

- 表形式のテーマ出力（`| テーマ | 説明 |` のみ）は **0 件**のまま固定した。プロンプト（`X_EXTRACT_COMMON_PROMPT` / `YOUTUBE_EXTRACT_COMMON_PROMPT`）が要求するのは `### テーマ名` + `- 説明:` の形式であり、表をテーマ表として解釈する経路は実装に存在しない。挙動を変えるのは仕様追加になるため、`test_no_theme_output_yields_an_empty_list` の 1 ケースとして「例外にせず 0 件」だけを固定した。
- `text = result.content if hasattr(result, "content") else str(result)` の `else` 側（`content` を持たない戻り値）は、プロダクションの LLM クライアントが常に `AIMessage` を返すため到達しない防御分岐であり、テストを付けていない。

### T029 で検出した活用アイデア表の欠陥: セルが空の行を採用する（2026-09-13 実測）

`_parse_angles_table` は「3 列未満の行を捨てる」だけだったため、**列数は足りているがセルが空の行**を採用していた。

| 入力行 | 修正前 | 修正後 |
|--------|--------|--------|
| `\| （必要なだけ繰り返す） \| \| \|` | `BlogAngle("（必要なだけ繰り返す）", "", "")` | 採用しない |
| `\| A \| \| C \|` | `BlogAngle("A", "", "C")` | 採用しない |
| `\|  \| B \| C \|` | `BlogAngle("", "B", "C")` | 採用しない |

1 行目は `X_ANALYZE_CONTENT_PROMPT` / `YOUTUBE_ANALYZE_CONTENT_PROMPT` が表の作り方を示すために置いている**例示行そのもの**で、モデルが雛形をそのまま返すと指示文が切り口として採用され、`key_points`（＝報告書に載る切り口一覧）に「（必要なだけ繰り返す）」が混入していた。プロンプトが要求する各行は「記事で扱える角度 × なぜ読者に価値があるか × キーフレーズ」の 3 つが揃っていることなので、3 列すべてが非空の行だけを採用する実装に合わせた（プロンプトと実装の不一致。FR-023）。

### T029 で検出したフォールバックの欠陥: 生の Markdown 表が `summary` になる（2026-09-13 実測）

応答が「`## ブログの活用アイデア` + 空行 + 表」の形（モデルがよく返す形）のとき、段落フォールバックが**表の先頭行**を要約に採用し、切り口ベースの合成が使われなくなっていた。

| 応答 | 修正前 `summary` | 修正後 `summary` |
|------|------------------|------------------|
| `## ブログの活用アイデア` + 空行 + 表（切り口 1 行） | `"\| 切り口 \| 読者への価値 \| 拾えるキーフレーズ \|\n\|---\|---\|---\|\n\| 入門解説 \| ..."` | `"このコンテンツでは、入門解説などについて語られています。"` |

`extract_section(text, "概要")` が空のときの一次フォールバックは「`#` で始まらない最初の段落」だったため、見出しが空行で区切られていると次の段落が表そのものになる。原因は見出し行だけを除外していたことで、表の行（`\|` 始まり）も除外するようにした。`angles` は同じ応答から取れている（`["入門解説"]`）ので、切り口ベースの合成が本来の受け皿になる。T028 で見つけた節分割の欠陥と同種の「宣言（プロンプトの形式）と実装（パース）の不一致」（FR-012 / FR-023）。

### T029: 変異探針（2026-09-13 実測）

**1 件ずつ実施**し、各件で「改変 → 失敗確認 → 復元 → `sha256sum` 一致 → フルスイート再実行 → `git status --short`」を完了させた。

| 変異 | 落ちるテスト | 実測 |
|------|--------------|------|
| （1）空セル行ガード（`or not all(cells[:3])`）の除去 | `test_parse_angles_table_skips_rows_with_empty_cells` の 3 ケース | **3 failed / 41 passed** |
| （2）表行を要約に使わない条件（`startswith(("#", "\|"))` → `("#")`）の除去 | `test_summary_from_single_angle_has_no_second_sentence` | **1 failed / 43 passed** |
| （3）区切り行スキップ（`re.match(r"^\|[\s:\|-\|]\+\|$", line)`）の除去 | 表を扱う 7 テスト（`reads_three_columns` / `skips_header_and_separator_rows` の 2 ケース / `keeps_valid_rows_between_broken_rows` / `structured_response_is_expanded_into_finding` / `summary_falls_back_to_angles` / `summary_from_single_angle_has_no_second_sentence`） | **7 failed / 37 passed** |
| （4）見出し行スキップ（`cells[0] in ("切り口", "角度")`）の除去 | 表を扱う 8 テスト | **8 failed / 36 passed** |
| （5）`source_text[:20000]` の切り詰め除去 | `test_source_text_is_truncated_at_twenty_thousand_chars` | **1 failed / 43 passed** |
| （6）`asyncio.Semaphore(2)` → `Semaphore(1)` | `test_parallelism_is_capped_at_two` | **1 failed / 43 passed** |
| （7）`contexts_by_id` の id 引き当ての除去 | `test_prompt_includes_context_text_matched_by_id` | **1 failed / 43 passed** |

復元後の `sha256sum` はいずれも変異前と一致（`nodes/analyze_content.py`: `46602ff7ac764d3b4d18197f611223d79bf6aa4c17fecda9aae9f513ff9062a6`）。復元後のフルスイートは **487 passed**（T028 完了時点は 443 passed。`test_analyze_content.py` 44 件を新規追加）。`nodes/analyze_content.py` のカバレッジは 78 stmts / 0 miss / **100%**（タスク本文の「未実行行 30 / 44 / 48 / 72-73」は T027・T028 の変更前の行番号。T028 完了時点で未実行は 1 行（列不足の `continue`）まで減っており、本タスクで 0 行になった）。

### T029 のスコープ外とした点

- `parallelism` の計測だけ `fake_model_factory` ではなく計測用フェイク（`_TrackingLLM`）を使う。差し替える境界は同じ `build_model`（R-7）だが、`FakeModelFactory` のフェイクは即座に応答を返すため同時実行数を観測できない（`asyncio.Semaphore(2)` の上限は「同時に何件走ったか」でしか固定できない）。
- `text = result.content if hasattr(result, "content") else str(result)` の `else` 側は T028 と同じ理由（到達不能）でテストしていない。
- 3 列すべてが非空の行だけを採用する変更により、`| A | B | C | D |` のような 4 列以上の行は先頭 3 列だけを採用する挙動のまま（プロンプトは 3 列を要求しているため、4 列目以降は解釈しない）。

### T030 で検出した欠陥: JSON オブジェクト以外の応答で `parse_instruction` が落ちる（2026-09-13 実測）

`extract_json_block` は `json.loads` の結果をそのまま返しており、型注釈（`dict[str, Any] | None`）と docstring（「最初の JSON **オブジェクト**を抽出する」）に反して配列・文字列・数値を返していた。呼び出し側（`parse_instruction` の `parsed = extract_json_block(text) or {}` → `parsed.get(...)`）は `.get()` で読むため、ノードごと `AttributeError` で落ちる。

| LLM 応答 | 修正前 | 修正後 |
|----------|--------|--------|
| `[1, 2]` | `extract_json_block` が `[1, 2]` を返し、ノードが `AttributeError: 'list' object has no attribute 'get'` | `None`（ブロック無し扱い。`topic` は指示本文全体、`max_results` は自然言語/既定） |
| `"hello"` | `str` を返し `AttributeError: 'str' object has no attribute 'get'` | `None` |
| `5` | `int` を返し `AttributeError: 'int' object has no attribute 'get'` | `None` |

対処: `_load_json_object`（`json.loads` の結果が `dict` のときだけ返す）を追加し、フェンス経路と波括弧経路の両方でこれを使う（`parse_instruction` は修正不要）。ノード側の回帰は `test_non_object_json_response_is_treated_as_no_block`（配列 / 文字列 / 数値の 3 ケース）で固定した。

### T030 の重複統合（FR-017）

`tests/unit/test_parse.py` から表の解釈に関する 3 件を削除した。`test_parse_angles_table` / `test_parse_angles_table_skips_header_and_separator` は **T029 の `tests/unit/test_analyze_content.py` が同じ関数の同じ経路を（列不足・空セル・アラインメント指定まで含めて）固定済み**、`test_fallback_summary_from_angles` は `_analyze_one` を直接呼ぶ形で、T029 がノード経由（`analyze_content`）で同じ経路を固定済みだからである。`tools/parse.py` に属する契約（JSON ブロック・箇条書き・見出し直下の本文）は `test_parse.py` に残した。

### T030: 変異探針（2026-09-13 実測）

**1 件ずつ実施**し、各件で「改変 → 失敗確認 → 復元 → `sha256sum` 一致 → フルスイート再実行 → `git status --short`」を完了させた。

| 変異 | 落ちるテスト | 実測 |
|------|--------------|------|
| （1）非オブジェクトを弾くガード（`isinstance(data, dict)`）の除去 | `test_extract_json_block_ignores_non_object_json` 4 件 / `..._in_text` 1 件 / `test_non_object_json_response_is_treated_as_no_block` 3 件 | **8 failed / 83 passed** |
| （2）フェンス優先（`candidate = fenced.group(1) if fenced else text`）の除去 | `test_extract_json_block_prefers_fenced_block` | **1 failed / 90 passed** |
| （3）番号付きリストの代替（`\d+\.\s+`）の除去 | `test_extract_list_items_numbered` / `test_extract_list_items_ignores_lines_without_marker` | **2 failed / 89 passed** |
| （4）次の見出しで打ち切る条件の除去 | `test_extract_section` / `test_extract_section_with_empty_body` | **2 failed / 89 passed** |
| （5）`extract_list_items` の空テキスト早期 return の除去 | なし（**91 passed**） | **挙動不変（等価変異）**。`"".splitlines()` が空なのでループ結果も `[]` になり、この防御は冗長。挙動が変わらないことを論証できるため欠陥として扱わず、テストも付け替えていない |

復元後の `sha256sum` はいずれも変異前と一致（`tools/parse.py`: `944ded6ba22c9910e686ce54fa6130af111d80ba780c0a62069122aa10901297`）。復元後のフルスイートは **506 passed**（T029 完了時点は 487 passed。`test_parse.py` は 10 → 25 件、`test_parse_instruction.py` に 3 件を追加、重複 3 件を削除）。`tools/parse.py` のカバレッジは 48 stmts / 0 miss / **100%**。

### T030 のスコープ外とした点

- 波括弧の探索（`re.search(r"\{.*\}", text, re.DOTALL)`）は最初の `{` から最後の `}` までを**貪欲**に取るため、「壊れたフェンス + 本文中の有効なオブジェクト」（例: `` ```json\n{"a": }\n``` `` + `補足 {"b": 2}`）は `{"b": 2}` を拾えず `None` になる。これは「最初の JSON オブジェクトを抽出する」という docstring の意図とは厳密には一致しないが、戻り値が `None`（＝ブロック無し扱い）に倒れるだけで例外にはならないため、安全側の劣化として現状を固定した（`test_extract_json_block_none_when_nothing_parses` の 2 ケース目）。入れ子オブジェクトを壊さずに直すには括弧の対応を数える走査（`json.JSONDecoder.raw_decode` を各 `{` 位置で試す）が必要で、本タスクの要件（例外にしない）を超える変更になるため触れていない。
- `if not text: return None`（`extract_json_block`）と `if not text: return ""`（`extract_section`）も同じ理由（冗長な防御）で残した。

### T031 で検出した欠陥: 日本語に隣接する年号と期間表現の数字が残る（2026-09-13 実測）

`_clean_query` は「生成クエリから年号・期間表現を除去し、広く検索できるようにする」ことを宣言しているが、実測では日本語のクエリで両方が残っていた。既存テストが空白区切りの英語風入力（`2024 オタク 困りごと`）しか見ていなかったため、実装の穴が隠れていた。

| 生成クエリ | 修正前 | 修正後 |
|------------|--------|--------|
| `2024年のオタク 困りごと` | `2024のオタク 困りごと` | `オタク 困りごと` |
| `2024のAI` | `2024のAI` | `AI` |
| `2024年から2025年の動画` | `20242025の動画` | `動画` |
| `2024年1月の動画` | `20241の動画` | `動画` |
| `最近のAI` | `のAI` | `AI` |
| `最近はAI ツール` | `はAI ツール` | `AI ツール` |
| `3ヶ月以内のAI` | `3のAI` | `AI` |
| `三ヶ月以内のAI` | `のAI` | `AI` |
| `（2024年）` | `（2024）`（空にならず 1 件のクエリとして残る） | `""`（空行と同じ扱いで破棄） |
| `月刊誌 特集` | `刊誌 特集`（数字を伴わない「月」を削ってしまう） | `月刊誌 特集` |

原因は 3 つ。(1) `_YEAR_RE` の `\b` は CJK も `\w` なので「数字と日本語の間」が境界にならず、`2024年` の年号が一致しない。(2) `_PERIOD_RE` の月・年のパターンが数字を前提にしておらず（`三?ヶ?月` / `1?年`）、`3ヶ月` の数字が残るうえ `月` 単体にも一致して `月刊誌` を壊す。(3) 期間表現を除去した後に助詞（`最近の` の `の`）が残り、`のAI` のようなクエリになる。

対処: 年号を「数字でない」前後条件（`(?<!\d)` / `(?!\d)`）で挟み、期間表現の数字を半角・全角・漢数字で許し（`_DIGITS`）、期間表現（および年号）の直後の助詞も一緒に除去し、除去後に残る括弧・引用符も `strip` するようにした。`月刊誌` / `100日間チャレンジ` / `12024`（5 桁の数字）が壊れないこともテストで固定している（`100日間` は「日付」を期間表現に含めない設計のため対象外）。

### T031: 変異探針（2026-09-13 実測）

**1 件ずつ実施**し、各件で「改変 → 失敗確認 → 復元 → `sha256sum` 一致 → フルスイート再実行 → `git status --short`」を完了させた。

| 変異 | 落ちるテスト | 実測 |
|------|--------------|------|
| （1）年号の前後条件を `\b` に戻す | `test_clean_query_removes_year_and_period[2024のAI]`（`2024年` は数字を伴う期間表現として別経路で除去されるため、年号だけのケースが唯一の検出点） | **1 failed / 33 passed** |
| （2）期間表現の数字を半角のみに戻す | `3ヶ月` / `３ヶ月` / `三ヶ月` / `3カ月` の 4 ケース | **4 failed / 30 passed** |
| （3）期間表現の直後の助詞の除去をやめる | 助詞が残る 11 ケース | **11 failed / 23 passed** |
| （4）期間表現の `から` / `より` の除去 | `2024年から2025年の動画` | **1 failed / 33 passed** |
| （5）X の 8 件上限の除去 | `test_x_caps_queries_at_eight` / `test_cap_applies_when_instruction_platform_is_empty` | **2 failed / 32 passed** |
| （6）空クエリの破棄（`if q:`）をやめる | `test_blank_and_cleaned_away_lines_are_dropped` | **1 failed / 33 passed** |
| （7）投稿日フィルタの分岐を反転 | 注記が逆に入り、`date_hint` が `None` のまま `.format()` に渡って `AttributeError` になるため 13 件が失敗 | **13 failed / 21 passed** |
| （8）トピックの括弧除去の削除 | `test_topic_has_parenthesized_part_removed` | **1 failed / 33 passed** |
| （9）進捗の `extend` への差し戻し | `test_progress_messages_report_start_then_finish` | **1 failed / 33 passed** |

復元後の `sha256sum` はいずれも変異前と一致（`nodes/plan_search.py`: `eef3a5f5bfb5093c2bc1ccb04a73689e403c1fb71cb1d5067a3b82dd430aaeff`）。復元後のフルスイートは **538 passed**（T030 完了時点は 506 passed。`test_plan_search.py` を 2 → 34 件へ強化し、`__import__("unittest").mock.patch` と手書きフェイクを `fake_model_factory` へ移行）。`nodes/plan_search.py` のカバレッジは 46 stmts / 0 miss / **100%**（タスク本文の未実行行 42 / 64 は `published_after` ありの注記分岐と 8 件上限の切り詰めで、どちらも解消した）。

### T032 で判明した「恒真アサート」の実体（2026-09-13 実測）

`tests/unit/test_models.py::test_report_sources_invariant` は `sources=[c.url for c in cands]` で組み立てたレポートに対し `set(report.sources) == {c.url for c in cands}` を断言していた。左辺は構築式のコピーであり、`models.py` の `sources` フィールドの型をどう変えても（実際には何も検証していないため）落ちない。

さらに、この契約の本体（出典が候補の URL から構築されること・URL なしの候補が除外されること）は `tests/unit/test_compile_report.py` が**ノード経由で**すでに検証している（`test_compile_report_returns_report_with_state_contents` / `test_compile_report_excludes_candidates_without_url_from_sources`）。したがって data-model 1.7 の `resolution` は当初案の `strengthened`（`compile_report` 経由に置換）ではなく **`merged`**（重複のため統合）が実態に即する（T038 で記録を更新）。`tests/unit/test_models.py` にはモデルの宣言（既定値）だけを残し、出典構築はノード側の 1 箇所で検証する（LAYOUT-005-5）。

### T032 で置換として追加した検証（実測で未検出だったもの）

「置換」は恒真アサートの削除だけでは終わらない。`models.py` の既定値のうち、**変更してもスイートが緑のままだった**ものを実測で特定し、モデル層の検証として追加した（この 3 件は追加前はすべて 538 passed で未検出だった）。

| 変異（追加前はすべて未検出） | 追加後の検出テスト | 実測 |
|------------------------------|--------------------|------|
| `ResearchReport.sources` の既定を `["dummy"]` | `test_report_defaults_are_empty_collections` | **1 failed / 538 passed** |
| `ResearchReport.candidates` の既定を 1 件のダミー候補 | 同テスト | **1 failed / 538 passed** |
| `CommonTheme.description` の既定を `"dummy"` | `test_common_theme_description_defaults_to_empty_string` | **1 failed / 538 passed** |

`sources` と `candidates` は「候補 0 件のときに存在しない出典・候補がレポートに載る」経路を作るため、既定値が振る舞いに効く（`render_markdown` の「## 出典」が嘘になる）。`description` は `compile_report._render_common_themes` が表へそのまま埋めるため効く。

### T032 のスコープ外とした点

- `tokens` 系ではないが同種の未検証の既定値として、`Candidate.platform = "x"` と `OutputSpec.table_for = ["common_points"]` も実測では未検出だった（それぞれ既定を `"youtube"` / `[]` にしても 538 passed）。ただし両フィールドは `src/` から**一度も読まれていない**（`grep -rn "table_for" src/` が 0 件、`Candidate.platform` も読み出しなし）。挙動に効かない既定値を断言しても「どの振る舞いの変異を検出するか」を説明できないため、テストは追加しない（LAYOUT-005-1 / LAYOUT-005-2）。フィールド自体の削除は検証対象（`models.py` は read-only）の変更になるため本機能の範囲外。
- `tests/unit/test_models.py` は未使用 import（`BlogAngle` / `Context`）で `F401` が 2 件出ていた（HEAD でも同数）。本タスクで当該ファイルを変更するため、削除して green にした（R-8 の boy-scout。リポジトリ全体の違反件数は 40 → 38 になる）。

### T033: 変異探針 M1（出典構築を空にする）の結果（2026-09-13 実測）

- 変異: `src/trend_researcher/nodes/compile_report.py` の `sources = [c.url for c in candidates if c.url]` → `sources = []`
- 結果: **5 failed / 534 passed**。検出したテスト:
  - `tests/unit/test_compile_report.py::test_compile_report_returns_report_with_state_contents`
  - `tests/unit/test_compile_report.py::test_compile_report_excludes_candidates_without_url_from_sources`
  - `tests/integration/test_full_flow.py::test_x_flow_produces_full_report`
  - `tests/integration/test_cli_contract.py::test_cli_004_05_sources_are_listed[x]` / `[youtube]`
- 恒真アサート（`test_report_sources_invariant`）を削除した後（T032）でも検出されることを確認した。**T032 / T024 の追加強化は不要**。
- 復元: `sha256sum` 一致（`de3eaca795c20c672e7a930430b812587ceba0fdc7725233a7a98a301d63b95b`）→ 復元後フルスイート **539 passed** → `git status --short` 清浄。
- 補足: data-model 1.7 の `evidence` 列に書かれた「M1 未検出」は**旧テスト（恒真アサートのみ）の状態**を指す。現在は CLI 契約層（`test_cli_004_05_sources_are_listed`）まで含めて 3 層で検出できる。

### T034: 変異探針 M2（候補なしの短絡を無効化する）の結果（2026-09-13 実測）

- 変異: `src/trend_researcher/graph.py` の `_route_after_search` を `return "skip" if not candidates else "continue"` → `return "continue"`（候補 0 件でも fetch 以降へ進む）
- 結果: **7 failed / 532 passed**。検出したテスト:
  - `tests/integration/test_graph_wiring.py::test_route_after_search[empty]` / `[missing-key]` / `[none]`（戻り値の 3 分岐）
  - `tests/integration/test_graph_wiring.py::test_zero_candidates_skips_fetch_and_downstream`（`fetch` 以降のノードが呼ばれないこと）
  - `tests/integration/test_graph_wiring.py::test_zero_candidate_progress_line_count`（進捗 12 行 = 短絡経路の行数）
  - `tests/integration/test_full_flow.py::test_empty_search_skips_the_rest_of_the_pipeline[x]` / `[youtube]`
- data-model 1.7 の `tests/test_graph.py::TestGraphBuild`（`weak` / `is not None` のみ）を `test_graph_wiring.py` が置き換え済みであることの実測裏付けになった。**T016 の追加強化は不要**。
- 復元: `sha256sum` 一致（`35552d6f9f4ab8e189cfab8f24c555bc90f0a2b2863f635d95a2c26919646252`）→ 復元後フルスイート **539 passed** → `git status --short` 清浄。

### T035: 変異探針 M3（進捗の総数をノード数と食い違わせる）の結果（2026-09-13 実測）

- 変異: `src/trend_researcher/progress.py` の `ProgressEmitter.TOTAL = 7` → `TOTAL = 8`（`NODE_ORDER` は 7 件のまま）
- 結果: **6 failed / 533 passed**。検出したテスト（`tests/unit/test_progress.py`）:
  - `test_total_matches_node_order_length`（`TOTAL == len(NODE_ORDER)` の不変条件。LAYOUT-006-1）
  - `test_emit_writes_start_line` / `test_emit_writes_done_line_with_detail`（出力が `[N/7]` 形式であること）
  - `test_emit_defaults_to_stderr` / `test_get_messages_accumulates_emitted_lines`
  - `test_every_node_reports_start_and_done`（7 ノードぶんの開始・完了。LAYOUT-006-4）
- 対抗措置（data-model 1.7 / test-layout LAYOUT-006 の「`TOTAL` を変更するとテストが落ちる」）が**実測で成立**した。**T015 の追加強化は不要**。
- 復元: `sha256sum` 一致（`58044c02480d7f7f7bc3159d1a8951088a905236d19a49c2c413e5e050f2a164`）→ 復元後フルスイート **539 passed** → `git status --short` 清浄。

### T036: 縮退処理の変異探針 5 件の結果（2026-09-13 実測）

quickstart 手順 5.3 の 5 件を **1 件ずつ**（改変 → フルスイート → 復元 → `sha256sum` 一致）実施した。**5 件すべて検出**（SC-004）。

| 変異 | 対象ファイル | 検出テスト | 実測 |
|------|--------------|------------|------|
| リトライループの打ち切り（再試行を 1 回に） | `tools/x_search.py` | `test_search_tweets_exhausts_retries_and_raises_last_error` / `test_search_tweets_recovers_after_transient_failure` / `test_search_tweets_with_zero_retries_returns_empty` | **3 failed / 536 passed** |
| 字幕の形式判定を `_parse_vtt` のみに | `tools/transcript.py` | `test_fetch_transcript_reads_json3_file` / `test_fetch_transcript_broken_json3_file_yields_empty_text` | **2 failed / 537 passed** |
| キャッシュ書き込みの `try` を外す | `nodes/compile_report.py` | `test_cache_write_failure_is_reported_and_execution_continues` / `test_cache_write_failure_does_not_add_a_note` / `test_unwritable_cache_dir_is_recorded_and_the_run_succeeds`（E2E） | **3 failed / 536 passed** |
| `read_json` の存在チェックを外す（例外化） | `cache.py` | `test_read_json_returns_none_when_file_is_missing` / `test_read_json_returns_none_when_directory_is_missing` | **2 failed / 537 passed** |
| X の重複除去（`seen` 判定）を外す | `providers/x.py` | `test_x_provider_relevance_dedupe_keeps_first_occurrence` / `test_x_provider_relevance_truncates_after_dedupe` / `test_x_provider_likes_dedupes_pool_before_sorting` / `test_x_likes_sort_orders_candidates_descending_without_duplicates` / CLI 契約 3 件（`test_cli_001_03` / `test_cli_002_05` / `test_cli_002_05_002_03`） | **7 failed / 532 passed** |

対象ファイルの変異前 sha256（復元後に一致を確認）:

| ファイル | sha256 |
|----------|--------|
| `tools/x_search.py` | `59f7a4e2073770d04db35ac33d347f1875dbd67eda59b57cda4137384b2e6596` |
| `tools/transcript.py` | `942fef782fecf6822dbf7bcad57ad18c2dd29099d0802152cd95eb87f0a4cfc0` |
| `nodes/compile_report.py` | `de3eaca795c20c672e7a930430b812587ceba0fdc7725233a7a98a301d63b95b` |
| `cache.py` | `73175d3fdc7f1b9f093cf2f39edc3c15893a5a9cc7932fc705f06ef3188c1a60` |
| `providers/x.py` | `c02fbb1580bbe1abc779af9eb47b98f34600ab2d0d329b8e90968092f4724d34` |

復元後のフルスイートは **539 passed**、`git status --short` は清浄。5 件とも「落ちなければ T0xx を強化する」の条件に該当しなかったため、**追加のテスト強化は不要**。重複除去の探針が CLI 契約（`test_cli_001_03_fewer_results_exit_zero`）まで落ちたのは、候補の重複が候補数 → 終了コード判定に波及するため。
