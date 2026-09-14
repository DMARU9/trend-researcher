---

description: "Task list for 003-pipeline-hardening-and-evaluation"
---

# Tasks: AI パイプラインの堅牢化と品質測定（Open Deep Research の工夫取り込み）

**Input**: Design documents from `/specs/003-pipeline-hardening-and-evaluation/`

**Prerequisites**: `plan.md`（必須）, `spec.md`（必須・ユーザーストーリー）, `research.md`（R-1〜R-21）,
`data-model.md`, `contracts/`（LLM / CTX / SET / QRY / EVAL の 5 契約）, `quickstart.md`,
`.specify/memory/constitution.md`

**Tests**: **必須**（憲法 原則 I「テスト必須（NON-NEGOTIABLE）」）。各ユーザーストーリーは
そのストーリー単体で検証できるテストを最低 1 つ含む。テストは実装より先に書き、
**赤になることを確認**する。テストはネットワーク・実認証情報なしで完走させる
（原則 II。境界は `tests/conftest.py` の `FakeModelFactory` と `tests/integration/cli_harness.py`）。

**Organization**: ユーザーストーリー単位でフェーズを分ける。優先度順
（P1: US1 → US2 → US6、P2: US3 → US4 → US7、P3: US5 → US8）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 並行実行可（別ファイル・未完のタスクへの依存なし）
- **[Story]**: US1〜US8（`spec.md` のユーザーストーリーに対応）
- すべてのタスクに具体的なファイルパスを含める

## パスの規約

- 単一プロジェクト（`src/` レイアウト）。ソースは `src/trend_researcher/`、テストは `tests/`。
- 評価基盤のうち**テストで固定する部分**は `tests/eval/`（`test_*.py` を置かない）、
  **実走**は `script/evaluate.py`（`tests/` の外。収集対象外）。
- リポジトリルートは `/home/takumi/github/trend-researcher`。

## この機能固有の注意（全タスク共通）

### 1. 凍結する契約（触ると落ちる）

| 契約 | 実測による固定箇所 |
|---|---|
| 進捗行の文言・行数・状態 `messages` の内容 | `tests/unit/test_analyze_content.py:374-387`（厳密比較）、`tests/integration/test_full_flow.py:167-181`（`(node, phase)` 列） |
| 既定の入力での LLM 呼び出し回数 | `tests/integration/test_full_flow.py:241-242`（analyze = 5 / extract = 1）、`tests/unit/test_analyze_content.py:421`（同時 2） |
| 検索クエリの件数と内容 | `tests/unit/test_plan_search.py:108`（3 件）/`:113`（2 件）/`:118`（8）/`:128`（12）/`:134`（8）/`:139`（0）、`tests/integration/test_full_flow.py:228`（2） |
| `prompts_for("plan_search")[0]` が生成プロンプト | `tests/unit/test_plan_search.py:147/152/157/163/170` |
| `Configuration.model_fields_set` の意味（明示指定 > env） | `providers/x.py:48`、`tests/unit/test_config.py:266`、`tests/unit/test_configuration.py:281` |
| `result["contexts"][0].thread_text == ""` | `tests/integration/test_full_flow.py:444`（**`contexts` を空リストにすると落ちる**） |
| stdout = レポートのみ / stderr = 進捗・ログ / exit 0・1・2 | `tests/integration/test_cli_contract.py`（531 行） |
| 7 ノード構成と `NODE_ORDER` の一致 | `tests/unit/test_progress.py`、`tests/integration/test_graph_wiring.py` |
| `cache/report.json` の既存キー | `tests/unit/test_compile_report.py`、`tests/unit/test_cache.py` |

**推定される設計判断との衝突**: `spec.md` US7 の「X は 5 件ちょうど」を**強制してはならない**
（`plan.md` の設計判断 D-1）。点検は件数を**減らさない・増やさない**。既定プロンプトが
5 件を指示するため、既定の運用では 5 件のままである。

### 2. 追加の観測は `ProgressEmitter.note()` に限定する

`emit()` の行を増やす／`detail` を変えると凍結契約が壊れる。圧縮・縮退・フォールバック・
失敗・使用量の通知は**すべて** `note()`（stderr のみ。状態 `messages` へ積まない。`FR-029` /
`plan.md` 設計判断 D-3）で出す。

### 3. 既定値は現行の挙動と同じにする

`analysis_concurrency = 2` / `compression_threshold = 20000` / `retry_max = 2` は
現行の `Semaphore(2)`・`source_text[:20000]`・（新規導入の再試行）と整合させる。
**既定の入力で stdout・進捗・`cache/report.json` の既存キーが変更前と一致**すること（FR-035 /
SC-011 / SC-026）。

### 4. テストスイートは 60 秒以内（SC-013）

実測は **601 passed / 49.10 秒**（カバレッジ計測込み）。増加に使える余地は**約 11 秒**。
待機（再試行・圧縮のタイムアウト）は `SleepSpy` で除去し、実時間を消費しない。
判定コマンドは `uv run pytest -q`（`--no-cov` を付けない）に固定する。

### 5. 各フェーズのチェックポイント

`uv run pytest -q` を通し、**601 件から落ちていない**こと、カバレッジ 90% 以上、
60 秒以内を確認する。加えて `uv run ruff check .` と `uv run mypy src` を 0 件で維持する。

### 6. 変異探針（憲法 原則 I の「無効なテスト」を避ける）

実装の完了条件は「テストが green」だけでなく「**対象の挙動を壊すとテストが落ちる**」を含む。
各フェーズの最後に、そのフェーズの変異探針を実行する。手順は毎回同じ:
対象ファイルを `/tmp` に退避 → 変異を適用 → 対象テストが**落ちる**ことを確認 →
退避から復元 → **フルスイートを再実行**して 601 件以上 green に戻ることを確認。

### 7. 後方互換シムを残さない（憲法 原則 VI）

`source_text[:20000]` の切り捨て経路は**削除**する。旧名の別名・移行フラグ・二重実装を作らない。
参照実装（`open_deep_research`）のコードはそのまま複製しない（FR-037 / FR-063 / FR-064）。

---

## Phase 1: Setup（共有の準備）

**Purpose**: 変更前の安全網と、設計の分岐点となる実測を確定する。**この段階ではソースを変更しない。**

- [X] T001 `plan.md` の「基準値のずれ」と Constitution Check に記録した基準値（**601 passed / カバレッジ 96.65% / `ruff` 0 件 / `mypy` 0 件 / 49.10 秒**）をブランチ `003-pipeline-hardening-and-evaluation` の作業ツリーで再現する（`uv run pytest -q`、`uv run ruff check .`、`uv run mypy src`、`git status --short`）。結果を作業ツリーの確認（`git status --short` が ` M .specify/feature.json` と `?? specs/003-pipeline-hardening-and-evaluation/` のみ）とともに本ファイルの「実装メモ §0」に記録する
- [X] T002 [P] 遅いテストを把握して時間予算を確保する。`uv run pytest -q --no-cov --durations=15` を実行し、上位 15 件の所要時間を「実装メモ §2」に控える（SC-013 の 60 秒以内を守るため、追加するテスト群の上限を決める根拠にする）
- [X] T003 [P] オフライン制約を実測する。`env -u OPENAI_API_KEY -u XTR_ACCOUNTS_DB -u YTR_ACCOUNTS_DB uv run pytest -q --no-cov` を実行し、認証情報なしでも **601 passed** のままであることを確認する（原則 II の安全網）
- [X] T004 [P] **設計の分岐点 1 を実測する**: 構造化出力が `json_schema` で通るかを、`uv run python -c` で `ChatOpenAI.with_structured_output(<Pydantic モデル>, method="json_schema")` の疎通を確認して確定する。通らなければ `Configuration.structured_method` の**既定を `function_calling` にする**（research §R-2 / 未解決事項 1）。「実装メモ §1」に記録
- [X] T005 [P] **設計の分岐点 2 を実測する**: 実際の上限超過応答の形（`status_code` / `exc.body` の構造 / メッセージの語彙）を採取し、`contracts/llm-invocation-contract.md` §5 の条件 3 の語彙を確定する（research §R-1 / 未解決事項 2）。テストは語彙に依存しない形（条件ごとの反例）で書く方針も同時に決める。「実装メモ §1」に記録
- [X] T006 [P] **設計の分岐点 3 を実測する**: `TR_EVAL_MODEL` の既定値（生成 `openai:mimo-v2.5` と同じで走るか、判定用の別名が必要か）を疎通で確定する（research §R-19 / 未解決事項 3）。「実装メモ §1」に記録
- [X] T007 [P] **設計の分岐点 4 を実測する**: Pydantic v2 の `Configuration.model_copy(update=...)` → 再検証の 2 案（`Configuration.model_validate(model_dump())` / `_check_bounds(settings)` による各フィールドの検査）のうち、**`model_fields_set` を保つ**のはどちらかを短いスクリプトで実測して確定する（research §R-10）。`providers/x.py:48` が `model_fields_set` を読むため、ここを誤ると US5 / US8 が壊れる。「実装メモ §1」に記録
- [X] T008 [P] `tools/parse.py` の既存 4 関数（`_load_json_object` / `extract_json_block` / `extract_list_items` / `extract_section`）が `<summary>` 形式のタグを扱えるかを実測する。`extract_section` は見出し前提（実測）のため、扱えない場合は**圧縮専用のタグ抽出を `tools/compression.py` 内に置く**方針を確定する（research §R-5。`tools/parse.py` を無理に一般化しない）。「実装メモ §1」に記録

**Checkpoint**: 基準値・時間予算・オフライン制約・設計の分岐点 4 件が「実装メモ」に記録され、ソースは未変更。

---

## Phase 2: Foundational（全ストーリーの前提・ブロッキング）

**Purpose**: 4 つ以上のストーリーが共有する基盤（共有モデル・状態フィールド・設定の宣言・
追加観測の出口・テスト境界）と、**凍結契約の回帰テスト**を用意する。

**⚠️ CRITICAL**: このフェーズが完了するまで、どのユーザーストーリーも開始できない。

**⚠️ このフェーズが下位の要求を担う**: FR-024（設定の単一解決）の**宣言部分**（型・値域・
選択肢・既定値・説明）と FR-046 / FR-054 の切り替え項目はここで宣言し、
US5（注入と拒否の挙動）と US8（宣言の検証と Studio）で**使い、検証する**。

### Tests for Foundational（憲法 原則 I により必須）⚠️

- [X] T009 [P] 凍結契約の回帰テストを作成する（**実装より先に書き、赤にならないことを確認する**。現状の挙動をそのまま固定するため green になるのが正しい）: 既定の入力で stdout が byte 一致 / 進捗行の文言と行数が不変 / `analyze_content` と `extract_common` の呼び出し回数が不変 / `report.notes` の既存要素が不変。`tests/integration/test_frozen_contracts.py`
- [X] T010 [P] 新規モデルと状態フィールドのテストを作成する: `CompressedSource` / `Degradation` / `Failure` / `ModelUsage` の必須項目と不変条件（`after_chars < before_chars` 等）、`AgentState` に 4 フィールドが載ること、`usage` が `Annotated[..., operator.add]` で**並列結果を連結**すること。`tests/unit/test_models.py`（拡張）
- [X] T011 [P] `Configuration` の宣言と値域の走査テストを作成する: 全項目に `description` があること、`ge` / `le` / `Literal` の宣言が期待どおりであること、`x_oap_ui_config` が付いていること、`ConfigurationError` のメッセージに項目名・入力値・期待する値域が入ること。`tests/unit/test_configuration.py`（拡張）
- [X] T012 [P] `ProgressEmitter.note()` のテストを作成する: stderr に 1 行（書式 `[補足] ...`）を書き、**`get_messages()` が増えない**こと、`emit()` の既存書式と `messages` の内容が不変であること。`tests/unit/test_progress.py`（拡張）
- [X] T013 [P] テスト境界のフェイクを検証するテストを作成する: `_FakeLLM` が `with_structured_output` と `usage_metadata` を持つこと、`FakeModelFactory` が `trend_researcher.tools.compression.build_model` も差し替えること、`no_retry_sleep` が `tools.llm.asyncio.sleep` を対象にすること（既存の「フィクスチャが実際に patch しているか」検証の延長）。`tests/unit/test_fixtures.py`（拡張）

### Implementation for Foundational

- [X] T014 [P] `src/trend_researcher/models.py` に 4 型を追加する: `CompressedSource` / `Degradation` / `Failure` / `ModelUsage`（data-model.md §3 の表どおり。既存フィールドの削除・改名をしない）
- [X] T015 [P] `src/trend_researcher/state.py` の `AgentState` に 4 フィールドを追加する: `compressed` / `degradations` / `failures`（通常フィールド）、`usage`（`Annotated[list[ModelUsage], operator.add]`）。`AgentInputState` は**変更しない**（US6 の実走は 3 項目のみを使う）
- [X] T016 `src/trend_researcher/configuration.py` に次の 3 つを追加する（T007 の実測結果に従う）: (a) 追加 11 項目の宣言（`ge` / `le` / `Literal` / `description` / `json_schema_extra={"x_oap_ui_config": ...}`。値域は `data-model.md` §1.1 と `research.md` §R-20 の表）、(b) `ConfigurationError(field, value, expected, message)`、(c) 上書き適用後の再検証（`_check_bounds` または `model_validate` のうち `model_fields_set` を保つ方）。`resolve_env` と `load()` の解決順は**変えない**
- [X] T017 [P] `src/trend_researcher/progress.py` の `ProgressEmitter` に `note(text)` を追加する: stderr に `[補足] {text}` を 1 行書き、`self._messages` へは**積まない**。`NODE_ORDER` と `emit` は変更しない
- [X] T018 [P] テスト境界のフェイクを拡張する: (a) `tests/conftest.py` の `_FakeLLM` に `with_structured_output(schema, **kwargs)` を追加し既定で `OutputParserException` を送出するランを返す、(b) `FakeModelFactory.install(responses, *, structured=None)` を追加（`structured` 指定時は成功するラン）、(c) `_FakeMessage` に `usage_metadata`（既定 `None`）、(d) patch 対象に `trend_researcher.tools.compression` を追加、(e) `no_retry_sleep` の対象に `tools.llm.asyncio.sleep` を追加し `autouse` にする、(f) `tests/integration/cli_harness.py` の `_FakeLLM` にも同じ 2 つを追加する（**(d) は `tools/compression.py` が未作成のため T024 で追加**。実装メモ §6 の乖離表を参照）
- [X] T019 `tests/unit/test_platform_scan.py` を実行して規則 (a)+(b) が**0 件のまま**であることを確認し、新規モジュール（`tools/compression.py` / `tools/degradation.py` / `usage.py` 相当）と `Configuration` の追加が走査に引っかからないことを確かめる（原則 IV）。引っかかった場合は走査テストではなく**ソース側を直す**（FR-035）

**Checkpoint**: 基盤が完成。共有モデル・状態フィールド・設定の宣言・`note()`・フェイクの拡張が
揃い、凍結契約の回帰テストが green。ここから各ユーザーストーリーを独立して開始できる。

---

## Phase 3: User Story 1 - 長い素材のネタを取りこぼさない (Priority: P1) 🎯 MVP

**Goal**: しきい値を超える素材を、素材**全体**から LLM で圧縮してから解析に渡す。圧縮が失敗しても
実行は完走し、理由が残る。

**Independent Test**: 後半にのみ固有キーワードを含むしきい値超過の素材を入力し、解析に渡された
プロンプトとレポートにそのキーワードが現れることを確認する。圧縮を失敗させるフェイクを注入し、
実行が完走して取代（生素材）が使われることも確認する。

### Tests for User Story 1（憲法 原則 I により必須）⚠️

- [X] T020 [P] [US1] 圧縮のテストを作成する: しきい値超過で**素材 1 件につき 1 回**呼ぶ / しきい値以下で**0 回** / 出力がしきい値以下に切り詰められる / 例外・タイムアウト・空応答で取代に切り替わり理由が `reason` に入る / `CompressedSource` の内容。`tests/unit/test_compression.py`（新規）
- [X] T021 [P] [US1] 解析への取り込みのテストを作成する: 圧縮後の素材が `provider.analyze_content_prompt` に渡る（**後半のキーワードがプロンプトに含まれる**）/ しきい値以下では素材がそのまま渡る / 圧縮の発生が `note()`（stderr）に出る。`tests/unit/test_analyze_content.py`（拡張）
- [X] T022 [P] [US1] 圧縮失敗時の完走テストを作成する: 圧縮が例外・タイムアウトでも解析が続き、**終了コード 0** でレポートが出る。`tests/integration/test_full_flow.py`（拡張。既存のシナリオの期待値は書き換えない）

### Implementation for User Story 1

- [X] T023 [P] [US1] `src/trend_researcher/prompts.py` に `COMPRESSION_PROMPT` を追加する: 素材全体を入力に取り、`<summary>…</summary>` と `<key_excerpts>…</key_excerpts>` の 2 部を返す。**元の指示文をプロンプトに含める**（文脈を失わない。research §R-5）。停止条件と出力形式の節を持つ（FR-055 / FR-057）
- [X] T024 [P] [US1] `src/trend_researcher/tools/compression.py` を新規作成する: `compress_text(text, *, model, max_chars, timeout)`。`asyncio.wait_for(model.ainvoke(...), timeout=...)` で 1 回だけ呼び、`<summary>` / `<key_excerpts>` を抽出して連結し `max_chars` で切り詰める（FR-007）。失敗時は生素材を `max_chars` で切って返す。T008 の実測により、タグ抽出が必要ならこのモジュール内に専用実装を置く（`tools/parse.py` を一般化しない）
- [X] T025 [US1] `src/trend_researcher/nodes/analyze_content.py` の `source_text[:20000]`（実測: 69 行目付近）を**削除**し、`tools/compression.py` の圧縮経路に置き換える。しきい値とタイムアウトは `Configuration`（`from_runnable_config`）から取り、コードに固定値を書かない（FR-005 / FR-032。後続段が生データを参照しないので、圧縮はここで完結させる）
- [X] T026 [US1] `src/trend_researcher/nodes/analyze_content.py` で圧縮の結果を `state["compressed"]` に記録し、`ProgressEmitter.note()` に「圧縮した件数」を 1 行出す（`emit()` の文言は**変更しない**。FR-017 / FR-029 / D-3）。旧経路の互換分岐を残さない（原則 VI）
- [X] T027 [US1] 変異探針を実行する: (a) 圧縮の分岐を `pass` にする（`return text[:max_chars]` のみ）→ T020 が落ちる、(b) 切り詰めを削る → T020 の FR-007 のケースが落ちる、(c) 発動条件を `>=` に変える → T021 のしきい値ちょうどのケースが落ちる。それぞれ復元後にフルスイートを再実行する

**Checkpoint**: US1 が単体で機能し、既定の入力（短い素材）では呼び出し回数も出力も不変。

---

## Phase 4: User Story 2 - LLM の応答が崩れても動き続ける (Priority: P1)

**Goal**: 指示解釈・個別解析・共通テーマ抽出を構造化スキーマで受け、規定回数まで自動再試行し、
それでも得られなければ既存の決定的パーサへフォールバックする。

**Independent Test**: スキーマに合致しない応答を返すフェイクで試行回数と最終結果を確認し、
全回失敗するフェイクで決定的パーサの経路へ落ちて実行が完走することを確認する。

**Note**: このフェーズが `tools/llm.py` の**呼び出し境界**（再試行・待機・構造化）を作る。
US3（縮退）と US8（使用量）は同じ関数に層を足すため、このフェーズの後に置く。

### Tests for User Story 2（憲法 原則 I により必須）⚠️

- [X] T028 [P] [US2] `tools/llm.py` の呼び出し境界のテストを作成する: 合計試行回数が `1 + retry_max`（既定 3）/ 待機が `retry_wait_seconds` 回だけ呼ばれる / スキーマ違反と一時エラーの両方が再試行対象 / `retry_max = 0` で再試行しない / 構造化出力の `method` が設定値になる / 上限超過は再試行**しない**（US3 の前提を先に固定）。`tests/unit/test_llm.py`（拡張）
- [X] T029 [P] [US2] `parse_instruction` のテストを作成する: 構造化出力が成功する経路で `ResearchInstruction` の**中身が既存の決定的解析と一致**する / 全回失敗で `extract_json_block` のフォールバックに落ちる / フォールバックが `note()` と中間データに残る。`tests/unit/test_parse_instruction.py`（拡張。既存の期待値は書き換えない）
- [X] T030 [P] [US2] `extract_common` のテストを作成する: 構造化出力の成功経路 / `extract_list_items` / `extract_section` へのフォールバック経路 / 0 件のときの挙動。`tests/unit/test_extract_common.py`（拡張）

### Implementation for User Story 2

- [X] T031 [US2] `src/trend_researcher/tools/llm.py` に構造化呼び出しの**単一経路**を追加する: `build_model(role, env_prefix).with_structured_output(Model, method=<structured_method>)` ＋ 再試行（`retry_max` / `retry_wait_seconds`。待機は `asyncio.sleep` を通す）＋ 上限超過以外の失敗の再試行。テキスト呼び出しにも同じ再試行を載せる。`ChatOpenAI` を直接構築しない（FR-045）
- [X] T032 [US2] `src/trend_researcher/nodes/parse_instruction.py` を構造化出力へ切り替え、全回失敗時に既存の `tools/parse.py` の経路へフォールバックする（正常系とフォールバックの**両方**をテストで固定。FR-012）。決定的事実解析（`_YEAR_RE` 等）は変更しない
- [X] T033 [US2] `src/trend_researcher/nodes/extract_common.py` を構造化出力へ切り替え、フォールバックを `extract_list_items` / `extract_section` にする
- [X] T034 [US2] `src/trend_researcher/nodes/analyze_content.py` の解析呼び出しを構造化出力へ切り替え、フォールバックを既存の `_parse_angles_table` にする（**既存のパーサを残す**。FR-012）
- [X] T035 [US2] 変異探針を実行する: (a) 再試行の待機を削る → T028 の待機回数のテストが落ちる、(b) フォールバックの分岐を削る（例外を送出する）→ T029 / T030 が落ちる、(c) `with_structured_output` を外す → T029 / T030 の成功経路が落ちる。復元後にフルスイートを再実行する

**Checkpoint**: US1 と US2 が独立して機能。既定の入力（フェイクが構造化出力に失敗する）では
フォールバック経路を通るため、呼び出し回数と出力は不変。

---

## Phase 5: User Story 6 - レポートの良し悪しを数字で比べられる (Priority: P1)

**Goal**: 固定した指示セットに対してレポートを 6 観点で採点し、提示順を伏せて 2 つの構成を比較し、
トークン数と並べて記録する。判定ロジックはテストで固定し、LLM を伴う実走は本体の外に分離する。

**Independent Test**: 固定の指示セットとモックの判定モデルで採点が行われ、観点ごとの点数・理由・
使用量・設定の識別子を含む結果ファイルが出力されることを確認する。判定モデルを失敗させ、
実行が完走して失敗が記録されることも確認する。

**Note**: このフェーズは `src/trend_researcher/` を**変更しない**（FR-065 / FR-074）。
`tests/eval/`（テストで固定）と `script/evaluate.py`（実走・収集対象外）に閉じる。

### Tests for User Story 6（憲法 原則 I により必須）⚠️

- [X] T036 [P] [US6] 採点ロジックのテストを作成する: 5 観点以上を採点する / 1〜5 を 0〜1 に正規化する / **値域検査をしない**（`7` をそのまま記録）/ 型違い・欠落は取得失敗にしてその観点を未採点にする / 総合品質が 6 観点の平均（`None` は除外）/ 1 観点の失敗で全体が落ちない / `correctness` が対象外として記録されている。`tests/unit/test_evaluation.py`（新規）
- [X] T037 [P] [US6] 記録のテストを作成する: ファイル名が `{dataset}__{config_name}__{commit}__{model_slug}.jsonl` / データセットの指紋が記録される / 既定で追記され `--overwrite` でのみ上書き / JSONL 1 行 1 レコード / `ensure_ascii=False` / 保存先が既定で `artifacts/eval/` / 2 つの結果を**名前で指定**して比較でき、生成を繰り返さない。`tests/unit/test_evaluation_records.py`（新規）
- [X] T038 [P] [US6] 実走入口の契約テストを作成する（`script/evaluate.py` を `importlib.util.spec_from_file_location` で読み込む）: (a) `pyproject.toml` の `testpaths` が `["tests"]` のまま、(b) argparse のオプション集合が期待どおり、(c) `subprocess` を import していない、(d) `trend_researcher` と `render_report` を参照している、(e) 初期状態に入れるキーが `messages` / `platform` / `max_results` のみ（AST で走査）。`tests/unit/test_evaluation_entrypoint.py`（新規）
- [X] T039 [P] [US6] 対応表の整合テストを作成する: 観点が 5 以上 / `correctness` が対象外と記録 / 各行が実在する観点と実在する `prompts.py` の制約を指す（制約側の存在は US7 の T068 が追加する節と一致させる）。`tests/unit/test_evaluation.py`（T036 と同じファイルに追記）

### Implementation for User Story 6

- [X] T040 [US6] `tests/eval/schemas.py` を作成する: 採点の受け取りスキーマ（`axis` / `score` / `reason`。`ge` / `le` を付けない = FR-067）と `AxisScore` への変換
- [X] T041 [US6] `tests/eval/evaluators.py` を作成する: 観点ごとの判定（LLM 呼び出しは**注入された呼び出し可能オブジェクト**経由。`tools/llm.py` の経路を使う）、正規化、総合品質の集約、提示順のランダム化、1 観点の失敗の隔離（FR-039 / FR-040 / FR-041 / FR-068）
- [X] T042 [US6] `tests/eval/judge_prompts.py` を作成する: 観点ごとの専用判定プロンプト（生成側の制約を反映。FR-040）
- [X] T043 [US6] `tests/eval/datasets.py` と `tests/eval/fixtures/tr-basic.json` を作成する: 名前付きデータセットの解決（既定は同ディレクトリの `fixtures/`）、指紋の計算、`DatasetEntry` の検証（FR-070 / FR-071 / FR-073）
- [X] T044 [US6] `tests/eval/axes.md` を作成する: 観点一覧・対応する `prompts.py` の制約（FR-048）・参照実装の 6 評価との対応（採用 / 対象外と理由）・**参照実装の実測済み欠陥 6 件とその扱い**（FR-074 / research §R-21）を 1 つの対応表に記録する
- [X] T045 [US6] `script/evaluate.py` を作成する: `--dataset` / `--platform` / `--config`（複数） / `--config-name` / `--judge-model` / `--out` / `--overwrite` / `--judge-only`。生成は公開 API を in-process で呼び、初期状態は 3 項目のみ（FR-065）。`subprocess` を import しない。判定モデルは `resolve_env("EVAL_MODEL", default=...)`（T006 の実測値）で解決し、生成と同一なら `judge_model_is_generator: true` を記録する（FR-069）
- [X] T046 [US6] 変異探針を実行する: (a) 採点に `ge=1` を付ける → T036 が落ちる、(b) 総合品質を `mean` から `sum` に変える → T036 が落ちる、(c) `script/evaluate.py` に `subprocess` を import する → T038 が落ちる、(d) 初期状態に 4 番目のキーを足す → T038 が落ちる、(e) 無条件に上書きする → T037 が落ちる、(f) 観点を 4 つに減らす → T036 が落ちる

**Checkpoint**: US6 が単体で機能。`uv run pytest -q` に実走が含まれず、ネットワークなしで完走する。

---

## Phase 6: User Story 3 - 入力が上限に達しても最後まで走り切る (Priority: P2)

**Goal**: 上限超過を検出し、入力を段階的に縮小して再試行する。使い切ったら理由を明示して終了する。
縮退が起きたことは実行後に確認できる。

**Independent Test**: 上限超過を返すフェイクを注入し、段階的な縮小を経てレポートが生成され終了コード 0
になることを確認する。`invalid model` を含む `400` が上限超過と誤認されないことも確認する。

**依存**: T031（`tools/llm.py` の呼び出し境界）に層を足す。

### Tests for User Story 3（憲法 原則 I により必須）⚠️

- [ ] T047 [P] [US3] 検出器のテストを作成する: 4 条件のそれぞれを満たす入力で `True` / 条件 3 を満たさない `400` で `False` / **除外条件（`invalid model` / `invalid api key` / `unsupported`）で `False`** / 上限超過以外の例外（接続エラー・認証失敗）で `False`。`tests/unit/test_degradation.py`（新規）
- [ ] T048 [P] [US3] 縮小のテストを作成する: 段数が `degrade_max_attempts` を超えない / 各段で入力長が `shrink_ratio` 分だけ短くなる / 停止条件（縮小しない・`min_input_chars` 未満）で打ち切る / 未知モデルでも縮退が成立し `limit_known = False` が記録される / `Degradation` の内容。`tests/unit/test_degradation.py`（T047 と同じファイルに追記）
- [ ] T049 [P] [US3] 縮退の連携テストを作成する: 上限超過は再試行**せず**縮退へ渡る / 縮小後の呼び出しで成功したら `Degradation` が 1 件記録され実行が成功する / 段数を使い切ったら例外が送出される（→ exit 1）。`tests/unit/test_llm.py`（拡張）
- [ ] T050 [P] [US3] CLI のテストを作成する: 縮退を使い切ったときに stderr に理由（試した段数・縮小前後の長さ）が出て **exit 1**、上限超過以外のエラーも exit 1、上限超過で縮退が成功した場合は exit 0。`tests/integration/test_cli_contract.py`（拡張）

### Implementation for User Story 3

- [ ] T051 [US3] `src/trend_researcher/tools/degradation.py` を新規作成する: `is_token_limit_exceeded(exc)`（`contracts/llm-invocation-contract.md` §5 の 4 条件。`isinstance` ベースで `body` は dict / str の両方を扱う）/ `get_model_token_limit(model)` / `shrink(text, ratio)` / `next_ladder(...)`（停止条件つき）。**参照実装の文字列依存の判定を移植しない**（FR-063 / FR-064 / research §R-1）
- [ ] T052 [US3] `src/trend_researcher/tools/llm.py` に縮退を組み込む: 上限超過と判定されたら再試行せず、`degrade_max_attempts` 段まで入力を縮小して呼び直す。段ごとに `Degradation` を状態へ返し、使い切ったら理由つきの例外を送出する。無効な引数をモデルへ渡す経路を作らない（FR-063）
- [ ] T053 [US3] `src/trend_researcher/__main__.py` で縮退の使い切りを扱う: 理由（試した段数・縮小前後の長さ）を stderr に出して **exit 1**。既存の例外ハンドリング（TimeoutError → exit 1 / その他 → exit 1）の分岐を壊さない
- [ ] T054 [US3] 縮退を `ProgressEmitter.note()` に 1 行で出す（段数・縮小前後の長さ。FR-017 / FR-029）。`emit()` の文言は変更しない
- [ ] T055 [US3] 変異探針を実行する: (a) 検出器の除外条件（条件 4）を削る → T047 の反例が落ちる、(b) `shrink_ratio` を `1.0` にする → T048 / T049 が落ちる、(c) 停止条件 2 を削る → T048 が落ちる、(d) 上限超過を再試行に回す → T049 が落ちる

**Checkpoint**: US1・US2・US6 と US3 が独立して機能。既定の入力（上限超過なし）では
縮退が発生せず、呼び出し回数も出力も不変。

---

## Phase 7: User Story 4 - 1 件の失敗でレポート全体を失わない (Priority: P2)

**Goal**: 解析 1 件の失敗を隔離し、成功分でレポートを生成する。失敗した対象は
「解析できなかった」ことが分かる形で残る。

**Independent Test**: 解析対象 10 件のうち 3 件で例外を発生させるフェイクを注入し、
7 件の結果を含むレポートが生成され、失敗件数と理由が明示されることを確認する。

### Tests for User Story 4（憲法 原則 I により必須）⚠️

- [ ] T056 [P] [US4] 部分失敗の隔離テストを作成する: 10 件中 3 件が失敗して 7 件の解析が得られる / 失敗が `failures` に入り**無言で消えない** / 実行は exit 0 / 全件失敗でも完走し、失敗の事実と理由が残る。`tests/unit/test_analyze_content.py`（拡張）
- [ ] T057 [P] [US4] キャンセルのテストを作成する: `asyncio.CancelledError` は部分失敗として飲み込まれず**再送出**される（原則 V「エラーを握りつぶさない」）。`tests/unit/test_analyze_content.py`（T056 と同じファイルに追記）
- [ ] T058 [P] [US4] 文脈取得の失敗テストを作成する: 一部の候補で追加文脈が取れなくても取得分で解析が続き、失敗が `failures` に記録され、**既存の `notes` の文言（`スレッド取得に失敗しました（本文のみで解析）`）は変更されない**。`tests/unit/test_fetch.py`（拡張）＋ `tests/integration/test_full_flow.py`（既存シナリオの維持確認）
- [ ] T059 [P] [US4] 失敗の可視化のテストを作成する: 失敗の件数と理由が `note()`（stderr）と中間データ（`include_intermediate = True` のとき `cache/failures.json`）で確認でき、**`report.notes` には既定で追加されない**。`tests/unit/test_compile_report.py`（拡張）

### Implementation for User Story 4

- [ ] T060 [US4] `src/trend_researcher/nodes/analyze_content.py` の `asyncio.gather` を `return_exceptions=True` にし、`asyncio.CancelledError` だけ再送出する。成功分を `analyses`、失敗分を `failures` に分ける（FR-020）
- [ ] T061 [US4] `src/trend_researcher/nodes/analyze_content.py`（または `__main__.py` の既存ハンドリングを壊さない位置）で、失敗の件数と理由を `note()` に 1 行で出す（FR-023）
- [ ] T062 [US4] 全件失敗のときに `src/trend_researcher/nodes/compile_report.py` の `notes` に「解析 0 件（すべて失敗: N 件）」を追加し、exit 0 で完走させる（US4 シナリオ 3）。**この行は全件失敗のときだけ**追加する（既定の入力では増えない = FR-035）
- [ ] T063 [US4] `src/trend_researcher/providers/x.py` / `youtube.py` 側の取得失敗（`fetch` 経路）を `failures`（`kind="context"`）に記録する。既存の `notes` の文言と `report.notes` の要素は**変えない**
- [ ] T064 [US4] 変異探針を実行する: (a) `return_exceptions=True` を外す → T056 が落ちる、(b) `CancelledError` の再送出を削る → T057 が落ちる、(c) `failures` への記録を削る → T056 が落ちる、(d) 全件失敗の `notes` を無条件に足す → T009（凍結契約）が落ちる

**Checkpoint**: US1〜US4 と US6 が独立して機能。既定の入力（失敗なし）では `failures` が空で出力は不変。

---

## Phase 8: User Story 7 - 検索クエリを自分で点検してから実行する (Priority: P2)

**Goal**: クエリ生成直後に**同一ノード内で 1 回だけ**自己点検し、重複の除去・不足の補充・期間表現の
除去をしてから確定する。点検が失敗しても生成結果で継続する。

**Independent Test**: LLM 呼び出しが生成 1 ＋ 点検 1 の計 2 回で固定されること、点検で重複が除かれること、
点検を失敗させても生成結果で同じ経路を進むことを確認する。

**設計判断（必須）**: `spec.md` US7 シナリオ 3 の「X は 5 件ちょうど」を**強制しない**（`plan.md` の D-1）。
点検は件数を減らさない・増やさない。根拠は `tests/unit/test_plan_search.py:108-139` と
`tests/integration/test_full_flow.py:228` の実測（件数を固定している 7 箇所）。

### Tests for User Story 7（憲法 原則 I により必須）⚠️

- [ ] T065 [P] [US7] 呼び出し回数と順序のテストを作成する: `self_review = True` で **2 回**（生成 1 ＋ 点検 1）、`False` で **1 回** / `prompts_for("plan_search")[0]` が**生成**プロンプト（点検は 2 番目）/ 点検が反復しない。`tests/unit/test_plan_search.py`（拡張）
- [ ] T066 [P] [US7] 適用規則のテストを作成する（規則 1〜5）: 点検が 0 行 → 生成結果を採用 / 点検が少ない → **生成結果から補充**して件数を下回らない / 点検が多い → `max_search_queries` で切り詰め / 重複を除去 / 生成 0 件 → 0 件のまま / 点検が例外・タイムアウト → 生成結果で継続。`tests/unit/test_plan_search.py`（T065 と同じファイルに追記）
- [ ] T067 [P] [US7] 件数契約の宣言テストを作成する: `Provider.required_query_count` が X = 5 / YouTube = 1 で宣言されている / 実装側に**明示の注釈**がある（mypy の Protocol 不変性） / `prompts.py` の生成プロンプトの件数指示と一致する（X のプロンプトは「5 件ちょうど」「5 件を厳守」を実測済み）。`tests/unit/test_providers.py`（拡張）
- [ ] T068 [P] [US7] プロンプトの走査テストを作成する: `prompts.py` の 8 ＋ 1 定数が**停止条件**と**出力形式**の節を持つ / 重要制約（出力言語・件数・引用形式）が**役割の異なる 2 箇所**にある（FR-058）/ 固定テンプレートの禁止語（「そのまま使う」等）が無い / 判定不能表現の禁止（「おそらく」等で埋めない）がある。`tests/unit/test_prompts.py`（新規）

### Implementation for User Story 7

- [ ] T069 [P] [US7] `src/trend_researcher/providers/base.py` の `Provider` Protocol に `required_query_count: int | None` を宣言し、`src/trend_researcher/providers/x.py` に `required_query_count: int | None = 5`、`src/trend_researcher/providers/youtube.py` に `= 1` を実装する（**明示の注釈**を付ける。mypy の Protocol 可変属性は不変）。コアに `platform == "..."` を書かない（原則 IV）
- [ ] T070 [US7] `src/trend_researcher/nodes/plan_search.py` に自己点検を追加する: `Configuration.self_review` が真のとき、生成の**後**に 1 回だけ点検を呼ぶ（生成と同じ行解析経路 = `_clean_query`。構造化出力は使わない）。規則 1〜5 を適用し、上限（`max_search_queries`）は従来どおり適用する。反復・リトライをしない（FR-050）。失敗時は生成結果で継続し `note()` に 1 行出す（FR-051）
- [ ] T071 [P] [US7] `src/trend_researcher/prompts.py` の 8 定数に**停止条件**と**出力形式**の節を追加し、重要制約（出力言語・件数・引用形式）を役割の異なる 2 箇所（役割説明の直後と出力形式の節）へ明示する（FR-055 / FR-056 / FR-057 / FR-058）。固定テンプレートの指示を書かない
- [ ] T072 [US7] 変異探針を実行する: (a) 点検の呼び出しを削る → T065 が落ちる、(b) 補充を削る（点検の結果をそのまま採用）→ T066 が落ちる、(c) `self_review` の既定を `False` にする → T065 が落ちる、(d) 点検を生成の**前**に呼ぶ → T065 のプロンプト順序が落ちる、(e) 二重明示の 1 箇所を削る → T068 が落ちる。復元後にフルスイートを再実行し、**既定の入力で検索クエリが不変**であること（T009）を確認する

**Checkpoint**: US1〜US4・US6・US7 が独立して機能。既定の入力でクエリの件数と内容は不変
（フェイクは全呼び出しに同じ内容を返すため「生成 3 件 → 点検 3 件」になる）。

---

## Phase 9: User Story 5 - 実行の予算と状態の行き先が分かる (Priority: P3)

**Goal**: 上限・しきい値・タイムアウト・並列数・再試行回数をすべて実行時設定から注入し、
生データと整形済みデータを状態上で区別し、不要になった中間データを解放する。
不正な値は起動時に拒否する。

**Independent Test**: 各設定を実行時に変更して挙動が変わることを確認し、設定の解決経路が 1 つで
あること、不要になった中間データが状態から解放されることをテストで固定する。

**依存**: T016（設定の宣言。Foundational）。

### Tests for User Story 5（憲法 原則 I により必須）⚠️

- [ ] T073 [P] [US5] 設定の注入テストを作成する: `analysis_concurrency` を 1 / 2 にして同時実行数がそれぞれ 1 / 2 になる / `retry_max` が試行回数に反映される / `compression_threshold` が圧縮の発動を変える / `degrade_max_attempts` が段数に反映される（**すべて実行時設定から注入**され、コードに固定値が無い）。`tests/unit/test_analyze_content.py`（拡張）＋ `tests/unit/test_llm.py`（拡張）
- [ ] T074 [P] [US5] 優先順位のテストを作成する: 環境変数と実行時指定が食い違うときに既定の優先順位（明示指定 > env > 既定値）に確定し、`model_fields_set` の意味が変わらない（`providers/x.py:48` が読む）。`tests/unit/test_configuration.py`（拡張）
- [ ] T075 [P] [US5] 状態の解放テストを作成する: レポート確定後に `contexts[].text` / `thread_text` / `replies` と `candidates[].text` が空になる / **`contexts` のレコードは残る**（`tests/integration/test_full_flow.py:444` を壊さない）/ `report.candidates` の内容が保持される（解放がレポート組み立ての**後**）/ `analyses` / `common_themes` / `report` は解放されない。`tests/unit/test_compile_report.py`（拡張）
- [ ] T076 [P] [US5] 中間データの切り替えテストを作成する: `include_intermediate = False`（既定）で `cache/` に新しいファイルが増えず `cache/report.json` の既存キーが**変更前と一致** / `True` で `compressed.json` / `degradations.json` / `failures.json` が増える / `cache_dir` 未指定なら何も書かない。`tests/unit/test_compile_report.py`（T075 と同じファイルに追記）
- [ ] T077 [P] [US5] 起動時拒否のテストを作成する: 値域外の CLI 引数（`--max-results 0`）で stderr に「設定が不正です: max_results=0（期待: ...）」が出て **exit 2** / 丸めも既定値への置換もされない / **LLM が 1 回も呼ばれない**（ノード実行前） / env 経由の値域外も同じ。`tests/integration/test_cli_contract.py`（拡張）

### Implementation for User Story 5

- [ ] T078 [US5] 5 ノード（`parse_instruction` / `plan_search` / `analyze_content` / `extract_common` / `compile_report`）の設定参照を `Configuration.from_runnable_config(config)` 経由の値に統一する: `analysis_concurrency` を `asyncio.Semaphore(...)` に、`retry_max` / `retry_wait_seconds` を呼び出し境界に、`compression_threshold` / `compression_timeout_seconds` を圧縮に、`degrade_max_attempts` / `shrink_ratio` / `min_input_chars` を縮退に渡す。**コードに固定値を残さない**（FR-005 / FR-024 / FR-025）
- [ ] T079 [US5] `src/trend_researcher/__main__.py` に起動時検証を追加する: 上書き適用後に T016 の再検証を呼び、`ConfigurationError` を捕捉して stderr に `message` を出し **exit 2**（`_parse_args` の失敗と同じ扱い）。検証は LLM・検索・ファイル読み書きの**前**に行う（FR-024 / SC-023）
- [ ] T080 [US5] `src/trend_researcher/nodes/compile_report.py` に次を追加する: (a) `include_intermediate = True` なら `cache/compressed.json` / `degradations.json` / `failures.json` を書く（解放の**前**）、(b) レポート確定後に `contexts` / `candidates` の**中身を解放**する（順序: report 組み立て → 中間データ → 解放。T075 が固定）、(c) `note()` に内訳（圧縮・縮退・失敗の件数）を出す
- [ ] T081 [US5] `extract_common` / `compile_report` が**生データを参照しない**ことを走査テストで固定する: `state.get("contexts")` / `candidates[..].text` を新しい用途で読み始めていないこと（既存の件数参照のみ許可）。`tests/unit/test_state.py`（新規）
- [ ] T082 [US5] 変異探針を実行する: (a) 解放をレポート組み立ての**前**に移す → T075 が落ちる、(b) `contexts` を空リストにする → `tests/integration/test_full_flow.py:444` が落ちる、(c) `include_intermediate` の条件を反転する → T076 が落ちる、(d) `max_results` の `ge` を削る → T077 が落ちる、(e) `__main__.py` の再検証を削る → T077 が落ちる（exit 2 が exit 0 になる）、(f) `Semaphore` を `2` に固定する → T073 が落ちる

**Checkpoint**: US1〜US7 と US5 が独立して機能。既定の設定では
`analysis_concurrency = 2` / `compression_threshold = 20000` が現行挙動と一致する。

---

## Phase 10: User Story 8 - 実行コストと調整できる値が見える (Priority: P3)

**Goal**: LLM 呼び出しの使用量を実行 1 回単位で集計して記録し、実行時設定の各項目に
型・値域・選択肢・既定値を宣言して Studio から調整できるようにする。

**Independent Test**: 集計値が中間成果物と進捗に現れること、宣言した値域外の値が起動時に拒否される
こと（終了コード 2）、Studio の `configurable` から変更できることを確認する。

**依存**: T016（宣言）／T031（呼び出し境界）／T079（起動時拒否）。**`Configuration` に項目を足さない**（FR-069）。

### Tests for User Story 8（憲法 原則 I により必須）⚠️

- [ ] T083 [P] [US8] 使用量の集約テストを作成する: 呼び出し 1 回につき `ModelUsage` が 1 要素 / 並列実行でも `operator.add` で**全ノード分が連結**される（後勝ちにならない）/ `cache/usage.json` に `calls` / `unknown_calls` / トークン合計 / `by_node` / `by_role` が書かれる。`tests/unit/test_state.py`（T081 と同じファイルに追記）＋ `tests/unit/test_compile_report.py`（拡張）
- [ ] T084 [P] [US8] 使用量欠落のテストを作成する: `usage_metadata` が `None` でも実行が継続し、`unknown_calls` に計上され、`note()` が「不明 N 回」を併記する。`tests/unit/test_compile_report.py`（拡張）
- [ ] T085 [P] [US8] 宣言の網羅テストを作成する: `Configuration.model_fields` の**全項目**に `description` があり、数値項目に `ge` / `le`、選択肢項目に `Literal` があり、`x_oap_ui_config` が付いている（走査）。`tests/unit/test_configuration.py`（拡張）
- [ ] T086 [P] [US8] Studio 経路のテストを作成する: `{"configurable": {"analysis_concurrency": 4}}` を `from_runnable_config` に渡すと値が反映され、値域内である限り変更できる（FR-060）。`tests/unit/test_configuration.py`（T085 と同じファイルに追記）
- [ ] T087 [P] [US8] 環境変数の直接参照の走査テストを作成する: ノードと `tools/`（`tools/llm.py` の `OPENAI_API_KEY` / `OPENAI_BASE_URL` の 2 つを除く）が `os.environ` / `os.getenv` を直接読んでいない（FR-025 の単一解決経路）。`tests/unit/test_config_scan.py`（新規）

### Implementation for User Story 8

- [ ] T088 [US8] `src/trend_researcher/tools/llm.py` に使用量の記録を追加する: 呼び出し境界で `AIMessage.usage_metadata` を読み、`ModelUsage` を 1 要素返す。欠落は `None` のまま保持し「不明」として扱う（FR-061。例外にしない）。構造化出力の呼び出しも同じ経路で数える
- [ ] T089 [US8] `src/trend_researcher/nodes/compile_report.py` に `cache/usage.json` の書き出し（`cache_dir` があるときのみ。既存の `cache.py:write_json` を使う。UTF-8 / `ensure_ascii=False`）と、`note()` の 1 行（呼び出し回数・入力/出力トークン・不明の件数）を追加する。**レポートには入れない**（D-3）
- [ ] T090 [US8] 変異探針を実行する: (a) `usage` の reducer を外す → T083 が落ちる、(b) `usage_metadata` の読み取りを削る → T083 が落ちる、(c) `x_oap_ui_config` を 1 項目から削る → T085 が落ちる、(d) `_check_bounds` を削る → T077 が落ちる、(e) 1 ノードだけ `os.getenv` を直接読む → T087 が落ちる

**Checkpoint**: 8 つのストーリーすべてが独立して機能する。

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: ストーリーをまたぐ仕上げと最終ゲート。

- [ ] T091 [P] `README.md` を更新する: 追加した環境変数の一覧（`TR_ANALYSIS_CONCURRENCY` / `TR_RETRY_MAX` / `TR_RETRY_WAIT_SECONDS` / `TR_COMPRESSION_THRESHOLD` / `TR_COMPRESSION_TIMEOUT_SECONDS` / `TR_DEGRADE_MAX_ATTEMPTS` / `TR_SHRINK_RATIO` / `TR_MIN_INPUT_CHARS` / `TR_SELF_REVIEW` / `TR_INCLUDE_INTERMEDIATE` / `TR_STRUCTURED_METHOD` / `TR_EVAL_MODEL`）と値域、`cache/usage.json` の位置、評価の実走の入口（`script/evaluate.py`）と保存先（`artifacts/eval/`、追跡外）を追記する。**既存の記述を削除しない**
- [ ] T092 [P] `tests/eval/axes.md` の対応表と `prompts.py` の制約（T071 で追加した節）・`Configuration` の項目を最終突き合わせし、欠落があれば**評価項目側を先に足す**（FR-048 / FR-074）
- [ ] T093 [P] `ProgressEmitter` の走査テストを追加する: `emit()` の呼び出し箇所が 7 ノード × 開始/完了の既存の形のままで、追加の観測が `note()` のみであること（`emit(` の増加が 0、`note(` のみが増える）。`tests/unit/test_progress.py`（拡張）
- [ ] T094 変異探針の全項目（quickstart.md §5 の 20 件）を 1 つずつ実行する: 対象テストが**落ちる**ことを確認 → 復元 → **フルスイートで 601 件以上 green に戻る**ことを確認。結果（落ちたテスト名）を「実装メモ §3」に記録する
- [ ] T095 最終ゲートを通す: `uv run pytest -q`（**601 件以上 green / カバレッジ 90% 以上 / 60 秒以内**）、`uv run ruff check .`（0 件）、`uv run mypy src`（0 件）。抑制（`# noqa`・除外設定・`testpaths` の変更）を追加していないことを確認する。結果を「実装メモ §4」に記録する
- [ ] T096 [P] `quickstart.md` の S1〜S8 と §3（手動の統合シナリオ）を実行して検証する。特に「既定の入力でレポートが byte 一致」（`git stash` を使った前後比較）と `[補足]` 行が既定では出ないことを確認する
- [ ] T097 「実装メモ」節を完成させる: 基準値（T001〜T003）／実測した設計の分岐点 4 件（T004〜T008）／変異探針の結果（T094）／最終ゲート（T095）／**spec と実測のずれ**（26 vs 27 ファイル、547 vs 601 passed、`analyze_content.py:65` → `:69`、`Configuration` の 2 経路の実体）／更新または削除したテスト（FR-035 / SC-008 に基づく記録）／参照実装の欠陥を移植していないことの確認

---

## 実装メモ（実装中に記録する）

### 0. 基準値（T001〜T003）

| 項目 | 実測値 | 測定日 | 備考 |
|---|---|---|---|
| `uv run pytest -q` | 601 passed / 48.55 秒 | 2026-09-14 | 前回は 601 passed / 49.10 秒（+0.55 秒の差は許容） |
| カバレッジ | 96.65% | 2026-09-14 | `fail_under = 90` を満たす（唯一の低水位は `providers/base.py` 71%。`Protocol` の `...` 本体のみ） |
| `uv run ruff check .` | 0 件（`All checks passed!`） | 2026-09-14 | 前回も 0 件 |
| `uv run mypy src` | 0 件（`Success: no issues found in 27 source files`） | 2026-09-14 | 前回も 0 件・27 ファイル |
| `git status --short` | 空（作業ツリー clean） | 2026-09-14 | spec の期待（` M .specify/feature.json` と `?? specs/003-.../`）とは**不一致**。spec 003 一式は `c06152e` で既にコミット済みのため未追跡にはならない。ブランチ名も spec の `003-pipeline-hardening-and-evaluation` ではなく現行の `specs/003-pipeline-hardening-and-evaluation` |
| `env -u OPENAI_API_KEY -u XTR_ACCOUNTS_DB -u YTR_ACCOUNTS_DB uv run pytest -q --no-cov`（T003） | **601 passed** / 47.17 秒 | 2026-09-14 | 認証情報を落としても green のまま（原則 II の安全網が機能）。本リポジトリには `.env`（git 管理外）があるが、テストは環境変数なしでも外部 I/O に到達しない |

### 1. 設計の分岐点の実測（T004〜T008）

| # | 実測した内容 | 結果 | 決定 |
|---|---|---|---|
| 1 | 構造化出力が `json_schema` で通るか | **通る（フォールバック不要）**。`build_model("research").with_structured_output(<Pydantic モデル>, method="json_schema").invoke(...)` → 検証済みモデルが返る（実測 `Probe(topic='AI ニュース', count=3)`）。`method="function_calling"` も同じ入力で成功 | `structured_method` の既定は **`json_schema`** のまま（`Configuration` で切り替え可能にする） |
| 2 | 上限超過の応答の形（`status_code` / `body` / 語彙） | 再現方法: `build_model("research").bind(max_tokens=100_000_000).invoke("hello")`。例外型は `langchain_openai.chat_models.base.OpenAIInvalidRequestError`（MRO: `OpenAIInvalidRequestError` → `BadRequestError` → `APIStatusError` → `APIError` → `OpenAIError`）。`status_code` は **400**。`exc.body` は `dict` で `{"type": "server_error", "message": "..."}` —— **`type` は `invalid_request_error` ではなく `server_error`**。メッセージの語彙は `This endpoint's maximum context length is 1048576 tokens. However, you requested about 100000002 tokens (2 of text input, 100000000 in the output). Please reduce the length of either one, ...` | 検出器は (a) `isinstance(exc, BadRequestError)`（or `status_code == 400`）を前提に、(b) **`"maximum context length"` を主語彙**としてメッセージを照合する。`body["type"]` とクラス名の**文字列には依存しない**（FR-064）。テストは語彙に依存しない形（条件ごとの反例・同じ語彙を含む別ステータスは非該当など）で書く |
| 3 | `TR_EVAL_MODEL` の既定値 | `TR_MODEL` は未設定で、疎通したモデルは `model_name == "mimo-v2.5"`（`max_tokens=10000`）。`build_model("summary")` も同じ。判定用途のプロンプト（0-10 採点し「点数: N」の 1 行だけ返す）を投げると `点数: 10` が返り、判定用途でもそのまま使える | 既定値は特例なしで **`openai:mimo-v2.5`**（生成と同一）。判定用の別名は**不要**。`resolve_env("EVAL_MODEL", default="openai:mimo-v2.5")` として `TR_EVAL_MODEL` / `{env_prefix}_EVAL_MODEL` で上書き可能にする |
| 4 | `model_copy` 後の再検証で `model_fields_set` が保たれるか | `Configuration(platform="x").model_fields_set == {"platform"}`。`model_copy(update={"max_results": 7})` → `{"platform", "max_results"}`（**保たれ、上書きキーが加わる**）。`Configuration.model_validate(copy.model_dump())` → **7 項目全て**が `model_fields_set` に載る（**失われる**。`model_dump()` が全キーを埋めるため） | 再検証は `model_validate(model_dump())` ではなく **`_check_bounds(settings)` ヘルパ**で行う（`model_fields_set` を保持するため）。消費側は `providers/x.py:48` の `_explicit_setting`（モジュール関数）で、`XProvider` のクラス本体には無い |
| 5 | `extract_section` がタグを扱えるか | **扱えない**。`<summary>…</summary>` / `<key_excerpts>…</key_excerpts>` を含む本文に対し、`extract_section(text, "summary") == ""`、`extract_section(text, "key_excerpts") == ""`（見出し行 `^#{1,6}\s+…$` のみを探すため）、`extract_json_block == None`、`extract_list_items == []`、`_load_json_object == None` —— **4 関数すべて空振り** | 圧縮専用のタグ抽出を **`tools/compression.py` 内に置く**（`tools/parse.py` を無理に一般化しない。R-5 のとおり） |

### 2. 時間予算（T002）

- 全体の上限: 60 秒（SC-013）／ベースライン: **46.30 秒**（`--no-cov`。カバレッジ計測ありでは 48.55 秒）
- 遅いテスト上位 15 件: **すべて `tests/integration/test_cli_contract.py` のサブプロセス起動テスト**（1.57 秒 ×1 ＋ 0.83〜0.78 秒 ×14、上位 15 件の合計は約 12.6 秒）。先頭は `test_cli_002_07_output_matches_stdout_rendering`（1.57 秒）、以降は `test_cli_002_01_stdout_is_report_only` / `test_cli_001_06_help_exits_zero` / `test_cli_001_17_blank_instruction[...]` / `test_cli_002_04_stderr_has_seven_nodes_progress` / `test_cli_001_15_unknown_sort` / `test_cli_005_enums_are_case_sensitive[format-uppercase]` などが 0.78〜0.83 秒で並ぶ
- 時間の内訳: `test_cli_contract.py` が **54 件**（サブプロセス起動のため 1 件 0.5〜1.6 秒 ≒ 約 35 秒）で全体の約 3/4 を占める。残り **547 件**は in-process で合計約 11 秒
- 追加するテスト群の上限: **+13 秒以内**（60 − 46.30 = 13.7 秒）。目安は (a) 新規は原則 in-process の単体テストとして 1 件 ≒ 0.06 秒換算で**最大 200 件**、(b) CLI 統合（サブプロセス）テストの新規追加は 1 件 0.8 秒として**最大 3 件**。変異探針（quickstart.md §5 の 20 件）は都度**対象テストのみ**を走らせるため、この予算には算入しない

### 3. 変異探針の結果（T094）

| # | 変異 | 落ちたテスト | 復元確認 |
|---|---|---|---|
| 1 | `return_exceptions=True` を外す | （記入） | （記入） |
| … | （quickstart.md §5 の 20 件） | | |

**実装中に回した探針（T011 / T016、`configuration.py`。各 1 回で復元）**

| 変異 | 落ちたテスト | 復元確認 |
|---|---|---|
| `retry_max` の宣言から `x_oap_ui_config` を削る（`_setting` を素の `Field` に置換） | `test_added_fields_declare_the_studio_ui_config`（+ `test_added_fields_declare_defaults_and_ui_type`。2 failed） | sha256 一致 |
| `analysis_concurrency` の `ge=1` を削る | `test_load_raises_configuration_error_for_out_of_range_env` ほか 3 failed | sha256 一致 |
| `ConfigurationError` を `Exception` 直系にする | `test_configuration_error_is_a_value_error`（1 failed） | sha256 一致 |
| `_check_bounds` を素通し（先頭で `return settings`）にする | `test_check_bounds_rejects_a_bad_override` ほか 3 failed | sha256 一致 |

復元確認: `sha256` の前後一致（`12d9fa5e…`）+ 復元後にフルスイートを 1 回再実行し
**641 passed / 96.92%** で green に戻ることを確認済み。

**実装中に回した探針（T012 / T017、`progress.py`。各 1 回で復元）**

| 変異 | 落ちたテスト | 復元確認 |
|---|---|---|
| `note()` が `self._messages` にも積む | `test_note_does_not_grow_the_messages` / `test_note_keeps_emit_messages_unchanged`（2 failed） | sha256 一致（`bea73aba…`） |
| 書式を `[note] {text}` に変える | `test_note_does_not_change_the_emit_format` ほか 3 failed | sha256 一致 |
| 出力先を `sys.stdout` に変える | `test_note_defaults_to_stderr` ほか 3 failed | sha256 一致 |
| `note()` を `emit()` 呼び出しに置換 | 6 failed | sha256 一致 |

復元後: フルスイート **647 passed / 96.93% / 49.53 秒** で green に戻ることを確認済み。

**実装中に回した探針（T013 / T018、`tests/conftest.py`。各 1 回で復元）**

| 変異 | 落ちたテスト | 復元確認 |
|---|---|---|
| `_FakeStructuredRunnable` が既定で送出しない（`if self._llm.structured is None` → `if False`） | `test_fake_llm_structured_output_fails_by_default` / `..._awaits_and_fails_too`（2 failed） | sha256 一致（`674beefd…`） |
| `_FakeMessage.usage_metadata` の既定を `None` 以外にする | `test_fake_message_carries_no_usage_by_default`（1 failed） | sha256 一致 |
| `no_retry_sleep` から `autouse=True` を外す | `test_sleep_spy_is_installed_without_requesting_the_fixture`（1 failed） | sha256 一致 |
| 成功時に `schema.model_validate` を通さない（生の dict を返す） | `test_fake_model_factory_structured_output_succeeds_when_configured` / `..._requires_the_configured_schema`（2 failed） | sha256 一致 |
| 構造化出力のプロンプトを記録しない | `test_fake_model_factory_structured_calls_are_recorded`（1 failed） | sha256 一致 |

復元後: フルスイート **656 passed / 96.93% / 49.81 秒** で green に戻ることを確認済み。

**autouse 化で判明した実測（T018 (e) の設計を変えた根拠）**: `asyncio.sleep` を一律に
無効化するスパイは `tests/unit/test_analyze_content.py::test_parallelism_is_capped_at_two` を
落とした（`max_in_flight` が 2 → 1）。`await asyncio.sleep(0)` は待機ではなく
**制御の譲渡**で、並列上限の検証には譲渡が必要である。対策として `SleepSpy` は
`seconds <= 0` の呼び出しを実物へ委譲し、`sleeps` には正の待機だけを記録する。

**T019（プラットフォーム走査）の実測**: `uv run pytest -q --no-cov tests/unit/test_platform_scan.py`
→ **5 passed / 違反 0 件**。T016 で追加した 11 項目の宣言と `ConfigurationError` のメッセージ
（「設定が不正です: …」）は規則 (a) プラットフォーム名リテラル / (b) `platform == "…"` 比較の
どちらにも該当しない。`tools/compression.py` / `tools/degradation.py` 相当の新規モジュールは
未作成のため、T024 / US3 / US5 の各チェックポイントで同じ走査を再実行する。

**実装中に回した探針（US1 / T027。各 1 回で復元）**

対象: `src/trend_researcher/tools/compression.py`（探針前 `sha256 = 81377b03…`）

| 変異 | 落ちたテスト | 復元確認 |
|---|---|---|
| 成功経路を `compressed = text[:max_chars]` に（圧縮せず先頭だけ返す） | `test_one_call_per_source_over_the_threshold` / `test_summary_and_excerpts_are_joined` / `test_truncation_keeps_the_excerpts_that_fit` / `test_a_response_without_tags_is_used_as_the_summary` / `test_over_threshold_source_is_compressed_not_silently_truncated` / `test_compressed_source_reaches_the_analyze_prompt`（**6 failed**） | sha256 一致 |
| 成功応答の切り詰めを削る（`_to_compressed_text(response)[:max_chars]` → `[:max_chars]` なし） | `test_output_is_truncated_to_the_limit` / `test_truncation_keeps_the_excerpts_that_fit`（2 failed） | sha256 一致 |
| 発動条件を `len(text) <= max_chars` → `< max_chars`（しきい値ちょうども対象に） | `test_exactly_at_the_threshold_makes_no_call` / `test_the_threshold_comes_from_the_configuration`（2 failed） | sha256 一致 |

復元後: フルスイート **683 passed / 97.46% / 50.52 秒** で green に戻ることを確認済み。

**T024 の申し送り（T018(d) の続き）**: `FakeModelFactory.install()` の patch 対象に
`trend_researcher.tools.compression.build_model` を追加し、`tests/unit/test_fixtures.py` に
4 テスト（差し替え・プロンプト記録の分離・失敗注入・**未指定時に即座に落ちる**）を追加した。
`compression` を指定していないテストで圧縮が呼ばれた場合は `AssertionError` になるため、
「黙って skip するフィクスチャ」にはなっていない。

**実装中に回した探針（US2 / T035。各 1 回で復元）**

対象: `src/trend_researcher/tools/llm.py`（探針前 `sha256 = 726959fe…`）、
`nodes/{parse_instruction,extract_common,analyze_content}.py`

| 変異 | 落ちたテスト | 復元確認 |
|---|---|---|
| (a) 再試行の待機を削る（`await asyncio.sleep(retry_wait_seconds)` → `pass`） | `test_text_call_is_retried_up_to_one_plus_retry_max` / `test_retry_stops_at_the_first_success` / `test_transient_and_schema_errors_are_retried[validation_error\|rate_limit_error\|connection_error\|TimeoutError]` / `test_structured_schema_violation_is_retried`（7 failed / 13 passed） | sha256 一致 |
| (b) フォールバックの分岐を削る（3 ノードの `except Exception` を `except ZeroDivisionError` に） | `test_structured_failure_falls_back_and_is_reported` / `test_structured_failure_falls_back_to_the_heading_parser` / `test_structured_failure_uses_the_existing_parser` / `test_structured_output_matches_the_fallback_parse` ほか（94 failed / 71 passed） | sha256 一致（4 ファイル全一致） |
| (c) `with_structured_output` を外す（`runnable = built`） | `test_topic_comes_from_structured_block` / `test_structured_output_matches_the_fallback_parse` / `test_structured_output_is_used_as_is` / `test_structured_empty_themes_are_kept` / `test_structured_method_comes_from_the_configuration` ほか（69 failed / 40 passed） | sha256 一致（`726959fe…`） |

復元後: フルスイート **713 passed / 97.57% / 386.54 秒** で green に戻ることを確認済み
（`ruff check .` → `All checks passed!` / `mypy src` → `Success: no issues found in 28 source files`）。

**実装中に回した探針（US6 / T046。各 1 回で復元）**

対象: `tests/eval/schemas.py` / `tests/eval/evaluators.py` / `tests/eval/records.py` /
`script/evaluate.py`。探針は `/tmp/t046_probe.py`（各変異の前後で `sha256` を比較し、
復元後にフルスイートを 1 回再実行する）。

| 変異 | 落ちたテスト | 復元確認 |
|---|---|---|
| (a) 採点の受け取りスキーマに `ge=1` を付ける（`AxisScore.score`） | `test_out_of_range_scores_are_recorded_without_checks[7-1.5\|0--0.25\|-1--0.5]` と `test_the_schemas_declare_no_range_limits`（3 failed / 36 passed） | sha256 一致 |
| (b) 総合品質を平均から合計へ（`statistics.fmean` → `sum`） | `test_overall_quality_is_the_mean_of_the_sub_criteria` ほか（3 failed / 36 passed） | sha256 一致 |
| (c) `script/evaluate.py` に `subprocess` を import する | `test_the_entrypoint_does_not_use_subprocess`（1 failed / 7 passed） | sha256 一致 |
| (d) 初期状態に 4 番目のキー（`state["unexpected"]`）を足す | `test_the_initial_state_has_only_the_three_allowed_keys`（1 failed / 7 passed） | sha256 一致 |
| (e) 常に上書き（`"w" if overwrite or not path.exists() else "a"` → `"w"`） | `test_two_runs_are_kept_by_default`（1 failed / 18 passed） | sha256 一致 |
| (f) 採点する観点を 6 → 4 に減らす（`completeness` / `output_language` の行を削る） | `test_axes_cover_at_least_five_scored_axes` ほか（3 failed / 36 passed） | sha256 一致 |

復元後: フルスイート **779 passed / 97.57% / 386.65 秒** で green に戻ることを確認済み
（`script/evaluate.py` と `tests/eval/` を含む。US6 の追加は既存テストの期待値を変えずに +66 件）。

### 4. 最終ゲート（T095）

- `uv run pytest -q`: （記入）
- `uv run ruff check .`: （記入）
- `uv run mypy src`: （記入）
- 抑制の追加: なし（`# noqa` 0 件 / `testpaths` 不変 / 除外設定の追加 0 件）

### 5. spec と実測のずれ（spec は変更しない）

| spec の記述 | 実測 | 対応 |
|---|---|---|
| `src/trend_researcher/` 26 モジュール | 27 ファイル / 2,736 行（`__init__.py` の数え方） | 記録のみ |
| ベースライン 547 passed / 95.29% | 601 passed / 96.65% / 49.10 秒（spec 002 完了分） | 記録のみ |
| `nodes/analyze_content.py:65` の `source_text[:20000]` | 69 行目付近 | 実測どおりに実装 |
| `settings-contract.md` §2「`sort_by` は `relevance` / `recency` の 2 択」 | 実測は `relevance` / `likes`（`__main__.py` の検証と `providers/base.py` の `selection_note` が 2 値） | 記録のみ。既存 7 項目の宣言（`Literal` 化）は凍結契約のため T016 では触らない（US8 / T085 の範囲） |
| `settings-contract.md` §2「`max_results` は 1 以上（0 を弾く）」 | T016 時点では既存 7 項目に `ge` を足していないため 0 を通す（`tests/unit/test_configuration.py` の `test_falsy_values_are_treated_as_specified[max_results-0]` が green） | §6 の「申し送り」のとおり US8（T085）で宣言を足すときに再判定 |
| T016 の記述 `ConfigurationError(field, value, expected, message)` | 実装は `ConfigurationError(field, value, expected)` の 3 引数で `message` を**組み立てる**（属性としては `message` を持つ） | 契約 §3 の stderr 書式を属性から必ず再現するため、4 つ目を渡させない設計にした（記録のみ） |
| T013 / T018(d)「`FakeModelFactory` が `trend_researcher.tools.compression.build_model` も差し替える」 | T024 で `tools/compression.py` を作成し、patch 対象に追加した（US1 の §3 の「T024 の申し送り」参照） | 完了 |
| `spec.md` / `tasks.md` の「**取代**（生素材）」 | 「**縮退**」の意（表記ゆれ） | 実装・テスト・コメントは「縮退」に統一。spec / tasks は変更しない（記録のみ） |
| `compression_threshold` の値域（spec は明示なし） | T016 の宣言は `ge=1000` / `le=200000`（実測） | テストは 1,000 以上の値（1,000 / 1,205）で境界を作る。50 文字のような小さい値は `ConfigurationError` になり境界テストに使えない |
| 契約 §3 の再試行対象の列挙（`OutputParserException` / `ValidationError` / `APIConnectionError` / `asyncio.TimeoutError`） | 実装は `RateLimitError` / `APITimeoutError` / `TimeoutError` も再試行する | **意図的な逸脱**。spec の US2 シナリオ 3 が「一時的なエラー」の再試行を要求しており、レート制限はその代表。列挙に無いことを理由に再試行しないと US2 の受け入れ基準を満たせない。契約 §3 の列挙は「下限」として読む（コードの `RETRYABLE_ERRORS` のコメントに根拠を書いた） |
| T031「`build_model(role, env_prefix).with_structured_output(Model, method=…)`」 | 実装は境界関数に**任意の `model=` 引数**を足し、省略時のみ内部で `build_model` を呼ぶ | ノードが `trend_researcher.nodes.<node>.build_model` を patch する既存の差し替え点を残すため（フィクスチャはノード側の名前を patch する。境界側で無条件に構築するとテストのフェイクが効かない）。既定の入力では `model=None` なので挙動は同じ |
| T033「`extract_common` を構造化出力へ」 | 構造化出力のルートは**オブジェクト**でなければならないため `models.py` に `CommonThemes`（`themes: list[CommonTheme]`）を追加した | リストをルートにすると `with_structured_output` が使えない（契約 §2）。`CommonTheme` 自体は既存のまま |
| `with_structured_output` の戻り値 | `Any`（`Runnable[..., Any]`） | 上限を `cast("_ModelT", …)` で取り出す。`schema` に Pydantic モデルを渡している以上、実行時の値はそのインスタンス（`mypy` の `no-any-return` をここだけ明示的に落とす） |
| T040〜T044 が挙げる `tests/eval/` のファイル（`schemas.py` / `evaluators.py` / `judge_prompts.py` / `datasets.py` / `axes.md`） | 記録の補助として `tests/eval/records.py` を**追加**した（6 ファイル） | T037（記録のテスト）には対応する実装タスクが無い。ファイル名の組み立て・指紋・追記/上書き・JSONL の形・保存済み結果の比較は「採点」とは別の関心事なので `records.py` に分けた（`schemas.py` / `evaluators.py` に混ぜない） |
| ゲート `uv run mypy src` | `tests/eval` を単体で mypy に渡すと `Source file found twice under different module names: 'judge_prompts' and 'tests.eval.judge_prompts'` で失敗する（`tests/` が名前空間パッケージのため） | ゲートは `mypy src`（28 ファイル）のまま。`tests/eval` は実行時に pytest が担保する。mypy の設定に `tests` を足す変更はしない（既存のゲートを広げない） |
| T045 のオプション一覧（contracts §4。8 個） | `--commit` を足して 9 個（`--dataset` / `--platform` / `--config`×n / `--config-name`×n / `--judge-model` / `--out` / `--overwrite` / `--judge-only` / `--commit`） | `resolve_commit` の「引数 → `TR_EVAL_COMMIT` → `.git` の読み取り」を実現するため。契約 §4 の列挙は「最低限これを備える」として読む。既定では `subprocess` を使わず `.git` を直接読み、解決できない場合だけ `unknown` を記録する |
| T038(e)「初期状態に入れるキーが `messages` / `platform` / `max_results` のみ（AST で走査）」 | 実装は辞書リテラルで初期状態を組み立てる（`{"messages": …, "platform": …}` ＋ 明示指定時のみ `state["max_results"] = …`） | 走査を「辞書リテラルの文字列キー」と「`state[...] =` の文字列キー」の両方を拾う形にした（spec の指示は後者の想定）。意図（3 項目のみ）は不変で、4 番目のキーを足す変異で落ちることは T046(d) で確認済み |
| T039「対応表の整合テスト」 | `tests/eval/axes.md` の**本文（表）**を読む走査テストも足した（`test_the_axes_table_documents_axes_constraints_and_defects`） | FR-074 は「1 つの対応表に記録する MUST」と定めるが、表は文章なので実装側へ観点・制約を足したときに黙って古くなる。観点と制約の識別子が表に現れること、実測済み欠陥が 6 件並んでいることを固定した |
| R-21 の実測済み欠陥 6 件の「固定する方法」 | `tests/eval/axes.md` の §3 に、担当する US（US3 / US4）と固定するテストの内容を並べた。US6 の時点では #1〜#3・#6 の**実装**はまだ無い | 欠陥の一覧を 1 箇所に置くのが FR-074 / R-21 の要求で、移植しない判断は US3 / US4 の実装タスクでテストとして固定する（本フェーズでは「列挙と担当の明示」まで） |

### 6. 更新または削除したテスト（FR-035 / SC-008）

**更新（T011 / T016。すべて「フィールドの一覧」を固定する内部構造テストで、既定値の意味と
契約は不変）**

| テスト | 変更 | 理由 |
|---|---|---|
| `test_defaults_cover_every_declared_field` / `test_model_json_schema_declares_all_fields` | `DEFAULTS` を 7 → 18 項目に拡張 | T016 で宣言が 11 項目増えたため。既定値の意味は変えていない |
| `test_from_runnable_config_uses_configurable_values` | 期待 dict を `DEFAULTS \| {上書き 7 項目}` に変更 | 同上（`model_dump()` の比較が全項目を見るため） |
| `test_from_runnable_config_with_empty_config` / `test_from_runnable_config_with_none` | 変更なし（`DEFAULTS` を参照しているため自動追随） | 同上 |
| `test_load_resolves_only_the_three_settings` → `test_load_resolves_the_three_settings_and_the_added_eleven` | 改名・拡張（env 経由の追加 5 項目と「読まない 3 項目」を同時に固定） | T016 で `load()` の解決対象が 3 → 14 項目になったため。SET-005 の趣旨（宣言と env 解決の対象を一致させる）は維持 |
| `isolated_settings_env`（fixture） | `delenv` する env 名に追加 11 項目を追加 | 実 `.env` の値でテストが非決定的になるのを防ぐ |

**更新（US1 / T025。期待値ではなく「振る舞いの契約」が変わった唯一の既存テスト）**

| テスト | 変更 | 理由 |
|---|---|---|
| `test_source_text_is_truncated_at_twenty_thousand_chars` → `test_over_threshold_source_is_compressed_not_silently_truncated` | 改名・書き換え（「素材**全体**が圧縮の入力に渡る」「解析プロンプトには圧縮結果が載る」を固定する形に） | 旧テストは `source_text[:20000]` という**無言の切り捨て**を固定していたが、FR-001 の MUST NOT（先頭のみを無言で切り捨ててはならない）がこの振る舞いを禁じるため、期待値を維持できない（spec Assumptions の「観測可能な振る舞いを固定する既存テストは変更しない」の**唯一の例外**）。**削除せず置き換え**、新しい契約を固定し直した |

**新規（値域・宣言の走査）**: `test_every_declared_field_has_a_description` /
`test_added_fields_declare_defaults_and_ui_type` / `test_added_numeric_fields_declare_their_range` /
`test_added_fields_reject_out_of_range_values` / `test_structured_method_is_a_literal_choice` /
`test_added_fields_declare_the_studio_ui_config` / `test_expected_text_follows_the_declaration`（6 分岐）

**新規（`ConfigurationError`）**: `test_configuration_error_names_the_field_value_and_range` /
`test_configuration_error_is_a_value_error` / `test_load_raises_configuration_error_for_out_of_range_env` /
`test_load_rejects_a_non_numeric_env_value` / `test_load_rejects_a_non_boolean_env_value` /
`test_load_rejects_an_unknown_structured_method` / `test_check_bounds_accepts_valid_settings` /
`test_check_bounds_preserves_model_fields_set` / `test_check_bounds_rejects_a_bad_override`

**申し送り（T016 では触らない）**: `settings-contract.md` §2 は `max_results` に `ge=1` を要求するが、
T016 の指示は「追加 11 項目の宣言」であるため既存 7 項目には値域を足していない。
`test_falsy_values_are_treated_as_specified[max_results-0]` は green のまま（実測）。
既存 7 項目に宣言を足すのは US8（T085）の範囲で、そのときにこのテストの要否を再判定する。

**申し送り（T024 で必ず実施する）**: T018(d) の `trend_researcher.tools.compression` の
差し替えは、`tools/compression.py` を作る T024 で `FakeModelFactory.install()` の patch 対象に
追加し、併せて `tests/unit/test_fixtures.py` に「`compression.build_model` が差し替わっている」
テストを足す（モジュールが存在しないうちに条件分岐で黙って skip する形にしない。
静かに無効化されたフィクスチャは憲法 原則 I の「無効なテスト」と同じ欠陥クラス）。

→ **完了（T024）**。実測は §3 の「T024 の申し送り」を参照。

**更新（US2 / T028・T034。フィクスチャの記録先と補足行の分離）**

| テスト | 変更 | 理由 |
|---|---|---|
| `tests/unit/test_fixtures.py::test_fake_model_factory_structured_calls_are_recorded` | 期待を「構造化プロンプトは `structured_prompts_for()` に、テキストは `prompts_for()` に別々に記録される」に書き換え | T028〜T034 で 1 ノードが「構造化 1 回＋フォールバックでテキスト 1 回」を呼ぶようになり、`_FakeStructuredRunnable` が同じログに記録すると**凍結契約**（`tests/integration/test_frozen_contracts.py::test_default_text_call_counts_are_unchanged` / `test_full_flow.py`）の「既定の入力での LLM 呼び出し回数」が構造化の再試行で膨らむ。ログを分け、`prompts_for()` は「テキスト呼び出し」の意味に保った（元のテストの docstring もそう読める） |
| `tests/unit/test_analyze_content.py::test_progress_note_reports_how_many_were_compressed` / `test_no_note_when_nothing_was_compressed` | 断言を**圧縮の補足行に限定**（`"[補足] 長文素材 1 件を圧縮（成功 1/1" in err` / `"長文素材" not in err`）。docstring に「US2 のフォールバック補足行とは別の契約」と明記 | US2 で既定の入力（フェイクは構造化出力に失敗する）でも `note()` が 1 行出るため、「`note()` が 0 行」を固定する旧断言は維持できない。**消したのは「この既定入力では常に 0 行」という前提だけ**で、圧縮が起きないときに出ない性質は新しい断言で固定し直した |
| `tests/unit/test_llm.py` の `pytest.raises(BaseException)` | `# noqa: PT011` を削除（コメントは本文へ） | `PT011` は有効でないため `RUF100`（未使用の noqa）になる。抑制は増やさない（ゲート「`# noqa` 0 件」に合わせる） |

**更新・削除（US6）**: なし。US6 は `tests/eval/` と `script/evaluate.py` の**新規のみ**で、
既存テストの期待値・名前・`testpaths` を変えていない（`tests/unit/test_evaluation_entrypoint.py`
の `test_the_entrypoint_stays_outside_the_test_paths` が `testpaths = ["tests"]` を固定する）。

**新規（採点の契約。`tests/unit/test_evaluation.py`、39 件）**

| 関心 | テスト |
|---|---|
| 観点の数と対象外 | `test_axes_cover_at_least_five_scored_axes` / `test_correctness_is_recorded_as_out_of_scope` |
| 正規化と値域 | `test_scores_are_normalized_to_zero_one` / `test_out_of_range_scores_are_recorded_without_checks` / `test_the_schemas_declare_no_range_limits` |
| 型違い・欠落 | `test_type_mismatch_and_missing_fields_become_unscored`（7 ケース） |
| 総合品質 | `test_overall_quality_is_the_mean_of_the_sub_criteria` / `test_overall_quality_axis_records_the_sub_criteria` / `test_overall_quality_keeps_raw_scores_when_the_judge_is_extreme` |
| 記録ごとの集約 | `test_aggregating_records_averages_each_axis` / `test_aggregating_records_excludes_unscored_and_out_of_scope` |
| 失敗の隔離と再試行 | `test_one_axis_failure_does_not_stop_the_others` / `test_the_retry_rule_is_the_same_for_every_axis` |
| 非同期経路 | `test_the_async_path_uses_the_same_contract` / `test_the_sync_path_refuses_an_async_judge` |
| 提示順 | `test_axis_order_can_be_randomized_and_is_recorded` / `test_an_incomplete_order_is_rejected` |
| 判定プロンプトと制約 | `test_every_scored_axis_has_a_dedicated_prompt` / `test_the_judge_prompts_include_the_generation_constraints` / `test_every_declared_constraint_is_measured_by_an_axis` / `test_the_axes_table_documents_axes_constraints_and_defects` |
| 比較 | `test_comparison_uses_only_the_saved_scores` / `test_comparison_of_equal_scores_is_a_tie` / `test_comparison_flips_when_the_sides_are_swapped` / `test_comparison_records_the_presentation_order` / `test_comparison_refuses_two_different_datasets` / `test_comparison_refuses_a_changed_dataset_fingerprint` / `test_comparison_with_an_empty_report_is_not_comparable` / `test_comparison_without_scores_is_not_comparable` |

**新規（記録の契約。`tests/unit/test_evaluation_records.py`、19 件）**:
ファイル名の契約と `model_slug` / 既定の保存先と `TR_EVAL_OUT_DIR` と引数の優先 / 指紋の記録と
内容変更での変化 / 実行の文脈（設定の中身・識別子・コミット・プラットフォーム・生成モデル・
判定モデル・同一判定の表明・使用量）/ レコードごとの採点の `id` による結合 / 使用量が不明な
場合の記録 / JSONL 1 行 1 レコードで 3 項目のみ / `ensure_ascii=False` / 壊れたレコードの拒否 /
既定での追記と `--overwrite` / 名前での比較と比較の署名（生成を繰り返さない）/ 不在の結果・
到達不能なデータセット・壊れたデータセットの拒否。

**新規（実走の入口の契約。`tests/unit/test_evaluation_entrypoint.py`、8 件）**:
収集対象外（`testpaths` と命名） / オプション集合と繰り返し指定 / 構成も `--judge-only` も無い
実行の引数エラー / `subprocess` を使わない（AST と `vars()`） / 公開 API を in-process で呼ぶ /
初期状態が 3 項目のみ（AST） / 既存 CLI の契約を汚さない（設定クラスに判定モデルを足さない） /
判定モデルの解決順（引数 → `TR_EVAL_MODEL` → 既定）。

### 7. 参照実装の欠陥を移植していないことの確認（FR-063 / FR-064）

- [ ] 検出器がクラス名・モジュール名の**文字列**に依存していない（`isinstance` ベース）
- [ ] 上限テーブルの引き当てで未知モデルを例外にしていない（比率方式）
- [ ] 無効なオプションをモデルへ渡す経路が無い
- [ ] ツール契約の非対称が無い（件数契約を生成と点検の**両方**の後に適用）
- [ ] 常に真になる条件分岐・到達しない `except` 節が無い

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**: 依存なし。**ソースを変更しない**。設計の分岐点 4 件の実測をここで済ませる
- **Foundational（Phase 2）**: Setup の完了後。**すべてのユーザーストーリーをブロックする**
- **User Stories（Phase 3〜10）**: すべて Foundational の完了後に開始できる
  - P1: US1 → US2 → US6（推奨順）
  - P2: US3 → US4 → US7
  - P3: US5 → US8
- **Polish（Phase 11）**: すべての対象ストーリーの完了後

### ストーリー間の依存（実装上の共有ファイル）

| 依存 | 内容 | 理由 |
|---|---|---|
| US3 → US2 | `src/trend_researcher/tools/llm.py` | US2 が呼び出し境界（再試行）を作り、US3 が縮退を層として足す |
| US8 → US2 | `src/trend_researcher/tools/llm.py` | 使用量の記録は呼び出し境界に置く |
| US8 → US5 | `src/trend_researcher/nodes/compile_report.py` | US5 が `note()` と中間データの書き出しを入れ、US8 が `cache/usage.json` を足す |
| US8 → Foundational T016 | `src/trend_researcher/configuration.py` | 宣言は Foundational、拒否の挙動と検証は US5 / US8 |
| US7 → US1 | `src/trend_researcher/prompts.py` | T071（US7）が節を追加し、T023（US1）の `COMPRESSION_PROMPT` と並ぶ |
| US4 → US1 / US2 | `src/trend_researcher/nodes/analyze_content.py` | 同じノードを US1（圧縮）・US2（構造化）・US4（隔離）が触る。**この順に実装する** |
| US1 と US2 | `tests/unit/test_analyze_content.py` | 同じテストファイルを拡張する（[P] を付けない） |

**独立して検証できる（ストーリー間の依存が無い）組み合わせ**: US1 / US2 / US6 / US7 は
互いに独立して実装・検証できる。US3 と US8 は US2 の完了後、US4 は US1 と US2 の完了後が安全。

### Within Each User Story

- テストを先に書き、**赤になることを確認**してから実装する（原則 I）
- モデル → サービス（`tools/`）→ ノードの順に進める
- ストーリーが完了してから次の優先度へ進む
- 各ストーリーのチェックポイントで `uv run pytest -q` を通す

### Parallel Opportunities

- Setup（Phase 1）: T002〜T008 は [P]（実測は独立）
- Foundational（Phase 2）: T009〜T013（テスト）と T014〜T018（実装）のうち別ファイルのものが [P]
- 各ストーリーの**テストタスク**は [P]（別ファイル）
- 各ストーリーの**実装タスク**は、共有ファイル（`tools/llm.py` / `nodes/analyze_content.py` /
  `nodes/compile_report.py`）を触るものを除いて [P]

---

## Parallel Example: User Story 1

```text
# テストを先に 3 本（別ファイル）
T020  tests/unit/test_compression.py（新規）
T021  tests/unit/test_analyze_content.py（拡張）
T022  tests/integration/test_full_flow.py（拡張）

# 実装（T023 と T024 は別ファイルなので並行可。T025 は T024 に依存）
T023  src/trend_researcher/prompts.py
T024  src/trend_researcher/tools/compression.py（新規）
T025  src/trend_researcher/nodes/analyze_content.py   ← T024 の後
T026  src/trend_researcher/nodes/analyze_content.py   ← T025 の後
T027  変異探針
```

## Parallel Example: User Story 6

```text
# テストを先に 4 本（別ファイル）
T036  tests/unit/test_evaluation.py
T037  tests/unit/test_evaluation_records.py
T038  tests/unit/test_evaluation_entrypoint.py
T039  tests/unit/test_evaluation.py（追記）

# 実装（すべて別ファイルなので並行可。T045 は T040〜T044 に依存）
T040  tests/eval/schemas.py
T041  tests/eval/evaluators.py
T042  tests/eval/judge_prompts.py
T043  tests/eval/datasets.py ＋ tests/eval/fixtures/tr-basic.json
T044  tests/eval/axes.md
T045  script/evaluate.py                               ← T040〜T044 の後
T046  変異探針
```

---

## Implementation Strategy

### MVP First（User Story 1 のみ）

1. Phase 1（Setup）を完了し、設計の分岐点 4 件を実測する
2. Phase 2（Foundational）を完了する（凍結契約の回帰テスト＋共有基盤）
3. Phase 3（US1 のみ）を完了する
4. **STOP and VALIDATE**: 既定の入力で出力が byte 一致すること、しきい値超過の素材で
   後半のキーワードがプロンプトに入ることを確認する
5. ここで一度レビューに出せる（取りこぼしという最も見えにくい劣化を先に解消する）

### Incremental Delivery

1. Foundational → 基盤の準備（すべてのストーリーが使える）
2. + US1 → 検証 → デリバリ（取り込み量の管理）
3. + US2 → 検証 → デリバリ（応答の契約化）
4. + US6 → 検証 → デリバリ（**改善の判断材料**。ここから先の変更を数字で比べられる）
5. + US3 → 検証 → デリバリ（上限超過の完走）
6. + US4 → 検証 → デリバリ（部分失敗の隔離）
7. + US7 → 検証 → デリバリ（クエリの自己点検）
8. + US5 → 検証 → デリバリ（予算と状態のライフサイクル）
9. + US8 → 検証 → デリバリ（コストと調整可能な値）
10. Polish → 最終ゲート

### 注意事項

- **`tools/llm.py` は US2 → US3 → US8 の順に同じファイルへ層を足す**。並行して触らない
- **`nodes/analyze_content.py` は US1 → US2 → US4 の順に触る**。並行して触らない
- 各チェックポイントで `uv run pytest -q` を通し、601 件から落ちていないことを確認する
- 進捗の `emit()` の文言と `messages` の内容は**どのフェーズでも変更しない**
- `Configuration` の既存 7 フィールドを削除・改名しない（原則 VI の例外 = 利用者に見える契約）
- カバレッジが 90% を割りそうな場合は、抑制ではなくテストを足す（憲法 技術制約）

---

## Format Validation

- 全タスクが `- [ ] TNNN [P?] [US?] 説明（ファイルパス）` の形式に従う
- Setup（Phase 1）と Foundational（Phase 2）と Polish（Phase 11）のタスクに **[Story] ラベルを付けない**
- User Story（Phase 3〜10）のタスクに **[US1]〜[US8] のいずれか**を付ける
- すべてのタスクに**具体的なファイルパス**を含める
- タスク ID は実行順の連番（**T001〜T097**）。重複・欠番なし。US1・US2・US6 の後に US3 が続くため、
  フェーズ番号（Phase 6）とユーザーストーリー番号（US3）は一致しない（優先度順に並べているため）
