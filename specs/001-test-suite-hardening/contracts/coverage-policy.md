# Contract: カバレッジ計測ポリシー

**Feature**: `001-test-suite-hardening` | **Date**: 2026-09-12

**対応要件**: FR-018、FR-019、SC-002

---

## COV-001: 計測コマンド

| ID | 規約 |
|----|------|
| COV-001-1 | カバレッジは既存のゲートコマンド **`uv run pytest -q` だけで**計測できる（FR-018） |
| COV-001-2 | 未実行行は `term-missing` レポートで特定できる |
| COV-001-3 | しきい値を下回る場合は pytest が非ゼロ終了する（CI と同じゲートで検出できる） |
| COV-001-4 | 計測は開発時依存のみで実現する。実行時依存（`[project].dependencies`）を増やさない |

**設定**（`pyproject.toml`）:

```toml
[project.optional-dependencies]
dev = [
    # …既存…
    "pytest-cov>=5.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=trend_researcher --cov-report=term-missing"

[tool.coverage.run]
source = ["trend_researcher"]

[tool.coverage.report]
fail_under = 90
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

**タスク順序の制約**: `addopts` と `fail_under` の有効化は、カバレッジが目標に到達した**後**に行う。先行して有効化すると、目標達成まで全テスト実行が赤になり、他の作業の検証ができなくなる。

## COV-002: しきい値と範囲

| ID | 規約 |
|----|------|
| COV-002-1 | 対象範囲の**合計**の行カバレッジが **90% 以上**（FR-019、SC-002）。判定は合計値で行う |
| COV-002-2 | 対象範囲は `src/trend_researcher/` 配下の**全モジュール**。判定は `--cov=trend_researcher` の **TOTAL 行（1,206 文）** で行う（FR-019 / SC-002 と同一の定義） |
| COV-002-3 | 宣言のみで分岐を持たないモジュールは母数から除外**できる**が、本機能では `omit` を設定しない。除外の有無で合計は 82.26% → 82.05% と 0.2 ポイントしか変わらないため、分母の解釈を単純に保つ |
| COV-002-4 | 個別モジュールごとの下限は要求しない（達成を阻害しないため）。合計値の達成を理由に CLI 契約や失敗経路の検証を省略してはならない |

**除外の判断**:

| モジュール | 除外 | 理由 |
|------------|------|------|
| `prompts.py` | 除外可（本機能では除外しない） | 文字列定数のみで分岐がない（10 文） |
| `__init__.py`（`trend_researcher/`） | 除外可（本機能では除外しない） | 再エクスポートのみ（4 文） |
| `providers/__init__.py` | **除外しない** | 再エクスポートに見えるが、provider レジストリと未知プラットフォームの拒否（行 20 / 28）という分岐を持つ |
| `providers/base.py` | **除外しない** | `Protocol` だが既定実装（`resort`）を持つ |
| その他のすべて | **除外しない** | 分岐を持つ |

**除外した場合の記録**: 除外する場合は `[tool.coverage.run].omit` に書き、除外理由を本ファイルのこの表に追記する。

## COV-003: 基準値と到達の目安

**2026-09-12 実測**（`uv run pytest -q --cov=trend_researcher --cov-report=term-missing`）:

**判定対象は下段の「全体」行のみ**。「全体」行は `--cov=trend_researcher` の TOTAL であり、`omit` を設定していないため分母は常に **1,206 文**である（COV-002-3）。モジュール別の値は、合計 90% を満たすためにどの領域を埋めるかを示す**目安**であり、個別の下限ではない（COV-002-4）。

| モジュール | 文数 | 未実行 | 現状 | 到達の目安 |
|------------|------|--------|------|------------|
| **全体（判定対象）** | 1,206 | 214 | 82% | **≥ 90%** |
| `__main__.py` | 79 | 79 | 0% | ≥ 90% |
| `tools/x_search.py` | 64 | 35 | 45% | ≥ 90% |
| `cache.py` | 16 | 10 | 38% | ≥ 90% |
| `tools/transcript.py` | 85 | 18 | 79% | ≥ 90% |
| `nodes/extract_common.py` | 68 | 14 | 79% | ≥ 90% |
| `nodes/parse_instruction.py` | 89 | 13 | 85% | ≥ 90% |
| `nodes/compile_report.py` | 136 | 16 | 88% | ≥ 90% |
| `providers/x.py` | 92 | 10 | 89% | ≥ 90% |
| `providers/__init__.py` | 12 | 2 | 83% | ≥ 90% |
| `nodes/analyze_content.py` | 78 | 5 | 94% | 維持 |
| `nodes/plan_search.py` | 44 | 2 | 95% | 維持 |
| `providers/youtube.py` | 49 | 1 | 98% | 維持 |
| `tools/parse.py` | 46 | 3 | 93% | 維持 |
| `providers/base.py` | 15 | 1 | 93% | 維持 |
| `tools/youtube_search.py` | 33 | 4 | 88% | ≥ 90% |
| `configuration.py` | 18 | 0 | 100% | 維持 |
| `graph.py` | 44 | 0 | 100% | 維持 |
| `models.py` | 70 | 0 | 100% | 維持 |
| `nodes/fetch.py` | 26 | 0 | 100% | 維持 |
| `nodes/search.py` | 24 | 0 | 100% | 維持 |
| `progress.py` | 27 | 0 | 100% | 維持 |
| `state.py` | 25 | 0 | 100% | 維持 |
| `tools/llm.py` | 13 | 0 | 100% | 維持 |
| `config.py` | 39 | 1 | 97% | 維持 |

## COV-004: 未実行行の扱い

| ID | 規約 |
|----|------|
| COV-004-1 | 未実行行を残す場合は、その行が「到達不能」であることを論証する（到達不能の論証がない場合はテストを追加する） |
| COV-004-2 | 「テストしにくい」ことは除外の理由にならない。境界モックで到達可能にする |
| COV-004-3 | 到達不能と判明した分岐は、テストを書くのではなく**削除**を検討する（憲法 VI / 不要コードの排除） |

**優先的に埋める未実行行**（現状の `missing` から）:

| モジュール | 未実行行 | 到達させるテスト |
|------------|----------|------------------|
| `__main__.py` | 3-164 全体 | `tests/integration/test_cli_contract.py`（層 A + B） |
| `tools/x_search.py` | 21, 23, 70-75, 90-123, 128, 132, 137-139 | `tests/unit/test_x_search.py`（リトライ枯渇・カウント確定・スレッド取得失敗） |
| `cache.py` | 21-25, 34-38 | `tests/unit/test_cache.py`（書き込み契約・読み戻し契約） |
| `tools/transcript.py` | 51-53, 56, 83, 90, 92, 96-101, 128-133 | `tests/unit/test_transcript.py`（DownloadError・json3・データ欠落） |
| `nodes/extract_common.py` | 57-59, 76-86 | `tests/unit/test_extract_common.py`（空テーマ・見出しのみ・崩れ） |
| `nodes/parse_instruction.py` | 54, 61-64, 72, 75, 102, 112-117 | `tests/unit/test_parse_instruction.py`（優先順位の分岐・漢数字・期間） |
| `nodes/compile_report.py` | 34, 44-45, 62-65, 105-107, 136-141 | `tests/unit/test_compile_report.py`（出典・備考・0 件・キャッシュ失敗） |
| `providers/x.py` | 39-40, 94, 103-109 | `tests/unit/test_x_search.py`（likes プール・描画・fetch 失敗） |
| `providers/__init__.py` | 20, 28 | `tests/unit/test_providers.py`（レジストリ・未知プラットフォームの拒否） |
| `providers/youtube.py` | 42 | `tests/unit/test_youtube_search.py`（字幕なしの描画） |
| `providers/base.py` | 77 | `tests/unit/test_providers.py`（`resort` の既定実装） |
| `tools/youtube_search.py` | 18, 21-22, 76 | `tests/unit/test_youtube_search.py`（件数上限・日付欠落） |
| `tools/parse.py` | 26-27, 47 | `tests/unit/test_parse.py`（崩れた表・ブロックなし） |
| `config.py` | 98 | `tests/unit/test_config.py`（環境変数の優先順位・パス解決） |
| `nodes/analyze_content.py` | 30, 44, 48, 72-73 | `tests/unit/test_analyze_content.py`（表の行破棄・フォールバック要約） |
| `nodes/plan_search.py` | 42, 64 | `tests/unit/test_plan_search.py`（空行の破棄・クエリ上限） |

**表の網羅性**: 本表は実測の `Missing` 列に現れた**すべての**モジュールを列挙する。したがって、カバレッジが未達の場合はこの表に沿って埋めればよい（T041 の手順）。

## COV-005: カバレッジが証明しないこと

| ID | 規約 |
|----|------|
| COV-005-1 | カバレッジ率は「実行された」ことのみを示す。「検証された」ことは示さない |
| COV-005-2 | 90% 達成だけでは SC-002 を満たすが、FR-016（無効テストの排除）は満たさない |
| COV-005-3 | したがって SC-004 / SC-006 は変異探針（`contracts/test-layout.md` LAYOUT-005）で別途担保する |

**根拠（実測）**: カバレッジ **82%** の状態で、次の 3 変異がすべて未検出（61 passed）だった。

| 変異 | 内容 |
|------|------|
| M1 | `compile_report` の出典構築を `[]` に |
| M2 | `graph._route_after_search` を常に `continue` に |
| M3 | `progress.ProgressEmitter.TOTAL` を 8 に |

## COV-006: 実行時間の予算

| ID | 規約 |
|----|------|
| COV-006-1 | スイート全体は 60 秒以内（FR-020） |
| COV-006-2 | 基準値は現状 1.5 秒 / 61 件。サブプロセス検証は約 1 秒/件で、境界マトリクス（11 件程度）に限定する |
| COV-006-3 | 60 秒を超える場合は、サブプロセス検証ではなく in-process の検証を増やす方向で調整する |

## 変更手順

しきい値・除外・計測方法を変更する場合は、本ファイルと `pyproject.toml` を同一変更で更新する。
