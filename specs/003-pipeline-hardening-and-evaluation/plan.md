# Implementation Plan: AI パイプラインの堅牢化と品質測定（Open Deep Research の工夫取り込み）

**Branch**: `003-pipeline-hardening-and-evaluation` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-pipeline-hardening-and-evaluation/spec.md`

## Summary

参照実装（`BLOG-TOOLS/open_deep_research`）が「コンテキスト管理」「一定の動作」「設定の宣言」「品質の測定」
で凝らしている工夫を、**7 ノード構成・CLI 出力契約・既存テストの期待値を変えずに**取り込む。
作業は 8 本の柱に分かれる。いずれも「観測可能な挙動は変えず、内部の堅牢性と入力の扱い、
および本体の外側に計測手段を足す」という同一の方針に従う。

1. **取り込み量の管理（FR-001〜008）**。`nodes/analyze_content.py:69` の `source_text[:20000]`
   という**無言の切り捨て**を、しきい値超過時のみ発動する LLM 圧縮に置き換える。境界は
   新モジュール `tools/compression.py`（原則 II）。圧縮は ODR と同じく要約＋重要抜粋の
   2 部構造で受け取り（`<summary>` / `<key_excerpts>` 相当）、失敗（例外・タイムアウト・空応答）は
   生素材へ戻して継続する。しきい値以下では**追加呼び出し 0 回**（SC-003）。
2. **LLM 応答の契約化（FR-009〜014）**。`parse_instruction` / `analyze_content` / `extract_common`
   の 3 呼び出しを `with_structured_output` に寄せ、規定回数の再試行後は既存の
   `tools/parse.py` へフォールバックする。正常系とフォールバック経路の**両方**をテストで固定する。
3. **上限超過時の完走（FR-015〜019）**。`tools/llm.py` の呼び出しラッパに段階的縮退を置く。
   超過の検出は**実測に基づく多段の検出器**とし、ODR の「例外クラス名＋モジュール名」依存
   （`utils.py:762, 795, 818`）は移植しない（FR-063 / FR-064）。
4. **部分失敗の隔離と状態のライフサイクル（FR-020〜029）**。`asyncio.gather` の 1 件失敗が
   実行全体を落とす経路を塞ぎ、失敗は「分かる形」（`report.notes` と中間データ）で残す。
   レポート確定時に `contexts` の**中身（生素材）だけ**を解放する（レコードは残す）。
5. **設定の宣言と起動時拒否（FR-024 / FR-025 / FR-059 / FR-060）**。`Configuration` の各項目に
   型・値域・選択肢・既定値・説明を宣言し、値域外と型違いは**ノード実行前に拒否**して
   終了コード 2 で終わる。丸めも既定値への置換もしない。Studio の入力契約は
   `json_schema_extra` の `x_oap_ui_config` で宣言する（ODR の E1 と同じ形）。
6. **検索クエリの自己点検（FR-049〜054）**。`nodes/plan_search.py` の**ノード内 1 回**に限定し、
   反復ループにしない。切り替えは出荷設定の真偽値項目（既定は有効。ODR の
   `include_source_str` と同じ形）。
7. **品質の測定（FR-038〜048 / FR-065〜074）**。判定ロジック・採点スキーマ・フィクスチャを
   `tests/eval/` に置いてテストで固定し、LLM を伴う**実走は `script/evaluate.py`** に分離する
   （収集対象外・`testpaths` は不変。FR-066）。実走は公開 API を in-process で駆動し、
   CLI の subprocess を使わない（SC-035）。
8. **プロンプトの深化と移植の統制（FR-055〜058 / FR-063 / FR-064）**。`prompts.py` の 8 プロンプトに
   機械可読な停止条件・上限・出力形式の節を足し、重要な制約を役割の異なる 2 箇所に置く。
   参照実装の実測済みの欠陥（常に真の条件分岐・無効なオプション・到達不能コード・
   プロバイダ固有の例外型依存・部分文字列によるモデル判定・ツール契約の非対称）は移植しない。

**最重要の制約は「既存の観測可能な契約を動かさないこと」**である。実測により、既存テストは
進捗行の**文言と件数**、`report.notes` の中身、`Configuration.model_fields_set`、状態の
`contexts` の存在まで固定している。本計画は、追加の観測を**既存の行を書き換えずに**
出す方法（`ProgressEmitter.note`）と、追加データを**レポート形式の外側**へ出す方法
（`cache/usage.json`・中間データの切り替え）を先に決めてから実装に入る。

## 基準値のずれ（実測 2026-09-14）

spec の「背景と現状の実測」は 2026-09-14 時点の実測だが、spec 002 完了後の数値と
1 点だけずれている。**SC の判定は終状態で行う**ため合否には影響しない。spec 側の
数値は変更せず、本節と `tasks.md` の実装メモに記録する。

| spec の記述 | 実測（2026-09-14） | 差分の理由 |
|---|---|---|
| `src/trend_researcher/` 26 モジュール / 2,736 行 | **27 ファイル / 2,736 行**（`find src -name "*.py" \| wc -l` = 27、`mypy src` = 27 source files） | `__init__.py` を数えるかどうかの差。行数は一致 |
| ベースライン 547 passed / カバレッジ 95.29%（SC-013 は 60 秒以内） | **601 passed / 96.65% / 49.10 秒** | spec 002（プラットフォーム拡張性リファクタリング）完了による増加。`uv run pytest -q` の実測 |
| `nodes/analyze_content.py:65` が `source_text[:20000]` | **`:69`**（`_analyze_one` 内の `provider.analyze_content_prompt.format(...)` 呼び出し行） | spec 002 で行が移動した |
| D7「`Configuration.load()` と `from_runnable_config()` の 2 経路」 | **正しい**。ただし分岐の実体は「env の解決（`load()`）」と「明示指定（`configurable`）」であり、`model_copy(update=...)` は**検証しない**（Pydantic v2 の仕様） | 値域の宣言（FR-059）を効かせるには `model_copy` の後に検証が要る（research.md R-10） |
| 呼び出し回数を固定している既存テスト | `tests/integration/test_full_flow.py:241-242`（`analyze_content` = 5、`extract_common` = 1）、`tests/unit/test_analyze_content.py:421`（同時実行 2） | 追加呼び出しを入れると落ちる箇所。spec の Assumptions が「内部構造（呼び出し回数）を固定しているテストは更新する」と定めている範囲 |
| 進捗行の契約 | `tests/unit/test_analyze_content.py:374-387` が `messages` を**厳密比較**（`[5/7] analyze_content ... 開始（並列上限 2）` / `完了（N 件を要約）`）。`tests/integration/test_full_flow.py:167-181` の `_node_phases` が `(node, phase)` 列を厳密比較 | **進捗行の文言・行数・`messages` への追加は変更できない**。追加の観測は `ProgressEmitter.note`（stderr のみ）で出す（research.md R-12） |

## Technical Context

**Language/Version**: Python 3.11（`requires-python = ">=3.11"`。実行環境は 3.11.15 / 検証用に 3.12 の
`__pycache__` も存在）

**Primary Dependencies**: 既存の実行時依存（`langgraph` 1.2.11 / `langchain` 1.3.18 /
`langchain-openai` 1.6.0 / `langchain-core` 1.6.1 / `twscrape` / `yt-dlp` / `pydantic` 2.13.4 /
`python-dotenv`）を**変更しない**（FR-033 / SC-014）。評価基盤も既存依存の範囲で実装する（FR-045。
`tests/evaluators.py` 相当の判定ロジックは自前で持ち、`langsmith` 等は導入しない）。

**Storage**: DB は持たない。中間成果物は従来どおり `cache/` 配下の JSON（`cache.py` の
`write_json`）。追加する成果物は次の 2 つで、いずれも**レポート形式の外側**に置く。

| 成果物 | 場所 | 追跡 |
|---|---|---|
| 使用量の集計 | `cache/usage.json`（`cache_dir` 配下） | 対象外（`cache/` は `.gitignore` 済み） |
| 評価結果（1 行 1 レコード JSONL） | `artifacts/eval/`（既定。引数 / env で変更可） | 対象外（`artifacts/` は `.gitignore` 済み。実測で `.gitignore` 末尾に「Project specific」節あり） |

**Testing**: `pytest`（`testpaths = ["tests"]`、`addopts = "--cov=trend_researcher --cov-report=term-missing"`、
`fail_under = 90`）。層は `tests/unit/` と `tests/integration/` の 2 層を維持し、**評価基盤の
補助は `tests/eval/`**（`test_*.py` を置かない。実走は `script/evaluate.py`）。境界モックと
LLM フェイクは `tests/conftest.py` の `FakeModelFactory` / `Boundary` を拡張して使う
（`tools/` と `providers/` の差し替えに限定する既存規約を守る。LAYOUT-003-3）。

**Target Platform**: Linux（開発機）。プロセス内で完結し、OS 依存の機能を追加しない。

**Project Type**: 単一プロジェクト（CLI ツール + ライブラリ）。`src/` レイアウト、hatchling ビルド。

**Performance Goals**: テストスイート全体が **60 秒以内**（SC-013）。**実測は 49.10 秒 / 601 passed
であるため、増加に使える余地は約 11 秒**。判定コマンドは `uv run pytest -q`（カバレッジ計測込み）
に固定する。したがって新規テストは次の方針で書く。

- 境界は必ずモックし、ネットワーク・LLM・待機を実時間で消費しない（圧縮・再試行・縮退の
  待機は既存の `no_retry_sleep` と同じ「スパイで観測」方式にする）。
- 評価基盤の実走はテストに含めない（FR-044）。判定ロジックのテストは固定入力の採点のみ。
- 走査・整合性テスト（対応表、収集除外、値域の宣言）はファイル読みのみで書く。

**Constraints**:

- ネットワーク接続と実認証情報なしで全件完走する（FR-036 / 憲法 II）。
- 新規の実行時依存を追加しない（FR-033 / SC-014）。開発用依存の追加も行わない。
- **既存の観測可能な契約を変えない**（最優先）。具体的には次を凍結する。
  - stdout = レポートのみ、stderr = 進捗・ログ・エラー、終了コード 0 / 1 / 2（FR-030）。
  - 進捗行の**文言・行数**と `ProgressEmitter.emit` が状態 `messages` へ積む内容
    （`[n/7] <node> ... <phase>（<detail>）`。実測で厳密比較されている）。
  - レポートの既存キー（Markdown / JSON）と `report.notes` の既存要素。**追加は可**
    （FR-034）だが、追加は「新しい挙動が起きたときだけ」に限る（既定の入力で出力を変えない）。
  - `Configuration.model_fields_set` の意味（明示指定 > 環境変数。`providers/x.py:48` /
    `tests/unit/test_config.py:266` / `tests/unit/test_configuration.py:281` が依存）。
  - 7 ノードの構成と `NODE_ORDER`（FR-031 / 憲法 V）。
- 値域の宣言は既存フィールドの削除・改名を伴わない。既存テストが使う値
  （`max_results` = 1 / 2 / 3 / 5 / 10 / 100 等）は値域内に収める（FR-035 / research.md R-20）。
- 圧縮・再試行・縮退・フォールバックを**すべて既定で有効にはするが**、既定の入力
  （短い素材・正常応答）では呼び出し回数と出力が変わらないようにする。これが
  既存テストを書き換えずに green を保つ条件である。
- 内部 API の後方互換は要求しない（憲法 VI）。旧経路の互換シムを残さない。
- カバレッジ `fail_under = 90` を維持する（実測 96.65%）。ただし
  `providers/base.py` の Protocol 本体（`...`）は既に 71% であり、対象外として扱う。

**Scale/Scope**:

- 変更対象のソース: `src/trend_researcher/` 27 ファイル / 2,736 行。
- 変更見込み: 既存 13 ファイルの変更（`configuration.py` / `state.py` / `models.py` /
  `prompts.py` / `progress.py` / `tools/llm.py` / `tools/parse.py` / `nodes/` の 5 ノード /
  `__main__.py` / `providers/base.py`）、新規 3 モジュール（`tools/compression.py` /
  `tools/degradation.py` / `usage.py`）、新規テスト 3 ディレクトリ分（`tests/eval/` と
  `tests/unit/` の追加分）、新規スクリプト 1（`script/evaluate.py`）。
- テスト規模: 601 passed を基準とする。既存テストは**期待値を書き換えない**。
  呼び出し回数・内部構造を固定しているテスト（上表に列挙）のみ、spec の Assumptions に従い更新する。
- 最も注意を要する箇所:
  1. `tests/conftest.py` の `FakeModelFactory` と `tests/integration/cli_harness.py` の `_FakeLLM`。
     ノードが `with_structured_output` を呼ぶようになると、**両方を同時に拡張しないと
     既存の統合テストが AttributeError で落ちる**（境界の契約そのものの変更）。
     また圧縮は `trend_researcher.tools.compression.build_model` を参照するため、
     `nodes/` の接頭辞を差し替える現行のモックでは**届かない**。両フェイクに追加が必要。
  2. `__main__.py`（値域拒否の経路。`Configuration.load()` と CLI 上書きの両方を通す）。
  3. `nodes/plan_search.py`（自己点検の追加で LLM 呼び出しが 1 回増える。件数契約の解釈は
     「設計上の判断」を参照）。

## 設計上の判断（要確認）

仕様の文字面と既存テストの期待値が両立しない 3 点について、**FR の MUST を優先**する判断を置く。
いずれも実装前の確認事項であり、`tasks.md` の先頭でテストとして固定する。

| # | 論点 | 仕様の文字面 | 採用する判断 | 理由・根拠 |
|---|---|---|---|---|
| D-1 | 自己点検後のクエリ件数（FR-052 / US7 シナリオ 3 / SC-021） | 「X は 5 件ちょうど、YouTube は 1 件」 | **点検は件数を減らさない**（重複除去で減った分は生成結果から補充する）。空配列を返した点検は「差分なし」として生成結果を採用する。件数を固定値まで**増やさない**（生成が 0 件なら 0 件のまま）。上限（`Provider.max_search_queries`）は従来どおり適用する | 「5 件ちょうど」を強制すると既存 6 テストが落ちる（`tests/unit/test_plan_search.py:108`（3 件）/`:113`（2 件）/`:118`（8 件）/`:128`（12 件）/`:134`（8 件）/`:139`（0 件）、`tests/integration/test_full_flow.py:228`（2 件））。FR-035 は「期待値を書き換えるな・失敗したらソースを直せ」と定めており、この方向は選べない。既定プロンプトは従来どおり X に 5 件を指示するため、**既定運用では 5 件**のままである |
| D-2 | 未知モデルで上限超過したときの扱い（FR-015 と Assumptions の「上限が不明なら明示して終了する」） | Assumptions は「未知のモデルでは上限が不明であることを明示して終了する」 | **FR-015 を優先**し、未知モデルでも比率方式（現在の入力の 0.9 倍）で縮退を試みる。モデル上限テーブルは**既知モデルのときに初回の縮小先を上限に合わせるため**にのみ使い、テーブルに無い場合は「上限が不明」を注記に残す（黙って失敗しない） | FR-015 は「縮小可能な入力が残っている間は規定回数内での成功を試みる MUST」。縮退は入力の比率で行えば上限値を要さないため、未知モデルでも試行できる。Assumptions は FR より弱い（Spec Kit の規範順序） |
| D-3 | 使用量の記録とレポート形式の一致（FR-062 / SC-011 / SC-026） | SC-011「レポート形式（Markdown / JSON）が変更前と一致」、FR-062「集計結果は中間成果物と進捗に記録する MUST」 | 使用量を**レポートに入れない**。`cache/usage.json`（中間成果物）と `ProgressEmitter.note`（stderr の追加行）に出す | `report.notes` は `rendering.py:44-47` で本文に描画されるため、常時入る情報（使用量）を足すと既定の stdout が必ず変わる。SC-026 は「既存キーが変更前と一致」と述べており、**キーの追加は許すが既存の出力は動かさない**と読む。よって中間成果物と stderr に出す |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md`（Version 1.2.1）の各ゲートに対する判定。**すべて PASS**（違反 0 件、
Complexity Tracking への追加も 0 件）。ゲートを跨ぐ論点は「設計上の判断」D-1〜D-3 に切り出した
（いずれも憲法違反ではなく、仕様の文字面と既存テストの期待値の調整である）。

- [x] **I. テスト必須（NON-NEGOTIABLE）**: **PASS**。8 本の柱すべてに、そのストーリー単体で
      検証できるテストを置く（US1 = しきい値超過の圧縮と失敗時の復帰、US2 = 再試行と
      フォールバックの両経路、US3 = 縮退の段数、US4 = 部分失敗の隔離、US5 = 設定の値域と
      解放、US6 = 採点の固定入力、US7 = 呼び出し 2 回の固定、US8 = 値域拒否と集計）。
      憲法が定義する「無効なテスト」（対象の挙動を削っても緑のままのテスト）を避けるため、
      各柱に**変異探針**を必須とする（圧縮の分岐を `pass` に／再試行の待機を削除／
      縮退の比率を 1.0 に／`return_exceptions=True` を外す／値域の `ge` を削除／
      `note()` を `emit()` に変える／`contexts` の解放を外す／対応表の 1 行を削る、
      のそれぞれで対象テストが落ちることを確認する）。
      `tools/compression.py` と `script/evaluate.py` は現行のモックで届かないため、
      フェイクの拡張（R-17）と同時にテストを書く。
- [x] **II. 外部 I/O の境界分離とオフラインテスト**: **PASS**。追加する外部 I/O は
      圧縮（LLM 呼び出し）と評価の実走のみで、前者は `tools/compression.py`、後者は
      `script/evaluate.py`（出荷パッケージの外）に置く。ノードは `tools/` の関数を呼ぶだけにする。
      上限超過の検出は `tools/llm.py` の境界に閉じ、ノードは縮退の事実だけを受け取る。
      テストは既存の境界モック（`FakeModelFactory` / `Boundary`）で完走し、ネットワークと
      実認証情報を要求しない。**評価の実走はテストの合否条件に含めない**（FR-044 / SC-018）。
      新規依存は 0。
- [x] **III. 型付きパイプライン契約**: **PASS**。`state.py` に `usage`（reducer 付き）と
      `degradations` を追加し、`models.py` に `CompressedSource` / `ModelUsage` /
      `Degradation` を追加する。`Configuration` に項目を追加する。変更は**同一変更内**で
      全参照（5 ノード・2 provider・レンダラ・CLI・README・テスト）へ波及させる。生の dict を
      新しい受け渡しとして追加しない。実行時設定は引き続き `RunnableConfig` 経由で渡し、
      provider を State に持たせない。`cache/` の JSON は既存キーを変えず、追加は
      `cache/usage.json` という**別ファイル**にする（表現の後方互換を壊さない）。
- [x] **IV. プラットフォーム抽象**: **PASS**。`graph.py` / `nodes/` に新しい
      `platform == ...` 分岐を追加しない。自己点検の必要件数・上限は provider の属性
      （既存の `max_search_queries` と新規 `Provider.required_query_count`）として宣言し、
      コアは値を解釈せずに使う。圧縮プロンプトは provider 差が無い（入力は既に整形済みの
      素材テキスト）ため `prompts.py` の単一定数とし、provider にフックを増やさない。
      `tests/unit/test_platform_scan.py` の規則 (a)+(b) を維持する（0 件のまま）。
- [x] **V. CLI 出力契約と観測可能性**: **PASS**（本機能で最も注意を要するゲート）。
      stdout / stderr / 終了コード 0・1・2 を変更しない（FR-030 / SC-012）。
      `NODE_ORDER` とグラフのノード数を一致させ、総数と表示番号は単一の定義から導出する
      既存の仕組みを維持する（ノードの追加・削除をしないため、進捗の行数も不変。FR-031 / SC-011）。
      **追加する観測は `ProgressEmitter.note()` に限定する**。これは stderr にのみ1 行を出し、
      `_messages` へは積まない。したがって `emit()` が作る `[n/7] <node> ... <phase>（<detail>）`
      の契約と、状態 `messages` の内容は不変である（実測: `tests/unit/test_analyze_content.py:374-387`
      が `messages` を厳密比較、`tests/integration/test_full_flow.py:167-181` が `(node, phase)`
      列を厳密比較）。中間成果物は `cache/` 配下の JSON（UTF-8 / `ensure_ascii=False`）という
      既存規約に従う。エラーは握りつぶさず stderr と終了コードに反映する。
      上限超過の検出器は**誤検出を許さない**（FR-018「判定できない失敗を上限超過と誤認しては
      ならない MUST NOT」）。秘密情報は追加しない。
- [x] **VI. リファクタリングは後方互換を要求しない**: **PASS**。`source_text[:20000]` の
      切り捨て経路は削除し、互換のための分岐を残さない（FR-001）。旧経路の別名・
      移行フラグを追加しない。参照実装のコードはそのまま複製しない（FR-037）。
      利用者が直接依存する契約（CLI オプション・終了コード・`TR_*` / `XTR_*` / `YTR_*`）は
      互換層ではなく**同一変更内での更新**で対応する（値域拒否の README 追記）。
      「将来使うかもしれない」抽象（複数プロバイダ向けの上限判定、汎用の実験管理）を
      先回りで追加しない。
- [x] **技術制約・品質ゲート**: **PASS**。`tasks.md` に `uv run pytest -q` / `uv run ruff check .` /
      `uv run mypy src` を最終タスクとして置く。実測ベースラインは **601 passed / カバレッジ 96.65% /
      ruff 0 errors / mypy 0 errors（27 source files）/ 49.10 秒**（2026-09-14）。
      リポジトリ全体で green を維持し、抑制（`# noqa`・除外設定）を追加しない。
      値域の宣言は `Configuration` の**加算のみ**で、`cache/` の JSON 表現を変えない。
      並列性の既定（`asyncio.Semaphore(2)`）は**値域つきの設定項目にするが既定値は 2** とし、
      既存テスト（`tests/unit/test_analyze_content.py:421` の `max_in_flight == 2`）を
      書き換えない。

### 設計後の再評価（Phase 1 完了時点）

Phase 1 で `data-model.md` と `contracts/` を書いた結果、新たに判明した論点をゲートに当て直した。
**結論は不変（違反 0 件）**。再評価で新たに固定した点は次の 3 つで、いずれもゲートを満たす方向に働く。

| ゲート | 再評価で確定した内容 |
|---|---|
| III（型付きパイプライン契約） | `usage` は `Annotated[list[ModelUsage], operator.add]` とする（現在の `AgentState` に reducer は 1 つも無い。並列実行で後勝ちになると内訳が消えるため）。`CompressedSource` / `Degradation` / `Failure` / `ModelUsage` の 4 型を `models.py` に追加し、いずれも `cache/` の既存表現に影響しない |
| V（CLI 出力契約と観測可能性） | 追加の観測は `ProgressEmitter.note()`（stderr のみ。状態 `messages` へ積まない）に限定する。`emit()` の `detail` を拡張する案は、`tests/unit/test_analyze_content.py:374-387` の厳密比較を壊すため**採用しない**（`contracts/llm-invocation-contract.md` §8 に凍結として明記） |
| I（テスト必須） | 「収集対象外のコード」（`script/evaluate.py`）を守るため、判定ロジックを `tests/eval/` へ分離し、入口の契約を `tests/unit/test_evaluation_entrypoint.py` が 5 項目で検証する形を契約として固定した |

**設計上の判断 D-1〜D-3 は Phase 1 でも維持**する。D-1 の根拠（既存テスト 7 箇所が件数を固定）は
`contracts/query-planning-contract.md` §1 に実測値として再掲し、テストで固定する対象を明示した。

**ゲート判定の根拠となる実測**（すべて 2026-09-14、リポジトリ内で実行）:

| 実測項目 | 結果 |
|---|---|
| テストスイート | **601 passed / 49.10 秒**（`uv run pytest -q`、カバレッジ計測込み） |
| カバレッジ | **96.65%**（`fail_under = 90` を満たす）。低いのは `providers/base.py` 71%（Protocol の `...` 本体）のみ |
| `ruff` | `All checks passed!`（0 件） |
| `mypy` | `Success: no issues found in 27 source files`（0 件） |
| 主要依存の版 | `openai` 3.5.0 / `langchain` 1.3.18 / `langchain-openai` 1.6.0 / `langchain-core` 1.6.1 / `langgraph` 1.2.11 / `pydantic` 2.13.4 |
| 構造化出力の既定 | `ChatOpenAI.with_structured_output(..., method="json_schema")` が既定（**実測**）。OpenAI 互換プロキシでは `json_schema` が拒否されうるため明示指定が要る（R-2） |
| 上限超過の例外型 | `openai.BadRequestError` は `APIStatusError` の派生（`APIStatusError.__init__(message, *, response, body)`）。`body` から `code` / `type` を取れる（**実測**） |
| `AIMessage.usage_metadata` | 属性は存在し、差分応答では 303 トークンが入る（`response_metadata` は空）。プロキシが返さない場合に備え「不明」経路を持つ（R-11） |
| `.gitignore` | `cache/` と `artifacts/` は追跡対象外（末尾の「Project specific」節。実測） |
| 進捗の凍結箇所 | `tests/unit/test_analyze_content.py:374-387`、`tests/integration/test_full_flow.py:167-181`、`tests/unit/test_progress.py` |
| 呼び出し回数の凍結箇所 | `tests/integration/test_full_flow.py:241-242`（analyze 5 / extract 1）、`tests/unit/test_analyze_content.py:421`（同時 2） |

## Project Structure

### Documentation (this feature)

```text
specs/003-pipeline-hardening-and-evaluation/
├── plan.md              # 本ファイル（/speckit.plan の出力）
├── spec.md              # 仕様（/speckit.specify + /speckit.clarify の出力）
├── research.md          # Phase 0 の出力（/speckit.plan）
├── data-model.md        # Phase 1 の出力（/speckit.plan）
├── quickstart.md        # Phase 1 の出力（/speckit.plan）
├── contracts/           # Phase 1 の出力（/speckit.plan）
│   ├── llm-invocation-contract.md        # 応答の契約化・再試行・縮退・上限超過の検出・使用量
│   ├── context-management-contract.md    # 圧縮・取り込み量・状態のライフサイクル・中間データ
│   ├── settings-contract.md              # 値域の宣言・単一解決経路・起動時拒否
│   ├── query-planning-contract.md        # 自己点検・件数契約・プロンプトの深化
│   └── evaluation-contract.md            # 採点・比較・フィクスチャ・実走の入口
├── checklists/
│   └── requirements.md  # 仕様品質チェックリスト（/speckit.specify / /speckit.clarify）
└── tasks.md             # Phase 2 の出力（/speckit.tasks。本コマンドでは作らない）
```

### Source Code (repository root)

```text
src/trend_researcher/
├── __init__.py                 # 変更: 公開 API（実走の入口が使う。追加のみ）
├── __main__.py                 # 変更: 値域拒否の経路（ConfigurationError → exit 2）・CLI 上書きの検証
├── configuration.py            # 変更: 値域・選択肢・UI スキーマの宣言、ConfigurationError、with_overrides
├── config.py                   # 変更なし（`load_env` / `_resolve_path` の提供元）
├── state.py                    # 変更: usage（reducer 付き）・degradations を追加
├── models.py                   # 変更: CompressedSource / ModelUsage / Degradation を追加
├── prompts.py                  # 変更: 圧縮プロンプトと、停止条件・上限・出力形式の節を追加
├── progress.py                 # 変更: ProgressEmitter.note()（stderr のみ）を追加
├── graph.py                    # 変更: 中間データの解放（compile_report 側。ノード構成は不変）
├── rendering.py                # 変更なし（レポート形式を変えない）
├── cache.py                    # 変更なし（write_json をそのまま使う）
├── tools/
│   ├── llm.py                  # 変更: 構造化出力の構築・再試行・縮退・使用量の記録
│   ├── compression.py          # 新規: しきい値超過時の圧縮（タイムアウト・失敗時の復帰）
│   ├── degradation.py          # 新規: 上限超過の検出と段階的縮小（入力を比率で削る）
│   ├── parse.py                # 変更: フォールバック経路のスキーマ整合（既存関数を維持）
│   ├── x_search.py             # 変更なし
│   ├── youtube_search.py       # 変更なし
│   └── transcript.py           # 変更なし
├── providers/
│   ├── __init__.py             # 変更なし（登録辞書は 2 行のまま）
│   ├── base.py                 # 変更: required_query_count を Protocol に宣言
│   ├── x.py                    # 変更: required_query_count = 5（値はプロンプトと一致させる）
│   └── youtube.py              # 変更: required_query_count = 1
└── nodes/
    ├── parse_instruction.py    # 変更: 構造化出力 → フォールバック（決定的事実解析は不変）
    ├── plan_search.py          # 変更: 自己点検（ノード内 1 回・設定で gate）
    ├── search.py               # 変更なし
    ├── fetch.py                # 変更なし（備考の付け方は既存のまま）
    ├── analyze_content.py      # 変更: 圧縮・並列上限の設定化・部分失敗の隔離
    ├── extract_common.py       # 変更: 構造化出力 → フォールバック
    └── compile_report.py       # 変更: 使用量の永続化・内訳の通知・生素材の解放

script/
├── analyze_structure.py        # 変更なし（既存の慣行）
└── evaluate.py                 # 新規: 評価の実走（公開 API を in-process 駆動。収集対象外）

tests/
├── conftest.py                 # 変更: FakeModelFactory の拡張（構造化出力・使用量・待機スパイ）
├── unit/                       # 変更: 既存の期待値は維持し、新規テストを追加
├── integration/
│   ├── cli_harness.py          # 変更: _FakeLLM に構造化出力・使用量・圧縮の境界を通す
│   └── ...                     # 既存の期待値は維持
└── eval/                       # 新規: 判定ロジック・採点スキーマ・フィクスチャ・対応表
    ├── evaluators.py           # 判定ロジック（LLM 呼び出しは注入された呼び出し可能オブジェクト）
    ├── schemas.py              # 採点スキーマ（観点の識別子・点数・理由）
    ├── judge_prompts.py        # 観点ごとの判定プロンプト（生成側の制約を反映）
    ├── datasets.py             # 名前付きデータセットの解決（既定は同ディレクトリの fixtures）
    ├── axes.md                 # 観点・プロンプト制約・ODR 6 評価の対応表（FR-048 / FR-074）
    └── fixtures/
        └── tr-basic.json       # 既定のデータセット（指示文の集合。内容の指紋を結果に記録）
```

**Structure Decision**: 既存の単一プロジェクト構成（`src/trend_researcher/` + `tests/`）を維持する。
新しい層は次の 2 つだけである。

1. `tests/eval/` … **テストで固定する部分**（判定ロジック・採点スキーマ・判定プロンプト・
   データセット・対応表）。`test_*.py` を置かず、`testpaths = ["tests"]` は変更しない。
   収集されるのは `tests/unit/` 側のテスト（採点ロジックを固定するもの）である。
2. `script/evaluate.py` … **実走（LLM 呼び出しを伴う手動の確認）**。`tests/` の外に置くため
   収集対象にならない（FR-066。`testpaths` の変更を要求しない）。

評価専用のコードを出荷パッケージ（`src/`）に入れない（FR-065）。出荷パッケージに足すのは
切り替え用の設定項目（`include_intermediate`）と、状態に載る中間データ（`usage` / `degradations`）
だけである。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

**違反 0 件。** Complexitiy Tracking に追加する項目はない。仕様の文字面と既存テストの期待値が
両立しない 3 点は憲法違反ではなく、上位の規範（原則 I と FR の MUST）を優先した
**設計上の判断 D-1〜D-3** として切り出してある（実装前にテストで固定し、確認を得る）。

## 次の段階への引き継ぎ

- **`/speckit.tasks` の先頭に置くタスク**（実測が設計を決めるため、実装より先に置く）:
  1. R-2 の構造化出力の方式を実測で確定（`json_schema` が通るか `function_calling` に落とすか）。
  2. R-1 の上限超過の応答を実測で確定（例外の `status_code` / `body` / メッセージ）。
  3. R-19 の判定モデルの既定値を実測で確定（実走が開始直後に失敗しない値にする）。
- **凍結する契約を最初にテストで固定するタスク**: 進捗行の文言と行数、`report.stdout` の
  byte 一致（既定の入力）、`model_fields_set` の意味、`Provider` の Protocol 走査 0 件。
- **`tasks.md` の実装メモに記録する事項**: 本ファイルの「基準値のずれ」（26 vs 27 ファイル、
  547 vs 601 passed、`analyze_content.py:65` → `:69`）。
