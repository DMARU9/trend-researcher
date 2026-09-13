# Quickstart: 新しいプラットフォームを追加しやすくするリファクタリングの検証

**Feature**: `002-platform-extensibility-refactor` | **Branch**: `002-platform-extensibility-refactor`

本ファイルは「本機能が意図どおりに効いているか」を実行して確かめる手順である。
すべて `trend-researcher` リポジトリのルートで実行する。実装の詳細（コード）は
`tasks.md` と実装フェーズに属する。

---

## 前提

| 項目 | 要件 |
|---|---|
| Python | 3.11（`uv` が解決する。手動の venv 作成は不要） |
| 依存 | `uv sync`（**新しい依存は追加しない**。FR-024） |
| ネットワーク | **不要**（FR-023）。テストは外部 SDK をすべてモックする |
| 認証情報 | **不要**（`OPENAI_API_KEY` / `XTR_ACCOUNTS_DB` を設定しない状態で実行する） |
| 作業ディレクトリ | リポジトリのルート（`/home/takumi/github/trend-researcher`） |

```bash
uv sync
```

---

## 手順 1: 変更前の基準値を採取する（**変更を始める前に 1 回だけ**）

後続の手順はこの値との比較で判定するため、実装の前に採取する。

```bash
uv run pytest -q 2>&1 | tail -5
uv run pytest -q --no-cov --durations=15 2>&1 | tail -20
uv run ruff check .
uv run mypy src
```

**期待（2026-09-13 の実測値）**

| コマンド | 期待 |
|---|---|
| `uv run pytest -q` | `547 passed`、カバレッジ **95.29%**（`fail_under = 90` を満たす）。**実行時間の判定もこのコマンドで行う** |
| `uv run pytest -q --no-cov --durations=15` | `547 passed`、実行時間 **約 51 秒**（遅いテストの把握用。60 秒の判定には使わない） |
| `uv run ruff check .` | `All checks passed!`（0 件） |
| `uv run mypy src` | `Success: no issues found in 26 source files` |

> 実行時間の上限は 60 秒（SC-010）。**判定は `uv run pytest -q`（カバレッジ計測込み）で行う**
> （`--no-cov` は計測を省いて速く終わるため、その値で 60 秒を判定しない）。変更後の値が 60 秒を
> 超えた場合は失敗とみなす。

---

## 手順 2: コアのプラットフォーム名を走査する（SC-002）

```bash
uv run pytest tests/unit/test_platform_scan.py -q
```

**期待**

| 時点 | 検出件数 |
|---|---|
| 変更前（基準） | **16 行**（許容リスト 2 行を含む） |
| 変更後（合格） | **2 行**（`providers/__init__.py` の登録辞書のみ） |

内訳（変更前）: `state.py` 2 / `configuration.py` 1 / `models.py` 2 / `config.py` 2 /
`tools/llm.py` 1 / `providers/__init__.py` 2（許容） / `nodes/compile_report.py` 3 /
`nodes/plan_search.py` 2 / `__main__.py` 1。

**非空虚性の確認（1 回だけ実施）**

```bash
# 例: graph.py に一時的に比較を足す → 走査テストが失敗することを確認 → 元に戻す
printf '\n_PLATFORM_HINT = "x"  # probe\n' >> src/trend_researcher/graph.py
uv run pytest tests/unit/test_platform_scan.py -q   # → FAILED（を確認）
git checkout -- src/trend_researcher/graph.py
uv run pytest tests/unit/test_platform_scan.py -q   # → passed（に戻る）
```

**期待**: 探針を足した状態で **失敗**（`graph.py` の行が違反として列挙される）。
戻した状態で **成功**。失敗しない場合、走査テストは空文化している。

---

## 手順 3: 試験用プラットフォームを追加して完走させる（SC-001）

```bash
uv run pytest tests/unit/test_platform_extension.py -q
```

**期待**: `passed`。テストは次を行う。

1. `register_provider()` で試験用プラットフォームを登録する（**コアのファイルを編集しない**）。
2. 境界（`Provider.search` / `fetch_contexts` / LLM）をテスト内のフェイクで置き換える。
3. `build_graph()` のパイプラインを実行し、`report` が生成されること、進捗が 7 行であることを確認する。
4. レポートに試験用プラットフォームの `content_noun` / `candidates_section_title` /
   `selection_note` が反映されていることを確認する。
5. 後始末（登録の解除）を行い、他のテストへ影響を残さない。

**あわせて確認する（コア差分 0 行）**

```bash
git diff --name-only -- src/trend_researcher/graph.py \
  src/trend_researcher/state.py src/trend_researcher/models.py \
  src/trend_researcher/configuration.py src/trend_researcher/nodes/ \
  src/trend_researcher/rendering.py
```

**期待**: 手順 3 の実施によって新しい差分が生じないこと（0 ファイル）。
手順 2・3 は「同じ変更一式」の中で行うため、実装済みの差分が出ていること自体は正常である。
追加の編集が必要になった場合は、コアに差分が生じている＝SC-001 の失敗である。

---

## 手順 4: 描画の出力一致を確認する（SC-006）

**手順 4 は実装の前に golden を採取する。**

```bash
# 4-1. 変更前に golden を採取する（1 回だけ）
uv run python - <<'PY'
from pathlib import Path
from tests.unit.test_rendering import build_golden_cases
# 変更前は描画が nodes/compile_report.py にある（US4 で rendering.py へ移す）
from trend_researcher.nodes.compile_report import render_json, render_markdown

out = Path("tests/unit/golden")
out.mkdir(parents=True, exist_ok=True)
for name, (report, provider) in build_golden_cases().items():
    (out / f"{name}.md").write_text(render_markdown(report, provider), encoding="utf-8")
    (out / f"{name}.json").write_text(render_json(report), encoding="utf-8")
    print("wrote", name)
PY
```

> `build_golden_cases()` は `tests/unit/test_rendering.py` 内の関数である（追加ファイルを増やさない）。
> 戻り値は `dict[str, tuple[ResearchReport, Provider]]` で、キーは `x_full` / `youtube_full` /
> `sparse` の 3 件。変更前に採取するため、実装の最初のタスクでこの関数だけを先に書く。
> **3 件すべてで `platform` / `output.format` などの既定依存値を明示する**（US1 で `platform` の
> 既定が `"x"` → `""` に変わるため、既定に依存させると golden が意図せず変化する）。
>
> `render_json` は **provider を取らない**（`report.model_dump_json` を返すだけであり、
> 出力にプラットフォーム依存の文言が無いため）。US4 でも署名は変えない。
>
> 採取は**変更前のツリー**で行う。変更後に採ると自己言及的なテストになり、SC-006 を検証できない。

> ⚠️ **JSON には削除対象フィールドの意図的な差分が生じる**: `render_json` は
> `report.model_dump_json(indent=2, exclude_none=True)` を返すため、FR-009 で削除する
> `ResearchInstruction.use_trends` と FR-008 で削除する `OutputSpec.table_for` が JSON から消える。
> これは削除要件の帰結であり、RND-003 のとおり **当該 2 キーを両側で除去してから byte 比較する**
> （Markdown は byte 一致を維持）。golden ファイル自体は削除前の出力（当該キーを含む）を保持し、
> 比較の側で除外する。

```bash
# 4-2. 変更後に比較する
uv run pytest tests/unit/test_rendering.py -q
```

**期待**: `passed`。比較は byte 一致（**Markdown は完全一致、JSON は `use_trends` / `table_for` の
2 キーのみ除外**）。
差が出た場合は**実装を直す**（golden を書き換えない。意図しない差分は失敗として扱う）。

> フェーズ 2（Foundational）で golden を採取した直後から `test_rendering.py` は
> `nodes/compile_report.py` を import して比較を回す（US1〜US3 の出力変化を継続的に検出するため）。
> US4 で import 先を `trend_researcher.rendering` へ切り替える。

**代表入力は 3 件**: X の完全形 / YouTube の完全形 / 欠落形（文脈・分析・共通テーマが空）。
3 件で RND-004 の分岐（本文あり・なし、要約なし、アイデアなし、テーマなし）を代表させる。

---

## 手順 5: 利用者可視の契約を確認する（SC-007 / FR-021）

```bash
uv run pytest tests/integration/test_cli_contract.py -q
```

**期待**: `passed`。固定されている契約は次のとおり。

| 契約 | 期待 |
|---|---|
| `--help` の終了コード | 0 |
| 未登録の `--platform` | 終了コード **2**、stderr に使用法（stdout には何も出さない） |
| 実行中の進捗 | **stderr** のみに 7 行 |
| レポート | **stdout** のみ（`--output` 指定時はファイル） |
| 失敗時 | 終了コード **1**、stderr にエラー |
| 削除する `--trends` | 受理しない（`--help` に現れない） |

**手動での確認（任意）**

```bash
uv run python -m trend_researcher --help
uv run python -m trend_researcher --platform bogus > /dev/null; echo "exit=$?"
```

**期待**: `--help` に `--trends` が現れない。2 つ目のコマンドは `exit=2`。

---

## 手順 6: 設定の一元化を確認する（SC-003 / SC-004）

```bash
# 6-1. 設定型が 1 つであること
grep -rn "class Config\b\|def get_config\|Config\.load" src/ || echo "OK: 0 件"

# 6-2. ノードが環境変数を読まないこと（走査テストの規則 (c)）
uv run pytest tests/unit/test_platform_scan.py -q -k "nodes_do_not_read"

# 6-3. 設定の解決と優先順位
uv run pytest tests/unit/test_config.py tests/unit/test_configuration.py -q
```

**期待**

| 確認 | 期待 |
|---|---|
| 6-1 | `OK: 0 件`（`Config` / `get_config` / `Config.load` が `src/` に存在しない） |
| 6-2 | `passed`（`nodes/**` に `os.getenv` / `os.environ` / `load_dotenv` が 0 件） |
| 6-3 | `passed`（`TR_*` > 環境変数 > 指示本文 > LLM の優先順位。**期待値は変更前と同一**） |

**プラットフォーム固有設定の所在**

```bash
grep -rn "XTR_\|YTR_" src/ --include=*.py | grep -v "^src/trend_researcher/providers/" | grep -v "^src/trend_researcher/tools/" || echo "OK: 固有設定は provider / tools のみ"
```

**期待**: `OK: ...`（`configuration.py` / `nodes/` に `XTR_` / `YTR_` が現れない）。

---

## 手順 7: 品質ゲートを確認する（SC-009 / SC-010）

```bash
uv run pytest -q 2>&1 | tail -5
uv run ruff check .
uv run mypy src
# 依存の差分（FR-024。テスト・Lint・型検査では検出できない）
git diff -- pyproject.toml
```

**期待**

| ゲート | 期待 |
|---|---|
| テスト | 全件 green（基準 547 + 本機能で追加する件数）。カバレッジ 90% 以上（`fail_under`） |
| Lint | 0 件 |
| 型チェック | 0 件 |
| 実行時間 | **`uv run pytest -q`（カバレッジ込み）で 60 秒以内**（基準 49.7 秒。**余地は約 10 秒**） |
| 依存 | `pyproject.toml` の `[project].dependencies` / `optional-dependencies` に差分なし（`[dependency-groups]` / `uv.lock` の解決差分は許容） |
| ネットワーク | 未接続でも完走する |

---

## 完了の判定（Acceptance 早見表）

| 手順 | 対応する要件 | 合格の条件 |
|---|---|---|
| 1 | SC-009 / SC-010 | 4 コマンドが基準値と同水準（テスト全件 / Lint 0 / 型 0 / 60 秒以内） |
| 2 | SC-001 (2) / SC-002 | 走査の検出が **2 行**（許容リストのみ）。探針で失敗することを 1 回確認 |
| 3 | SC-001 (1) / FR-005 / FR-006 | 試験用プラットフォームがコアを編集せずに完走。既存 2 プラットフォームのテストも green |
| 4 | SC-006 / FR-018 | golden 3 件と byte 一致（Markdown / JSON の両方） |
| 5 | SC-007 / FR-021 | 終了コード・出力チャネル・`--help` の語が不変。`--trends` が消えている |
| 6 | SC-003 / SC-004 / FR-013〜FR-015 | 設定型が 1 つ。ノードの環境変数アクセス 0。優先順位が不変 |
| 7 | SC-009 / SC-010 / FR-024 | 3 ゲートが green、`pytest -q` で 60 秒以内、依存の追加 0、ネットワーク不要 |

---

## 関連文書

| 文書 | 内容 |
|---|---|
| `spec.md` | 要件（FR-001〜FR-027）と成功基準（SC-001〜SC-010） |
| `plan.md` | 技術方針、Constitution Check、基準値のずれ |
| `research.md` | 設計判断 R-1〜R-12（Decision / Rationale / Alternatives） |
| `data-model.md` | 拡張点・設定・描画・走査規則・削除一覧・テスト移行一覧 |
| `contracts/platform-extensibility-contract.md` | EXT-001〜EXT-010 |
| `contracts/settings-contract.md` | SET-001〜SET-012 |
| `contracts/rendering-contract.md` | RND-001〜RND-007 |
| `contracts/removal-rationale.md` | REM-001〜REM-009（削除の根拠とテスト更新の記録） |
