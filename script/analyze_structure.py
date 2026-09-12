#!/usr/bin/env python3
"""Analyze the structure of trend_researcher and emit diagrams + metrics.

Outputs (under <repo>/artifacts):
  - pyreverse/classes_<pkg>.{dot,png,svg} : UML class diagram (attributes + associations)
  - pyreverse/packages_<pkg>.{dot,png,svg}: module import dependency graph
  - pydeps_<pkg>.svg                        : clustered dependency graph (pydeps)
  - radon_cc.json / radon_mi.json          : complexity & maintainability metrics
  - isolated_modules.txt                   : modules nobody imports (floating code)
  - summary.md                             : human-readable digest

Requirements (install into the project venv with `uv pip install`):
  pylint  (pyreverse)
  pydeps
  radon
  graphviz (system `dot` command)

Usage:
  python script/analyze_structure.py [--src SRC_DIR] [--out OUT_DIR]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check,
                          capture_output=True, text=True)


def require_dot() -> None:
    if shutil.which("dot") is None:
        sys.exit("ERROR: graphviz 'dot' command not found. Install with: sudo apt-get install graphviz")


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        # try python -m style fallback for radon/pyreverse
        sys.exit(f"ERROR: {name} not found on PATH. Install it into the venv (uv pip install pylint pydeps radon).")


def pyreverse(src: Path, out: Path, pkg: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    # -o dot emits .dot files in cwd; run inside out/ then move up if needed.
    run(["pyreverse", "-o", "dot", "-p", pkg, str(src)], cwd=out, check=False)
    for kind in ("classes", "packages"):
        dot = out / f"{kind}_{pkg}.dot"
        if not dot.exists():
            continue
        run(["dot", "-Tpng", str(dot), "-o", str(out / f"{kind}_{pkg}.png")])
        run(["dot", "-Tsvg", str(dot), "-o", str(out / f"{kind}_{pkg}.svg")])


def pydeps(src: Path, out: Path, pkg: str) -> None:
    # NOTE: pydeps writes SVG content even when the -o path ends with .png,
    # so we always emit SVG first, then convert to PNG with rsvg-convert.
    svg = out / f"pydeps_{pkg}.svg"
    png = out / f"pydeps_{pkg}.png"
    run(["pydeps", str(src), "-o", str(svg), "--noshow", "--exclude", "stdlib,extern"], check=False)
    if not svg.exists():
        print("WARNING: pydeps did not produce output (possible import errors).", file=sys.stderr)
        return
    if shutil.which("rsvg-convert"):
        run(["rsvg-convert", "-b", "white", str(svg), "-o", str(png)])
    else:
        # fallback: copy svg as png (avoid this; the png will actually be svg)
        print("WARNING: rsvg-convert not found; PNG not generated.", file=sys.stderr)


def radon_metrics(src: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    cc_path = out / "radon_cc.json"
    mi_path = out / "radon_mi.json"
    cc = run(["radon", "cc", "-j", "-s", str(src)], check=False)
    mi = run(["radon", "mi", "-j", "-s", str(src)], check=False)
    cc_path.write_text(cc.stdout or "{}")
    mi_path.write_text(mi.stdout or "{}")
    try:
        cc_data = json.loads(cc.stdout or "{}")
    except json.JSONDecodeError:
        cc_data = {}
    # Flatten blocks to find the most complex ones.
    ranked = []
    for file, blocks in cc_data.items():
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            ranked.append({
                "file": file,
                "name": b.get("name"),
                "type": b.get("type"),
                "complexity": b.get("complexity", 0),
                "rank": b.get("rank"),
                "lineno": b.get("lineno"),
            })
    ranked.sort(key=lambda x: x["complexity"], reverse=True)
    return {"cc": cc_data, "ranked": ranked[:15]}


def find_isolated(src: Path, out: Path, pkg: str) -> list[str]:
    """Modules that are not imported by any other module in the package.

    A module is considered "used" if another module does
    `from <pkg>.<module> import ...` or `import <pkg>.<module>[.sub]`.
    The top-level package itself is excluded from the report.
    """
    modules: set[str] = set()
    for p in src.rglob("*.py"):
        if p.name == "__init__.py":
            continue
        rel = p.relative_to(src.parent)
        mod = ".".join(rel.with_suffix("").parts)
        modules.add(mod)

    def walk(name: str, acc: set[str]) -> None:
        # record the full name and all its prefixes (a.b.c -> a.b.c, a.b, a)
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            acc.add(".".join(parts[:i]))

    imported: set[str] = set()
    for p in src.rglob("*.py"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("import "):
                # import a.b.c [as x]  or  import a.b, c.d
                rest = line[len("import "):].strip()
                for part in rest.split(","):
                    name = part.strip().split()[0]  # drop "as alias"
                    walk(name, imported)
            elif line.startswith("from "):
                # from a.b.c import d
                rest = line[len("from "):].strip()
                name = rest.split()[0]
                walk(name, imported)

    isolated = sorted(m for m in modules if m not in imported and m != pkg)
    (out / "isolated_modules.txt").write_text(
        "\n".join(isolated) + ("\n" if isolated else "")
    )
    return isolated


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=REPO_ROOT / "src" / "trend_researcher")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts")
    args = ap.parse_args()

    pkg = args.src.name
    require_dot()
    require_tool("pyreverse")
    require_tool("pydeps")
    require_tool("radon")
    if shutil.which("rsvg-convert") is None:
        print("WARNING: rsvg-convert not found; pydeps PNG will be skipped.", file=sys.stderr)

    out = args.out
    pyreverse_out = out / "pyreverse"
    pyreverse_out.mkdir(parents=True, exist_ok=True)

    print("== pyreverse (class + package diagrams) ==")
    pyreverse(args.src, pyreverse_out, pkg)

    print("== pydeps (clustered dependency graph) ==")
    pydeps(args.src, out, pkg)

    print("== radon (complexity + maintainability) ==")
    metrics = radon_metrics(args.src, out)

    print("== isolated module detection ==")
    isolated = find_isolated(args.src, out, pkg)

    # Write summary
    summary = out / "summary.md"
    lines = ["# Structure Analysis Summary", ""]
    lines.append(f"- Source: `{args.src}`")
    lines.append(f"- Output: `{out}`")
    lines.append("")
    lines.append("## Most complex blocks (radon CC, top 15)")
    lines.append("")
    lines.append("| Complexity | Rank | File | Block | Line |")
    lines.append("|---|---|---|---|---|")
    for r in metrics["ranked"]:
        lines.append(f"| {r['complexity']} | {r['rank']} | `{r['file']}` | {r['name']} ({r['type']}) | {r['lineno']} |")
    lines.append("")
    lines.append("## Isolated modules (imported by nobody)")
    lines.append("")
    if isolated:
        for m in isolated:
            lines.append(f"- `{m}`")
    else:
        lines.append("_No isolated modules detected._")
    lines.append("")
    summary.write_text("\n".join(lines))
    print(f"\nWrote summary to {summary}")


if __name__ == "__main__":
    main()
