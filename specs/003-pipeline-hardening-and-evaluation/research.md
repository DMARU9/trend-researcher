# Phase 0 Research: AI パイプラインの堅牢化と品質測定

**Feature**: `003-pipeline-hardening-and-evaluation` | **Date**: 2026-09-14

**Input**: [spec.md](./spec.md) / [plan.md](./plan.md)

本ドキュメントは `plan.md` の Technical Context に残っていた未確定事項（`NEEDS CLARIFICATION`）と、
仕様の実装可否を左右する設計選択を、**リポジトリ内の実測**に基づいて確定する。
「実測」と書いた項目は、本リポジトリで実際にコマンドを実行して得た結果である。

## 目次

| ID | 論点 | 対応する要件 |
|---|---|---|
| R-1 | 上限超過の検出方法（参照実装の移植可否） | FR-015 / FR-018 / FR-063 / FR-064 |
| R-2 | 構造化出力の方式とフェイクの扱い | FR-009〜012 / FR-035 |
| R-3 | 再試行の回数・待機・失敗時のフォールバック経路 | FR-010〜012 |
| R-4 | 段階的縮退のアルゴリズムと終了条件 | FR-015〜019 |
| R-5 | 圧縮の入力・出力形式・境界 | FR-001〜008 |
| R-6 | 圧縮と縮退の段階の分離 | FR-019 |
| R-7 | 部分失敗の隔離方法 | FR-020〜023 |
| R-8 | 状態のライフサイクルと生素材の解放 | FR-026 / FR-027 / SC-010 |
| R-9 | 中間データの記録の切り替え | FR-046 / FR-062 / SC-026 |
| R-10 | 設定の宣言・値域拒否・単一解決経路 | FR-024 / FR-025 / FR-059 / FR-060 |
| R-11 | 使用量の集計元と記録先 | FR-061 / FR-062 |
| R-12 | 追加の観測を既存の進捗契約を壊さずに出す方法 | FR-029 / FR-030 / SC-011 / SC-012 |
| R-13 | 検索クエリの自己点検の形と件数契約 | FR-049〜054 |
| R-14 | プロンプトの深化（停止条件・構造例・二重明示） | FR-055〜058 |
| R-15 | 評価の実走の入口と初期状態の複製 | FR-065 / FR-066 / SC-035 |
| R-16 | 評価フィクスチャと記録の形 | FR-070〜074 |
| R-17 | テスト境界の拡張（フェイクの契約変更） | 原則 II / FR-012 / FR-028 |
| R-18 | 既定モデルが知られていない場合の縮退 | FR-015 / Assumptions |
| R-19 | 判定モデルの既定値 | FR-069 / SC-034 |
| R-20 | 既存テストを壊さない値域の決め方 | FR-024 / FR-035 / FR-059 |
| R-21 | 移植統制の運用（欠陥リストの管理） | FR-063 / FR-064 |

---

## R-1: 上限超過の検出方法（参照実装の移植可否）

**Decision**: `tools/llm.py` の呼び出し境界に**多段の検出器**を置く。検出は次の 4 段で判定し、
**すべて満たしたときだけ**上限超過とみなす。

1. 例外が OpenAI 互換クライアントの `APIStatusError` 系であること
   （`isinstance(exc, openai.APIStatusError)`。クラス名の文字列比較をしない）。
2. `status_code` が `400` または `413` であること。
3. 応答本文（`exc.body`）またはメッセージに、**機械的に判定できるトークン量の指標**が
   含まれること。指標は `error.code == "context_length_exceeded"`、
   `error.type == "invalid_request_error"` ＋ メッセージ中の
   `context length` / `maximum context` / `too many tokens` / `token limit` のいずれか。
4. メッセージに**無効な引数**を示す語（`unsupported` / `unknown parameter` / `invalid model` /
   `does not exist` 等の既知の非該当パターン）が**含まれない**こと（除外条件）。

**Rationale**:
- 参照実装の検出器（`open_deep_research/src/utils.py:724` の `is_token_limit_exceeded()`）は
  次の 2 点で本リポジトリに適合しない。**移植しない**（FR-063 / FR-064）。
  - `_check_openai_token_limit`（`utils.py:762`）が
    `'openai' in str(type(exception)).lower() or 'openai' in module_name.lower()` という
    **文字列依存**で判定する（FR-064 が禁じる「参照実装の判定条件をそのまま用いること」に該当）。
  - `utils.py:795` が `class_name in ['BadRequestError', 'InvalidRequestError']` と
    **クラス名の文字列比較**を行い、`utils.py:818` が
    `exception.code == 'context_length_exceeded' or exception.type == 'invalid_request_error'` を
    参照する。後者は未定義属性を参照しうる形（`getattr` でない）である。
- 本リポジトリの `/v1` は OpenAI 互換の**プロキシ**（`tools/llm.py` の既定 `base_url`）であり、
  上流プロバイダの例外型は一定でない。`isinstance` で**型に基づいて**判定し、構造化された
  `body` を主たる根拠にする方が、文字列に依存せず決定的である。
- FR-018 は「判定できない失敗を上限超過と誤認してはならない MUST NOT」と定める。したがって
  検出器は**保守的**にし、条件 3 を満たさない `400` は上限超過とみなさない（そのまま送出する）。
  除外条件（条件 4）は、`invalid model` のような設定ミスを縮退で隠さないために置く。

**Alternatives considered**:
- 参照実装の検出器をそのままコピー … **却下**（FR-063 が移植を禁じる実測済み欠陥を 2 つ含む）。
- メッセージの部分文字列のみで判定（`if "context" in str(exc).lower()`） … **却下**。
  誤検出で縮退が走り、FR-018 に反する。テストで反例（`invalid model` を含む 400）を固定できる形にする。
- 応答のトークン数を数えて事前に判定（プロアクティブ） … **却下**。入力のトークン数は
  トークナイザなしでは正確に得られず、新規依存なしの制約（FR-033）に反する。事後の検出＋縮退
  （FR-015 の MUST）で足りる。
- litellm の `context_window_fallbacks` … **却下**。新規依存（FR-033 / FR-045）。

---

## R-2: 構造化出力の方式とフェイクの扱い

**Decision**: 宣言的なスキーマ（`typing_extensions.TypedDict` ではなく **Pydantic モデル**）から
`ChatOpenAI.with_structured_output(Model, method="json_schema")` を構築する。ただし
**`method` は実行時設定（`TR_STRUCTURED_METHOD`）で `json_schema` / `function_calling` を
切り替えられるようにする**（既定は `json_schema`）。パース失敗（`OutputParserException`）は
再試行の対象とし、規定回数失敗したら既存の `tools/parse.py` の抽出へフォールバックする。

**Rationale**:
- 実測（2026-09-14）: `langchain-openai` 1.6.0 の `ChatOpenAI.with_structured_output` は
  既定で `json_schema`（`response_format={"type":"json_schema", ...}`）を使う。
  既存の `/v1` は OpenAI 互換プロキシであり、`json_schema` を拒否する実装もありうる。
  本リポジトリは**認証情報を要する実走**をテストに含めない（FR-036 / FR-044）ため、
  既定で失敗しても検出できない。切り替え手段を設定に持たせることで、
  実走時に `function_calling` へ落とせるようにする（新規依存は 0。`langchain-openai` に同梱）。
- Pydantic モデルをスキーマの単一の源にする（`schemas.py` ではなく各ノードの近傍に定義）。
  既存の `models.py` の語彙（`ResearchInstruction` / `AnalysisFinding` / `CommonTheme`）と
  **同じデータ**を表すため、二重定義を避ける意味でも `models.py` に置くのが自然（原則 III）。
- フェイクの扱い: `tests/conftest.py` の `_FakeLLM` は `with_structured_output` を実装していない。
  実装しないと **AttributeError** になり、既存の統合テスト（`tests/integration/test_cli_contract.py`
  を含む 601 件の大部分）が落ちる。よって R-17 と同時に拡張する。

**Alternatives considered**:
- `bind_tools` による function calling … 却下（`with_structured_output(method="function_calling")`
  と同じ経路であり、切り替え設定で足りる）。
- 構造化出力を使わず、既存の `extract_json_block` を全ノードに広げる … 却下。FR-009 は
  「構造化スキーマで受け取る MUST」と定めており、正規表現による抽出は「一定の動作」の
  保証にならない（参照実装の `parse_json` 方式も同じ理由で採らない）。
- `langchain` の `create_react_agent` 等でツール化 … 却下（YAGNI。ノード構成を変える必要がない）。

---

## R-3: 再試行の回数・待機・失敗時のフォールバック経路

**Decision**: 再試行は `tools/llm.py` の構造化呼び出しラッパに実装する。

- 回数: **1 回目の試行 ＋ 最大 `retry_max` 回の再試行**（既定 `retry_max = 2` → 合計 3 回。
  SC-005 の「3 回試行して失敗したらフォールバック」に一致）。回数は実行時設定から注入する
  （FR-005 / FR-010 / FR-024）。
- 待機: 再試行の前に `abort_wait`（既定 1.0 秒）を空ける。`abort_wait = 0` または負なら待機しない。
  **待機は `tools.llm.asyncio.sleep` を通す**ため、既存の `no_retry_sleep` と同じ方式のスパイで
  テストから観測・除去できる。
- 再試行の対象: `OutputParserException` / `ValidationError`（スキーマ不一致）。
  `APIConnectionError`・タイムアウトも対象。**上限超過と判定された例外は再試行しない**
  （R-1 の縮退経路へ渡す。縮退の方が根本的な解決であり、同じ入力で 3 回失敗させる意味がない）。
- フォールバック: 3 経路それぞれでそのノードの既存の決定的解析へ落とす。
  - `parse_instruction` → `tools/parse.py:extract_json_block` ＋ 既存の正規表現群
  - `analyze_content` → 既存の見出し表の抽出（`_parse_angles_table`）
  - `extract_common` → `tools/parse.py:extract_list_items` / `extract_section`
- フォールバックは**無言にしない**。`ProgressEmitter.note()`（stderr のみ。R-12）で
  「フォールバック」を 1 行出し、`state.notes` ではなく**中間データ**（`degradations`）に記録する。

**Rationale**:
- 既存テストは `tools/parse.py` のパスを固定している（`tests/unit/test_parse.py` 125 行、
  `tests/unit/test_analyze_content.py:171` 等の見出し表の入力）。構造化出力がフェイクで失敗し、
  フォールバックが従来と同じ結果を返すことで、**既存テストの期待値を書き換えずに green** になる。
  これが FR-012「正常系とフォールバックの両方を固定」を既存スイートを壊さずに満たす唯一の形。
- 実測: 既存の `fake_model_factory` は `_FakeLLM.invoke` が固定の `content` を返す。
  `with_structured_output(...).invoke(...)` は `_FakeLLM` に無い（AttributeError）ため、
  フェイク側で `OutputParserException` を送出するランを示す必要がある（R-17）。
- 待機の実時間消費を避けるため、既存の `tests/conftest.py:no_retry_sleep`（`SleepSpy`）を
  共通フィクスチャとして自動適用する。**現状は `tools.x_search.asyncio.sleep` のみ**を対象に
  している（実測）。`tools.llm.asyncio.sleep` を対象に加える。

**Alternatives considered**:
- 指数バックオフ … 却下（テストで固定しやすさと、既定 1.0 秒という小さな待機に対して過剰）。
- `langchain` の `with_retry()` … 却下。上限超過を再試行してしまい、縮退へ渡す分岐が組めない。
- 各ノードに個別の再試行ループ … 却下。3 ノードで重複する実装になる（YAGNI・原則の重複回避）。
- フォールバックを `state.notes` に書く … 却下。`state.notes` は `compile_report` で
  `report.notes` となり Markdown に描画されるため、**既定の入力で stdout が変わる**（FR-035 / SC-011）。

---

## R-4: 段階的縮退のアルゴリズムと終了条件

**Decision**: `tools/degradation.py` の純粋関数（`shrink(text, ratio)` / `plan_ladder(...)`）で
段階を作り、`tools/llm.py` が駆動する。

- 段数: `degrade_max_attempts`（既定 3）。初回の失敗を 1 段目とし、**最大 `degrade_max_attempts` 段**
  まで縮小を試す。
- 縮小率: `shrink_ratio`（既定 0.9）。各段で直前の入力長 × 0.9 に切り詰める。
  **モデル上限テーブル（`_MODEL_TOKEN_LIMITS`）は既知モデルのときに初回の縮小先
  （おおよそ「上限トークン − 出力枠」相当の文字数）を決めるためにのみ使う**。
  テーブルに無いモデルでは比率のみで縮小する（R-18 / D-2）。
- 停止条件（無限縮小の禁止）: 次のいずれかで打ち切る。
  1. `degrade_max_attempts` 段を使い切った。
  2. 縮小後の入力長が**前段の入力長と同じ**（比率適用で減らない。例: 入力が極端に短い）。
  3. 入力長が `min_input_chars`（既定 1000）を下回った。
- 使い切った場合: 例外を送出し、`__main__.py` が **stderr に理由を出して終了コード 1** で終わる
  （FR-015 / US3 シナリオ 2）。理由には「縮退を何段試したか」「縮小前後の入力長」を含める。
- 縮退したら `ProgressEmitter.note()` に 1 行出し（FR-017 / FR-029）、
  `state.degradations` に記録する（`Degradation(node, stage, before_chars, after_chars, reason)`）。

**Rationale**:
- 「モデル上限テーブル」は実行時依存が提示する情報であり、未知モデルでは得られない。
  比率方式にすればテーブルが無くても前進できる（D-2 の根拠）。
- 停止条件 2 が無いと、縮小できない入力で同じ呼び出しを `degrade_max_attempts` 回繰り返す
  （無意味な待機と課金）。FR-015 の「無限縮小禁止」はこの条件で満たす。
- 縮退は**呼び出しごとに入力を組み替える**形にする（呼び出し元の素材を書き換えない）。
  圧縮（別段階。R-6）と違い、状態には記録のみを残す。

**Alternatives considered**:
- トークナイザ（`tiktoken`）で正確に測る … 却下。新規依存（FR-033）。
- 例外のたびに**半分**に縮める … 却下。失敗のたびに大きく情報を失い、2 段目以降の成功確率が落ちる。
- 段階ごとに**小さいモデルへ切り替える**（ODR の `max_tokens` 削減に相当） … 却下。
  参照実装で実測された欠陥（無効なオプションをモデルへ渡す）に近い経路であり、FR-063 / FR-064。

---

## R-5: 圧縮の入力・出力形式・境界

**Decision**: `tools/compression.py` の 1 関数 `compress_text(text, *, model, max_chars, timeout)`。

- 発動条件: `len(text) > compression_threshold`（既定 20,000 文字。**現行の
  `source_text[:20000]` と同じ値**にして、既定の入力での出力を変えない）。
- 入出力: 入力は素材**全体**（切り捨てない。FR-001）。出力は
  `<summary>…</summary>` と `<key_excerpts>…</key_excerpts>` の 2 部を
  `tools/parse.py` の既存 `extract_section` で取り出す**単純なテキスト契約**。
  ODR の `summarize_webpage`（`utils.py:179`）と同じ形。
- プロンプトには**指示文を含める**（ODR と同じ工夫。`summarize_webpage` は元の指示を
  プロンプトに渡す）。素材の文脈を失わないため。
- タイムアウト: `asyncio.wait_for(model.ainvoke(...), timeout=compression_timeout)`
  （既定 60.0 秒。ODR と同じ値）。
- 縮小後: `compressed = summary + key_excerpts` を `max_chars` 以内に切り詰める（FR-007）。
  `max_chars` は `compression_threshold` と同じ値を既定とする。
- 失敗時（例外・タイムアウト・空応答）: **生素材を `max_chars` で切り詰めたもの**を使い、
  `note()` と `degradations` に記録する（`__main__.py` / グラフは成功として進む。SC-004）。

**Rationale**:
- FR-007「圧縮後の素材部分はしきい値以下」を満たすには、出力側で切り詰めが要る。
  LLM に文字数を守らせるのは保証にならない（「一定の動作」の観点で弱い）。
- ODR の `<summary>` / `<key_excerpts>` の 2 部構造は、**要点の保持**と**原文の引用**を
  分離できる点が優れている。前者は要約、後者はイディオムや数字の保持に効く。
- タイムアウトは ODR の 60.0 秒をそのまま採る（実測値。ローカルのプロキシに対する前提として妥当）。

**Alternatives considered**:
- `/responses` エンドポイントの `truncation="auto"`（ODR の C1）… 却下。`/v1` 互換プロキシで
  使える保証が無く、実走でしか確認できない（テストが green でも動く保証にならない）。
  本実装はクライアント側で切り詰める。
- 素材を**分割して逐次要約**（map-reduce）… 却下。呼び出し回数が増え、
  「しきい値以下では追加呼び出し 0 回」（FR-008 / SC-003）と「呼び出し回数の固定」を
  満たしにくい。1 回の圧縮で足りることは spec の前提（US1）。
- 圧縮を別ノードにする … 却下。FR-031 が 7 ノード構成の維持を MUST とする。

**実測が必要な点（tasks の先頭に置く）**: `tools/parse.py` の `extract_section` が
`<summary>` 形式のタグを受け取れるか（既存の実装は Markdown 見出しを想定している可能性がある）。
受け取れない場合は `tools/compression.py` 内に専用のタグ抽出を置く（`tools/parse.py` を
無理に一般化しない = YAGNI）。

---

## R-6: 圧縮と縮退の段階の分離

**Decision**: 2 つを**別の層**に置き、`degradations` の `reason` で区別する。

| 段階 | 実装の場所 | 目的 | 記録 |
|---|---|---|---|
| 圧縮 | `tools/compression.py`（発動条件はしきい値超過） | **事前**に素材を縮める | `Compression` 相当の記録（対象ごと） |
| 縮退 | `tools/degradation.py` + `tools/llm.py`（発動条件は上限超過の例外） | 失敗の**事後**に入力を削って再試行する | `Degradation(node, stage, before, after, reason="token_limit")` |

圧縮の記録は中間データ（`state.compressed` / 進捗の `note`）に、縮退の記録は
`state.degradations` に入れる。**同じ入力に対して両方は原則発動しない**
（圧縮でしきい値以下になれば上限超過は起きない）が、圧縮後も上限を超える長さの場合は
縮退が発動しうる。この 2 段が別段階であることを `degradations` の要素で識別できるようにする。

**Rationale**: FR-019 が「圧縮と段階的縮退を別の段階として扱い、各段階を記録する MUST」と
定める。1 つの機構に統合すると、事後（失敗時）と事前（予防）の区別が記録から消える。

**Alternatives considered**: 圧縮を縮退の 1 段目として扱う … 却下（FR-019 の MUST に反する）。

---

## R-7: 部分失敗の隔離方法

**Decision**: `nodes/analyze_content.py` の `asyncio.gather` を
`asyncio.gather(*tasks, return_exceptions=True)` にし、`BaseException` のうち
**`asyncio.CancelledError` だけは再送出**する（キャンセルは実行の中断要求であり、
部分失敗として飲み込んではならない。原則 V の「エラーを握りつぶさない」）。

- 失敗した対象は `failures: list[Failure]`（`id` / `reason`。`reason` は例外型名と短いメッセージ）に入れる。
- 上限超過（R-1）と `KeyboardInterrupt` 系は再送出しない（上限超過は縮退済みで、
  最後まで残ったものは「失敗」として扱う）。
- 成功分は `analyses` に、失敗分は `failures` に入れて**同じ入力のまま後続へ渡す**
  （`extract_common` は `analyses` のみを入力にする。実測: `nodes/extract_common.py:38` が
  `state.get("analyses", [])` を読む）。
- 全件失敗した場合は `analyses = []` のまま `extract_common` → `compile_report` へ進み、
  `report.notes` に「解析 0 件（すべて失敗: N 件）」の 1 行を追加して**終了コード 0** で終える
  （US4 シナリオ 3 / SC-007 の趣旨）。
- 失敗の件数と理由は `ProgressEmitter.note()` に 1 行、`state.failures` に構造化して残す（FR-021 / FR-023）。

**Rationale**:
- 現行の `asyncio.gather` は 1 件の失敗で全体が例外になる（実測: `tests/integration/test_full_flow.py`
  の `test_search_failure_propagates_*` 系は**検索**の失敗を対象にしており、解析の
  部分失敗は固定されていない）。FR-020 の MUST はここで満たす。
- `report.notes` への追加は「新しい挙動が起きたときだけ」なので、既定の入力では
  追加されない（FR-035 / SC-011 を満たす。plan の制約表を参照）。

**Alternatives considered**:
- `asyncio.TaskGroup` … 却下。1 件の失敗でグループ全体をキャンセルする（部分失敗の隔離と逆）。
- 失敗した対象を**リトライして揃える** … 却下。呼び出し回数が対象数に依存して増え、
  「一定の動作」の観点で上限が読めない。再試行は LLM 呼び出しの層（R-3）に閉じる。

---

## R-8: 状態のライフサイクルと生素材の解放

**Decision**: `nodes/compile_report.py` で、レポートを確定した後に `contexts` の
**中身（生素材）だけ**を解放する。`Context` のレコード（`id`）は残す。

- `Context.text` を `""`、`Context.thread_text` を `""`、`Context.replies` を `[]` にする。
- `candidates` は `Candidate.text` を `""` にする（`report.candidates` は別オブジェクトで、
  レポートには元の値が既に入っている）。
- `analyses` / `common_themes` / `report` は**解放しない**（整形済みであり、利用者に見える）。
- 解放は `include_intermediate` の値に関わらず行う（FR-027 は設定の有無に依存しない）。
  ただし `include_intermediate = True` のときは解放前に中間データを `cache/` へ書き出す（R-9）。
- 共通テーマ抽出（`extract_common`）は既に `analyses` のみを入力にしているため、
  この段階での入力の切り替えは不要（実測済み。`nodes/extract_common.py:38`）。FR-026 の
  「後続段は生データを参照しない」は満たされている。**新たに生データを参照し始める
  コードを書かないこと**をテストで固定する。

**Rationale**:
- 実測: `tests/integration/test_full_flow.py:444` が `result["contexts"][0].thread_text == ""` を
  固定している。シナリオは「スレッド取得に失敗して本文のみ」であり、**既に空文字列**である。
  中身を空にしてもこの assertion は `""` のまま通る。レコード自体を消す（`contexts = []`）と
  `IndexError` で落ちるため、**レコードを残す判断は必須**である。
- `report.candidates` は `Candidate` のコピーではなく同じモデルを参照するため、
  `compile_report` が `ResearchReport(...)` を組み立てた**後**に解放する順序が要る
  （順序を誤るとレポートが空になる）。この順序をテストで固定する。

**Alternatives considered**:
- `contexts` を状態から**削除**する（キーごと消す）… 却下（上記の既存テストが落ちる）。
- `del state["contexts"]` … 却下（LangGraph の状態は TypedDict で、ノードの戻り値に
  含めないだけではキーが消えない。`AgentState` の定義と矛盾する）。
- 解放を**新しいノード**で行う … 却下（FR-031 が 7 ノード維持を MUST とする）。

---

## R-9: 中間データの記録の切り替え

**Decision**: `Configuration.include_intermediate: bool = False`（出荷設定クラスの boolean。
既定は無効。ODR の `include_source_str` と同じ形）で切り替える。

- **無効（既定）**: `cache/usage.json` 以外の新しいファイルを書かない。`cache/report.json` の
  書き込みは現状のまま。**既存の出力（stdout・`cache/report.json`）は変更前と一致する**（SC-026）。
- **有効**: `cache_dir` に次の 3 ファイルを追加で書く。
  `cache/compressed.json`（圧縮の入力長・出力長・発動有無）/ `cache/degradations.json`
  （縮退の段）/ `cache/failures.json`（部分失敗）。
  レポート形式（`report.json` のキー）は変えない。
- 書き込みは `compile_report` の最後（レポート確定後）に行う。`cache_dir` が未指定なら何もしない。
- `ProgressEmitter.note()` による通知（R-12）は**切り替えに依存しない**（実行後に何が起きたかを
  常に stderr で確認できる。FR-017 / FR-029）。

**Rationale**: FR-046 は「出荷設定クラスの真偽値で切り替え、無効時は既存の出力を変えない MUST」。
`cache/report.json` に新しいキーを足す方式は、SC-026 の「既存キーが変更前と一致」を満たしつつ
ファイルが 1 つで済むが、「中間データを**ファイルとして**残す」という FR-062 の意図
（実行後に確認できること）に対して、レポート定義を太らせる方針は FR-034 の
「既存のフィールドを変更しない」の精神に反しないものの、`report.json` を読む既存の
利用者（テスト・手動確認）に影響する。**別ファイル**にして影響範囲をゼロにする。

**Alternatives considered**:
- env 変数 `TR_KEEP_INTERMEDIATE` のみで切り替え … 却下（FR-046 が「出荷設定クラスの
  真偽値」と定める。env → 設定の解決経路（`load()`）には載せる）。
- `cache/` ではなく `artifacts/` に書く … 却下（`cache/` は実行成果物の置き場という既存の規約。
  実測: `.gitignore` の「Project specific」節に `cache/` と `artifacts/` の両方があり、
  前者は実行時成果物、後者は構造解析の出力という位置づけ）。

---

## R-10: 設定の宣言・値域拒否・単一解決経路

**Decision**:

1. 各フィールドに `Field(default=..., description="...", json_schema_extra={"x_oap_ui_config": {...}})` を
   付け、型は既存の注釈（`int` / `str` / `bool` / `float` / `str | None`）で表す。
   値域は `Field(ge=..., le=...)`、選択肢は `Literal[...]` で表す（Pydantic v2 の標準機能のみ。
   新規依存 0）。
2. 値域違反は `ConfigurationError(Exception)` として送出する。Pydantic の `ValidationError` は
   `ConfigurationError` に包み、**項目名・入力値・期待する値域**を含むメッセージにする（FR-024）。
3. 起動時拒否は `__main__.py` の**早い段階**で行う。`Configuration.load(...)` と
   CLI 上書きの `model_copy(update=...)` はどちらも検証をしない（Pydantic v2 の仕様）ため、
   上書きを適用した**後**に `Configuration.model_validate(settings.model_dump())` を呼び、
   `model_fields_set` を保ったまま再検証する（`validate_assignment` を有効にすると
   `model_copy` の意味が変わりうるため採らない）。
   失敗時は stderr に理由を出して **exit 2**（`_parse_args` の失敗と同じ扱い）。
4. 単一の解決経路: `Configuration.load(env_prefix)` → CLI 上書き → 再検証 →
   `runnable_config = {"configurable": configuration.model_dump()}` → ノードは
   `Configuration.from_runnable_config(config)` で受け取る。**この 1 経路以外で設定を読まない**
   （ノードが `os.getenv` を直接読むことをテストで禁止する。既存の `tests/unit/test_config.py`
   の走査方針を拡張する）。
5. Studio からの変更は `langgraph.json` の `config_schema`（既に `Configuration` を指す）で
   そのまま可能。`x_oap_ui_config` を付けることで UI に説明と値域が出る（FR-060）。

**Rationale**:
- Pydantic v2 では `model_copy(update=...)` は検証を行わない。現行の `__main__.py` は
  `settings.model_copy(update={...})` で `--max-results` などを適用している（実測）。
  ここに `ge`/`le` を足しても**素通りする**ため、明示的な再検証が必須である。
  これが「値域外は起動時に拒否」（FR-024 / FR-059 / SC-009 / SC-023）を満たす唯一の方法。
- `model_fields_set` を保つ必要があるのは、`--max-results` の明示指定が
  「環境変数の値より優先される」ことをテストが固定しているため
  （実測: `tests/unit/test_config.py:266` / `tests/unit/test_configuration.py:281`）。
  `model_validate(model_dump())` は**全フィールドを「設定済み」にする**（`model_fields_set` が
  全項目になる）ため、`model_fields_set` を読む箇所を壊す可能性がある。
  **実測で確認してから確定する**（`model_copy` の `model_fields_set` は
  「元の fields_set ＋ update のキー」になる。`model_dump` を経由すると失われるため、
  `Configuration.model_validate` に `model_copy` の結果をそのまま渡す方法が使えない場合は、
  `model_copy` の後で各フィールドを**手動で検証するヘルパ**（`_validate_bounds()`
  のような純粋関数）を用意する。
  → **tasks の先頭で実測して決める**（本 research では「再検証の実装位置は 2 案のうち実測で選ぶ」
  と確定する）。
- `providers/x.py:48` が `model_fields_set` を見てプラットフォーム既定を上書きする
  （実測）。したがって「全項目が設定済み」になる実装は、この優先順位を壊す。

**Alternatives considered**:
- `model_config = ConfigDict(validate_assignment=True)` … 却下（`model_copy(update=...)` は
  `__init__` を経由しないため検証されない。設定を足しても解決しない）。
- `__main__.py` で 1 フィールドずつ `if` で検査 … 却下（FR-059 の「宣言」にならない。
  値域がコードと宣言の 2 箇所に散る）。
- env ごとに `Configuration` を分ける … 却下（原則 III の単一の実行時設定型に反する）。

---

## R-11: 使用量の集計元と記録先

**Decision**:

- 集計は `tools/llm.py` の呼び出し境界で行う。`AIMessage.usage_metadata` を読み、
  `input_tokens` / `output_tokens` / `total_tokens` を取る。
  欠落（`None`）の場合は `None` のまま保持し、「不明」として扱う（FR-061。
  実測: 差分応答では `usage_metadata` に値が入るが、`response_metadata` は空。
  プロキシが usage を返さない場合は `None` になる）。
- 呼び出し回数は**境界で数える**（`invoke` / `ainvoke` / 構造化呼び出しのすべて）。
  ノードは数えない（集計が 1 箇所になる）。
- 受け渡しは `AgentState.usage: Annotated[list[ModelUsage], operator.add]`。
  1 呼び出し = 1 要素（`node` / `role` / `model` / `input_tokens` / `output_tokens` / `total_tokens`）。
  並列実行（`asyncio.gather`）でも reducer で連結できる。
- 記録先は 2 つ。`cache/usage.json`（中間成果物。FR-062。合計と内訳）と、
  `compile_report` の `ProgressEmitter.note()` 1 行（「LLM 呼び出し合計 N 回（入力 X / 出力 Y トークン）」。
  **不明が含まれる場合は「不明 N 回」を併記**）。
- **レポートには入れない**（D-3 の判断。`report.notes` は本文に描画されるため）。

**Rationale**:
- ODR は `usage_metadata` を集計して結果に併記する（FR-042）。本実装はそれを
  「1 回の実行単位」で行う（SC-026 相当。クリアランス: FR-061）。
- reducer を使う理由: ノードの戻り値は並列に到着するため、後勝ちの通常フィールドでは
  他ノードの要素が消える（`AgentState` は現状すべて通常フィールド。実測）。
- `state.usage` は**利用者のレポートに出さない**ため、`include_intermediate` に依存しない。

**Alternatives considered**:
- `usage` を `dict[str, int]` にして合算する … 却下（内訳が消える。FR-042 は併記を要求）。
- `langchain` の callback（`get_openai_callback`）… 却下。`init_chat_model` の
  `configurable_fields` 経由の呼び出しで確実に捕捉できる保証が無く、実走でしか確認できない。
  境界で `AIMessage` を見る方が決定論的。
- `StateGraph` の `usage` を `Report` に混ぜる … 却下（D-3）。

---

## R-12: 追加の観測を既存の進捗契約を壊さずに出す方法

**Decision**: `ProgressEmitter` に `note(text)` を追加する。`note` は
**stderr にのみ** 1 行（`[補足] {text}`）を書き、**`_messages` へは積まない**。

**Rationale**:
- 実測: 進捗の契約は次の 3 箇所で固定されている。
  - `tests/unit/test_analyze_content.py:374-387`: `emitter.get_messages()` の
    `[m.content for m in ...]` を**厳密比較**（`["[5/7] analyze_content ... 開始（並列上限 2）",
    "[5/7] analyze_content ... 完了（5 件を要約）"]`）。
  - `tests/integration/test_full_flow.py:167-181`: 全メッセージから `_node_phases` を抽出し、
    `(node, phase)` 列を厳密比較。**余分な行があると落ちる**実装かどうかは抽出関数の
    実装に依存するが、`emit` の行を足せば確実に影響する。
  - `tests/unit/test_progress.py`: `emit` の書式を固定。
- したがって「進捗に出す」（FR-029 / FR-017 / FR-062）を満たすには、`emit` の行を増やさずに
  出す手段が要る。`note` は stderr の観測可能性（原則 V）を満たしつつ、状態の `messages` を
  汚さない。憲法 V は「stdout はレポートのみ、stderr は進捗・ログ・エラー」と定めており、
  **補足の行を stderr に出すことは契約に適合する**。
- 代替案として「`emit` の `detail` に足す」があるが、`detail` は
  `（{detail}）` の形で行に埋め込まれ、**既存テストの厳密比較を壊す**（実測）。
  よって `detail` の既存文言は一切変更しない。

**Alternatives considered**:
- `emit` に新しいノード名や phase を足す … 却下（`NODE_ORDER` とグラフの一致を崩す。FR-031 / SC-011）。
- 進捗の `detail` を拡張する … 却下（上記）。
- `logging` を使う … 却下。既存の進捗は `ProgressEmitter` に一本化されており、
  テストで観測する手段（`get_messages` / `capsys`）と別系統になる。

---

## R-13: 検索クエリの自己点検の形と件数契約

**Decision**:

- 実装は `nodes/plan_search.py` の**ノード内で 1 回だけ**。ループ・リトライをしない
  （FR-050。呼び出しは「生成 1 回 ＋ 点検 1 回」の計 2 回で、テストで固定する。FR-053）。
- 点検の呼び出しは**生成と同じテキスト→行の解析経路**（`_clean_query` を行ごとに適用）を使う。
  構造化出力は使わない（FR-009 の対象は「指示解釈・個別解析・共通テーマ抽出」の 3 つであり、
  クエリ生成は含まれない。既存の生成も同じ経路）。
- 適用規則:
  1. 点検の出力が空（行 0 件）→ **差分なし**とみなし生成結果を採用する（FR-051 / Edge Case）。
  2. 点検の出力が生成結果より**少ない** → 生成結果から**補充**し、生成結果の件数を下回らせない
     （Edge Case「規定件数に満たない分を補充」/ US7 シナリオ 1。D-1）。
     **補充は生成結果の候補からのみ行い、新しいクエリを創作しない**。
  3. 点検の出力が生成結果より**多い** → 上限（`Provider.max_search_queries`。
     X = 8、YouTube = `None`）で切り詰める（既存の挙動を維持）。
  4. 重複は除去する（正規化後の文字列で比較。既存の `_clean_query` の出力で比較）。
     期間表現（`_PERIOD_RE` / `_YEAR_RE`）の除去も点検の役割に含める。
  5. 生成結果が 0 件 → 点検しても 0 件（固定件数まで**増やさない**）。
- 失敗時（例外・タイムアウト）は生成結果で継続する（FR-051）。
- 切り替えは `Configuration.self_review: bool = True`（FR-054。既定は有効。
  **評価専用の切り替え手段を別に設けない**）。
- 必要件数は `Provider.required_query_count`（X = 5、YouTube = 1）として**宣言**する。
  この値は次の 2 つに使う。(a) `prompts.py` の生成プロンプトの件数指示と一致することの
  テスト（対応表の一部）、(b) 点検の結果が生成結果より少ないときの**補充の上限**。
  **点検は件数を `required_query_count` まで増やさない**（D-1）。

**Rationale**:
- 規則 2 と 5 が D-1 の帰結である。実測: `tests/unit/test_plan_search.py:108`（3 件）/
  `:113`（2 件）/`:118`（8 件）/`:128`（12 件）/`:134`（8 件）/`:139`（0 件）、
  `tests/integration/test_full_flow.py:228`（2 件）が件数を固定している。
  「5 件ちょうど」を強制すると `:139`（0 件）と `:113`（2 件）で必ず落ちる。
- フェイクは**ノード内のすべての呼び出しに同じ内容を返す**（実測: `_FakeLLM.invoke` は
  固定の `content` を返す）。よって点検を足しても
  「生成 3 件 → 点検 3 件」となり、テストの期待値は変わらない。
  これが既存テストを壊さずに FR-049〜054 を満たす鍵である。
- `tests/unit/test_plan_search.py:147/152/157/163/170` は
  `prompts_for("plan_search")[0]` を参照する（実測）。点検のプロンプトを**2 番目**に
  出す限り、`[0]` は生成プロンプトのままである。この順序をテストで固定する。
- `Provider` に 1 属性を足すのは原則 IV に適合する（値は provider が宣言し、コアは解釈しない）。
  `tests/unit/test_platform_scan.py` の規則 (a)+(b) は「コアに `platform == "..."` を
  書かないこと」であり、属性の追加は対象外。

**Alternatives considered**:
- 自己点検を**別ノード**にする（ODR の `think_tool` に相当する独立ノード）… 却下。
  FR-031 が 7 ノード維持を MUST とし、FR-049 は「同一ノード内で 1 回」と定める。
- 点検を反復ループにする（ODR の reflection 相当）… 却下（FR-050 が 1 回に固定を MUST とする）。
- 件数を `required_query_count` に**揃える**（不足を補う）… 却下（D-1。既存テストが落ちる）。

---

## R-14: プロンプトの深化（停止条件・構造例・二重明示）

**Decision**: `prompts.py` の各定数に、次の 3 つを**機械的に区別できる形**で足す（FR-055 / FR-057）。

```
## 停止条件
- 出力は <形式> のみとする。前置き・後書き・謝辞を書かない。
- 不明な項目は空文字列とし、"おそらく" 等の推定表現で埋めない。（判定不能表現の禁止。FR-056）
- <役割別の上限> 件を超えない。

## 出力形式
- 見出しは `## 見出し名`、箇条書きは `- ` で始める。（種類別の構造例。FR-057）
```

- **重要制約の二重明示**（FR-058）: レポートの出力言語・候補の件数・引用の形式の 3 つを、
  (a) 生成プロンプトの**冒頭**（役割の説明の直後）と (b) **末尾**（出力形式の節）の
  役割の異なる 2 箇所に置く。テストで両方の存在を固定する（`prompts.py` の定数を
  文字列として走査する）。
- 固定テンプレートの禁止（FR-057）: 出力の例示は「種類別の構造例」に留め、
  レポート本文の骨組みを**そのまま真似させる**文言（`以下のテンプレートをそのまま使う`）
  を書かない。テストで禁止語を走査する。
- プロンプト制約と評価観点の対応は `tests/eval/axes.md` の対応表に記録する（FR-048 / FR-074）。

**Rationale**: 実測: 現行の `prompts.py`（173 行）は 8 定数を持ち、`X_PLAN_SEARCH_PROMPT` は
「5 件」「140 文字以内」等の指示を箇条書きで与えている。停止条件と出力形式の節は
既に部分的にある（`extract_json_block` が JSON ブロックを要求している）。本作業は
**節として明示する**ことが目的であり、内容を大きく変えるものではない。

**Alternatives considered**:
- Few-shot 例を大量に入れる … 却下（トークン数を増やし、テンプレート化を招く）。
- プロンプトを YAML で外部化 … 却下（YAGNI。`langgraph.json` の配線と関係しない）。

---

## R-15: 評価の実走の入口と初期状態の複製

**Decision**: `script/evaluate.py`（`tests/` の外。収集対象外）。

```
script/evaluate.py --dataset tr-basic --platform x \
  --config configs/baseline.json --config configs/candidate.json \
  [--judge-model <name>] [--out artifacts/eval]
```

- 1 つの構成を 1 回だけ生成し、結果を**名前で指定して比較する**（FR-041）。
  `--config` は複数回指定でき、各構成に**識別子（名前）**を付ける
  （ファイル名から導出し、`--config-name` で上書き可。FR-072）。
- 生成は公開 API を in-process で呼ぶ（SC-035）:

```python
from trend_researcher import trend_researcher, render_report
state = {"messages": [HumanMessage(content=prompt)], "platform": platform}
if max_results is not None:
    state["max_results"] = max_results
config = {"configurable": <その構成の Configuration>.model_dump()}
result = await trend_researcher.ainvoke(state, config)
markdown = render_report(result["report"])
```

- **初期状態の複製は 3 項目に限る**（`messages` 1 件 / `platform` / 明示時のみ `max_results`。
  FR-065）。`__main__.py` の引数解釈（`--since` の解析・`output_format` の既定解決・
  provider の `env_prefix` の適用）を**再実装しない**。必要な値は引数または環境変数で与える。
- CLI の subprocess を使わない（FR-065 / SC-035）。`--out` に JSONL を書く（R-16）。
- 判定は生成と**別のモデル**（`TR_EVAL_MODEL`。R-19）で行い、生成と同じモデルの場合も
  実走可能とし、「同一モデルを使用した」事実を結果の `settings` に記録する（FR-069）。
- **評価の実走をテストの合否条件に含めない**（FR-044）。`script/evaluate.py` は
  `tests/` の外にあるため `testpaths = ["tests"]` の収集に含まれず、
  そのままでは**未検証のコード**になる。よって次の 2 つで守る。
  1. 判定ロジック・採点スキーマ・フィクスチャ解決・レコード整形は `tests/eval/` に置き、
     `tests/unit/test_evaluation.py` から**固定入力で**検証する（LLM 呼び出しなし）。
  2. `tests/unit/test_evaluation_entrypoint.py` が `script/evaluate.py` を
     **読み込んで**（`importlib.util.spec_from_file_location`）次の不変条件を検証する。
     (a) `testpaths` を変更していないこと（`pyproject.toml` を読む）、
     (b) argparse のオプション集合が期待どおりであること、
     (c) `subprocess` を import していないこと、
     (d) `trend_researcher.ainvoke` と `render_report` を参照していること、
     (e) 初期状態に `messages` / `platform` / `max_results` 以外のキーを入れていないこと
         （ソースを AST で走査し、`state[...] = ...` の右辺キーを列挙する）。
     これにより「実際に走らせなくても入口の契約を固定する」を満たす。

**Rationale**:
- CLI の subprocess を使うと、出力がレポート 1 本に潰れて判定の入力を作れず、
  プロセスの起動コストと進捗の混入が加わる。公開 API を in-process で呼ぶ方が
  「構成ごとに 1 回だけ生成する」（FR-041）を素直に表せる。
- 初期状態を 3 項目に限るのは、`__main__.py` が組み立てる状態
  （`messages` / `platform` / 任意の `max_results`。実測: `__main__.py` の
  `initial_state = {"messages": [...], "platform": platform}` ＋ 任意 `max_results`）と
  一致させるためである。余分なキーを入れると、評価が本番と違う初期状態を測ることになる。

**Alternatives considered**:
- CLI を subprocess で起動して stdout を判定する … 却下（FR-065 が禁止）。
- 評価専用のグラフ（判定ノードを含む StateGraph）を作る … 却下（出荷のグラフ構成を汚染する。
  FR-063 の「移植の統制」と、原則 VI の YAGNI に反する）。
- `pytest` のマーカー（`-m eval`）で実走を同居させる … 却下（FR-066 が「収集対象に
  含めない」を MUST とする。マーカーは収集対象を変えない）。

---

## R-16: 評価フィクスチャと記録の形

**Decision**:

- データセットは**名前付き**（`tr-basic`）。既定はリポジトリ内の固定ファイル
  `tests/eval/fixtures/tr-basic.json`。外部サービスは必須にしない（FR-070）。
- 1 行 1 レコードの JSONL で、1 レコードは **3 項目**:

```json
{"id": "q-001", "prompt": "調査の指示文", "article": "生成されたレポート（Markdown）"}
```

- 結果のファイル名は `{dataset}__{config}__{commit}__{model-slug}.jsonl` にし、
  データセット名・構成の識別子・コミット識別子・判定モデル名を含める（FR-072 / FR-043）。
  構成差は `{config}` の識別子で区別する。`model-slug` は `/` と `:` を `-` に置換する。
- 追記モード（`a`）で書き、**既存ファイルを無断で上書きしない**（SC-027）。
  上書きする場合のみ `--overwrite` を要求する。
- 保存先は既定 `artifacts/eval/`（追跡外。実測: `.gitignore` の Project specific 節に `artifacts/`）。
  引数 `--out` または `TR_EVAL_OUT_DIR` で変更できる（FR-043）。
- 記録に含めるもの: 設定の識別子と中身（`Configuration` の `model_dump`）、データセット名と
  **内容の指紋**（`id` と `prompt` を並べた文字列の SHA-256 の先頭 16 文字。FR-073）、
  コミット識別子（`git rev-parse HEAD`。取得できない場合は `"unknown"`）、
  **判定モデル名**、観点ごとの点数と理由、総合品質、トークン数と呼び出し回数（FR-042）、
  観点の提示順（FR-041 のランダム化の記録）。
- 観点は 6 つ（`tests/eval/axes.md` の対応表で定義。FR-038 / FR-074）。
  採点は 1〜5 の整数で受け、**0〜1 に正規化**して保存する（FR-039。生の点数も残す）。
  総合品質は 6 つの**下位基準の集約**として計算する（LLM に総合点を直接聞かない）。
  `correctness`（正しさ）は**対象外**であることを対応表と結果の両方に明示する（FR-038）。
- 点数は値域検査を追加しない（`ge` / `le` なし。FR-067）。型違い・欠落は
  **取得失敗**として扱い、その観点の理由に記録する（1 観点の失敗で全体を落とさない）。

**Rationale**:
- `artifacts/eval/` の追跡外は `.gitignore` の実測で確認済みであり、
  実行ごとにファイルが増える性質（1 行 1 レコード）と整合する。
- 「コミット識別子・判定モデル・設定・データセット指紋」は、**後から結果を比較するときに
  前提が違うことを検出する**ために必要である（ODR の `expt_results` が持つ情報に相当）。
- 点数に `ge` / `le` を付けないのは FR-067 の明示的な指示である
  （プロバイダ側の検証に任せ、こちらで二重に弾かない）。
- 総合品質を下位基準の集約にするのは、判定モデルに「まとめの点数」を聞くと
  下位基準と矛盾する値が返りうるためである（SC-013 相当の一貫性）。

**Alternatives considered**:
- データセットを `git` 管理外の外部ファイルにする … 却下（FR-070 が「既定は
  リポジトリ内の固定ファイル」と定める）。
- 結果を 1 ファイル（JSON 配列）にする … 却下（FR-043 が「JSONL 1 行 1 レコード」を MUST とする）。
- 判定を実走と同じプロセスで行い、その場で比較する … 却下（FR-041 が「生成は構成ごとに 1 回、
  判定のみ再実行可」を MUST とする。保存した結果を名前で指定して比較する形にする）。

---

## R-17: テスト境界の拡張（フェイクの契約変更）

**Decision**: 境界のフェイクを次のように拡張する。**ノード側の変更と同じコミットで行う**
（原則 II の境界はテストにも及ぶ。片方だけ変えると既存の統合テストが落ちる）。

1. `tests/conftest.py`
   - `_FakeLLM` に `with_structured_output(schema, **kwargs)` を追加し、
     **`OutputParserException` を送出するラン**を返す（既定の構造化出力は失敗し、
     既存のフォールバック経路を通る。= 既存テストの期待値が変わらない）。
   - `FakeModelFactory.install(responses, *, structured=None)` を追加。`structured` に
     ノード名 → オブジェクトを渡すと、構造化出力が**成功する**ランになる（新規テスト用）。
   - `_FakeMessage` に `usage_metadata` を追加（既定は `None`。指定時に
     `{"input_tokens": n, "output_tokens": m, "total_tokens": n+m}`）。
   - `FakeModelFactory` が差し替えるモジュールの一覧に
     **`trend_researcher.tools.compression` を追加**する（`nodes/` の接頭辞だけでは届かない。
     実測: 現行は `trend_researcher.nodes.{node}.build_model` の 4 つだけを差し替える）。
   - `no_retry_sleep` の対象に **`tools.llm.asyncio.sleep`** を追加する（再試行・縮退の待機）。
   - 自動適用（`autouse`）にする。`SleepSpy` は記録するだけなので既存テストの意味を変えない。
2. `tests/integration/cli_harness.py`
   - `_FakeLLM` に同じ `with_structured_output` / `usage_metadata` を追加する。
   - シナリオに応じた応答（`LLM_RESPONSES`）の構造は**変えない**。
   - 圧縮が発動するシナリオを足す場合のみ、`tools.compression` の境界を追加で差し替える。

**Rationale**:
- 実測: 現行の `FakeModelFactory.install` は
  `LLM_NODES = ("parse_instruction","plan_search","analyze_content","extract_common")` の
  `trend_researcher.nodes.{node}.build_model` を patch する。ノードが
  `build_model(...).with_structured_output(...)` を呼ぶと、`_FakeLLM` に
  その属性が無いため **AttributeError** になる。601 件のうち LLM を通るテストは
  すべて落ちる。
- `with_structured_output` を「必ず失敗する」既定にすると、構造化出力を入れた後も
  既存テストは**フォールバック経路**（`tools/parse.py`）を通り、期待値が変わらない。
  これは FR-012 の「フォールバック経路を固定する」テストとしても機能する。
- `tools/compression.py` は `tools/llm.build_model` を import するため、
  patch 対象は `trend_researcher.tools.compression.build_model` になる
  （import 時の束縛。Python の patch 意味論）。`nodes/` の接頭辞では届かない。

**Alternatives considered**:
- ノード側で `build_model` を**引数として注入**する … 却下（`build_model` は
  ノードのローカル import であり、既存の patch 契約（`tests/unit/test_fixtures.py:184` が
  検証）を広範囲に変える）。
- 実装を `nodes/` に置いて patch 対象を増やさない … 却下（原則 II 違反。LLM 呼び出しは
  `tools/` の境界に置く規約を崩せない）。
- `respx` / `httpx` のモックで HTTP 層を差し替える … 却下（新規依存。既存の
  `init_chat_model` 経由の呼び出しに対して過剰）。

---

## R-18: 既定モデルが知られていない場合の縮退

**Decision**: モデル上限テーブルを `tools/degradation.py` に置き、
`get_model_token_limit(model)` で引く。**テーブルに無い場合は `None` を返し、
比率のみで縮退する**（D-2）。縮退の記録に `limit_known: bool` を持たせ、
「上限が不明のまま縮退した」ことを事後確認できるようにする（FR-013 / FR-017 の趣旨）。

**Rationale**: 実測: 既定モデルは `openai:mimo-v2.5`（`tools/llm.py` の
`resolve_env("MODEL", default="openai:mimo-v2.5")`）であり、公開されている上限テーブルに
無い。上限が既知でなければ縮退できない設計（参照実装は
`get_model_token_limit()` が `None` なら例外にする）では、**既定のモデルで
一度も縮退できない**。FR-015 は「縮小可能な入力が残っている間は試みる MUST」であるため、
比率方式を採る。

**Alternatives considered**: 未知モデルでは諦めて終了する … 却下（D-2 / FR-015）。

---

## R-19: 判定モデルの既定値

**Decision**: 既定は **`TR_EVAL_MODEL` → 既定値 `openai:mimo-v2.5`**（生成と同じ既定値）とし、
`resolve_env("EVAL_MODEL", default="openai:mimo-v2.5")` の 1 箇所で解決する。
`Configuration` には項目を追加しない（FR-069 の MUST）。`script/evaluate.py` の
`--judge-model` はこの解決結果を上書きする。
判定モデル名は結果レコードの `settings.judge_model` と**ファイル名**の両方に記録する。
生成モデルと同一の場合、結果に `"judge_model_is_generator": true` を記録する（FR-069）。

**Rationale**: FR-069 は既定を「コードで定めた既定値」としつつ、**生成と別のモデルを
SHOULD** とする。既定を「未設定ならエラー」にすると実走が開始直後に落ちる。
「生成と同じ既定値」にすれば、未設定でも走り、`judge_model_is_generator` で
事実が残る（SC-034 の趣旨）。

**実測が必要な点（tasks の先頭に置く）**: `TR_EVAL_MODEL` の既定値を
`openai:mimo-v2.5` にするか、判定専用の別名（例: `openai:claude-3-5-sonnet` のような
プロキシ上の別モデル）にするかは、実走の可否に依存する。実走の初回で疎通確認し、
通らない場合は既定を変更する（コードの 1 行であり、変更しても `Configuration` の契約は不変）。

**Alternatives considered**:
- `Configuration.eval_model` … 却下（FR-069 が `Configuration` への項目追加を MUST NOT とする）。
- 未設定なら例外 … 却下（実走の入口が使いにくくなる。FR-065 の趣旨に反する）。

---

## R-20: 既存テストを壊さない値域の決め方

**Decision**: 値域は「既存テストが実際に使う値の集合」を含む**最小の範囲**にする。
実測してから決める（下は実測に基づく案）。

| フィールド | 型 | 値域 / 選択肢 | 既定 | 根拠 |
|---|---|---|---|---|
| `platform` | `str` | 空文字可（空はエラーにしない） | `""` | 既存テストが空を許す（`Configuration()` を直接作る経路） |
| `output_format` | `OutputFormat \| None` | `markdown` / `json` / `None` | `None` | 既存の CLI の `--format` の選択肢と一致 |
| `max_results` | `int` | `1 ≤ n ≤ 100` | `5` | 既存テストは 1 / 2 / 3 / 5 / 10 を使用（実測）。CLI の範囲と一致 |
| `sort_by` | `Literal["relevance","recency"]` | 2 択 | `"relevance"` | `providers/base.py` の `selection_note` と `__main__.py` の検証が既に 2 値 |
| `transcript_language` | `str` | 空でない | `"ja"` | 既存テストが `"en"` を代入 |
| `analysis_concurrency` | `int` | `1 ≤ n ≤ 16` | `2` | 既存テストが `2` を固定（実測: `tests/unit/test_analyze_content.py:421`） |
| `retry_max` | `int` | `0 ≤ n ≤ 10` | `2` | SC-005 の 3 回試行 |
| `retry_wait_seconds` | `float` | `0 ≤ x ≤ 60` | `1.0` | テストでは 0 を注入 |
| `compression_threshold` | `int` | `1000 ≤ n` | `20000` | 現行の `[:20000]` と同じ（既定の挙動を変えない） |
| `compression_timeout_seconds` | `float` | `1 ≤ x ≤ 300` | `60.0` | ODR と同じ |
| `degrade_max_attempts` | `int` | `1 ≤ n ≤ 10` | `3` | FR-015 |
| `shrink_ratio` | `float` | `0.1 ≤ x ≤ 0.9` | `0.9` | `1.0` を許すと縮小しない（無限縮小の禁止に反する） |
| `min_input_chars` | `int` | `100 ≤ n` | `1000` | 停止条件 3 |
| `self_review` | `bool` | — | `True` | FR-054（既定は有効） |
| `include_intermediate` | `bool` | — | `False` | FR-046（既定は無効） |
| `cache_dir` | `str \| None` | — | `None` | 既存 |
| `published_after` | `str \| None` | — | `None` | 既存 |
| `structured_method` | `Literal["json_schema","function_calling"]` | 2 択 | `"json_schema"` | R-2 |
| `model` / `session_id` | `str` | — | 既存の解決に委ねる | `tools/llm.py` が既に `resolve_env` で解決 |

`abort_wait_seconds` という名前は使わない（`retry_wait_seconds` に統一）。

**Rationale**: FR-035 / 原則 VI。既存テストの期待値を書き換えないためには、
既存テストが使う値がすべて値域内でなければならない。上の表は
`grep -rn "max_results=\|sort_by=\|transcript_language=" tests/` の実測に基づく。
**実装時に `tests/` を走査して「実際に現れる値の集合」を再確認し、表を確定する。**

**Alternatives considered**:
- 値域を広めに取る（`1 ≤ max_results ≤ 1000`）… 却下。値域は「誤った値の拒否」が目的であり、
  実際に扱える範囲を示す必要がある。ただし**取得できる上限を超える値**（`max_results = 100`）を
  拒否しないこと（既存テストが使う）。
- 値域を env からのみ検査し、`Configuration` の宣言は説明だけにする … 却下（FR-059 が
  「型・値域・既定値・説明を宣言する MUST」と定める）。

---

## R-21: 移植統制の運用（欠陥リストの管理）

**Decision**: 参照実装の**実測済みの欠陥**を `tests/eval/axes.md` の対応表に列挙し、
それぞれについて本リポジトリでの扱い（「該当機能を移植しない」/「移植するが実装を変える」）と
**テスト上の根拠**を 1 行で書く（FR-063 / FR-074）。列挙する欠陥は次の 6 つ（参照実装の実測）。
少なくとも先頭 3 つは、対応するテストで「同じ誤りを持ち込んでいないこと」を固定する。

| # | 参照実装の欠陥（実測） | 本リポジトリの扱い | 固定する方法 |
|---|---|---|---|
| 1 | `utils.py` のトークン上限検出がクラス名・モジュール名の**文字列**に依存し、`exception.code` / `exception.type` を `getattr` せず参照する | **移植しない**。`isinstance` ＋ 構造化 `body` ＋ 除外条件で判定する（R-1） | `invalid model` を含む `400` を「上限超過ではない」と判定するテスト |
| 2 | 到達不能な分岐・無効なオプションの受け渡し（モデルに存在しない引数を渡す経路） | **移植しない**。縮退は入力を比率で削る（R-4） | 縮退が入力を縮めることと、引数を組み替えないことを固定 |
| 3 | Model Token Limit テーブルの引き当てで未知モデルを例外にする | **移植しない**。未知モデルでも比率で縮退する（R-18） | 未知モデル名で縮退が成立するテスト |
| 4 | ツール契約の非対称（同じ検証が片方の経路にしかない。例: 検索件数の検証は検索経路のみ） | **移植しない**。自己点検は生成と点検の**両方**の後で件数契約を適用する（R-13） | 点検が上限を超える件数を返す場合の切り詰めテスト |
| 5 | 常に真になる条件分岐（`if x is not None and x:` のような冗長な形） | **移植しない**。検出器は条件ごとにテストを持つ | 検出器の反例テスト（4 条件それぞれ） |
| 6 | 到達しない `except` 節（捕捉型が実際には投げられない） | **移植しない**。捕捉型は実測で確認する（R-1 の `isinstance`） | 捕捉型の実測に基づくテスト（R-1 の反例） |

**Rationale**: FR-063 は「参照実装の実測済み欠陥を移植してはならない MUST」、FR-064 は
「上限超過の検出は実測に基づく設計とし、参照実装の判定条件をそのまま用いてはならない MUST」と
定める。欠陥を**列挙して対応を 1 箇所に置く**ことで、レビュー時に
「同じ誤りを持ち込んでいないか」を 1 ファイルで確認できる（`.github` のレビュー観点 (f)）。

**Alternatives considered**: 各所のコメントに散らす … 却下（対応の一覧性が失われる）。FR-074 が
「1 つの対応表に記録する MUST」と定める。

---

## 未解決事項

**`NEEDS CLARIFICATION` は 0 件。** 仕様の `## Clarifications`（17 項目）と
本 research の R-1〜R-21 で、実装を左右する論点はすべて「決定」または
「実装時に実測して 2 案から選ぶ」の形で確定した。実測に委ねた項目は次の 3 つで、
いずれも `tasks.md` の**先頭**に置く（設計の分岐点であり、後から見つけると手戻りが大きい）。

| 実測する項目 | 決め方 | 影響範囲 |
|---|---|---|
| 構造化出力が `json_schema` で通るか（R-2） | 実走の疎通確認。通らなければ `function_calling` を既定にする | `Configuration.structured_method` の既定値 1 行 |
| 上限超過の応答の形（R-1） | 実走で `status_code` / `body` / メッセージを採取し、条件 3 の語彙を確定する | 検出器の閾値（テストは語彙に依存しない形で書く） |
| 判定モデルの既定値（R-19） | 実走の初回で疎通確認 | 既定値 1 行 |
| `model_copy` 後の再検証の実装位置（R-10） | `model_fields_set` が保たれるかを実測。保たれない場合はヘルパで各フィールドを検査する | `configuration.py` の 1 関数 |
