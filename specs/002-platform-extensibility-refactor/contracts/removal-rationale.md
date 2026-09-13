# Contract: 削除の根拠（削除対象の一覧と判断理由）

**Feature**: `002-platform-extensibility-refactor` | **Date**: 2026-09-13

FR-008 / FR-010 / FR-019 / SC-005 / SC-008 の証跡。各項目に **(a) 実行時の参照件数（実測）**、
**(b) 削除理由**、**(c) 同一変更で更新する参照**、**(d) 更新したテストの「何を固定していたか」**を
記す。(d) は FR-019 の要求であり、本節がその一覧である。

---

## REM-001: `cache.read_json`

| 項目 | 内容 |
|---|---|
| 位置 | `src/trend_researcher/cache.py:28` |
| (a) 参照 | `src/` から **0**。`tests/unit/test_cache.py` の 5 件のみ |
| (b) 理由 | docstring に「将来の途中再開等に備えて用意」とある**予約**実装。途中再開の仕組みは存在せず、ペアになる呼び出し元もない。FR-008（「将来使うかもしれない」を理由に残さない）と FR-010（テストのみの補助機能）に該当 |
| (c) 更新 | `tests/unit/test_cache.py` の当該節（`write_json` の節は維持） |
| (d) 固定していたもの | 「JSON を書き出したものを読み戻すと同値になる」という往復の性質。**観測可能な契約ではない**（CLI もパイプラインも読み戻さない）。`write_json` の出力形式は別の節が固定しており、失われる網羅はない |

---

## REM-002: `prompts.COMPILE_REPORT_PROMPT`

| 項目 | 内容 |
|---|---|
| 位置 | `src/trend_researcher/prompts.py:175` |
| (a) 参照 | **0**（`src/`・`tests/` の双方） |
| (b) 理由 | 参照 0 のメッセージ定数（FR-008）。コンパイル段階のプロンプトはプラットフォーム別の 4 種が使われており、本定数は使われない |
| (c) 更新 | なし |
| (d) 固定していたもの | なし（テストからの参照も 0） |

---

## REM-003: `--trends` 一式

| 項目 | 内容 |
|---|---|
| 位置 | `__main__.py:50`（フラグ定義）、`__main__.py:80`（受け渡し）、`Configuration.use_trends`、`ResearchInstruction.use_trends`（`models.py:38`）、`AgentState.use_trends`（`state.py:62`）、`parse_instruction.py:191` |
| (a) 参照 | 実行時 0。値は `report` まで運ばれるが、分岐に寄与しない。ただし `ResearchInstruction` として **JSON レポートに現れる**（下欄参照） |
| (b) 理由 | 「予約。現在は通常検索と同じ」という**効果のない予約機構**（FR-009）。互換のための予約は将来の判断を曖昧にする |
| (c) 更新 | `README.md:168`、argparse のヘルプ、`tests/unit/test_configuration.py`（`DEFAULTS`）、`tests/unit/test_parse_instruction.py`（該当節）、`tests/integration/test_cli_contract.py`（`--trends` の受理）、`specs/001-test-suite-hardening/contracts/cli-contract.md:128` |
| (d) 固定していたもの | 「`--trends` を受理し、既定で True になる」という**オプションの受理**。これは利用者可視の契約だが、**挙動を持たない**ため FR-009 が削除を MUST としており、更新対象は内部構造の固定として扱う。終了コード・stdout/stderr の分離・レポート形式の断言は維持する |
| (e) JSON への影響 | `render_json` は `report.model_dump_json(...)` を返すため、`ResearchInstruction.use_trends` が**JSON 出力から消える**。これは削除に必然的に伴う**意図的な差分**であり、RND-003 のとおり比較時に当該キーを除外する（`spec.md` の SC-006 の文言は変更しない） |
| 更新しない参照 | `specs/001-test-suite-hardening/` の `plan.md` / `tasks.md` / `research.md` / `data-model.md` / `quickstart.md`（完了済み機能の履歴） |

---

## REM-004: `OutputSpec.table_for`

| 項目 | 内容 |
|---|---|
| 位置 | `src/trend_researcher/models.py:25` |
| (a) 参照 | **0** |
| (b) 理由 | 参照 0 のモデル項目（FR-008）。表の特定は provider の `candidate_table_header` と `render_candidate_row` が担っている |
| (c) 更新 | `tests/unit/test_models.py`（該当があれば削除） |
| (d) 固定していたもの | 該当テストがある場合のみ「既定値の存在」。観測可能な契約ではない |
| (e) JSON への影響 | `OutputSpec` は `ResearchInstruction.output` として JSON に含まれるため、`table_for` が**JSON 出力から消える**（`"table_for": ["common_points"]`）。REM-003 と同じく RND-003 の意図的な差分として扱い、比較時に除外する |

---

## REM-005: `tools/x_search.fetch_thread`

| 項目 | 内容 |
|---|---|
| 位置 | `src/trend_researcher/tools/x_search.py:165` |
| (a) 参照 | `src/` から **0**。`tests/unit/test_x_search.py` の 11 件のみ。実際の取得は `fetch_threads`（`:174`）が `_fetch_threads_async` を直接使う |
| (b) 理由 | テストのみから参照される補助機能（FR-010）。`fetch_threads` が同等以上の機能を提供している |
| (c) 更新 | `tests/unit/test_x_search.py` の `fetch_thread` の節（`fetch_threads` の節は維持） |
| (d) 固定していたもの | 「1 件取得時にスレッド本文を連結する」という単体の性質。同等の性質は `fetch_threads` の節（複数件・リトライ・並列）が**同じ経路**を通って固定している。失われるのは 1 件時のみの入力差で、`fetch_threads` の節に 1 件のケースを足して補う（テストの削除と同時に 1 件のケースを移す） |

---

## REM-006: `Config`

| 項目 | 内容 |
|---|---|
| 位置 | `src/trend_researcher/config.py` の `Config` クラス |
| (a) 参照 | `src/` の 9 ファイル（`__init__.py` / `__main__.py` / `nodes/search.py` / `nodes/fetch.py` / `graph.py` ほか）。ただしこれは「実行時の参照が 0」ではなく**重複定義**として扱う |
| (b) 理由 | `Configuration` と 7 項目（`platform` / `max_results` / `sort_by` / `transcript_language` / `cache_dir` / `use_trends` / `published_after`）が重複（FR-013）。clarify Q4 の回答により `Configuration` を残す |
| (c) 更新 | `__init__.py` の `__all__`、`__main__.py`、`nodes/search.py`、`nodes/fetch.py`、`tests/unit/test_config.py`、`tests/integration/test_full_flow.py`、`README.md` |
| (d) 固定していたもの | `tests/unit/test_config.py` は「`TR_*` > `XTR_*`/`YTR_*` > 既定」の**解決結果**（観測可能な契約）を固定している。**期待値は書き換えず**、対象を `Configuration.load()` に替える。`XTR_*` / `YTR_*` の節は provider の固有設定の解決へ移す（X は `XSettings`） |
| 削除の一部として扱う項目 | `Config.openai_api_key` / `openai_base_url` / `model`（`src/` からの参照 0。実測）。`Config` の削除に含める |

---

## REM-007: `get_config()`（`@lru_cache`）

| 項目 | 内容 |
|---|---|
| 位置 | `src/trend_researcher/config.py` の `get_config()` |
| (a) 参照 | `src/` から **0**。`tests/unit/test_config.py` と `tests/integration/test_full_flow.py` が `cache_clear()` を呼ぶのみ |
| (b) 理由 | プロセス内共有（キャッシュ）のためだけに存在する。ノードは `RunnableConfig` 経由で設定を受け取る（FR-014）ため不要 |
| (c) 更新 | 上記 2 テストの `cache_clear()` の呼び出し |
| (d) 固定していたもの | 「同一引数で同一インスタンスを返す」という**内部の同一性**。観測可能な契約ではない（値の同一性は `Configuration.load()` の結果比較で代替できる）。`TR_*` の解決結果の断言は維持する |

---

## REM-008: 進捗の手書き番号と `TOTAL`

| 項目 | 内容 |
|---|---|
| 位置 | `progress.py:18` の `TOTAL = 7` と、7 ノードが `emit()` に渡す番号 `1`〜`7` |
| (a) 参照 | 全ノードが番号を渡す。`TOTAL` は `make_emitter()` のみ |
| (b) 理由 | 同じ事実（ノードの順序と総数）を 2 箇所が別々に持つ二重管理（FR-012） |
| (c) 更新 | `tests/unit/test_progress.py`、7 ノードの呼び出し |
| (d) 固定していたもの | 「`[i/7] name ... phase」という**進捗行の書式と行数**。これは観測可能な契約であり**維持する**（RND-006）。変更するのは引数の形のみ |

---

## REM-009: `nodes/compile_report.py` の整形関数群

| 項目 | 内容 |
|---|---|
| 位置 | `nodes/compile_report.py` の `render_markdown` / `render_json` / `render_report` / `_render_candidates_table` / `_render_analysis_block` / `_render_common_themes`（約 120 行） |
| (a) 参照 | `graph.py:69`（`render_report`）、`__main__.py`（CLI 出力）、`tests/unit/test_compile_report.py` |
| (b) 理由 | 描画がノードの実行から分離されていない（FR-016）。骨格（`graph.py`）が描画を参照しているため、描画だけを直しても回帰範囲が読めない |
| (c) 更新 | `rendering.py` へ移設。`graph.py` から参照を削除。`tests/unit/test_compile_report.py` の描画節を `tests/unit/test_rendering.py` へ移す |
| (d) 固定していたもの | 「レポートの Markdown / JSON の内容」という**観測可能な契約**。**削除ではなく移動**であり、期待値は書き換えない（golden で byte 一致を固定。RND-003） |

---

## 削除しない項目（誤って削除しないための記録）

| 項目 | 理由 |
|---|---|
| `providers/__init__.py` の登録辞書 2 行 | 走査テストの許容リスト。プラットフォーム追加の拡張点そのもの |
| `tools/x_search.py` / `tools/youtube_search.py` / `tools/transcript.py` のプラットフォーム名 | 固有の外部境界。走査の除外集合 |
| `prompts.py` のプロンプト本文 | データ（分岐を持たない）。R-11 |
| `progress.py` の `NODE_ORDER` / `NODE_*` 定数 | 単一の順序定義。R-7 |
| `cache.write_json` | 実行時に使われている（`compile_report`） |
| `tests/unit/test_providers.py` の `_PROVIDERS` の import | 登録の契約を固定する正当な参照 |
