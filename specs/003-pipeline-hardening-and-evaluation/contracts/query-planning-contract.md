# Contract: 検索クエリの計画（自己点検・件数契約・プロンプト）

**Feature**: `003-pipeline-hardening-and-evaluation` | **Date**: 2026-09-14

**対応要件**: FR-049〜054 / FR-055〜058 / FR-002 の一部 / SC-021 / SC-036

**境界**: `src/trend_researcher/nodes/plan_search.py`（生成と自己点検）と
`src/trend_researcher/prompts.py`（プロンプトの契約）。
件数の契約は `src/trend_researcher/providers/base.py` の属性として**provider が宣言**する。

## 1. 自己点検の契約

| 項目 | 契約 |
|---|---|
| 実装の位置 | `nodes/plan_search.py` の**同一ノード内**。新しいノードを作らない（FR-031 の 7 ノード維持） |
| 回数 | **1 ノード実行につき 1 回だけ**（FR-050）。ループしない |
| 呼び出し回数 | 生成 1 回 ＋ 点検 1 回 = **2 回**。有効時は 2、無効時は 1（FR-053 / SC-021 / SC-036） |
| 出力の解析 | 生成と同じ経路（行分割 ＋ `_clean_query`）。構造化出力は使わない |
| 点検が行うこと | (a) 重複の除去、(b) 生成結果より少ない場合の**補充**、(c) 上限（`max_search_queries`）の適用、(d) 期間表現（`_PERIOD_RE` / `_YEAR_RE`）の除去 |
| 点検が**行わない**こと | 件数を `required_query_count` まで**増やす**こと（D-1）、反復して改善すること、生成結果に無いクエリを創作すること |
| 失敗時 | 生成結果をそのまま採用して継続（FR-051）。例外を送出しない。`note()` に 1 行 |
| 切り替え | `Configuration.self_review`（真偽値。既定 `True`）。**評価専用の切り替えを別に設けない**（FR-054） |

### 適用規則（順序が契約）

| # | 入力の状態 | 出力 |
|---|---|---|
| 1 | 点検の出力が 0 行 | 生成結果をそのまま採用（差分なし。FR-051 / Edge Case） |
| 2 | 点検の出力が生成結果より少ない | 生成結果から補充し、**生成結果の件数を下回らない**（Edge Case / US7 シナリオ 1。D-1） |
| 3 | 点検の出力が生成結果より多い | `max_search_queries` で切り詰める（X = 8、YouTube = `None` = 無制限） |
| 4 | 重複がある（正規化後） | 先に現れたものを残す |
| 5 | 生成結果が 0 件 | 点検しても 0 件（固定件数まで増やさない） |

**要件対応**: FR-049（同一ノード内で 1 回の自己点検）/ FR-050（呼び出し回数を 1 回に固定）/
FR-051（失敗時は生成結果で継続）/ FR-052（点検後も provider 契約を満たす）。

### D-1 の理由（実測）

「X は 5 件ちょうど」を強制すると、次の既存テストが落ちる（FR-035 が期待値の書換を禁じる）。

| テスト | 固定している件数 |
|---|---|
| `tests/unit/test_plan_search.py:108` | 3 件 |
| `tests/unit/test_plan_search.py:113` | 2 件 |
| `tests/unit/test_plan_search.py:118` | 8 件（上限で切り詰め） |
| `tests/unit/test_plan_search.py:128` | 12 件（YouTube は無制限） |
| `tests/unit/test_plan_search.py:134` | 8 件 |
| `tests/unit/test_plan_search.py:139` | 0 件 |
| `tests/integration/test_full_flow.py:228` | 2 件 |

既定のプロンプトは X に 5 件を指示しているため、**既定運用では 5 件**である。
点検が件数を減らさない規則なので、既定の入力でも 5 件のまま（US7 シナリオ 3 は満たす）。

## 2. 件数契約の宣言（provider）

| provider | `max_search_queries`（上限） | `required_query_count`（追加） | 出典 |
|---|---|---|---|
| X | `8` | `5` | `providers/x.py` のプロンプトが 5 件を指示（実測: `providers/x.py:89` のコメント「LLM が 5 件を守らなくても安全に切り詰める」） |
| YouTube | `None`（単一クエリの設計） | `1` | `providers/youtube.py` が `max_search_queries = None`（実測）。`search` は先頭の 1 件を使う |

**契約**:

1. `required_query_count` は `Provider` Protocol に宣言する（`int | None`）。実装側にも**明示の注釈**を
   付ける（`required_query_count: int | None = 5`。mypy は Protocol の可変属性を不変として扱うため）。
2. コアは値を解釈しない（`platform == "..."` を書かない。原則 IV）。
3. 用途は (a) プロンプトが指示する件数との一致をテストで確認する、(b) 規則 2（補充）の上限。
   **固定件数への引き上げには使わない**（D-1）。
4. `tests/unit/test_platform_scan.py` の規則 (a)+(b) は 0 件のまま（属性の追加は対象外）。

## 3. プロンプトの契約（FR-055〜058）

各プロンプト定数（`prompts.py` の 8 つ ＋ 追加の `COMPRESSION_PROMPT`）に次の節を持つ。

| 節 | 内容 | 要件 |
|---|---|---|
| 目的・役割 | 何をするか 1〜2 文 | 既存 |
| 入力 | 差し込まれる値（`{topic}` / `{transcript}` 等）を列挙 | 既存 |
| **停止条件** | 出力できるのは指定の形式のみ。前置き・後書き・謝辞を書かない。件数・長さの上限を明示 | FR-055 |
| **判定不能表現の禁止** | 「おそらく」「不明だが」で埋めない。不明は空にする | FR-056 |
| **出力形式** | 種類別の構造例（見出しの付け方、箇条書きの記号、JSON ブロックの形） | FR-057 |
| **重要制約の二重明示** | 出力言語・件数・引用形式の 3 つを、(a) 役割説明の直後と (b) 出力形式の節の**2 箇所**に置く | FR-058 |

**禁止**: 「以下のテンプレートをそのまま使う」という指示（固定テンプレート。FR-057）。

**要件対応**: FR-055（停止条件を機械判定可能に）/ FR-056（判定不能表現のみでの提示の禁止）/
FR-057（種類別の構造例・固定テンプレートの禁止）/ FR-058（重要制約を 2 箇所で明示）。

## 4. プロンプトと評価観点の対応（FR-048 / FR-074）

`tests/eval/axes.md` の対応表が、次の 3 つを 1 つの表に記録する。

| 列 | 内容 |
|---|---|
| 観点 | `tests/eval/` の 6 観点の識別子 |
| プロンプト制約 | 対応する `prompts.py` の制約（例: `constraint_compliance` ↔ `出力言語` / `件数` / `引用形式`） |
| 参照実装の 6 評価との対応 | 採用（同じ観点）/ 対象外（理由を書く）。`correctness` は対象外と明記 |

**走査テスト**: `tests/unit/test_evaluation.py` が対応表を読み、
(a) 観点の数が 5 以上であること（SC-015）、(b) `correctness` が対象外と記録されていること、
(c) 各行が実在する観点と実在するプロンプトの節を指していることを検証する。

## 5. 凍結する契約（変更してはならない）

| # | 契約 | 実測による固定箇所 |
|---|---|---|
| 1 | `plan_search` の**1 番目**のプロンプトが生成プロンプトであること | `tests/unit/test_plan_search.py:147/152/157/163/170` が `prompts_for("plan_search")[0]` を参照 |
| 2 | 生成プロンプトに `トピック: {topic}` / `投稿日フィルタ` の有無が正しく反映されること | 同上（`:147` / `:170`） |
| 3 | 検索クエリの件数と内容（既定の入力で不変） | `tests/unit/test_plan_search.py:108-139`、`tests/integration/test_full_flow.py:228` |
| 4 | 進捗行 `クエリ N 件: ...` の文言 | `tests/unit/test_plan_search.py`、`tests/integration/test_full_flow.py` |
| 5 | `search` ノードが先頭の `max_search_queries` 件（YouTube は 1 件）を使うこと | `tests/unit/test_search.py`、`tests/unit/test_youtube_search.py` |
| 6 | provider 登録辞書（`providers/__init__.py` の 2 行） | `tests/unit/test_platform_scan.py` |

**順序の固定**: 点検の呼び出しは生成の**後**に行い、`prompts_for("plan_search")` の `[0]` が
生成プロンプトであり続けることをテストで固定する（新規テスト）。

## 6. 検証（この契約を固定するテスト）

| テスト | 何を固定するか |
|---|---|
| `tests/unit/test_plan_search.py`（拡張） | 呼び出し 2 回（有効）/ 1 回（無効）、規則 1〜5、`[0]` が生成プロンプト、`required_query_count` との一致 |
| `tests/unit/test_providers.py`（拡張） | `required_query_count` の宣言（X = 5 / YouTube = 1）と注釈の型 |
| `tests/unit/test_prompts.py`（新規） | 8 ＋ 1 の定数が停止条件・出力形式・二重明示の節を持つこと、禁止語（固定テンプレート）が無いこと |
| `tests/integration/test_full_flow.py`（不変の確認） | 既定の入力で進捗と検索クエリが変わらないこと |

**変異探針**:

| 変異 | 期待 |
|---|---|
| 点検の呼び出しを削る | 呼び出し回数のテストが落ちる（有効時の 2 回が 1 回になる） |
| 点検の結果をそのまま採用する（補充を削る） | 規則 2 のテストが落ちる |
| `self_review` の既定を `False` にする | 呼び出し回数のテストが落ちる |
| 生成プロンプトの件数を 3 に変える | `required_query_count` との一致テストが落ちる |
| 二重明示の 1 箇所を削る | プロンプトの走査テストが落ちる |
| 点検を生成の**前**に呼ぶ | プロンプト順序のテストが落ちる |
