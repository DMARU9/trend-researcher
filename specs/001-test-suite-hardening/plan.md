# Implementation Plan: テスト拡充によるパイプライン信頼性の向上

**Branch**: `001-test-suite-hardening` | **Date**: 2026-09-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-test-suite-hardening/spec.md`

## Summary

既存テストスイート（61 件・行カバレッジ 82%）を、**「落ちるべきときに落ちる」テスト**へ再構築する。重点は 3 つ。

1. **CLI の外部契約を検証する層を新設する**（現状 0%）。引数エラー経路はサブプロセス実行で、成功・実行時エラー経路は境界モックを注入したサブプロセスで、終了コード 0/1/2 と stdout/stderr の分離をプロセスレベルで固定する。
2. **外部境界の失敗経路を検証する**（X 検索のリトライ枯渇・スレッド取得失敗、字幕なし、キャッシュ書き込み失敗、検索 0 件）。成功経路しか検証されていない領域に、縮退動作の回帰防止を入れる。
3. **既存テストの有効性を実測で監査する**。変異探針により、`compile_report` の出典構築・検索 0 件時のルーティング・進捗総数とノード数の整合を**どの既存テストも検出しない**ことを確認済み（3 変異すべて 61 passed）。これらを検出するテストを追加し、恒真アサートと重複を統合する。

技術アプローチは「新規依存を増やさない」ことを軸にする。サブプロセス検証は `sys.executable` と既存の `unittest.mock` だけで成立し、待機・時刻の非決定性は既存踏襲のモックで固定する。追加する開発時依存はカバレッジ計測のためだけ（`pytest-cov`）。

上記に加え、契約定義の実測で判明した 2 点を計画に含める。

4. **検出した実装不具合を最小修正する**（FR-023 / FR-025）。`__main__.py` の `main()` 内の 2 ブロックを修正する。（a）`--output` の書き込み失敗時に生のスタックトレースが stderr に出る欠陥（research.md R-9）、（b）空文字・空白のみの指示が argparse を通過して受理される欠陥（FR-025。`/speckit.analyze` の是正で検出）。いずれも修正を戻すと対応する契約テストが落ちることを確認する。**この項目が列挙するのは計画時点で把握していた 2 件である。実装段階で FR-023 の対象は `src/` 10 ファイルへ拡大した（後述「実装による是正（2026-09-13）」）。**
5. **X 検索の重複候補の契約を固定する**（FR-024）。複数の検索クエリで同一 `id` が返る場合の重複除去（先勝ち）と取得順の維持を provider の責務として固定する。YouTube は単一クエリのみで重複が発生する経路がないため対象外であり、この非対称は仕様として明示済み。

## Technical Context

**Language/Version**: Python 3.11（`requires-python = ">=3.11"`、実測 3.11.15）

**Primary Dependencies**: 既存の実行時依存（LangGraph / LangChain / `langchain-openai` / `twscrape` / `yt-dlp` / Pydantic v2 / `python-dotenv`）は**変更しない**。開発時依存に `pytest-cov` を追加（FR-018 の計測手段、憲法の YAGNI 条項に基づき必要性を明示）。テストダブルは標準ライブラリの `unittest.mock` のみを使用し、モック基盤は追加しない。

**Storage**: なし（既存どおり `cache/` 配下の JSON のみ。本機能はその契約をテストで固定する）

**Testing**: `pytest`（既存）。`uv run pytest -q` が単一のゲート。テスト層は `tests/unit/`（決定的な変換・解析・モデル・設定）と `tests/integration/`（パイプライン全経路・CLI 経路）の 2 層。非同期テストは既存どおり `asyncio.run()` を直接呼ぶ（`pytest-asyncio` は導入しない）。

**Target Platform**: Linux（開発機）。サブプロセス検証は OS 非依存の `sys.executable` 起動で実現する。

**Project Type**: 単一プロジェクト（CLI ツール + ライブラリ）。`src/` レイアウト、hatchling ビルド。

**Performance Goals**: テストスイート全体の実行時間 **60 秒以内**（FR-020）。基準値は現状 1.5 秒 / 61 件。サブプロセス検証は 1 起動あたり約 1 秒（実測）のため、境界マトリクスに絞って 10 件前後に留める。

**Constraints**:
- ネットワーク接続と実認証情報なしで全件完走する（FR-001、憲法 II）。`OPENAI_API_KEY`・`accounts.db` のクッキー・`yt-dlp` の実通信を要求しない。
- 非決定性（現在時刻・乱数・並列順序・待機）はテスト側で固定する（FR-021）。
- 既存の公開インターフェース（CLI オプション、環境変数、出力形式、終了コード）を変更しない。例外は 2 つで、いずれも終了コードの契約（0 / 1 / 2）を変えない。（a）`--output` の書き込み失敗時のエラーメッセージを、生のスタックトレースから契約どおりの `[エラー]` 形式に改める（終了コードは 1 のまま。FR-023 / research.md R-9）。（b）空文字・空白のみの指示を引数エラー（2）として拒否する（FR-025。現状は受理され、空の指示のまま LLM が呼ばれる）。
- テスト件数は**純増**（追加数 − 削除数）が正であることをもって満たす（SC-005）。重複統合・削除により総件数が一時的に減ることは許容する。
- リポジトリ全体の静的品質ベースライン（実測: `ruff` 40 件 / `mypy` 37 件）は増やさない。本機能で**変更したファイルのみ** boy-scout ルールで green にする。

**Scale/Scope**:
- 対象ソース: 26 ファイル / 1,206 文（`src/trend_researcher/`）
- 現状カバレッジ: 全体 82%（214 文未実行）。とくに薄い領域は `__main__.py` 0%（79 文）、`tools/x_search.py` 45%（35 文）、`cache.py` 38%、`tools/transcript.py` 79%、`nodes/extract_common.py` 79%、`nodes/parse_instruction.py` 85%、`nodes/compile_report.py` 88%、`providers/x.py` 89%
- 目標カバレッジ: 対象範囲（CLI・ノード・外部境界ツール・provider。宣言のみのモジュールを除く）の**合計**で **90% 以上**（FR-019）。個別モジュールごとの下限は要求しない（モジュール別の値は、合計を満たすためにどの領域を埋めるかを示す目安として扱う）
- テスト規模: 61 件を基準とし、追加・強化後の**純増**が正となるようにする（SC-005）。重複統合により総件数が一時的に減ることは許容する

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md`（Version 1.1.0）の各ゲートに対する判定。すべて **PASS**。

- [x] **I. テスト必須（NON-NEGOTIABLE）**: **PASS**。本機能の成果物自体がテストであり、4 つのユーザーストーリーすべてに独立したテストタスクを置く。憲法が定義する「無効なテスト」（対象の挙動を削っても緑のままのテスト、実装の写し、恒真アサート、収集されない fixture）を排除するため、変異探針による監査を US4 と SC-006 で必須化した。実測により 3 クラス（`compile_report` の出典構築、検索 0 件時のルーティング、`ProgressEmitter.TOTAL` と `NODE_ORDER` の整合）が未検出であることを確認済みで、これらは新規テストで固定する。
- [x] **II. 外部 I/O の境界分離とオフラインテスト**: **PASS**。`src/` への新規外部 SDK 導入はなく、テストは `tools/` / `providers/` の境界で `unittest.mock` により差し替える。実測で「実グラフ + 境界モック」の CLI 実行が 1 秒未満で完走し、ネットワークなしで終了コード 0 が得られることを確認済み。実 API の手動スモークは plan のスコープ外（spec Assumptions）。
- [x] **III. 型付きパイプライン契約**: **PASS**。`state.py` / `models.py` / `Configuration` のフィールド変更を**計画していない**。既存契約をテストで固定する側に徹する。US4 の監査で型・State の変更が必要な欠陥が見つかった場合は、原則 III に従い同一変更で全参照（ノード・provider・レンダラ・テスト）を追随させ、その旨を `tasks.md` に明記する。
- [x] **IV. プラットフォーム抽象**: **PASS**。`graph.py` / `nodes/` に**新しい** `platform == ...` 分岐を追加しない。X / YouTube の差は既存どおり `providers/` に閉じたまま、provider 単体テスト（`test_x_search.py` / `test_youtube_search.py` / `test_providers.py`）と両プラットフォームの統合テストで固定する。X 検索の重複候補の除去（FR-024）は `XProvider.search` の責務として固定し、YouTube に同等の要求を課さない（単一クエリのみのため重複が発生する経路がない）。この非対称は仕様に明示済みであり、provider 間の「見かけの不揃い」を欠陥と誤認しない。`nodes/compile_report.py` の既存分岐には触れない（原則 IV の SHOULD は「そのファイルを変更する際」であり、本機能での変更を計画していない）。
- [x] **V. CLI 出力契約と観測可能性**: **PASS**。むしろ本ゲートが本機能の中心である。stdout = レポートのみ / stderr = 進捗・ログ・エラー / 終了コード 0・1・2 を、プロセスレベルで固定する（FR-002〜FR-008）。`ProgressEmitter` の `TOTAL`・`NODE_ORDER` とグラフのノード数の一致（FR-015）、`cache/` の永続化契約（FR-014）もテストで固定する。実測で `--platform bogus` は exit 2・stdout 空、`--format json` は stdout が JSON のみ・stderr に 7 ノード分の進捗、を確認済み。
- [x] **VI. リファクタリングは後方互換を要求しない**: **PASS**。テストファイルの移動（`tests/test_graph.py` → `tests/integration/test_graph_wiring.py`、`tests/test_configuration.py` → `tests/unit/test_configuration.py`）と重複テストの削除・統合は、旧パスへの互換シムや旧テストの残置を**行わない**。全参照を同一変更で更新し、振る舞いの固定はテストで担保する。ユーザー向け契約（CLI オプション・出力・終了コード・`TR_*` / `XTR_*` / `YTR_*`）は変更しない。
- [x] **技術制約・品質ゲート**: **PASS**。`tasks.md` に `uv run pytest -q` / `uv run ruff check .` / `uv run mypy src` を必須タスクとして置く。実測ベースラインは `ruff` 40 件・`mypy` 37 件であり、憲法の移行措置（変更ファイルは green、ベースラインを増やさない）に従う。**リポジトリ全体の burndown は憲法の `TODO(BASELINE-BURNDOWN)` が要求する追跡タスクとして `tasks.md` に起票**し、本機能では完遂しない（スコープ外を明示）。

**ゲート判定の根拠となる実測**（すべて 2026-09-12、リポジトリ内で実行）:

| 実測項目 | 結果 |
|----------|------|
| 現状テスト | 61 passed / 1.5 秒 |
| 現状カバレッジ | 82%（未実行 214 文）、`__main__.py` 0% |
| 引数エラー経路 | `--platform bogus` / 引数欠落 → exit 2・stdout 空・stderr に argparse のエラー |
| `--since` 不正 | exit 2・stdout 空・stderr に日本語エラー |
| `--help` | exit 0 |
| 成功経路（境界モック） | exit 0・stdout = レポートのみ・stderr = 進捗。実グラフ込みで 1 秒未満 |
| 実行時エラー経路 | 例外 → exit 1 / 時間上限 → exit 1 / レポート欠落 → exit 1（いずれも stdout 0 バイト） |
| 0 件経路 | exit 0・stderr に理由・stdout に空レポート |
| 出力先ファイル指定 | stdout にレポートなし・stderr に完了メッセージ・ファイルに書き出し |
| リトライ待機のモック | attempts=3 / sleeps=[1, 2, 4] / elapsed 0.001 秒（実時間 7 秒を消費しない） |
| 静的品質ベースライン | `ruff` 40 件（うち `src` 32 件）/ `mypy` 37 件（12 ファイル） |
| 変異探針（3 件） | **すべて 61 passed**（＝未検出。詳細は research.md R-4） |
| 空指示（実測） | `_parse_args([""])` / `_parse_args(["   "])` がいずれも例外なしで受理される（引数検証の欠落） |
| 列挙値のケース | `--platform X` → `SystemExit(2)`（正規化されない） |

### Phase 1 設計後の再評価（2026-09-12）

Phase 1 で確定した設計成果物（`data-model.md` / `contracts/` / `quickstart.md`）を踏まえて再判定した結果、**すべて PASS を維持**している。設計が憲法に与える影響は次のとおりで、いずれも新たな違反を生まない。

- `contracts/cli-contract.md` はゲート V（stdout / stderr / 終了コード）をそのまま契約表として固定する。実装の変更ではなく、既存契約の明文化である。
- `contracts/coverage-policy.md` で計測範囲と除外（宣言のみのモジュール）を定義した。ゲート II（オフライン）と YAGNI（プロダクション依存を増やさない）の範囲内に留まる。
- `data-model.md` のエンティティはすべてテスト成果物（テストケース・フィクスチャ・境界モック・変異探針・無効テスト判定記録）であり、`state.py` / `models.py` の契約には触れない。ゲート III に影響しない。
- `contracts/cli-contract.md` を作る過程で `--output` の書き込み失敗が未捕捉であることを実測で検出した（research.md R-9）。FR-023 に従って `__main__.py` を最小修正する。ゲート VI（後方互換を要求しない）の範囲内で、終了コードは変わらずメッセージのみが契約に沿う形になる。（この時点の見込みは `__main__.py` の 2 ブロック。実装段階で FR-023 の対象は 9 ファイルへ拡大した。「実装による是正（2026-09-13）」）
- `/speckit.analyze` の是正で、空文字・空白のみの指示が argparse を通過することを実測で確認した。FR-025 として引数エラー化する。同じ `main()` 内の検証で、既存の `--since` の検証と同型になる。
- X 検索の重複除去（FR-024）を provider の責務として固定する。ゲート IV の対象は `providers/` の内側であり、`nodes/` にプラットフォーム分岐を持ち込まない。

Complexity Tracking に追加した項目は上記 1 件（生成物としての複雑性の追加ではなく、検出済み欠陥の修正）。憲法のゲートに対する違反は 0 件のままである。

## Clarify の反映（2026-09-12）

`/speckit.clarify`（5 問）で確定した判断を、仕様と設計成果物の両方に反映済み。

| 確定事項 | 仕様での反映先 | 計画成果物での反映先 |
|----------|----------------|----------------------|
| カバレッジ 90% は対象範囲の**合計**で判定（個別モジュールの下限なし） | `FR-019` / `SC-002` | `contracts/coverage-policy.md`（COV-002-1 / COV-002-4 / COV-003）、`data-model.md` 1.5、`quickstart.md` 手順 3、本ファイルの Scale/Scope |
| 検出した実装不具合は**本機能の範囲で修正** | `FR-023` | `research.md` R-9、`contracts/cli-contract.md`（文言表 + 既知の実装欠陥）、`quickstart.md` 手順 5.4 |
| テスト件数は**純増**（追加数 − 削除数）で判定 | `SC-005` | `quickstart.md` 手順 1、本ファイルの Scale/Scope |
| 重複候補の契約を要件化 | **`FR-024`（新規）** | `data-model.md` 1.3 / 2、`quickstart.md` 手順 5.3（探針の追加）、本ファイルの Summary #5 / ゲート IV |
| 重複除去のプラットフォーム非対称を仕様として明示 | `FR-024` / Edge Cases | 同上（YouTube を対象外とする記述） |

この反映により、計画の変更点は次の 3 つに集約される。

1. カバレッジの判定を合計値で行う（モジュール別の値は目安に格下げ）。
2. `src/trend_researcher/__main__.py` を変更する（変更対象は `tests/` と `pyproject.toml` に加えてここだけ、というのがこの時点の見込み。**実装段階で FR-023 の対象は 9 ファイルへ拡大した**。後述「実装による是正（2026-09-13）」）。
3. X 検索の重複除去（`FR-024`）のテストを `tests/unit/test_x_search.py` に追加し、変異探針の対象に加える。

## 分析による是正（2026-09-12）

`/speckit.analyze` で検出した指摘のうち、設計判断を伴う 2 件を次のとおり確定した（他は文言・参照の修正）。

| 検出 | 内容 | 確定した扱い | 反映先 |
|------|------|--------------|--------|
| 未カバー要件（Edge Case にあり FR なし） | 「指示文が空文字である」の期待が未定義。実測では `""` / `"   "` がいずれも argparse を通過し、空の指示で LLM が呼ばれる | **引数エラー（終了コード 2）として拒否する。新規 `FR-025`** を追加し、`main()` の引数検証（`--since` と同じ位置）に `src/` の変更を 1 ブロック追加する | `spec.md` FR-025 / Clarifications、`contracts/cli-contract.md`（CLI-001-17 / 文言表 / 既知の実装欠陥 2）、`tasks.md`（T010 / T017 / T018） |
| 曖昧な契約（列挙値のケース） | `--platform X` の期待が未定義。実測では正規化されず引数エラー（2） | **正規化しない**（小文字のみ受理）と契約に明記する。`src/` の変更は不要 | `spec.md` Clarifications、`contracts/cli-contract.md`（CLI-001 の規約 / CLI-005 の注意）、`tasks.md` T010 |

したがってこの時点での `src/` の変更は `src/trend_researcher/__main__.py` の `main()` 内の **2 ブロック**（R-9 の捕捉・FR-025 の検証）に確定した。

## 実装による是正（2026-09-13）

**上記「分析による是正」の `src/` 変更範囲の宣言は、実装段階で失効した。** 本節が実際の範囲の記録であり、`src/` の変更範囲に関する他の記述（Summary #4、Phase 1 再評価、Clarify の反映 #2、Source Code の注記、Complexity Tracking の「`__main__.py` の 1 ブロックのみ修正する」）より優先する。

実測（`git diff --stat cdfe7de -- src/`、基準 `cdfe7de` は T004 のベースライン測定時点）: `10 files changed, 174 insertions(+), 47 deletions(-)`

| # | ファイル | 変更（`+` 行数） | 検出したタスク | FR-023 の根拠 |
|---|----------|------------------|----------------|----------------|
| 1 | `__main__.py` | +22 | T017 | `--output` の書き込み失敗の捕捉（research.md R-9）／空指示の拒否（FR-025）。**計画どおりの 2 ブロック** |
| 2 | `nodes/parse_instruction.py` | +73 | T027 | 件数抽出が年号・期間表現を件数と誤認していた／`input_max != 5` のセンチネルが明示指定 5 を未指定扱いしていた（FR-011） |
| 3 | `nodes/plan_search.py` | +23 | T031 | 日本語に隣接する年号・期間表現の数字が検索クエリに残っていた（`\b` が CJK と数字の間で境界にならない） |
| 4 | `nodes/extract_common.py` | +26 | T028 | `_split_sections` が `#### 説明` を別テーマとして扱っていた（見出し深さを無視） |
| 5 | `nodes/analyze_content.py` | +13 | T029 | 活用アイデア表が空セルの行を採用していた／生の Markdown 表が要約に混入していた |
| 6 | `tools/parse.py` | +26 | T030 | `extract_json_block` が配列・文字列・数値を返し、`parse_instruction` が `AttributeError` で落ちていた |
| 7 | `providers/x.py` | +25 | FR-024 修正 | likes モードで重複した `id` が候補を複数枠占めていた（`_dedupe`） |
| 8 | `nodes/compile_report.py` | +7 | T026 | `--cache-dir` がレポート永続化に届いていなかった／進捗メッセージの重複 |
| 9 | `nodes/fetch.py` | +3 | T028（検証は T047） | 進捗メッセージの重複（戻り値に「開始」が 2 行入る） |
| 10 | `nodes/search.py` | +3 | T028（検証は T047） | 進捗メッセージの重複（同上） |

**実装が正しい理由**: FR-023 は「テスト追加の過程で検出された実装側の不具合は**本機能の範囲で修正** MUST。独立した修正タスクへの切り出しで代替してはならない（MUST NOT）」と定める。2〜10 の変更はいずれもテストを作成する過程で検出された実装欠陥への修正であり、それぞれ差し戻し検証が `tasks.md` の該当節（T026〜T031、T047）に実測として記録されている。計画の「2 ブロックのみ」は**計画時点で既知だった 2 件**を列挙したものであり、その前提が T026 以降に崩れたのが実態である。

**変わらない制約**: `state.py` / `models.py` / `configuration.py` は無変更（憲法 III の「`models.py` の Pydantic モデルを唯一の契約とする」に影響しない）。`nodes/` と `graph.py` に**新しい** `platform == ...` 分岐を追加していない（憲法 IV。`nodes/plan_search.py` の `if platform == "x" and len(queries) > 8:` は基準 `cdfe7de` の 63 行目に既存）。新しい実行時依存を追加していない（FR-018 / COV-001-4）。

## Project Structure

### Documentation (this feature)

```text
specs/001-test-suite-hardening/
├── plan.md              # 本ファイル
├── research.md          # Phase 0 の成果物（技術判断と実測根拠）
├── data-model.md        # Phase 1 の成果物（テスト成果物のエンティティと契約）
├── quickstart.md        # Phase 1 の成果物（実行可能な検証手順）
├── contracts/           # Phase 1 の成果物
│   ├── cli-contract.md      # CLI の外部契約（オプション→終了コード→出力チャネル）
│   ├── test-layout.md       # テスト配置・命名・オフライン/決定性の規約
│   └── coverage-policy.md   # カバレッジ計測の範囲・除外・しきい値
├── checklists/
│   └── requirements.md  # /speckit.specify の成果物（検証済み）
└── tasks.md             # Phase 2 の成果物（/speckit.tasks が生成。本コマンドでは作成しない）
```

### Source Code (repository root)

`src/` の変更は、計画時点では **1 ファイル 2 ブロックのみ**（いずれも `src/trend_researcher/__main__.py` の `main()` 内）と見込んでいた。契約定義のための実測と `/speckit.analyze` の是正が実装欠陥を 2 件検出したため、FR-023 / FR-025 に従って最小修正する計画であり（research.md R-9、本ファイル「分析による是正」）、**実装段階では更に 9 ファイルが FR-023 の対象として追加された**。実際の範囲は **`src/` 10 ファイル / +174 −47** であり、本ファイル「実装による是正（2026-09-13）」がそれを列挙する。主たる変更は `tests/` と `pyproject.toml`（開発時依存 + テスト/カバレッジ設定）。

```text
pyproject.toml                       # [dev] に pytest-cov を追加、[tool.pytest.ini_options] と [tool.coverage.*] を新設

src/trend_researcher/                # 変更範囲は「実装による是正（2026-09-13）」を参照（実際は 10 ファイル）
├── __main__.py                      #   ※計画どおりの 2 ブロック: --output の書き込み失敗を捕捉（R-9）／空指示を拒否（FR-025）
│                                    #   その他の変更ファイル（nodes/*.py・providers/x.py・tools/parse.py）は同節の表を参照
├── cache.py                         #   中間成果物の JSON I/O
├── config.py                        #   .env / 環境変数からの設定解決
├── configuration.py                 #   RunnableConfig 経由の実行時設定
├── graph.py                         #   グラフ構築・ルーティング・レポート描画の入口
├── models.py                        #   Pydantic エンティティ
├── progress.py                      #   ProgressEmitter / NODE_ORDER / TOTAL
├── prompts.py                       #   プロンプト定数
├── state.py                         #   AgentState / AgentInputState
├── nodes/                           #   parse_instruction, plan_search, search, fetch,
│                                    #   analyze_content, extract_common, compile_report
├── providers/                       #   base / x / youtube / __init__
└── tools/                           #   llm, parse, transcript, x_search, youtube_search

tests/
├── conftest.py                                        # 新規: 共有フィクスチャ（境界モック・時刻固定・待機スパイ・一時ディレクトリ）
├── unit/
│   ├── test_fixtures.py                               # 新規: 共有フィクスチャが実際に境界を差し替えていることの検証
│   ├── test_models.py                                 # 既存: 恒真テストを実装経由の検証へ置換
│   ├── test_configuration.py                          # 新規: tests/test_configuration.py を吸収して統合
│   ├── test_config.py                                 # 新規: 環境変数の優先順位・パス解決
│   ├── test_llm.py                                    # 既存: 維持
│   ├── test_parse.py                                  # 既存: 重複ケースを統合、崩れた入力のケースを追加
│   ├── test_parse_instruction.py                      # 既存: 優先順位の分岐を追加（明示設定・自然言語・LLM）
│   ├── test_plan_search.py                            # 既存: クエリ洗浄・上限・空行の扱いを追加
│   ├── test_extract_common.py                         # 新規: 共通ネタ解析の正常系・空・崩れ
│   ├── test_analyze_content.py                        # 新規: ソース整形・表解析・フォールバック要約
│   ├── test_compile_report.py                         # 新規: 出典構築・備考・Markdown/JSON 描画・キャッシュ失敗
│   ├── test_cache.py                                  # 新規: 書き込み契約（配置・UTF-8・非 ASCII）と読み戻し契約
│   ├── test_progress.py                               # 新規: 出力形式・蓄積メッセージ・TOTAL/NODE_ORDER 整合
│   ├── test_providers.py                              # 新規: レジストリ・未知プラットフォーム・行描画
│   ├── test_transcript.py                             # 既存: json3・データ欠落・ダウンロード失敗を追加
│   ├── test_x_search.py                               # 既存: リトライ枯渇・スレッド取得失敗・カウント確定・重複候補の除去（FR-024）を追加
│   └── test_youtube_search.py                         # 既存: 重複ケースを統合、日付欠落・不正形式を追加（単一クエリのみで重複除去を要求しないことも固定）
└── integration/
    ├── conftest.py                                    # 新規: CLI サブプロセス実行用のヘルパフィクスチャ
    ├── cli_harness.py                                 # 新規: サブプロセス側の起動スクリプト（テストとして収集されない名前）
    ├── test_cli_contract.py                           # 新規: 終了コード 0/1/2・出力チャネル分離・出力先ファイル（書き込み失敗の挙動を含む。FR-023）
    ├── test_graph_wiring.py                           # 新規: ノード順・0 件ルーティング・グラフ/進捗の整合（tests/test_graph.py の後継）
    └── test_full_flow.py                              # 既存: 境界モックのディスパッチをノード単位へ変更、失敗経路を追加

（削除）tests/test_graph.py, tests/test_configuration.py   # 上記へ統合。互換のための残置はしない（原則 VI）
```

**Structure Decision**: 既存の 2 層構成（`tests/unit/` = 決定的な変換の単体、`tests/integration/` = 全経路と CLI 経路）をそのまま採用し、憲法 I が規定する配置へ統一する。ルート直下に残っている `tests/test_graph.py` と `tests/test_configuration.py` はこの 2 層の外にあるため、前者の配線・エントリポイント検証は `tests/integration/test_graph_wiring.py` へ、後者の設定検証は `tests/unit/test_configuration.py` へ統合して削除する。

サブプロセス検証のための起動スクリプトは `tests/integration/cli_harness.py` に置く。ファイル名を `test_` で始めないため pytest の収集対象にならず、「収集されない補助テストが静かに無効化される」事故（憲法 I が禁じる無効テストの一形態）を避けられる。実行は `sys.executable <harness> <CLI 引数...>` で行い、シナリオは環境変数で選択する。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

違反なし。すべてのゲートが PASS であり、正当化を要する複雑性の追加はない。

補足として、判断の妥当性を記録しておく。

| 判断 | 採用理由 | 却下した単純案 |
|------|----------|----------------|
| CLI 契約をサブプロセスで検証する（約 1 秒/件） | `main()` の戻り値だけでは `sys.exit(main())` の対応関係と fd レベルの stdout/stderr 分離を検出できない。実測でこの方式のみが「進捗が stdout に漏れる」「argparse のエラーが stdout に出る」型の回帰を捕まえられることを確認した | in-process で `main()` を呼ぶだけの検証（速いが契約を検出できない）。採用品では引数エラー経路の補助として併用する |
| `pytest-cov` を開発時依存に追加 | 既存のゲートコマンド `uv run pytest -q` から 1 コマンドで未実行行を特定できる（FR-018）。プロダクション依存は増えない | `coverage run -m pytest` を別コマンドとして運用（FR-018 の「単一コマンド」を満たさない） |
| 境界モックを注入した「実グラフ」での CLI 検証 | CLI→Configuration→ノードへの設定伝播（例: `--format json` が実際に JSON を出すか）を配線込みで固定できる。実測で、偽グラフだけの検証では `--format json` が Markdown を返し契約を検出できないことを確認した | 偽のグラフだけでの検証（配線の欠陥を検出できない） |
| 空指示を引数エラーとして拒否する（`src/` の追加変更 1 ブロック） | 正否の判定を「空の指示で LLM を呼ぶ」という無意味な実行に依存させない。`--since` の検証と同型で、層 A（サブプロセス 1 回）で検証できるため実行時間への影響が小さい | 空指示の受理をそのまま契約として固定する（LLM 応答に依存し、境界モックで無意味な実行を模様することになり、契約としての価値がない）／Edge Case から削除する（Edge Case と要件の対応が崩れる） |
| テストファイルの移動・削除 | 憲法 I の配置規約と、重複テストの排除（FR-017）を同時に満たす。互換シムを残さない（原則 VI） | 旧ファイルを残置（重複が残り、憲法 I の配置規約に反する） |
| `__main__.py` の 1 ブロックのみ修正する（`--output` の書き込み失敗） | 契約を文書化した時点で、生の `Traceback` が出ることが実測で確定した。テストが期待値を表現するには修正が前提になる（research.md R-9）。**実装段階で FR-023 により `src/` 10 ファイルへ拡大した（「実装による是正（2026-09-13）」）** | 欠陥を追跡タスクとして起票し、テストは現状（Traceback）を固定する（契約違反をテストが追認してしまう） |
| X にのみ重複除去を要求する（YouTube は対象外） | YouTube は `queries[0]` のみを使うため、重複除去の有無が結果に影響する経路が存在しない（= 検証不能な要求を作らない） | YouTube にも重複除去を実装して見かけの対称性を揃える（到達しないコードが増え、憲法の YAGNI に反する） |
