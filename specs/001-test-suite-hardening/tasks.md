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
- [ ] T025 [US2] `tests/unit/test_providers.py` を新規作成する。provider レジストリ、未知プラットフォームの拒否、行描画（表ヘッダ・ラベル・件名）の差分を固定する（FR-009 / 憲法 原則 IV）
- [ ] T026 [US2] `tests/integration/test_full_flow.py` を強化する。`_FakeModel` の**プロンプト部分一致ディスパッチを廃止**し、`fake_model_factory` によるノード単位の応答注入へ変更する（現状は `extract_common` のプロンプトが「関連」を含むため検索クエリ応答が返り、共通テーマが 0 件になる。R-7）。あわせて境界の失敗経路（部分応答・例外）を含む経路を追加する（FR-009 / data-model 1.3 のマトリクス）

**Checkpoint**: US2 完了。外部境界と永続化の失敗経路が独立に検証できる

---

## Phase 5: User Story 3 - LLM の自由文出力に対する決定的な解釈を固定する (Priority: P3)

**Goal**: LLM が返す揺れのある自由文から、件数・投稿日下限・出力形式・検索クエリ・共通テーマをどう解釈するかを分岐ごとに固定する。

**Independent Test**: `uv run pytest -q tests/unit/test_parse_instruction.py tests/unit/test_extract_common.py tests/unit/test_analyze_content.py tests/unit/test_parse.py tests/unit/test_plan_search.py` が完走する。固定の入力（指示文・LLM 応答の模擬）を与え、解釈結果のみを検証する。

**契約**: `contracts/test-layout.md`（LAYOUT-004-4）、`contracts/coverage-policy.md` COV-004 の未実行行表

- [ ] T027 [P] [US3] `tests/unit/test_parse_instruction.py` を強化する。優先順位の 3 分岐（明示設定 > 本文の自然言語 > LLM の解釈）、漢数字と期間表現（「5件」「半年以内」）、明示的な日付（「2025-01-01 以降」）、解釈できない日付文字列（例外にしない）、構造化ブロックを返さない応答（トピック＝指示本文全体＋既定値）を固定する。`frozen_now` で時刻を固定する（FR-011 / COV-004 の `nodes/parse_instruction.py` 未実行行 54 / 61-64 / 72 / 75 / 102 / 112-117）
- [ ] T028 [P] [US3] `tests/unit/test_extract_common.py` を新規作成する。見出しと本文のみの出力からのテーマ名・説明の抽出と全コンテンツへの紐づけ、空出力（テーマ一覧が空）、崩れた出力（見出しのみ・本文欠落）、表形式と箇条書きの両方の解釈を固定する（FR-012 / COV-004 の `nodes/extract_common.py` 未実行行 57-59 / 76-86）
- [ ] T029 [P] [US3] `tests/unit/test_analyze_content.py` を新規作成する。ソースの整形、活用アイデア表の解析、列不足・見出しのみ・区切り行のみの行破棄（例外にしない）、構造化ブロックがない場合のフォールバック要約を固定する（FR-012 / COV-004 の `nodes/analyze_content.py` 未実行行 30 / 44 / 48 / 72-73）
- [ ] T030 [P] [US3] `tests/unit/test_parse.py` を強化する。崩れた表（列不足・区切り行のみ・見出しのみ）と JSON ブロックを含まない応答を追加し、見出し・区切り行のスキップを検証する既存の重複ケースを統合する（FR-012 / FR-017）
- [ ] T031 [P] [US3] `tests/unit/test_plan_search.py` を強化する。検索クエリからの年号・期間表現の除去、空になった行の破棄、クエリ数の上限を固定する（FR-012 / COV-004 の `nodes/plan_search.py` 未実行行 42 / 64）

**Checkpoint**: US3 完了。LLM 自由文の解釈が分岐ごとに独立して検証できる

---

## Phase 6: User Story 4 - 既存テストが「落ちるべきときに落ちる」ことを保証する (Priority: P4)

**Goal**: 既存・新規テストが対象の振る舞いを実際に検証していることを変異探針で確認し、無効なテストを強化・統合・削除して、その判断を記録する。

**Independent Test**: `uv run pytest -q` を実行し、各探針の改変でスイートが落ちることを確認する（改変は必ず元に戻す：復元 → `sha256sum` 一致 → 再実行 → `git status` 清浄）。

**依存**: US1（`test_graph_wiring.py` / `test_progress.py`）と US2（`test_compile_report.py`）の完了後に実施する。探針は**作業ツリーを改変するため、複数の探針を同時に実行してはならない**（結果が汚染され、判定を誤る）。

- [ ] T032 [US4] `tests/unit/test_models.py` の恒真アサートを置換する。`test_report_sources_invariant` は断言が構築式と同一であり、`compile_report` の出典構築を `[]` にしても緑のままだった（M1 未検出）。`compile_report` の描画経路を通して `sources` を検証する形へ置き換える（data-model 1.7 / LAYOUT-005-3）
- [ ] T033 [US4] **変異探針 M1** を実施する。`src/trend_researcher/nodes/compile_report.py` の出典構築を `[]` に改変し、`uv run pytest -q` が落ちることを確認して復元する。落ちなければ T032 / T024 を強化する（data-model 1.6）
- [ ] T034 [US4] **変異探針 M2** を実施する。`src/trend_researcher/graph.py` の `_route_after_search` を常に `continue` に改変し、スイートが落ちることを確認して復元する。落ちなければ T016 を強化する（FR-015 / data-model 1.6）
- [ ] T035 [US4] **変異探針 M3** を実施する。`src/trend_researcher/progress.py` の `ProgressEmitter.TOTAL` を 8 に改変し、スイートが落ちることを確認して復元する。落ちなければ T015 を強化する（FR-015 / data-model 1.6）
- [ ] T036 [US4] 縮退処理に対する追加の探針を実施する（quickstart 手順 5.3）。リトライループの打ち切り、`tools/transcript.py` の形式判定を `_parse_vtt` のみに、`nodes/compile_report.py` のキャッシュ書き込みの `try` 除去、`cache.read_json` の例外化、`providers/x.py` の重複除去（`seen` 判定）の除去。5 件すべてが検出されることを確認する（SC-004）
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

