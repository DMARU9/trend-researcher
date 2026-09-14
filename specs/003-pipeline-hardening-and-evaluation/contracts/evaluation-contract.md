# Contract: 評価基盤（採点・比較・フィクスチャ・実走の入口）

**Feature**: `003-pipeline-hardening-and-evaluation` | **Date**: 2026-09-14

**対応要件**: FR-038〜048 / FR-065〜074 / FR-044 / FR-045 / SC-015 / SC-016 / SC-018 /
SC-026〜SC-028 / SC-034 / SC-035

**境界**: `tests/eval/`（テストで固定する部分。出荷パッケージには入れない）と
`script/evaluate.py`（実走。収集対象外）。

## 1. 採点の契約

| 項目 | 契約 |
|---|---|
| 観点数 | 6（`correctness` を含めると 7。`correctness` は**対象外**として明示。FR-038） |
| 採点の下限 | 5 観点以上を実際に採点する（SC-015） |
| 受け取り | 構造化スキーマ（`AxisScore`）で識別子・点数・理由を受ける（FR-039） |
| 正規化 | 1〜5 → 0〜1（`(score - 1) / 4`）。生の点数も保存する |
| 総合品質 | 6 観点の `normalized` の平均（`None` は除外）。**LLM に総合点を聞かない** |
| 値域検査 | **行わない**（`ge` / `le` なし）。範囲外の値もそのまま記録（FR-067 / SC-028） |
| 型違い・欠落 | 「取得失敗」として扱う。`score = None`、`error` に理由を入れる。**例外を送出しない** |
| 再試行 | 全観点で同一の規則（FR-068）。1 観点の失敗で全体を落とさない |
| 判定プロンプト | 観点ごとに専用（生成側の制約を反映。FR-040） |
| 中間データ | **一時ファイル・作業ディレクトリを作らない**。結果の JSONL のみを書く（FR-046 の趣旨） |

**要件対応**: FR-038（6 評価を基盤・5 つ以上・総合品質は下位基準の集約・正しさは対象外明示）/
FR-039（識別子・点数・理由を構造化スキーマで受け 0〜1 に正規化）/ FR-040（観点ごとの専用プロンプト）/
FR-067（値域検査を追加しない）/ FR-068（判定の再試行は全観点同一）。

## 2. 比較の契約

| 項目 | 契約 |
|---|---|
| 生成の回数 | **構成ごとに 1 回**（FR-041。同じ構成を 2 回生成しない） |
| 提示順 | 観点の提示順を**ランダム化**し、使った順序を `axis_order` に記録（FR-041） |
| 再実行 | **判定のみ**再実行できる（生成結果を保存済みのファイルから読む） |
| 比較の単位 | 保存済みの 2 つ（以上）を**名前で指定**して比較する（SC-016） |
| 数値の併記 | トークン数と呼び出し回数を結果に併記（FR-042） |
| 構成の区別 | ファイル名の `{config_name}` 識別子で区別（FR-072） |

**要件対応**: FR-041（提示順のランダム化・構成ごとに独立実行・保存結果を名前指定で比較・
判定のみ再実行可）/ FR-042（トークン数と呼び出し回数の併記）/ SC-016。

## 3. フィクスチャと記録の契約

| 項目 | 契約 |
|---|---|
| データセット | 名前付き（既定 `tr-basic`）。既定は `tests/eval/fixtures/tr-basic.json`（FR-070） |
| 外部サービス | 必須にしない（FR-070） |
| レコード | `{"id": str, "prompt": str}` の 2 項目。結果の 1 行には `article` を加えた 3 項目（FR-071） |
| ファイル名 | `{dataset}__{config_name}__{commit}__{model_slug}.jsonl`（FR-072 / FR-043） |
| 指紋 | データセット名と内容の指紋（`id` と `prompt` を並べた SHA-256 の先頭 16 文字）を記録（FR-073） |
| 保存先 | 既定 `artifacts/eval/`（追跡外）。`--out` / `TR_EVAL_OUT_DIR` で変更（FR-043） |
| 書き込み | 追記（`a`）。既存を上書きするには `--overwrite` を要求（SC-027） |
| 記録する文脈 | 設定の中身と識別子、データセット名と指紋、コミット識別子、**判定モデル名**（FR-043） |
| 形式 | JSONL 1 行 1 レコード。UTF-8、`ensure_ascii=False`（既存の `cache.py` と同じ方針） |

**要件対応**: FR-043（設定・フィクスチャ・コミット識別子・判定モデル名とともに保存・JSONL）/
FR-070（名前付きデータセット・既定はリポジトリ内） / FR-071（3 項目 1 行 1 レコード）/
FR-072（ファイル名に名前と対象識別子）/ FR-073（指紋の記録）/ SC-027。

## 4. 実走の入口の契約（FR-065 / FR-066 / SC-035）

**場所**: `script/evaluate.py`（`tests/` の外。`testpaths = ["tests"]` の収集対象外）。

```
script/evaluate.py --dataset tr-basic --platform x \
  --config configs/baseline.json --config configs/candidate.json \
  [--config-name baseline --config-name candidate] \
  [--judge-model <name>] [--out artifacts/eval] [--overwrite] \
  [--judge-only <file>]
```

| # | 契約 |
|---|---|
| 1 | CLI の引数契約を**変更しない**（`__main__.py` のオプションを増やさない。FR-065） |
| 2 | 評価依存を出荷経路に含めない（`src/` は評価のコードを参照しない。FR-065） |
| 3 | 生成は**公開 API を in-process** で呼ぶ（`trend_researcher.ainvoke(state, config)` → `render_report(...)`。SC-035） |
| 4 | **CLI の subprocess を使わない**（`subprocess` を import しない。FR-065 / SC-035） |
| 5 | 初期状態の複製は 3 項目に限る（`messages` 1 件 / `platform` / 明示時のみ `max_results`。FR-065） |
| 6 | `__main__.py` の引数解釈（`--since` の解析・出力形式の既定・`env_prefix` の適用）を**再実装しない**（FR-065） |
| 7 | 必要な値（プラットフォーム・フィクスチャ・保存先・判定モデル）は**引数または環境変数**で与える（FR-066） |
| 8 | テストの収集対象に含めない（`testpaths` を変更しない。FR-066 / SC-018） |
| 9 | 判定モデルは生成と別に解決する（`TR_EVAL_MODEL` → 既定。`Configuration` に項目を足さない。FR-069 / SC-034） |
| 10 | 生成と同一モデルでの実行も可能とし、**その事実を結果に記録**する（FR-069） |
| 11 | 使用するモデル名を結果の設定識別子に含める（FR-069） |
| 12 | **実走をテストの合否条件に含めない**（FR-044 / SC-018） |
| 13 | 値域検査を追加しない（FR-067 / SC-028） |

**公開 API の使い方（実測に基づく）**:

```python
from langchain_core.messages import HumanMessage
from trend_researcher import trend_researcher, render_report

state = {"messages": [HumanMessage(content=prompt)], "platform": platform}
if max_results is not None:
    state["max_results"] = max_results
config = {"configurable": settings.model_dump()}
result = await trend_researcher.ainvoke(state, config)
markdown = render_report(result["report"])
```

**要件対応**: FR-065（独立スクリプト・CLI 契約の不変・in-process・subprocess 禁止・
3 項目の複製・引数解釈の非再実装）/ FR-066（収集対象外・値は引数/env）/ SC-035。

## 5. 依存と境界の契約

| 項目 | 契約 |
|---|---|
| 新規依存 | 追加しない（実行時・開発時とも。FR-045 / SC-014） |
| 判定の呼び出し経路 | 既存の `tools/llm.py` の経路（`build_model`）を使う（FR-045） |
| `ChatOpenAI` の直接構築 | 禁止（`tools/llm.py` の 1 箇所のみ。FR-045） |
| 外部評価サービス | 必須にしない（FR-045） |
| 出荷パッケージへの配置 | 評価のコードを `src/` に置かない（FR-065 / FR-074） |
| 実走の副作用 | `artifacts/` と `cache/` の外にファイルを作らない |

## 6. 収集対象外のコードを守る方法

`script/evaluate.py` はテストの収集対象外であるため、**そのままでは未検証のコード**になる。
次の 2 段で守る。

| 層 | 内容 |
|---|---|
| (a) ロジックの分離 | 判定ロジック・採点スキーマ・判定プロンプト・データセット解決・レコード整形を `tests/eval/` に置き、`tests/unit/test_evaluation.py` が**固定入力で**検証する（LLM 呼び出しなし） |
| (b) 入口の契約の検証 | `tests/unit/test_evaluation_entrypoint.py` が `script/evaluate.py` を `importlib` で読み込み、下の 5 項目を検証する |

`tests/unit/test_evaluation_entrypoint.py` が検証する 5 項目:

| # | 検証 |
|---|---|
| 1 | `pyproject.toml` の `testpaths` が `["tests"]` のまま（FR-066） |
| 2 | argparse のオプション集合が期待どおり（`--dataset` / `--platform` / `--config` / `--config-name` / `--judge-model` / `--out` / `--overwrite` / `--judge-only`） |
| 3 | `subprocess` を import していない（FR-065 / SC-035） |
| 4 | `trend_researcher` の公開 API（`trend_researcher` / `render_report`）を参照している（SC-035） |
| 5 | 初期状態に入れるキーが `messages` / `platform` / `max_results` のみ（AST で `state[...] = ...` の右辺キーを列挙。FR-065） |

**要件対応**: FR-044（実走をテストの合否条件に含めない）/ FR-066 / SC-018。

## 7. 検証（この契約を固定するテスト）

| テスト | 何を固定するか |
|---|---|
| `tests/unit/test_evaluation.py`（新規） | 採点スキーマの受け取り、正規化、総合品質の集約、値域検査をしないこと、型違い・欠落の扱い、観点数の下限、対応表の整合 |
| `tests/unit/test_evaluation_entrypoint.py`（新規） | 5 項目（`testpaths`・オプション集合・`subprocess` 不使用・公開 API・3 項目の初期状態） |
| `tests/unit/test_evaluation_records.py`（新規） | ファイル名の規則、指紋、追記と `--overwrite`、JSONL の 1 行 1 レコード、`ensure_ascii=False` |

**変異探針**:

| 変異 | 期待 |
|---|---|
| `script/evaluate.py` に `subprocess` を import する | 入口の契約テストが落ちる |
| 初期状態に 4 つ目のキーを足す | 入口の契約テストが落ちる |
| `testpaths` に `script` を足す | 入口の契約テストが落ちる |
| 採点に `ge=1` を付ける | 値域検査のテストが落ちる |
| 総合品質を `sum` に変える（`mean` から） | 集約のテストが落ちる |
| 既存ファイルを無条件に上書きする | 追記のテストが落ちる |
| 観点を 4 つに減らす | 観点数の下限テストが落ちる |
