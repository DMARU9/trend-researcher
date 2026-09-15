# Phase 1 Data Model: AI パイプラインの堅牢化と品質測定

**Feature**: `003-pipeline-hardening-and-evaluation` | **Date**: 2026-09-14

**Input**: [spec.md](./spec.md) / [plan.md](./plan.md) / [research.md](./research.md)

DB を持たないため、すべてのエンティティは **Pydantic モデル**（`src/trend_researcher/models.py` /
`configuration.py`）または **LangGraph の状態フィールド**（`state.py`）として表す。
評価基盤のエンティティは**記録のスキーマ**（`tests/eval/` が扱う辞書）であり、
出荷パッケージには入れない（FR-065 / FR-074）。

凡例: **追加** = 新規エンティティ、**変更** = 既存エンティティへの追加項目、
**不変** = 変更しない（凍結）。

---

## 1. 設定エンティティ

### 1.1 `Configuration`（変更: 追加のみ。既存フィールドの削除・改名なし）

既存 7 フィールドは**そのまま**（`platform` / `output_format` / `max_results` / `sort_by` /
`transcript_language` / `cache_dir` / `published_after`）。以下は**追加分**のみ。

| フィールド | 型 | 値域 / 選択肢 | 既定 | 説明（`description` に入る文言） | 対応要件 |
|---|---|---|---|---|---|
| `analysis_concurrency` | `int` | `1 ≤ n ≤ 16` | `2` | `個別解析の同時実行数` | FR-024 / FR-059 |
| `retry_max` | `int` | `0 ≤ n ≤ 10` | `2` | `LLM 応答が契約を満たさないときの再試行回数（初回を除く）` | FR-010 |
| `retry_wait_seconds` | `float` | `0 ≤ x ≤ 60` | `1.0` | `再試行の前に待つ秒数` | FR-010 |
| `compression_threshold` | `int` | `1000 ≤ n` | `20000` | `素材がこの文字数を超えたら LLM で圧縮する` | FR-005 |
| `compression_timeout_seconds` | `float` | `1 ≤ x ≤ 300` | `60.0` | `圧縮 1 回あたりのタイムアウト秒` | FR-005 |
| `degrade_max_attempts` | `int` | `1 ≤ n ≤ 10` | `3` | `上限超過のときに入力を縮小して再試行する最大段数` | FR-015 / FR-019 |
| `shrink_ratio` | `float` | `0.1 ≤ x ≤ 0.9` | `0.9` | `縮退 1 段あたりの入力長の比率` | FR-016 |
| `min_input_chars` | `int` | `100 ≤ n` | `1000` | `縮退を打ち切る入力長の下限` | FR-015 |
| `self_review` | `bool` | — | `True` | `検索クエリを生成直後に点検するか` | FR-054 |
| `include_intermediate` | `bool` | — | `False` | `圧縮・縮退・失敗の中間データを cache に書き出すか` | FR-046 |
| `structured_method` | `Literal["json_schema", "function_calling"]` | 2 択 | `"function_calling"` | `構造化出力の方式` | FR-009 / research R-2 |

**不変条件**:

1. **既定値は現行の挙動と同じ**。`analysis_concurrency = 2` は現行の
   `asyncio.Semaphore(2)` と一致し、`compression_threshold = 20000` は現行の
   `source_text[:20000]` と一致する。既定で動かしたときの出力と呼び出し回数を変えない
   （FR-035 / SC-011 / SC-026）。
2. `model_fields_set` の意味（明示指定 > 環境変数）を変えない。実測で依存している箇所:
   `providers/x.py:48`、`tests/unit/test_config.py:266`、`tests/unit/test_configuration.py:281`。
3. `load()` が env から解決するのは既存 3 項目（`max_results` / `transcript_language` /
   `cache_dir`）＋ 追加分（`TR_ANALYSIS_CONCURRENCY` / `TR_RETRY_MAX` /
   `TR_RETRY_WAIT_SECONDS` / `TR_COMPRESSION_THRESHOLD` / `TR_COMPRESSION_TIMEOUT_SECONDS` /
   `TR_DEGRADE_MAX_ATTEMPTS` / `TR_SHRINK_RATIO` / `TR_MIN_INPUT_CHARS` / `TR_SELF_REVIEW` /
   `TR_INCLUDE_INTERMEDIATE` / `TR_STRUCTURED_METHOD`）。プレフィックスは既存の
   `resolve_env`（`TR_{name}` → `{env_prefix}_{name}` → 既定）をそのまま使う。
4. 追加フィールドに `json_schema_extra={"x_oap_ui_config": {...}}` を付ける（FR-060）。
   Studio の `configurable` に表示され、変更できる。

### 1.2 `ConfigurationError`（追加）

| 項目 | 内容 |
|---|---|
| 型 | `Exception` の派生（`src/trend_researcher/configuration.py`） |
| 必須属性 | `field: str` / `value: object` / `expected: str` / `message: str` |
| 発生条件 | 値域外（`ge` / `le` 違反）、型違い（`Literal` の選択肢外、`int` に非数値）、比率の範囲外 |
| 送出される場所 | `Configuration.load()` / CLI 上書きの適用後（`__main__.py` の起動時検証） |
| 受け取り側の契約 | `__main__.py` が捕捉して **stderr に `message` を出し、exit 2**（FR-024 / SC-023） |
| 禁止される回復 | 丸め（`max_results = 0` → `1`）、既定値への置換、警告のみで続行（FR-024 の MUST NOT） |

**メッセージの形**（項目名・入力値・期待する値域を必ず含む）:

```
設定が不正です: max_results=0（期待: 1 以上 100 以下の整数）
設定が不正です: shrink_ratio=1.5（期待: 0.1 以上 0.9 以下の実数）
設定が不正です: structured_method="auto"（期待: json_schema または function_calling）
```

### 1.3 検証のタイミング（値域の宣言と適用の対応）

| 段階 | 何が起きるか | 備考 |
|---|---|---|
| `Configuration.load(env_prefix)` | env を読み、型変換する（`int()` / `float()` / `bool` 判定）。値域違反はここで `ConfigurationError` | 起動時に 1 回 |
| CLI 上書き（`model_copy(update=...)`） | **検証されない**（Pydantic v2 の仕様。実測） | 上書き項目はここで無検証で入る |
| 起動時検証（追加） | 上書き適用後に、値域を**明示的に検査**する。違反は `ConfigurationError` → exit 2 | research R-10 の実測に基づく実装位置の決定 |
| `from_runnable_config(config)` | `configurable` から `cls(**{...})` する。ここでも Pydantic の `ge` / `le` が働く | ノード側の最終防衛線（FR-025 の単一経路） |

---

## 2. 状態エンティティ（`state.py`）

### 2.1 `AgentState`（変更: 追加 4 フィールド。既存フィールドは不変）

| フィールド | 型 | reducer | 説明 | 対応要件 |
|---|---|---|---|---|
| `compressed` | `list[CompressedSource]` | なし（後勝ち） | 圧縮を行った対象の記録。`analyze_content` が設定する | FR-001 / FR-019 |
| `degradations` | `list[Degradation]` | なし（後勝ち） | 縮退の段の記録。段ごとに追記される | FR-017 / FR-019 |
| `failures` | `list[Failure]` | なし（後勝ち） | 部分失敗（解析・取得）の記録 | FR-021 / FR-023 |
| `usage` | `Annotated[list[ModelUsage], operator.add]` | **`operator.add`** | LLM 呼び出し 1 回につき 1 要素。並列ノードの結果を連結する | FR-061 / FR-062 |

**reducer が必要な理由**: `analyze_content` は `asyncio.gather` で並列に LLM を呼ぶ。
ノードの戻り値は 1 つの dict にまとめて返すため、ノード内では reducer を経由しないが、
将来 2 つ以上のノードが `usage` を返す（`parse_instruction` / `plan_search` /
`extract_common` も返す）ため、通常フィールドでは**後から書いたノードの要素だけが残る**。
`Annotated[..., operator.add]` にすることで全ノード分が連結される（実測: `AgentState` は
現状すべて通常フィールドであり、reducer は 1 つも無い）。

**不変条件**:

1. `usage` は**レポートに含めない**（D-3。`ResearchReport` のフィールドを増やさない）。
2. `compressed` / `degradations` / `failures` は `include_intermediate = False` でも
   **状態には載る**（実行中の観測のため）。ファイルに書くかどうかだけが切り替わる（FR-046）。
3. 解放（R-8）の対象は `contexts` と `candidates` の**中身**のみ。`usage` /
   `degradations` / `failures` / `analyses` / `common_themes` / `report` は解放しない。

### 2.2 `AgentInputState`（不変）

`messages` / `platform` / `max_results` の 3 つのみ。評価の実走（R-15）はこの 3 項目だけを
組み立てる（FR-065）。

---

## 3. 新規モデル（`models.py`）

### 3.1 `CompressedSource`（追加）

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `source_id` | `str` | ✓ | 圧縮対象の識別子（`Candidate.id`） |
| `input_chars` | `int` | ✓ | 圧縮前の素材の文字数 |
| `output_chars` | `int` | ✓ | 圧縮後の素材の文字数（しきい値以下。FR-007） |
| `applied` | `bool` | ✓ | 実際に LLM で圧縮したか（`False` = 失敗して切り詰めた） |
| `reason` | `str` | ✓ | `"compressed"` / `"timeout"` / `"error"` / `"empty"`（失敗時の理由） |

**検証規則**: `applied = True` なら `output_chars <= compression_threshold`
（FR-007。プロンプトの指示ではなく**実装側の切り詰め**で保証する。R-5）。

### 3.2 `Degradation`（追加）

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `node_name` | `str` | ✓ | 縮退が起きたノード（`NODE_ORDER` のいずれか） |
| `stage` | `int` | ✓ | 段番号（1 始まり。1 が初回の縮小） |
| `before_chars` | `int` | ✓ | 縮小前の入力長 |
| `after_chars` | `int` | ✓ | 縮小後の入力長 |
| `reason` | `str` | ✓ | `"token_limit"` 固定（圧縮と区別する。FR-019） |
| `limit_known` | `bool` | ✓ | モデルの上限が既知だったか（R-18） |

**検証規則**: `after_chars < before_chars`（縮小しない段は記録しない。R-4 の停止条件 2）。

### 3.3 `Failure`（追加）

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `kind` | `Literal["analysis","context"]` | ✓ | 失敗した段（個別解析 / 追加文脈の取得） |
| `id` | `str` | ✓ | 失敗した対象の識別子 |
| `error_type` | `str` | ✓ | 例外の型名（`RuntimeError` 等） |
| `message` | `str` | ✓ | 短いメッセージ（先頭 200 文字に切り詰める） |

**検証規則**: 無言の欠落を禁止する（FR-021）。`analyses` に無い `id` は `failures` にあるか、
そもそも候補に無いかのいずれかであること（テストで固定する）。

### 3.4 `ModelUsage`（追加）

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `node_name` | `str` | ✓ | 呼び出し元のノード（`NODE_ORDER` のいずれか。圧縮は `analyze_content`） |
| `role` | `str` | ✓ | `build_model` に渡した役割（`research` / `summary` / `final` / `compression`） |
| `model` | `str` | ✓ | モデル名（`init_chat_model` に渡した文字列） |
| `input_tokens` | `int \| None` | ✓ | 不明なら `None`（FR-061） |
| `output_tokens` | `int \| None` | ✓ | 同上 |
| `total_tokens` | `int \| None` | ✓ | 同上 |
| `structured` | `bool` | ✓ | 構造化出力の呼び出しだったか |

**派生値**（`cache/usage.json` に書く集計）:

| キー | 型 | 説明 |
|---|---|---|
| `calls` | `int` | 呼び出し回数の合計（`usage` の要素数） |
| `unknown_calls` | `int` | `total_tokens` が `None` の呼び出し数 |
| `input_tokens` / `output_tokens` / `total_tokens` | `int` | 判明分の合計（不明は 0 として加算し、`unknown_calls` で明示） |
| `by_node` | `dict[str, int]` | ノードごとの呼び出し回数 |
| `by_role` | `dict[str, int]` | 役割ごとの呼び出し回数 |

---

## 4. 状態遷移（実行のライフサイクル）

### 4.1 ノードの順序と各ノードが触る状態（不変）

```
parse_instruction → plan_search → search → fetch → analyze_content → extract_common → compile_report
                        └────────────（候補 0 件）────────────→ compile_report
```

| ノード | 読む | 書く | 追加する観測 |
|---|---|---|---|
| `parse_instruction` | `messages` | `instruction` / `search_query` / `max_results` / `output_format` / `published_after` / `sort_by` / `transcript_language` | `usage`（構造化呼び出し）／`note`（フォールバックしたときだけ） |
| `plan_search` | `instruction` | `search_queries` | `usage` ×2（生成 ＋ 点検）／`note`（点検で差分が出たときだけ） |
| `search` | `search_queries` | `candidates` | なし |
| `fetch` | `candidates` | `contexts` / `notes` | `failures`（取得失敗） |
| `analyze_content` | `candidates` / `contexts` | `analyses` / `notes` | `compressed` / `degradations` / `failures` / `usage` |
| `extract_common` | `analyses` | `common_themes` | `usage` |
| `compile_report` | すべて | `report` / `notes`、`contexts`・`candidates` の**中身を解放** | `note`（使用量の合計・失敗件数）／`cache/usage.json` |

### 4.2 素材 1 件の処理の段階（圧縮 → 縮退 → 解析）

```
素材（Candidate + Context）
  │
  ├─ len(source_text) > compression_threshold ?
  │     ├─ Yes → 圧縮（1 回。タイムアウト 60 秒）
  │     │         ├─ 成功 → CompressedSource(applied=True) → 素材を差し替え（≤ threshold）
  │     │         └─ 失敗 → CompressedSource(applied=False, reason=...) → 生素材を threshold で切る
  │     └─ No  → 追加呼び出し 0 回（FR-008 / SC-003）
  │
  └─ 構造化出力の呼び出し
        ├─ 成功 → AnalysisFinding
        ├─ スキーマ不一致 → 再試行（retry_max まで。retry_wait_seconds 待つ）
        │                          └─ 使い切った → フォールバック（見出し表の抽出）
        └─ 上限超過と判定 → 縮退（degrade_max_attempts 段まで）
                               ├─ 縮小して再試行 → 成功なら Degradation を記録して続行
                               └─ 使い切った → Failure に記録して**他の対象は継続**（FR-020）
```

**段階の識別**（FR-019）: 圧縮は `CompressedSource`、縮退は `Degradation`
（`reason = "token_limit"`）として**別の型**で記録する。`Degradation` に圧縮の記録は入らない。

### 4.3 状態の解放（`compile_report` の内部順序）

```
1. notes を組み立てる（既存の 3 要素 ＋ 新しい挙動のときだけ追加）
2. ResearchReport を組み立てる（既有のフィールドのみ）
3. [include_intermediate が真なら] 中間データを cache へ書き出す（解放の前）
4. cache/usage.json を書く（cache_dir があるときだけ）
5. 進捗の note（使用量・失敗件数）
6. cache/report.json を書く（既存の経路。順序も既存のまま）
7. contexts / candidates の**中身を解放**する  ← 3〜6 の後（レポートは既に確定済み）
```

**順序が必須である理由**: `ResearchReport.candidates` は `Candidate` を参照するため、
先に解放するとレポートの候補が空になる。テストで「レポート確定 → 解放」の順序を
固定する（R-8）。

**実測との整合**: `tests/integration/test_full_flow.py:444` は
`result["contexts"][0].thread_text == ""` を固定している。本設計では `contexts` の
**リストは残り**、`thread_text` は解放後も `""`（解放前も `""` のシナリオ）であるため
この assertion は通る。`contexts` を空リストにすると `IndexError` で落ちる（採用しない）。

---

## 5. 評価エンティティ（`tests/eval/`。出荷パッケージには入れない）

### 5.1 `DatasetEntry`（入力レコード。FR-071）

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | `str` | ✓ | レコードの識別子（結果の対応付けに使う） |
| `prompt` | `str` | ✓ | 調査の指示文（`messages` に 1 件入る） |

**データセット**: `tests/eval/fixtures/tr-basic.json` は `DatasetEntry` の**配列**。
名前（`tr-basic`）はファイル名から解決し、内容の指紋（`id` と `prompt` を並べた
SHA-256 の先頭 16 文字）を計算して結果に記録する（FR-073）。

### 5.2 `AxisScore`（1 観点の判定結果。FR-039）

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `axis` | `str` | ✓ | 観点の識別子（6 つのいずれか） |
| `score` | `int \| None` | ✓ | 生の点数（1〜5）。取得失敗は `None` |
| `normalized` | `float \| None` | ✓ | `(score - 1) / 4`（0〜1）。`score` が `None` なら `None` |
| `reason` | `str` | ✓ | 判定の理由（取得失敗時はその理由） |
| `error` | `str \| None` | ✓ | 取得失敗の内容（型違い・欠落・API エラー） |

**規則（FR-039 / FR-067 / SC-028）**: 点数に `ge` / `le` の**値域検査を置かない**。
1〜5 の範囲外の値も**そのまま記録**する（`normalized` は計算できる場合のみ計算）。
型違い・欠落は「取得失敗」として `score = None` / `error` に理由を入れる。
**1 観点の失敗で全体を落とさない**（例外を送出しない）。

### 5.3 `Axis`（観点の定義。`tests/eval/axes.md` が単一の源）

| フィールド | 型 | 説明 |
|---|---|---|
| `id` | `str` | 観点の識別子 |
| `title` | `str` | 表示名 |
| `judge_prompt` | `str` | 観点ごとの判定プロンプト（生成側の制約を反映。FR-040） |
| `prompt_constraints` | `list[str]` | 対応する `prompts.py` の制約（FR-048 / FR-074） |
| `odr_axis` | `str \| None` | 参照実装の 6 評価との対応（採用 / 対象外と理由） |

**必須の観点（6 つ。`correctness` は対象外として明示。FR-038）**:

| # | 観点 | 何を見るか |
|---|---|---|
| 1 | `relevance` | 指示の主題に対する候補の関連度 |
| 2 | `coverage` | 指示が求める観点を網羅しているか |
| 3 | `evidence` | 引用・出典が本文の主張を支えているか |
| 4 | `structure` | 見出し・順序・読みやすさ |
| 5 | `actionability` | 読み手が次に取れる行動が示されているか |
| 6 | `constraint_compliance` | 出力言語・件数・引用形式の制約の遵守 |
| — | `correctness` | **対象外**（ウェブ検索を伴うため。対応表に理由を記録） |

**総合品質** = 6 観点の `normalized` の**平均**（`None` の観点は除外して平均する）。
LLM に総合点を直接聞かない（FR-038 の「下位基準の集約」）。

### 5.4 `EvalRun`（1 構成 × 1 データセットの実行。FR-041 / FR-043）

| フィールド | 型 | 説明 |
|---|---|---|
| `dataset` | `str` | データセット名（`tr-basic`） |
| `dataset_fingerprint` | `str` | 内容の指紋（FR-073） |
| `config_name` | `str` | 構成の識別子（ファイル名から導出。FR-072） |
| `settings` | `dict` | `Configuration.model_dump()` ＋ `judge_model` ＋ `judge_model_is_generator`（FR-069） |
| `commit` | `str` | `git rev-parse HEAD`（取得できない場合は `"unknown"`） |
| `judge_model` | `str` | 判定に使ったモデル名（FR-043 / SC-034） |
| `axis_order` | `list[str]` | 観点の提示順（ランダム化の記録。FR-041） |
| `generated_at` | `str` | ISO 8601 |

**保存先**: `artifacts/eval/{dataset}__{config_name}__{commit}__{model_slug}.jsonl`
（1 行 1 レコード。既定で追記。上書きは `--overwrite` を要求。SC-027）。

### 5.5 `EvalRecord`（結果の 1 行）

| フィールド | 型 | 説明 |
|---|---|---|
| `id` | `str` | `DatasetEntry.id` |
| `run` | `EvalRun` | 実行の文脈（全行に複製して 1 行で完結させる） |
| `article` | `str` | 生成されたレポート（Markdown） |
| `scores` | `list[AxisScore]` | 観点ごとの判定 |
| `overall` | `float \| None` | 総合品質（`normalized` の平均） |
| `usage` | `dict \| None` | 生成のトークン数と呼び出し回数（FR-042） |

**比較の単位**（FR-041 / SC-016）: 保存済みの 2 つ（以上）のファイルを**名前で指定**して
比較する。生成は構成ごとに 1 回であり、**判定のみ再実行できる**
（`script/evaluate.py --judge-only {file}` に相当する経路）。

---

## 6. 既定値の一覧（実装時にテストで固定する）

| 項目 | 既定 | 凍結の根拠 |
|---|---|---|
| 個別解析の同時実行数 | `2` | `tests/unit/test_analyze_content.py:421`（`max_in_flight == 2`） |
| 圧縮しきい値 | `20000` 文字 | 現行 `source_text[:20000]`（挙動を変えない） |
| 圧縮タイムアウト | `60.0` 秒 | 参照実装と同じ（`utils.py:179`） |
| 再試行回数（初回を除く） | `2`（合計 3 回） | SC-005 / FR-010 |
| 再試行の待機 | `1.0` 秒 | テストでは 0 を注入 |
| 縮退の最大段数 | `3` | FR-015 |
| 縮小率 | `0.9` | FR-016 |
| 縮退の入力下限 | `1000` 文字 | FR-015 の停止条件 |
| 自己点検 | 有効 | FR-054（`False` で 1 回） |
| 中間データの書き出し | 無効 | FR-046（無効時の出力は変更前と一致） |
| 構造化出力の方式 | `function_calling` | research R-2（実走で確定。`json_schema` は例外なしに意味の壊れた出力を返す） |
| 判定モデル | `TR_EVAL_MODEL` → 既定（実走で確定） | FR-069 / SC-034 |
| 評価の保存先 | `artifacts/eval/` | FR-043 |

## 7. テストで固定する不変条件（データに関わるもの）

| # | 不変条件 | 固定する場所 | 対応要件 |
|---|---|---|---|
| 1 | しきい値以下の素材は追加 LLM 呼び出しが 0 回 | `tests/unit/test_compression.py` | FR-008 / SC-003 |
| 2 | 圧縮後の素材はしきい値以下（プロンプトの指示に依存しない） | 同上 | FR-007 |
| 3 | 圧縮が失敗しても実行は exit 0 で完走し、理由が残る | `tests/unit/test_compression.py` ＋ 統合 | SC-004 |
| 4 | 再試行 3 回失敗 → フォールバックの結果が返る | `tests/unit/test_llm.py` | FR-010〜012 / SC-005 |
| 5 | 上限超過と判定されない `400`（`invalid model`）はそのまま送出される | `tests/unit/test_degradation.py` | FR-018 |
| 6 | 縮退は入力を縮め、`degrade_max_attempts` を超えない | 同上 | FR-015〜017 |
| 7 | 解析 1 件の失敗で他が継続する（10 中 3 失敗 → 7 件成功） | `tests/unit/test_analyze_content.py` | FR-020 / SC-007 |
| 8 | 失敗は `failures` に残り、無言で消えない | 同上 | FR-021 / FR-023 |
| 9 | レポート確定後に `contexts` / `candidates` の文字列が空になる | `tests/unit/test_compile_report.py` | FR-027 / SC-010 |
| 10 | 解放後も `report.candidates` の中身は保持される（順序） | 同上 | R-8 |
| 11 | 既定の入力で `cache/` に新しいファイルが増えない | 統合テスト | FR-046 / SC-026 |
| 12 | 使用量が `cache/usage.json` に書かれ、不明が明示される | `tests/unit/test_compile_report.py` | FR-061 / FR-062 |
| 13 | 値域外の設定で exit 2（丸めも既定値置換もしない） | `tests/integration/test_cli_contract.py` | FR-024 / SC-023 |
| 14 | `TR_SELF_REVIEW=true` で 2 回、`false` で 1 回 | `tests/unit/test_plan_search.py` | FR-049〜054 / SC-021 / SC-036 |
| 15 | 点検が件数を減らさない・増やさない | 同上 | D-1 / FR-052 |
| 16 | 採点の値域検査をしない（範囲外もそのまま記録） | `tests/unit/test_evaluation.py` | FR-067 / SC-028 |
| 17 | 総合品質は 6 観点の平均（欠落を除外） | 同上 | FR-038 / FR-039 |
| 18 | 1 要素の欠落が全体を落とさない | 同上 | FR-068 |
| 19 | `testpaths` が不変で、`script/evaluate.py` が収集対象外 | `tests/unit/test_evaluation_entrypoint.py` | FR-066 / SC-018 |
| 20 | 実走の入口が CLI subprocess を使わず公開 API を呼ぶ | 同上 | FR-065 / SC-035 |
