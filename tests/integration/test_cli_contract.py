"""CLI の外部契約テスト（`contracts/cli-contract.md`）。

契約は `main()` の戻り値ではなく**実行プロセスの観測結果**で検証する（FR-002）。
このモジュールは層 A（`python -m trend_researcher <args>` を直接起動。モック不要）を
担う。境界モックを注入する層 B（成功経路・実行時エラー）は同じファイルに追記する。

層 A が検証するのは「引数検証が外部接続より前に完走すること」である。そのため
ネットワークにも認証情報にも触れない（CLI-006-1 / CLI-006-2 / CLI-006-3）。
"""

from __future__ import annotations

import json

import pytest

from trend_researcher.progress import NODE_ORDER

#: X の成功経路で使う共通引数（件数を明示し、自然言語の件数解釈に依存しない）
X_ARGS = ("AI 動画のトレンドを3件教えて", "--platform", "x", "--max-results", "3")

#: YouTube の成功経路で使う共通引数
YT_ARGS = ("AI 動画のトレンドを3件教えて", "--platform", "youtube", "--max-results", "3")

# --- CLI-001-6: --help -----------------------------------------------------


def test_cli_001_06_help_exits_zero(cli_module_runner):
    """CLI-001-6: `--help` は終了コード 0。使い方を stdout に出し、stderr は空。"""
    result = cli_module_runner("--help")

    assert result.exit_code == 0
    assert "usage: trend_researcher" in result.stdout
    assert result.stderr == ""


# --- CLI-001-10 〜 CLI-001-16: 引数エラー ---------------------------------


def test_cli_001_10_unknown_platform(cli_module_runner):
    """CLI-001-10: 未知のプラットフォーム値は引数エラー（2）。"""
    result = cli_module_runner("AI 動画のトレンド", "--platform", "tiktok")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "invalid choice" in result.stderr


def test_cli_001_11_missing_instruction(cli_module_runner):
    """CLI-001-11: 必須の位置引数（指示）を省略すると引数エラー（2）。"""
    result = cli_module_runner("--platform", "x")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "instruction" in result.stderr


def test_cli_001_12_missing_platform(cli_module_runner):
    """CLI-001-12: `--platform` を省略すると引数エラー（2）。"""
    result = cli_module_runner("AI 動画のトレンド")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--platform" in result.stderr


def test_cli_001_13_invalid_since(cli_module_runner):
    """CLI-001-13: `--since` に `YYYY-MM-DD` 以外を指定すると引数エラー（2）。"""
    result = cli_module_runner("AI 動画のトレンド", "--platform", "x", "--since", "2025/01/01")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "[エラー] --since は YYYY-MM-DD 形式で指定してください: 2025/01/01" in result.stderr


def test_cli_001_14_unknown_format(cli_module_runner):
    """CLI-001-14: 未知の `--format` 値は引数エラー（2）。"""
    result = cli_module_runner("AI 動画のトレンド", "--platform", "x", "--format", "xml")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "invalid choice" in result.stderr


def test_cli_001_15_unknown_sort(cli_module_runner):
    """CLI-001-15: 未知の `--sort` 値は引数エラー（2）。"""
    result = cli_module_runner("AI 動画のトレンド", "--platform", "x", "--sort", "newest")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "invalid choice" in result.stderr


def test_cli_001_16_non_integer_max_results(cli_module_runner):
    """CLI-001-16: `--max-results` に整数以外を指定すると引数エラー（2）。"""
    result = cli_module_runner("AI 動画のトレンド", "--platform", "x", "--max-results", "abc")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "invalid int value" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(("指示", "--platform", "X"), id="platform-uppercase"),
        pytest.param(("指示", "--platform", "x", "--format", "JSON"), id="format-uppercase"),
        pytest.param(("指示", "--platform", "x", "--sort", "Relevance"), id="sort-capitalized"),
        pytest.param(("指示", "--platform", "YouTube"), id="platform-capitalized"),
    ],
)
def test_cli_005_enums_are_case_sensitive(cli_module_runner, args):
    """CLI-005 の注意 / CLI-001-10: 列挙値の大文字小文字は正規化しない（すべて 2）。"""
    result = cli_module_runner(*args)

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "invalid choice" in result.stderr


# --- CLI-001-17: 空の指示（T017 で修正する欠陥） --------------------------


@pytest.mark.parametrize(
    "instruction",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="spaces"),
        pytest.param("\t\n ", id="tabs-and-newline"),
        pytest.param("　", id="ideographic-space"),
    ],
)
def test_cli_001_17_blank_instruction(cli_module_runner, instruction):
    """CLI-001-17: 指示が空文字または空白のみなら引数エラー（2）。

    T017 の修正前は argparse を通過して実行に進み、終了コード 1（認証情報欠如）に
    なるため、このテストは失敗する。
    """
    result = cli_module_runner(instruction, "--platform", "x")

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "[エラー] 指示を指定してください。" in result.stderr


# ===========================================================================
# 層 B: 境界モックを注入した実行（成功経路 / 0 件 / 出力先 / 実行時エラー）
# ===========================================================================


# --- CLI-001-1: 正常終了 ---------------------------------------------------


def test_cli_001_01_success_exits_zero(cli_runner):
    """CLI-001-1: 正常にレポートを生成すると終了コード 0。"""
    result = cli_runner(*X_ARGS)

    assert result.exit_code == 0
    assert result.stdout != ""


def test_cli_001_01_youtube_success_exits_zero(cli_runner):
    """CLI-001-1: YouTube 経路でも正常終了は 0。"""
    result = cli_runner(*YT_ARGS, scenario="youtube_success")

    assert result.exit_code == 0
    assert result.stdout != ""


# --- CLI-002: 出力チャネルの分離 -------------------------------------------


def test_cli_002_01_stdout_is_report_only(cli_runner):
    """CLI-002-1: stdout は最終レポートのみ（先頭がレポートのタイトル行）。"""
    result = cli_runner(*X_ARGS)

    assert result.stdout.startswith("# リサーチレポート: ")
    assert result.stdout.count("# リサーチレポート: ") == 1


def test_cli_002_02_stdout_has_no_progress_lines(cli_runner):
    """CLI-002-2: stdout に進捗行（`[n/7] <node> ... <phase>`）を含まない。"""
    result = cli_runner(*X_ARGS)

    for index, node in enumerate(NODE_ORDER, start=1):
        assert f"[{index}/7] {node}" not in result.stdout
    assert "[1/7]" not in result.stdout


def test_cli_002_04_stderr_has_seven_nodes_progress(cli_runner):
    """CLI-002-4: stderr に 7 ノード分の進捗行（開始・完了）が出る。"""
    result = cli_runner(*X_ARGS)
    stderr_lines = result.stderr_lines()

    for index, node in enumerate(NODE_ORDER, start=1):
        prefix = f"[{index}/7] {node} ... "
        phases = [line[len(prefix) :] for line in stderr_lines if line.startswith(prefix)]
        assert any(p.startswith("開始") for p in phases), f"{node} の開始行が見つかりません"
        assert any(p.startswith("完了") for p in phases), f"{node} の完了行が見つかりません"


def test_cli_002_05_information_messages_go_to_stderr(cli_runner):
    """CLI-002-5: ログ・情報メッセージは stderr に出て stdout には混入しない。"""
    result = cli_runner(*X_ARGS, scenario="x_fewer")

    assert "[情報] 要求件数 3 件に対し、実際に見つかったのは 1 件です。" in result.stderr
    assert "[情報]" not in result.stdout


# --- CLI-003: 出力形式 ----------------------------------------------------


def test_cli_003_01_markdown_is_default(cli_runner):
    """CLI-003-1: `--format markdown`（既定）は `# リサーチレポート: ` で始まる。"""
    result = cli_runner(*X_ARGS)

    assert result.stdout.startswith("# リサーチレポート: ")


def test_cli_003_02_json_is_single_object(cli_runner):
    """CLI-003-2: `--format json` の stdout 全体が単一の JSON オブジェクトとして解析できる。"""
    result = cli_runner(*X_ARGS, "--format", "json")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)


def test_cli_003_03_json_has_all_keys(cli_runner):
    """CLI-003-3: JSON に指示・候補・解析・共通テーマ・出典・備考・生成時刻が含まれる。"""
    result = cli_runner(*X_ARGS, "--format", "json")
    payload = json.loads(result.stdout)

    assert set(payload) >= {
        "instruction",
        "candidates",
        "analyses",
        "common_themes",
        "sources",
        "notes",
        "generated_at",
    }


def test_cli_003_04_json_format_reaches_instruction(cli_runner):
    """CLI-003-4: CLI → Configuration → parse_instruction → 描画の配線が通っている。"""
    result = cli_runner(*X_ARGS, "--format", "json")
    payload = json.loads(result.stdout)

    assert payload["instruction"]["output"]["format"] == "json"


def test_cli_003_05_json_has_no_markdown_headings(cli_runner):
    """CLI-003-5: `--format json` の stdout に Markdown の見出し行が混入しない。"""
    result = cli_runner(*X_ARGS, "--format", "json")

    headings = [line for line in result.stdout_lines() if line.startswith(("# ", "## "))]
    assert headings == []


# --- CLI-004: レポートの内容契約 ------------------------------------------


def test_cli_004_01_x_report_has_selected_list(cli_runner):
    """CLI-004-1: X の成功時に選定ツイートリストの見出しを含む。"""
    result = cli_runner(*X_ARGS)

    assert "## 選定ツイートリスト（上位 N 件）" in result.stdout


def test_cli_004_02_youtube_report_has_selected_list(cli_runner):
    """CLI-004-2: YouTube の成功時に選定動画リストの見出しを含む。"""
    result = cli_runner(*YT_ARGS, scenario="youtube_success")

    assert "## 選定動画リスト（関連度順上位 N 件）" in result.stdout


@pytest.mark.parametrize(
    ("args", "scenario"),
    [
        pytest.param(X_ARGS, "x_success", id="x"),
        pytest.param(YT_ARGS, "youtube_success", id="youtube"),
    ],
)
def test_cli_004_03_04_report_has_summary_and_themes(cli_runner, args, scenario):
    """CLI-004-3 / CLI-004-4: 要約セクションと共通ネタ表を常に含む。"""
    result = cli_runner(*args, scenario=scenario)

    assert "## 各コンテンツのブログ向け要約" in result.stdout
    assert "## 共通ネタ（表）" in result.stdout
    assert "### 1. " in result.stdout


@pytest.mark.parametrize(
    ("args", "scenario", "platform"),
    [
        pytest.param(X_ARGS, "x_success", "x", id="x"),
        pytest.param(YT_ARGS, "youtube_success", "youtube", id="youtube"),
    ],
)
def test_cli_004_05_sources_are_listed(cli_runner, args, scenario, platform):
    """CLI-004-5: 出典の見出しを含み、`sources` の各 URL が箇条書きされる。"""
    result = cli_runner(*args, scenario=scenario)

    assert "## 出典" in result.stdout
    expected = {f"- https://example.test/{platform}/{i}" for i in range(1, 4)}
    assert expected <= set(result.stdout_lines())


@pytest.mark.parametrize(
    ("args", "scenario", "expected_criterion"),
    [
        pytest.param(
            X_ARGS,
            "x_success",
            "選定基準: 検索結果からいいね数の少ない順に上位 N 件を採用",
            id="x",
        ),
        pytest.param(
            YT_ARGS,
            "youtube_success",
            "選定基準: 検索結果の関連度順に上位 N 件を採用",
            id="youtube",
        ),
    ],
)
def test_cli_004_07_notes_record_selection_criterion(cli_runner, args, scenario, expected_criterion):
    """CLI-004-7: 備考の見出しを含み、選定基準が記録される。"""
    result = cli_runner(*args, scenario=scenario)

    assert "## 備考" in result.stdout
    assert expected_criterion in result.stdout


def test_cli_001_01_x_likes_sort_records_criterion(cli_runner):
    """CLI-004-7: `--sort likes` は備考の選定基準も「いいね数の多い順」へ切り替える。"""
    result = cli_runner(*X_ARGS, "--sort", "likes")

    assert result.exit_code == 0
    assert "選定基準: 検索結果からいいね数の多い順に上位 N 件を採用" in result.stdout

