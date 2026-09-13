# Implementation Plan: 新しいプラットフォームを追加しやすくするリファクタリング

**Branch**: `002-platform-extensibility-refactor` | **Date**: 2026-09-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-platform-extensibility-refactor/spec.md`

## Summary

プラットフォーム（X / YouTube）の差がコアに漏れている **15 箇所**（実測。走査テストの検出器では 16 行。
差分は後述「基準値のずれ」）を `providers/` のフックへ移し、実行時の参照が 0 の **5 件**を削除し、
実行時設定を **1 つの型**に集約し、レポート描画をノードから分離する。
観測可能な挙動（CLI の出力契約・レポート出力・進捗表示）は変更しない。

作業は 4 本の柱に分かれる。

1. **拡張点の確立**（原則 IV / FR-001〜FR-007）。追加するフックは 5 つで、いずれも現在コアに
   ハードコードされている差の移設先である。
   - `Provider.max_search_queries: int | None` … クエリ本数の上限（X: 8 / YouTube: 制限なし）
   - `Provider.selection_note(sort_by) -> str` … 選定基準の注記（`nodes/compile_report.py:37`）
   - `Provider.content_noun: str` … 「ツイート」「動画」の名詞（`compile_report.py:45` / `__main__.py:148`）
   - `Provider.candidates_section_title: str` … 選定リストの見出し（`compile_report.py:85`）
   - `Provider.env_prefix: str` … 固有の環境変数プレフィックス（`XTR` / `YTR`）+ 固有設定の解決
     （`accounts_db` / `search_pool_size` / `max_retries` は X 側で解決する）
2. **不要物と重複の除去**（FR-008〜FR-012）。`cache.read_json` / `prompts.COMPILE_REPORT_PROMPT` /
   `--trends` 一式 / `OutputSpec.table_for` / `tools.x_search.fetch_thread` を削除する。進捗は
   `NODE_ORDER` から番号と総数を導出し、手書きの `1`〜`7` と `TOTAL = 7` の二重管理を解消する。
3. **設定の一元化**（FR-013〜FR-015）。`Config` を削除し、`Configuration` を唯一の実行時設定型にする。
   環境変数・`.env` の解決は `Configuration.load()` に移し、プラットフォーム固有の解決は
   provider が自分の `env_prefix` で行う（FR-003 と FR-013 の整合は research.md R-4 で確定）。
   ノードは `Config.load()` を呼ばなくなる（SC-004: 2 ノード → 0）。
4. **描画の分離**（FR-016〜FR-018）。`nodes/compile_report.py` から整形処理（約 120 行）を
   新モジュール `rendering.py` へ移し、`graph.py` から描画への参照を外す。描画は受け取った
   provider を使い、内部で解決し直さない（現行の「引数を捨てて解決し直す」不具合の解消）。

検証は 3 つのテストで機械的に判定する（FR-025）。

- **走査テスト**（新規 `tests/unit/test_platform_scan.py`）: コアのソースを行単位で走査し、
  プラットフォーム名のリテラル・env プレフィックスを検出する。許容リストは登録の定義の
  2 行のみ（`providers/__init__.py` の登録辞書）。実測（2026-09-13）で現行は **16 行**、
  目標は **2 行**。
- **拡張テスト**（新規 `tests/unit/test_platform_extension.py`）: 試験用プラットフォームを
  登録辞書へ追加し、コアを編集せずにグラフが完走してレポートが生成されることを固定する。
- **出力一致テスト**（新規 `tests/unit/test_rendering.py`）: 代表入力の Markdown / JSON を
  **変更前に golden として採取**し、分離の前後で byte 一致することを固定する（SC-006）。

## Technical Context

**Language/Version**: Python 3.11（`requires-python = ">=3.11"`、実測 3.11.15）

**Primary Dependencies**: 既存の実行時依存（LangGraph / LangChain / `langchain-openai` / `twscrape` /
`yt-dlp` / Pydantic v2 / `python-dotenv`）を**変更しない**（FR-024）。開発時依存も追加しない。

**Storage**: 変更なし。中間成果物は `cache/` 配下の JSON のみ（書き込み専用のまま。読み戻しの
実装は行わない）。

**Testing**: `pytest`（既存）。層は `tests/unit/` と `tests/integration/` の 2 層のまま。新規テストは
`tests/unit/` に置く（境界モックと LLM フェイクは既存の `tests/conftest.py` のフィクスチャを使う）。

**Target Platform**: Linux（開発機）。テストはプロセス内で完結し、OS 依存の機能を追加しない。

**Project Type**: 単一プロジェクト（CLI ツール + ライブラリ）。`src/` レイアウト、hatchling ビルド。

**Performance Goals**: テストスイート全体が **60 秒以内**（SC-010）。**現行の実測は 49.7 秒
（547 passed / カバレッジ 95.29%）であり、増加に使える余地は約 10 秒しかない。** 判定コマンドは
`uv run pytest -q`（カバレッジ計測込み）に固定する（`--no-cov` は遅いテストの把握用であり、
60 秒の判定には使わない）。新規 3 テストは
この範囲に収まるよう、走査テストはファイル読みのみ（ネットワーク・LLM なし）、拡張テストは
既存の境界モック 1 回、出力一致テストは固定入力の描画のみとする。

**Constraints**:
- ネットワーク接続と実認証情報なしで全件完走する（FR-023 / 憲法 II）。
- 新規の実行時依存を追加しない（FR-024）。
- **観測可能な挙動を変えない**（本機能の最優先事項）。具体的には stdout = レポートのみ、
  stderr = 進捗・ログ・エラー、終了コード 0 / 1 / 2、レポートの Markdown / JSON の byte 一致、
  進捗行の形式と行数。
- `state.py` / `models.py` / `Configuration` の変更は同一変更内で全参照（ノード・provider・
  レンダラ・テスト・README）へ波及させる（憲法 III）。
- 内部 API の後方互換は要求しない（FR-020 / 憲法 VI）。旧名の別名・互換シムを残さない。
- 1 回の実行で対象とするプラットフォームは 1 つ（FR-026）。集合を扱う抽象を導入しない。
- 語は既存の「プラットフォーム」で統一し、識別子（`--platform` / `TR_*` / `XTR_*` / `YTR_*` /
  フィールド名 / モジュール名）を改名しない（FR-027）。
- カバレッジは `fail_under = 90` を維持する。削除対象のテストを消すことで行数が減るため、
  未実行行が残らないよう削除と同時にテストを整理する。

**Scale/Scope**:
- 対象ソース: 26 ファイル / 2,541 行（`src/trend_researcher/`、実測）。
- 変更見込み: 15 箇所の分岐除去、5 件 + `Config` 一式 + `get_config` の削除、設定型の 1 本化、
  描画の分離（新モジュール 1・新規テスト 3）。
- テスト規模: 547 passed を基準とする。移行対象（`tests/unit/test_config.py` 307 行 /
  `tests/unit/test_configuration.py` / `tests/unit/test_progress.py` / `tests/unit/test_cache.py` の
  `read_json` 節 / `tests/unit/test_x_search.py` の `fetch_thread` 節 / `tests/integration/test_full_flow.py`）は
  期待値を維持したまま対象を差し替える。詳細は `data-model.md` 4 節。
- 最も注意を要する箇所: `src/trend_researcher/__main__.py`（カバレッジ 46%、48 行未実行）。
  CLI 契約を固定する `tests/integration/test_cli_contract.py` が唯一の安全網であり、変更後も
  green であることを各段階で確認する。

## 基準値のずれ（実測 2026-09-13）

spec の「15 箇所」は文（statement）単位の集計であり、走査テストの検出器は行単位のため **16 行**を
検出する。差の 1 件は `config.py:57` の引数既定値（`Config.load(platform: str = "x")`）で、
spec の内訳では「設定解決 1」（`config.py:71`）のみが数えられている。

| ファイル（検出器の実測） | 検出行数 | spec の内訳との対応 |
|---|---|---|
| `state.py` | 2 | 状態定義 2 |
| `configuration.py` | 1 | 既定値 3 のうち 1 |
| `models.py` | 2 | 既定値 3 のうち 2 |
| `config.py` | 2 | 設定解決 1 + 引数既定値 1（**spec の集計外**） |
| `tools/llm.py` | 1 | LLM 構築 1 |
| `providers/__init__.py` | 2 | 登録 2（許容リスト） |
| `nodes/compile_report.py` | 3 | レポート文言 3 |
| `nodes/plan_search.py` | 2 | 検索ポリシー 2 |
| `__main__.py` | 1 | CLI 文言 1 |
| **計** | **16** | 文単位では 15 |

SC-002 の判定は**終状態**（検出が許容リストの 2 行のみ）で行う。基準値の 15 と検出器の 16 の差は
`tasks.md` の実装メモに記録し、spec 側の数値は変更しない。

### 設定の重複項目数（spec は「7 項目」、実測は「3 フィールド + 引数 1」）

spec の現状分析は「`Config` と `Configuration` が 7 項目を重複定義している」と記すが、
両クラスのフィールド定義を直接読んだ実測は次のとおりで、**同名で重複しているのは 3 フィールド**である。

| 分類 | 実際の項目 | 件数 |
|---|---|---|
| 同名で重複（フィールド） | `max_results` / `transcript_language` / `cache_dir` | 3 |
| 同名で重複（フィールドと引数） | `platform`（`Configuration.platform` と `Config.load(platform=...)`） | 1 |
| `Config` のみ | `openai_api_key` / `openai_base_url` / `model` / `search_pool_size` / `accounts_db` / `max_retries` | 6 |
| `Configuration` のみ | `output_format` / `sort_by` / `use_trends` / `published_after` | 4 |

SC-003 の判定は**終状態**（同名項目の定義箇所が 1 つ）で行うため、この差は合否に影響しない。
spec 側の数値は変更せず、本節と `tasks.md` の実装メモに記録する。

### レポート出力一致（SC-006）の適用範囲

SC-006 / FR-018 は「代表入力に対するレポート出力（Markdown と JSON の両方）が変更前と完全に一致」
を要求する。しかし `render_json` は `report.model_dump_json(indent=2, exclude_none=True)` を返すため、
FR-008（`OutputSpec.table_for`）と FR-009（`ResearchInstruction.use_trends`）の削除に伴い
**JSON の 2 キーが必ず消える**。これは削除要件の帰結であり、両立しない要求である。

| 項目 | spec の記述 | 実測による帰結 | 対応 |
|---|---|---|---|
| JSON の出力 | 「変更前と完全に一致」 | `use_trends` / `table_for` の 2 キーが消える | **Markdown は byte 一致を維持**し、JSON は当該 2 キーのみ除外して比較する（RND-003）。意図的な差分として `removal-rationale.md` REM-003 / REM-004 に記録し、spec 側の文言は変更しない |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md`（Version 1.2.0）の各ゲートに対する判定。**すべて PASS**（違反 0 件、
Complexity Tracking への追加も 0 件）。

- [x] **I. テスト必須（NON-NEGOTIABLE）**: **PASS**。4 つのユーザーストーリーすべてに、そのストーリー
      単体で検証できるテストを置く（US1 = 走査テスト + 拡張テスト、US2 = 削除後の参照 0 を確かめる
      テストと CLI 契約テスト、US3 = `Configuration.load()` の優先順位テスト、US4 = golden 比較）。
      憲法が定義する「無効なテスト」（対象の挙動を削っても緑のままのテスト）を避けるため、走査テストと
      拡張テストには**変異探針**を必須とする（コアに `platform == "x"` を一時挿入 → 走査テストが落ちる。
      試験用プラットフォームのフックを削ってノードへ分岐を戻す → 拡張テストが落ちる）。
- [x] **II. 外部 I/O の境界分離とオフラインテスト**: **PASS**。外部 SDK は `tools/` と `providers/` の
      内側に留まる。プラットフォーム固有の環境変数の解決は provider 自身が行い（FR-003）、境界の外へ
      出ない。テストは既存の境界モック（`tests/conftest.py`）で `tools/` / `providers/` を差し替え、
      ネットワーク・認証情報を要求しない。新規依存は 0（FR-024）。
- [x] **III. 型付きパイプライン契約**: **PASS**（本機能で最も注意を要するゲート）。`state.py` の
      `platform: Literal[...]` を `str` に、`models.py` の `platform` / `use_trends` / `table_for` を
      変更・削除し、`Configuration` のフィールドを再編する。変更は**同一変更内**で全参照（7 ノード・
      2 provider・レンダラ・CLI・README・テスト）へ波及させる。生の dict を新設しない。
      実行時設定は引き続き `RunnableConfig` 経由で受け渡し、provider を State に持たせない
      （現行どおり `get_provider()` を各ノードで解決する）。
- [x] **IV. プラットフォーム抽象**: **PASS**。`graph.py` / `nodes/` に新しい `platform == ...` 分岐を
      **追加しない**（既存の分岐を 0 にする）。追加するのは provider のフックのみで、登録は
      `providers/__init__.py` の辞書と provider 単体テストで完結する（FR-001 / FR-005）。
      provider プロトコルを Protocol のまま維持し、継承を強制しない。
- [x] **V. CLI 出力契約と観測可能性**: **PASS**。stdout = レポートのみ / stderr = 進捗・ログ・エラー /
      終了コード 0・1・2 を変更しない（SC-007。`tests/integration/test_cli_contract.py` が固定）。
      `ProgressEmitter` は維持し、出力行の形式 `[i/total] name ... phase（detail）` と行数も維持する
      （変えるのは番号の与え方だけ。FR-012）。`cache/` の書き込み契約も維持する。
      例外は 1 点だけで、これは利用者可視の契約の削除である: `--trends` を削除し、README とヘルプを
      同一変更で更新する（FR-009）。**改正対象が 1 つある**: 原則 V の「`NODE_ORDER`・
      `ProgressEmitter.TOTAL`・グラフのノード数の一致を保つ MUST」は `TOTAL = 7` の維持を要求して
      おり、FR-012（総数と表示番号を単一の定義から導出 MUST）と両立しない。観測可能な契約
      （進捗行の形式と行数）は不変のため**本ゲートは PASS のままとし、原則 V の当該節を
      `tasks.md` T065 で「総数と表示番号は単一の定義（`NODE_ORDER`）から導出する MUST」へ
      PATCH 改正する**（research.md R-12 #2）。
- [x] **VI. リファクタリングは後方互換を要求しない**: **PASS**。`Config` / `get_config` / 未使用 5 件 /
      `--trends` 一式を削除し、旧名の別名・互換シムを**残さない**（FR-020）。全参照（実装・テスト・
      README・`specs/001-test-suite-hardening/contracts/cli-contract.md`）を同一変更で更新する。
      正しさは互換層ではなくテストで担保する（振る舞いを固定するテストは期待値を書き換えない）。
- [x] **技術制約・品質ゲート**: **PASS**。`tasks.md` に `uv run pytest -q` / `uv run ruff check .` /
      `uv run mypy src` を最終タスクとして置く。実測ベースラインは **547 passed / カバレッジ 95.29% /
      ruff 0 / mypy 0**（2026-09-13）であり、移行措置は終了済みのため**リポジトリ全体で green を維持**する
      （部分適用・`# noqa` の追加は行わない）。**改正対象が 1 つある**: 「技術制約と品質基準」の
      「実行条件は `.env` と `Config` から供給し」は FR-013 が削除する `Config` を指す。方針
      （環境変数と `.env` から供給し、コードにハードコードしない）は不変のため**本ゲートは PASS の
      ままとし、`tasks.md` T065 で `Configuration` へ読み替える**（research.md R-12 #3）。

**ゲート判定の根拠となる実測**（すべて 2026-09-13、リポジトリ内で実行）:

| 実測項目 | 結果 |
|---|---|
| テストスイート | 547 passed / 49.67 秒（カバレッジ計測込み） |
| カバレッジ | 95.29%（`fail_under = 90` を満たす）。とくに薄いのは `__main__.py` 46%（48 行未実行）、`providers/base.py` 69%（Protocol の `...` 本体） |
| `ruff check .` | 0 件 |
| `mypy src` | 0 件（26 ファイル） |
| 走査テストの検出器（現行ツリー） | 16 行（内訳は前節の表） |
| 走査テストの検出器（許容リスト） | `providers/__init__.py:11-12` の 2 行 |

### Phase 1 設計後の再評価（2026-09-13）

Phase 1 の成果物（`data-model.md` / `contracts/` 4 件 / `quickstart.md`）を踏まえて再判定し、
**すべて PASS を維持**する。設計が憲法に与える影響は次のとおりで、いずれも新しい違反を生まない。

- `contracts/platform-extensibility-contract.md` はゲート IV を契約表として固定する（走査ルール・
  許容リスト・拡張手順）。新しい分岐を許可する条項はない。
- `contracts/settings-contract.md` はゲート III の対象（`Configuration` のフィールドと優先順位）を
  1 か所に固定する。Studio の設定契約（既存 8 フィールドの意味・既定値）は変更しない。
- `contracts/rendering-contract.md` はゲート V（出力の一致）と IV（描画は provider を受け取る）を固定する。
- `contracts/removal-rationale.md` はゲート VI の削除根拠を 1 件ずつ示す。
- プロンプト本文を `prompts.py`（データのみ）に残す判断は、ゲート IV の「差は providers に実装する」に
  抵触しない。差の**選択**は provider のプロパティが担っており、本文は分岐を持たないデータだからである
  （走査テストの対象外にする理由も契約に明記する。research.md R-11）。

### 憲法の改正要否（spec の保留事項への回答）

spec の Assumptions が計画時に判定するとした「原則 IV の射程拡大が憲法の改正を要するか」への回答は
**原則の追加・削除・再定義は不要**である。原則 IV は「コアはプラットフォーム非依存を維持する MUST」
「差は `providers/` に実装する MUST」「新プラットフォームは Provider の実装＋登録＋単体テストで
追加できる MUST」を要求しており、本計画はこれを**強化する方向**に進む（分岐を追加せず、削除する）。

改正（または読み替え）が必要な箇所は **3 点**である。いずれも方針の変更ではなく、本機能の完了に
伴う記載の追随（PATCH 相当）であり、**実装完了後に `/speckit.constitution` で PATCH 改正する**
タスク（`tasks.md` T065）にまとめる（改正手続きは憲法 Governance の MUST に従う）。

| # | 憲法の箇所 | 現行の記述 | 改正後 | 対応する要求 |
|---|---|---|---|---|
| 1 | 原則 IV | 「既存のプラットフォーム分岐（`nodes/compile_report.py` などに残存）は、そのファイルを変更する際に provider のフックへ寄せる SHOULD」 | 「コアにプラットフォーム名の列挙・比較を残してはならない MUST NOT」 | FR-001〜FR-004 / SC-002 |
| 2 | 原則 V | 「`NODE_ORDER`・**`ProgressEmitter.TOTAL`**・グラフのノード数の一致を保つ MUST」 | 「`NODE_ORDER` とグラフのノード数を一致させ、総数と表示番号は単一の定義（`NODE_ORDER`）から導出する MUST（手書きの定数を置かない）」 | FR-012（T035 で `TOTAL = 7` を削除する） |
| 3 | 技術制約と品質基準 | 「実行条件は `.env` と **`Config`** から供給し、コードにハードコードしてはならない MUST NOT」 | 「`.env` と **`Configuration`**（唯一の実行時設定型）から供給し」 | FR-013（T042 で `Config` を削除する） |

#2 と #3 は実装の完了によって憲法の記述の前提が消えるものであり、放置すると **FR-012 / FR-013 の
完了時点で憲法違反が確定する**（`plan.md` の Constitution Check には「改正対象」として記録した）。

**順序の制約**: 改正は US1〜US4 の実装完了後に行う（先に改正すると、残存分岐が実在する間は
改正後の記述が実態と食い違う）。ただし T035 / T042 は T065 と同一の変更一式として完了させ、
憲法と実装を同時に green にする（片方だけを適用した状態を残さない）。

Complexity Tracking に追加した項目は **0 件**。

## Project Structure

### Documentation (this feature)

```text
specs/002-platform-extensibility-refactor/
├── plan.md              # 本ファイル
├── research.md          # Phase 0: 設計判断（R-1〜R-12）と実測根拠
├── data-model.md        # Phase 1: 拡張点・設定・描画・走査・削除・移行の契約
├── quickstart.md        # Phase 1: 実行可能な検証手順
├── contracts/
│   ├── platform-extensibility-contract.md   # 拡張点と走査ルール
│   ├── settings-contract.md                 # 唯一の設定型と優先順位
│   ├── rendering-contract.md                # 描画インターフェースと出力一致
│   └── removal-rationale.md                 # 削除対象の根拠一覧
├── checklists/
│   └── requirements.md  # /speckit.specify の成果物
└── tasks.md             # Phase 2 の成果物（/speckit.tasks が生成）
```

### Source Code (repository root)

単一プロジェクト（`src/` レイアウト）。変更の全体像は次のとおりで、`[新]` は新規、`[削]` は削除を表す。

```text
src/trend_researcher/
├── __init__.py                # 公開 API の差し替え（Config → Configuration / render_report の取得元）
├── __main__.py                # --trends 削除、名詞を provider から取得
├── config.py                  # 環境変数・パスの解決だけを残す（Config クラス・get_config [削]）
├── configuration.py           # 唯一の実行時設定型。環境変数・.env の解決をここへ集約
├── graph.py                   # 骨格のみ。描画への参照を削除
├── models.py                  # platform のリテラル既定を廃止、use_trends [削]、table_for [削]
├── progress.py                # 番号と総数を NODE_ORDER から導出（TOTAL の手書きを廃止）
├── rendering.py               # [新] レポート描画（Markdown / JSON）
├── state.py                   # platform: str（Literal 廃止）、use_trends [削]
├── cache.py                   # read_json [削]
├── prompts.py                 # プロンプト本文のみ（データ。COMPILE_REPORT_PROMPT [削]）
├── nodes/
│   ├── parse_instruction.py   # use_trends の削除を追随（解釈のロジックは変更しない）
│   ├── plan_search.py         # 上限を provider.max_search_queries へ、platform のフォールバックを削除
│   ├── search.py              # Config.load を削除（provider が固有設定を解決）
│   ├── fetch.py               # Config.load を削除（同上）
│   ├── analyze_content.py     # 変更は進捗の呼び方のみ
│   ├── extract_common.py      # 変更は進捗の呼び方のみ
│   └── compile_report.py      # 整形を rendering.py へ、注記と表題を provider へ
├── providers/
│   ├── __init__.py            # 登録辞書（走査テストの許容リスト 2 行）+ エラー文言の生成
│   ├── base.py                # Protocol にフックを追加
│   ├── x.py                   # フック実装 + 固有設定の解決（env_prefix = "XTR"）
│   └── youtube.py             # フック実装（env_prefix = "YTR"）
└── tools/
    ├── llm.py                 # env_prefix 引数化（XTR_/YTR_ の直列を排除）
    ├── x_search.py            # fetch_thread [削]
    ├── youtube_search.py      # 変更なし（tool 層は境界として走査対象外）
    └── transcript.py          # 変更なし（同上）

tests/
├── conftest.py                # 既存の境界モック・フェイクをそのまま使う（変更は最小）
├── unit/
│   ├── golden/                      # [新] 代表入力 3 件の期待出力（.md / .json、変更前に採取）
│   ├── test_platform_scan.py        # [新] コアの走査（SC-002 / US1）
│   ├── test_platform_extension.py   # [新] 試験用プラットフォームの完走（SC-001 / US1）
│   ├── test_rendering.py            # [新] golden 比較（SC-006 / US4）。build_golden_cases() を内包
│   ├── test_config.py               # Configuration.load へ移行（期待値は維持）
│   ├── test_configuration.py        # use_trends の削除を追随
│   ├── test_progress.py             # emit の呼び方と単一の定義を固定
│   ├── test_cache.py                # read_json 節を削除
│   ├── test_x_search.py             # fetch_thread 節を削除、固有設定の解決を追加
│   ├── test_providers.py            # フックの契約を追加
│   └── test_compile_report.py       # 描画の呼び出しを追随
└── integration/
    ├── test_cli_contract.py         # --trends の削除を追随
    └── test_full_flow.py            # Config / get_config の参照を追随
```

**Structure Decision**: 単一プロジェクト・`src/` レイアウトを維持し、新しいモジュールは `rendering.py`
の 1 つだけとする（新しいパッケージを作らない。YAGNI）。`providers/` の下に `registry.py` を新設する案は、
登録箇所が動くと憲法 IV の記載（`providers/__init__.py` への登録）と走査テストの許容リストが二重に
変わるため採らない（research.md R-2）。

### Phase 0 / Phase 1 の成果物

| 成果物 | 主な確定事項 |
|---|---|
| `research.md` | R-1〜R-12（フック設計・登録方式・走査ルール・設定の整合・移行・削除・原則 IV） |
| `data-model.md` | 拡張点の表・設定の再配置表・描画契約・走査ルール・削除一覧・移行対象テスト一覧 |
| `contracts/platform-extensibility-contract.md` | EXT-001〜EXT-010 |
| `contracts/settings-contract.md` | SET-001〜SET-012 |
| `contracts/rendering-contract.md` | RND-001〜RND-007 |
| `contracts/removal-rationale.md` | REM-001〜REM-009 |
| `quickstart.md` | 検証手順 1〜7（基準値の取得・走査・拡張・golden・契約・ゲート） |

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

憲法ゲートに対する違反は **0 件** であり、正当化を要する複雑性の追加はない。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （なし） | — | — |

設計上の解釈が 1 点だけあるため、正当化ではなく**解釈の記録**として残す。

| 論点 | 解釈 | 根拠 |
|------|------|------|
| FR-013（環境変数の解決を唯一の型へ集約する MUST）と FR-003（プラットフォーム固有設定は provider が解決する MUST）の両立 | `TR_*` の解決は `Configuration.load()` に集約し、プラットフォーム固有の `XTR_*` / `YTR_*` は provider が自分の `env_prefix` で解決する | 2 つの MUST は対象が違う（共通設定と固有設定）。両方を 1 か所に寄せると、設定解決の側にプラットフォーム名の分岐が必要になり FR-003 と SC-002 に違反する。詳細は research.md R-4 |
| FR-007（既存フィールドの型・意味を変えてはならない MUST NOT）と、`ResearchInstruction.platform` / `Candidate.platform` の既定値を `"x"` → `""` に変えること（FR-002）の関係 | 「意味を変えない」とは**解決結果を変えない**ことを指すと解釈する。既定値を空文字にしても、空文字は登録辞書の先頭（= `x`）として解決されるため、実行時の挙動は同一である。既定値の変更は、型にプラットフォーム名を埋め込まない（FR-002 / SC-002）ために必須 | 実測（2026-09-13）: `providers/__init__.py` の登録順の先頭が `x` であり、EXT-007 の「空文字 → 先頭」により現行と同じ結果になる。golden は既定値に依存させない（T004 / RND-003） |
