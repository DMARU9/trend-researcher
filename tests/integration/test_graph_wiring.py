"""グラフ配線の検証（FR-015 / LAYOUT-006-2 / LAYOUT-006-3）。

`tests/test_graph.py` の後継である。旧ファイルは「グラフが None でないこと」
「`ainvoke` を持つこと」しか見ておらず、ノードの並びや 0 件ルーティングの欠落を
検出できなかった。ここでは次を固定する。

1. 登録されたノードが `NODE_ORDER` と一致し、本数も一致すること
2. 直線エッジを辿った順序が `NODE_ORDER` と一致すること
3. `search` の条件分岐が `skip` → `compile_report` / `continue` → `fetch` であること
4. 0 件時は `fetch` 以降を実行しないこと（実行プロセスの進捗行で観測）
5. 成功経路の進捗が 7 ノード × 2 行であること
"""

from __future__ import annotations

import re

import pytest

from trend_researcher.graph import _route_after_search, build_graph, trend_researcher
from trend_researcher.progress import NODE_ORDER

#: グラフ内の内部ノード（`NODE_ORDER` には含まれない）
INTERNAL_NODES = {"__start__", "__end__"}

#: 進捗行の検出（`[n/7] <node> ... <phase>`）
PROGRESS_RE = re.compile(r"^\[\d+/7\] ")

X_ARGS = ("AI 動画のトレンドを3件教えて", "--platform", "x", "--max-results", "3")


def _drawable():
    return build_graph().get_graph()


def _linear_successors() -> dict[str, str]:
    """直線エッジ（条件分岐でない `data is None` の辺）の対応表。"""
    return {edge.source: edge.target for edge in _drawable().edges if edge.data is None}


def _execution_order() -> list[str]:
    """全ノードを通る実行順をエッジから導出する。

    直線エッジを優先し、条件分岐では `continue`（全ノードを通る側）を選ぶ。
    """
    linear = _linear_successors()
    conditional: dict[str, dict[str, str]] = {}
    for edge in _drawable().edges:
        if edge.data is not None:
            conditional.setdefault(edge.source, {})[edge.data] = edge.target

    order: list[str] = []
    current = "__start__"
    while True:
        if current in linear:
            nxt = linear[current]
        elif "continue" in conditional.get(current, {}):
            nxt = conditional[current]["continue"]
        else:
            break
        if nxt == "__end__":
            break
        order.append(nxt)
        current = nxt
    return order


def _progress_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if PROGRESS_RE.match(line)]


# --- 1. ノードの登録 ------------------------------------------------------


def test_build_graph_returns_compiled_graph():
    """`build_graph()` は実行可能なコンパイル済みグラフを返す。"""
    graph = build_graph()

    assert hasattr(graph, "ainvoke")
    assert trend_researcher is not None and hasattr(trend_researcher, "ainvoke")


def test_registered_nodes_match_node_order():
    """グラフに `add_node` されたノードが `NODE_ORDER` と一致する。"""
    names = {node.name for node in _drawable().nodes.values()}

    assert names - INTERNAL_NODES == set(NODE_ORDER)


def test_registered_node_count_matches_node_order():
    """ノード本数が `NODE_ORDER` の長さと一致する（表示の分母とも一致）。"""
    names = {node.name for node in _drawable().nodes.values()}

    assert len(names - INTERNAL_NODES) == len(NODE_ORDER)


# --- 2. 実行順 ------------------------------------------------------------


def test_linear_edges_follow_node_order():
    """エッジを辿った実行順（分岐は `continue` 側）が `NODE_ORDER` と一致する。"""
    assert _execution_order() == NODE_ORDER


def test_entry_point_is_parse_instruction():
    """開始点は `parse_instruction`。"""
    successors = _linear_successors()

    assert successors["__start__"] == "parse_instruction"


def test_compile_report_reaches_end():
    """`compile_report` は終端へ繋がっている。"""
    successors = _linear_successors()

    assert successors["compile_report"] == "__end__"


# --- 3. 0 件ルーティング --------------------------------------------------


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        pytest.param({"candidates": []}, "skip", id="empty"),
        pytest.param({}, "skip", id="missing-key"),
        pytest.param({"candidates": None}, "skip", id="none"),
        pytest.param({"candidates": [object()]}, "continue", id="one-candidate"),
    ],
)
def test_route_after_search(state, expected):
    """`_route_after_search` は候補の有無だけで分岐する。"""
    assert _route_after_search(state) == expected


def test_conditional_edges_map_branches():
    """`search` の条件分岐の対応表が `skip` / `continue` の 2 経路を定義する。"""
    branches = {edge.data: edge.target for edge in _drawable().edges if edge.source == "search"}

    assert branches == {"skip": "compile_report", "continue": "fetch"}


# --- 4/5. 実行プロセスでの観測 --------------------------------------------


def test_zero_candidates_skips_fetch_and_downstream(cli_runner):
    """0 件時は `skip` 経路を通り、`fetch` / `analyze_content` / `extract_common` を実行しない。"""
    result = cli_runner(*X_ARGS, scenario="x_zero")

    assert result.exit_code == 0
    assert "[3/7] search ... 完了（0 件を選定）" in result.stderr
    for skipped in ("fetch", "analyze_content", "extract_common"):
        assert not any(skipped in line for line in _progress_lines(result.stderr)), (
            f"0 件時に {skipped} が実行されています"
        )
    assert "[7/7] compile_report ... 完了" in result.stderr


def test_success_path_runs_all_nodes(cli_runner):
    """候補があるときは `continue` 経路を通り、7 ノードすべての進捗が出る。"""
    result = cli_runner(*X_ARGS, scenario="x_success")

    assert result.exit_code == 0
    lines = _progress_lines(result.stderr)
    for index, node in enumerate(NODE_ORDER, start=1):
        assert any(line.startswith(f"[{index}/7] {node} ... ") for line in lines), node


def test_success_path_progress_line_count(cli_runner):
    """成功経路の進捗行は 7 ノード ×（開始 + 完了）= 14 行。"""
    result = cli_runner(*X_ARGS, scenario="x_success")

    assert len(_progress_lines(result.stderr)) == 2 * len(NODE_ORDER)


def test_zero_candidate_progress_line_count(cli_runner):
    """0 件経路の進捗行は 4 ノード × 2 = 8 行（`fetch` 以降を省く）。"""
    result = cli_runner(*X_ARGS, scenario="x_zero")

    assert len(_progress_lines(result.stderr)) == 8
