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
uv run pytest -q      # テスト（ネットワーク・認証情報不要で完走する）＋行カバレッジ計測
uv run ruff check .   # Lint
uv run mypy src       # 型チェック
```

`uv run pytest -q` は同時に行カバレッジを計測し、対象範囲の**合計が 90% を下回ると非ゼロ終了**します
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
| `--max-results N` | `5` | 解析対象の件数 |
| `--lang CODE` | `ja` | 字幕取得の優先言語（YouTube 用） |
| `--output PATH` | 標準出力 | レポート書き込み先ファイル |
| `--since YYYY-MM-DD` | なし | 投稿日下限 |
| `--sort {relevance,likes}` | `relevance` | 選定基準（X 用） |
| `--trends` | なし | トレンドワード探索モード（X 用・予約） |
| `--cache-dir PATH` | `cache/` | 中間成果物の永続化先 |

列挙値（`--platform` / `--format` / `--sort`）は**大文字小文字を区別**します。
`--platform X`、`--format JSON`、`--sort Relevance` はいずれも未知の値として引数エラー（終了コード 2）になります。

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
| `2` | 引数エラー | 指示の省略・空文字・空白のみ / `--platform` の省略または未知の値 / 未知の `--format`・`--sort` / `--since` が `YYYY-MM-DD` 以外 / `--max-results` が整数以外 |

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
中間成果物は `cache/` に JSON で永続化される（FR-012）。
