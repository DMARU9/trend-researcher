# Trend Researcher

自然言語のリサーチ指示（ブログ記事の参考にしたいトピック）を受け取り、LangGraph でオーケストレーションする CLI ツール。**X（Twitter）と YouTube の両方に対応**し、CLI の `--platform` オプションで対象を選択します。

`x_trend_researcher` と `youtube_trend_researcher` を統合したものです。パイプライン（7 ノード）は共通で、データソース・プロンプト・レンダリングのみをプラットフォームごとの `provider` で切り替えます。

- **X（Twitter）**: データソースは `twscrape`（アカウントクッキー要）。複数クエリ検索、いいね/RT/引用数を取得、スレッド＋リプライを文脈として取得。選定基準は「関連度順（既定）」または `--sort likes`。
- **YouTube**: データソースは `yt-dlp`（認証不要）。単一クエリ検索、字幕（自動翻訳含む）を文脈として取得。関連度順上位 N 件を解析対象。

## セットアップ

```bash
cd /home/takumi/github/trend-researcher
cp .env.example .env
# .env を編集し OPENAI_API_KEY 等を設定
uv sync --extra dev
```

### テスト・Lint・型チェック（品質ゲート）

変更を提出する前に、次の 3 つがすべて通ることを確認します（`.specify/memory/constitution.md`）。

```bash
uv run pytest -q -n auto   # テスト（ネットワーク・認証情報不要で完走する）＋行カバレッジ計測
uv run ruff check .        # Lint
uv run mypy src            # 型チェック
```

`uv run pytest -q -n auto` の `-n auto` は `pytest-xdist` による**並列実行**です（開発用の追加依存。
実行時依存は増えていません）。テストを 1 件も削らず、期待値も書き換えずに **60 秒以内**を満たします。

| 実行方法 | 実測（2026-09-15。1,102 件 / カバレッジ 97.64%） |
|---|---|
| `uv run pytest -q -n auto`（既定のゲート） | **34.2〜34.4 秒**（並列 16。`/usr/bin/time` の総計 36.5〜36.7 秒） |
| `uv run pytest -q`（直列） | 93.63 秒（総計 96.0 秒） |

`uv run pytest -q -n auto` は同時に行カバレッジを計測し、対象範囲の**合計が 90% を下回ると非ゼロ終了**します
（`pyproject.toml` の `[tool.coverage.report] fail_under = 90`）。未実行行は
`--cov-report=term-missing` で表示されるため、そのまま追記できます。

> 一部のテストだけを実行するときは `--no-cov` を付けてください。
> ```bash
> uv run pytest -q tests/unit/test_parse.py --no-cov   # しきい値の判定をしない
> ```
> しきい値は「実行した範囲の合計」に掛かるため、部分実行では全件 pass でも未達（終了コード 1）になります。

`ruff` と `mypy` は**どちらも 0 件**を維持します。変更前から存在していた違反
（`ruff` 40 件 / `mypy` 37 件、2026-09-12 時点）は本リポジトリで全件解消済みで、
抑制のための `# noqa` や `pyproject.toml` の除外設定は使っていません（2026-09-13）。

テストには実 API（OpenAI / X / YouTube）を使いません。外部呼び出しは `tools/` と
`providers/` の境界でモックします。実 API での確認は下記の手動スモークとして行い、
自動テストの合否条件には含めません。

### X（Twitter）を使う場合：アカウントクッキーの登録

X の検索には認証済みアカウントが必要です。`twscrape` が `accounts.db`（クッキー保存先）を利用します。
YouTube のみを使う場合はこの手順は不要です。

#### 手順 1：ブラウザからクッキーを取得

X（x.com）にログインした状態で、ブラウザのデベロッパーツール →
「Application / ストレージ → Cookies → x.com」から以下の値をコピーします。

- `auth_token`
- `ct0`
- その他 `twid` 等もあると精度が上がります

Netscape 形式（`# Netscape HTTP Cookie File` で始まるテキスト）でエクスポートした
`x_cookies.txt` があれば、手順 2 のスクリプトでそのまま読み込めます。

#### 手順 2：クッキーを `accounts.db` に登録

`tmp/register_x_account.py` のようなスクリプトで登録します（Netscape ファイルから解析）：

```python
import asyncio, json
from pathlib import Path
from twscrape import AccountsPool

COOKIE_FILE = Path("tmp/x_cookies.txt")   # Netscape 形式
USERNAME = "DMARU009"                      # 任意の識別名（自分のアカウント名等）

def parse_netscape(path: Path) -> str:
    """Netscape 形式クッキーファイルを 'name=value; ...' 形式の JSON 文字列に変換。"""
    cookies: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    return json.dumps(cookies)

async def main() -> None:
    cookies_json = parse_netscape(COOKIE_FILE)
    pool = AccountsPool("accounts.db")
    # 既存登録をリセットしてから登録（初回は不要）
    existing = await pool.get_all()
    if existing:
        await pool.delete_accounts([a.username for a in existing])
    await pool.add_account(
        USERNAME, "", "", "",
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        cookies=cookies_json,
    )
    accs = await pool.get_all()
    print(f"登録完了: {len(accs)} 件")
    for a in accs:
        print(f"  - {a.username} | active={a.active} | cookies={len(a.cookies)}")

asyncio.run(main())
```

実行：

```bash
uv run python tmp/register_x_account.py
```

> **補足**：`twscrape add_cookie <username> <cookies>` コマンドでも登録できますが、
> `<cookies>` には `name=value; name=value` 形式の文字列を渡す必要があります
> （Netscape 形式のファイルをそのまま渡すと `auth_token` / `ct0` が見つからず失敗します）。
> 上記スクリプトは Netscape ファイルも扱えるため確実です。

#### 手順 3：動作確認

```bash
uv run python -m trend_researcher "Claude Code の使い方" --platform x --max-results 3
```

検索結果が 0 件で `No active accounts` と警告される場合は、クッキーが正しく登録
されていないか期限切れです。再度手順 1・2 をやり直してください。

## 使い方

```bash
# X（Twitter）対象・既定 5 件・Markdown
uv run python -m trend_researcher \
  "Claude Code で会社を回す方法を解説しているポストを参考にブログを書きたい" \
  --platform x

# YouTube 対象
uv run python -m trend_researcher \
  "Claude Code で会社を回す方法を解説している動画を参考にブログを書きたい" \
  --platform youtube

# 件数指定・JSON 出力
uv run python -m trend_researcher \
  "機械学習チュートリアルを参考にブログを書きたい" \
  --platform youtube --max-results 10 --format json --output out.json

# X のいいね数順（バズ把握用）
uv run python -m trend_researcher \
  "Claude Code の使い方" --platform x --max-results 10 --sort likes

# 投稿日で絞り込み（--since YYYY-MM-DD または自然言語「半年以内」等）
uv run python -m trend_researcher \
  "半年以内に公開された機械学習の基礎投稿" --platform youtube --max-results 3
```

### オプション

| オプション | 既定値 | 説明 |
|-----------|--------|------|
| `INSTRUCTION`（位置引数） | 必須 | 自然言語のリサーチ指示（空文字・空白のみは不可 → 終了コード 2） |
| `--platform {x,youtube}` | 必須 | 対象プラットフォーム（省略すると終了コード 2） |
| `--format {markdown,json}` | `markdown` | 最終レポートの出力形式 |
| `--max-results N` | `5` | 解析対象の件数（`1`〜`100`。範囲外・整数以外は起動時に拒否 → 終了コード 2） |
| `--lang CODE` | `ja` | 字幕取得の優先言語（YouTube 用） |
| `--output PATH` | 標準出力 | レポート書き込み先ファイル |
| `--since YYYY-MM-DD` | なし | 投稿日下限 |
| `--sort {relevance,likes}` | `relevance` | 選定基準（X 用） |
| `--cache-dir PATH` | `cache/` | 中間成果物の永続化先 |

列挙値（`--platform` / `--format` / `--sort`）は**大文字小文字を区別**します。
`--platform X`、`--format JSON`、`--sort Relevance` はいずれも未知の値として引数エラー（終了コード 2）になります。

### 環境変数

実行時設定は `.env`（または環境変数）から供給します。名前は **共通の `TR_*`**、**X 固有の `XTR_*`**、
**YouTube 固有の `YTR_*`** の 3 群です。共通の項目は `TR_*` に置けば両プラットフォームで使われ、
片方だけ変えたいときは `XTR_*` / `YTR_*` で上書きします。

| 群 | 変数 | 既定値 | 説明 |
|---|---|---|---|
| 共通 | `TR_MODEL` | `openai:mimo-v2.5` | LLM のモデル名 |
| 共通 | `TR_MAX_RESULTS` | `5` | 解析対象の件数（`1`〜`100`） |
| 共通 | `TR_TRANSCRIPT_LANG` | `ja` | 字幕取得の優先言語 |
| 共通 | `TR_CACHE_DIR` | `cache` | 中間成果物の永続化先（相対パスはリポジトリ直下基準） |
| 共通 | `TR_ANALYSIS_CONCURRENCY` | `2` | 個別解析の同時実行数（`1`〜`16`） |
| 共通 | `TR_RETRY_MAX` | `2` | LLM 応答が契約を満たさないときの再試行回数・初回を除く（`0`〜`10`） |
| 共通 | `TR_RETRY_WAIT_SECONDS` | `1.0` | 再試行の前に待つ秒数（`0`〜`60`） |
| 共通 | `TR_COMPRESSION_THRESHOLD` | `20000` | 素材がこの文字数を超えたら LLM で圧縮する（`1000` 以上） |
| 共通 | `TR_COMPRESSION_TIMEOUT_SECONDS` | `60.0` | 圧縮 1 回あたりのタイムアウト秒（`1`〜`300`） |
| 共通 | `TR_DEGRADE_MAX_ATTEMPTS` | `3` | 上限超過のときに入力を縮小して呼び直す最大段数（`1`〜`10`） |
| 共通 | `TR_SHRINK_RATIO` | `0.9` | 縮退 1 段あたりの入力長の比率（`0.1`〜`0.9`） |
| 共通 | `TR_MIN_INPUT_CHARS` | `1000` | 縮退を打ち切る入力長の下限（`100` 以上） |
| 共通 | `TR_SELF_REVIEW` | `true` | 検索クエリを生成直後に点検するか（`true` / `false`） |
| 共通 | `TR_INCLUDE_INTERMEDIATE` | `false` | 圧縮・縮退・失敗の中間データを `cache/` に書き出すか（`true` / `false`） |
| 共通 | `TR_STRUCTURED_METHOD` | `json_schema` | 構造化出力の方式（`json_schema` / `function_calling`） |
| X 固有 | `XTR_ACCOUNTS_DB` | `accounts.db` | `twscrape` のアカウント DB（クッキー保存先） |
| X 固有 | `XTR_SEARCH_POOL_SIZE` | `50` | いいね順ソート用の検索プールサイズ |
| X 固有 | `XTR_MAX_RETRIES` | `3` | X 境界の最大リトライ回数 |
| YouTube 固有 | `YTR_TRANSCRIPT_LANG` | `ja` | 字幕取得の優先言語（YouTube で変えたいとき） |
| LLM 接続 | `OPENAI_API_KEY` / `OPENAI_BASE_URL` | — / `https://opencode.ai/zen/go/v1` | OpenAI 互換 API の接続情報 |
| 評価 | `TR_EVAL_MODEL` | `openai:mimo-v2.5` | 判定（採点）に使うモデル名。出荷する `Configuration` には現れない（評価の実走専用） |

解決の順序は **明示指定（CLI オプション） > 環境変数（`TR_*` → `XTR_*` / `YTR_*`） > 既定値**です。
たとえば `--max-results 10` は `TR_MAX_RESULTS` より優先され、`TR_MAX_RESULTS` は
`XTR_MAX_RESULTS`（`--platform x` のとき）より優先されます。
設定の入口は `Configuration`（実行時設定の唯一の型）で、ノードは環境変数を直接読みません。
実際の値の一覧は `.env.example` を参照してください。

**宣言した値域は起動時に検査します**。環境変数（`TR_*`）や `--max-results` などで範囲外の値を
渡すと、LLM 呼び出しや検索を始める前に `[エラー] 設定が不正です: <項目>=<値>（期待: …）`
を stderr に出して**終了コード 2** で止まります（丸めたり既定値へ置き換えたりしません）。
`Configuration` の全項目は `x_oap_ui_config`（型・ラベル・説明・値域）を持つため、
LangGraph Studio の `configurable` から同じ制約の下で変更できます。

### 出力チャネル

- **stdout**: 最終レポート（Markdown または JSON）**のみ**。進捗行もエラーメッセージも出しません。
  `--output` を指定したときは**レポートを stdout に出さない**（0 バイト）
- **stderr**: 進捗（`[n/7] <node> ... 開始` / `完了`）・ログ・警告・エラー。
  メッセージは `[エラー]` / `[警告]` / `[情報]` / `[完了]` の接頭辞で始まります

```bash
# 例: レポートをファイルに出す（stdout には何も出さず、完了メッセージは stderr に出る）
uv run python -m trend_researcher "Claude Code の使い方" --platform x --output out.md
# stderr: [完了] レポートを out.md に書き出しました。

# 例: 書き込み先の親ディレクトリが存在しない（--output の書き込み失敗）
uv run python -m trend_researcher "Claude Code の使い方" --platform x --output /tmp/no_such_dir/out.md
# stderr: [エラー] レポートを /tmp/no_such_dir/out.md に書き出せませんでした: <理由>
# 終了コード: 1（Traceback は出しません）
```

`--output` の書き込み失敗は、親ディレクトリの欠落・書込不可・ディレクトリの指定のいずれでも
`[エラー] レポートを <PATH> に書き出せませんでした: <理由>` を stderr に出して終了コード 1 になります。

### 終了コード

| コード | 意味 | 条件の例 |
|--------|------|----------|
| `0` | 成功 | レポートの生成 / 検索結果が 0 件 / 要求件数より取得件数が少ない / `--output` への書き出し成功 / `--help` |
| `1` | 実行時エラー | 実行中の例外 / 時間上限 / レポート未生成 / `--output` の書き込み失敗 |
| `2` | 引数エラー | 指示の省略・空文字・空白のみ / `--platform` の省略または未知の値 / 未知の `--format`・`--sort` / `--since` が `YYYY-MM-DD` 以外 / `--max-results` が整数以外・`1`〜`100` の範囲外 / 宣言した値域外の環境変数（例: `TR_ANALYSIS_CONCURRENCY=0`） |

この 3 値以外を返しません（`0` = 成功、`1` = 実行時エラー、`2` = 引数エラー）。
契約の全条件は `specs/001-test-suite-hardening/contracts/cli-contract.md` を参照してください。

## アーキテクチャ

```
parse_instruction → plan_search → search → fetch
                                                │
                                                ▼
                                           analyze_content (並列, 上限2)
                                                │
                                                ▼
                                           extract_common → compile_report → END
```

プラットフォーム差（検索・ソース取得・レンダリング）は `src/trend_researcher/providers/` に集約。
中間成果物は `cache/` に JSON で永続化される（FR-012）。`analyze_content` の並列度は
`--max-results` とは独立で、既定 2（`TR_ANALYSIS_CONCURRENCY` で変更可）。

### `cache/` に書かれるもの

`--cache-dir`（既定 `cache/`）を指定した実行では、次の JSON が書かれます。

| ファイル | 内容 |
|---|---|
| `report.json` | 最終レポート。**使用量は入れない**（本文に描画される `notes` を汚さないため。集計は `usage.json` 側） |
| `usage.json` | LLM 呼び出しとトークンの集計（`calls` / `unknown_calls` / `input_tokens` / `output_tokens` / `total_tokens` / `by_node` / `by_role`） |
| `compressed.json` | 圧縮の記録（`TR_INCLUDE_INTERMEDIATE=true` のときだけ） |
| `degradations.json` | 縮退の記録（同上） |
| `failures.json` | 失敗の記録（同上） |

`usage.json` は**必ず**書かれます（LLM を 1 回も呼ばなかった実行も `calls: 0` として残ります）。
トークン数を返さないプロバイダ（設定によっては `usage_metadata` が空）では、件数を
`unknown_calls` に分けて計上します。実行の最後には stderr に 1 行の集計が出ます。

```
[i/7] compile_report ... 完了
[補足] LLM 呼び出し合計 9 回（入力 0 / 出力 0 トークン、不明 9 回）
```

なお `[補足]` は追加の観測（圧縮・縮退・失敗・使用量）だけに使う行で、進捗の番号は進めず、
stdout にも出ません（`emit()` の書式と `messages` は変えません）。

### 評価の実走

品質（指示追従・網羅性・根拠の有無など）を外部の判定モデルで採点したいときは `script/evaluate.py`
を使います。**通常の実行（CLI の既定値）とは別経路**で、出荷する `Configuration` には影響しません。

```bash
uv run python script/evaluate.py                 # 既定のケースを実行して採点
TR_EVAL_MODEL=openai:gpt-5-mini uv run python script/evaluate.py   # 判定モデルを差し替える
```

結果は `artifacts/eval/`（**追跡外**。`.gitignore` 済み）に保存されます。ケースの軸と対応表は
`tests/eval/axes.md`、プロンプトは `tests/eval/prompts.py` を参照してください。
