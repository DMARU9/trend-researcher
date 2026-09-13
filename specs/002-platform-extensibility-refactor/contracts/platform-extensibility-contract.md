# Contract: プラットフォーム拡張（コア不変）

**Feature**: `002-platform-extensibility-refactor` | **Date**: 2026-09-13

「新しいプラットフォームを追加するとき、コア（骨格・ノード・状態・設定・描画）に差分を生じさせない」
という約束を、検証可能な形で固定する。判定は機械的に行えること（テストで red にできること）を
要求する。

---

## EXT-001: 追加が必要なファイル

新しいプラットフォームを 1 つ追加するのに触るファイルは、次の **3 つだけ**でなければならない。

| # | ファイル | 変更内容 |
|---|---|---|
| 1 | `src/trend_researcher/providers/<name>.py` | `Provider` Protocol の実装（新規ファイル） |
| 2 | `src/trend_researcher/providers/__init__.py` | 登録辞書への 1 エントリ追加（または `register_provider()` の呼び出し） |
| 3 | `src/trend_researcher/prompts.py` | プロンプト本文の追加（**データの追加。分岐は追加しない**） |
| （4） | `tests/unit/test_<name>.py` | 単体テスト（新規ファイル） |

**禁止**: `graph.py` / `nodes/**` / `state.py` / `models.py` / `configuration.py` /
`tools/**`（固有の境界を除く）/ `progress.py` への変更。**検証**: EXT-009。

---

## EXT-002: 状態定義に名前を列挙しない

`state.py` と `models.py` において、プラットフォーム名（`"x"` / `"youtube"` / 追加する名前）を
`Literal` で列挙してはならない。プラットフォームは `str` として扱う。

| 対象 | 契約 |
|---|---|
| `AgentInputState.platform` | `NotRequired[str]` |
| `AgentState.platform` | `str` |
| `ResearchInstruction.platform` | `str`（既定は空文字。解決は登録側） |
| `Candidate.platform` | `str`（既定は空文字。解決は登録側） |

**検証**: EXT-009（走査）で `state.py` / `models.py` の検出が 0 件であること。

---

## EXT-003: 登録は辞書の追加で完結する

| 項目 | 契約 |
|---|---|
| 登録の定義 | `providers/__init__.py` の `_PROVIDERS: dict[str, type[Provider]]` の 1 エントリ |
| 追加の方法 | 新エントリの追加、または `register_provider(cls)` の呼び出し |
| 既存エントリ | 変更しない |
| 登録の構造 | 変更しない（新しいレジストリクラス・探索機構を作らない） |
| `available_platforms()` | 戻り値が登録キーの一覧（順序は定義順）である |
| エラー文言 | 登録キーから生成し、プラットフォーム名のリテラルを含めない |

**検証**: `tests/unit/test_platform_extension.py` が、テスト内で `register_provider()` により
試験用プラットフォームを登録し、`available_platforms()` に現れることを確認する。

---

## EXT-004: 差は provider のフックで表現する

コアに残るプラットフォーム差分の表現先は、次のフックに限定する（data-model.md 1 章）。

| 差の種類 | 表現するフック |
|---|---|
| 検索ポリシー（クエリ本数の上限） | `max_search_queries`（`int \| None`） |
| 出力の名詞 | `content_noun` |
| 候補一覧の見出し | `candidates_section_title` |
| 選定基準の注記 | `selection_note(sort_by)` |
| 固有の環境変数の接頭辞 | `env_prefix` |
| 固有設定の解決 | provider 内部（`settings()`。Protocol には含めない） |
| 表・詳細ブロック・プロンプト | 既存フック（変更しない） |

**禁止**: 上記以外の目的で `provider.name == "..."` の比較をコア（`graph.py` / `nodes/` /
`rendering.py` / `__main__.py` / `configuration.py`）に書くこと。**検証**: EXT-009。

また、`help=` / `description=` などの**説明文にプラットフォーム名を列挙しない**
（例: `help="対象プラットフォーム（x=X/Twitter、youtube=YouTube）"`）。利用可能な値の提示は
CLI の `choices=available_platforms()` に委ね、登録の追加だけでヘルプが正しくなる状態にする。
**検証**: EXT-008 の検出規則 (d)。

---

## EXT-005: 1 実行 = 1 プラットフォーム

`AgentState` / `Configuration` は単一のプラットフォームしか持たない。
複数プラットフォームの集合・結果統合・並列実行を前提とした型・関数を追加しない。

**検証**: 追加されるシグネチャに `list[Provider]` / `dict[str, ...]`（プラットフォーム名をキーとする
もの）が現れないことを、EXT-008 の検出規則 (e) で AST 走査により確認する（FR-026）。

---

## EXT-006: 既存プラットフォームの挙動を変えない

追加後も、X / YouTube の次の観測可能な挙動は不変である。

| 観測項目 | 固定しているテスト |
|---|---|
| レポート本文（Markdown / JSON） | `tests/unit/test_rendering.py`（golden） |
| CLI の終了コードと出力チャネル | `tests/integration/test_cli_contract.py` |
| パイプラインの進行（7 ノード・進捗 7 行） | `tests/integration/test_full_flow.py` |
| 選定・並び替え・重複除去の規則 | `tests/unit/test_providers.py`、`tests/unit/test_compile_report.py` |
| 設定の優先順位 | `tests/unit/test_config.py`、`tests/unit/test_configuration.py` |

---

## EXT-007: 未登録名の扱い

| 経路 | 契約（現行と同一） |
|---|---|
| CLI（`--platform`） | `choices=available_platforms()` により引数エラー。終了コード **2**。stderr に使用法 |
| Studio（状態の `platform`） | 入力段階の検証は行わない。ノード実行時に `get_provider()` が `ValueError` |
| 空文字（未指定） | 登録辞書の先頭のプラットフォームとして解決する（現行の既定 `"x"` と同じ結果） |
| `get_provider()` の直接呼び出し | 未登録名は `ValueError`。メッセージに利用可能な名前を含む |

---

## EXT-008: 走査テストの許容リストは 2 行

| 項目 | 契約 |
|---|---|
| 許容リストの位置 | `providers/__init__.py` の登録辞書の 2 行のみ |
| 照合方法 | `(ファイル名, 正規化した行内容)` の組（行番号に依存しない） |
| 検出件数（規則 (a)+(b)） | **2**（変更前は 16） |
| 検出件数（規則 (d): `help=` / `description=` の名前列挙） | **0**（変更前は `__main__.py` の `--platform` ヘルプ 1 件） |
| 検出件数（規則 (e): プラットフォームの集合型） | **0** |
| 除外集合 | `providers/{x,youtube,base}.py`、`tools/{x_search,youtube_search,transcript}.py`、`prompts.py` |
| 除外の理由 | 実装ファイル = 差の実装そのもの / `tools/` = 固有の外部境界 / `prompts.py` = データ |
| 規則 (c) | `nodes/**.py` の `os.getenv` / `os.environ` / `load_dotenv` / `Config.load` が **0 件**（SET-004） |

**検証**: `tests/unit/test_platform_scan.py`。違反時はファイル・行・内容を列挙して失敗する。

---

## EXT-009: コア差分 0 の機械的検証（SC-001）

次の 2 つのテストが、両方とも green でなければならない。

1. **完走テスト**（`tests/unit/test_platform_extension.py`）: 試験用プラットフォームを
   `register_provider()` で登録し、境界をすべてモックしたパイプラインを実行して完走すること。
   コア（`graph.py` / `nodes/` / `state.py` / `models.py` / `configuration.py` / `rendering.py`）を
   編集せずに完走できることを示す。
2. **走査テスト**（`tests/unit/test_platform_scan.py`）: コアの検出件数が許容リスト（2）と一致すること。

**非空虚性の確認**: 走査テストは、コアのいずれかのファイルに `== "x"` の比較を一時的に足すと
失敗しなければならない（テストの空文化を防ぐ）。この確認は実装時に 1 回行い、結果を
`## Implementation Notes` に記録する。

---

## EXT-010: 用語と改名の禁止

| 禁止事項 | 内容 |
|---|---|
| 改名 | CLI オプション `--platform`、環境変数 `TR_*` / `XTR_*` / `YTR_*`、状態のフィールド `platform`、モジュール名（`providers/` / `providers/base.py`）を変えない |
| 語彙の入れ替え | 「プラットフォーム」を他の語（「取得元」「ソース」など）に置き換えない |
| 例外 | 該当なし。語の選定は既存の慣習に従う |
