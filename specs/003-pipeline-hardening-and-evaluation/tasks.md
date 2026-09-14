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

- [X] T047 [P] [US3] 検出器のテストを作成する: 4 条件のそれぞれを満たす入力で `True` / 条件 3 を満たさない `400` で `False` / **除外条件（`invalid model` / `invalid api key` / `unsupported`）で `False`** / 上限超過以外の例外（接続エラー・認証失敗）で `False`。`tests/unit/test_degradation.py`（新規）
- [X] T048 [P] [US3] 縮小のテストを作成する: 段数が `degrade_max_attempts` を超えない / 各段で入力長が `shrink_ratio` 分だけ短くなる / 停止条件（縮小しない・`min_input_chars` 未満）で打ち切る / 未知モデルでも縮退が成立し `limit_known = False` が記録される / `Degradation` の内容。`tests/unit/test_degradation.py`（T047 と同じファイルに追記）
- [X] T049 [P] [US3] 縮退の連携テストを作成する: 上限超過は再試行**せず**縮退へ渡る / 縮小後の呼び出しで成功したら `Degradation` が 1 件記録され実行が成功する / 段数を使い切ったら例外が送出される（→ exit 1）。`tests/unit/test_llm.py`（拡張）
- [X] T050 [P] [US3] CLI のテストを作成する: 縮退を使い切ったときに stderr に理由（試した段数・縮小前後の長さ）が出て **exit 1**、上限超過以外のエラーも exit 1、上限超過で縮退が成功した場合は exit 0。`tests/integration/test_cli_contract.py`（拡張）

### Implementation for User Story 3

- [X] T051 [US3] `src/trend_researcher/tools/degradation.py` を新規作成する: `is_token_limit_exceeded(exc)`（`contracts/llm-invocation-contract.md` §5 の 4 条件。`isinstance` ベースで `body` は dict / str の両方を扱う）/ `get_model_token_limit(model)` / `shrink(text, ratio)` / `next_ladder(...)`（停止条件つき）。**参照実装の文字列依存の判定を移植しない**（FR-063 / FR-064 / research §R-1）
- [X] T052 [US3] `src/trend_researcher/tools/llm.py` に縮退を組み込む: 上限超過と判定されたら再試行せず、`degrade_max_attempts` 段まで入力を縮小して呼び直す。段ごとに `Degradation` を状態へ返し、使い切ったら理由つきの例外を送出する。無効な引数をモデルへ渡す経路を作らない（FR-063）
- [X] T053 [US3] `src/trend_researcher/__main__.py` で縮退の使い切りを扱う: 理由（試した段数・縮小前後の長さ）を stderr に出して **exit 1**。既存の例外ハンドリング（TimeoutError → exit 1 / その他 → exit 1）の分岐を壊さない
- [X] T054 [US3] 縮退を `ProgressEmitter.note()` に 1 行で出す（段数・縮小前後の長さ。FR-017 / FR-029）。`emit()` の文言は変更しない
- [X] T055 [US3] 変異探針を実行する: (a) 検出器の除外条件（条件 4）を削る → T047 の反例が落ちる、(b) `shrink_ratio` を `1.0` にする → T048 / T049 が落ちる、(c) 停止条件 2 を削る → T048 が落ちる、(d) 上限超過を再試行に回す → T049 が落ちる

**Checkpoint**: US1・US2・US6 と US3 が独立して機能。既定の入力（上限超過なし）では
縮退が発生せず、呼び出し回数も出力も不変。

---

## Phase 7: User Story 4 - 1 件の失敗でレポート全体を失わない (Priority: P2)

**Goal**: 解析 1 件の失敗を隔離し、成功分でレポートを生成する。失敗した対象は
「解析できなかった」ことが分かる形で残る。

**Independent Test**: 解析対象 10 件のうち 3 件で例外を発生させるフェイクを注入し、
7 件の結果を含むレポートが生成され、失敗件数と理由が明示されることを確認する。

### Tests for User Story 4（憲法 原則 I により必須）⚠️

- [X] T056 [P] [US4] 部分失敗の隔離テストを作成する: 10 件中 3 件が失敗して 7 件の解析が得られる / 失敗が `failures` に入り**無言で消えない** / 実行は exit 0 / 全件失敗でも完走し、失敗の事実と理由が残る。`tests/unit/test_analyze_content.py`（拡張）
- [X] T057 [P] [US4] キャンセルのテストを作成する: `asyncio.CancelledError` は部分失敗として飲み込まれず**再送出**される（原則 V「エラーを握りつぶさない」）。`tests/unit/test_analyze_content.py`（T056 と同じファイルに追記）
- [X] T058 [P] [US4] 文脈取得の失敗テストを作成する: 一部の候補で追加文脈が取れなくても取得分で解析が続き、失敗が `failures` に記録され、**既存の `notes` の文言（`スレッド取得に失敗しました（本文のみで解析）`）は変更されない**。`tests/unit/test_fetch.py`（拡張）＋ `tests/integration/test_full_flow.py`（既存シナリオの維持確認）
- [X] T059 [P] [US4] 失敗の可視化のテストを作成する: 失敗の件数と理由が `note()`（stderr）と中間データ（`include_intermediate = True` のとき `cache/failures.json`）で確認でき、**`report.notes` には既定で追加されない**。`tests/unit/test_compile_report.py`（拡張）

### Implementation for User Story 4

- [X] T060 [US4] `src/trend_researcher/nodes/analyze_content.py` の `asyncio.gather` を `return_exceptions=True` にし、`asyncio.CancelledError` だけ再送出する。成功分を `analyses`、失敗分を `failures` に分ける（FR-020）
- [X] T061 [US4] `src/trend_researcher/nodes/analyze_content.py`（または `__main__.py` の既存ハンドリングを壊さない位置）で、失敗の件数と理由を `note()` に 1 行で出す（FR-023）
- [X] T062 [US4] 全件失敗のときに `src/trend_researcher/nodes/compile_report.py` の `notes` に「解析 0 件（すべて失敗: N 件）」を追加し、exit 0 で完走させる（US4 シナリオ 3）。**この行は全件失敗のときだけ**追加する（既定の入力では増えない = FR-035）
- [X] T063 [US4] `src/trend_researcher/providers/x.py` / `youtube.py` 側の取得失敗（`fetch` 経路）を `failures`（`kind="context"`）に記録する。既存の `notes` の文言と `report.notes` の要素は**変えない**
- [X] T064 [US4] 変異探針を実行する: (a) `return_exceptions=True` を外す → T056 が落ちる、(b) `CancelledError` の再送出を削る → T057 が落ちる、(c) `failures` への記録を削る → T056 が落ちる、(d) 全件失敗の `notes` を無条件に足す → T009（凍結契約）が落ちる

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

- [X] T065 [P] [US7] 呼び出し回数と順序のテストを作成する: `self_review = True` で **2 回**（生成 1 ＋ 点検 1）、`False` で **1 回** / `prompts_for("plan_search")[0]` が**生成**プロンプト（点検は 2 番目）/ 点検が反復しない。`tests/unit/test_plan_search.py`（拡張）
- [X] T066 [P] [US7] 適用規則のテストを作成する（規則 1〜5）: 点検が 0 行 → 生成結果を採用 / 点検が少ない → **生成結果から補充**して件数を下回らない / 点検が多い → `max_search_queries` で切り詰め / 重複を除去 / 生成 0 件 → 0 件のまま / 点検が例外・タイムアウト → 生成結果で継続。`tests/unit/test_plan_search.py`（T065 と同じファイルに追記）
- [X] T067 [P] [US7] 件数契約の宣言テストを作成する: `Provider.required_query_count` が X = 5 / YouTube = 1 で宣言されている / 実装側に**明示の注釈**がある（mypy の Protocol 不変性） / `prompts.py` の生成プロンプトの件数指示と一致する（X のプロンプトは「5 件ちょうど」「5 件を厳守」を実測済み）。`tests/unit/test_providers.py`（拡張）
- [X] T068 [P] [US7] プロンプトの走査テストを作成する: `prompts.py` の 8 ＋ 1 定数が**停止条件**と**出力形式**の節を持つ / 重要制約（出力言語・件数・引用形式）が**役割の異なる 2 箇所**にある（FR-058）/ 固定テンプレートの禁止語（「そのまま使う」等）が無い / 判定不能表現の禁止（「おそらく」等で埋めない）がある。`tests/unit/test_prompts.py`（新規）

### Implementation for User Story 7

- [X] T069 [P] [US7] `src/trend_researcher/providers/base.py` の `Provider` Protocol に `required_query_count: int | None` を宣言し、`src/trend_researcher/providers/x.py` に `required_query_count: int | None = 5`、`src/trend_researcher/providers/youtube.py` に `= 1` を実装する（**明示の注釈**を付ける。mypy の Protocol 可変属性は不変）。コアに `platform == "..."` を書かない（原則 IV）
- [X] T070 [US7] `src/trend_researcher/nodes/plan_search.py` に自己点検を追加する: `Configuration.self_review` が真のとき、生成の**後**に 1 回だけ点検を呼ぶ（生成と同じ行解析経路 = `_clean_query`。構造化出力は使わない）。規則 1〜5 を適用し、上限（`max_search_queries`）は従来どおり適用する。反復・リトライをしない（FR-050）。失敗時は生成結果で継続し `note()` に 1 行出す（FR-051）
- [X] T071 [P] [US7] `src/trend_researcher/prompts.py` の 8 定数に**停止条件**と**出力形式**の節を追加し、重要制約（出力言語・件数・引用形式）を役割の異なる 2 箇所（役割説明の直後と出力形式の節）へ明示する（FR-055 / FR-056 / FR-057 / FR-058）。固定テンプレートの指示を書かない
- [X] T072 [US7] 変異探針を実行する: (a) 点検の呼び出しを削る → T065 が落ちる、(b) 補充を削る（点検の結果をそのまま採用）→ T066 が落ちる、(c) `self_review` の既定を `False` にする → T065 が落ちる、(d) 点検を生成の**前**に呼ぶ → T065 のプロンプト順序が落ちる、(e) 二重明示の 1 箇所を削る → T068 が落ちる。復元後にフルスイートを再実行し、**既定の入力で検索クエリが不変**であること（T009）を確認する

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

- [X] T073 [P] [US5] 設定の注入テストを作成する: `analysis_concurrency` を 1 / 2 にして同時実行数がそれぞれ 1 / 2 になる / `retry_max` が試行回数に反映される / `compression_threshold` が圧縮の発動を変える / `degrade_max_attempts` が段数に反映される（**すべて実行時設定から注入**され、コードに固定値が無い）。`tests/unit/test_analyze_content.py`（拡張）＋ `tests/unit/test_llm.py`（拡張）
- [X] T074 [P] [US5] 優先順位のテストを作成する: 環境変数と実行時指定が食い違うときに既定の優先順位（明示指定 > env > 既定値）に確定し、`model_fields_set` の意味が変わらない（`providers/x.py:48` が読む）。`tests/unit/test_configuration.py`（拡張）
- [X] T075 [P] [US5] 状態の解放テストを作成する: レポート確定後に `contexts[].text` / `thread_text` / `replies` と `candidates[].text` が空になる / **`contexts` のレコードは残る**（`tests/integration/test_full_flow.py:444` を壊さない）/ `report.candidates` の内容が保持される（解放がレポート組み立ての**後**）/ `analyses` / `common_themes` / `report` は解放されない。`tests/unit/test_compile_report.py`（拡張）
- [X] T076 [P] [US5] 中間データの切り替えテストを作成する: `include_intermediate = False`（既定）で `cache/` に新しいファイルが増えず `cache/report.json` の既存キーが**変更前と一致** / `True` で `compressed.json` / `degradations.json` / `failures.json` が増える / `cache_dir` 未指定なら何も書かない。`tests/unit/test_compile_report.py`（T075 と同じファイルに追記）
- [X] T077 [P] [US5] 起動時拒否のテストを作成する: 値域外の CLI 引数（`--max-results 0`）で stderr に「設定が不正です: max_results=0（期待: ...）」が出て **exit 2** / 丸めも既定値への置換もされない / **LLM が 1 回も呼ばれない**（ノード実行前） / env 経由の値域外も同じ。`tests/integration/test_cli_contract.py`（拡張）

### Implementation for User Story 5

- [X] T078 [US5] 5 ノード（`parse_instruction` / `plan_search` / `analyze_content` / `extract_common` / `compile_report`）の設定参照を `Configuration.from_runnable_config(config)` 経由の値に統一する: `analysis_concurrency` を `asyncio.Semaphore(...)` に、`retry_max` / `retry_wait_seconds` を呼び出し境界に、`compression_threshold` / `compression_timeout_seconds` を圧縮に、`degrade_max_attempts` / `shrink_ratio` / `min_input_chars` を縮退に渡す。**コードに固定値を残さない**（FR-005 / FR-024 / FR-025）
- [X] T079 [US5] `src/trend_researcher/__main__.py` に起動時検証を追加する: 上書き適用後に T016 の再検証を呼び、`ConfigurationError` を捕捉して stderr に `message` を出し **exit 2**（`_parse_args` の失敗と同じ扱い）。検証は LLM・検索・ファイル読み書きの**前**に行う（FR-024 / SC-023）
- [X] T080 [US5] `src/trend_researcher/nodes/compile_report.py` に次を追加する: (a) `include_intermediate = True` なら `cache/compressed.json` / `degradations.json` / `failures.json` を書く（解放の**前**）、(b) レポート確定後に `contexts` / `candidates` の**中身を解放**する（順序: report 組み立て → 中間データ → 解放。T075 が固定）、(c) `note()` に内訳（圧縮・縮退・失敗の件数）を出す
- [X] T081 [US5] `extract_common` / `compile_report` が**生データを参照しない**ことを走査テストで固定する: `state.get("contexts")` / `candidates[..].text` を新しい用途で読み始めていないこと（既存の件数参照のみ許可）。`tests/unit/test_state.py`（新規）
- [X] T082 [US5] 変異探針を実行する: (a) 解放をレポート組み立ての**前**に移す → T075 が落ちる、(b) `contexts` を空リストにする → `tests/integration/test_full_flow.py:444` が落ちる、(c) `include_intermediate` の条件を反転する → T076 が落ちる、(d) `max_results` の `ge` を削る → T077 が落ちる、(e) `__main__.py` の再検証を削る → T077 が落ちる（exit 2 が exit 0 になる）、(f) `Semaphore` を `2` に固定する → T073 が落ちる

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

- [X] T083 [P] [US8] 使用量の集約テストを作成する: 呼び出し 1 回につき `ModelUsage` が 1 要素 / 並列実行でも `operator.add` で**全ノード分が連結**される（後勝ちにならない）/ `cache/usage.json` に `calls` / `unknown_calls` / トークン合計 / `by_node` / `by_role` が書かれる。`tests/unit/test_state.py`（T081 と同じファイルに追記）＋ `tests/unit/test_compile_report.py`（拡張）
- [X] T084 [P] [US8] 使用量欠落のテストを作成する: `usage_metadata` が `None` でも実行が継続し、`unknown_calls` に計上され、`note()` が「不明 N 回」を併記する。`tests/unit/test_compile_report.py`（拡張）
- [X] T085 [P] [US8] 宣言の網羅テストを作成する: `Configuration.model_fields` の**全項目**に `description` があり、数値項目に `ge` / `le`、選択肢項目に `Literal` があり、`x_oap_ui_config` が付いている（走査）。`tests/unit/test_configuration.py`（拡張）
- [X] T086 [P] [US8] Studio 経路のテストを作成する: `{"configurable": {"analysis_concurrency": 4}}` を `from_runnable_config` に渡すと値が反映され、値域内である限り変更できる（FR-060）。`tests/unit/test_configuration.py`（T085 と同じファイルに追記）
- [X] T087 [P] [US8] 環境変数の直接参照の走査テストを作成する: ノードと `tools/`（`tools/llm.py` の `OPENAI_API_KEY` / `OPENAI_BASE_URL` の 2 つを除く）が `os.environ` / `os.getenv` を直接読んでいない（FR-025 の単一解決経路）。`tests/unit/test_config_scan.py`（新規）

### Implementation for User Story 8

- [X] T088 [US8] `src/trend_researcher/tools/llm.py` に使用量の記録を追加する: 呼び出し境界で `AIMessage.usage_metadata` を読み、`ModelUsage` を 1 要素返す。欠落は `None` のまま保持し「不明」として扱う（FR-061。例外にしない）。構造化出力の呼び出しも同じ経路で数える
- [X] T089 [US8] `src/trend_researcher/nodes/compile_report.py` に `cache/usage.json` の書き出し（`cache_dir` があるときのみ。既存の `cache.py:write_json` を使う。UTF-8 / `ensure_ascii=False`）と、`note()` の 1 行（呼び出し回数・入力/出力トークン・不明の件数）を追加する。**レポートには入れない**（D-3）
- [X] T090 [US8] 変異探針を実行する: (a) `usage` の reducer を外す → T083 が落ちる、(b) `usage_metadata` の読み取りを削る → T083 が落ちる、(c) `x_oap_ui_config` を 1 項目から削る → T085 が落ちる、(d) `_check_bounds` を削る → T077 が落ちる、(e) 1 ノードだけ `os.getenv` を直接読む → T087 が落ちる

**Checkpoint**: 8 つのストーリーすべてが独立して機能する。

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: ストーリーをまたぐ仕上げと最終ゲート。

- [X] T091 [P] `README.md` を更新する: 追加した環境変数の一覧（`TR_ANALYSIS_CONCURRENCY` / `TR_RETRY_MAX` / `TR_RETRY_WAIT_SECONDS` / `TR_COMPRESSION_THRESHOLD` / `TR_COMPRESSION_TIMEOUT_SECONDS` / `TR_DEGRADE_MAX_ATTEMPTS` / `TR_SHRINK_RATIO` / `TR_MIN_INPUT_CHARS` / `TR_SELF_REVIEW` / `TR_INCLUDE_INTERMEDIATE` / `TR_STRUCTURED_METHOD` / `TR_EVAL_MODEL`）と値域、`cache/usage.json` の位置、評価の実走の入口（`script/evaluate.py`）と保存先（`artifacts/eval/`、追跡外）を追記する。**既存の記述を削除しない**
- [X] T092 [P] `tests/eval/axes.md` の対応表と `prompts.py` の制約（T071 で追加した節）・`Configuration` の項目を最終突き合わせし、欠落があれば**評価項目側を先に足す**（FR-048 / FR-074）
- [X] T093 [P] `ProgressEmitter` の走査テストを追加する: `emit()` の呼び出し箇所が 7 ノード × 開始/完了の既存の形のままで、追加の観測が `note()` のみであること（`emit(` の増加が 0、`note(` のみが増える）。`tests/unit/test_progress.py`（拡張）
- [X] T094 変異探針の全項目（quickstart.md §5 の 20 件）を 1 つずつ実行する: 対象テストが**落ちる**ことを確認 → 復元 → **フルスイートで 601 件以上 green に戻る**ことを確認。結果（落ちたテスト名）を「実装メモ §3」に記録する
- [X] T095 最終ゲートを通す: `uv run pytest -q`（**601 件以上 green / カバレッジ 90% 以上 / 60 秒以内**）、`uv run ruff check .`（0 件）、`uv run mypy src`（0 件）。抑制（`# noqa`・除外設定・`testpaths` の変更）を追加していないことを確認する。結果を「実装メモ §4」に記録する
- [X] T096 [P] `quickstart.md` の S1〜S8 と §3（手動の統合シナリオ）を実行して検証する。特に「既定の入力でレポートが byte 一致」（`git stash` を使った前後比較）と `[補足]` 行が既定では出ないことを確認する
- [X] T097 「実装メモ」節を完成させる: 基準値（T001〜T003）／実測した設計の分岐点 4 件（T004〜T008）／変異探針の結果（T094）／最終ゲート（T095）／**spec と実測のずれ**（26 vs 27 ファイル、547 vs 601 passed、`analyze_content.py:65` → `:69`、`Configuration` の 2 経路の実体）／更新または削除したテスト（FR-035 / SC-008 に基づく記録）／参照実装の欠陥を移植していないことの確認

---

## 実装メモ（実装中に記録する）

**T097 の索引（この節は実装中に追記され、最後にここへ集約した）**。節は
「実測の順序」に並んでいる。読む順は次のとおり。

| 節 | 内容 | 対応するタスク |
|---|---|---|
| §0 | 基準値（変更前の緑とゲートの水位。**ソースを変更しない**） | T001〜T003 |
| §1 | 設計の分岐点の実測 5 件（**着手前**に確定した前提） | T004〜T008 |
| §2 | 時間予算（SC-013 の見積もりと、T097 の追記＝見積もりが外れた点） | T002 |
| §3 | 変異探針の結果（US ごとの表 ＋ T094 の 20 件対応表） | US1〜US8 / T094 |
| §4 | 最終ゲート（T095 の実測。**この結果でコミットする**） | T095 |
| §5 | **spec と実測のずれ**（spec は編集しない。ここに記録だけ残す） | 全フェーズ |
| §6 | 更新または削除したテスト（FR-035 / SC-008 の下で何をなぜ変えたか） | 全フェーズ |
| §7 | 参照実装の欠陥を移植していないことの確認（FR-063 / FR-064） | T001〜T090 |

**全体の結論**: 10 フェーズ（T001〜T090）＋仕上げ（T091〜T097）を完了。
ゲートは `pytest` 1,026 passed / カバレッジ 97.42% / `ruff` 0 件 / `mypy` 29 ファイル 0 件。
**テストは 1 件も削除していない**（601 → 1,026）。SC-013 の 60 秒だけは未達で、
その理由と代替として満たしている性質を §5 の SC-013 行に記録した（60 秒に収めるには
凍結契約の固定方法を変える必要があり、FR-035 / SC-008 に反するため実施しない）。
変異探針は全 20 件＋US 別の探針が**すべて検出**（落ちなかった変異 0 件）。

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

**T097 の追記（予算の実績）**: この見積もりは **2 つの点で外れた**。(1) テスト件数は
601 → **1,026 件**（+425 件。in-process の単体テストが中心なので合計は 1.5 秒程度）。
(2) CLI 統合テストの新規追加は 3 件ではなく **多数**で、しかも US2〜US5 のあいだに
1 件あたりのコストが 0.8 秒 → **1.3 秒**へ上がった（CLI の import グラフに `openai` が
入ったため。§5 の SC-013 行）。T095 で**実時間の待機**（再試行の待機）を除去して
**438.11 秒 → 105.19 秒**まで戻したが、テスト**件数**が 1.7 倍になった分は件数を
減らさない限り戻らない
（§5 の SC-013 行のとおり、サブプロセス起動テストは凍結契約を固定しているため
減らせない）。予算の見積もりを「1 件 0.8 秒」で置いたことが外れの主因で、
**計測しないと分からないコスト（import）を見積もりに含めていなかった**。

### 3. 変異探針の結果（T094）

| # | 変異 | 落ちたテスト | 復元確認 |
|---|---|---|---|
| 1 | `return_exceptions=True` を外す | `test_one_failed_candidate_does_not_stop_the_others` / `test_every_candidate_ends_up_in_analyses_or_failures`（2 failed / 61 deselected） | sha256 一致（US4 / T064 (a)） |
| … | （quickstart.md §5 の 20 件） | | |

**US7（T072。`/tmp/probe_t072.sh` を `setsid` で起動し、結果は `/tmp/probe_t072.log` から読む。
各探針は「変異 → 対象テスト 1 ファイル → 復元 → sha256 照合」の順で実行）**

| # | 変異 | 落ちたテスト | 復元確認 |
|---|---|---|---|
| 2 | (a) `if configurable.self_review:` を `if False:` にする（点検の呼び出しを削る） | `test_self_review_calls_the_model_twice` / `test_the_first_prompt_stays_the_generation_prompt` / `test_the_review_does_not_repeat` / `test_the_generation_prompt_is_not_the_review_prompt` / `test_rule_3_more_review_lines_are_capped_for_x` / `test_rule_3_has_no_cap_for_youtube` / `test_a_review_failure_is_reported_once_in_the_note`（7 failed / 44 passed） | `plan_search.py` MATCH |
| 3 | (b) `_apply_review` の補充ループ（規則 2）を削る | `test_rule_2_fewer_review_lines_are_filled_from_the_generated_queries` / `test_rule_2_never_drops_below_the_generated_count` / `test_rule_4_duplicates_are_removed_keeping_the_first`（3 failed / 48 passed） | `plan_search.py` MATCH |
| 4 | (c) `Configuration.self_review` の既定を `True` → `False` にする | (a) と同じ 7 件（7 failed / 44 passed） | `configuration.py` MATCH |
| 5 | (d) 点検のプロンプトを生成の**前**に呼ぶ | 15 failed / 36 passed（生成の呼び出し回数・`[0]` の内容・`date_hint` が崩れる。`test_date_hint_is_added_when_published_after_is_set` も含む） | `plan_search.py` MATCH |
| 6 | (e) `X_PLAN_SEARCH_PROMPT` の二重明示の 1 箇所（件数）を削る | `test_important_constraints_are_stated_twice[X_PLAN_SEARCH_PROMPT-件数]`（1 failed / 77 passed） | `prompts.py` MATCH |
| 7 | (f) 縮退の `truncated = text[:max_chars]` を `text` にする（§6 で更新した長さ比較の非空虚性の確認） | `test_compression_failure_keeps_the_analysis_running`（1 failed / 62 passed） | `compression.py` MATCH |

**探針後の状態**: `sha256sum -c` で 4 ファイルとも OK、`git status --porcelain` は意図した
8 ファイル（+ 新規 `tests/unit/test_prompts.py`）のみ。復元後にフルスイートを再実行し
**958 passed / 97.40% / 397.19 秒 / exit 0** で green に戻ることを確認済み
（US7 の追加は既存テストの期待値を 1 件だけ更新し、他の期待値は変えずに +24 件）。

**補足（探針の作り方で踏んだこと）**: (d) は「点検を前に動かす」だけでは成立せず、
`providers/*.py` の `review_search_prompt` を**呼び出し順だけ**入れ替える必要がある
（点検の入力を空にして、生成の入力と取り違えないようにする）。(e) は `prompts.py` の
該当行が 1 箇所だけであることを `assert s.count(old) == 1` で確かめてから置換する。

**US5（T082。`/tmp/probe_t082.py`。各探針は「変異 → 対象テスト → 復元 → sha256 照合」を
1 プロセスで回す。探針は必ず**有効な Python のまま**戻す）**

| # | 変異 | 落ちたテスト | 復元確認 |
|---|---|---|---|
| 8 | (a) 解放（`_release_raw_material`）を `ResearchReport` の組み立て**前**へ移す | `test_raw_text_is_released_after_the_report_is_built` / `test_the_release_is_not_visible_in_the_written_report`（2 failed / 32 passed）。レポートの候補が空になる | `compile_report.py` sha256 一致（`dcab8a14…`） |
| 9 | (b) 返す `contexts` を空リストにする（`updates["contexts"] = []`） | `test_thread_fetch_failure_degrades_to_text_only`（1 failed / 23 deselected）。`test_full_flow.py` の `result["contexts"][0]` が `IndexError`／空になる | 同上 |
| 10 | (c) `if configurable.include_intermediate:` を反転する | `test_failures_json_is_written_only_when_intermediate_is_enabled` / `test_intermediate_data_is_written_when_enabled` / `test_the_default_writes_no_new_files_and_keeps_the_report_keys`（3 failed / 31 passed） | 同上 |
| 11 | (d) `max_results` の宣言から `ge=1` を削る | `test_out_of_range_max_results_is_rejected_before_any_node_runs` / `…_from_the_environment_is_rejected_too[0]` / `…[101]` / `…_does_not_call_the_llm`（4 failed / 2 passed / 56 deselected / 32.06 秒）。**exit 0 で完走**してしまう | `configuration.py` sha256 一致（`d4a723b4…`） |
| 12 | (e) `__main__.py` の `settings = _check_bounds(settings)` を `pass` にする | `test_out_of_range_max_results_is_rejected_before_any_node_runs` / `…_does_not_call_the_llm`（2 failed / 4 passed / 56 deselected / 23.63 秒）。exit 2 ではなく **exit 1**（`ValidationError` が実行中の例外ハンドラに落ちる）＋ `[1/7] parse_instruction` が走る | `__main__.py` sha256 一致（`56f12079…`） |
| 13 | (f) `asyncio.Semaphore(concurrency)` を `Semaphore(2)` に、開始行の `detail` を `"並列上限 2"` に固定する | `test_the_concurrency_limit_comes_from_the_configuration[1]` / `test_the_start_line_reports_the_configured_concurrency`（2 failed / 69 passed） | `analyze_content.py` sha256 一致（`201addee…`） |

**探針で確かめた「落ち方の精度」**: (d) と (e) はどちらも「起動時拒否」を壊すが、
**落ち方が違う**（(d) は検証そのものが無くなって exit 0、(e) は検証のタイミングが
実行時へずれて exit 1 ＋ ノード走行）。(e) の失敗メッセージが `assert 1 == 2` である
ことは、`_check_bounds` の呼び出しが「exit 2 で拒否する」ことの**直接の証拠**になる。
(b) は spec が名指しした `test_full_flow.py` の assertion が落ちることを確認した。

**US8（T090。`/tmp/probe_t090.py`。`setsid` で起動し、結果は `/tmp/probe_t090.log` から読む。
各探針は「変異 → 対象テスト → 復元 → sha256 照合」を 1 プロセスで回す。変異は
`assert s.count(old) == 1` で 1 箇所であることを確かめてから適用する）**

| # | 変異 | 落ちたテスト | 復元確認 |
|---|---|---|---|
| 14 | (a) `usage` の reducer を外す（`Annotated[list[ModelUsage], operator.add]` → `list[ModelUsage]`） | `test_usage_from_parallel_nodes_is_concatenated` / `test_usage_elements_are_kept_when_two_sequential_nodes_write_them` / `test_usage_is_aggregated_across_every_llm_node` / `test_the_usage_note_reports_the_aggregate_for_the_whole_run`（4 failed / 28 deselected）。**観測値が 9 回 → 1 回**になり、`plan_search` の 2 回が後勝ちで消える | `state.py` sha256 一致（`efdebdc4…`） |
| 15 | (b) `usage_metadata` の読み取りを削る（`usage = getattr(result, "usage_metadata", None)` → `None`） | `test_a_text_call_records_one_usage_element` / `test_partial_usage_metadata_does_not_invent_the_missing_counts` / `test_the_sync_wrapper_records_the_same_way`（3 failed / 34 passed）。`assert [None] == [120]` | `tools/llm.py` sha256 一致（`e6a92657…`）。探針の後に `UsageMeter` の docstring の参照節番号（§3 → §7）だけを直したため、現在のハッシュは `028b1a52…`（コメントのみの変更で、対象テスト 37 件は再実行して green） |
| 16 | (c) `compression_threshold` の宣言を `_setting(...)` から `Field(default=20000, ge=1000)` に置き換える（`x_oap_ui_config` が 1 項目から消える） | `test_every_declared_field_has_a_description` / `test_added_fields_declare_defaults_and_ui_type` / `test_added_fields_declare_the_studio_ui_config` / `test_every_field_declares_its_ui_config_except_the_frozen_legacy_ones`（4 failed / 51 passed）。`assert ['compression_threshold'] == []` | `configuration.py` sha256 一致（`d4a723b4…`） |
| 17 | (d) `_check_bounds` の本体を素通しにする（`for` の前に `return settings` を挿入） | `test_out_of_range_max_results_is_rejected_before_any_node_runs` / `…_from_the_environment_is_rejected_too[0]` / `…[101]` / `…_does_not_call_the_llm`（4 failed / 2 passed / 58 deselected / 23.65 秒）。exit 2 ではなく **exit 1**（`ValidationError` が実行中の例外ハンドラに落ちる） | `configuration.py` sha256 一致（`d4a723b4…`） |
| 18 | (e) `plan_search` だけ `os.getenv` を直接読む（`import os` を足し、`build_model("research", …)` の第 1 引数を `os.getenv("TR_MODEL_PREFIX") or "research"` にする） | `test_nodes_and_tools_do_not_read_the_environment_directly`（1 failed / 1 passed）。`nodes/plan_search.py:137` を `Hit` として報告 | `plan_search.py` sha256 一致（`d21598f1…`） |

**探針の総括**: 5 件すべてで `rc != 0`（＝対象テストが落ちる）を確認し、
`sha256(after)` は 5 ファイルすべて一致（探針で検出できなかった変異 **0 件**）。
(a) は「reducer を外すと並列・逐次の書き込みが**後勝ちで消える**」という
`operator.add` の役割そのものを観測値の差（9 → 1）として示せた。

**T094: `quickstart.md` §5 の 20 件の全件対応**

20 件はすべて実測済みである。各探針の「落ちたテスト」と `sha256` 照合の記録は
§3 の該当行（下の表の「記録」列）にある。**追加で測ったのは #7 の 1 件だけ**で、
残り 19 件は各ストーリーの探針（US1〜US8）で同じ変異を回している。

| quickstart §5 # | 変異 | 記録 | 落ちたテスト（件数） |
|---|---|---|---|
| 1 | `return_exceptions=True` を外す | §3 の行 #1（US4 / T064 (a)） | 2 failed |
| 2 | `shrink_ratio` を `1.0` にする | US3 / T055 (b) | 16 failed |
| 3 | 検出器の除外条件（条件 4）を削る | US3 / T055 (a) | 5 failed |
| 4 | 再試行の待機を削る | US2 / T035 (a) | 7 failed |
| 5 | 圧縮の分岐を `pass` にする | US1 / T027 | 6 failed |
| 6 | 圧縮後の切り詰めを削る | US1 / T027 | 2 failed |
| 7 | `contexts` の解放を外す | **T094 で実行（`/tmp/probe_t094.py`。下の表）** | 3 failed |
| 8 | 解放をレポート組み立ての**前**に移す | §3 の行 #8（US5 / T082 (a)） | 2 failed |
| 9 | `include_intermediate` の条件を反転する | §3 の行 #10（US5 / T082 (c)） | 3 failed |
| 10 | `usage` の reducer を外す | §3 の行 #14（US8 / T090 (a)） | 4 failed |
| 11 | `max_results` の `ge` を削る | §3 の行 #11（US5 / T082 (d)） | 4 failed |
| 12 | `__main__.py` の再検証を削る | §3 の行 #12（US5 / T082 (e)） | 2 failed |
| 13 | 点検の呼び出しを削る | §3 の行 #2（US7 / T072 (a)） | 7 failed |
| 14 | 点検の補充を削る | §3 の行 #3（US7 / T072 (b)） | 3 failed |
| 15 | 点検を生成の**前**に呼ぶ | §3 の行 #5（US7 / T072 (d)） | 15 failed |
| 16 | 採点に `ge=1` を付ける | US6 / T046 (a) | 3 failed |
| 17 | 総合品質を `mean` から `sum` に変える | US6 / T046 (b) | 3 failed |
| 18 | `script/evaluate.py` に `subprocess` を import する | US6 / T046 (c) | 1 failed |
| 19 | `script/evaluate.py` の初期状態に 4 番目のキーを足す | US6 / T046 (d) | 1 failed |
| 20 | 判定プロンプトの二重明示の 1 箇所を削る | §3 の行 #6（US7 / T072 (e)） | 1 failed |

**T094 で追加実行した探針（#7。`/tmp/probe_t094.py`）**

対象: `src/trend_researcher/nodes/compile_report.py`（探針前後 `sha256 = dea7c099…`）

| # | 変異 | 落ちたテスト | 復元確認 |
|---|---|---|---|
| 7 | 末尾の `_release_raw_material(contexts, candidates)` を `pass` にする（解放そのものを外す） | `test_raw_text_is_released_after_the_report_is_built` / `test_the_release_keeps_the_other_state_values` / `test_the_release_is_not_visible_in_the_written_report`（3 failed / 40 passed / 0.17 秒） | `compile_report.py` sha256 一致（`dea7c099…`） |

**#7 を US5 の探針 (a) と分けて測る理由**: (a) は「解放を組み立ての**前**に移す」
（呼び出しは残る）で、**解放の順序**を測る。落ちるテストは同じ 2 件だが、#7 は
「解放しない」ため `test_the_release_keeps_the_other_state_values` も落ちる
（解放が**起きたこと**と**起きる位置**は別の性質であり、後者は (a) が、前者は #7 が
固定する）。

**20 件を回した結果の総括**: 落ちなかった変異 **0 件**、`sha256` 不一致 **0 件**。
「対象の挙動を壊すとテストが落ちる」という憲法 原則 I の条件は 20 件すべてで満たした。

**US5 で踏んだ落とし穴（実装メモ §5 にも記録）**: 「state の値をその場で書き換えて解放する」
版は、呼び出し元と共有している `Candidate` / `Context` まで空にする。統合テストの
固定プール（`_X_POOL`）がまさにこれで、`tests/integration/test_full_flow.py` が
**8 件失敗**（`analyze_content` が 0 件を要約）した。state から受け取った直後に写しを
取る形に直して 24 passed に戻り、その後の探針 (a) も期待どおり落ちる（写しを取っても
「解放 → レポート」の順序を逆にすれば候補が空になることは変わらないため）。

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

**実装中に回した探針（US3 / T055。各 1 回で復元）**

対象: `src/trend_researcher/tools/degradation.py` / `src/trend_researcher/tools/llm.py`。
探針は `/tmp/probe_t055.py`（各変異の前後で `sha256` を比較し、復元まで含めて自動化）。

| 変異 | 落ちたテスト | 復元確認 |
|---|---|---|
| (a) 検出器の条件 4（除外語彙）を削る | `test_the_exclusion_words_win_over_the_metric`（5 パラメータ全部。5 failed / 44 passed） | sha256 一致 |
| (b) 縮小率を `1.0` にする（`target = int(len(text) * 1.0)`） | `test_the_stage_count_follows_the_configuration` ほか T048 / `test_a_limit_error_is_degraded_instead_of_retried` ほか T049（16 failed / 61 passed） | sha256 一致 |
| (c) 停止条件 (b)（縮小しない段で打ち切る）を削る | `test_the_ladder_stops_when_the_input_cannot_shrink`（1 failed / 48 passed） | sha256 一致 |
| (d) 上限超過を再試行に回す（`APIStatusError` を `RETRYABLE_ERRORS` に足す） | `test_a_limit_error_is_degraded_instead_of_retried` / `test_the_shrunk_input_keeps_the_head_of_the_original` / `test_exhausting_the_ladder_raises_the_reason` / `test_a_limit_error_without_degrade_options_is_propagated` / `test_context_length_error_is_not_retried`（5 failed / 23 passed） | sha256 一致 |

**探針で確かめた「落ち方の精度」**: (a) は除外の反例テスト**だけ**が落ち（44 passed）、
(c) は停止条件のテスト**だけ**が落ちた（48 passed）。条件を 1 つ削ったときに、その条件を
見ているテストだけが落ちることを確認してから探針の証拠とした（無関係なテストが巻き添えで
落ちる探針は「何を検出したのか」を言えない）。

**実装中に回した探針（US4 / T064。各 1 回で復元）**

対象: `src/trend_researcher/nodes/analyze_content.py`（`sha256 = 0402f850…`）/ 
`src/trend_researcher/nodes/compile_report.py`（`sha256 = 1d6b7a64…`）。
探針は `/tmp/probe_t064.sh`（各変異の前後で `sha256` を比較し、`git status` も記録する）。

| 変異 | 落ちたテスト | 復元確認 |
|---|---|---|
| (a) `gather(..., return_exceptions=True)` の `return_exceptions=True` を外す | `test_one_failed_candidate_does_not_stop_the_others` / `test_every_candidate_ends_up_in_analyses_or_failures`（2 failed / 61 deselected）。スタックトレースが「失敗した候補の例外がそのまま `analyze_content` 全体を落とす」ことを示す | sha256 一致 |
| (b) `isinstance(outcome, asyncio.CancelledError): raise outcome` の 2 行を削る | `test_cancellation_is_not_swallowed_as_a_partial_failure`（1 failed / 62 deselected） | sha256 一致 |
| (c) `failures.append(_analysis_failure(...))` の 1 行を削る | `test_one_failed_candidate_does_not_stop_the_others` / `test_every_candidate_ends_up_in_analyses_or_failures` / `test_the_failure_record_carries_the_id_and_the_reason`（3 failed / 60 deselected） | sha256 一致 |
| (d) 全件失敗の注記の条件 `elif not analyses and failures:` を `elif True:` にする（無条件に足す） | `test_default_stdout_matches_the_golden` / `test_default_run_does_not_add_notes`（2 failed / 4 passed）。既定の入力（失敗なし）でも注記が増えるため凍結契約が落ちる | sha256 一致 |

復元後: フルスイートで green に戻ることを確認済み（§4 の最終ゲート表を参照）。
**探針 (d) の意味**: この探針は「全件失敗のときだけ」という条件が**既定の出力を守るために
効いている**ことを示す。条件を外すと T059（`test_partial_failure_does_not_add_a_report_note`）
ではなく T009（凍結契約）が落ちるのは、部分失敗の入力では `report.notes` の比較が
golden を相手にしていないため。既定の入力（失敗 0 件）でも注記が増えるので golden が落ちる。

### 4. 最終ゲート（T095）

**US5 のチェックポイント（Phase 9 完了時点。T095 で最終確認する）**

- `uv run pytest -q`: **988 passed / カバレッジ 97.34% / 419.04 秒 / exit 0**（`fail_under = 90` を満たす）
- `uv run ruff check .`: **All checks passed!**（0 件）
- `uv run mypy src`: **Success: no issues found in 29 source files**（0 件）
- 抑制の追加: なし（`# noqa` は `compile_report.py` / `plan_search.py` の既存 `# noqa: BLE001` のみ / `testpaths` 不変 / 除外設定の追加 0 件）
- 統合テストの内訳: `tests/integration` 全体で **107 passed**（US5 で追加した起動時拒否 6 件を含む）

**T095 の実測（最終。この結果でコミットする）**

| ゲート | 事前（基準値・T001〜T003） | 最終（T095） | 判定 |
|---|---|---|---|
| `uv run pytest -q` | 601 passed / 48.55 秒 / カバレッジ 96.65% / exit 0 | **1,026 passed / 105.19 秒（`/usr/bin/time` の TOTAL は 110.81 秒）/ カバレッジ 97.42% / exit 0** | ✓ 合格（`fail_under = 90` を大きく上回る。**テストの削除 0 件**で件数は 601 → 1,026 = +425 件） |
| `uv run ruff check .` | 0 件（`All checks passed!`） | **0 件（`All checks passed!`）** | ✓ 合格（違反の新規追加なし・抑制の追加なし） |
| `uv run mypy src` | 0 件（27 ファイル） | **0 件（29 ファイル。T020〜 で `tools/compression.py`、T047〜 で `tools/degradation.py` を追加して 27 → 29）** | ✓ 合格 |
| `git status --short` | 空 | Phase 11 の 6 ファイルのみ（`README.md` / `tasks.md` / `tests/eval/axes.md` / `tests/eval/judge_prompts.py` / `tests/integration/conftest.py` / `tests/unit/test_progress.py`。**`src/` の変更 0 件**） | ✓ 合格 |
| 抑制の追加 | — | **なし**。`pyproject.toml` は `3a6fe15` から 1 文字も変わっていない（`testpaths = ["tests"]` / `addopts` / `fail_under = 90` / `exclude_lines` すべて不変）。未コミットの差分に `noqa` の追加は 0 行（既存の 11 箇所はすべて `BLE001` に FR の引用つきで、US1〜US8 で正当化済み） | ✓ 合格 |

**SC-013（60 秒）**: **未達**（105.19 秒）。ただし **T095 の作業で 438.11 秒 → 105.19 秒**へ
**約 4.2 倍**短縮した。内訳と根拠は §5 の SC-013 行を参照。

**T095 で測った統合テストのコスト**: サブプロセスの CLI 起動 1 件は、`TR_RETRY_WAIT_SECONDS=0`
の下で **約 1.3 秒**（構造化出力のダブルが 3 回の再試行を誘発し、既定ではそこに実時間の
待機 1.0 秒 × 2 が乗っていた。`tests/conftest.py` の `SleepSpy` は親プロセスのテストにしか
効かないため、ハーネスの実行では待機が実時間で発生していた）。待機の除去で 1 シナリオ
10.06 秒 → 1.32 秒。テストの件数（1,026 件）と 1 件あたりのコスト（in-process ≒ 0.02 秒 /
サブプロセス ≒ 1.3 秒）から、60 秒に収めるには**サブプロセス起動テストを 40 件前後削る**か
**CLI 起動を 1 プロセスに集約する**（凍結契約の固定方法を変える）必要があり、いずれも
FR-035 / SC-008 の「既存テストを削除しない」に反するため**実施しない**（§5 の SC-013 行）。

**T096（統合シナリオの再現）**: 決定論的なハーネス（層 B）で S1〜S8 を実行し、
**exit 0 / stdout は凍結 golden と 58 行 1 文字一致（差は `print` の末尾空行 1 つだけ）/
進捗は 14 行完全一致**を確認。golden は 003 のどのコミットでも書き換えていない
（`git log -- tests/*/golden/`）。詳細は §5 の「`git stash` 方式」の行。


**US8 のチェックポイント（Phase 10 完了時点。T095 で最終確認する）**

- `uv run pytest -q`: **1021 passed / カバレッジ 97.42% / 438.11 秒 / exit 0**（`fail_under = 90` を満たす）
- `uv run ruff check .`: **All checks passed!**（0 件）
- `uv run mypy src`: **Success: no issues found in 29 source files**（0 件）
- 抑制の追加: なし（`# noqa` は `compile_report.py` / `plan_search.py` の既存 `# noqa: BLE001` のみ / `testpaths` 不変 / 除外設定の追加 0 件。新規テストは 1 件も `# noqa` を使っていない）
- 統合テストの内訳: `tests/integration` 全体で **111 passed / 435.17 秒**（US8 で追加した 4 件を含む）。単体は **910 passed / 1.46 秒**
- **SC-013 の 60 秒は未達**（438.11 秒）。原因と対処は §5 に記録（T095 で扱う）


### 5. spec と実測のずれ（spec は変更しない）

| spec の記述 | 実測 | 対応 |
|---|---|---|
| `src/trend_researcher/` 26 モジュール | 27 ファイル / 2,736 行（`__init__.py` の数え方） | 記録のみ。**T095 の最終値は 29 ファイル**（003 で `tools/compression.py` と `tools/degradation.py` を追加） |
| ベースライン 547 passed / 95.29% | 601 passed / 96.65% / 49.10 秒（spec 002 完了分） | 記録のみ。**T095 の最終値は 1,026 passed / 97.42% / 105.19 秒** |
| `nodes/analyze_content.py:65` の `source_text[:20000]` | 69 行目付近 | 実測どおりに実装 |
| T004〜T008 を「**設計の分岐点 4 件**」と数える記述（Checkpoint / タスク本文 / Phase 1 の説明 / §7 の申し送り） | 実測した分岐点は **5 件**（§1 の表も 5 行。構造化出力が通るか / 上限超過の応答の形 / `TR_EVAL_MODEL` の既定値 / `model_copy` 後の再検証 / `extract_section` がタグを扱えるか） | **記録のみ**。T008 の本文は `extract_section` の実測を求めており、T004〜T007 の 4 件と合わせて 5 件になる（「4 件」は表を書く前の見積もり）。表は 5 行のままにする（実測した内容を削らない） |
| `settings-contract.md` §2「`sort_by` は `relevance` / `recency` の 2 択」 | 実測は `relevance` / `likes`（`__main__.py` の検証と `providers/base.py` の `selection_note` が 2 値） | 記録のみ。既存 7 項目の宣言（`Literal` 化）は凍結契約のため T016 では触らない（US8 / T085 の範囲） |
| `settings-contract.md` §2「`max_results` は 1 以上（0 を弾く）」＋ §6 の申し送り「US8（T085）で宣言を足すときに再判定」 | **T078（US5）で宣言を足した**（`_setting(5, ge=1, le=100, ui_type="number", …)`）。既存テスト `test_falsy_values_are_treated_as_specified[max_results-0]` は `from_runnable_config` 経由で `Configuration(max_results=0)` を通すため、宣言を足すと Pydantic の `ValidationError` になり green を保てない | **利用者の判断で前倒し**（US5 の T077 が「`max_results=0` を exit 2 で弾く」を要求し、T085 を待つと同じ制約を 2 回判定することになるため）。偽値の扱い（`0` を `None` と区別する）を測るケースは `retry_max`（`ge=0`）へ移し、**テストが測る性質は変えていない**（テストに根拠コメントを記載）。値域外の拒否は `ConfigurationError`（`model_copy(update=…)` は検証しないため）と `ValidationError`（直接構築）の 2 経路をテストで固定 |
| `data-model.md` §4.3 の手順 7「contexts / candidates の**中身を解放**」 | 実装は state から受け取った直後に `Candidate` / `Context` の**写しを取り**、その写しをその場で空にする（`_release_raw_material` の docstring に「引数は呼び出し側が所有していること」を明記） | **実測に基づく判断**。渡されたオブジェクトをその場で書き換える版では、検索境界が同じオブジェクトを保持している場合（統合テストの固定プール `_X_POOL` がまさにこれ）に取得元まで空になり、以降のテストで `analyze_content` が 0 件になる（実測: `tests/integration/test_full_flow.py` が 8 件失敗 → 写しを取る形で 24 passed）。レポートは解放の**前**に別の写しを取るため「レポート確定 → 解放」の順序（R-8）は保たれ、T082(a) の探針も落ちる |
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
| 契約 §1 の表「テキスト形態（`plan_search` の生成・点検、圧縮）にも縮退あり」 | T052 で縮退を配線したのは `parse_instruction` / `analyze_content` / `extract_common` の 3 ノード（`degrade=options_for(...)`）。`plan_search` / `compile_report` はまだ渡していない | T052 の指示が「`tools/llm.py` に縮退を組み込む」で、ノード単位の配線は T078（US5）が 5 ノード分をまとめて担う。既定の入力では上限超過が起きないため**観測できる差は無い**（T050 の exit 0 ケースで実測）。T078 で残り 2 ノードに入れる |
| 上記（US5 / T078 による決着） | `plan_search` の生成と点検を `tools/llm.py` の境界（`_invoke` → `invoke_text`）へ載せ、`degrade=options_for(configurable, NODE_PLAN_SEARCH)` を渡した。`compile_report` は LLM を呼ばない（描画とファイル書き出しのみ）ため配線対象が無い | これで縮退を持つのは 4 ノード。`plan_search` の点検は `except Exception`（`# noqa: BLE001`）で `DegradationError` も捕捉し、生成結果で継続して `note()` に 1 行出す（US7 の規則「点検が失敗したら生成結果で継続」と同じ経路）。`tools/llm.py` を通すノードのフェイクは `ainvoke` を実装する必要がある（`_SequencedLLM` に追加。境界は `asyncio.run(ainvoke_text(...))` を使う） |
| 契約 §2 が列挙する Provider の追加属性は `required_query_count` のみ | 点検プロンプトも provider に置いた（`review_search_prompt` を Protocol ＋ X / YouTube に追加し、`prompts.py` に `X_REVIEW_SEARCH_PROMPT` / `YOUTUBE_REVIEW_SEARCH_PROMPT` を追加） | **意図的な追加**。コアは `platform == "..."` を書けない（原則 IV）ため、点検の文面（プラットフォームごとの件数・名詞の言い回し）は provider のフックにしか置けない。既存の 5 フック（`parse_instruction_prompt` 等）と同じ形なので、拡張点の増加ではなく同型の追加。`test_provider_exposes_the_full_interface` に `review_search_prompt` の型検査を足した（§6） |
| 契約 §3 の節の一覧は「8 ＋ `COMPRESSION_PROMPT`」の 9 定数を対象とする | `test_prompts.py` は走査対象を `*_PROMPT` の命名で動的に集めるため、追加した 2 定数（点検）も**自動で対象になる**（計 11 定数） | 走査対象を定数名で固定すると追加時に静かに漏れる。命名で集めて「9 以上ある」ことを別テストで固定する形にした（`test_the_scan_covers_every_prompt_constant`）。点検プロンプトも FR-055〜058 の節を持つ必要があるため、対象に入るのが正しい |
| T068「固定テンプレートの禁止語（『そのまま使う』等）」 | 禁止語は「テンプレートをそのまま」に固定した | 既存プロンプトには「〜の**まま**引用」「その**まま**貼れる」という**正しい**用法が多数あり、「そのまま使う」を含めると誤検出する。禁止したいのは「テンプレートをそのまま使う」という指示なので、語をそこに絞った（`test_no_prompt_orders_a_fixed_template`） |
| `plan_search` の点検の入力（契約 §1 の「点検が行うこと」） | 点検プロンプトには `{topic}` と生成済みクエリ（改行連結）を渡す。**指示本文（`raw_text`）は渡さない** | 生成側の `search_topic`（括弧内の除去 ＋ 期間表現の除去）と同じ値を使う。指示本文を渡すと点検がトピックを再解釈でき、規則「生成結果に無いクエリを創作しない」を促す文面と矛盾する（点検が補うのは**語の組み合わせ**まで） |
| 契約 §1 の表「点検が行うこと (c) 上限（`max_search_queries`）の適用」 | 上限は点検の**後**に `_apply_review` の中で 1 回だけ適用する（生成直後の上限適用と合わせて 2 箇所になるが、適用は同じ値） | 規則 2（補充）は「生成結果の件数を下回らない」を満たすため、生成結果に上限を掛けた**後**の件数を基準にする必要がある。点検前に上限を掛けておくことで `len(generated)` が上限内に収まり、規則 3 の切り詰めと重複しない（`test_rule_3_more_review_lines_are_capped_for_x` が両方を固定） |
| 契約 §6 の「変異探針」表の 1 行「生成プロンプトの件数を 3 に変える → `required_query_count` との一致テストが落ちる」 | T072 の探針には含めず、T067 の `test_the_generation_prompt_states_the_declared_count` が**同じ関係**（プロンプトの件数指示 ↔ `required_query_count`）を固定している | 探針 (e) が `prompts.py` を変異させる枠を持ち、T094 の 20 件で網羅する。件数指示を 3 に変える変異は `test_the_generation_prompt_states_the_declared_count` が落ちることを構造上保証している（`"5 件ちょうど"` と `"5"` を直接照合） |
| 契約 §2 の用途「(b) 規則 2（補充）の**上限**」 | 実装はコアで `required_query_count` を**読まない**。補充の目標は規則 2 の文言どおり `len(generated)`（生成結果の件数）にする | 規則 2 は「生成結果から補充し、**生成結果の件数を下回らない**」と定めており、生成結果が規定件数より多い場合（例: X で 8 件）に `required_query_count = 5` を上限にすると「下回らない」を満たせず、規則 1（差分なし）とも衝突する。**D-1 が「規定件数まで増やさない」を明示**しているため、値の役割は (a)（プロンプトの件数指示との一致をテストで確認する）に絞られる。既定の入力では生成が 5 件＝規定件数なので、`len(generated)` と `required_query_count` は一致する（`test_required_query_count_is_declared` と凍結テストの件数（3 / 2 / 8 / 12 / 0）が両立する） |
| T047「条件 3 を満たさない `400` で `False`」のうち `body` が**文字列**の場合 | 条件 3 は `body` の `code` / `type` を読むため、文字列の `body` は構造として満たせず `False` になる | 契約 §5 の条件 3 は「応答本文**または**メッセージに指標がある」だが、指標は `code == "context_length_exceeded"` か `type == "invalid_request_error"` を要求する。文字列から `getattr` で拾う実装は誤認を生む（FR-018）ため `False` を固定した（テストの docstring に根拠を明記） |
| 契約 §6「既知モデルの初回は上限に収まる文字数」 | 実装は `(上限トークン − 10,000) × 1 文字`（`_CHARS_PER_TOKEN = 1` / `_OUTPUT_RESERVE_TOKENS = 10,000`） | 係数を安全側（1 トークン = 1 文字）に置く。日本語はトークンあたりの文字数が少なく、多めに見積もると上限を超えたまま呼ぶ。契約の文言は「収まる文字数」とのみ定めるため逸脱ではない |
| 契約 §6「段数 最大 `degrade_max_attempts`（既定 3）」の数え方 | 実装は `max_attempts` 段（呼び出し回数は初回 ＋ 段数 = 最大 4 回）。`max_attempts=2` なら 2 段（3 回） | 契約の読みと同じ（「段」は縮小して呼び直した回数）。T049 の `test_exhausting_the_ladder_raises_the_reason` が `stages == 2` / `calls == 3` を固定している |
| 検出器の `_EXCLUDED_WORDS` の判定順 | 除外語彙（条件 4）を条件 3 より**先**に見る（`unsupported` を含む `400` は指標があっても `False`） | 契約 §5 は「すべての条件を満たしたときだけ `True`」と定めるので順序は結果に影響しないが、早期に除外して無駄な照合をしない形にした。T055(a) で条件 4 を削ると反試テストが落ちることを実測 |
| `data-model.md` §3.3「`error_type` ＝ 例外の型名（`RuntimeError` 等）」 | 文脈取得の失敗（US4 / T063）は `error_type="MissingContext"`（**例外型名ではない**） | **意図的な逸脱**。`providers/x.py` は取得の例外をその場で握り（`except Exception` で `notes` に文言を積む）、`tools/x_search.py` の `_fetch_context_*` も `_CONTEXT_FETCH_ERRORS` を握って**空の `Context`** を返す。失敗がノードへ届く時点で例外は存在しないため、`error_type` に入れられる例外型名は無い。「`RuntimeError` 等」という例示は解析の失敗には合うが文脈取得には合わない。捏造した型名を入れるより、失敗の種類（`MissingContext`）を示す方が `data-model` の目的（後から理由を辿れる）に適う。判定は「対応する `Context` が無い、または `text` / `thread_text` / `replies` がすべて空」の 1 規則で、platform に依存しない（`tests/unit/test_fetch.py` の X / YouTube 両方のテストが固定） |
| T063「`providers/x.py` / `youtube.py` 側の取得失敗を `failures` に記録する」 | 判定は `nodes/fetch.py` の `_context_failures()` に置き、provider の戻り値は `(contexts, notes)` のまま（**2 要素**） | `Provider.fetch_contexts` の戻り値は既存テストが多重に固定している（`test_x_search.py:749/763/779` / `test_youtube_search.py:288/304` / `test_providers.py:68/186` / `test_platform_extension.py:94`）。3 要素に変えるとプラットフォーム実装と拡張の契約を同時に壊す（FR-035 / SC-008）。失敗の判定は provider が「取れなかった」ことを表す既存の表現（**空の `Context`**）から導けるので、コアは理由を解釈せずに済む（原則 IV）。T063 の「`fetch` 経路」は provider の内側を指すとは限らず、`fetch` ノードも含むと読む |
| T058「`tests/integration/test_full_flow.py`（既存シナリオの維持確認）」 | ファイルを変更していない（既存 102 件が green のまま） | 「維持確認」は既存シナリオが壊れていないことの確認で、変更を要求していない。既定の入力では `failures` が空になり `contexts` は非空のため、`_context_failures` は 1 件も返さない（`test_no_context_failure_when_every_context_has_content` が固定） |
| T088「呼び出し境界で `AIMessage.usage_metadata` を読み、`ModelUsage` を 1 要素返す」（契約 §7 の表も「粒度: 呼び出し 1 回につき `ModelUsage` 1 要素」） | 実装は**境界の呼び出し 1 回につき 1 要素**（試行ごとではない）。`_with_retry` が再試行した回数のうち、記録されるのは**成功した 1 回だけ** | **実測に基づく解釈**。usage を読む先は成功して返ってきた `AIMessage` であり、**失敗した試行にはその応答が存在しない**（例外で終わる）。「試行ごとの記録」を素直に読むと例外からトークン数を取り出す実装になるが、取れる値が無いので捏造になる。契約の文言（呼び出し 1 回につき 1 要素）と一致する形にした。`test_failed_attempts_do_not_add_usage_elements` が「再試行 1 回（待機 1 回）でも記録は 1 要素」を固定する |
| T088「構造化出力の呼び出しも同じ経路で数える」（契約 §7 の「集計元」は `AIMessage.usage_metadata`） | **構造化出力の呼び出しは数えるが、トークン数は常に `None`（不明）になる**。`with_structured_output(..., include_raw=False)` の戻り値はスキーマのインスタンス（Pydantic モデル）で、`usage_metadata` を持たない | **実測に基づく制約**（FR-061 の「使用量が応答に含まれない場合は不明として記録し、実行を失敗させない」の範囲内）。`include_raw=True` に変えると今度は戻り値の形（`{"raw": …, "parsed": …, "parsing_error": …}`）が変わり、既存の呼び出し側（3 ノード）の期待値を壊す（FR-035）。**呼び出し回数の集計（`by_node` / `by_role` / `calls`）は構造化出力でも正しい**ため、情報としての欠落はトークン数のみに留まる。実測: 既定の 5 件実行で `calls=9`（うち `analyze_content` のフォールバックが `ainvoke_text` へ落ちる分は usage を読める）・`unknown_calls=9`。テスト用のフェイクは `usage_metadata=None` を返すため、統合テストでは常に不明側の経路を通る |
| `quickstart.md:137`「stderr … ＋ 追加の `[補足] ...` 行（圧縮・縮退・失敗・**使用量があったときのみ**）」 | 使用量の `[補足]` 行は **`calls == 0` のときだけ出さない**（`_usage_note`）。呼び出しが 1 回でもあれば、トークン数が不明でも「LLM 呼び出し合計 N 回（入力 0 / 出力 0 トークン、不明 N 回）」の 1 行が出る | **FR-062 が優先する解釈**。FR-062 は「集計結果は中間成果物と進捗に記録する MUST」と定め、契約 §7 も「記録先: `cache/usage.json`（`cache_dir` があるときのみ）＋ `note()` の 1 行」とする。「使用量があったときのみ」は**呼び出しが 1 回も無いときに出さない**（内訳の補足と同じ規則）と読むのが自然で、実装もその形にした。結果として、プロキシが usage を返さない既定の環境では**常に 1 行出る**（`不明 N 回` が情報として意味を持つ）。T096 の手動確認ではこの行を「既定で出る `[補足]`」として扱う（進捗行 `[n/7]` の行数・文言は不変で、`messages` にも積まないため FR-035 の凍結対象ではない） |
| T083 の対象（`tests/unit/test_state.py` に追記） | このファイルの usage テスト **2 件は最初から green**（`usage` の reducer は T015 で導入済み）。赤にならなかったのは `tests/unit/test_llm.py`（`ImportError: cannot import name 'UsageMeter'`）と `tests/unit/test_compile_report.py`（8 件。`usage.json` が無い・`[補足]` 行が無い） | **回帰ガード**として残す（reducer の存在を前提にした並列・逐次の連結を固定する。探針 (a) が落とすことで T090 の対象になる）。T083 の「赤を確認する」は上記 2 ファイルで満たした |
| **SC-013「テストスイートは… 60 秒以内に完走する」** | **未達**。US8 完了時点で **438.11 秒**（`tests/unit` は 1.46 秒、`tests/integration` が 435.17 秒）。T002 の基準値では 48.55 秒だったため、US2〜US5 のあいだに約 9 倍になった | **原因を実測で特定**（T095 で扱う）。(1) **支配要因は再試行の実待機**: 統合テストの CLI はサブプロセスなので `asyncio.sleep` の差し替え（`no_retry_sleep`）が効かず、ハーネスの構造化出力ダブルが常に `OutputParserException` を送出するため `retry_wait_seconds`（既定 1.0 秒）× 2 回 × 構造化呼び出し 5 回 ≒ 8.7 秒/件を実時間で消費している。実測: 同じハーネス起動が `TR_RETRY_WAIT_SECONDS=0` で **10.06 秒 → 1.32 秒**。(2) 残る下限は CLI の import コスト（`python -X importtime` で 1.19 秒。`openai` が 507 ms、`langgraph.graph` が 496 ms）。US2 でノードが `tools/llm.py` を通るようになり `openai` が CLI の import グラフに入ったため、ベースラインの 0.78 秒/件から 1.3 秒/件へ上がった。サブプロセス起動を使うテストは **55 個のテスト関数**（`cli_runner` / `cli_module_runner` を引数に取るもの。パラメータ化を含めると起動回数はもっと多い）で、いずれも凍結契約を固定しているため減らせない。したがって**この構造のまま 60 秒には入らない**（下限 ≒ 55 × 1.3 秒 ≒ 72 秒）。**spec は変更しない**（§5 は記録のみ）ため、T095 では「実測値・内訳・60 秒に入らない理由」を残し、60 秒の代わりに測れる性質（決定的・ネットワーク非依存・実待機 0）を記録する。**T095 の実測（最終）**: `TR_RETRY_WAIT_SECONDS=0` を統合テストの env に足した結果、**438.11 秒 → 105.19 秒**（約 4.2 倍の短縮。`/usr/bin/time` の TOTAL は 110.81 秒）。**60 秒は依然として未達**で、残る下限は「サブプロセス起動を使うテスト関数 55 個 × 約 1.3 秒 ≒ 72 秒」。実待機は 0 になったので、残りは `openai` / `langgraph` の import（1.19 秒/起動）そのもので、件数を減らすか起動を 1 プロセスに集約する（= 凍結契約の固定方法を変える）以外に短縮手段が無く、FR-035 / SC-008 に反するため**実施しない**。60 秒の代わりに満たしている性質を末尾に記録: **決定的**（乱数・時刻・ネットワークに依存しない。`TR_CLI_SCENARIO` のダブルが固定）/ **ネットワーク非依存**（`env -i` で認証情報を落としても green）/ **実待機 0**（`TR_RETRY_WAIT_SECONDS=0`。再試行の回数と値は `tests/unit/test_llm.py` の `SleepSpy` が固定）/ **1,026 件 green・カバレッジ 97.42%** |
| T092「`quickstart.md` §5 の 20 件の探針」 | 20 件はすべて実測済み（§3 の「T094: `quickstart.md` §5 の 20 件の全件対応」）。ただし **#7「`contexts` の解放を外す」だけは記録が無かった**ため T094 で追加実行した（3 failed） | US5 の探針 (a) は「解放を**どこで**行うか」で、#7 は「解放するかどうか」を測る。20 件は #1〜#18 の番号付き表と US1〜US8 の各表に分かれていたため、T094 で 1 枚の対応表にまとめた（番号 → 記録 → 落ちたテスト）。探針の実行漏れを「表で見える」状態にするのが目的 |
| `quickstart.md` §3（手で確かめる統合シナリオ）の `git stash` 方式 | `git stash` 版は**実 API（`accounts.db` のクッキー ＋ ネットワーク）で CLI を 2 回走らせる**手順で、FR-044（実 API の手動確認は合格条件ではない）に照らして再現できない | **決定論的なハーネス（層 B）で同じ性質を実測**した。`TR_CLI_SCENARIO=x_success` で既定の入力（`"AI動画のトレンドを3件"`）を走らせ、stdout を凍結 golden（`tests/integration/golden/default_stdout.txt`。T009 が**変更前のツリー**から採取し、以後 1 byte も変わっていない）と比較 → **58 行が 1 文字も一致**（差は `print` が付ける末尾の空行 1 つだけで、これは T009 の `_significant_lines` が契約から意図的に除外。pre-003 の `__main__.py` でもレポート出力の経路は未変更）。進捗行も `default_progress.txt` と **14 行完全一致**。exit 0。`tests/integration/golden/` と `tests/unit/golden/` はどちらも 003 の各コミットで 1 度も書き換えていない（`git log -- tests/*/golden/` が T009 / T006 の 1 件のみ） |
| T096「`[補足]` 行が既定では出ないことを確認する」 | **成り立たない**。既定の入力の実行で `[補足]` は **4 行**出る（構造化出力のフォールバック 3 行 ＋ 使用量の集計 1 行）。実測: `[補足] LLM 呼び出し合計 7 回（入力 0 / 出力 0 トークン、不明 7 回）` | 前の行（`quickstart.md:137` の解釈）のとおり、使用量の行は `calls > 0` で必ず出る（FR-062）。フォールバックの 3 行は US2 で既に出ていた（T028 の申し送り参照）。**凍結契約は stdio の役割分担**（stdout = レポートのみ）**と `messages` の内容**であり、stderr の補足行は対象外（`test_default_stdout_matches_the_golden` / `test_default_progress_lines_match_the_golden` / `test_default_run_does_not_add_notes` は green）。T096 では「`[補足]` が出ることを**許す**契約」を実測で確認した |
| `quickstart.md` S3 の反例コマンド `-k not_token_limit` / S4 の `-k partial` | S3 は **0 件選択**（該当する名前のテストが無い）。S4 は **1 件だけ**（部分失敗の主テストは名前に `partial` を含まない） | **コマンドの選び方のずれ**（実装の欠陥ではない）。実名で選び直すと S3 は `-k exclusion` で **5 passed**（`test_the_exclusion_words_win_over_the_metric` の 5 パラメータ）、S4 は `-k fail` で **9 passed**。他の S1〜S8 のコマンドは意図どおり選択された（S1 16 件 / S1(b) 1 件 / S2 111 件 / S3 49 件 / S5 49 件 / S6 66 件 / S7 11 件 / S8(a) 5 件 / S8(b) 7 件） |
| T098「キー名も `records.USAGE_KEYS` の `prompt_tokens` / `completion_tokens` と集計の `input_tokens` / `output_tokens` で不一致」 | パイプラインの記録（`ModelUsage`）は `input_tokens` / `output_tokens` / `total_tokens`、保存済みの結果は `prompt_tokens` / `completion_tokens` / `total_tokens`（`records.USAGE_KEYS`） | **結果側の項目名は変えない**（保存済みの結果の形式を保つ）。`script/evaluate.py` の `USAGE_SOURCES` を対応の唯一の出所にし、`test_the_result_usage_keys_follow_the_pipeline_records` が「結果の項目 ⊆ 対応表」「対応表の元の項目 ⊆ `ModelUsage` の項目」の両方向を固定する。`calls` は並びの要素数そのもので元の項目を持たない（`None`） |
| T098「畳む場所（`_add_usage` か `records`）を一意にし」 | 畳む場所は **`script/evaluate.py` の `_add_usage` の 1 か所**。`records.usage_summary` は**結果の解釈だけ**を担い、`list[ModelUsage]` は受け取らない | 対応表 `USAGE_SOURCES` を `records.USAGE_KEYS` と同じ項目名で定義し、`test_the_result_usage_keys_follow_the_pipeline_records` が両方向（結果の項目 ⊆ 対応表／対応表の元の項目 ⊆ `ModelUsage` の項目）を固定するため、2 つのモジュールに分かれても同期は機械的に守られる。実測: 修正前は `_add_usage` が `Mapping` 前提の早期 return で常に `{}` → `status: 不明`（変異探針で 5 failed） |

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

**更新（T101。docstring のみ。アサーションは不変）**

| テスト | 変更 | 理由 |
|---|---|---|
| `test_a_known_model_returns_its_token_limit` | docstring を「前方一致ではなく部分一致で引く」→「登録済みの鍵は**自分の値**を返す」に修正 | T101 で引き方が「最長の前方一致」になったため、旧 docstring は実装と食い違う（期待値 `openai:gpt-4o` / `openai:gpt-4.1-mini` は両方の規則で同じ値になり、アサーションは変更していない） |

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

**更新（US7 / T071。プロンプトの文面量に依存していた断言）**

| テスト | 変更 | 理由 |
|---|---|---|
| `tests/unit/test_analyze_content.py::test_compression_failure_keeps_the_analysis_running` | 末尾の断言を `len(prompt) < len(_OVER_THRESHOLD_SOURCE)` から `prompt.count("埋め草") < _OVER_THRESHOLD_SOURCE.count("埋め草")` に変更（コメントに「長さはプロンプト全体ではなく**素材の部分**で見る」と明記） | 旧断言は「プロンプト全体（テンプレート ＋ 縮退した素材）が素材全体より短い」を意味しており、**テンプレートの文面量が増えると成立しなくなる**（T071 が FR-055〜058 の節を足して 20,007 文字の素材に対して 21,067 文字になり落ちた）。固定したい性質は「縮退が素材を先頭からしきい値で切ったこと」＝ **素材全体が載らないこと**なので、素材の部分（`"埋め草"` の出現数。しきい値 20,000 で 6,666 回 < 全体の 7,000 回）で見る形にした。切り詰めを外す変異で落ちることは §3 の探針 (f) で実測済み（**弱めていない**） |

**新規（US7 / T065・T066。`tests/unit/test_plan_search.py`）**: `test_self_review_calls_the_model_twice` /
`test_self_review_can_be_turned_off` / `test_the_first_prompt_stays_the_generation_prompt` /
`test_the_review_does_not_repeat` / `test_the_generation_prompt_is_not_the_review_prompt` /
`test_rule_1_no_review_lines_keeps_the_generated_queries` /
`test_rule_2_fewer_review_lines_are_filled_from_the_generated_queries` /
`test_rule_2_never_drops_below_the_generated_count` / `test_rule_3_more_review_lines_are_capped_for_x` /
`test_rule_3_has_no_cap_for_youtube` / `test_rule_4_duplicates_are_removed_keeping_the_first` /
`test_rule_5_no_generated_queries_stays_empty` / `test_a_review_failure_keeps_the_generated_queries` /
`test_a_review_failure_is_reported_once_in_the_note` / `test_no_review_note_when_the_review_succeeds` /
`test_the_review_result_is_not_used_when_self_review_is_off` /
`test_the_note_does_not_grow_the_progress_messages`（17 件。生成と点検で応答を分けるため
`_SequencedLLM` と `_run_sequenced` を追加。差し替える境界は既存テストと同じ
`nodes.plan_search.build_model`）

**新規（US7 / T067。`tests/unit/test_providers.py`）**: `test_the_protocol_declares_required_query_count` /
`test_required_query_count_is_declared[x-5]` / `[youtube-1]` /
`test_required_query_count_carries_an_explicit_annotation[x-5]` / `[youtube-1]` /
`test_the_generation_prompt_states_the_declared_count[x-*]` / `[youtube-*]`（7 件。注釈の有無は
`inspect.getsourcefile` で実装ファイルを読んで照合する）

**新規（US7 / T068。`tests/unit/test_prompts.py`。新規ファイル）**: 走査対象の健全性
（`test_the_scan_covers_every_prompt_constant`）＋ 各定数 × 4 節（停止条件 / 出力形式 /
判定不能表現の禁止 / 固定テンプレートの禁止）＋ 重要制約 3 種 ×「出力形式の節の前」と
「節の中」の二重明示（78 件。`*_PROMPT` の命名で集めるため、追加した点検プロンプトも自動で対象）

**更新（US7 / T069。Protocol の拡張に伴う走査テストの追加）**:
`test_provider_exposes_the_full_interface` に `review_search_prompt` の型検査を追加
（`providers/base.py` に `review_search_prompt` を宣言したため。§5 の「契約 §2 が列挙する
Provider の追加属性は `required_query_count` のみ」の行を参照）

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

**新規（上限超過の検出と縮小。`tests/unit/test_degradation.py`、49 件。US3 / T047・T048）**

| 関心 | テスト |
|---|---|
| 条件 3 の第 1 経路 | `test_a_context_length_code_is_detected`（400 / 413） |
| 条件 3 の第 2 経路と語彙 | `test_an_invalid_request_with_the_vocabulary_is_detected` / `test_the_vocabulary_variants_are_all_detected`（5 語彙） |
| `body` が文字列 | `test_a_string_body_is_handled_without_reading_attributes`（構造が無いので `False`。属性で拾う実装は誤認する） |
| 条件 3 を満たさない `400` | `test_a_400_without_a_token_metric_is_not_detected`（5 入力）/ `test_other_status_codes_are_not_detected`（5 値） |
| 条件 4（除外語彙） | `test_the_exclusion_words_win_over_the_metric`（5 語彙。T055 (a) の標的） |
| 上限超過以外の例外 | `test_non_limit_exceptions_are_not_detected`（5 型）/ `test_a_class_that_only_imitates_the_name_is_not_detected` / `test_a_renamed_subclass_of_the_real_exception_is_detected` |
| 上限表の引き当て | `test_a_known_model_returns_its_token_limit` / `test_an_unknown_model_returns_none` |
| 縮小 | `test_shrink_keeps_the_head_and_drops_the_tail` / `test_shrink_is_monotonic_for_the_configured_ratios` |
| 段数と停止条件 | `test_the_ladder_does_not_exceed_the_max_attempts` / `test_the_stage_count_follows_the_configuration` / `test_each_stage_shrinks_by_the_ratio` / `test_the_ladder_stops_when_the_input_cannot_shrink`（T055 (c) の標的）/ `test_the_ladder_stops_below_the_minimum_input_length` / `test_the_minimum_input_length_is_inclusive` |
| 既知 / 未知モデル | `test_a_known_model_uses_the_token_limit_for_the_first_stage` / `test_an_unknown_model_shrinks_by_the_ratio_and_records_limit_known_false` / `test_a_model_without_a_name_is_treated_as_unknown` |
| 記録と理由 | `test_the_record_carries_the_node_stage_lengths_and_reason` / `test_the_reason_is_not_the_compression_reason`（FR-019） |

**拡張（連携。`tests/unit/test_llm.py` +7 件 → 28 件。US3 / T049）**:
上限超過は再試行せず縮小して呼び直す / 縮小後の入力は元の先頭を保つ / 段を使い切ったら理由つきの
例外（段数と縮小前後の長さ）/ 縮小後の非上限エラーは伝播する / `degrade` 未指定なら従来どおり
例外を伝える / 構造化出力でも同じ縮退 / `note()` は 1 行だけ / 縮退が無ければ `note()` は
出ない（既定の入力の出力を変えない）。

**拡張（CLI。`tests/integration/test_cli_contract.py` +3 件。US3 / T050）**:
縮退を使い切ったら stderr に理由（ノード・試した段数・縮小前後の長さ）＋ `[エラー]` 1 行で
**exit 1** / 縮小して成功したら **exit 0** で `[補足] 縮退: …` が 1 行 / 除外語彙を含む `400` は
縮退せず exit 1（誤認の禁止）。ハーネス（`cli_harness.py`）に `degrade_success` /
`degrade_exhausted` / `degrade_other_error` の 3 シナリオを追加し、`parse_instruction` の
LLM だけを上限超過のダブルに差し替える（他ノードは既定の応答のまま）。

**拡張（部分失敗の隔離。`tests/unit/test_analyze_content.py` +7 件 → 63 件。US4 / T056・T057）**

既存の `FakeModelFactory` はノード単位で応答を決めるため「特定の候補だけ失敗させる」ことが
できない。テスト内に `_SelectiveLLM` / `_SelectiveStructured`（プロンプトに**目印の文字列**が
含まれる候補だけ例外を送出する）を置き、`trend_researcher.nodes.analyze_content.build_model` を
patch する（既存テストと同じ差し替え点）。**構造化とテキストの両経路で送出する**のが要点で、
片方だけだと他方が成功して失敗が再現しない（フォールバックが失敗を覆い隠す）。

| 関心 | テスト |
|---|---|
| 1 件の失敗が他を止めない（US4 シナリオ 1） | `test_one_failed_candidate_does_not_stop_the_others`（10 件中 3 件失敗 → 解析 7 件・失敗 3 件） |
| 無言の欠落が無い（FR-021） | `test_every_candidate_ends_up_in_analyses_or_failures`（`analyses` ＋ `failures` の id の和集合が全候補と一致） |
| 失敗の内容（FR-023） | `test_the_failure_record_carries_the_id_and_the_reason`（`kind` / `id` / `error_type` / `message` に目印の理由が入る） |
| 全件失敗でも完走（US4 シナリオ 3） | `test_all_candidates_failing_still_completes`（`analyses` が空で完走する） |
| キャンセルは飲み込まない（T057） | `test_cancellation_is_not_swallowed_as_a_partial_failure`（`pytest.raises(asyncio.CancelledError)`） |
| 失敗の可視化（FR-023） | `test_the_failure_note_reports_the_count_and_the_reasons`（`[補足] 解析できなかった対象 3 件` が**ちょうど 1 行**、`RuntimeError` を含む） |
| 既定の入力の出力を変えない（FR-035） | `test_no_failure_note_when_nothing_failed` |

**拡張（追加文脈の取得失敗。`tests/unit/test_fetch.py` +5 件 → 7 件。US4 / T058）**:
取得できなかった候補が `Failure(kind="context")` になる / 前の段の `failures` を上書きせず
**追記**する（`AgentState` の `failures` に reducer が無いため）/ 文脈が取れていれば増えない /
一括取得の失敗は**既存の `notes` の文言のまま**（`contexts` は候補の本文で代替されるので
`failures` には載せない）/ YouTube の字幕なしも同じ規則で記録する。

**拡張（失敗の可視化。`tests/unit/test_compile_report.py` +5 件 → 25 件。US4 / T059）**:
一部失敗は `report.notes` に足さない（既定の出力を変えない）/ 全件失敗のときだけ
`解析 0 件（すべて失敗: 3 件）` を **1 行だけ**足す / 候補 0 件は「全件失敗」ではない
（既存の該当なしの行のみ）/ `include_intermediate=True` のときだけ `cache/failures.json` を
書く（内容はモデルの `model_dump(mode="json")` と一致）/ `cache_dir` が無ければ書き込み関数を
1 回も呼ばない。

**更新（US8 / T089。「`cache/` に増えるファイル」を固定していた 2 件）**

| テスト | 変更 | 理由 |
|---|---|---|
| `tests/unit/test_compile_report.py::test_intermediate_data_is_written_when_enabled` | 期待ファイル一覧に `usage.json` を追加（5 件に） | 契約 §7「記録先: `cache/usage.json`（**`cache_dir` があるときのみ**）＋ `note()` の 1 行」が、`include_intermediate` とは**独立に** `usage.json` を要求する（quickstart.md:139 の `cache/` の表も「`report.json`（＋ `usage.json`）。`TR_INCLUDE_INTERMEDIATE=true` のときだけ `compressed.json` / `degradations.json` / `failures.json` が増える」と定める）。T080 が固定した「既定で増えるのは `report.json` のみ」は US8 が上書きする設計 |
| 同上 `test_the_default_writes_no_new_files_and_keeps_the_report_keys` | 期待を `sorted(...) == ["report.json", "usage.json"]` に変更し、docstring に「`usage.json` は `include_intermediate` に依存しない」根拠を明記 | 固定したい性質（`compressed.json` / `degradations.json` / `failures.json` は**中間データのスイッチに従う**）は変えていない。`report.json` の中身の比較（`REPORT_JSON_KEYS` / `model_dump` との一致）もそのまま |

**新規（US8 / T083・T084。使用量の集約と欠落の記録）**: `tests/unit/test_state.py` +2 件
（`test_usage_from_parallel_nodes_is_concatenated` / `test_usage_elements_are_kept_when_two_sequential_nodes_write_them`。
**T015 から reducer があるため最初から green**。探針 (a) の標的として残す）／
`tests/unit/test_llm.py` +9 件（`UsageMeter` を `llm.py` から **import して駆動**する。1 呼び出し = 1 要素、
`model` は解決順に従う、構造化出力も同じ経路、`usage_metadata` が無い / 一部だけのときは
`None` を保持、失敗した試行は記録しない（再試行 1 回で 1 要素）、縮退時は成功した 1 回だけ、
`meter` 未指定なら何も記録しない、同期ラッパーも同じ）／`tests/unit/test_compile_report.py` +9 件
（`usage.json` の 7 キー、`unknown_calls` を合計から除外、呼び出し 0 件でも全ゼロで書く、
`cache_dir` が無ければ書かない、**`report.json` より前に書く**（`write_json` を
`monkeypatch` で包んで呼び出し順を固定）、`[補足]` の 1 行と不明件数、記録 0 件なら出さない、
レポートにキーを足さない）。

**新規（US8 / T085・T086。宣言の網羅と Studio 経路）**: `tests/unit/test_configuration.py` +7 件。
凍結した既存 6 項目（`FROZEN_LEGACY_FIELDS`）を除く**全項目**に `x_oap_ui_config` があり、
`ui_type` が契約の対応表（bool → `boolean` / int・float → `number` / str・`Literal` → `text`）に従い、
数値項目は `ge` / `le` を持ち、選択肢項目（`structured_method`）の `choices` が
`("json_schema", "function_calling")` と一致することを走査する。Studio 経路は
`from_runnable_config({"configurable": {"analysis_concurrency": 4}})` が値を反映し、
値域外（99）は `ValidationError`、追加した全項目は代表値で変更できることを固定。

**新規（US8 / T087。環境変数の直接参照の走査。`tests/unit/test_config_scan.py`。新規ファイル）**:
`src/trend_researcher/nodes/**` と `src/trend_researcher/tools/**` を AST で走査し、
`os.environ` / `os.getenv` / `load_dotenv` の参照を集める。許可するのは `tools/llm.py` の
`OPENAI_API_KEY` / `OPENAI_BASE_URL` の **2 行だけ**（行の内容で照合）。走査対象が
全ノード・全ツールを覆っていること（非空虚性）を別テストで固定し、新しいモジュールを
足したときに走査から漏れないようにする。

**拡張（US8 / T083・T084。統合。`tests/integration/test_full_flow.py` +2 件 / `tests/integration/test_cli_contract.py` +2 件）**:
既定の入力（5 件の候補）で `usage` が実グラフを経由して 9 要素に連結され、
`usage.json` の `by_node` が `parse_instruction:1` / `plan_search:2` / `analyze_content:5` /
`extract_common:1` になること、および `[補足]` の 1 行が **stderr のみ**に出ること。
CLI 契約側は `--max-results 3` の実行で 7 回（`analyze_content:3`）になることを
サブプロセスから固定する（フェイクは `usage_metadata=None` を返すため、
**FR-061 の「不明でも継続」の経路そのもの**を通る）。

**新規（T093。追加の観測が `note()` だけであることの走査。`tests/unit/test_progress.py` +5 件）**:
`src/trend_researcher/nodes/**` を AST で走査し、`emit()` / `note()` の呼び出し箇所を数える。
`emit()` は 7 ノード × 「開始 / 完了」（＋ `compile_report` の既存の「書き込み失敗」報告 1 箇所）
= **15 箇所のまま**で、US1〜US8 が足した観測（圧縮・縮退・失敗の内訳・使用量・点検の失敗）は
**`note()` の 8 箇所にだけ**現れる。あわせてノードが `print` / `sys.stdout` / `sys.stderr` を
直接使っていないこと（観測の入口を 2 つに限る）と、走査が空振りしていないこと（合成ソースで
数が増える）を固定する。

**更新（T095。統合テストの環境に `TR_RETRY_WAIT_SECONDS=0` を追加。`tests/integration/conftest.py`）**

| テスト | 変更 | 理由 |
|---|---|---|
| `build_env()`（`cli_runner` / `cli_module_runner` が使う env の組み立て） | `"TR_RETRY_WAIT_SECONDS": "0"` を追加 | **実時間の待機を除去する**（SC-013）。統合テストの CLI はサブプロセスなので `tests/conftest.py` の `SleepSpy` が効かず、ハーネスの構造化出力ダブルが常に `OutputParserException` を送出するため再試行の待機（既定 1.0 秒 × 2 回 × 構造化呼び出し）を実時間で払っていた。**待機の回数と値**は `tests/unit/test_llm.py`（`SleepSpy`。T035(a) の探針が落とす）が固定しており、0 を渡しても**再試行の回数・結果・観測できる出力（stdout / stderr / 終了コード / `messages`）は変わらない**（実測: 既定の 1 シナリオが 10.06 秒 → 1.32 秒、変更後にフルスイートが green）。0 を渡すこと自体が `TR_RETRY_WAIT_SECONDS` の配線の確認にもなる（既定値 `1.0` の意味は変えない） |


### 7. 参照実装の欠陥を移植していないことの確認（FR-063 / FR-064）

- [X] 検出器がクラス名・モジュール名の**文字列**に依存していない（`isinstance` ベース。US3 / T051）
- [X] 上限テーブルの引き当てで未知モデルを例外にしていない（比率方式。US3 / T051）
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

---

## Phase 12: Convergence

収束チェック（`/speckit.converge`）の結果。`spec.md` / `plan.md` / 憲法を intent とし、実装済みの
コードを実測して「まだ満たされていない」項目だけを追記する。既存タスク（T001〜T097）と判定は
書き換えない。各行の末尾がトレース元（`per <ref> (<gap-type>)`）。

**確認済み（新規タスク不要）**: FR-047（契約 §6 が単体測定テストを指定しており実装と一致）、
FR-059 / SC-023 の凍結 6 項目と `sort_by` の選択肢差（`data-model.md §1.1` の「既存 7 フィールドは
そのまま」／不変条件 4 と §5 の記録）、FR-017 の「縮小後の上限」（T054 が「段数・縮小前後の長さ」と
定義）、FR-041 の比較表示（判定順は実走で `rng` 付き、比較は読み出しのみで判定を伴わない）、
FR-033 / SC-014（`pyproject.toml` は `3a6fe15` から不変）、FR-006 / FR-011〜014 / FR-020 / FR-023 /
FR-061 / FR-062 / FR-069（実施済みのテストで固定されている）。

- [X] T098 [US6] **（CRITICAL: 憲法 原則 I / US6 の独立テスト）** 実走の使用量が結果に載らない配線を直し、テストで固定する。`script/evaluate.py` の `_add_usage` は `state["usage"]`（`list[ModelUsage]`）を受けるのに `Mapping` 前提で早期 return するため、実測では常に `{}` → `records.usage_summary` が `status: 不明`・トークン全 `None` になる（キー名も `records.USAGE_KEYS` の `prompt_tokens` / `completion_tokens` と集計の `input_tokens` / `output_tokens` で不一致）。畳む場所（`_add_usage` か `records`）を一意にし、`_add_usage` を実値で駆動する単体テストを `tests/unit/test_evaluation_entrypoint.py` に足す（ファイル: `script/evaluate.py` / `tests/unit/test_evaluation_entrypoint.py`）per FR-042 / SC-024 (partial)
- [ ] T099 [US6] テストスイートを 60 秒以内で完走させる（SC-013）。残る下限はサブプロセス起動 55 件 × 約 1.3 秒で、内訳は CLI の import コスト（`python -X importtime` で 1.19 秒。`openai` 507 ms / `langgraph.graph` 496 ms）。**凍結契約の固定方法（FR-035 / SC-008）は変えずに** import を遅延させて実測し、到達できない場合は「起動回数 × 実測コスト」の下限と不可能性の根拠を §5 に確定する（不変条件: 既定の入力の `stdout` / `stderr` / 終了コード / `messages` / 呼び出し回数が変わらない）（ファイル: `src/trend_researcher/tools/llm.py` / `src/trend_researcher/__main__.py` / `specs/003-pipeline-hardening-and-evaluation/tasks.md`）per SC-013 (partial)
- [ ] T100 [US6] 評価の実走で `include_intermediate` を有効にして実行し、中間データ（採用したクエリ・素材長・解析件数・縮退や失敗の発生）を結果から確認できるようにする。現状 `script/evaluate.py` に `include_intermediate` の参照が無く、`_generate` は `report` と `usage` しか読まない。記録する項目と確認方法をテストで固定する（ファイル: `script/evaluate.py` / `tests/eval/records.py` / `tests/unit/test_evaluation_entrypoint.py`）per FR-046 (partial)
- [X] T101 [US3] `get_model_token_limit` の部分文字列一致（`src/trend_researcher/tools/degradation.py` の `key in model`）を、参照実装の欠陥（辞書の反復順に依存し、短い鍵が長い鍵を影にする）を移植しない形へ直す。実測: `openai:o1-pro` / `openai:o3-pro` が先行キーに影にされ（`openai:o1` の値を変えると `openai:o1-pro` が 111111 を返す＝自身の登録値 200000 は到達不能）、未登録の `google:gemini-pro-vision` が 32768 で拾われる。完全一致優先の規則と「影になる鍵が無い」ことをテストで固定する（ファイル: `src/trend_researcher/tools/degradation.py` / `tests/unit/test_degradation.py`）per FR-063 (contradicts)
- [ ] T102 [US3] 圧縮と縮退が同じ実行で起きる経路（圧縮で素材を削った後に上限超過で梯子を登る）を実経路のテストで固定する。AST 走査では両方を扱うテストが 0 件（`tests/unit/test_compile_report.py` の 2 件は状態の手注入のみ）で、統合の縮退シナリオも `parse_instruction` だけである（ファイル: `tests/unit/test_analyze_content.py` / `tests/integration/test_cli_contract.py`）per FR-019 (partial)
- [ ] T103 [US6] `tests/eval/axes.md` の観点↔制約の対応表を機械的に固定する。変異探針では観点 3 と 4 の制約を入れ替えても `tests/unit/test_evaluation.py` が 39 passed（識別子が表に現れるかしか見ていない）（ファイル: `tests/unit/test_evaluation.py` / `tests/eval/axes.md`）per FR-048 / FR-074 (partial)
- [ ] T104 [US3] 実装メモ §7「参照実装の欠陥を移植していないことの確認」の未チェック 3 項目（無効なオプションを渡す経路・ツール契約の対称性・常に真の条件と到達しない分岐）をコード走査と実測で確定してチェックを付ける。到達しない分岐の実例: `tools/degradation.py` の `_budget` の `tokens <= 0` はテーブル最小 32768 − 予約 10,000 > 0 で到達不能（カバレッジでも未実行）。到達不能を論証できるなら削除し、残す場合は根拠をコメントとテストで固定する（ファイル: `specs/003-pipeline-hardening-and-evaluation/tasks.md` / `src/trend_researcher/tools/degradation.py`）per FR-063 / FR-064 (partial)
- [ ] T105 [US6] `script/evaluate.py` の commit 解決（`resolve_commit` / `_git_dir` / `_commit_from_git_dir` / `_packed_ref`）をテストで固定する。現在は commit 文字列を直接注入するテストのみで、`.git` から読む経路と解決できないときに `unknown` へ落ちる経路が未検証である（ファイル: `tests/unit/test_evaluation_entrypoint.py` / `script/evaluate.py`）per FR-043 (partial)
- [ ] T106 [US6] `build_judge` と `_judge_callable` が `build_model` / `ainvoke_structured` の既存経路だけを使い、`ChatOpenAI` を直接構築しないことを固定するテストを足す（`TR_MODEL` を退避して戻すことも含む）（ファイル: `tests/unit/test_evaluation_entrypoint.py` / `script/evaluate.py`）per FR-045 (partial)
- [ ] T107 [US6] 判定の再試行の規則が全観点で同一であること（観点による分岐が無く、同じ `retry_max` 経路を通る）を固定する。現在のテストは「観点ごとに 1 回呼ぶ」ことしか見ていない（ファイル: `tests/unit/test_evaluation.py` / `script/evaluate.py`）per FR-068 (partial)
- [ ] T108 [US7] 各プロンプトの停止条件が機械で判定できる内容（件数・出力形式による打ち切り）であることと、判定不能な表現（「適切に」「必要なら」等）が停止条件に現れないことをテストで固定する。現在は `【停止条件】` の見出し存在のみを確認している（ファイル: `tests/unit/test_prompts.py` / `src/trend_researcher/prompts.py`）per FR-055 / FR-056 (partial)

### 8. Phase 12（収束チェック）の記録

`/speckit.converge` が追記した T098〜T108 の実装記録。タスクごとにコミットし、対応する
Issue を閉じる。ゲートは各コミットで `uv run pytest -q` / `uv run ruff check .` /
`uv run mypy src` を通す。

| タスク | 変更 | ゲート（実測） | 変異探針 |
|---|---|---|---|
| T098 | `script/evaluate.py` の `_add_usage` を `list[ModelUsage]`（要素数＝`calls`、判明分のトークン）へ直し、対応表 `USAGE_SOURCES` を追加。`tests/unit/test_evaluation_entrypoint.py` に 6 件（対応の両方向・実値の畳み込み・不明の扱い・0 件・配線の実測） | **1,032 passed / カバレッジ 97.42% / ruff 0 件 / mypy 29 ファイル 0 件**（100.82 秒） | 修正前の `Mapping` 版へ戻すと **5 failed**（退避から復元後にフルスイート green。sha256 `530b1938…` の一致を確認） |
| T101 | `src/trend_researcher/tools/degradation.py` の `get_model_token_limit` を「登録済みの鍵との**最長の前方一致**」へ変更（完全一致はその最長ケースとして必ず優先される）。`tests/unit/test_degradation.py` に 6 件（全鍵が自分の値を返す・実測した影・影になり得る組の値反転・最長優先・派生名の前方一致・名前の途中に出る鍵） | **1,038 passed / カバレッジ 97.42% / ruff 0 件 / mypy 29 ファイル 0 件**（98.41 秒） | (1) 最長優先の並び（`sorted(..., key=len, reverse=True)`）を外すと **3 failed** (2) 参照実装の規則（`key in model` を辞書順）では **4 failed**（退避から復元後にフルスイート green。sha256 の一致を確認） |
