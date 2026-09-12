# Quickstart: テスト拡充の検証手順

**Feature**: `001-test-suite-hardening` | **Date**: 2026-09-12

本機能の成果物（テストスイート）が要件を満たすことを、**実行して確認する**ための手順。

- 契約の詳細は `contracts/` を参照（本ファイルでは表を再掲しない）
- エンティティの定義は `data-model.md` を参照
- 技術判断の根拠は `research.md` を参照

すべてのコマンドは `trend-researcher/` をカレントディレクトリとして実行する。

---

## 0. 前提

| 項目 | 要件 |
|------|------|
| Python | 3.11 以上（実測環境: 3.11.15） |
| パッケージ管理 | `uv` |
| ネットワーク | **不要**（手順 1〜5 はオフラインで完走する） |
| 認証情報 | **不要**（`OPENAI_API_KEY`、`accounts.db` のクッキーを要求しない） |

```bash
cd trend-researcher
uv sync --extra dev
```

`pytest-cov` は本機能で `[project.optional-dependencies].dev` に追加する。設定（`[tool.pytest.ini_options]` と `[tool.coverage.*]`）が入る前の中間確認では、次の形でも計測できる。

```bash
uv run --with pytest-cov pytest -q --cov=trend_researcher --cov-report=term-missing
```

---

## 1. スイートが完走すること（FR-001 / FR-020 / SC-001）

```bash
time uv run pytest -q
```

**期待結果**: 全件 pass。実行時間は **60 秒以内**（基準値: 変更前 61 件 / 0.5 秒）。

```bash
# テスト件数の確認
uv run pytest -q --collect-only | tail -3
```

**期待結果**: 件数が変更前（61 件）より増えていること。削除・統合したテストがあるため、増分は「追加数 − 削除数」。

## 2. オフラインで完走すること（FR-001 / LAYOUT-003）

```bash
# 認証情報を除いた環境で完走する
env -u OPENAI_API_KEY -u OPENAI_BASE_URL uv run pytest -q

# ネットワークを遮断した名前空間で完走する（実測: 61 passed）
unshare -rn uv run pytest -q
```

**期待結果**: どちらも全件 pass。

**判定**: ここで接続エラー・認証エラーが出る場合、外部 I/O を境界で差し替えられていない（憲法 II 違反）。

## 3. カバレッジが目標に達すること（FR-018 / FR-019 / SC-002）

```bash
uv run pytest -q
```

`addopts` に計測設定が入っているため、**この 1 コマンド**でカバレッジが表示される（FR-018）。

**期待結果**:

| 確認項目 | 期待 |
|----------|------|
| 合計 | **90% 以上（判定対象）** |
| 対象範囲 | `src/trend_researcher/` 配下の全モジュール（`omit` なし。分母は 1,206 文で固定） |
| 個別モジュール | 下限なし（合計を満たすための目安として見る） |
| 未実行行 | `term-missing` 列に表示される |
| しきい値未達 | 非ゼロ終了する（`fail_under = 90` は合計値に適用される） |
| 実行時依存 | 増えていない（`pyproject.toml` の `[project].dependencies` が不変） |

**とくに埋めるべき領域**（変更前の実測値。個別の下限ではなく、合計 90% を満たすための目安）:

| モジュール | 変更前 | 目安 |
|------------|--------|--------|
| `__main__.py` | 0% | ≥ 90% |
| `tools/x_search.py` | 45% | ≥ 90% |
| `cache.py` | 38% | ≥ 90% |
| `tools/transcript.py` | 79% | ≥ 90% |
| `nodes/extract_common.py` | 79% | ≥ 90% |
| `nodes/parse_instruction.py` | 85% | ≥ 90% |
| `nodes/compile_report.py` | 88% | ≥ 90% |
| `providers/x.py` | 89% | ≥ 90% |

**注意**: カバレッジ 90% は「実行された」ことの証明にすぎない。有効性は手順 5 で確認する（`contracts/coverage-policy.md` COV-005）。

## 4. CLI 契約がプロセスレベルで検証されること（FR-002 〜 FR-008 / SC-003）

契約テストが実際に外部契約を観測しているかを確認する。契約 ID との対応は `contracts/cli-contract.md` を参照。

### 4.1 層 A（引数エラー経路。モック不要）

```bash
uv run python -m trend_researcher "t" --platform bogus; echo "exit=$?"
uv run python -m trend_researcher "t" --platform x --since 2025/01/01; echo "exit=$?"
uv run python -m trend_researcher "t" --platform x --format yaml; echo "exit=$?"
uv run python -m trend_researcher "t" --platform x --sort bogus; echo "exit=$?"
uv run python -m trend_researcher "t" --platform x --max-results abc; echo "exit=$?"
uv run python -m trend_researcher "t"; echo "exit=$?"
uv run python -m trend_researcher; echo "exit=$?"
uv run python -m trend_researcher "" --platform x; echo "exit=$?"
uv run python -m trend_researcher "   " --platform x; echo "exit=$?"
uv run python -m trend_researcher "t" --platform X; echo "exit=$?"
```

**期待結果**: すべて `exit=2`（空指示と大文字のプラットフォーム名を含む。CLI-001-17 / CLI-001-10）。`--help` は `exit=0`。

```bash
uv run python -m trend_researcher --help >/dev/null; echo "exit=$?"
```

### 4.2 層 B（実行経路。境界モックを注入した実グラフ）

契約テスト（`tests/integration/test_cli_contract.py`）が担う。手動で同等の確認をする場合は、`tests/integration/cli_harness.py` を CLI と同様の引数で起動する。

```bash
# 契約テストを個別に実行して、確認した契約 ID を出力させる
uv run pytest -q tests/integration/test_cli_contract.py -v
```

**期待結果**: CLI-001〜CLI-006 に対応するテストが pass。とくに次を確認する。

| 確認項目 | 期待 |
|----------|------|
| `--format json` の stdout | 単一の JSON オブジェクトとして解析できる（Markdown が混ざらない） |
| `--format json` の `instruction.output.format` | `"json"`（CLI → Configuration → ノード → 描画の配線が通っている） |
| 進捗行（`[n/7] ...`） | stderr のみ。stdout に 1 行も出ない |
| `--output` 指定時 | stdout が 0 バイト、指定ファイルにレポートが書かれる |
| 0 件 | exit 0、stderr に理由、stdout は空のレポート |
| 例外・タイムアウト・レポート欠落 | exit 1、stdout 0 バイト |
| `--output` の書き込み失敗 | exit 1、**`[エラー]` 形式のメッセージ**（生の `Traceback` ではない） |

**最後の行は research.md R-9 で検出した実装欠陥の検証である。** 修正前は次のように Traceback が出る。

```bash
uv run python -m trend_researcher "t" --platform x --output /tmp/nonexistent_dir/out.md
# 修正前: Traceback (FileNotFoundError)  / 修正後: [エラー] レポートを ... に書き出せませんでした: ...
```

## 5. テストが有効であること（FR-016 / SC-004 / SC-006）

カバレッジでは検出できない「無効なテスト」を、変異探針で確認する（`contracts/test-layout.md` LAYOUT-005）。

### 5.1 変異探針の手順（各探針で必ず全部やる）

```bash
# (1) 改変前のハッシュを記録
sha256sum src/trend_researcher/nodes/compile_report.py

# (2) 対象を 1 箇所だけ改変する（振る舞いが変わる改変に限る）

# (3) 対象テストが落ちることを確認する
uv run pytest -q

# (4) 復元する
# (5) 復元を検証する（一致しなければ判定を無効とする）
sha256sum src/trend_researcher/nodes/compile_report.py

# (6) スイートが green に戻ったことを確認する
uv run pytest -q

# (7) 残骸がないことを確認する
git status --short
```

### 5.2 必須の探針（変更前に**未検出**だった 3 件）

| 探針 | 改変 | 変更前の結果 | 変更後の期待 |
|------|------|--------------|--------------|
| M1 | `nodes/compile_report.py` の出典構築を `[]` にする | **未検出**（61 passed） | 失敗する |
| M2 | `graph._route_after_search` を常に `continue` にする | **未検出**（61 passed） | 失敗する |
| M3 | `progress.ProgressEmitter.TOTAL` を 8 にする | **未検出**（61 passed） | 失敗する |

**判定**: 3 件すべてでスイートが落ちれば FR-016 / SC-004 を満たす。1 件でも通る場合は、対応するテストを追加・強化する。

### 5.3 追加で確認する探針（失敗経路の縮退処理）

失敗経路のテストが「縮退処理を消しても通る」状態になっていないかを確認する。

| 改変 | 対応する失敗経路 |
|------|------------------|
| リトライのループを 1 回で打ち切る | X 検索のリトライ枯渇（FR-010） |
| `tools/transcript.py` の形式判定を `_parse_vtt` のみにする | json3 字幕の解析 |
| `nodes/compile_report.py` のキャッシュ書き込みの `try` を外す | 書き込み失敗を備考に記録して継続 |
| `cache.read_json` を例外を投げる実装にする | 読み戻し契約（存在しない場合の戻り値） |
| `providers/x.py` の重複除去（`seen` の判定）を外す | X 検索の重複候補除去（FR-024） |

### 5.4 FR-023 / FR-025 で修正した不具合の検証

テスト追加の過程で検出した実装不具合 2 件（レポート出力先への書き込み失敗で生のスタックトレースが出る／空指示が argparse を通過する）を修正するため、**修正を 1 つずつ元に戻すと対応する契約テストが落ちる**ことを確認する（FR-023 / FR-025）。**2 つ同時に戻さない**（どちらの修正が効いているか判定できなくなる）。

```bash
# (a) `__main__.py` の書き込み失敗の捕捉（try/except）を外してから実行
uv run pytest -q tests/integration/test_cli_contract.py

# (b) 復元してから、空指示の検証（引数解析直後のチェック）を外して実行
uv run pytest -q tests/integration/test_cli_contract.py
```

**期待結果**: (a) を外すと CLI-001-5 が、 (b) を外すと CLI-001-17 が失敗する。緑のままなら、テストが契約を検証していない。

### 5.5 無効テストの判定記録の確認

`data-model.md` 1.7 の表が、実際のテストファイルの状態と一致していることを確認する。

```bash
# 統合・削除した旧ファイルが残っていないこと
ls tests/test_graph.py tests/test_configuration.py 2>&1 | head -3
```

**期待結果**: どちらも「No such file」。

```bash
# 収集範囲の確認（testpaths が効いていること）
uv run pytest -q --collect-only | grep -c "::"
```

## 6. 決定性（FR-021 / SC-001）

```bash
# 単独実行と全体実行で同じ結果になること
uv run pytest -q tests/unit/test_compile_report.py
uv run pytest -q

# 実行順序を変えても同じ結果になること
uv run pytest -q -p no:cacheprovider tests/unit
uv run pytest -q tests/integration
```

**期待結果**: すべて全件 pass。実行するたびに結果が変わらない（同じコマンドを 3 回実行して確認する）。

**とくに確認する項目**:

| 項目 | 期待 |
|------|------|
| リトライの待機 | 実時間を消費しない（スイート全体の実行時間が変わらない） |
| 現在時刻 | 値に依存した断言がない（固定した時刻を使う） |
| 並列実行の順序 | 完了順に依存した断言がない（集合・件数で比較） |
| 一時ファイル | 実リポジトリの `cache/` を汚さない（実行後に `git status --short` が清浄） |

## 7. 静的品質（憲法の開発ワークフローと品質ゲート）

```bash
uv run ruff check . --statistics
uv run mypy src
```

**期待結果**:

| 確認項目 | 期待 |
|----------|------|
| 変更・新規作成したファイルの `ruff` | 違反 0 件 |
| 変更した `src` ファイル（`__main__.py`）の `ruff` / `mypy` | 違反 0 件 |
| リポジトリ全体の違反件数 | ベースライン（`ruff` 40 件 / `mypy` 37 件）から**増えていない** |

**注意**: リポジトリ全体の burndown は本機能の完了条件ではない（`tasks.md` に追跡タスクとして起票する）。ベースラインの違反を増やさないことが条件。

## 8. README との整合（憲法 V）

CLI の契約を変更した場合は、`README.md` の次が同期していることを確認する。

```bash
grep -n "終了コード\|--output\|--format\|stderr\|stdout" README.md | head -20
```

**期待結果**: 終了コード（0 / 1 / 2）、出力チャネルの分離、`--output` の失敗時の挙動が、`contracts/cli-contract.md` と一致している。

---

## 受け入れ判定のまとめ

| 手順 | 対応する要件・成功基準 | 判定 |
|------|------------------------|------|
| 1 | FR-001 / FR-020 / SC-001 | 全件 pass、60 秒以内 |
| 2 | FR-001（オフライン）/ 憲法 II | 認証情報なし・遮断下で全件 pass |
| 3 | FR-018 / FR-019 / SC-002 | 1 コマンドで合計 ≥ 90%、しきい値未達で非ゼロ終了 |
| 4 | FR-002〜FR-008 / FR-025 / SC-003 | 層 A は exit 2（空指示・大文字の列挙値を含む）、層 B は終了コード・チャネル・形式を観測 |
| 5 | FR-016 / FR-017 / FR-023 / FR-024 / FR-025 / SC-004 / SC-006 | 必須探針 3 件が検出される、修正 2 件の差し戻しで契約テストが落ちる、旧ファイルが残っていない |
| 6 | FR-021 / SC-005 | 単独・全体・順序変更で同一結果、`git status` 清浄 |
| 7 | 憲法の品質基準 | 変更ファイルは green、ベースラインを増やさない |
| 8 | 憲法 V / FR-022 | README と契約文書が同期、既存テストの期待値を実装へ書き換えていない |
