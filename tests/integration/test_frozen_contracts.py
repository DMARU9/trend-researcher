"""凍結契約の回帰テスト（SC-011 / SC-026 / FR-035）。

US1〜US8 はノードの内部（圧縮・再試行・縮退・使用量の記録）に手を入れる。その前に
**外から見た既定の挙動**を固定しておく。固定するのは次の 4 点だけ。

1. 既定の入力で stdout が不変（`golden/default_stdout.txt`）
2. 進捗行（stderr の `[i/7] ...` 行）の文言と件数が不変（`golden/default_progress.txt`）
3. 既定の入力での**テキスト呼び出し**の回数が不変（`analyze_content` = 5 / `extract_common` = 1）
4. `report.notes` の既存要素が不変（追加の観測は**末尾に足す**）

観測の仕方は契約ごとに使い分ける。

- stdout / stderr は**実行プロセス**から観測する（`cli_runner`。FR-002）
- 呼び出し回数と `report.notes` はプロセス内のグラフ実行で観測する
  （サブプロセスの内部は見えないため）

ここで数える「テキスト呼び出し」は `invoke` / `ainvoke` の回数である。US2 が足す
**構造化呼び出しの試行**は別のチャネル（`_FakeLLM.structured_prompts`）で数えるため、
この値は US2 以降も変わらない。再試行の回数そのものは `tests/unit/test_llm.py` が固定する。

**観測の限界（実測）**: CLI ハーネスの LLM フェイクは `build_model(role, env_prefix)` の
第 2 引数（位置引数）を応答文字列の既定値で受け取る形で注入しているため、実際には
`env_prefix`（`"XTR"`）が応答として使われる。既存の CLI 契約テスト（54 件）はこの
挙動を前提にしているため、このテストは**現状の挙動をそのまま**固定する
（詳細は `tasks.md` の実装メモ §6）。
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from trend_researcher import config as config_module
from trend_researcher.graph import trend_researcher
from trend_researcher.models import Candidate

#: 既定のシナリオと入力（`test_cli_contract.py` と同じ既定経路）
DEFAULT_INSTRUCTION = "AI動画のトレンドを3件"

#: 凍結した出力（`golden/` 配下）
GOLDEN_DIR = Path(__file__).with_name("golden")

#: 進捗行の判定（`ProgressEmitter.emit` が出す行だけを取り出す）
_PROGRESS_RE = re.compile(r"^\[\d+/\d+\] ")

#: 既定のレポートに載る既存の備考。追加の観測はこの**後ろ**に足す
GOLDEN_NOTES = ["選定基準: 検索結果からいいね数の少ない順に上位 N 件を採用"]

#: 既定の入力でのテキスト呼び出し回数（`plan.md` の「凍結する契約」と同じ値）
GOLDEN_TEXT_CALLS = {"analyze_content": 5, "extract_common": 1}

#: 既定の入力で解析する候補数（`max_results` の既定）
GOLDEN_CANDIDATE_COUNT = 5


def _significant_lines(text: str) -> list[str]:
    """末尾の空行だけを落とした行の並び。

    `print` が付ける末尾の改行ゆらぎは契約ではないため比較から外す。それ以外は
    1 文字の違いも許さない。
    """
    lines = text.splitlines()
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _progress_lines(stderr: str) -> list[str]:
    """stderr から**進捗行だけ**を取り出す。

    `ProgressEmitter.note()`（`[補足] ...`）は進捗行ではないため数えない。
    US8 が追加する通知で行数が変わらないようにするための区別である（FR-029）。
    """
    return [line for line in stderr.splitlines() if _PROGRESS_RE.match(line)]


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """実 `.env` と `TR_*` 環境変数を遮断する（実行環境に依存しない）。"""
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **k: None)
    for key in list(os.environ):
        if key.startswith(("TR_", "XTR_", "YTR_")):
            monkeypatch.delenv(key, raising=False)


def _candidates(count: int) -> list[Candidate]:
    """境界モックが返す決定的な候補リスト。"""
    return [
        Candidate(
            platform="x",
            id=f"x{i}",
            text=f"本文 {i}",
            url=f"https://example.test/x/{i}",
            author_handle=f"user{i}",
            like_count=100 - i,
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            relevance_rank=i,
        )
        for i in range(1, count + 1)
    ]


def _run_default_graph(x_flow: Any) -> dict[str, Any]:
    """既定の入力でグラフを 1 回実行する（`__main__._run_async` と同じ形）。"""
    search, _threads = x_flow
    search.responds(lambda query, **kwargs: _candidates(GOLDEN_CANDIDATE_COUNT))
    configurable = {
        "platform": "x",
        "output_format": "markdown",
        "max_results": GOLDEN_CANDIDATE_COUNT,
        "sort_by": "relevance",
    }
    initial_state = {
        "messages": [HumanMessage(content=DEFAULT_INSTRUCTION)],
        "platform": "x",
        "max_results": GOLDEN_CANDIDATE_COUNT,
    }
    return trend_researcher.invoke(initial_state, {"configurable": configurable})


@pytest.fixture
def x_flow(fake_x_search, fake_x_threads) -> Iterator[Any]:
    """X の検索・スレッド境界をテストダブルへ差し替える（`test_full_flow` と同型）。"""
    yield fake_x_search, fake_x_threads


@pytest.fixture
def default_responses() -> dict[str, str]:
    """ノード単位の応答（`fake_model_factory.install` に渡す）。"""
    return {
        "parse_instruction": '{"topic": "AI動画", "max_results": 5}',
        "plan_search": "クエリA\nクエリB",
        "analyze_content": "## 概要\n要約です。",
        "extract_common": "## 共通テーマ\n### テーマA\n- 説明: 説明A",
    }


# --- 1. stdout の byte 一致 ---------------------------------------------------


def test_default_stdout_matches_the_golden(cli_runner) -> None:
    """既定の入力の stdout は凍結した内容と 1 行も変わらない。"""
    result = cli_runner(DEFAULT_INSTRUCTION, "--platform", "x")

    assert result.exit_code == 0
    golden = (GOLDEN_DIR / "default_stdout.txt").read_text(encoding="utf-8")
    assert _significant_lines(result.stdout) == _significant_lines(golden)


def test_default_stdout_has_no_progress_lines(cli_runner) -> None:
    """凍結した stdout に進捗行が混じらない（stdout = レポートのみ。CLI-002-1）。"""
    result = cli_runner(DEFAULT_INSTRUCTION, "--platform", "x")

    assert _progress_lines(result.stdout) == []
    assert result.stdout.endswith("\n")


# --- 2. 進捗行の文言と件数 -----------------------------------------------------


def test_default_progress_lines_match_the_golden(cli_runner) -> None:
    """進捗行の文言と件数が変わらない（7 ノード × 開始・完了 = 14 行）。"""
    result = cli_runner(DEFAULT_INSTRUCTION, "--platform", "x")

    golden = (GOLDEN_DIR / "default_progress.txt").read_text(encoding="utf-8")
    assert _progress_lines(result.stderr) == _significant_lines(golden)


# --- 3. 既定の入力でのテキスト呼び出し回数 -------------------------------------


def test_default_text_call_counts_are_unchanged(
    fake_model_factory, x_flow, default_responses
) -> None:
    """既定の入力でのテキスト呼び出し回数が変わらない（analyze = 5 / extract = 1）。"""
    with fake_model_factory.install(default_responses):
        result = _run_default_graph(x_flow)

    assert len(result["candidates"]) == GOLDEN_CANDIDATE_COUNT
    for node, expected in GOLDEN_TEXT_CALLS.items():
        assert len(fake_model_factory.prompts_for(node)) == expected, node
    # 候補ごとに 1 件の解析が返る（取りこぼしが無いことの裏取り）
    assert len(result["report"].analyses) == GOLDEN_CANDIDATE_COUNT


# --- 4. report.notes の既存要素 ------------------------------------------------


def test_default_report_notes_are_unchanged(
    fake_model_factory, x_flow, default_responses
) -> None:
    """`report.notes` の既存要素が先頭に残る（追加の観測は末尾に足してよい）。"""
    with fake_model_factory.install(default_responses):
        result = _run_default_graph(x_flow)

    notes = result["report"].notes
    assert notes[: len(GOLDEN_NOTES)] == GOLDEN_NOTES


def test_default_run_does_not_add_notes(
    fake_model_factory, x_flow, default_responses
) -> None:
    """既定の入力（短い素材・失敗なし）では新しい観測が増えない。

    伸縮の対象はしきい値超えの素材・失敗・縮退であり、既定の入力ではどれも
    起きない（SC-003 / SC-011）。増えていたら既定の実行で追加処理が走っている。
    """
    with fake_model_factory.install(default_responses):
        result = _run_default_graph(x_flow)

    assert result["report"].notes == GOLDEN_NOTES
