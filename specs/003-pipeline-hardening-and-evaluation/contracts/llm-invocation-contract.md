# Contract: LLM 呼び出しの契約（構造化出力・再試行・縮退・使用量）

**Feature**: `003-pipeline-hardening-and-evaluation` | **Date**: 2026-09-14

**対応要件**: FR-009〜014 / FR-015〜019 / FR-018 / FR-061 / FR-062 / FR-063 / FR-064 / FR-068 / FR-069

**境界**: `src/trend_researcher/tools/llm.py`（呼び出しの構築・再試行・縮退・使用量の記録）と、
`src/trend_researcher/tools/degradation.py`（上限超過の検出と縮小の純粋関数）。
ノードは**この境界の関数だけ**を通して LLM を呼ぶ。ノードが `ChatOpenAI` を直接構築しては
ならない（FR-045）。

## 1. 呼び出しの 3 形態

| 形態 | 関数 | 用途 | 再試行 | 縮退 |
|---|---|---|---|---|
| テキスト | `invoke_text` / `ainvoke_text`（既存 `build_model` の利用経路） | `plan_search` の生成・点検、圧縮 | あり（FR-010） | あり（FR-015） |
| 構造化 | `invoke_structured` / `ainvoke_structured`（追加） | `parse_instruction` / `analyze_content` / `extract_common` | あり | あり |
| 判定（評価。出荷パッケージ外） | `script/evaluate.py` が同じ境界を使う | 評価の採点 | 全観点同一（FR-068） | なし（入力を縮めない） |

## 2. 構造化出力の契約

| 項目 | 契約 |
|---|---|
| スキーマ | `models.py` の Pydantic モデル（`ResearchInstruction` / `AnalysisFinding` / `CommonTheme`） |
| 構築 | `build_model(role, env_prefix).with_structured_output(Model, method=<structured_method>)` |
| `method` | `Configuration.structured_method`（既定 `function_calling`）。`json_schema` へ切り替え可能 |
| 成功時 | モデルのインスタンスを返す（ノードは `.model_dump()` せず、そのまま状態へ入れる） |
| パース失敗 | `OutputParserException` / `ValidationError` を捕捉 → 再試行（3 節） |
| 規定回数失敗 | 既存の決定的解析へフォールバック（4 節）。例外を送出しない |
| 直接構築の禁止 | ノードは `ChatOpenAI` / `init_chat_model` を参照しない（テストで走査。FR-045） |

**要件対応**: FR-009（構造化スキーマで受ける）/ FR-045（既存経路の維持・直接構築の禁止）/
SC-003 相当（呼び出しの一元化）。

## 3. 再試行の契約

| 項目 | 契約 |
|---|---|
| 合計試行回数 | `1 + retry_max`（既定 `retry_max = 2` → 3 回。SC-005） |
| 待機 | 再試行の前に `retry_wait_seconds`（既定 `1.0`）。`0` なら待機しない |
| 待機の観測 | `tools.llm.asyncio.sleep` を通す（テストの `SleepSpy` で除去・観測できる） |
| 対象 | `OutputParserException` / `pydantic.ValidationError` / `APIConnectionError` / `asyncio.TimeoutError` |
| **対象外** | 上限超過と判定された例外（縮退へ渡す）、`asyncio.CancelledError`（再送出）、設定ミス系の 4xx（そのまま送出） |
| 試行ごとの記録 | `ModelUsage` を 1 要素追加（回数とトークンが残る。FR-061 / FR-042） |
| 全失敗時 | フォールバック（4 節）＋ `note()` に 1 行 ＋ 中間データに記録 |

**要件対応**: FR-010（規定回数まで自動再試行）/ FR-011（失敗時フォールバック）/
FR-013（プロンプトに上限・停止条件・出力形式を明示）/ FR-028（上限をテストで固定）。

## 4. フォールバックの契約（ノードごと）

| ノード | フォールバック先 | 結果の型 | 無言にしない方法 |
|---|---|---|---|
| `parse_instruction` | `tools/parse.py` の `extract_json_block` ＋ 既存の正規表現群 | `ResearchInstruction` | `note()` ＋ `degradations` に `reason="structured_fallback"` |
| `analyze_content` | 既存の `_parse_angles_table`（見出し表の抽出） | `AnalysisFinding`（1 件以上保証できない場合は失敗として `failures` へ） | `note()` ＋ `failures` |
| `extract_common` | `tools/parse.py` の `extract_list_items` / `extract_section` | `CommonTheme` のリスト（空を許す） | `note()` ＋ `degradations` |
| `plan_search`（点検） | 生成結果を採用（4 節の規則） | `list[str]` | `note()`（差分が出たときのみ） |

**要件対応**: FR-011 / FR-012（正常系とフォールバックの**両方**をテストで固定）/
FR-051（点検失敗時は生成結果で継続）。

## 5. 上限超過の検出の契約

```
is_token_limit_exceeded(exc) -> bool
```

**すべての条件を満たしたときだけ `True`**（保守的。誤認の禁止 = FR-018）。

| # | 条件 | 実装 |
|---|---|---|
| 1 | `isinstance(exc, openai.APIStatusError)` | **型**で判定（クラス名の文字列比較をしない） |
| 2 | `exc.status_code in (400, 413)` | 数値で判定 |
| 3 | 応答本文またはメッセージにトークン量の指標がある | `body.error.code == "context_length_exceeded"`、または `body.error.type == "invalid_request_error"` ＋ 語彙（`context length` / `maximum context` / `too many tokens` / `token limit` / `reduce the length`） |
| 4 | 無効な引数・設定ミスを示す語が**無い** | `unsupported` / `unknown parameter` / `invalid model` / `does not exist` / `invalid api key` のいずれも含まない |

`body` は dict / str の双方を扱う（`getattr` ではなく `isinstance(body, dict)` で分岐。
「宣言と実装の乖離」を作らない）。

**参照実装との差**（FR-063 / FR-064）:

| 参照実装（移植しない） | 本契約 |
|---|---|
| クラス名の文字列比較（`class_name in [...]`） | `isinstance` による型判定 |
| モジュール名の部分一致（`'openai' in module_name.lower()`） | 型判定に一本化（不要） |
| `exception.code` / `exception.type` を `getattr` せず参照 | `body` を dict として読み、無ければ metric なし |
| 例外クラスごとに 3 つの checker を呼び分け、既知でないと**すべて試す** | 判定は 1 経路（条件 1〜4） |
| 上限テーブルに未知のモデルは例外 | 比率のみで縮退（`limit_known = False`。FR-015） |

## 6. 段階的縮退の契約

| 項目 | 契約 |
|---|---|
| 発動 | 上限超過と判定された呼び出しのみ（圧縮とは別段階。FR-019） |
| 段数 | 最大 `degrade_max_attempts`（既定 3） |
| 縮小 | 直前の入力長 × `shrink_ratio`（既定 0.9）。切り詰め位置は末尾（素材の先頭を残す） |
| 既知モデルの初回 | `get_model_token_limit(model)` の値から「上限に収まる文字数」を初回の目標に使う |
| 未知モデル | 比率のみ（`limit_known = False` を記録。R-18） |
| 打ち切り | (a) 段数を使い切った、(b) 縮小後の長さが前段と同じ、(c) `min_input_chars` 未満 |
| 記録 | 段ごとに `Degradation(node_name, stage, before_chars, after_chars, "token_limit", limit_known)` |
| 通知 | `ProgressEmitter.note()` に 1 行（FR-017 / FR-029） |
| 使い切った場合 | 例外を送出 → `__main__.py` が stderr に理由（試した段数・縮小前後の長さ）を出して **exit 1** |
| 禁止 | 無限縮小（停止条件 (b)(c) で担保）、引数の組み替え（文字列のオプションを渡す経路を作らない）、別モデルへの切り替え |

**要件対応**: FR-015（段階的縮小再試行・使い切ったら理由明示＋exit 1・無限縮小禁止）/
FR-016（入力を段階的に落とす）/ FR-017（事後に確認可能）/ FR-019（別段階として記録）。

## 7. 使用量の記録の契約

| 項目 | 契約 |
|---|---|
| 集計元 | 呼び出し境界で `AIMessage.usage_metadata` の `input_tokens` / `output_tokens` / `total_tokens` |
| 欠落時 | `None` のまま記録し「不明」として扱う（例外にしない。FR-061） |
| 粒度 | 呼び出し 1 回につき `ModelUsage` 1 要素 |
| 受け渡し | `AgentState.usage`（`Annotated[list[ModelUsage], operator.add]`） |
| 記録先 | `cache/usage.json`（`cache_dir` があるときのみ）＋ `note()` の 1 行 |
| レポート | **含めない**（D-3。`ResearchReport` のフィールドを増やさない） |

**要件対応**: FR-061（実行 1 回単位で集計・不明でも継続）/ FR-062（中間成果物と進捗に記録）/
FR-042（トークン数と呼び出し回数を併記）。

## 8. 凍結する契約（変更してはならない）

| # | 契約 | 実測による固定箇所 | 要件 |
|---|---|---|---|
| 1 | 進捗行の文言・行数・状態 `messages` の内容 | `tests/unit/test_analyze_content.py:374-387`（厳密比較）、`tests/integration/test_full_flow.py:167-181`（`(node, phase)` 列の厳密比較） | FR-030 / SC-011 / SC-012 |
| 2 | `emit()` の `detail` の既存文言（`（並列上限 2）` / `（5 件を要約）` 等） | 同上 | FR-035 |
| 3 | 既定の入力での LLM 呼び出し回数 | `tests/integration/test_full_flow.py:241-242`（`analyze_content` = 5 / `extract_common` = 1）、`tests/unit/test_analyze_content.py:421`（同時 2） | FR-028 / FR-035 |
| 4 | stdout = レポートのみ / stderr = 進捗・ログ / exit 0・1・2 | `tests/integration/test_cli_contract.py`（531 行） | FR-030 / 原則 V |
| 5 | 7 ノード構成と `NODE_ORDER` の一致 | `tests/unit/test_progress.py`、`tests/integration/test_graph_wiring.py` | FR-031 / 原則 V |
| 6 | `report.notes` の既存要素（`スレッド取得に失敗しました（本文のみで解析）` 等） | `tests/integration/test_full_flow.py:443` | FR-034 |

**唯一許される追加観測は `ProgressEmitter.note()`**（stderr のみ。状態 `messages` へ積まない）。

## 9. 検証（この契約を固定するテスト）

| テスト | 何を固定するか |
|---|---|
| `tests/unit/test_llm.py`（拡張） | 再試行 3 回 → フォールバック、待機回数、`usage` の記録、構造化出力の `method` |
| `tests/unit/test_degradation.py`（新規） | 検出器の 4 条件（反例を含む）、縮小の段数・停止条件、未知モデルの縮退 |
| `tests/unit/test_compression.py`（新規） | しきい値超過で 1 回だけ呼ぶ、失敗時の復帰、出力がしきい値以下 |
| `tests/unit/test_parse_instruction.py`（拡張） | 構造化出力の正常系、フォールバック、`ResearchInstruction` の中身の一致 |
| `tests/unit/test_analyze_content.py`（拡張） | 部分失敗の隔離（1 件失敗で他が継続）、`failures` の記録 |
| `tests/unit/test_configuration.py`（拡張） | 値域の宣言、`ConfigurationError` のメッセージ、`model_fields_set` の維持 |
| `tests/integration/test_cli_contract.py`（拡張） | 値域外で exit 2、既定で追加ファイルなし、進捗・レポートの不変 |

**変異探針（各テストが欠陥を検出することを確認する）**:

| 変異 | 期待 |
|---|---|
| `return_exceptions=True` を外す | 部分失敗のテストが落ちる |
| 縮小率を `1.0` にする | 縮退のテストが落ちる |
| 検出器の条件 4（除外）を削る | `invalid model` の反例テストが落ちる |
| 再試行の待機を削る | 待機回数のテストが落ちる |
| 圧縮の分岐を `pass` にする | 圧縮のテストが落ちる |
| `usage` の reducer を外す | 使用量の集約テストが落ちる |
