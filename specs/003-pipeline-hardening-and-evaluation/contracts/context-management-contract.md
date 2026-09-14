# Contract: コンテキスト管理と状態のライフサイクル

**Feature**: `003-pipeline-hardening-and-evaluation` | **Date**: 2026-09-14

**対応要件**: FR-001〜008 / FR-015〜019 / FR-020〜023 / FR-026〜029 / FR-032 / FR-046 / FR-047 /
SC-001〜SC-004 / SC-007 / SC-010 / SC-026

**境界**: `src/trend_researcher/tools/compression.py`（圧縮）と
`src/trend_researcher/nodes/compile_report.py`（レポート確定と状態の解放）。
`nodes/analyze_content.py` は圧縮を**呼ぶだけ**で、切り捨ての判断を持たない。

## 1. 取り込み量の管理（圧縮）の契約

| 項目 | 契約 |
|---|---|
| 対象 | 個別解析の素材（`_build_source_text(candidate, context)` の結果 = `provider.analyze_content_prompt` に渡す本文） |
| 発動条件 | `len(source_text) > compression_threshold`（既定 20,000 文字） |
| しきい値以下 | **追加の LLM 呼び出しを 1 回もしない**（FR-008 / SC-003）。素材を切らない（FR-001 の「全体を渡す」対象外） |
| しきい値超過 | 素材**全体**を 1 回の LLM 呼び出しで圧縮する（分割・逐次にしない。FR-001） |
| 圧縮プロンプト | `prompts.py` の `COMPRESSION_PROMPT`。**元の指示文を含める**（文脈を失わない。R-5） |
| 出力形式 | `<summary>…</summary>` と `<key_excerpts>…</key_excerpts>` の 2 部（テキスト契約） |
| 出力の大きさ | `summary` ＋ `key_excerpts` を連結し、`compression_threshold` 以内に**実装側で切り詰める**（FR-007。プロンプトの遵守に依存しない） |
| タイムアウト | `asyncio.wait_for(..., timeout=compression_timeout_seconds)`（既定 60.0 秒） |
| 失敗時 | 生素材を `compression_threshold` で切り詰めて使い、`CompressedSource(applied=False, reason=...)` を記録。**実行は継続し、終了コード 0**（SC-004） |
| 記録 | `state.compressed`（`CompressedSource` のリスト）／ `include_intermediate = True` なら `cache/compressed.json` |
| 通知 | `note()` に 1 行（圧縮した件数と平均の縮小率） |
| 呼び出し回数への影響 | しきい値以下の素材では 0 回（既定の入力では**既存の呼び出し回数と一致**。FR-035） |

**要件対応**: FR-001（全体を渡す）/ FR-002（事前に縮める）/ FR-003（要約と重要抜粋）/
FR-004（失敗時に継続）/ FR-005（しきい値とタイムアウトを実行時設定から注入）/
FR-006（素材の一部を捨てる形の切り詰めをやめる）/ FR-007（しきい値以下）/
FR-008（追加呼び出し 0 回）/ FR-032（しきい値超過素材に限る）。

## 2. 圧縮と縮退の段階の区別

| 段階 | 型 | 発動のきっかけ | `reason` の例 | 記録先 |
|---|---|---|---|---|
| 圧縮（事前） | `CompressedSource` | 素材がしきい値を超えた | `compressed` / `timeout` / `error` / `empty` | `state.compressed` |
| 縮退（事後） | `Degradation` | LLM が上限超過を返した | `token_limit` 固定 | `state.degradations` |

**不変条件**: 1 つの記録が両方を表してはならない（FR-019 の MUST）。
`Degradation.reason` に圧縮の理由は入らず、`CompressedSource.reason` に
`token_limit` は入らない。

## 3. 部分失敗の隔離の契約

| 対象 | 隔離の単位 | 失敗の扱い | 記録 |
|---|---|---|---|
| 個別解析（`analyze_content`） | 候補 1 件ごと | 他の候補の解析を継続（FR-020） | `Failure(kind="analysis", id, error_type, message)` |
| 追加文脈の取得（`fetch` / provider の境界） | 候補 1 件ごと | 取得できた分で継続（FR-022）。既存の `notes` の文言は**変更しない** | `Failure(kind="context", ...)` ＋ 既存の `notes` |
| 検索（`search`） | 実行単位 | **隔離しない**（既存の挙動: リトライ枯渇で例外。`tests/integration/test_full_flow.py` が固定） | — |
| サービス終了要求 | 実行単位 | `asyncio.CancelledError` は**再送出**（部分失敗として飲み込まない） | — |

**要件対応**: FR-020（1 件失敗でも継続）/ FR-021（無言で欠落させない）/ FR-022（取得分で継続）/
FR-023（失敗件数と理由を確認可能）/ SC-007（10 中 3 失敗 → 7 件成功）。

## 4. 状態のライフサイクルの契約

| データ | レポート確定後 | 理由 |
|---|---|---|
| `contexts[].text` / `[].thread_text` | `""` にする | 生素材（FR-026 / FR-027 / SC-010） |
| `contexts[].replies` | `[]` にする | 同上 |
| `contexts[].id` / `[].counts` | **残す** | `tests/integration/test_full_flow.py:444` が `contexts[0]` を参照する |
| `candidates[].text` | `""` にする | 生素材 |
| `candidates[].id` / メタデータ | 残す | 識別子はレポートと対応する |
| `analyses` / `common_themes` | 解放しない | 整形済みデータ（利用者に価値がある） |
| `report` | 解放しない | 最終成果物 |
| `usage` / `degradations` / `failures` / `compressed` | 解放しない | 実行後に確認する記録（FR-017 / FR-023 / FR-062） |

**実行順序（必須）**: `report` の組み立て → 中間データの書き出し → `cache/usage.json` →
`note()` → `cache/report.json` → 解放。「レポートを組む前に解放する」と
`report.candidates` が空になるため、順序をテストで固定する。

**要件対応**: FR-026（生データと整形済みデータを区別し、後続段は生データを参照しない）/
FR-027（不要になった中間データを解放）/ FR-029（進捗に入力量と縮退の有無が現れる）/
SC-010（レポート確定後に生素材が状態に残らない）。

**後続段が生データを参照しないことの固定**: `extract_common` が読むのは `analyses` のみ
（実測: `nodes/extract_common.py:38`）。ソース走査テストで、`extract_common` /
`compile_report` が `state.get("contexts")` / `state.get("candidates")[..].text` を
**新しい用途で読み始めていない**ことを確認する（既存の `compile_report` は
`len(candidates)` などの件数のみを使う）。

## 5. 中間データの切り替えの契約

| `include_intermediate` | `cache/` に書かれるファイル | 既存の出力 |
|---|---|---|
| `False`（既定） | `report.json`（既存）のみ | **変更前と一致**（SC-026） |
| `True` | `report.json` ＋ `compressed.json` ＋ `degradations.json` ＋ `failures.json` ＋（常時）`usage.json` | レポート形式は不変 |

- 切り替えは**出荷設定クラスの真偽値** `Configuration.include_intermediate`（FR-046）。
  env 名は `TR_INCLUDE_INTERMEDIATE`（`{env_prefix}_INCLUDE_INTERMEDIATE` も解決される）。
- `cache_dir` が未指定なら何も書かない（既存の挙動）。
- 書き込みの失敗は既存と同じ扱い（握りつぶさず `note()` に出し、実行は継続）。
- JSONL ではなく JSON（既存の `cache.py:write_json` を使う。UTF-8 / `ensure_ascii=False`）。

## 6. 運用特性の検証の契約（FR-047）

| 特性 | 測り方 |
|---|---|
| 並列度 | `analysis_concurrency` を 1 と 2 にして、境界のフェイクで同時実行数を数える（`max_in_flight`） |
| 上限の遵守 | `compression_threshold` を跨ぐ入力と跨がない入力で、圧縮呼び出し回数が 1 / 0 になること |
| 縮退の発生 | 上限超過の例外を 1 回返すフェイクで、`Degradation` が 1 件記録され、2 回目の呼び出しが短い入力で行われること |

**要件対応**: FR-047（並列度・上限遵守・縮退を測定で検証）。テストはすべて境界モックで完走する。

## 7. 凍結する契約（変更してはならない）

| # | 契約 | 実測による固定箇所 |
|---|---|---|
| 1 | `fetch` の進捗 `detail` の文言（`コンテキスト取得 N 件（追加文脈なし M 件）`） | `tests/integration/test_full_flow.py:459-460` |
| 2 | `report.notes` の既存要素 | `tests/integration/test_full_flow.py:443`、`tests/unit/test_compile_report.py` |
| 3 | `cache/report.json` の書き込み条件（`cache_dir` があるときのみ・`report` の `model_dump(mode="json")`） | `tests/unit/test_compile_report.py`、`tests/unit/test_cache.py` |
| 4 | `analyze_content` の進捗行（`開始（並列上限 2）` / `完了（N 件を要約）`） | `tests/unit/test_analyze_content.py:374-387` |
| 5 | 候補 0 件のときに `search` → `compile_report` へ飛ぶ条件付きエッジ | `tests/integration/test_graph_wiring.py` |
| 6 | 成果物に残る `Candidate` の `text`（レポート本文） | `tests/unit/test_rendering.py`（552 行） |

## 8. 検証（この契約を固定するテスト）

| テスト | 何を固定するか |
|---|---|
| `tests/unit/test_compression.py`（新規） | 発動条件・1 回だけ呼ぶ・出力の上限・失敗時の復帰・`CompressedSource` の内容 |
| `tests/unit/test_analyze_content.py`（拡張） | 部分失敗の隔離、`failures`、圧縮の呼び出し回数（しきい値以下で 0） |
| `tests/unit/test_compile_report.py`（拡張） | 解放の順序、`cache/usage.json` の内容、`include_intermediate` の切り替え、`note()` の出力 |
| `tests/unit/test_fetch.py`（拡張） | 取得失敗の `Failure` 記録と既存 `notes` の維持 |
| `tests/unit/test_state.py`（新規） | `usage` の reducer が並列結果を連結すること |

**変異探針**:

| 変異 | 期待 |
|---|---|
| 圧縮の分岐を `pass` にする（`return text[:max_chars]` のみ） | 圧縮のテストが落ちる |
| 出力の切り詰めを削る | FR-007 のテストが落ちる |
| 解放を「レポート組み立ての前」に移す | 解放の順序テストが落ちる |
| `contexts` を空リストにする | `tests/integration/test_full_flow.py:444` が落ちる |
| `include_intermediate` の条件を反転する | 中間データの切り替えテストが落ちる |
| `return_exceptions=True` を外す | 部分失敗のテストが落ちる |
