# Contract: テスト配置・命名・決定性

**Feature**: `001-test-suite-hardening` | **Date**: 2026-09-12

**対応要件**: FR-001、FR-012、FR-015、FR-016、FR-017、FR-021、SC-004、SC-006

テストスイート自体の構造に関する契約。憲法 I / II を具体化する。

---

## LAYOUT-001: 配置

| ID | 規約 |
|----|------|
| LAYOUT-001-1 | 決定的な変換・解析・モデル・設定の単体テストは `tests/unit/` に置く |
| LAYOUT-001-2 | パイプライン全経路と CLI 経路のテストは `tests/integration/` に置く |
| LAYOUT-001-3 | リポジトリルート直下（`tests/` 直下）にテストファイルを置かない |
| LAYOUT-001-4 | 1 モジュールにつき 1 テストファイルを原則とし、ファイル名は `test_<module>.py` とする |
| LAYOUT-001-5 | 共有フィクスチャは `tests/conftest.py`、層固有は `tests/<layer>/conftest.py` に置く |
| LAYOUT-001-6 | テストから起動される補助スクリプトは `test_` で始めない名前（例: `cli_harness.py`）とし、`tests/integration/` に置く |
| LAYOUT-001-7 | 収集範囲は `[tool.pytest.ini_options].testpaths = ["tests"]` で明示する |
| LAYOUT-001-8 | 旧パスへの互換シム（旧ファイルの残置・再エクスポート）を残さない（原則 VI） |

**配置マップ**:

| 対象モジュール | テストファイル |
|----------------|----------------|
| `models.py` | `tests/unit/test_models.py` |
| `configuration.py` | `tests/unit/test_configuration.py` |
| `config.py` | `tests/unit/test_config.py` |
| `progress.py` | `tests/unit/test_progress.py` |
| `cache.py` | `tests/unit/test_cache.py` |
| `tools/parse.py` | `tests/unit/test_parse.py` |
| `tools/llm.py` | `tests/unit/test_llm.py` |
| `tools/transcript.py` | `tests/unit/test_transcript.py` |
| `tools/x_search.py` | `tests/unit/test_x_search.py` |
| `tools/youtube_search.py` | `tests/unit/test_youtube_search.py` |
| `providers/`（レジストリ・行描画） | `tests/unit/test_providers.py` |
| `nodes/parse_instruction.py` | `tests/unit/test_parse_instruction.py` |
| `nodes/plan_search.py` | `tests/unit/test_plan_search.py` |
| `nodes/search.py` | `tests/unit/test_search.py` |
| `nodes/fetch.py` | `tests/unit/test_fetch.py` |
| `nodes/analyze_content.py` | `tests/unit/test_analyze_content.py` |
| `nodes/extract_common.py` | `tests/unit/test_extract_common.py` |
| `nodes/compile_report.py` | `tests/unit/test_compile_report.py` |
| `graph.py`（配線・ルーティング） | `tests/integration/test_graph_wiring.py` |
| `__main__.py`（CLI 契約） | `tests/integration/test_cli_contract.py` |
| グラフ全経路 | `tests/integration/test_full_flow.py` |

## LAYOUT-002: 命名

| ID | 規約 |
|----|------|
| LAYOUT-002-1 | テスト関数名は `test_<対象>_<条件>_<期待>` の形にする（例: `test_search_zero_candidates_routes_to_compile`） |
| LAYOUT-002-2 | 失敗経路のテストは条件に `raises` / `empty` / `missing` / `malformed` / `rejected` のいずれかを含める |
| LAYOUT-002-3 | 契約テストは `test_cli_<契約 ID>`（例: `test_cli_exit_code_2_on_invalid_since`）の形にし、`contracts/cli-contract.md` の ID を docstring に書く |
| LAYOUT-002-4 | 1 テストは 1 つの振る舞いを検証する。複数の契約を 1 テストに詰めない |

## LAYOUT-003: オフライン性

| ID | 規約 |
|----|------|
| LAYOUT-003-1 | テストスイートはネットワーク接続なしで全件完走する（憲法 II） |
| LAYOUT-003-2 | `OPENAI_API_KEY` / `OPENAI_BASE_URL` の実値、X のクッキー、`accounts.db` を要求しない |
| LAYOUT-003-3 | 外部呼び出しの差し替えは `tools/` / `providers/` の境界で行う。`nodes/` の内部関数を差し替えない |
| LAYOUT-003-4 | 実リポジトリの `cache/` と `accounts.db` に書き込まない（一時ディレクトリを使う） |
| LAYOUT-003-5 | 実 API を叩く確認は README の手動スモークとしてのみ行い、自動テストの合否条件に含めない |

**検証方法**: `env -u OPENAI_API_KEY -u OPENAI_BASE_URL uv run pytest -q` が green であること。加えて、ネットワーク名前空間を遮断して完走することを確認する。

```bash
# ネットワーク遮断下での完走確認（2026-09-12 実測: 61 passed）
unshare -rn uv run pytest -q
```

## LAYOUT-004: 決定性

| ID | 規約 |
|----|------|
| LAYOUT-004-1 | 現在時刻に依存する検証は `now` を固定する（`MagicMock(wraps=datetime)` で `fromisoformat` は実物へ委譲） |
| LAYOUT-004-2 | リトライ待機はスパイに差し替え、実時間を消費しない（観測した待機値を断言する） |
| LAYOUT-004-3 | 並列実行（上限 2）の完了順序に依存する断言をしない。集合または件数で比較する |
| LAYOUT-004-4 | LLM 応答はテストが明示的に与える。プロンプト本文の部分文字列によるディスパッチを使わない |
| LAYOUT-004-5 | テストは実行順序に依存しない（`-p no:randomly` の有無、単独実行と全体実行で同じ結果） |
| LAYOUT-004-6 | 生成時刻など本質的に非決定的な値は、値ではなく型・存在を断言する |

**検証方法**: 各テストファイルを単独で実行しても green であること。

```bash
uv run pytest -q tests/unit/test_compile_report.py   # 単独でも green
uv run pytest -q                                     # 全体でも green
```

## LAYOUT-005: 有効性（無効テストの排除）

| ID | 規約 |
|----|------|
| LAYOUT-005-1 | 追加する各テストは「対象の振る舞いをどう変異させると落ちるか」を説明できること（`detects_mutation_of`） |
| LAYOUT-005-2 | 説明できないテストは追加しない（憲法 I） |
| LAYOUT-005-3 | 恒真アサート（断言が構築式と同一）、実装の写し（テスト内に production のロジックをコピー）、収集されない fixture を持ち込まない |
| LAYOUT-005-4 | テスト内のヘルパが出荷コードのロジックを再実装している場合、出荷コードを import して駆動するよう改める |
| LAYOUT-005-5 | 同一の振る舞いを複数箇所で検証しない。重複を見つけたら 1 箇所へ統合する |
| LAYOUT-005-6 | 変異探針の実施手順（sha256 復元検証 → スイート再実行 → `git status`）を省略しない |

## LAYOUT-006: 構造の整合

| ID | 規約 |
|----|------|
| LAYOUT-006-1 | `ProgressEmitter.TOTAL == len(NODE_ORDER)` |
| LAYOUT-006-2 | `len(NODE_ORDER) == グラフに `add_node` されたノード数` |
| LAYOUT-006-3 | 進捗の出力行数は、成功経路で `2 × ノード数 + 追加メッセージ数` と一致する |
| LAYOUT-006-4 | 各ノードは開始と完了の両方を出力し、片方だけの状態を残さない（憲法 V） |

**検証方法**: `tests/unit/test_progress.py` と `tests/integration/test_graph_wiring.py`。`TOTAL` を変更するとテストが落ちること（M3 の対抗措置）。

## 変更手順

構造・命名・決定性の規約を変更する場合は、本ファイルと該当テストを同一変更で更新する。
