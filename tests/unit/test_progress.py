"""`ProgressEmitter` の契約（LAYOUT-006-1 / LAYOUT-006-4 / data-model 1.6 M3 / FR-012）。

表示番号と総数は **`NODE_ORDER` から導出**する。手書きの数値を持たないため、
ノードを足し引きすれば表示が自動で追随する（`TOTAL = 7` の二重定義をやめた）。
ここでは次の 4 点を固定する。

1. 番号が `NODE_ORDER.index(node_name) + 1` と一致すること
2. 分母が `len(NODE_ORDER)` と一致すること
3. 出力の書式が `[i/total] name ... phase（detail）` で**現行と 1 文字も変わらない**こと
4. 導出が非空虚であること（`NODE_ORDER` を差し替えると出力が追随すること）
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

from trend_researcher import progress
from trend_researcher.progress import NODE_ORDER, ProgressEmitter, make_emitter


def test_total_is_not_duplicated_as_a_class_constant():
    """総数の定義は 1 箇所（`NODE_ORDER`）だけ。独立した定数を持たない（FR-012）。"""
    assert not hasattr(ProgressEmitter, "TOTAL")


def test_emit_derives_the_index_from_node_order():
    """番号は `NODE_ORDER` の位置から決まる（呼び出し側が数値を渡さない）。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    for node_name in NODE_ORDER:
        emitter.emit(node_name, "開始")

    lines = stream.getvalue().splitlines()
    for position, node_name in enumerate(NODE_ORDER, start=1):
        assert lines[position - 1] == f"[{position}/{len(NODE_ORDER)}] {node_name} ... 開始"


def test_emit_rejects_unknown_node_name():
    """`NODE_ORDER` に無い名前は例外にする（表示だけ進んで実行とずれるのを防ぐ）。"""
    emitter = ProgressEmitter(stream=io.StringIO())

    with pytest.raises(ValueError) as exc:
        emitter.emit("unknown_node", "開始")

    assert "unknown_node" in str(exc.value)


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

    emitter.emit("parse_instruction", "開始")

    assert stream.getvalue() == "[1/7] parse_instruction ... 開始\n"


def test_emit_writes_done_line_with_detail():
    """完了の出力形式は `[n/total] <node> ... 完了（<detail>）`。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    emitter.emit("plan_search", "完了", detail="クエリ 3 件")

    assert stream.getvalue() == "[2/7] plan_search ... 完了（クエリ 3 件）\n"


def test_emit_uses_custom_total():
    """`total` を指定すると分母がその値になる（`make_emitter` 以外の経路）。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(total=3, stream=stream)

    emitter.emit("search", "開始")

    assert stream.getvalue() == "[3/3] search ... 開始\n"


def test_emit_defaults_to_stderr(capsys):
    """既定の出力先は stderr（stdout はレポート専用。CLI-002-1）。"""
    emitter = ProgressEmitter()

    emitter.emit("parse_instruction", "開始")

    captured = capsys.readouterr()
    assert captured.err == "[1/7] parse_instruction ... 開始\n"
    assert captured.out == ""


def test_get_messages_accumulates_emitted_lines():
    """`get_messages()` は出力した行を `AIMessage` として蓄積する。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    emitter.emit("parse_instruction", "開始")
    emitter.emit("parse_instruction", "完了", detail="トピック: X")

    contents = [m.content for m in emitter.get_messages()]
    assert contents == [
        "[1/7] parse_instruction ... 開始",
        "[1/7] parse_instruction ... 完了（トピック: X）",
    ]


def test_get_messages_returns_a_copy():
    """`get_messages()` の戻り値を変更しても内部状態は変わらない。"""
    emitter = ProgressEmitter(stream=io.StringIO())
    emitter.emit("parse_instruction", "開始")

    snapshot = emitter.get_messages()
    snapshot.clear()

    assert len(emitter.get_messages()) == 1


def test_every_node_reports_start_and_done():
    """全ノードが「開始」と「完了」の両方を報告する（空白状態を作らない）。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    for node in NODE_ORDER:
        emitter.emit(node, "開始")
        emitter.emit(node, "完了")

    lines = stream.getvalue().splitlines()
    assert len(lines) == len(NODE_ORDER) * 2
    for index, node in enumerate(NODE_ORDER, start=1):
        assert f"[{index}/{len(NODE_ORDER)}] {node} ... 開始" in lines
        assert f"[{index}/{len(NODE_ORDER)}] {node} ... 完了" in lines


def test_emitted_index_follows_the_current_node_order(monkeypatch: pytest.MonkeyPatch):
    """導出の**非空虚性**: `NODE_ORDER` を差し替えると番号と分母が追随する。

    手書きの番号（`TOTAL = 7` やノードごとの数値引数）に戻すとこのテストが落ちる。
    """
    monkeypatch.setattr(progress, "NODE_ORDER", ["search", "fetch", "compile_report"])
    stream = io.StringIO()
    emitter = ProgressEmitter(total=len(progress.NODE_ORDER), stream=stream)

    for node in progress.NODE_ORDER:
        emitter.emit(node, "開始")

    assert stream.getvalue().splitlines() == [
        "[1/3] search ... 開始",
        "[2/3] fetch ... 開始",
        "[3/3] compile_report ... 開始",
    ]


# --- `note()`（追加の観測の唯一の入口。FR-029 / D-3 / tasks §2）---------------


def test_note_writes_one_supplementary_line():
    """出力形式は `[補足] {text}` の 1 行（進捗の書式とは別系統）。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    emitter.note("圧縮した 2 件")

    assert stream.getvalue() == "[補足] 圧縮した 2 件\n"


def test_note_defaults_to_stderr(capsys):
    """既定の出力先は stderr（stdout はレポート専用。CLI-002-1）。"""
    emitter = ProgressEmitter()

    emitter.note("縮退した 1 件")

    captured = capsys.readouterr()
    assert captured.err == "[補足] 縮退した 1 件\n"
    assert captured.out == ""


def test_note_does_not_grow_the_messages():
    """`note()` は状態（`messages`）へ積まない（D-3。レポートと契約を汚さない）。

    ここが `emit()` と同じ蓄積経路になると、既定の入力でも `messages` の内容が
    変わり、凍結した契約（`tests/integration/test_frozen_contracts.py`）が壊れる。
    """
    emitter = ProgressEmitter(stream=io.StringIO())
    emitter.emit("parse_instruction", "開始")
    before = [message.content for message in emitter.get_messages()]

    emitter.note("失敗 1 件")

    assert [message.content for message in emitter.get_messages()] == before


def test_note_does_not_consume_a_step():
    """`note()` は進捗の番号を進めない（補足は段ではない）。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    emitter.emit("parse_instruction", "開始")
    emitter.note("補足")
    emitter.emit("plan_search", "開始")

    assert stream.getvalue().splitlines() == [
        "[1/7] parse_instruction ... 開始",
        "[補足] 補足",
        "[2/7] plan_search ... 開始",
    ]


def test_note_does_not_change_the_emit_format():
    """`emit()` の書式は `note()` を足しても 1 文字も変わらない（FR-017）。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    emitter.note("補足")
    emitter.emit("parse_instruction", "完了", detail="トピック: X")

    assert stream.getvalue().splitlines() == [
        "[補足] 補足",
        "[1/7] parse_instruction ... 完了（トピック: X）",
    ]


def test_note_keeps_emit_messages_unchanged():
    """`note()` を挟んでも `emit()` が積む内容は同じ（書式の凍結）。"""
    stream = io.StringIO()
    emitter = ProgressEmitter(stream=stream)

    emitter.note("補足")
    emitter.emit("search", "完了", detail="3 件を選定")

    assert [message.content for message in emitter.get_messages()] == [
        "[3/7] search ... 完了（3 件を選定）"
    ]


# --- 追加の観測は `note()` だけ（T093。`emit(` は増えていない） ---------------

#: 出荷コードのノード実装が置かれているディレクトリ。
NODES_DIR = Path(__file__).resolve().parents[2] / "src" / "trend_researcher" / "nodes"

#: ノードごとの `emit()` 呼び出し箇所。各ノードは「開始」「完了」の 2 箇所だけを
#: 持ち、`compile_report` は既存の「キャッシュ書き込み失敗」の報告が 1 つ加わる
#: （`test_cli_001_05_write_failure_has_single_error_line` が固定する既存の振る舞い）。
#: 新しい観測を足すときは `note()` を使う（この表が増えないことが契約）。
EMIT_CALL_SITES = {
    "analyze_content.py": 2,
    "compile_report.py": 3,
    "extract_common.py": 2,
    "fetch.py": 2,
    "parse_instruction.py": 2,
    "plan_search.py": 2,
    "search.py": 2,
}

#: ノードごとの `note()` 呼び出し箇所。US1〜US8 で足した追加の観測はここにだけ
#: 現れる（圧縮・縮退・失敗の内訳・使用量・点検の失敗）。
#: `fetch` / `search` は追加の観測を持たない（既存の `notes` は provider が作る）。
NOTE_CALL_SITES = {
    "analyze_content.py": 3,
    "compile_report.py": 2,
    "extract_common.py": 1,
    "fetch.py": 0,
    "parse_instruction.py": 1,
    "plan_search.py": 1,
    "search.py": 0,
}


def _attribute_calls(source: str, name: str) -> int:
    """`<何か>.<name>(...)` の呼び出しを数える（AST で見る）。"""
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
    )


def _node_sources() -> dict[str, str]:
    """出荷コードのノード実装（`nodes/__init__.py` を除く）を読む。"""
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(NODES_DIR.glob("*.py"))
        if path.name != "__init__.py"
    }


def test_the_scan_covers_every_node_module():
    """走査対象は `nodes/` の実装（7 ノード）。新しいノードを足したら走査も広げる。"""
    assert sorted(_node_sources()) == sorted(EMIT_CALL_SITES)


def test_every_node_keeps_only_the_start_and_done_emit_call_sites():
    """`emit()` の呼び出し箇所は増えていない（開始 / 完了の形のまま。T093）。"""
    counts = {name: _attribute_calls(src, "emit") for name, src in _node_sources().items()}

    assert counts == EMIT_CALL_SITES
    assert sum(counts.values()) == len(NODE_ORDER) * 2 + 1


def test_additional_observations_use_note_only():
    """US1〜US8 の追加の観測は `note()` にだけ現れる（T093 / D-3）。"""
    counts = {name: _attribute_calls(src, "note") for name, src in _node_sources().items()}

    assert counts == NOTE_CALL_SITES
    assert sum(counts.values()) > 0  # 走査が空振りしていない（非空虚性）


def test_nodes_do_not_write_to_stdout_or_stderr_directly():
    """ノードは自前で出力しない（観測の入口を `emit()` / `note()` の 2 つに限る）。

    直接 `print` / `sys.stdout` / `sys.stderr` を書くと、stdout はレポート専用
    という契約（CLI-002-1）と `messages` の蓄積を迂回できてしまう。
    """
    sources = _node_sources()
    direct = {
        name: sorted(word for word in ("print(", "sys.stdout", "sys.stderr") if word in src)
        for name, src in sources.items()
    }

    assert {name: words for name, words in direct.items() if words} == {}


def test_the_call_scanner_sees_what_it_counts():
    """走査の非空虚性: 呼び出しを足したら数が増える（空振りの `0` と区別する）。"""
    source = "def f(e):\n    e.emit('a', '開始')\n    e.note('補足')\n"

    assert _attribute_calls(source, "emit") == 1
    assert _attribute_calls(source, "note") == 1
    assert _attribute_calls(source + "    e.emit('a', '完了')\n", "emit") == 2
