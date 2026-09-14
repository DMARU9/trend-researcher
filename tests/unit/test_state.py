"""生データの参照範囲を走査で固定する（FR-027 / data-model §4.2・§4.3）。

`extract_common` と `compile_report` は「後続段で不要になった大量の中間データ」
（字幕・スレッド・返信・本文）を**参照しない**ノードである。参照するのは
`analyses` / `common_themes` / `candidates` の**メタ情報**（id / url / counts）だけ
で、生のテキストは `analyze_content` までで消費される。

この性質は「読まないこと」の証明なので、実行時テストでは観測できない（読んでも
結果が同じになる入力を作れてしまう）。そこでソースの AST を走査して、次の 4 点を
機械的に判定する（`test_platform_scan.py` と同じ設計。行番号ではなく AST の形で
判定するため、整形やコメントの変更では揺れない）。

1. `compile_report` は生データのフィールドを**読まない**（`context.text` /
   `context.thread_text` / `context.replies` の出現は代入の左辺に限る）
2. `compile_report` は生データのフィールドを**空にする代入を持つ**（解放そのもの。
   走査が空虚でないことを同時に確かめる）
3. 解放の代入は**空値**（`""` または空のコレクション）である（要約や切り詰めで
   置き換えると、解放ではなく変換になる）
4. `extract_common` は `contexts` にも生データのフィールドにも触れない

docstring は除外する（説明文に `contexts` と書いても検出しない）。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

NODES_ROOT = Path(__file__).resolve().parents[2] / "src" / "trend_researcher" / "nodes"

#: 生データのフィールド名（`Context` / `Candidate` の本文・スレッド・返信）。
RAW_FIELDS = frozenset({"text", "thread_text", "replies"})

#: `extract_common` が触れてはならない state のキー（生素材の入れ物）。
RAW_KEYS = frozenset({"contexts"})

#: 解放とみなす空値（左辺に代入してよい唯一の値）。
EMPTY_VALUES: tuple[object, ...] = ("",)


@dataclass(frozen=True)
class Access:
    """生データのフィールド 1 箇所の出現。"""

    module: str
    lineno: int
    attr: str
    content: str
    is_write: bool


def _parse(module: str) -> tuple[list[str], ast.Module]:
    path = NODES_ROOT / module
    source = path.read_text(encoding="utf-8")
    return source.splitlines(), ast.parse(source, filename=str(path))


def _docstring_lines(tree: ast.Module) -> set[int]:
    """docstring が占める行番号（説明文を検出から除外する）。"""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is None or not node.body:
                continue
            first = node.body[0]
            end = getattr(first, "end_lineno", None) or first.lineno
            lines.update(range(first.lineno, end + 1))
    return lines


def _write_target_ids(tree: ast.Module) -> set[int]:
    """代入の左辺に現れる属性ノードの id（`ctx.text = ""` の `.text` を書く側とみなす）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Attribute):
                    ids.add(id(sub))
    return ids


def _raw_field_accesses(module: str) -> list[Access]:
    """生データのフィールドの出現（読み取りと書き込みの別つき）。"""
    lines, tree = _parse(module)
    skip = _docstring_lines(tree)
    writes = _write_target_ids(tree)
    found: list[Access] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in RAW_FIELDS:
            continue
        if node.lineno in skip:
            continue
        found.append(
            Access(
                module=module,
                lineno=node.lineno,
                attr=node.attr,
                content=lines[node.lineno - 1].strip(),
                is_write=id(node) in writes,
            )
        )
    return sorted(found, key=lambda a: a.lineno)


def _raw_key_hits(module: str) -> list[Access]:
    """`contexts` の出現（辞書のキー文字列とローカル名の両方）。"""
    lines, tree = _parse(module)
    skip = _docstring_lines(tree)
    found: list[Access] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in RAW_KEYS:
            name = str(node.value)
        elif isinstance(node, ast.Name) and node.id in RAW_KEYS:
            name = node.id
        else:
            continue
        if node.lineno in skip:
            continue
        found.append(
            Access(
                module=module,
                lineno=node.lineno,
                attr=name,
                content=lines[node.lineno - 1].strip(),
                is_write=False,
            )
        )
    return sorted(found, key=lambda a: a.lineno)


def _assignment_values(tree: ast.Module) -> list[tuple[int, ast.expr]]:
    """代入（`Assign` / `AnnAssign`）の左辺が属性なら (行, 右辺) を返す。"""
    rows: list[tuple[int, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr in RAW_FIELDS:
                rows.append((node.lineno, value))
    return rows


def _is_empty_value(node: ast.expr) -> bool:
    """空値の代入か（`""` / `[]` / `{}` / `()` / `set()`）。"""
    if isinstance(node, ast.Constant):
        return node.value in EMPTY_VALUES
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in {"list", "set", "tuple", "dict"} and not node.args
    return False


# --- 規則 1: compile_report は生データを読まない ----------------------------


def test_compile_report_never_reads_the_raw_fields() -> None:
    """`context.text` 等の出現は代入の左辺（= 解放）に限る（data-model §4.2）。"""
    reads = [a for a in _raw_field_accesses("compile_report.py") if not a.is_write]

    assert reads == [], "\n".join(f"{a.lineno}: {a.content}" for a in reads)


# --- 規則 2・3: 解放が存在し、空値で行われる --------------------------------


def test_compile_report_releases_the_raw_fields_with_empty_values() -> None:
    """解放が実在し（走査が空虚でない）、代入は空値である（data-model §4.3）。"""
    accesses = _raw_field_accesses("compile_report.py")
    writes = [a for a in accesses if a.is_write]

    assert writes, (
        "compile_report.py に生データを空にする代入が 1 つも無い"
        "（解放が実装されていればこの走査は必ず 1 件以上を検出する）"
    )

    _lines, tree = _parse("compile_report.py")
    for lineno, value in _assignment_values(tree):
        assert _is_empty_value(value), f"{lineno}: 解放の代入が空値ではない"


# --- 規則 4: extract_common は生素材に触れない ------------------------------


def test_extract_common_does_not_touch_raw_material() -> None:
    """`extract_common` は `contexts` も生データのフィールドも参照しない（§4.2）。"""
    hits = _raw_field_accesses("extract_common.py") + _raw_key_hits("extract_common.py")

    assert hits == [], "\n".join(f"{a.lineno}: {a.content}" for a in hits)


# --- 走査そのものの健全性（空振り検出） --------------------------------------


def test_the_scan_detects_a_known_reference() -> None:
    """走査が空振りしていないこと（既知の参照を検出できる）を確かめる。

    `analyze_content.py` は生データを読む唯一のノードである。ここで検出できなければ
    規則 1・4 の「0 件」は何も意味しない。
    """
    samples = _raw_field_accesses("analyze_content.py")

    assert samples, "analyze_content.py でも生データを検出できない（走査が空振りしている）"
    assert any(a.is_write is False for a in samples)
