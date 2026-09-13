"""コアにプラットフォーム名・環境変数接頭辞が漏れていないことの走査（SC-002 / EXT-008）。

憲法 原則 IV の「コアはプラットフォーム非依存を維持する」を機械的に判定する。
プラットフォームの差の表現先は `providers/` のフックだけであり、`providers/__init__.py`
の登録辞書（拡張点そのもの）だけが例外である。

検出規則は 4 本ある（`data-model.md` 4 節 / EXT-008）。

- (a)+(b) `test_platform_literals_are_confined_to_registry`: 登録済みプラットフォーム名の
  完全一致、および登録済み `env_prefix` の `^(XTR|YTR)_` 一致。許容リストは登録辞書の
  キーの行のみ。
- (d) `test_help_text_does_not_enumerate_platforms`: CLI のヘルプ文（argparse の `help=` と
  `ArgumentParser(description=...)`）にプラットフォーム名を列挙しない。
- (e) `test_platform_collections_are_absent`: プラットフォームの集合を扱う型を追加しない（FR-026）。
- (c) `test_nodes_do_not_read_environment`: `nodes/**` が環境変数・`.env` を読まない
  （SET-004 / SC-004。US1 の時点では `Config` が実在し検出対象が残るため US3 で追加した）。
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from trend_researcher.providers import _PROVIDERS, available_platforms, get_provider

#: 走査対象のルート。
SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "trend_researcher"

#: 走査対象のノードディレクトリ（規則 (c) 用）。
NODES_ROOT = SRC_ROOT / "nodes"

#: 検出から除外するファイル（EXT-008 の除外集合）。
#:
#: - `providers/{x,youtube,base}.py`: 差の実装そのもの
#: - `tools/{x_search,youtube_search,transcript}.py`: 固有の外部境界
#: - `prompts.py`: 分岐を持たないデータ
EXCLUDED_FILES = frozenset(
    {
        "providers/x.py",
        "providers/youtube.py",
        "providers/base.py",
        "tools/x_search.py",
        "tools/youtube_search.py",
        "tools/transcript.py",
        "prompts.py",
    }
)

#: `env_prefix` が provider に実装されるまでの暫定表。
#:
#: 規則 (b) の正規表現は本来 `get_provider(name).env_prefix` から組み立てるが、
#: US1 のテストを先に書く段階では属性がまだ無い。走査の目的は「コアに接頭辞
#: リテラルを書かない」ことなので、テスト側が接頭辞を知っていても SC-002 は損なわれない。
_ENV_PREFIX_FALLBACK = {"x": "XTR", "youtube": "YTR"}

#: `Provider` の集合を表すコンテナ（規則 (e)）。
_SEQUENCE_CONTAINERS = frozenset(
    {"list", "set", "frozenset", "tuple", "Sequence", "Iterable", "Collection"}
)


@dataclass(frozen=True)
class Hit:
    """検出した 1 行。照合は `(path, content)`（行番号に依存しない）。"""

    path: str
    lineno: int
    content: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.path, self.content)


def _format_hits(rows: Iterable[tuple[str, int, str]]) -> str:
    lines = ["プラットフォーム名／環境変数接頭辞の検出（許容リスト外）:"]
    ordered = sorted(rows)
    for path, lineno, content in ordered:
        lines.append(f"  - {path}:{lineno}: {content}")
    lines.append(f"  計 {len(ordered)} 件")
    return "\n".join(lines)


# --- 走査の共通処理 ---------------------------------------------------------


def _iter_sources() -> list[tuple[str, list[str], ast.Module]]:
    """走査対象のソースを (相対パス, 行リスト, AST) で返す（除外集合を適用）。"""
    sources: list[tuple[str, list[str], ast.Module]] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(SRC_ROOT).as_posix()
        if rel in EXCLUDED_FILES:
            continue
        source = path.read_text(encoding="utf-8")
        sources.append((rel, source.splitlines(), ast.parse(source)))
    return sources


def _docstring_lines(tree: ast.Module) -> set[int]:
    """docstring が占める行番号（除外 (4)）。"""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is None or not node.body:
                continue
            first = node.body[0]
            end = getattr(first, "end_lineno", None) or first.lineno
            lines.update(range(first.lineno, end + 1))
    return lines


def _iter_node_sources() -> list[tuple[str, list[str], ast.Module]]:
    """`nodes/**` のソースを (相対パス, 行リスト, AST) で返す（規則 (c)）。"""
    sources: list[tuple[str, list[str], ast.Module]] = []
    for path in sorted(NODES_ROOT.rglob("*.py")):
        rel = path.relative_to(SRC_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        sources.append((rel, source.splitlines(), ast.parse(source)))
    return sources


def _env_prefixes() -> list[str]:
    """登録済みプラットフォームの `env_prefix` を集める（規則 (b) の材料）。"""
    prefixes: list[str] = []
    for name in available_platforms():
        prefix = getattr(get_provider(name), "env_prefix", None)
        if not isinstance(prefix, str) or not prefix:
            prefix = _ENV_PREFIX_FALLBACK.get(name)
        if prefix:
            prefixes.append(prefix)
    return prefixes


def _env_prefix_pattern() -> re.Pattern[str]:
    prefixes = _env_prefixes()
    if not prefixes:  # pragma: no cover - 登録が空になる構成はない
        raise AssertionError("env_prefix を 1 つも解決できませんでした")
    return re.compile(rf"^({'|'.join(re.escape(p) for p in prefixes)})_")


def _registry_allowlist() -> list[Hit]:
    """`providers/__init__.py` の登録辞書のキーの行を許容リストとして返す。

    リテラルをハードコードせず、AST から辞書リテラルを見つけてソース行を取得する。
    """
    rel = "providers/__init__.py"
    path = SRC_ROOT / rel
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)

    hits: list[Hit] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value: ast.expr | None = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "_PROVIDERS" for t in targets):
            continue
        if not isinstance(value, ast.Dict):
            continue
        for key in value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                hits.append(Hit(rel, key.lineno, lines[key.lineno - 1].strip()))

    if not hits:
        raise AssertionError(
            "providers/__init__.py の登録辞書 _PROVIDERS を AST から特定できませんでした"
            "（許容リストが空文化すると走査テストが無効になる）"
        )
    return hits


# --- 検出規則 (a)+(b) ------------------------------------------------------


def _platform_literal_hits() -> list[Hit]:
    names = set(available_platforms())
    pattern = _env_prefix_pattern()
    hits: list[Hit] = []
    for rel, lines, tree in _iter_sources():
        skip = _docstring_lines(tree)
        found: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if node.lineno in skip:
                continue
            if node.value in names or pattern.match(node.value):
                found.add(node.lineno)
        hits.extend(Hit(rel, lineno, lines[lineno - 1].strip()) for lineno in sorted(found))
    return hits


def test_platform_literals_are_confined_to_registry() -> None:
    """規則 (a)+(b)。検出集合が登録辞書のキーの行のみになる（SC-002）。"""
    allowlist = _registry_allowlist()
    # 許容リストが登録数と一致すること（空文化・過剰な除外の検知）
    assert len(allowlist) == len(_PROVIDERS)

    allowed = {hit.key for hit in allowlist}
    violations = [hit for hit in _platform_literal_hits() if hit.key not in allowed]

    assert not violations, _format_hits(
        [(hit.path, hit.lineno, hit.content) for hit in violations]
    )


# --- 検出規則 (d) ----------------------------------------------------------


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _keyword_texts(node: ast.Call) -> list[ast.Constant]:
    """argparse のヘルプ文にあたる文字列定数を集める。

    `help=` は常に、`description=` は `ArgumentParser(...)` のときだけ対象にする
    （`Configuration` の `Field(description=...)` は Studio の設定説明であり CLI の
    ヘルプではないため対象外）。
    """
    texts: list[ast.Constant] = []
    is_arg_parser = _call_name(node) == "ArgumentParser"
    for kw in node.keywords:
        is_target = kw.arg == "help" or (kw.arg == "description" and is_arg_parser)
        if is_target and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            texts.append(kw.value)
    return texts


def _help_text_hits() -> list[Hit]:
    names = [name for name in available_platforms() if name]
    hits: list[Hit] = []
    for rel, lines, tree in _iter_sources():
        found: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for text in _keyword_texts(node):
                if any(name in text.value for name in names):
                    found.add(text.lineno)
        hits.extend(Hit(rel, lineno, lines[lineno - 1].strip()) for lineno in sorted(found))
    return hits


def test_help_text_does_not_enumerate_platforms() -> None:
    """規則 (d)。ヘルプ文の名前列挙が 0 件（登録の追加だけでヘルプが正しくなる）。"""
    hits = _help_text_hits()

    assert not hits, _format_hits({(h.path, h.lineno, h.content) for h in hits})


# --- 検出規則 (e) ----------------------------------------------------------


def _is_provider_ref(node: ast.expr | None) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "Provider"
    if isinstance(node, ast.Attribute):
        return node.attr == "Provider"
    return False


def _dict_value_type(node: ast.Subscript) -> ast.expr | None:
    """`dict[K, V]` の V を取り出す（`dict[str, Provider]` の検出用）。"""
    slice_node = node.slice
    if isinstance(slice_node, ast.Tuple) and len(slice_node.elts) == 2:
        return slice_node.elts[1]
    return None


def _provider_collection_hits() -> list[Hit]:
    hits: list[Hit] = []
    for rel, lines, tree in _iter_sources():
        found: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            container = node.value
            name = container.id if isinstance(container, ast.Name) else None
            is_collection = (name in _SEQUENCE_CONTAINERS and _is_provider_ref(node.slice)) or (
                name == "dict" and _is_provider_ref(_dict_value_type(node))
            )
            if is_collection:
                found.add(node.lineno)
        hits.extend(Hit(rel, lineno, lines[lineno - 1].strip()) for lineno in sorted(found))
    return hits


def test_platform_collections_are_absent() -> None:
    """規則 (e)。1 実行 = 1 プラットフォームのため集合型を追加しない（FR-026）。"""
    hits = _provider_collection_hits()

    assert not hits, _format_hits({(h.path, h.lineno, h.content) for h in hits})


# --- 検出規則 (c) ----------------------------------------------------------


def _dotted(node: ast.expr) -> str | None:
    """属性アクセスを `os.environ.get` のような点線表記にする（名前でなければ None）。"""
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
    """環境変数・`.env`・削除対象の設定ローダを指す式か（規則 (c)）。"""
    dotted = _dotted(node)
    if dotted is None:
        return False
    return (
        dotted == "load_dotenv"
        or dotted.endswith(".load_dotenv")
        or dotted == "getenv"
        or dotted.endswith(".getenv")
        or "environ" in dotted.split(".")
        or dotted == "Config.load"
    )


def _environment_read_hits() -> list[Hit]:
    hits: list[Hit] = []
    for rel, lines, tree in _iter_node_sources():
        found: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if _reads_environment(node.func):
                    found.add(node.func.lineno)
            elif isinstance(node, ast.Subscript):
                # `os.environ["TR_X"]` の形（呼び出しを伴わない読み取り）
                if _reads_environment(node.value):
                    found.add(node.value.lineno)
        hits.extend(Hit(rel, lineno, lines[lineno - 1].strip()) for lineno in sorted(found))
    return hits


def test_nodes_do_not_read_environment() -> None:
    """規則 (c)。ノードは環境変数・`.env`・`Config.load` を読まない（SET-004 / SC-004）。

    ノードが受け取るのは `RunnableConfig` 経由の `Configuration` 1 つだけであり、
    環境の解決は境界（provider / CLI）に閉じる。走査対象が空になると無効化される
    ため、対象件数も合わせて確認する。
    """
    sources = _iter_node_sources()
    assert sources, "走査対象のノードが 0 件（NODES_ROOT の設定を確認）"

    hits = _environment_read_hits()

    assert not hits, _format_hits({(h.path, h.lineno, h.content) for h in hits})
