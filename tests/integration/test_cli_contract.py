"""CLI の外部契約テスト（`contracts/cli-contract.md`）。

契約は `main()` の戻り値ではなく**実行プロセスの観測結果**で検証する（FR-002）。
このモジュールは層 A（`python -m trend_researcher <args>` を直接起動。モック不要）を
担う。境界モックを注入する層 B（成功経路・実行時エラー）は同じファイルに追記する。

層 A が検証するのは「引数検証が外部接続より前に完走すること」である。そのため
ネットワークにも認証情報にも触れない（CLI-006-1 / CLI-006-2 / CLI-006-3）。
"""

from __future__ import annotations

import json
import re

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


# --- CLI-001-2 / CLI-001-3: 0 件・件数不足でも成功 ------------------------


@pytest.mark.parametrize(
    ("args", "scenario", "subject"),
    [
        pytest.param(X_ARGS, "x_zero", "ツイート", id="x"),
        pytest.param(YT_ARGS, "youtube_zero", "動画", id="youtube"),
    ],
)
def test_cli_001_02_zero_candidates_exit_zero(cli_runner, args, scenario, subject):
    """CLI-001-2: 検索結果が 0 件でも終了コード 0（該当なしを stderr へ通知）。"""
    result = cli_runner(*args, scenario=scenario)

    assert result.exit_code == 0
    assert (
        f"該当なし: 指定された指示に一致する{subject}が見つかりませんでした。" in result.stderr
    )
    assert "該当なし" not in result.stdout
    # 0 件でもレポートは描画される（空のレポート）
    assert result.stdout.startswith("# リサーチレポート: ")


def test_cli_001_03_fewer_results_exit_zero(cli_runner):
    """CLI-001-3: 要求件数より取得件数が少なくても終了コード 0。"""
    result = cli_runner(*X_ARGS, scenario="x_fewer")

    assert result.exit_code == 0
    assert "[情報] 要求件数 3 件に対し、実際に見つかったのは 1 件です。" in result.stderr
    assert result.stdout.startswith("# リサーチレポート: ")


def test_cli_004_06_no_common_themes(cli_runner):
    """CLI-004-6: 共通テーマが 0 件なら `（特筆すべき共通点なし）` を出力する。"""
    result = cli_runner(*X_ARGS, scenario="no_themes")

    assert result.exit_code == 0
    assert "（特筆すべき共通点なし）" in result.stdout
    # 共通ネタ表のヘッダは出さない（0 件を表で表現しない）
    assert "| テーマ | 説明 |" not in result.stdout


# --- CLI-001-4 / CLI-002-6 / CLI-002-7: 出力先へ書き出す -----------------


def test_cli_001_04_02_06_02_07_output_writes_file(cli_runner, tmp_path):
    """CLI-001-4 / CLI-002-6 / CLI-002-7: `--output` はファイルへ書き、stdout は空。"""
    target = tmp_path / "report.md"

    result = cli_runner(*X_ARGS, "--output", str(target))

    assert result.exit_code == 0
    assert result.stdout == ""  # CLI-002-6: 0 バイト
    assert result.stdout_bytes == b""
    assert f"[完了] レポートを {target} に書き出しました。" in result.stderr
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("# リサーチレポート: ")


def test_cli_001_04_output_json_file(cli_runner, tmp_path):
    """CLI-001-4 / CLI-002-7: `--format json` でも出力ファイルに JSON を書き出す。"""
    target = tmp_path / "report.json"

    result = cli_runner(*X_ARGS, "--format", "json", "--output", str(target))

    assert result.exit_code == 0
    assert result.stdout == ""
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["instruction"]["output"]["format"] == "json"


def test_cli_002_07_output_matches_stdout_rendering(cli_runner, tmp_path):
    """CLI-002-7: 同じ入力なら `--output` の内容は stdout の描画と一致する。

    stdout は `print()` 経由のため末尾に改行が 1 つ付く。ファイルは `write_text()`
    なので付かない。差はこの 1 文字のみであることを固定する。
    """
    stdout_result = cli_runner(*X_ARGS)
    target = tmp_path / "report.md"
    file_result = cli_runner(*X_ARGS, "--output", str(target))

    assert file_result.exit_code == 0
    assert target.read_text(encoding="utf-8") == stdout_result.stdout.removesuffix("\n")
    assert stdout_result.stdout.endswith("\n")


# --- CLI-001-7 / CLI-001-8 / CLI-001-9: 実行時エラー ----------------------


def test_cli_001_07_runtime_exception_exits_one(cli_runner):
    """CLI-001-7: 実行時に例外が発生したら終了コード 1（Traceback は出さない）。"""
    result = cli_runner(*X_ARGS, scenario="raise_search")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "[エラー] リサーチ実行中に問題が発生しました: X API が失敗しました" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_001_08_timeout_exits_one(cli_runner):
    """CLI-001-8: 実行が時間上限に達したら終了コード 1（警告を stderr へ）。"""
    result = cli_runner(*X_ARGS, scenario="timeout")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert re.search(
        r"\[警告\] リサーチが時間上限（\d+分）に達しました。途中結果を返します。", result.stderr
    )


def test_cli_001_09_missing_report_exits_one(cli_runner):
    """CLI-001-9: レポートが生成されなかったら終了コード 1。"""
    result = cli_runner(*X_ARGS, scenario="no_report")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "[エラー] レポートが生成されませんでした。" in result.stderr


@pytest.mark.parametrize(
    ("scenario", "marker"),
    [
        pytest.param("raise_search", "[エラー]", id="error"),
        pytest.param("timeout", "[警告]", id="warning"),
        pytest.param("x_fewer", "[情報]", id="info"),
        pytest.param("x_success", "[1/7]", id="progress"),
    ],
)
def test_cli_002_05_002_03_stderr_only_for_diagnostics(cli_runner, scenario, marker):
    """CLI-002-5 / CLI-002-3: ログ・情報・警告・エラー・進捗は stderr のみに出る。"""
    result = cli_runner(*X_ARGS, scenario=scenario)

    assert marker in result.stderr
    assert marker not in result.stdout


def test_cli_001_07_partial_progress_still_keeps_stdout_clean(cli_runner):
    """CLI-002-1 / CLI-002-3: 途中で失敗しても stdout には何も書かない。"""
    result = cli_runner(*X_ARGS, scenario="raise_search")

    # 失敗前に 2 ノード分の進捗は出ている（握り潰していない）
    assert "[2/7] plan_search ... 完了" in result.stderr
    assert "[3/7] search ... 開始" in result.stderr
    assert result.stdout_bytes == b""


# --- CLI-001-5: 出力先への書き込み失敗（T017 で修正する欠陥） -------------


@pytest.mark.parametrize(
    ("kind", "filename"),
    [
        pytest.param("missing-parent", "no_such_dir/report.md", id="missing-parent"),
        pytest.param("directory", "existing_dir", id="existing-directory"),
    ],
)
def test_cli_001_05_output_write_failure(cli_runner, tmp_path, kind, filename):
    """CLI-001-5 / CLI-002-3: 出力先に書き込めないときは 1 と `[エラー]` 形式の報告。

    T017 の修正前は `Path.write_text` が `try` の外にあり、生の `Traceback` が
    stderr に出るため、このテストは失敗する（research.md R-9 の欠陥）。
    親ディレクトリが無い場合（`FileNotFoundError`）と出力先が既存ディレクトリの場合
    （`IsADirectoryError`）で**非対称を作らない**ことも固定する。
    """
    target = tmp_path / filename
    if kind == "directory":
        target.mkdir()

    result = cli_runner(*X_ARGS, "--output", str(target))

    assert result.exit_code == 1
    assert result.stdout_bytes == b""
    assert f"[エラー] レポートを {target} に書き出せませんでした:" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_001_05_write_failure_has_single_error_line(cli_runner, tmp_path):
    """CLI-001-5: 書き込み失敗の報告は `[エラー]` で始まる 1 行に収まる。"""
    target = tmp_path / "no_such_dir" / "report.md"

    result = cli_runner(*X_ARGS, "--output", str(target))

    error_lines = [line for line in result.stderr_lines() if line.startswith("[エラー] レポートを")]
    assert len(error_lines) == 1


# --- US3 / FR-015〜019: 上限超過の検出と段階的縮退 -------------------------
#
# 固定する契約（contracts/llm-invocation-contract.md §6）:
#   - 段を使い切ったら stderr に理由（試した段数・縮小前後の長さ）を出して **exit 1**
#   - 上限超過以外のエラーは縮退せず、既存どおり exit 1（誤認の禁止。FR-018）
#   - 縮小して成功したら exit 0（既定の入力の出力を変えない）

#: 縮退の検証に使う長い指示。`min_input_chars`（既定 1000）を十分に超え、3 段縮退
#: しても下限を下回らない長さにする（1 文字 = 1 トークン換算のプロンプト）。
LONG_INSTRUCTION = "AI 動画のトレンドを調査してください。" * 120

#: 縮退のシナリオで使う共通引数
DEGRADE_ARGS = (LONG_INSTRUCTION, "--platform", "x", "--max-results", "3")


def test_us3_degradation_exhausted_exits_one(cli_runner):
    """US3 シナリオ 2 / FR-015: 縮退を使い切ったら理由を stderr に出して exit 1。

    理由には**試した段数**と**縮小前後の長さ**が入る（事後に確認できる。FR-017）。
    """
    result = cli_runner(*DEGRADE_ARGS, scenario="degrade_exhausted")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "[エラー] 上限超過のため生成できませんでした" in result.stderr
    assert "ノード: parse_instruction" in result.stderr
    assert "試した段数: 3" in result.stderr
    assert re.search(r"縮小前: \d+ 文字 → 縮小後: \d+ 文字", result.stderr)
    assert "Traceback" not in result.stderr
    # 報告は `[エラー]` で始まる 1 行に収まる（既存の失敗報告と同じ形式）
    error_lines = [line for line in result.stderr_lines() if line.startswith("[エラー]")]
    assert len(error_lines) == 1


def test_us3_degradation_success_exits_zero(cli_runner):
    """US3 シナリオ 4 / FR-015: 縮小して成功したら exit 0 で完走する。

    実行した段は `note()` の 1 行として stderr に残る（FR-017 / FR-029）。
    """
    result = cli_runner(*DEGRADE_ARGS, scenario="degrade_success")

    assert result.exit_code == 0
    assert result.stdout != ""
    assert re.search(r"\[補足\] 縮退: parse_instruction / 1 段 / \d+ → \d+ 文字", result.stderr)
    assert "[エラー]" not in result.stderr
    # 進捗は stderr のみ（stdout = レポート。CLI-002-1 / CLI-002-3）
    assert "[1/7]" not in result.stdout


def test_us3_non_limit_error_is_not_degraded(cli_runner):
    """US3 シナリオ 3 / FR-018: 上限超過と判定されない 400 は縮退せず exit 1。

    除外語彙（`invalid api key`）を含む 400 を縮退へ渡すと、入力を切り詰めて同じ
    失敗を繰り返したうえ、原因が「上限超過」に化ける（誤認の禁止）。
    """
    result = cli_runner(*DEGRADE_ARGS, scenario="degrade_other_error")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "[エラー] リサーチ実行中に問題が発生しました: " in result.stderr
    assert "縮退" not in result.stderr
    assert "試した段数" not in result.stderr


def test_us3_compression_and_degradation_happen_in_the_same_run(cli_runner):
    """FR-019 / FR-026: 長文素材の圧縮と上限超過の縮退が**同じ実行**で起きる。

    既存の統合シナリオは片方ずつしか動かしていない（縮退のシナリオは
    `parse_instruction` だけで、圧縮は起きず、圧縮のシナリオは縮退しない）。
    ここでは 1 プロセスで両方を起こし、`analyze_content` が「圧縮で削った素材で
    組み立てたプロンプト」を縮小して続行できることを、実行プロセスの観測結果
    （FR-002）として固定する。

    しきい値だけをテスト側で下げる（`TR_COMPRESSION_THRESHOLD`）。値域の下限は
    1000 で、長文スレッド（既定 20,000 文字超）はそれを上回る。縮退の判断
    （`min_input_chars` 既定 1000 に対する縮小後の長さ）は既定のままにする。
    """
    result = cli_runner(
        *DEGRADE_ARGS,
        scenario="compress_and_degrade",
        env={"TR_COMPRESSION_THRESHOLD": "2000"},
    )

    assert result.exit_code == 0
    # 圧縮と縮退の両方が、同じ実行の補足行として stderr に残る（FR-029）
    assert re.search(r"\[補足\] 長文素材 1 件を圧縮（成功 1/1、平均 \d+(\.\d+)?% 削減）", result.stderr)
    assert re.search(r"\[補足\] 縮退: analyze_content / 1 段 / \d+ → \d+ 文字", result.stderr)
    assert "[エラー]" not in result.stderr
    # レポート（stdout）は変わらない。進捗・補足は stderr のみ（CLI-002-1 / CLI-002-3）
    assert result.stdout != ""
    assert "[補足]" not in result.stdout
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# US5: 起動時拒否（FR-024 / SC-023 / settings-contract §3）
# ---------------------------------------------------------------------------

#: 値域外の `max_results` で期待する 1 行（`_expected` が宣言から組み立てる文言）。
MAX_RESULTS_ZERO = "設定が不正です: max_results=0（期待: 1 以上 100 以下の整数）"
MAX_RESULTS_TOO_LARGE = "設定が不正です: max_results=101（期待: 1 以上 100 以下の整数）"


def test_out_of_range_max_results_is_rejected_before_any_node_runs(cli_module_runner):
    """層 A / CLI 引数: 値域外は接続前に拒否し **exit 2**（丸めも置換もしない）。

    層 A（`python -m trend_researcher` を直接起動）で検証するのは、拒否が環境変数
    や境界モックの助けを借りずに成立すること、すなわち**外部接続より前**に完走する
    ことの証拠になるためである（CLI-006）。
    """
    result = cli_module_runner("AI 動画のトレンド", "--platform", "x", "--max-results", "0")

    assert result.exit_code == 2
    assert MAX_RESULTS_ZERO in result.stderr
    assert "Traceback" not in result.stderr
    # 丸め（0 → 1）も既定値への置換（0 → 5）も起きていない
    assert "max_results=0" in result.stderr
    assert "max_results=5" not in result.stderr
    # ノードは 1 つも走らない（走れば進捗の 1 行目が出る）
    assert "[1/7]" not in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [("0", MAX_RESULTS_ZERO), ("101", MAX_RESULTS_TOO_LARGE)],
)
def test_out_of_range_max_results_from_the_environment_is_rejected_too(
    cli_module_runner, env_value, expected
):
    """層 A / 環境変数: env 経由の値域外も同じ経路で拒否する（settings-contract §3）。"""
    result = cli_module_runner(
        "AI 動画のトレンド", "--platform", "x", env={"TR_MAX_RESULTS": env_value}
    )

    assert result.exit_code == 2
    assert expected in result.stderr
    assert "Traceback" not in result.stderr
    assert "[1/7]" not in result.stderr


def test_out_of_range_max_results_does_not_call_the_llm(cli_runner):
    """層 B / 境界モック: 拒否は LLM の呼び出しより前（FR-024 / SC-023）。

    層 B は成功経路が exit 0 で完走するフィクスチャなので、`exit 2` と
    `stdout == ""` が同時に成立することは「ノードが 1 つも走っていない」の
    直接の証拠になる（1 つでも走れば進捗が stderr に出て、成功シナリオなら
    レポートが stdout に出る）。
    """
    result = cli_runner(
        "AI 動画のトレンドを3件教えて", "--platform", "x", "--max-results", "0", scenario="x_success"
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert MAX_RESULTS_ZERO in result.stderr
    assert "[1/7]" not in result.stderr
    assert "[補足]" not in result.stderr


def test_a_valid_max_results_still_runs(cli_runner):
    """境界の内側（1 と 100）は拒否しない（過剰な拒否をしない）。"""
    for value in ("1", "100"):
        result = cli_runner(
            "AI 動画のトレンドを3件教えて",
            "--platform",
            "x",
            "--max-results",
            value,
            scenario="x_success",
        )
        assert result.exit_code == 0, result.stderr


# --- US8: 使用量の集約が実行プロセスの観測結果に現れる（FR-061 / FR-062） ------


def test_us8_usage_json_records_the_run(cli_runner, tmp_path):
    """実プロセスの実行で `cache/usage.json` に集計が残る（SC-022）。

    ハーネスの LLM ダブルは `usage_metadata` を返さない（実 API が使用量を
    返さない場合と同じ経路）。それでも**実行は成功し**、不明として集計される
    （FR-061 の「不明でも実行を失敗させない」）。
    """
    result = cli_runner(*X_ARGS, scenario="x_success")

    assert result.exit_code == 0
    written = json.loads((tmp_path / "cache" / "usage.json").read_text(encoding="utf-8"))
    # 呼び出し回数はノードごとの内訳の合計と一致する（reducer で連結されている）
    assert written["calls"] == sum(written["by_node"].values())
    assert written["by_node"] == {
        "parse_instruction": 1,
        "plan_search": 2,
        "analyze_content": 3,
        "extract_common": 1,
    }
    assert written["unknown_calls"] == written["calls"]
    assert written["input_tokens"] == written["output_tokens"] == 0


def test_us8_usage_is_reported_on_stderr_only(cli_runner):
    """集計は進捗（stderr）に 1 行で出て、stdout のレポートには混ざらない（D-3）。"""
    result = cli_runner(*X_ARGS, scenario="x_success")

    assert result.exit_code == 0
    assert "[補足] LLM 呼び出し合計 7 回（入力 0 / 出力 0 トークン、不明 7 回）" in result.stderr
    assert "LLM 呼び出し合計" not in result.stdout
    # 使用量はレポート本文にも備考にも入らない（D-3）
    assert "不明" not in result.stdout




