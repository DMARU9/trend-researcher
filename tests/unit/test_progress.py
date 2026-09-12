"""`ProgressEmitter` の契約（LAYOUT-006-1 / LAYOUT-006-4 / data-model 1.6 M3）。

進捗表示の総数はノード順の定義と一致していなければならない。`TOTAL` だけを
書き換えると**グラフに登録したノード数と表示がずれる**が、表示だけを見るテストは
そのずれを検出できない。ここでは `TOTAL == len(NODE_ORDER)` を直接固定する
（M3 の対。T035 の変異探針がこのテストで落ちることを確認する）。
"""

from __future__ import annotations

import io

from trend_researcher.progress import NODE_ORDER, ProgressEmitter, make_emitter


def test_total_matches_node_order_length():
    """`ProgressEmitter.TOTAL` はノード順の定義と一致する（M3 の対）。"""
    assert ProgressEmitter.TOTAL == len(NODE_ORDER)
    assert ProgressEmitter.TOTAL == 7


def test_node_order_is_the_execution_order():
    """`NODE_ORDER` はグラフの実行順（parse_instruction → compile_report）。"""
    assert NODE_ORDER == [
        "parse_instruction",
        "plan_search",
        "search",
        "fetch",
        "analyze_content",
        "extract_common",
        "compile_report",
    ]


def test_make_emitter_uses_node_order_length():
    """`make_emitter()` は `NODE_ORDER` の長さを総数に使う。"""
    assert make_emitter().total == len(NODE_ORDER)


def test_emit_writes_start_line():
    """開始の出力形式は `[n/total] <node> ... <phase>`。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    emitter.emit(1, "parse_instruction", "開始")

    assert stream.getvalue() == "[1/7] parse_instruction ... 開始\n"


def test_emit_writes_done_line_with_detail():
    """完了の出力形式は `[n/total] <node> ... 完了（<detail>）`。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    emitter.emit(2, "plan_search", "完了", detail="クエリ 3 件")

    assert stream.getvalue() == "[2/7] plan_search ... 完了（クエリ 3 件）\n"


def test_emit_uses_custom_total():
    """`total` を指定すると分母がその値になる（`make_emitter` 以外の経路）。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(total=3, stream=stream)

    emitter.emit(2, "search", "開始")

    assert stream.getvalue() == "[2/3] search ... 開始\n"


def test_emit_defaults_to_stderr(capsys):
    """既定の出力先は stderr（stdout はレポート専用。CLI-002-1）。"""
    emitter = ProgressEmitter()

    emitter.emit(1, "parse_instruction", "開始")

    captured = capsys.readouterr()
    assert captured.err == "[1/7] parse_instruction ... 開始\n"
    assert captured.out == ""


def test_get_messages_accumulates_emitted_lines():
    """`get_messages()` は出力した行を `AIMessage` として蓄積する。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    emitter.emit(1, "parse_instruction", "開始")
    emitter.emit(1, "parse_instruction", "完了", detail="トピック: X")

    contents = [m.content for m in emitter.get_messages()]
    assert contents == [
        "[1/7] parse_instruction ... 開始",
        "[1/7] parse_instruction ... 完了（トピック: X）",
    ]


def test_get_messages_returns_a_copy():
    """`get_messages()` の戻り値を変更しても内部状態は変わらない。"""
    emitter = ProgressEmitter(stream=io.StringIO())
    emitter.emit(1, "parse_instruction", "開始")

    snapshot = emitter.get_messages()
    snapshot.clear()

    assert len(emitter.get_messages()) == 1


def test_every_node_reports_start_and_done():
    """全ノードが「開始」と「完了」の両方を報告する（空白状態を作らない）。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    for index, node in enumerate(NODE_ORDER, start=1):
        emitter.emit(index, node, "開始")
        emitter.emit(index, node, "完了")

    lines = stream.getvalue().splitlines()
    assert len(lines) == len(NODE_ORDER) * 2
    for index, node in enumerate(NODE_ORDER, start=1):
        assert f"[{index}/{len(NODE_ORDER)}] {node} ... 開始" in lines
        assert f"[{index}/{len(NODE_ORDER)}] {node} ... 完了" in lines
