# Specification Quality Checklist: AI パイプラインの堅牢化と品質測定（Open Deep Research の工夫取り込み）

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-14
**Updated**: 2026-09-14（深掘り分析の結果と `/speckit/clarify` の追加確認を統合）
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- `背景と現状の実測` の表は参照実装と対象の**行番号つき実測**であり、本リポジトリの既存 spec（001 / 002）の慣行に従う。要件ではなく前提として扱う。参照実装の工夫は 8 系統（C / D / E / F / G / H / I / J）に整理した。
- 「実装詳細」の扱いについて: 本リポジトリは内部 CLI であり、要件（FR-001〜FR-074）は観測可能な挙動として記述している。関数名・モジュール名（`tools/parse.py`、`tools/llm.py` など）は既存の境界契約を指す参照としてのみ登場し、実装手段の指定ではない。Studio の `configurable`（FR-060）と `tests/` 配下の配置（FR-065 / FR-066）も、利用者に見える入力面とリポジトリの検証慣行を指す参照であり、ライブラリ選定の指定ではない。
- スコープ判断は 2 回の確認を経て確定した（Clarifications 2026-09-14 / 深掘り分析セッション）。**取り込む**: コンテキスト管理・決定的動作・品質の測定（評価基盤）・設定の宣言・使用量の計測・プロンプトの深化・自己点検。**取り込まない**: 階層型エージェント構成・反復ループ・確認ステップ・MCP 連携・配布形態・外部評価サービスへの依存。
- 品質の測定（FR-038〜FR-048 / FR-065 / FR-066）は対象に存在しない最も大きな欠落であり、利用者の判断により本仕様に統合した。実走は原則 II（テストスイートはネットワークなしで完走）と衝突するため、**テストで固定する部分と実走を分離**してある（FR-044 / SC-018）。計画時に Constitution Check でこの分離が原則 II と両立することを確認する。
- 中間データの出力（FR-046）は参照実装の `include_source_str` 方式に合わせた。すなわち**出荷される設定クラスに boolean 項目（既定は無効）を 1 つ追加し、状態と戻り値の組み立てを `if` でゲートする**（`legacy/configuration.py:42` / `legacy/graph.py:345` / `legacy/multi_agent.py:335`）。既定の実行の出力は変わらない（SC-026）。`Configuration` への項目追加は既存フィールドの削除・改名を伴わない。
- 評価結果の保存は参照実装の JSONL 出力に倣う（FR-043 / SC-027）。外部評価サービスを必須にせず、評価専用のライブラリを使う場合は開発用の追加依存に限定する（FR-045 / SC-019）。参照実装も `langsmith` を `[project.optional-dependencies]` に置いている（`pyproject.toml:17, 39`）。
- 判定スコアの扱いは参照実装に合わせた（FR-039 / FR-067）。型と必須項目は構造化出力に保証させ、**点数の値域検査は追加しない**（参照実装のスコアモデルは `int` 型＋説明文のみ。`tests/evaluators.py:26-39`）。値域外は記録のみ、型違い・欠落は取得失敗として未採点にする（SC-028）。唯一あわせないのは再試行の非対称（根拠性の評価器のみ `with_retry`。`:146`）で、FR-063（欠陥を移植しない）に従い全観点で同一規則とした（FR-068 / SC-029）。
- 評価フィクスチャと記録の形も参照実装に合わせた（FR-070〜FR-073 / SC-030〜SC-032）。指示セットは**名前付きデータセット**として指定し（`run_evaluate.py:14, 66`）、結果は `{"id", "prompt", "article"}` の 1 行 1 レコードとし（`extract_langsmith_data.py:40-45`）、ファイル名にデータセット名と対象の識別子を含める（`:50`）。**1 点のみ配置が異なる**: 参照実装はデータセットの実体を外部サービス（LangSmith）に置きリポジトリには結果のみが残る（実測: `tests/expt_results/` に 3 件、データセット定義は無い）が、対象は外部アカウントを必須にできないため（FR-045）、既定のデータセットはリポジトリ内の固定ファイルとし、外部参照は任意の経路とする。
- 評価の観点は参照実装の 6 評価を基盤とし、各観点に専用の判定プロンプトを対応させた（FR-038 / FR-040 / FR-074）。ただし「正しさ」は参照出力（正解）を必要とするため（`tests/evaluators.py:108-111`）、一意の正解を用意できない対象では**対象外として明示**し、残る 5 評価で観点数の要件を満たす（SC-033）。「出力言語の一致」など対象固有の観点は追加する。
- 自己点検（FR-049〜FR-054）は `think_tool` の考え方を取り込むが、反復ループにはせず 7 ノード構成内の 1 回に限定した。呼び出し回数の増加（注 1 回）は許容し、効果は評価基盤で測る（US6 の比較シナリオ / SC-024）。
- `背景と現状の実測 (7)` は参照実装の**実測済みの欠陥**の一覧である。特に `deep_researcher.py:338` の常に真の条件分岐による例外の握りつぶしと、上限超過の判定が実プロバイダ固有の例外クラス名に依存する点を移植統制（FR-063 / FR-064）で禁止している。
- `FR-031`（7 ノード維持）は原則 V（`NODE_ORDER` とグラフのノード数の一致）と連動する。計画時に Constitution Check で整合を確認する。
- `FR-024` / `FR-025`（設定の単一解決経路）および `FR-058` / `FR-059`（値域の宣言）は、技術制約と品質基準の `Configuration` の扱いに触れる。計画時に改正要否を判定する。
- 値域外の設定値の扱いは、参照実装と異なり**起動時に拒否**とした（FR-024 / FR-058 / SC-023）。参照実装は Studio の UI をスライダーにして範囲を UI 側で守らせ、環境変数の値域検査を持たない（`ge` / `le` なし）。対象は環境変数経由の誤設定（並列数 0 でセマフォが停止する等）を防ぐため、拒否（終了コード 2・丸めなし）を採用する。既存フィールドに値域を追加した場合は従来受理していた値が新たに拒否されうるため、計画時に終了コード 2 の範囲内であることと既存テスト（FR-035 / SC-012）への影響を確認する。
- 判定（採点）に用いるモデルは `.env` / 環境変数（`TR_EVAL_MODEL`）で指定し、出荷する設定クラスには追加しない（FR-069 / SC-034）。参照実装は `tests/evaluators.py:8-10` で `ChatOpenAI(model="gpt-4.1")` を直に構築しており、対象は接続設定（`OPENAI_BASE_URL` / `x-opencode-session`）の都合で `tools/llm.py` の経路に寄せる（FR-045）。判定モデルはノード実行の設定ではないため FR-024 / FR-025 の対象外とし、計画時にこの線引きを確認する。
- 評価結果の保存先は `artifacts/eval/`（リポジトリの成果物置き場・追跡対象外）とし、参照実装の `tests/expt_results/` へのコミットとは異なる（FR-043 / SC-027）。成果物をコミットしない既存方針（`artifacts/` は `.gitignore` 済み）に合わせたもので、計画時にこの線引きを確認する。
- 実走の経路は公開 API の **in-process 呼び出し**とした（FR-065 / SC-035）。参照実装の `client.aevaluate(graph, ...)` に倣う。CLI の subprocess 経由は中間データ（FR-046）に到達できないため採らない。初期状態の組み立て（最小 3 項目）のみを複製し、CLI の引数解釈は再実装しない（FR-063）。計画時に「公開 API を実走から呼ぶ」ことと「出荷パッケージに評価コードを入れない」（FR-037 / FR-065）の両立を確認する。
- 2 構成の比較は**生成と判定を分離**した（FR-041 / FR-072 / SC-016）。参照実装の `evaluate_comparative((実験A, 実験B), ...)` に倣い、構成ごとに 1 回実走して保存し、比較は保存済みの結果を名前で指定する。判定のみを再実行できることを優先し、生成のやり直しを強制しない。計画時に比較対象の識別子の持ち方（FR-072 のファイル名）を確認する。
- 「自己点検あり／なし」の構成差は、出荷設定クラスの真偽値項目（既定は有効）で作る（FR-054 / SC-036）。参照実装の `include_source_str` と同じ形をとり、評価専用の切り替え手段を別に持たない。無効時は生成 1 回で確定する（FR-053 / SC-021）。計画時に、この項目と FR-046 の中間データの切り替えが独立していることと、既存フィールドの追加のみで済むことを確認する。
