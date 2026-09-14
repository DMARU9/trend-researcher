# 観点の対応表（FR-038 / FR-040 / FR-048 / FR-074）

**Feature**: `003-pipeline-hardening-and-evaluation` | **更新**: 2026-09-15

評価基盤が採点する観点と、**生成側のプロンプトが課す制約**（`src/trend_researcher/prompts.py`）、
および**参照実装の 6 評価**との対応を 1 つの表にまとめる。この表は
「制約を書いたままそれを測っていない状態」（FR-048 の禁止）と
「参照実装の実測済み欠陥を持ち込むこと」（FR-063）をレビュー時に 1 箇所で確認するためのもの。

- 実装: 観点の定義は `tests/eval/evaluators.py` の `AXIS_SPECS`、制約は
  `tests/eval/judge_prompts.py` の `CONSTRAINTS` / `AXIS_CONSTRAINTS`、
  判定プロンプトは同 `JUDGE_PROMPTS`。
- 機械的な担保: `tests/unit/test_evaluation.py`（観点数・対象外の表明・制約の実在・
  全制約が測られていること・値域検査をしないこと・総合品質の集約）。

---

## 1. 観点の対応表

採点する観点は **6**（`correctness` は対象外として明示するため含めない＝表の最終行）。
「参照実装」列は参照実装 `tests/evaluators.py` の 6 評価との関係を示す。

| # | 観点の識別子 | 表示名 | 参照実装の 6 評価 | 採点 | 測る制約（`CONSTRAINTS` の識別子） | 受け取りスキーマ |
|---|---|---|---|---|---|---|
| 1 | `overall_quality` | 総合品質（下位基準 6 つの集約） | `eval_overall_quality`（採用） | する | `output_language` / `citation` / `relevance_target` | `OverallQualityScore`（下位基準 6 つ＋理由） |
| 2 | `relevance` | 関連性 | `eval_relevance`（採用） | する | `relevance_target` | `AxisScore` |
| 3 | `structure` | 構造 | `eval_structure`（採用） | する | `output_structure` / `output_purity` / `citation_count` | `AxisScore` |
| 4 | `groundedness` | 根拠性 | `eval_groundedness`（採用） | する | `citation` / `citation_context` | `AxisScore` |
| 5 | `completeness` | 網羅性 | `eval_completeness`（採用） | する | `query_count` | `AxisScore` |
| 6 | `output_language` | 出力言語の一致 | 対応なし（**本リポジトリで追加**。FR-038 が追加を許可） | する | `output_language` | `AxisScore` |
| 7 | `correctness` | 正しさ | `eval_correctness`（**対象外**） | しない | — | —（判定モデルへ送らない） |

**採点の下限との関係**: 採点する観点は 6 つで要件（5 つ以上。SC-015 / FR-038）を満たす。
`correctness` を測らない場合でも、**対象外であることを結果に明示**する（`excluded_axes` に
`["correctness"]` と理由が残る。FR-038 の「黙って落として欠落を隠さない MUST NOT」）。

**`correctness` を対象外とする理由**: 参照実装の `eval_correctness` は
`reference_outputs["answer"]`（正解の参照出力）を必要とする。本リポジトリの対象の指示
（「〜のトレンドを 5 件」など）には一意の正解を用意できないため、**採点しない**
（FR-038 / FR-074 / research R-21 の前提）。正解を人手で整備して測る判断は本仕様の範囲外。

**総合品質の下位基準（6 つ。FR-038）**: `research_depth`（研究の深さ）/
`source_quality`（情報源の質）/ `analytical_rigor`（分析の厳密さ）/ `practical_value`（実用的価値）/
`balance_and_objectivity`（中立性と客観性）/ `writing_quality`（文章の質）。
総合品質はこの 6 つの点数から**集約**し、判定モデルへ総合点を聞かない（`AXIS_SPECS[0].schema`
は 6 つすべての点と理由 1 つを受け取る `OverallQualityScore`。契約 §1）。

**値域**: 受け取りスキーマに `ge` / `le` を付けない（0 や 6、負値もそのまま記録する。FR-067 /
SC-028）。正規化は `(score - 1) / 4` で行い、範囲外の値はそのまま写す。

**比較時の扱い**: 保存済みの 2 つの結果の比較は「両方に現れる観点」を並べるため、対照外の
`correctness` も行として現れる（両側とも `normalized` が `None` なので常に引き分け）。
勝敗は採点した観点の多数決で決まり、`correctness` は勝敗に影響しない（FR-041）。

---

## 2. プロンプトの制約との対応（FR-048）

制約は `tests/eval/judge_prompts.py` の `CONSTRAINTS` が識別子で持ち、`CONSTRAINT_EVIDENCE`
に**生成側のプロンプトに実在する文言**を並べる（実在しない制約を評価項目に作らない）。
`tests/unit/test_evaluation.py` が「根拠の文言が `prompts.py` に実在すること」と
「宣言したすべての制約がどれかの観点で測られていること」を固定する。

| 制約の識別子 | 内容 | 実在の根拠（`prompts.py` の文言） | 測る観点 |
|---|---|---|---|
| `output_language` | 出力言語はトピックの言語に合わせる | 「日本語トピックなら日本語クエリ、英語なら英語クエリ」（`X_PLAN_SEARCH_PROMPT` / `YOUTUBE_PLAN_SEARCH_PROMPT`） | `output_language` / `overall_quality` |
| `query_count` | 検索クエリの件数を守る（X は 5 件ちょうど、YouTube は 1 件） | 「合計で必ず 5 件ちょうど生成すること」「クエリは 5 件を厳守すること」（`X_PLAN_SEARCH_PROMPT`）/ 「最適な検索クエリを 1 つだけ生成してください」（`YOUTUBE_PLAN_SEARCH_PROMPT`） | `completeness` |
| `citation` | 引用は原文のままで、改変・創作をしない | 「投稿内の代表的なキーフレーズ（そのまま引用できる形）」（`X_ANALYZE_CONTENT_PROMPT` / `YOUTUBE_ANALYZE_CONTENT_PROMPT`） | `groundedness` / `overall_quality` |
| `relevance_target` | 対象は「バズっている投稿」ではなく「トピックに関連する投稿」 | 「目的は「バズっている投稿」ではなく「トピックに関連する投稿」を拾うこと」（`X_PLAN_SEARCH_PROMPT`） | `relevance` / `overall_quality` |
| `output_structure` | 決められた見出し構成に従う | 「## 概要」「## ブログの活用アイデア」（`X_ANALYZE_CONTENT_PROMPT` / `YOUTUBE_ANALYZE_CONTENT_PROMPT`） | `structure` |
| `output_purity` | 出力は指定の形式だけにし、前置き・後書き・謝辞・補足説明を書かない | 「前置き・後書き・謝辞・説明を書かないこと」（8 定数の【停止条件】。T071 で追加） | `structure` |
| `citation_count` | 引用の箇条数と活用アイデアの行数を指定の範囲（3〜6）に収める | 「引用は 3〜6 箇条、活用アイデアは 3〜6 行に収める」（`X_ANALYZE_CONTENT_PROMPT` / `YOUTUBE_ANALYZE_CONTENT_PROMPT`。T071 で追加） | `structure` |
| `citation_context` | 引用には原文だけでなく、どんな文脈で語られたかの説明を添える | 「どんな文脈で語られていたか」（`X_ANALYZE_CONTENT_PROMPT` / `YOUTUBE_ANALYZE_CONTENT_PROMPT` の【出力形式】。T071 で追加） | `groundedness` |

**制約を増やすときの手順**: 先に `prompts.py` 側で制約を宣言し、`CONSTRAINTS` と
`CONSTRAINT_EVIDENCE`、測る観点（`AXIS_CONSTRAINTS`）を同時に足す。制約だけを足して
測る観点を足さない状態は FR-048 の「欠落」として扱う
（`test_every_declared_constraint_is_measured_by_an_axis` が落ちる）。

---

## 3. 参照実装の実測済み欠陥とその扱い（FR-063 / FR-074 / research R-21）

参照実装（`tests/evaluators.py` ほか）で**実測された欠陥**を列挙し、本リポジトリでの扱いと
テスト上の根拠を 1 行で示す。先頭 3 件は対応するテストで「同じ誤りを持ち込んでいないこと」を
固定する。

| # | 参照実装の欠陥（実測） | 本リポジトリの扱い | 固定する方法 | 状態 |
|---|---|---|---|---|
| 1 | `utils.py` のトークン上限検出がクラス名・モジュール名の**文字列**に依存し、`exception.code` / `exception.type` を `getattr` せず参照する | **移植しない**。`isinstance` ＋ 構造化 `body` ＋ 除外条件で判定する（R-1） | `invalid model` を含む `400` を「上限超過ではない」と判定するテスト | US3（T047〜T052） |
| 2 | 到達不能な分岐・無効なオプションの受け渡し（モデルに存在しない引数を渡す経路） | **移植しない**。縮退は入力を比率で削る（R-4） | 縮退が入力を縮めることと、引数を組み替えないことを固定 | US3（T053〜T055） |
| 3 | Model Token Limit テーブルの引き当てで未知モデルを例外にする | **移植しない**。未知モデルでも比率で縮退する（R-18） | 未知モデル名で縮退が成立するテスト | US3（T053〜T055） |
| 4 | ツール契約の非対称（同じ検証が片方の経路にしかない。例: 検索件数の検証は検索経路のみ） | **移植しない**。自己点検は生成と点検の**両方**の後で件数契約を適用する（R-13） | 点検が上限を超える件数を返す場合の切り詰めテスト | US4（T056〜T064） |
| 5 | 常に真になる条件分岐（`if x is not None and x:` のような冗長な形） | **移植しない**。検出器は条件ごとにテストを持つ | 検出器の反例テスト（4 条件それぞれ） | US4（T056〜T064） |
| 6 | 到達しない `except` 節（捕捉型が実際には投げられない） | **移植しない**。捕捉型は実測で確認する（R-1 の `isinstance`） | 捕捉型の実測に基づくテスト（R-1 の反例） | US3（T047〜T052） |

**評価基盤の側の欠陥クラスへの備え**（同じ表に載せないが、この対応表を読む前提として）:
採点の値域は検査しない（FR-067）、型違い・欠落は例外にせず「取得失敗」として記録する
（FR-039）、`correctness` を黙って落とさず `excluded_axes` に残す（FR-038）。
これらは `tests/unit/test_evaluation.py` が固定する。

---

## 4. 最終突き合わせの結果（T092。FR-048 / FR-074）

`prompts.py`（T071 が加えた【停止条件】・【出力形式】と 2 箇所への明示）・
`Configuration` の項目・この対応表の 3 つを突き合わせた結果を残す。

**(a) 制約側から評価側へ足したもの（評価項目を先に足す）**。T071 の【停止条件】と
【出力形式】には、既存の 5 制約（`output_language` / `query_count` / `citation` /
`relevance_target` / `output_structure`）に入っていない制約が 3 つ現れていた。
制約を書いたまま測らない状態（FR-048 の禁止）を作らないため、観点を増やさずに
測る側（`CONSTRAINTS` / `CONSTRAINT_EVIDENCE` / `AXIS_CONSTRAINTS`）を先に足した。

| 足した制約 | 根拠（`prompts.py` の文言） | 測る観点 |
|---|---|---|
| `output_purity` | 「前置き・後書き・謝辞・説明を書かないこと」（【停止条件】） | `structure` |
| `citation_count` | 「引用は 3〜6 箇条、活用アイデアは 3〜6 行に収める」 | `structure` |
| `citation_context` | 「どんな文脈で語られていたか」（【出力形式】の引用の説明） | `groundedness` |

**(b) `Configuration` の項目との関係**。設定は「レポートをどう作るか」を変える
（使用量・リトライ数・並列度・圧縮など）もので、**観点（何を測るか）は変えない**。
そのためこの表に「設定 → 観点」の列は置かない（置くと「設定ごとに採点項目が
変わる」と読めてしまう）。次の 2 点だけを実装側で固定している。

- 評価の実走は `Configuration.load()` を通し、`--config` のキーは
  `Configuration.model_fields` に限る（未知キーは起動時に拒否。T066）。
- 判定モデル（`TR_EVAL_MODEL`）は `Configuration` の項目にしない
  （`judge_model` / `eval_model` というフィールドを作らない。FR-069）。初期状態へ
  入れるのは `messages` / `platform` / `max_results` の 3 つだけ（FR-065）。

根拠は `tests/unit/test_evaluation_entrypoint.py`（初期状態 3 項目・判定モデルの
別解決・出荷 CLI の引数を再実装していないこと）にある。
