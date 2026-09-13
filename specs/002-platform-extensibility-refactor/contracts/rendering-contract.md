# Contract: レポート描画の分離

**Feature**: `002-platform-extensibility-refactor` | **Date**: 2026-09-13

「描画をパイプラインの進行から独立して変更・検証できる」ことを、依存の向きと出力の不変性で固定する。

---

## RND-001: 依存の向き

| 許可される依存 | 内容 |
|---|---|
| `rendering.py` → `providers/base.py` | `Provider` Protocol の型（実行時の解決はしない） |
| `rendering.py` → `models.py` / `state.py` | `ResearchReport` などの型 |
| `nodes/compile_report.py` → `rendering.py` | チャット表示用メッセージの本文を作るため |
| `__main__.py` → `rendering.py` | CLI の出力 |
| **禁止** | `graph.py` → `rendering.py`（FR-016） |
| **禁止** | `rendering.py` → `providers/__init__.py` の `get_provider`（FR-017） |
| **禁止** | `rendering.py` → `tools/**`（外部 I/O を行わない。憲法 II） |

**検証**: `tests/unit/test_rendering.py` の 1 件目で、`graph.py` のソースに `rendering` の
文字列が現れないことを AST 走査で確認する。

---

## RND-002: 描画の入口

| 関数 | シグネチャ | 用途 |
|---|---|---|
| `render_markdown` | `(report: ResearchReport, provider: Provider) -> str` | 本文の Markdown |
| `render_json` | `(report: ResearchReport) -> str` | `--output` と `cache.write_json` の入力。**provider を取らない**（JSON は `report.model_dump_json` であり、プラットフォーム依存の文言を含まないため。不要な引数を増やさない） |
| `render_report` | `(report: ResearchReport, provider: Provider) -> str` | `__init__.py` の re-export。`instruction.output.format == "json"` なら `render_json(report)`、それ以外は `render_markdown(report, provider)` |

- **provider を取る入口は `render_markdown` と `render_report`**（両方とも必須引数。省略・`None` を許さない）。
- `render_json` のシグネチャは**変更しない**（現行どおり `render_json(report)`）。
- 内部で `get_provider()` を呼ばない。`report.instruction.platform` から解決し直さない（FR-017）。
- `graph.py` は `render_report` の再エクスポートを行わない（`__init__.py` が担う）。

---

## RND-003: 出力の不変性（SC-006 / FR-018）

| 契約 | 内容 |
|---|---|
| Markdown | 分離前と **byte 一致**（末尾の改行の有無を含む） |
| JSON | **2 つの削除対象フィールドを除いて** byte 一致（キー順を含む） |
| JSON の意図的な差分 | `render_json` は `report.model_dump_json(indent=2, exclude_none=True)` であり、`ResearchInstruction.use_trends`（REM-003 / FR-009）と `OutputSpec.table_for`（REM-004 / FR-008）が**必ず消える**。この 2 キーの消失は削除要件に伴う**意図的な差分**であり、SC-006 の対象外として扱う（Markdown 側には現れないため影響なし） |
| 比較の実装 | golden の JSON と比較する際、両側で当該 2 キーを除去（または `pytest` の差分表示から除外）してから比較する。**他のキーの差分は失敗として扱う** |
| golden の採取 | **変更前の `src/` に対して**行い、`tests/unit/golden/` に保存する（手順は `quickstart.md` 手順 4）。golden 自体は削除対象キーを含む元の出力を保持する |
| 代表入力 | 3 件: (1) X の完全形、(2) YouTube の完全形、(3) 欠落形（文脈・分析・共通テーマが空）。**3 件すべてで `platform` / `output.format` などの既定依存値を明示する**（US1 で `platform` の既定が `"x"` → `""` に変わるため、既定に依存させない） |
| 違反時 | テストではなく**実装**を直す（意図的な 2 キー以外の出力変更は本機能の範囲外） |

---

## RND-004: 分岐の保持

分離の前後で、次の分岐の意味を変えない（data-model.md 3 章の構造を維持する）。

| 分岐 | 条件 | 変わらない出力 |
|---|---|---|
| 候補なし | `candidates` が空 | 「該当なし」の行 |
| 表の有無 | 候補が 1 件以上 | ヘッダ + 各行 |
| 詳細ブロックの本文 | 文脈／分析がある | 引用行 + 本文 |
| 要約の有無 | `summary` が空 | 見出しのみ |
| アイデアの有無 | `ideas` が空 | 節を出さない |
| 共通テーマ | `themes` が空 | 節を出さない |
| プラットフォーム依存の文言 | 名詞・表題・注記・根拠ラベル | `provider` のフックから取得 |

**検証**: golden 3 件（完全形 2 + 欠落形 1）で分岐を代表させる。

---

## RND-005: ノードの責務

| `nodes/compile_report.py` が行うこと | 行わないこと |
|---|---|
| `report` の組み立てと状態への格納 | Markdown の文字列組み立て |
| `cache.write_json(Path(cache_dir), "report", report)` | 表・見出し・注記の文言の決定 |
| チャット表示用メッセージ用に `render_markdown(report, provider)` を呼ぶ | `get_provider` の再解決 |
| `provider` を `get_provider(platform)` で **1 回だけ**解決する | 描画の内部での再解決 |

- `compile_report` は provider を解決し、その provider を描画へ渡す（同一の値）。
- 進捗の emit は RND-006 の形式で行う。

---

## RND-006: 進捗表示の不変（FR-012 / 憲法 V）

| 契約 | 内容 |
|---|---|
| 行の書式 | `[i/total] <node_name> ... <phase>（<detail>）`（全角括弧。detail は任意） |
| 行数 | 7 行（7 ノード） |
| 番号 | `NODE_ORDER.index(node_name) + 1` から導出 |
| 総数 | `len(NODE_ORDER)` から導出（`TOTAL = 7` の手書きを廃止） |
| 出力先 | stderr（stdout はレポートのみ。憲法 V） |
| テスト用の上書き | `total` の上書きが引き続き可能であること（既存テストの互換） |
| 検証 | `tests/unit/test_progress.py` と `tests/integration/test_full_flow.py` |

---

## RND-007: 検証可能性（US4 / Acceptance Scenario 1）

| 契約 | 内容 |
|---|---|
| ノード実行を伴わない検証 | `tests/unit/test_rendering.py` が `ResearchReport` を直接組み立てて描画を呼ぶ（LangGraph・LLM・境界モックを使わない） |
| 引数の使用の検証 | `render_markdown(report, provider)` に**レポートと異なるプラットフォームの provider** を渡すテストを置き、出力が**渡された provider** のフック（名詞・表題・注記）を使うことを確認する（FR-017 の検証。現行実装は引数を無視するため、このテストは実装前は赤になる） |
| 骨格の非依存 | `graph.py` のソースに `rendering` が現れないことを AST 走査で確認する（FR-016 の検証） |
| 実行時間 | 描画テストは 1 秒未満（SC-010 の予算内） |
| 独立性 | `rendering.py` のテストが `conftest.py` の境界モックに依存しない |
