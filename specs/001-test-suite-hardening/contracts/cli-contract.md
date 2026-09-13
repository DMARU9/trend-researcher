# Contract: CLI 外部契約

**Feature**: `001-test-suite-hardening` | **Date**: 2026-09-12

**対象**: `uv run python -m trend_researcher <INSTRUCTION> --platform <x|youtube> [options]`（テストからは `sys.executable -m trend_researcher`）

**対応要件**: FR-002 〜 FR-008（US1）、SC-003

この文書は CLI の**外部契約**を定義する。ユーザーのスクリプト・自動化が依存する観測可能な振る舞いであり、テストで固定する（憲法 V）。

**検証方式**: すべて**実行プロセスの観測結果**として検証する。`main()` の戻り値のみによる検証は契約の検証とみなさない（FR-002）。

- **層 A**: `sys.executable -m trend_researcher <args>` を直接起動（モック不要。引数検証が外部接続より前に完走するため）。`python` ではなく `sys.executable` を使い、実行中の仮想環境を指すことを保証する
- **層 B**: `sys.executable <tests/integration/cli_harness.py> <args>` を起動（環境変数でシナリオを選択し、境界モックを注入してから `main()` を呼ぶ）

---

## CLI-001: 終了コード

| ID | 条件 | 終了コード | 検証層 |
|----|------|-----------|--------|
| CLI-001-1 | 正常にレポートを生成した | `0` | 層 B |
| CLI-001-2 | 検索結果が 0 件（該当なし） | `0` | 層 B |
| CLI-001-3 | 要求件数より取得件数が少ない | `0` | 層 B |
| CLI-001-4 | レポートの出力先を指定して書き出しに成功した | `0` | 層 B |
| CLI-001-5 | レポートの出力先の親ディレクトリが存在しない | `1` | 層 B |
| CLI-001-6 | `--help` を指定した | `0` | 層 A |
| CLI-001-7 | 実行時に例外が発生した | `1` | 層 B |
| CLI-001-8 | 実行が時間上限に達した | `1` | 層 B |
| CLI-001-9 | レポートが生成されなかった | `1` | 層 B |
| CLI-001-10 | 未知のプラットフォーム値を指定した | `2` | 層 A |
| CLI-001-11 | 必須の位置引数（指示）を省略した | `2` | 層 A |
| CLI-001-12 | `--platform` を省略した | `2` | 層 A |
| CLI-001-13 | `--since` に `YYYY-MM-DD` 以外を指定した | `2` | 層 A |
| CLI-001-14 | 未知の `--format` 値を指定した | `2` | 層 A |
| CLI-001-15 | 未知の `--sort` 値を指定した | `2` | 層 A |
| CLI-001-16 | `--max-results` に整数以外を指定した | `2` | 層 A |
| CLI-001-17 | 指示が空文字または空白のみだった | `2` | 層 A |

**規約**: `0` = 成功 / `1` = 実行時エラー / `2` = 引数エラー。この 3 値以外を返してはならない。

**プラットフォーム値の大文字小文字**: **正規化しない**。`--platform X` は未知の値として引数エラー（`2`）とする（CLI-001-10）。受理するのは `x` / `youtube` の小文字のみである。

**既知の実装欠陥（2026-09-12 実測・契約テストで検出）**:

`--output` の書き込みは `try` ブロックの外側（`src/trend_researcher/__main__.py:155`）にあるため、書き込みに失敗すると生の `Traceback` が stderr に出る。観測結果:

| 入力 | 終了コード | stderr | 契約適合 |
|------|-----------|--------|----------|
| `--output /tmp/nonexistent_dir_xyz/out.md` | `1` | `FileNotFoundError` の Traceback | **否**（`[エラー]` 形式でない） |
| `--output /tmp`（既存ディレクトリ） | `1` | `IsADirectoryError` の Traceback | **否** |

終了コードは `1` で正しいが、エラー報告の形式が契約（CLI-002 の文言表）を満たさない。契約テストは終了コードだけでなく `[エラー]` の有無と Traceback の不在も検証する（FR-023 の最小修正の対象）。

**既知の実装欠陥 2（2026-09-12 実測・仕様の是正で検出）**:

指示が空文字でも空白のみでも argparse を通過して受理され、`parse_instruction` が空の指示のまま LLM を呼ぶ。引数検証の欠落であり、FR-025 に従って引数エラー（`2`）へ改める。

| 入力 | 終了コード | 契約適合 |
|------|-----------|----------|
| `"" --platform x` | 引数エラーにならない（実行に進む） | **否**（CLI-001-17 は `2` を要求） |
| `"   " --platform x` | 引数エラーにならない（実行に進む） | **否** |

## CLI-002: 出力チャネルの分離

| ID | チャネル | 内容 | 検証層 |
|----|----------|------|--------|
| CLI-002-1 | stdout | 最終レポート（Markdown または JSON）**のみ** | 層 B |
| CLI-002-2 | stdout | 進捗行（`[n/7] <node> ... <phase>`）を含まない | 層 B |
| CLI-002-3 | stdout | エラーメッセージを含まない | 層 A / B |
| CLI-002-4 | stderr | 進捗行（7 ノード分の開始・完了） | 層 B |
| CLI-002-5 | stderr | ログ・情報・警告・エラー | 層 A / B |
| CLI-002-6 | stdout | `--output` 指定時はレポートを出力しない（0 バイト） | 層 B |
| CLI-002-7 | ファイル | `--output` 指定時はそのファイルにレポートを書き出す | 層 B |

**固定する文言**（変更時は本契約とテストを同時に更新する）:

| トリガ | チャネル | 文言 |
|--------|----------|------|
| `--since` 不正 | stderr | `[エラー] --since は YYYY-MM-DD 形式で指定してください: <値>` |
| 指示が空（空文字・空白のみ） | stderr | `[エラー] 指示を指定してください。` |
| 実行時例外 | stderr | `[エラー] リサーチ実行中に問題が発生しました: <例外>` |
| 時間上限 | stderr | `[警告] リサーチが時間上限（<分>分）に達しました。途中結果を返します。` |
| レポート欠落 | stderr | `[エラー] レポートが生成されませんでした。` |
| 0 件（X） | stderr | `該当なし: 指定された指示に一致するツイートが見つかりませんでした。` |
| 0 件（YouTube） | stderr | `該当なし: 指定された指示に一致する動画が見つかりませんでした。` |
| 件数不足 | stderr | `[情報] 要求件数 <N> 件に対し、実際に見つかったのは <M> 件です。` |
| 出力先へ書き出し | stderr | `[完了] レポートを <PATH> に書き出しました。` |
| 出力先へ書き出し失敗（親ディレクトリなし・書込不可・ディレクトリ指定） | stderr | `[エラー] レポートを <PATH> に書き出せませんでした: <理由>` |

## CLI-003: 出力形式

| ID | 条件 | 期待 |
|----|------|------|
| CLI-003-1 | `--format markdown`（既定） | stdout が Markdown（`# リサーチレポート: ` で始まる） |
| CLI-003-2 | `--format json` | stdout 全体が単一の JSON オブジェクトとして解析できる |
| CLI-003-3 | `--format json` | 解析結果に `instruction` / `candidates` / `analyses` / `common_themes` / `sources` / `notes` / `generated_at` が含まれる |
| CLI-003-4 | `--format json` | `instruction.output.format == "json"`（CLI → Configuration → ノード → 描画の配線が通っている） |
| CLI-003-5 | `--format json` | stdout に Markdown の見出し行（`# `）が混入しない |

**規約**: `--format` は `_run_async` が `Configuration.output_format` に伝え、`parse_instruction` が `ResearchInstruction.output` に反映し、`render_report` がその値で描画を切り替える。**この配線全体が契約**であり、層 B（実グラフ）でのみ検証できる。

## CLI-004: レポートの内容契約

| ID | 条件 | 期待 |
|----|------|------|
| CLI-004-1 | X の成功時 | `## 選定ツイートリスト（上位 N 件）` を含む |
| CLI-004-2 | YouTube の成功時 | `## 選定動画リスト（関連度順上位 N 件）` を含む |
| CLI-004-3 | 常に | `## 各コンテンツのブログ向け要約` を含む |
| CLI-004-4 | 常に | `## 共通ネタ（表）` を含む |
| CLI-004-5 | 常に | `## 出典` を含み、`sources` の各 URL が箇条書きされる |
| CLI-004-6 | 共通テーマが 0 件 | `（特筆すべき共通点なし）` を出力する |
| CLI-004-7 | 常に | `## 備考` を含み、選定基準（X は並び順、YouTube は関連度順）が記録される |
| CLI-004-8 | 投稿日下限が指定された | 備考に `投稿日フィルタ: <YYYY-MM-DD> 以降に公開された投稿を対象` が含まれる |

## CLI-005: オプションの受理（既存契約。変更しない）

| オプション | 受理値 | 既定 |
|-----------|--------|------|
| `INSTRUCTION`（位置） | 空文字・空白のみを除く任意の文字列（必須） | — |
| `--platform` | `x` \| `youtube`（必須） | — |
| `--format` | `markdown` \| `json` | `markdown` |
| `--max-results` | 整数 | `5` |
| `--lang` | 言語コード | `ja` |
| `--output` | パス | 標準出力 |
| `--since` | `YYYY-MM-DD` | なし |
| `--sort` | `relevance` \| `likes` | `relevance` |
| `--cache-dir` | パス | `cache/` |

**注意**: 列挙値は大文字小文字を**区別する**。`--platform X` / `--format JSON` / `--sort Relevance` はいずれも未知の値として引数エラー（`2`）になる（正規化しない）。`INSTRUCTION` は空文字・空白のみを受理しない（CLI-001-17）。

## CLI-006: 応答性の契約

| ID | 条件 | 期待 |
|----|------|------|
| CLI-006-1 | 常に | ネットワーク接続なしで完走する（境界モック使用時） |
| CLI-006-2 | 常に | 実認証情報（`OPENAI_API_KEY`、`accounts.db` のクッキー）を要求しない |
| CLI-006-3 | 常に | テスト実行時の `OPENAI_API_KEY` が空でも起動経路が完走する |

---

## 契約とテストの対応

| 契約グループ | 対応するテストファイル | 層 |
|--------------|------------------------|-----|
| CLI-001（終了コード） | `tests/integration/test_cli_contract.py` | A + B |
| CLI-002（出力チャネル） | `tests/integration/test_cli_contract.py` | A + B |
| CLI-003（出力形式） | `tests/integration/test_cli_contract.py` + `tests/unit/test_compile_report.py` | B + unit |
| CLI-004（レポート内容） | `tests/unit/test_compile_report.py` + `tests/integration/test_full_flow.py` | unit + integration |
| CLI-005（オプション） | `tests/integration/test_cli_contract.py`（層 A の引数エラー群） | A |
| CLI-006（応答性） | 全テスト（ネットワーク禁止は suite 全体の性質） | — |

## 変更手順

この契約を変更する場合は、次を**同一変更**で行う（憲法 V / VI）。

1. 本ファイルの該当行を更新する。
2. 対応するテストを更新する。
3. `README.md` の「使い方」「オプション」「出力チャネル」「終了コード」を更新する。
4. `uv run pytest -q` が green であることを確認する。
