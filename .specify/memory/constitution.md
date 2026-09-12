<!--
Sync Impact Report
==================
Version change: 1.0.0 → 1.1.0
Rationale: MINOR（原則の追加）。リファクタリング時の後方互換性の扱いを原則 VI として
  明文化した。既存原則の削除・再定義は行っていない。

Modified principles:
  - VI. リファクタリングは後方互換を要求しない（新規追加）
  - I〜V は変更なし（V との境界を原則 VI で明示）

Added sections: なし（Core Principles に原則 VI を追加）
Removed sections: なし

Templates requiring updates:
  ✅ .specify/templates/plan-template.md（Constitution Check にゲート VI を追加）
  ✅ .specify/templates/tasks-template.md（リファクタリングタスクの互換シム禁止を追記）
  ✅ .github/agents/speckit.tasks.agent.md（変更不要。憲法を参照する汎用記述のため）
  ✅ README.md（変更不要。判断基準は憲法側に集約するため）

History:
  - v1.0.0（2026-09-12）: 初期テンプレートから初版採択。原則 I〜V、技術制約と品質基準、
    開発ワークフローと品質ゲート、Governance を具体化。

Follow-up TODOs:
  - TODO(BASELINE-BURNDOWN): 採択時点の実測値（2026-09-12）= テスト 61 passed /
    ruff 40 errors / mypy 37 errors。リポジトリ全体を green にする追跡タスクを
    `/speckit.tasks` で起票する（移行措置は「開発ワークフローと品質ゲート」節）。
-->

# Trend Researcher Constitution
<!-- プロジェクト: trend-researcher（X / YouTube トレンドリサーチ CLI、LangGraph 7 ノードパイプライン） -->

## Core Principles

### I. テスト必須（NON-NEGOTIABLE）

すべての挙動変更・新機能は、対応する自動テストと同時に提供する MUST。
テストを伴わない機能追加は「未完了」とみなし、レビューに提出してはならない（MUST NOT）。

- テストを先に書き、失敗することを確認してから実装する（Red → Green → Refactor）。
- `tasks.md` のテストタスクは省略できない MUST。各ユーザーストーリーには、その
  ストーリー単体で検証できるテストタスクを最低 1 つ含める。
- テストの配置は既存構成に従う MUST:
  - `tests/unit/` … tools / nodes / パーサ / models / configuration の単体
  - `tests/integration/` … グラフ全経路（parse→…→compile）と CLI 経路
- 「落ちるべきときに落ちる」テストのみをテストと認める MUST。対象の挙動を削除・改変
  しても緑のままのテスト（テスト内での実装のコピー、恒真アサート、収集されない
  fixture）は無効であり、無効なテストしかない変更は未完了とみなす。
- 完了条件の一つは `uv run pytest -q` が全件 green であること MUST。

**Rationale**: LLM・外部メディア・並列実行が絡む本パイプラインは目視確認では回帰を
検出できない。テストは唯一の再現可能な回帰防止手段であり、Spec Kit のタスク生成でも
「テストが最初から付いてくる」状態を保つために非交渉とする。

### II. 外部 I/O の境界分離とオフラインテスト

外部サービスへのアクセス（LLM API、`twscrape`、`yt-dlp`、HTTP、ファイルシステム）は
`src/trend_researcher/tools/` と `src/trend_researcher/providers/` の境界に限定する MUST。
グラフ（`graph.py`）とノード（`nodes/`）はロジックのみを持ち、SDK を直接呼んでは
ならない（MUST NOT）。

- テストスイートはネットワークと認証情報なしで完走する MUST。`OPENAI_API_KEY`・
  `accounts.db`・X のクッキー・`yt-dlp` の実通信を要求するテストは禁止（MUST NOT）。
  外部呼び出しは必ず境界でモックする（`unittest.mock.patch` を既存踏襲）。
- 実際の API を叩く確認は手動スモーク（README 記載のコマンド）として扱い、
  自動テストの合否条件に含めてはならない（MUST NOT）。
- 新しい外部 SDK を導入する場合、その SDK は薄い関数／クラスの背後からのみ参照する
  MUST（差し替え可能な継ぎ目を必ず用意する）。
- 除外できない非決定性（時刻、乱数、並列順序）はテスト側で固定する MUST。

**Rationale**: X のクッキーや LLM の可用性に依存しないことが、テストを「常に回せる」
状態に保つ前提である。数十件のテストが数秒で完走する現在の実行時間は、この境界の
維持によって成立している。

### III. 型付きパイプライン契約

ノード間で受け渡すデータは `state.py` の `AgentState` / `AgentInputState` と
`models.py` の Pydantic モデルを唯一の契約とする MUST。新しい受け渡しを生の dict で
追加してはならない（MUST NOT）。

- 状態・モデルにフィールドを追加／変更する場合は、先に `state.py` または `models.py`
  を更新し、影響する全ノード・provider・レンダラ・テストを同一変更で追随させる MUST
  （部分的な変更を残したまま次の作業へ進まない）。
- 実行時設定は `Configuration`（`RunnableConfig` 経由）で受け渡す MUST。provider や
  `Config` などのランタイムオブジェクトを State に持たせてはならない（MUST NOT）。
- LLM の自由文出力を扱う解析は `tools/parse.py` の決定的な関数に閉じ込め、正常系と
  フォールバック経路の両方をテストで固定する MUST。
- モデルの表現は `cache/` に JSON として永続化されるため、フィールド名・型の変更は
  後方互換を壊す変更として扱い、`tests/` の期待値を同時更新する MUST。

**Rationale**: LangGraph の状態は暗黙に肥大しやすく、型とテストがなければ破壊的変更を
検出できない。`state.py` / `models.py` / `Configuration` の 3 点を明示的な契約として扱う。

### IV. プラットフォーム抽象（Provider 境界）

コア（`graph.py` / `nodes/` / `models.py`）はプラットフォーム非依存を維持する MUST。
X と YouTube の差（検索・ソース取得・プロンプト・レンダリング）は `providers/` に
実装する MUST。

- 新プラットフォームは「`Provider` プロトコルの実装」＋「`providers/__init__.py` への
  登録」＋「provider 単体テスト」で追加できる MUST。ノードやグラフに
  `platform == "..."` の新しい分岐を追加してはならない（MUST NOT）。
- 既存のプラットフォーム分岐（`nodes/compile_report.py` などに残存）は、そのファイルを
  変更する際に provider のフックへ寄せる SHOULD。
- 表ヘッダ・ラベル・件名など出力の差分は provider のメソッド／プロパティで表現する MUST。
- プラットフォームを追加・変更する際は、既存プラットフォームのテストが緑のままである
  ことを確認する MUST（片方の変更がもう片方を壊していないこと）。

**Rationale**: 統合前の X / YouTube 2 実装の差を吸収することが本リポジトリの核であり、
分岐がノードへ漏れるとテストも分岐爆発する。

### V. CLI 出力契約と観測可能性

CLI の出力契約を維持する MUST。新規の出力・終了経路は次の規約に従う。

- **stdout** は最終レポート（Markdown / JSON）のみ。**stderr** は進捗・ログ・エラー
  （FR-013）。
- **終了コード**は 0 = 成功、1 = 実行時エラー、2 = 引数エラー。契約を変える場合は
  README とテストを同時に更新する MUST。
- 各ノードは `ProgressEmitter` を通じて開始／完了を必ず出力し、中間状態を空にしない
  MUST。`NODE_ORDER`・`ProgressEmitter.TOTAL`・グラフのノード数の一致を保つ MUST
  （変更時はテストで固定）。
- 中間成果物は `cache/` 配下に JSON（UTF-8 / `ensure_ascii=False`）で永続化する MUST
  （FR-012）。
- エラーは握りつぶさず stderr へ出力し、終了コードに反映する MUST。秘密情報（API
  キー、クッキー、`accounts.db`）をリポジトリへコミットしてはならない（MUST NOT）。

**Rationale**: CLI はパイプラインを外部から検証できる唯一の観測点であり、
stdout / stderr / 終了コードはテストで固定できる契約である。

### VI. リファクタリングは後方互換を要求しない

内部構造の改善（リファクタリング）を目的とする変更に、後方互換性の維持を要求しない
（MUST NOT）。旧仕様を残すための互換シム（旧関数・旧引数・旧フィールド・旧モジュール
パスへのエイリアス、非推奨警告付きの二重実装）を追加してはならない MUST NOT。

- 対象はリポジトリ内部の API（モジュール構成、関数・クラス名、引数、State の
  フィールド、provider の内部 IF、private ヘルパ）。改名・削除・シグネチャ変更は自由に
  行ってよく、旧名の別名を残す必要はない。
- 改名・削除は同一変更内で全参照（実装・テスト・README / spec / tasks）を更新する MUST。
  新旧併存の部分移行を残したまま次の作業へ進んではならない（MUST NOT）。
- リファクタリングの正しさは「互換層の有無」ではなく**振る舞いを固定するテスト**で
  検証する MUST（原則 I を適用。変更前に green、変更後も同じ振る舞いで green）。
  リファクタリングでは既存テストの期待値そのものを書き換える必要はない
  （書き換えが必要になった場合、それは振る舞いの変更である）。
- モデル（`models.py`）のフィールド改名・削除は、原則 III のとおり `cache/` の JSON
  表現を変える破壊的変更として扱い、テストを同一変更で更新する MUST。`cache/` は
  現在「書き込み専用」（読み戻し経路は未実装）のため、旧 JSON を読むための
  マイグレーションや互換読み込みを実装する必要はない MUST NOT。
- **例外（互換維持が必要な外部契約）**: 利用者が直接依存する次の契約はこの原則の対象外。
  ただし互換層を残すのではなく、契約変更時の同一変更での更新（原則 III / V）で対応する MUST。
  - CLI のオプション名・出力形式・終了コード（0/1/2）
  - README に記載された実行コマンドと環境変数（`TR_*` / `XTR_*` / `YTR_*`）
- 「将来使うかもしれない」ための互換コード・フラグ・抽象化を先回りで追加してはならない
  MUST NOT（YAGNI）。

**Rationale**: 本リポジトリは開発中の CLI であり、外部に公開された API を持たない。
互換シムはコードを二重化してテスト面積を膨らませ、リファクタリングの最大の利得である
「単純さ」を失わせる。安全網は互換層ではなくテストで確保する。

## 技術制約と品質基準

**言語・実行環境**: Python 3.11 以上。`uv` で依存と仮想環境を管理する MUST
（`uv sync --extra dev` / `uv run ...`）。パッケージレイアウトは
`src/trend_researcher/`（hatchling ビルド）。

**主要依存**: LangGraph / LangChain（`langchain-openai`）、Pydantic v2、`twscrape`（X）、
`yt-dlp`（YouTube）、`python-dotenv`。依存の追加は必要性を説明できる場合に限る SHOULD
（YAGNI）。

**外部接続**: LLM は OpenAI 互換 API（`OPENAI_BASE_URL` / `OPENAI_API_KEY`）。モデル名・
件数・キャッシュ先などの実行条件は `.env` と `Config` から供給し、コードに
ハードコードしてはならない（MUST NOT）。

**静的品質**: `ruff`（line-length 100 / target py311）と `mypy`（`src` 対象）を
`pyproject.toml` の設定のまま維持する MUST。設定変更は根拠を伴う場合のみ行う。

**永続化**: DB は持たない。中間成果物は `cache/` の JSON のみ（`cache.py`）。

**秘密情報**: `.env` と `accounts.db` はコミットしない（MUST NOT）。テストは実認証情報を
要求してはならない（MUST NOT）。

**並列性**: 解析は並列上限 2（`asyncio.Semaphore(2)`）を既定とする MUST。変更はテストで
固定し、上流 API のレート制限を考慮した根拠を示す MUST。

## 開発ワークフローと品質ゲート

**Spec Kit フロー**: 機能は `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` →
`/speckit.implement` の順で進める MUST。実装開始前に plan の Constitution Check を
通過させる MUST（違反は Complexity Tracking に正当化を記載し、正当化できない場合は
実装しない）。

**テストタスクの必須化**: `/speckit.tasks` が生成するタスクには、各ユーザーストーリーの
テストタスクを必ず含める MUST（`.specify/templates/tasks-template.md` の OPTIONAL 扱いも
廃止済み）。

**品質ゲート（変更提出前に green）**:

1. `uv run pytest -q`
2. `uv run ruff check .`
3. `uv run mypy src`

**既存違反のベースライン（移行措置）**: 本憲法の採択時点で、リポジトリ全体の `ruff` /
`mypy` には既存違反が残っている。移行期間中は次の規則で扱う MUST。

- 新規ファイルおよび変更したファイルはゲートを green にして提出する MUST
  （boy-scout ルール）。
- ベースラインの違反件数を増やしてはならない（MUST NOT）。増加は新規違反として扱う。
- リポジトリ全体を green にする作業は追跡タスクとして起票し、解消する MUST。
- `pytest` は既存を含めて常に全件 green を維持する MUST（テストには移行措置を適用しない）。

**完了の定義（DoD）**: 実装コード、対応するテスト、影響する README / spec / tasks の
更新、上記 3 ゲートの結果（移行期間中は変更ファイル分の green）が揃って完了とする。
手動スモーク（README の実 API 実行例）は確認として推奨するが、完了条件ではない。

**レビュー観点**: (a) 出力契約（stdout / stderr / 終了コード）の維持、(b) 外部 I/O が
境界に閉じているか、(c) プラットフォーム分岐が provider に留まっているか、
(d) 既存テストが回帰していないか、(e) テストが「落ちるべきときに落ちる」か、
(f) リファクタリング時に互換シムや旧経路の残骸が残っていないか（原則 VI）。

## Governance

- 本憲法はリポジトリ内の他の慣行・ドキュメントに優先する MUST。矛盾する実装・運用を
  見つけた場合は、憲法を基準に是正する。
- **改正手続き**: 変更は `/speckit.constitution` を通じて提案し、原則の追加・削除・
  再定義と影響範囲（テンプレート、spec、plan、tasks）を Sync Impact Report に記録する
  MUST。改正後は `.specify/templates/` と該当 spec を同一変更で追随させる MUST。
- **バージョニング**: MAJOR = 原則の削除・再定義など後方互換でない変更、MINOR = 原則の
  追加または実質的な拡張、PATCH = 文言修正・明確化。
- **遵守レビュー**: 各 plan の Constitution Check を唯一のゲートとし、違反は
  Complexity Tracking の正当化とセットでのみ許容する。原則 I（テスト必須）は例外を
  認めない（NON-NEGOTIABLE）。緊急対応であってもテストを省略せず、少なくとも回帰を
  固定するテストを残す MUST。
- 実行時の開発ガイダンスは `README.md` と `.github/copilot-instructions.md` を参照する。

**Version**: 1.1.0 | **Ratified**: 2026-09-12 | **Last Amended**: 2026-09-12
