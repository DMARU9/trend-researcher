# Phase 0 Research: テスト拡充によるパイプライン信頼性の向上

**Feature**: `001-test-suite-hardening` | **Date**: 2026-09-12

Technical Context の不確定要素を、**すべて実測により**解決した。結論を先に示し、各決定に「採用理由」と「実測の生データ」を付ける。

## 決定の要約

| ID | 論点 | 決定 |
|----|------|------|
| R-1 | CLI の終了コード・出力チャネルをどう検証するか | 2 層方式。引数エラーは `python -m trend_researcher` を直接サブプロセス実行。成功・実行時エラーは**境界モックを注入する起動スクリプト**をサブプロセス実行 |
| R-2 | カバレッジをどう計測するか | `pytest-cov` を開発時依存に追加し、`[tool.pytest.ini_options].addopts` に `--cov` を入れて単一コマンド化 |
| R-3 | 待機・時刻の非決定性をどう固定するか | 待機は `asyncio.sleep` をスパイに差し替え、時刻は `MagicMock(wraps=datetime)` で `now` のみ固定（既存踏襲、新規依存なし） |
| R-4 | 既存テストの有効性をどう判定するか | 変異探針（振る舞いを一時改変 → テストが落ちるか）で判定し、復元を sha256 で検証 |
| R-5 | テストの配置と重複をどう扱うか | `tests/unit` と `tests/integration` の 2 層へ統一。ルート直下の 2 ファイルを統合して削除（互換シムなし） |
| R-6 | サブプロセス検証のコストをどう抑えるか | 境界マトリクスに限定した起動スクリプト方式（1 起動あたり約 1 秒）。シナリオは環境変数で選択 |
| R-7 | LLM のフェイクをどう設計するか | ノード単位で個別に注入する。プロンプト本文の部分文字列によるディスパッチは使わない |
| R-8 | 静的品質のベースラインをどう扱うか | 本機能で変更するファイルのみ boy-scout で green 化。全体 burndown は追跡タスクとして起票 |

---

## R-1: CLI の終了コード・出力チャネルの検証方式

**Decision**: 2 層方式を採用する。

- **層 A（引数エラー経路 / ネットワーク不要）**: `[sys.executable, "-m", "trend_researcher", ...]` を直接サブプロセス実行する。引数解析は外部接続より前に完結するため、モック注入が不要。
- **層 B（成功・実行時エラー経路）**: `tests/integration/cli_harness.py` を `[sys.executable, "<harness>", <CLI 引数...>]` として実行する。ハーネスは**モックを適用してから** `trend_researcher.__main__.main()` を呼び、`sys.exit()` で終了する。シナリオ（実グラフ / 例外 / 時間上限 / レポート欠落）は環境変数で選択する。

**Rationale**:

- `main()` の**戻り値だけ**を検証すると、(a) `sys.exit(main())` との対応関係、(b) fd レベルの stdout/stderr 分離、を検出できない。実際に「進捗が stdout に混ざる」「argparse のエラーが stdout に出る」型の回帰は戻り値検証では緑のままになる。
- 層 A は**モックなしで**成立する。実測で `--platform bogus` / 引数欠落 / `--since` 不正のいずれも exit 2・stdout 0 バイト・stderr にエラー、`--help` は exit 0 だった。これは「引数検証が外部接続より前にある」という順序契約そのものの検証になる。
- 層 B は**実グラフ**を使えるため、CLI→`Configuration`→ノードへの設定伝播まで配線込みで固定できる。実測で `--format json` の stdout が解析可能な JSON のみになり、stderr に 7 ノード分の進捗が出ることを確認した。

**Alternatives considered**:

- **in-process で `main()` を呼び戻り値のみ検証**: 高速だが終了コード契約と出力チャネル分離を検出できない。層 A の補助（`--help` が 0 を返す等）としてのみ併用する。
- **production コードにテスト用フック（環境変数でグラフを差し替える等）を追加**: 憲法の YAGNI 条項に違反する。テストのためだけの分岐を本体に入れない。
- **実 API を叩く**: 憲法 II に違反（オフライン完走が必須）。
- **`runpy.run_module` + `atexit` フック**: 過去に別プロジェクトで使った手法だが、本件ではサブプロセス + モック注入で足りるため不採用（不要な複雑性）。

**実測の生データ**:

```text
# 層 A: 引数エラー経路（モックなし・ネットワークなし）
$ python -m trend_researcher "t" --platform bogus      → exit 2 / stdout 0 バイト
  stderr: trend_researcher: error: argument --platform: invalid choice: 'bogus'
$ python -m trend_researcher "t"                        → exit 2 / stdout 0 バイト
$ python -m trend_researcher "t" --platform x --since 2025/01/01
                                                        → exit 2 / stdout 0 バイト
  stderr: [エラー] --since は YYYY-MM-DD 形式で指定してください: 2025/01/01
$ python -m trend_researcher --help                     → exit 0

# 層 B: 境界モックを注入した実グラフ（exit 0、約 1 秒）
$ python <harness> "テスト指示" --platform x --format json --max-results 3
  exit 0 / stdout: {"analyses", "candidates", "common_themes", "generated_at",
                    "instruction", "notes", "sources"} を持つ JSON のみ
  stderr: [1/7] parse_instruction ... 開始 〜 [7/7] compile_report ... 完了

# 層 B: 実行時エラー経路（いずれも stdout 0 バイト）
  例外        → exit 1 / stderr: [エラー] リサーチ実行中に問題が発生しました: ...
  時間上限    → exit 1 / stderr: [警告] リサーチが時間上限（100分）に達しました。...
  レポート無し → exit 1 / stderr: [エラー] レポートが生成されませんでした。

# 層 B: 0 件経路
  exit 0 / stderr: 該当なし: 指定された指示に一致するツイートが見つかりませんでした。
  stdout: 空のレポート（334 バイト）

# 層 B: 出力先ファイル指定
  exit 0 / stdout 0 バイト / stderr: [完了] レポートを <path> に書き出しました。
```

**重要な副産物**: 偽のグラフだけを使う検証では `--format json` が Markdown を返した。`main()` は `report.instruction.output.format` を見て描画形式を決めるため、偽グラフがその値を設定しないと契約を再現できない。**CLI の出力形式契約は「CLI → Configuration → parse_instruction → レポート描画」の配線全体で決まる**ため、境界モックを注入した実グラフでの検証が必要だと確定した。

---

## R-2: カバレッジ計測の方式

**Decision**: 開発時依存に `pytest-cov` を追加し、`pyproject.toml` に次を新設する。

- `[tool.pytest.ini_options]`: `addopts = "--cov=trend_researcher --cov-report=term-missing"`、`testpaths = ["tests"]`
- `[tool.coverage.run]`: `source = ["trend_researcher"]`
- `[tool.coverage.report]`: `fail_under = 90`、`exclude_lines`（`pragma: no cover` 等）

**Rationale**:

- FR-018 は「カバレッジを**単一のコマンド**で計測でき、未実行行を特定できる」ことを要求する。既存のゲートコマンド `uv run pytest -q` に `--cov` を載せれば、追加のコマンドを覚える必要がない。
- `testpaths = ["tests"]` により、収集範囲が明示され「`src/` 配下や `/tmp` の拾い上げ」がなくなる。
- プロダクション依存は増えない（`[project.optional-dependencies].dev` のみ）。憲法の YAGNI 条項が許容する「必要性を説明できる場合」に該当する（未実行行の特定手段が現状存在しない）。

**Alternatives considered**:

- **`coverage run -m pytest` を別コマンド運用**: FR-018 の「単一コマンド」を満たさない。
- **`pytest-cov` を入れずに `coverage` API を直接叩くテストを書く**: 計測コード自体がテスト対象になり、無効テストの温床になる。

**注意（タスク順序）**: `--cov` と `fail_under = 90` を先に有効化すると、目標達成までゲートが赤になる。**カバレッジ設定の有効化はテスト追加の後**に置く。

**実測の生データ**:

```text
$ pytest -q --cov=trend_researcher --cov-report=term-missing
61 passed / TOTAL 1206 stmts, 214 miss, 82%
  __main__.py            79 stmts   79 miss    0%
  tools/x_search.py      64 stmts   35 miss   45%
  cache.py               16 stmts   10 miss   38%
  tools/transcript.py    85 stmts   18 miss   79%
  nodes/extract_common.py 68 stmts  14 miss   79%
  nodes/parse_instruction.py 89 stmts 13 miss 85%
  nodes/compile_report.py 136 stmts 16 miss   88%
  providers/x.py          92 stmts  10 miss   89%
$ pip install 相当: ModuleNotFoundError: No module named 'pytest_cov'（未導入）
```

---

## R-3: 非決定性（待機・時刻）の固定

**Decision**:

- **待機**: `mock.patch("trend_researcher.tools.x_search.asyncio.sleep", spy)` でスパイに差し替え、呼び出し回数と引数を検証する。
- **時刻**: `mock.patch.object(parse_instruction, "datetime", MagicMock(wraps=datetime))` に `now.return_value` を設定する（既存 `tests/unit/test_parse_instruction.py` の `_with_fixed_now` パターンを踏襲）。`wraps` により `fromisoformat` などは実物へ委譲され、`now` だけが固定される。

**Rationale**:

- FR-010 は「リトライを伴う外部呼び出しは、待機時間を実時間で消費せずに検証できる」ことを要求する。X 検索のリトライは `await asyncio.sleep(2 ** attempt)` で、`max_retries=3` なら 1+2+4 = **7 秒**を実時間で消費する。スパイ差し替えで 0.001 秒になることを実測した。
- `MagicMock(wraps=datetime)` は新規依存なしで `now` だけを固定できる。`freezegun` の追加は YAGNI に反する（既存テストが同じ目的を標準ライブラリで達成済み）。
- 副次的な注意: `parse_instruction` は `datetime.fromisoformat` も使うため、モジュール全体を素の `MagicMock` に差し替えると `fromisoformat` が壊れる。`wraps` が必須。

**Alternatives considered**:

- **`freezegun` / `time-machine` の導入**: 追加依存。既存パターンで代替可能なため却下。
- **`asyncio` のイベントループ仮想時間（`loop.time()` の差し替え）**: 追加のループ操作が必要で、得られる検証内容はスパイと同等。
- **リトライ待機を production 側で設定可能にする（`retry_base_delay` 引数の追加）**: テストのためだけの production 変更であり YAGNI。ただしテストの可読性が問題になった場合の代替案として記録しておく。

**実測の生データ**:

```text
$ pytest -q -s /tmp/probe_retry_test.py
PROBE attempts=3 sleeps=[1, 2, 4] elapsed=0.001s
1 passed in 0.43s          # 実時間 7 秒を消費していない
```

---

## R-4: 既存テストの有効性の判定（変異探針）

**Decision**: 変異探針を監査の主要手段とする。手順は次のとおり固定する。

1. `sha256sum` で対象ファイルのハッシュを取得する。
2. 振る舞いを 1 箇所だけ改変する（例: 出典構築を空にする）。
3. フルスイートを実行し、**失敗するか**を記録する。
4. バックアップから復元し、`sha256sum` が一致することを確認する。
5. 復元後にフルスイートをもう一度実行して green に戻ったことを確認する。
6. `git status --short` で変異の残骸がないことを確認する。

**Rationale**:

- カバレッジ率は「実行された」ことしか示さず、「検証された」ことを示さない。実測で **カバレッジ 82% の状態でも 3 クラスが未検出**だった。これはカバレッジ目標（FR-019）だけでは FR-016（無効テストの排除）を満たせないことの直接の証拠である。
- 復元を sha256 で検証するのは、「変異が残ったまま次の判定に進む」事故を防ぐため。過去に他エージェントと並行して変異を当てた際に結果が汚染された事例があり、復元確認を完了条件に含めないと判定が信用できない。

**Alternatives considered**:

- **カバレッジ率のみで判断**: 「実行されているが検証していない」テストを検出できない（本実測が反例）。
- **`mutmut` / `cosmic-ray` などの変異テストツール導入**: 追加依存。対象が 3 クラスに絞られており、手動探針で十分。ただし将来の自動化候補として記録する。
- **レビューによる目視判定**: 再現性がなく、憲法 I が求める「落ちるべきときに落ちる」の客観的根拠にならない。

**実測の生データ（3 変異すべて未検出）**:

| 変異 | 内容 | 結果 |
|------|------|------|
| M1 | `nodes/compile_report.py` の `sources = [c.url for c in candidates if c.url]` を `sources = []` に変更 | **61 passed**（検出せず） |
| M2 | `graph.py` の `return "skip" if not candidates else "continue"` を `return "continue"` に変更（0 件でも fetch へ進む） | **61 passed**（検出せず） |
| M3 | `progress.py` の `TOTAL = 7` を `TOTAL = 8` に変更（`NODE_ORDER` と不一致） | **61 passed**（検出せず） |

```text
=== 復元検証 ===
cr: before=a621818fe6ed570093702021e5e2cf82aa4e62fcba1070dfbccf97690defab42
    after =a621818fe6ed570093702021e5e2cf82aa4e62fcba1070dfbccf97690defab42
gr: before=35552d6f9f4ab8e189cfab8f24c555bc90f0a2b2863f635d95a2c26919646252
    after =35552d6f9f4ab8e189cfab8f24c555bc90f0a2b2863f635d95a2c26919646252
pg: before=58044c02480d7f7f7bc3159d1a8951088a905236d19a49c2c413e5e050f2a164
    after =58044c02480d7f7f7bc3159d1a8951088a905236d19a49c2c413e5e050f2a164
=== git status（変異の残骸がないこと）===
?? .specify/feature.json
?? specs/
=== 復元後のフルスイート ===
61 passed in 0.46s
```

**監査で特定した無効テストの内訳**（US4 の作業対象）:

| 対象 | 判定 | 根拠 |
|------|------|------|
| `tests/unit/test_models.py::test_report_sources_invariant` | **恒真** | `sources=[c.url for c in cands]` と断言 `set(report.sources) == {c.url for c in cands}` が同じ式。production の `compile_report` を触っていない。M1 が未検出であることと整合 |
| `tests/test_graph.py::TestAgentState::test_agent_state_has_messages_field` / `test_agent_state_inherits_messages_state` | **重複** | 同一クラス内で同一の断言（`"messages" in AgentState.__annotations__`）を 2 回書いている |
| `tests/test_graph.py::TestConfiguration`（4 件） | **重複** | `tests/unit/test_configuration.py` と同一内容（既定値・`from_runnable_config`・`None` 経路・JSON スキーマ） |
| `tests/test_graph.py::TestGraphBuild`（2 件） | **弱い** | `assert graph is not None` / `hasattr(graph, "ainvoke")` のみ。ノード順やルーティングを固定していない（M2 が未検出であることと整合） |
| `tests/unit/test_transcript.py::test_transcript_dataclass` | **弱い** | テストファイル内で定義したデータクラスの enum 値を確認しているだけで、production の分岐を通らない |
| `tests/unit/test_parse.py::test_parse_angles_table_skips_header_and_separator` | **一部重複** | `test_parse_angles_table` が同じヘッダ・区切り行のスキップを既に検証している |
| `tests/unit/test_youtube_search.py::test_search_videos_limits_to_max` | **一部重複** | `test_search_videos_top_n` の `len == 5` が件数制限を既に検証している |
| `tests/integration/test_full_flow.py::_FakeModel`（部分文字列ディスパッチ） | **欠陥の温床** | プロンプト本文の部分一致で応答を切り替えるため、無関係な語（「関連」）で誤応答する。実測で `extract_common` に誤った応答が返り共通テーマが 0 件になった |

**併せて判明した静的品質の事実**（R-8 の根拠）:

- `nodes/analyze_content.py` は `"Candidate"` / `"Context"` / `"Provider"` を**引用符付き前方参照で書きつつ import していない**。`ruff` の `UP037`（引用符除去）を機械的に適用すると `F821`（未定義名）が残る。正しい修正は import の追加であり、自動修正の適用だけでは不十分。
- `ruff` の違反は `src` に 32 件、`tests` に 8 件（合計 40 件）。`mypy` は 37 件 / 12 ファイル。

---

## R-5: テスト配置と重複統合

**Decision**: 憲法 I が規定する 2 層（`tests/unit/`、`tests/integration/`）へ統一する。

- `tests/test_configuration.py`（ルート直下）→ `tests/unit/test_configuration.py` に統合して削除。
- `tests/test_graph.py`（ルート直下）→ 配線・エントリポイント検証を `tests/integration/test_graph_wiring.py` へ移して削除。`Configuration` の重複 4 件は統合先で既に検証されているため削除。
- 新規ファイルは `tests/unit/test_extract_common.py` / `test_analyze_content.py` / `test_compile_report.py` / `test_cache.py` / `test_config.py` / `test_progress.py` / `test_providers.py`、`tests/integration/test_cli_contract.py` / `test_graph_wiring.py`。

**Rationale**:

- 憲法 I: 「テストの配置は既存構成に従う MUST: `tests/unit/` … 単体、`tests/integration/` … グラフ全経路と CLI 経路」。ルート直下の 2 ファイルはこの規約の外にある。
- FR-017 の重複解消と、憲法 I の配置規約を 1 回の移動で同時に満たせる。
- 原則 VI により、旧パスへの互換シム（旧ファイルの残置、`from tests.test_graph import ...` の別名など）は**作らない**。
- 新規単体テストの単位は「既存テストが空いているファイル」に合わせる（例: `nodes/extract_common.py` → `tests/unit/test_extract_common.py`）。1 モジュール 1 テストファイルの原則を崩さない。

**Alternatives considered**:

- **ルート直下のファイルを残したまま新規を追加**: 重複が残り、配置規約に反する。
- **`tests/e2e/` を新設してサブプロセステストを分離**: 過去の別プロジェクトで、`testpaths` から外れたディレクトリに置いたガードテストが静かに無効化される事故があった。収集対象から外れるリスクを避けるため、既存の `tests/integration/` に置く。
- **1 モジュールを複数ファイルへ分割**: 既存の粒度から外れるため不採用。

---

## R-6: サブプロセス検証のコスト

**Decision**: サブプロセス検証は CLI 契約の境界マトリクスに限定し、10 件前後とする。1 件あたり約 1 秒を見込み、合計 10〜15 秒を 60 秒予算に収める。

対象シナリオ（1 シナリオ = 1 テスト）:

1. 引数エラー: 未知のプラットフォーム（層 A）
2. 引数エラー: 必須オプション欠落（層 A）
3. 引数エラー: `--since` 不正（層 A、日本語エラーメッセージを含む）
4. `--help` は exit 0（層 A、`main()` の `SystemExit` 再送出経路を踏む）
5. 成功 + stdout 出力（層 B、実グラフ、stdout = レポートのみ / stderr = 進捗）
6. 成功 + JSON 出力（層 B、実グラフ、stdout が解析可能な JSON）
7. 成功 + 出力先ファイル（層 B、stdout にレポートなし）
8. 検索 0 件（層 B、exit 0 + stderr に理由）
9. 実行時例外（層 B、exit 1 + stderr にエラー）
10. 時間上限到達（層 B、exit 1 + stderr に警告）
11. レポート欠落（層 B、exit 1）

**Rationale**:

- 実測で境界モックを注入した実グラフの CLI 実行が約 1 秒（`real 0m0.996s`）で完走する。11 件でも 15 秒程度で、既存 61 件（1.5 秒）と合わせて 60 秒予算に十分収まる。
- サブプロセス検証は**このリポジトリで唯一 CLI の実契約を観測できる手段**であり、削ると FR-002〜FR-008 が満たせない。

**Alternatives considered**:

- **`pytest-xdist` で並列化してサブプロセス検証を増やす**: テストの並列実行はログの混線とデバッグ困難を招く。11 件なら不要。
- **すべて層 A で済ませる**: 引数エラー以外の契約（成功時の stdout 分離、実行時エラーの終了コード）を検出できない。

**前提の実測**: `sys.executable` は venv の Python を指し、`import trend_researcher` が成功することをサブプロセスで確認済み。

```text
PROBE subprocess rc= 0 ok
```

---

## R-7: LLM フェイクの設計

**Decision**: ノード単位でフェイクを注入する。`mock.patch` の対象を `trend_researcher.nodes.<node>.build_model` のように**ノードごとに個別指定**し、1 つのフェイクがプロンプト本文の部分文字列で応答を切り替える設計をやめる。

**Rationale**:

- 既存の統合テストは単一の `_FakeModel` が `"検索クエリ" in prompt or "関連" in prompt` のような部分一致で分岐する。実測で `extract_common` のプロンプトが「関連」を含むため、本来の共通テーマ抽出ではなく検索クエリ応答が返り、**共通テーマが 0 件になった**。同じ原因で「どのノードを検証しているか」がプロンプト文言の変更に脆く依存する。
- ノード単位の注入なら、各ノードのフェイクが返す内容がテストコード上で明示され、プロンプト文言を変えても壊れない。
- これは FR-012（LLM 自由文解析を正常系と崩れの両方で固定）と FR-021（テストが実行順序に依存しない）の前提でもある。

**Alternatives considered**:

- **プロンプト本文の部分一致ディスパッチを維持し、判定語を追加**: プロンプト変更のたびに壊れる。誤検知の実例が出た以上、維持できない。
- **LLM 呼び出しを記録・再生する VCR 方式**: 追加依存。境界モックで十分。

**実測の生データ**: 実グラフ + 部分一致ディスパッチのプローブで `extract_common` が `### テーマ` を含まない応答を受け取り、結果が `common_themes: []` になった（stderr に `[6/7] extract_common ... 完了（0 件の共通テーマ）`）。

---

## R-8: 静的品質ベースラインの扱い

**Decision**:

- 本機能で**変更するファイルのみ**、boy-scout ルールで `ruff` / `mypy` を green にして提出する。
- リポジトリ全体の burndown（`ruff` 40 件 / `mypy` 37 件）は、憲法 `TODO(BASELINE-BURNDOWN)` が要求する**追跡タスクとして `tasks.md` に起票**し、本機能の完了条件には含めない。
- テストの追加のみで `src` を変更しない場合は、既存の `src` 違反に**触れない**（ベースラインを増やさないことが条件）。

**Rationale**:

- 憲法「技術制約と品質基準」の移行措置は「新規ファイルおよび変更したファイルはゲートを green にして提出する MUST」「ベースラインの違反件数を増やしてはならない」と定める。全体 green は「追跡タスクとして起票し、解消する MUST」と別扱いである。
- 本機能の主題はテストの信頼性であり、`src` 全体の静的品質改善は独立した作業単位として切り出すのが妥当（FR-023 が許容する「明示的な追跡」に該当）。
- 実測で `ruff` 40 件 / `mypy` 37 件という具体値が得られたため、burndown タスクにはこの数値をベースラインとして記載する。

**注意**: `UP037`（quoted-annotation）の自動修正は単独では不十分。`nodes/analyze_content.py` と `nodes/compile_report.py` は引用符付き前方参照の名前を import していないため、`ruff --fix` を適用すると `F821` が残る。修正は「import の追加」とセットで行う。

**Alternatives considered**:

- **本機能で `src` 全体を green にする**: スコープが数倍に膨らみ、テスト拡充という主題が薄まる。憲法も burndown を別タスクとして要求している。
- **ベースライン違反を放置したままテストだけ追加**: 変更したファイルが赤のまま提出され、憲法の移行措置に違反する。

---

## R-9: 契約テストで検出した実装欠陥（`--output` の書き込み失敗）

**Decision**:

契約定義のために CLI の失敗経路を実測したところ、**実装欠陥を 1 件検出**した。FR-023 に従い、本機能で最小修正する。

- 欠陥: `--output` の書き込みが `try` ブロックの外側にある（`src/trend_researcher/__main__.py:155`）。書き込みに失敗すると生の `Traceback` が stderr に出る。
- 修正: 書き込みを捕捉し、契約の文言（`[エラー] レポートを <PATH> に書き出せませんでした: <理由>`）で報告して `1` を返す。
- 併せて `contracts/cli-contract.md` の文言表と対応テスト（CLI-001-5）を追加する。

**実測結果**（2026-09-12）:

| 入力 | 終了コード | stdout | stderr |
|------|-----------|--------|--------|
| `--output /tmp/nonexistent_dir_xyz/out.md` | `1` | 0 バイト | `FileNotFoundError` の Traceback |
| `--output /tmp`（既存ディレクトリ） | `1` | 0 バイト | `IsADirectoryError` の Traceback |

**Rationale**:

- 終了コードは `1` で正しいが、エラー報告が仕様（`[エラー]` 形式のメッセージ）から外れる。「エラーは握りつぶさず stderr へ出力し、終了コードに反映する」という既存の意図に対し、生の Traceback は内部実装の露出であり、利用者の自動化がメッセージを解析できない。
- この種の欠陥は、**契約を先に文書化してから実測する**ことで初めて見つかる。既存の 61 件のテストは `main()` の戻り値のみを検証しており、`--output` の失敗経路を一度も通っていない（`__main__.py` のカバレッジ 0%）。
- **計画への影響**: 実装計画の「ソースを変更しない」前提に例外が 1 件加わる。変更は `__main__.py` の 1 ブロックのみで、公開契約は後方互換（終了コードは変わらず、メッセージが追加される）。

**Alternatives considered**:

- **欠陥を追跡タスクとして起票し、本機能では修正しない**: テストが期待値を表現できない（`[エラー]` が無いことを断言することになる）。契約を文書化する以上、修正までを同一変更に含めるのが妥当。
- **親ディレクトリを自動作成して成功にする**: 契約変更が大きく（既存の終了コードが 1→0 に変わる）、利用者の自動化を壊す。
- **`FileNotFoundError` のみ捕捉し `IsADirectoryError` を放置**: 捕捉型の非対称が残り、同じ欠陥クラスが再発する。`OSError` で一括して捕捉する。

---

## 未解決事項

なし。Technical Context の `NEEDS CLARIFICATION` は 0 件であり、上記 9 論点はすべて実測に基づいて確定した。

## 参照した実測の再現コマンド

```bash
# 現状のテストとカバレッジ
uv run pytest -q
uv run --with pytest-cov pytest -q --cov=trend_researcher --cov-report=term-missing

# CLI 引数エラー経路（層 A）
uv run python -m trend_researcher "t" --platform bogus; echo $?
uv run python -m trend_researcher "t" --platform x --since 2025/01/01; echo $?

# 静的品質のベースライン
uv run ruff check . --statistics
uv run mypy src

# 変異探針（例: 出典構築を空にする）
cp src/trend_researcher/nodes/compile_report.py /tmp/cr.bak
# … 1 箇所だけ改変して uv run pytest -q …
cp /tmp/cr.bak src/trend_researcher/nodes/compile_report.py
sha256sum src/trend_researcher/nodes/compile_report.py   # 復元の確認
uv run pytest -q                                          # green に戻ったことの確認
git status --short                                        # 残骸がないことの確認
```
