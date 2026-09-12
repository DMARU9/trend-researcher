# Phase 1 Data Model: テスト拡充によるパイプライン信頼性の向上

**Feature**: `001-test-suite-hardening` | **Date**: 2026-09-12

本機能の成果物は**テストスイート**である。したがってここで定義するエンティティは「テスト成果物」であり、`state.py` / `models.py` のドメインモデルは**変更しない**。

ドメインモデル側は「検証対象（Read-only）」として扱い、テストが固定する契約だけを列挙する。

---

## 1. テスト成果物のエンティティ

### 1.1 テストケース（Test Case）

テストスイートの最小単位。

| 属性 | 内容 | 制約 |
|------|------|------|
| `id` | `tests/<layer>/test_<module>.py::<test_name>` | 1 テスト 1 振る舞い |
| `layer` | `unit` \| `integration` | 憲法 I の配置規約 |
| `target` | 検証対象のモジュール・関数 | 1 ファイル 1 モジュールを原則とする |
| `requirement_refs` | 対応する FR / SC の番号 | 最低 1 つ。対応が説明できないテストは追加しない |
| `kind` | `happy` \| `failure` \| `boundary` \| `contract` | FR-009 / FR-011 / FR-012 の分岐網羅に使う |
| `detects_mutation_of` | このテストが落ちるように仕込める変異の説明 | **必須**。空なら憲法 I の「無効なテスト」に該当する |

**検証規則**:

- `detects_mutation_of` を記入できないテストは追加してはならない（FR-016）。
- `kind == failure` のテストは、縮退処理（try/except、フォールバック、`notes` への記録）を 1 つでも取り除くと失敗すること。
- `kind == contract` のテストは、契約値（終了コード、出力チャネル、形式）を 1 つ変更すると失敗すること。

### 1.2 フィクスチャ（Fixture）

テストの前提状態を決定的に用意する。

| 属性 | 内容 | 制約 |
|------|------|------|
| `name` | フィクスチャ名 | 共有するものは `tests/conftest.py`、層固有は各層の `conftest.py` |
| `scope` | `function`（既定） \| `module` | テスト間の状態共有を避けるため原則 `function` |
| `mocks` | 差し替える境界 | `tools/` / `providers/` の**境界のみ**（憲法 II） |
| `frozen` | 固定する非決定性 | 時刻・待機・乱数・並列順序（FR-021） |

**必須フィクスチャ**:

| フィクスチャ | 差し替え対象 | 用途 |
|--------------|--------------|------|
| `fake_model_factory` | ノードごとの `build_model` | ノード単位で応答を指定（research.md R-7） |
| `fake_x_search` | `providers.x.search_tweets` | X の検索結果を決定的に供給 |
| `fake_x_threads` | `providers.x.fetch_threads` | X のスレッド・リプライ・正確なカウントを供給 |
| `fake_yt_search` | `providers.youtube.search_videos` | YouTube の検索結果を供給 |
| `fake_yt_transcript` | `providers.youtube.fetch_transcript` | 字幕の有無を供給 |
| `frozen_now` | `nodes.parse_instruction.datetime` | 時刻を固定（`wraps` で `fromisoformat` は実物へ委譲） |
| `no_retry_sleep` | `tools.x_search.asyncio.sleep` | リトライ待機を実時間で消費しない（FR-010） |
| `tmp_cache_dir` | `cache/` の出力先 | 実リポジトリの `cache/` を汚さない |
| `cli_runner` | なし（実行基盤） | `sys.executable` でハーネスをサブプロセス起動し、`(exit_code, stdout, stderr)` を返す |

**フィクスチャ自体の実効性**は `tests/unit/test_fixtures.py` で検証する。境界を差し替えているつもりのフィクスチャが実際には差し替えていない場合、憲法 I の「収集されない fixture」と同じ欠陥クラス（静かに無効なテスト）になる。

**検証規則**:

- `mocks` は `tools/` / `providers/` の境界に限る。`nodes/` の内部関数を差し替えてはならない（差し替えるとノードのロジックが検証されない）。
- フィクスチャが `yield` を使う場合、後処理で確実に元に戻す（`mock.patch` のコンテキストマネージャを優先）。
- 実リポジトリの `cache/` と `accounts.db` に書き込んではならない。

### 1.3 境界モック（Boundary Mock）

外部依存を差し替える仕掛け。`unittest.mock` のみを使用する（新規モック基盤を導入しない）。

| 属性 | 内容 |
|------|------|
| `boundary` | `x_search` \| `x_threads` \| `yt_search` \| `yt_transcript` \| `llm` \| `filesystem` \| `clock` \| `sleep` |
| `scenario` | `ok` \| `empty` \| `partial` \| `raises` \| `malformed` |
| `payload` | 返す値（`scenario == ok/partial` の場合） |
| `exception` | 送出する例外（`scenario == raises` の場合） |

**必須シナリオ×境界のマトリクス**（FR-009 の網羅根拠）:

| 境界 | ok | empty | partial | raises |
|------|----|-------|---------|--------|
| `x_search` | ○（必須） | ○（0 件 → ルーティング skip） | ○（複数クエリで同一 `id` → 重複除去。FR-024） | ○（リトライ枯渇 → 伝播） |
| `x_threads` | ○（必須） | — | ○（本文のみ） | ○（備考に記録して継続） |
| `yt_search` | ○（必須） | ○（0 件） | ○（投稿日欠落） | — |
| `yt_transcript` | ○（必須） | ○（字幕なし → 備考） | ○（空文字） | — |
| `llm` | ○（必須） | ○（空応答） | ○（構造化ブロックなし） | — |
| `filesystem` | ○（必須） | ○（読み戻しなし） | — | ○（書き込み不可 → 進捗に記録して継続） |
| `clock` | 固定（必須） | — | — | — |
| `sleep` | 固定（必須） | — | — | — |

### 1.4 契約アサーション（Contract Assertion）

外部から観測できる契約を固定する断言。`contracts/` 配下の規約に 1 対 1 で対応する。

| 属性 | 内容 | 対応する成果物 |
|------|------|----------------|
| `contract_id` | `CLI-<番号>` / `LAYOUT-<番号>` / `COV-<番号>` | `contracts/cli-contract.md` 等 |
| `observable` | 終了コード \| stdout \| stderr \| ファイル \| 戻り値 \| カバレッジ | — |
| `expected` | 期待値 | 契約文書の表と一致すること |
| `violated_by` | この断言を落とす変更の例 | 空なら無効なテスト |

**検証規則**: `observable` が `終了コード` / `stdout` / `stderr` の断言は、**プロセスレベルのテスト**でなければならない（FR-002）。in-process の戻り値検証では代替できない。引数エラー（`--since` 不正・空指示（FR-025）・未知の列挙値）もこの規則の対象であり、CLI-001 の層 A で観測する。

### 1.5 カバレッジ計測結果（Coverage Result）

| 属性 | 内容 | 制約 |
|------|------|------|
| `module` | 対象モジュール | `src/trend_researcher/` 配下 |
| `statements` / `missed` | 文数と未実行数 | `--cov-report=term-missing` で取得 |
| `percent` | 行カバレッジ | 判定は対象範囲の**合計**で 90% 以上（FR-019）。モジュール別の値は到達の目安であり、個別の下限ではない |
| `missing_lines` | 未実行行の一覧 | 0 件にするか、除外理由を `contracts/coverage-policy.md` に記録する |
| `excluded` | 母数から除外したモジュール | 本機能では除外しない（`omit` を設定しない。`contracts/coverage-policy.md` COV-002-3）。`prompts.py` と `trend_researcher/__init__.py` は除外可だが、`providers/__init__.py` は分岐を持つため除外しない |

**基準値（2026-09-12 実測）と到達の目安**:

**判定対象は「全体」行のみ**。モジュール別は、合計 90% を満たすためにどの領域を埋めるかを示す目安である。

| モジュール | 現状 | 到達の目安 |
|------------|------|------------|
| **全体（判定対象）** | 82% | **≥ 90%** |
| `__main__.py` | 0% | ≥ 90% |
| `tools/x_search.py` | 45% | ≥ 90% |
| `cache.py` | 38% | ≥ 90% |
| `tools/transcript.py` | 79% | ≥ 90% |
| `nodes/extract_common.py` | 79% | ≥ 90% |
| `nodes/parse_instruction.py` | 85% | ≥ 90% |
| `nodes/compile_report.py` | 88% | ≥ 90% |
| `providers/x.py` | 89% | ≥ 90% |
| `tools/youtube_search.py` | 88% | ≥ 90% |
| `providers/__init__.py` | 83% | ≥ 90% |
| `nodes/analyze_content.py` | 94% | 維持（≥ 90%） |
| `nodes/plan_search.py` | 95% | 維持（≥ 90%） |
| `providers/youtube.py` | 98% | 維持（≥ 90%） |

### 1.6 変異探針（Mutation Probe）

テストの有効性を実測で判定する手順の記録。

| 属性 | 内容 | 制約 |
|------|------|------|
| `target_file` | 改変するファイル | 1 回の探針で 1 箇所のみ |
| `mutation` | 改変内容 | 振る舞いを変えるものであること（コメント変更等は無効） |
| `sha_before` / `sha_after` | 復元の検証 | **一致しなければ判定を無効とする** |
| `observed` | `detected` \| `undetected` | スイートの成否 |
| `action` | `add_test` \| `strengthen` \| `remove` \| `merge` \| `keep` | 未検出の場合は必ず追加・強化・統合のいずれか |

**手順（必須）**: 改変 → スイート実行 → 復元 → `sha256sum` 一致確認 → スイート再実行で green 確認 → `git status` で残骸なし確認。

**確定済みの初期探針**（research.md R-4 で実測済み）:

| 探針 | `mutation` | `observed` | `action` |
|------|-----------|------------|----------|
| M1 | `compile_report` の出典構築を `[]` に | **undetected** | `add_test`（`test_compile_report.py`） |
| M2 | `graph._route_after_search` を常に `continue` に | **undetected** | `add_test`（`test_graph_wiring.py`） |
| M3 | `progress.ProgressEmitter.TOTAL` を 8 に | **undetected** | `add_test`（`test_progress.py`） |

### 1.7 無効テスト判定記録（Invalid Test Record）

憲法 I が定める「無効なテスト」の監査結果。

| 属性 | 内容 |
|------|------|
| `test_id` | 対象テスト |
| `reason` | `tautological`（恒真） \| `duplicate`（重複） \| `weak`（検証不足） \| `copy_of_impl`（実装の写し） \| `not_collected`（収集外） |
| `evidence` | 変異探針の結果、または重複先のテスト ID |
| `resolution` | `strengthened` \| `merged` \| `removed` \| `kept_with_reason` |

**初期判定**（research.md R-4 で特定済み）:

| `test_id` | `reason` | `evidence` | `resolution` |
|-----------|----------|------------|--------------|
| `tests/unit/test_models.py::test_report_sources_invariant` | `tautological` | 断言が構築式と同一。M1 未検出 | `strengthened`（`compile_report` 経由に置換） |
| `tests/test_graph.py::TestAgentState`（2 件） | `duplicate` | 同一クラス内で同一断言 | `merged` |
| `tests/test_graph.py::TestConfiguration`（5 件） | `duplicate` | `tests/unit/test_configuration.py` と同一 | `removed` |
| `tests/test_graph.py::TestGraphBuild`（2 件） | `weak` | `is not None` のみ。M2 未検出 | `strengthened`（配線・ルーティングを固定） |
| `tests/unit/test_transcript.py::test_transcript_dataclass` | `weak` | production の分岐を通らない | `removed` または `strengthened` |
| `tests/unit/test_parse.py::test_parse_angles_table_skips_header_and_separator` | `duplicate` | `test_parse_angles_table` が同一経路を検証 | `merged` |
| `tests/unit/test_youtube_search.py::test_search_videos_limits_to_max` | `duplicate` | `test_search_videos_top_n` が件数制限を検証 | `merged` |
| `tests/integration/test_full_flow.py::_FakeModel` | `weak`（誤検知） | 部分一致で `extract_common` に誤応答。共通テーマが 0 件に | `strengthened`（ノード単位の注入へ変更） |

---

## 2. 検証対象（Read-only）

テストが固定する既存の契約。**変更しない**。

| エンティティ | 定義場所 | テストが固定する内容 |
|--------------|----------|----------------------|
| `AgentState` / `AgentInputState` | `state.py` | ノード間で受け渡すフィールドの集合。進捗メッセージが `messages` に蓄積されること |
| `Candidate` / `Context` | `models.py` | プラットフォーム共通の候補表現。`relevance_rank` の振り直し |
| `ResearchInstruction` / `OutputSpec` / `OutputFormat` | `models.py` | 件数・出力形式・投稿日下限の解決結果 |
| `AnalysisFinding` / `BlogAngle` | `models.py` | LLM 自由文から抽出した要約・切り口・引用 |
| `CommonTheme` | `models.py` | テーマ名・説明・該当 ID・代表抜粋 |
| `ResearchReport` | `models.py` | 出典（`sources`）が候補の URL から構築されること（M1 の対象） |
| `Configuration` | `configuration.py` | `RunnableConfig` からの解決と `None` の除外 |
| `Config` | `config.py` | 環境変数の優先順位（`TR_*` > `XTR_*`/`YTR_*` > 既定）とパス解決 |
| `ProgressEmitter` / `NODE_ORDER` / `TOTAL` | `progress.py` | 開始／完了の必ず出力。`TOTAL == len(NODE_ORDER) == グラフのノード数` |
| `Provider`（`XProvider` / `YouTubeProvider`） | `providers/` | 検索・取得・描画・ソートの差が provider に閉じていること。X の `search` は複数クエリの重複候補を除去し取得順を維持すること（FR-024）。YouTube は単一クエリのみのため重複除去を要求しない（この非対称は仕様） |
| `Transcript` | `tools/transcript.py` | 字幕形式（VTT / json3）と `source` の判定 |

**状態遷移（グラフの経路）**:

```text
parse_instruction → plan_search → search ─┬─ 候補あり → fetch → analyze_content → extract_common → compile_report → END
                                          └─ 候補なし → compile_report → END
```

| 遷移 | 条件 | 固定するテスト |
|------|------|----------------|
| `search → fetch` | `candidates` が 1 件以上 | `test_graph_wiring.py`（M2 の対） |
| `search → compile_report` | `candidates` が 0 件 | `test_graph_wiring.py`（M2 の対） |
| 全ノード通過 | 常に | `test_full_flow.py` の進捗 7 行 |

---

## 3. エンティティ間の関係

```text
Test Case ──uses──> Fixture ──applies──> Boundary Mock ──emulates──> 外部サービス
    │                                                                       │
    └──asserts──> Contract Assertion ──verifies──> 検証対象（Read-only）      │
    │                                                                       │
    └──audited_by──> Mutation Probe ──revises──> Test Case  ◄────────────────┘
                              │
                              └──records──> Invalid Test Record

Coverage Result ──measures──> 検証対象（未実行行の特定）
```

## 4. 除外・非対象

| 対象 | 扱い | 理由 |
|------|------|------|
| 実 API（OpenAI / X / YouTube） | 自動テストの対象外 | 憲法 II。README の手動スモークとしてのみ実施 |
| `cache/` の読み戻し経路 | 契約（存在しない場合の戻り値）の固定のみ | 現状「書き込み専用」の設計（憲法 VI / spec Assumptions） |
| `prompts.py` / `__init__.py` | カバレッジ母数から除外 | 宣言のみで分岐がない |
| `src/` 全体の静的品質 burndown | 追跡タスクとして起票 | 憲法 `TODO(BASELINE-BURNDOWN)`。本機能の完了条件外 |
| `tools/` / `providers/` の実装変更 | US4 が欠陥を検出した場合のみ最小修正 | FR-023 |
