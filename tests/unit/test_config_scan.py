"""ノードと `tools/` が環境変数を直接読まないことの走査（FR-025 / SET-004 / SC-009）。

設定の解決経路は 1 つである（`Configuration.load` / `from_runnable_config`）。
ノードと `tools/` が `os.environ` / `os.getenv` を直接読むと、その項目だけ
Studio・CLI から変更できなくなり、値域の検査（起動時の拒否）も迂回される。

例外は `tools/llm.py` の `OPENAI_API_KEY` / `OPENAI_BASE_URL` の 2 つだけである
（設定ではなく接続情報であり、既存の例外として凍結されている）。
`Configuration` のフィールドになる項目を新しく直接読むことは許さない。

検出は AST で行う（`test_platform_scan.py` の規則 (c) と同じ判定）。行番号ではなく
`(相対パス, 行の内容)` を照合するため、整形やコメントの変更では揺れない。
走査が空振りしていないことは、許容リストの 2 行が**実際に検出される**ことで
確かめる（検出できないなら「0 件」は何も意味しない）。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

#: 走査対象のルート。
SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "trend_researcher"

#: 走査対象のサブツリー（ノードと境界ツール）。
SCANNED_ROOTS = ("nodes", "tools")

#: 直接参照を許す 2 行（`tools/llm.py` の接続情報。settings-contract §1 の既存の例外）。
#: 値はソースの行そのもの（`lines[i].strip()`）で照合する。
ALLOWED_ENV_READS = frozenset(
    {
        ("tools/llm.py", 'api_key = os.getenv("OPENAI_API_KEY", "")'),
        (
            "tools/llm.py",
            'base_url = os.getenv("OPENAI_BASE_URL", "https://opencode.ai/zen/go/v1")',
        ),
    }
)

#: 環境変数・`.env` の読み取りとみなす関数名（`test_platform_scan.py` の規則と同じ）。
_ENV_READERS = frozenset({"getenv", "load_dotenv"})


@dataclass(frozen=True)
class Hit:
    """環境変数の直接参照 1 箇所。"""

    path: str
    lineno: int
    content: str


def _dotted(node: ast.expr) -> str | None:
    """属性アクセスを `os.environ.get` のような点線表記にする（名前でなければ `None`）。"""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _reads_environment(node: ast.expr) -> bool:
    """環境変数・`.env` を指す式か。"""
    dotted = _dotted(node)
    if dotted is None:
        return False
    parts = dotted.split(".")
    return "environ" in parts or parts[-1] in _ENV_READERS


def _environment_read_line(node: ast.AST) -> int | None:
    """環境の読み取りを表す式の行番号（読み取りでなければ `None`）。

    `os.getenv(...)` の呼び出しに加え、`os.environ["TR_X"]`（呼び出しを伴わない
    読み取り）も検出する。
    """
    if isinstance(node, ast.Call) and _reads_environment(node.func):
        return node.func.lineno
    if isinstance(node, ast.Subscript) and _reads_environment(node.value):
        return node.value.lineno
    return None


def _iter_sources() -> list[tuple[str, list[str], ast.Module]]:
    """走査対象のソースを (相対パス, 行リスト, AST) で返す。"""
    sources: list[tuple[str, list[str], ast.Module]] = []
    for root in SCANNED_ROOTS:
        for path in sorted((SRC_ROOT / root).rglob("*.py")):
            rel = path.relative_to(SRC_ROOT).as_posix()
            source = path.read_text(encoding="utf-8")
            sources.append((rel, source.splitlines(), ast.parse(source)))
    return sources


def _environment_reads() -> list[Hit]:
    """環境変数の直接参照を全件返す（許容リストは適用しない）。"""
    hits: list[Hit] = []
    for rel, lines, tree in _iter_sources():
        found = {lineno for node in ast.walk(tree) if (lineno := _environment_read_line(node))}
        hits.extend(Hit(rel, lineno, lines[lineno - 1].strip()) for lineno in sorted(found))
    return sorted(hits, key=lambda hit: (hit.path, hit.lineno))


def test_nodes_and_tools_do_not_read_the_environment_directly() -> None:
    """直接参照は `tools/llm.py` の 2 行だけ（FR-025 の単一の解決経路）。"""
    hits = _environment_reads()
    found = {(hit.path, hit.content) for hit in hits}

    # 走査の非空虚性: 許容リストの行が検出できなければ、以下の「0 件」は無意味である
    assert ALLOWED_ENV_READS <= found, (
        "許容リストの行を検出できない（走査が空振りしているか、行の内容が変わった）"
        f": 検出 {sorted(found)}"
    )

    unexpected = [hit for hit in hits if (hit.path, hit.content) not in ALLOWED_ENV_READS]

    assert unexpected == [], "\n".join(
        f"{hit.path}:{hit.lineno}: {hit.content}" for hit in unexpected
    )


def test_the_scan_covers_every_node_and_tool_module() -> None:
    """走査対象が空でない（ノードと `tools/` の両方を含む）。"""
    paths = {rel for rel, _lines, _tree in _iter_sources()}

    assert len(paths) >= 10, sorted(paths)
    assert "nodes/compile_report.py" in paths
    assert "tools/compression.py" in paths
    assert "tools/llm.py" in paths
