# Quickstart（検証手順）: AI パイプラインの堅牢化と品質測定

**Feature**: `003-pipeline-hardening-and-evaluation` | **Date**: 2026-09-14

**Input**: [spec.md](./spec.md) / [plan.md](./plan.md) / [data-model.md](./data-model.md) /
[contracts/](./contracts/)

このドキュメントは、実装が仕様を満たしていることを**実行して確かめる**ための手順である。
実装の詳細（モデル・関数・テストの中身）は `tasks.md` と実装フェーズに属する。
契約の詳細は `contracts/` を参照し、ここでは重複させない。

## 前提

| 項目 | 値 |
|---|---|
| Python | 3.11 以上 |
| パッケージ管理 | `uv` |
| 作業ディレクトリ | リポジトリルート（`/home/takumi/github/trend-researcher`） |
| ネットワーク | **不要**（`uv sync` 済みの環境で、テストはすべて境界モックで完走する） |
| 認証情報 | **不要**（実走（`script/evaluate.py`）でのみ必要） |
| 実測ベースライン（2026-09-14） | 601 passed / カバレッジ 96.65% / 49.10 秒 / ruff 0 / mypy 0 |

```bash
cd /home/takumi/github/trend-researcher
uv sync --extra dev
```

## 1. 品質ゲート（すべての変更の後に実行する）

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
```

| ゲート | 合格条件 | 対応要件 |
|---|---|---|
| `pytest` | 全件 green、カバレッジ 90% 以上（`fail_under = 90`）、**60 秒以内** | SC-013 |
| `ruff` | 0 件（`All checks passed!`） | 技術制約 |
| `mypy` | 0 件（`Success: no issues found`） | 技術制約 |

**注意**: テストスイートの実測は 49.10 秒であり、増加に使える余地は約 11 秒しかない。
新規テストで実時間の待機（再試行の待機・圧縮のタイムアウト）を発生させないこと。
待機は `SleepSpy`（`tests/conftest.py`）で除去・観測する。

## 2. シナリオ別の検証

各シナリオは「前提 → コマンド → 期待」の形で書く。対応する契約は `contracts/` を参照。

### S1. 長い素材のネタを取りこぼさない（US1 / FR-001〜008 / SC-001〜004）

| | |
|---|---|
| 前提 | 素材（`Candidate` ＋ `Context` の本文）が `compression_threshold`（既定 20,000 文字）を超える |
| コマンド | `uv run pytest tests/unit/test_compression.py -q` |
| 期待 | (a) 圧縮の LLM 呼び出しが**素材 1 件につき 1 回**、(b) 圧縮後の素材がしきい値以下、(c) 圧縮が例外・タイムアウト・空応答で失敗しても**実行は継続し exit 0**、(d) 記録（`CompressedSource`）に失敗の理由が残る |
| 追加確認 | しきい値**以下**の素材では圧縮の呼び出しが **0 回**（`uv run pytest tests/unit/test_compression.py -q -k below`） |

### S2. LLM 応答が崩れても動き続ける（US2 / FR-009〜014 / SC-005）

| | |
|---|---|
| 前提 | 構造化出力が規定回数失敗する（`FakeModelFactory` の構造化出力が `OutputParserException` を返す） |
| コマンド | `uv run pytest tests/unit/test_llm.py tests/unit/test_parse_instruction.py -q` |
| 期待 | (a) 試行回数が `1 + retry_max`（既定 3）、(b) 待機が `retry_wait_seconds` 回だけ呼ばれる、(c) 3 回失敗後に**フォールバック**の結果が返る、(d) 正常系（構造化出力が成功）とフォールバックの**両方**がテストで固定されている |
| 追加確認 | フォールバックした事実が `note()`（stderr）と中間データに残り、**`report.notes` には入らない** |

### S3. 入力が上限に達しても最後まで走り切る（US3 / FR-015〜019 / SC-006）

| | |
|---|---|
| 前提 | 上限超過の例外（`openai.APIStatusError` 相当）を注入する |
| コマンド | `uv run pytest tests/unit/test_degradation.py -q` |
| 期待 | (a) 縮小が最大 `degrade_max_attempts` 段まで行われ、段ごとに `Degradation` が記録される、(b) 縮小後の入力長が前段より短い、(c) 縮小で成功すれば実行は exit 0、(d) 使い切ったら stderr に理由（試した段数・縮小前後の長さ）が出て **exit 1**、(e) 縮小できない入力では**同じ呼び出しを繰り返さない**（無限縮小の禁止） |
| 反例 | `invalid model` を含む `400` は**上限超過と判定されない**（`uv run pytest tests/unit/test_degradation.py -q -k not_token_limit`） |

### S4. 1 件の失敗でレポート全体を失わない（US4 / FR-020〜023 / SC-007）

| | |
|---|---|
| 前提 | 10 件の候補のうち 3 件の解析が例外になる（境界モックで注入） |
| コマンド | `uv run pytest tests/unit/test_analyze_content.py -q -k partial` |
| 期待 | (a) 成功した 7 件の解析が `analyses` に入る、(b) 失敗した 3 件が `failures` に入る（無言で消えない）、(c) 実行は exit 0 でレポートが出る、(d) 失敗の件数と理由が `note()` と中間データで確認できる |
| 追加確認 | `asyncio.CancelledError` は**再送出**される（部分失敗として飲み込まれない） |

### S5. 実行の予算と状態の行き先が分かる（US5 / FR-024〜029 / SC-008〜010）

| | |
|---|---|
| 前提 | `cache_dir` を一時ディレクトリに設定する（`tmp_cache_dir` フィクスチャ） |
| コマンド | `uv run pytest tests/unit/test_compile_report.py tests/unit/test_state.py -q` |
| 期待 | (a) `analysis_concurrency` を 1 と 2 にして同時実行数がそれぞれ 1 と 2 になる、(b) `retry_max` と縮退の段数が設定値に従う、(c) レポート確定後に `contexts` / `candidates` の**文字列が空**になり、`report.candidates` の内容は保持される、(d) `cache/usage.json` に呼び出し回数とトークン数が書かれ、不明な呼び出しが明示される、(e) `include_intermediate = False` では `cache/` に新しいファイルが増えない |
| 追加確認 | 既定の入力で `cache/report.json` の既存キーが変更前と一致する |

### S6. レポートの良し悪しを数字で比べられる（US6 / FR-038〜048・FR-065〜074 / SC-015・SC-016・SC-027・SC-028）

| | |
|---|---|
| 前提 | なし（テストは固定入力のみ） |
| コマンド | `uv run pytest tests/unit/test_evaluation.py tests/unit/test_evaluation_records.py tests/unit/test_evaluation_entrypoint.py -q` |
| 期待 | (a) 6 観点のうち 5 つ以上を採点する、(b) 点数を 0〜1 に正規化し、範囲外の値もそのまま記録する（値域検査をしない）、(c) 総合品質が 6 観点の平均、(d) 型違い・欠落は「取得失敗」として扱い全体を落とさない、(e) ファイル名にデータセット名・構成の識別子・コミット識別子・判定モデル名が入る、(f) 追記され、上書きには `--overwrite` が要る、(g) `testpaths` が `tests` のままで `script/evaluate.py` が収集対象外 |
| 実走（手動。合否条件に含めない） | `uv run python script/evaluate.py --dataset tr-basic --platform x --config configs/baseline.json --config configs/candidate.json` → `artifacts/eval/{dataset}__{config}__{commit}__{model}.jsonl` が作られ、判定のみ再実行（`--judge-only`）で同じ点数が得られる |

### S7. 検索クエリを自分で点検してから実行する（US7 / FR-049〜054 / SC-021・SC-036）

| | |
|---|---|
| 前提 | `TR_SELF_REVIEW` を `true` / `false` で切り替える |
| コマンド | `uv run pytest tests/unit/test_plan_search.py -q -k review` |
| 期待 | (a) 有効時は LLM 呼び出しが **2 回**（生成 1 ＋ 点検 1）、無効時は **1 回**、(b) `prompts_for("plan_search")[0]` が**生成**プロンプト（順序が固定）、(c) 点検が件数を**減らさない**（少ない場合は生成結果から補充）、(d) 点検が 0 行を返した場合は生成結果を採用、(e) 上限（X = 8、YouTube は無制限）を超えない、(f) 点検が失敗しても生成結果で継続 |
| 追加確認 | 既定の入力で検索クエリの内容と件数が変更前と一致する |

### S8. 実行コストと調整できる値が見える（US8 / FR-059〜062 / SC-023 / SC-034）

| | |
|---|---|
| 前提 | CLI から値域外の値を渡す（例: `--max-results 0`） |
| コマンド | `uv run pytest tests/integration/test_cli_contract.py -q -k "range or invalid"` |
| 期待 | (a) stderr に `設定が不正です: max_results=0（期待: 1 以上 100 以下の整数）`、(b) **exit 2**、(c) 丸めも既定値への置換もされない、(d) LLM が 1 回も呼ばれない、(e) `uv run pytest tests/unit/test_configuration.py -q -k declared` で全項目に型・値域・既定値・説明の宣言があること、(f) `TR_EVAL_MODEL` が `Configuration` の外で解決されること |

## 3. 手で確かめる統合シナリオ（CLI）

**注意**: 実 API を呼ぶ手動確認は**合格条件ではない**（FR-044）。テストスイートは
境界モックで完走する。以下は「既定の入力で観測可能な契約が変わっていないこと」を
目で確認するための手順である。

```bash
# 既定の入力（短い素材）で、変更前と同じ出力になること
uv run python -m trend_researcher "オタクの困りごとを調査したい" --platform x > /tmp/after.md
git stash && uv run python -m trend_researcher "オタクの困りごとを調査したい" --platform x > /tmp/before.md && git stash pop
diff /tmp/before.md /tmp/after.md   # 差分が出ないこと（FR-035 / SC-011）
```

| 確認項目 | 期待 |
|---|---|
| stdout | レポート（Markdown）のみ。進捗・ログが混ざらない |
| stderr | `[n/7] <node> ... <phase>（<detail>）` の**同じ文言・同じ行数** ＋ 追加の `[補足] ...` 行（圧縮・縮退・失敗・使用量があったときのみ） |
| 終了コード | 成功 0 / 実行時エラー 1 / 引数・設定エラー 2 |
| `cache/` | `report.json`（＋ `usage.json`）。`TR_INCLUDE_INTERMEDIATE=true` のときだけ `compressed.json` / `degradations.json` / `failures.json` が増える |
| レポート | 既存のキーと `notes` の要素が同一。新しい挙動（圧縮・失敗・縮退）が起きたときだけ `notes` が増える |

## 4. 契約の凍結を確認するコマンド（回帰の見張り）

```bash
# 進捗の文言と行数（厳密比較しているテスト）
uv run pytest tests/unit/test_progress.py tests/unit/test_analyze_content.py -q

# 呼び出し回数の凍結（analyze_content = 5 / extract_common = 1 / 同時 2）
uv run pytest tests/integration/test_full_flow.py tests/unit/test_analyze_content.py -q

# CLI の出力契約と終了コード
uv run pytest tests/integration/test_cli_contract.py -q

# プラットフォーム抽象（規則 (a)+(b) が 0 件）
uv run pytest tests/unit/test_platform_scan.py -q

# レポート形式（552 行のレンダリングテスト）
uv run pytest tests/unit/test_rendering.py -q
```

## 5. 変異探針（テストが欠陥を検出することを確かめる）

実装の完了条件には「テストが green」だけでなく「**対象の挙動を壊すとテストが落ちる**」を含める
（憲法 I の「無効なテスト」を避ける）。次の探針を 1 つずつ実行し、**必ずフルスイートで復元を確認する**。

| # | 変異 | 落ちるべきテスト |
|---|---|---|
| 1 | `asyncio.gather(..., return_exceptions=True)` を外す | 部分失敗（S4） |
| 2 | `shrink_ratio` を `1.0` にする | 縮退（S3） |
| 3 | 検出器の「除外条件」（条件 4）を削る | 検出器の反例（S3） |
| 4 | 再試行の待機を削る | 再試行（S2） |
| 5 | 圧縮の分岐を `pass` にする（`text[:max_chars]` のみ返す） | 圧縮（S1） |
| 6 | 圧縮後の切り詰めを削る | FR-007（S1） |
| 7 | `contexts` の解放を外す | 解放（S5） |
| 8 | 解放をレポート組み立ての**前**に移す | 解放の順序（S5） |
| 9 | `include_intermediate` の条件を反転する | 中間データ（S5） |
| 10 | `usage` の reducer を外す | 使用量の集約（S5） |
| 11 | `max_results` の `ge` を削る | 値域（S8） |
| 12 | `__main__.py` の再検証を削る | exit 2（S8） |
| 13 | 点検の呼び出しを削る | 呼び出し 2 回（S7） |
| 14 | 点検の「補充」を削る | 件数契約（S7） |
| 15 | 点検を生成の**前**に呼ぶ | プロンプト順序（S7） |
| 16 | 採点に `ge=1` を付ける | 値域検査をしないこと（S6） |
| 17 | 総合品質を `mean` から `sum` に変える | 集約（S6） |
| 18 | `script/evaluate.py` に `subprocess` を import する | 入口の契約（S6） |
| 19 | `script/evaluate.py` の初期状態に 4 番目のキーを足す | 入口の契約（S6） |
| 20 | 判定プロンプトの二重明示の 1 箇所を削る | プロンプトの走査（S7） |

**探針の手順（毎回同じ）**: 対象ファイルを `/tmp` に退避 → 変異を適用 → 対象テストを実行して
**落ちることを確認** → 退避から復元 → **フルスイートを再実行**して 601 件以上 green に戻ることを確認。

## 6. 未解決事項の実測（実装の前に済ませる）

`research.md` の「未解決事項」の 4 項目は、実装の分岐点であるため**最初に**実測する。

| # | 実測する内容 | 決め方 | 影響 |
|---|---|---|---|
| 1 | 構造化出力が `json_schema` で通るか | 実走の疎通確認 → 通らなければ `structured_method` の既定を `function_calling` に | 既定値 1 行 |
| 2 | 上限超過の応答の形（`status_code` / `body` / メッセージ） | 実走で採取し、検出器の語彙を確定 | 検出器の語彙（テストは語彙に依存しない形で書く） |
| 3 | 判定モデルの既定値（`TR_EVAL_MODEL`） | 実走の初回で疎通確認 | 既定値 1 行 |
| 4 | `model_copy` 後の再検証で `model_fields_set` が保たれるか | 短い Python スクリプトで実測 → 保たれない場合は `_check_bounds` を使う | `configuration.py` の 1 関数 |

## 7. 参照

| ドキュメント | 内容 |
|---|---|
| [spec.md](./spec.md) | 要件（FR-001〜074）、受入シナリオ（US1〜US8）、成功基準（SC-001〜036） |
| [plan.md](./plan.md) | 技術方針、憲法ゲート、基準値のずれ、設計上の判断 D-1〜D-3 |
| [research.md](./research.md) | 設計選択 R-1〜R-21、参照実装の欠陥に基づく移植統制 |
| [data-model.md](./data-model.md) | 設定・状態・モデル・評価のエンティティと不変条件 |
| [contracts/llm-invocation-contract.md](./contracts/llm-invocation-contract.md) | 構造化出力・再試行・縮退・上限超過の検出・使用量 |
| [contracts/context-management-contract.md](./contracts/context-management-contract.md) | 圧縮・部分失敗・状態のライフサイクル・中間データ |
| [contracts/settings-contract.md](./contracts/settings-contract.md) | 値域の宣言・起動時拒否・単一解決経路 |
| [contracts/query-planning-contract.md](./contracts/query-planning-contract.md) | 自己点検・件数契約・プロンプト |
| [contracts/evaluation-contract.md](./contracts/evaluation-contract.md) | 採点・比較・フィクスチャ・実走の入口 |
| `.specify/memory/constitution.md` | 開発原則（I〜VI）と品質ゲート |
