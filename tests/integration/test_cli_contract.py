"""CLI の外部契約テスト（`contracts/cli-contract.md`）。

契約は `main()` の戻り値ではなく**実行プロセスの観測結果**で検証する（FR-002）。
このモジュールは層 A（`python -m trend_researcher <args>` を直接起動。モック不要）を
担う。境界モックを注入する層 B（成功経路・実行時エラー）は同じファイルに追記する。

層 A が検証するのは「引数検証が外部接続より前に完走すること」である。そのため
ネットワークにも認証情報にも触れない（CLI-006-1 / CLI-006-2 / CLI-006-3）。
"""

from __future__ import annotations

import pytest

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
