"""実走の入口（`script/evaluate.py`）の契約テスト（FR-065 / FR-066 / SC-018 / SC-035）。

`script/` は `testpaths = ["tests"]` の収集対象外なので、そのままでは未検証の
コードになる。このファイルが**入口の契約**（収集対象外であること・引数の集合・
`subprocess` を使わないこと・公開 API を参照していること・初期状態の 3 項目）を
固定する（contracts/evaluation-contract.md §6）。採点ロジックは `tests/eval/` 側の
テストが担う。

LLM は呼ばない（実走をテストの合否条件に含めない。FR-044）。読み込むだけで
`main()` は引数の検証までしか通さない。
"""

from __future__ import annotations

import ast
import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

#: 実走の入口（収集対象外の独立スクリプト。FR-065）。
ENTRYPOINT = Path(__file__).resolve().parents[2] / "script" / "evaluate.py"

#: リポジトリ直下。
REPO_ROOT = ENTRYPOINT.parents[1]

#: 入れてよい初期状態のキー（CLI と同じ最小の項目。FR-065）。
ALLOWED_STATE_KEYS = {"messages", "platform", "max_results"}

#: 期待するオプション（contracts/evaluation-contract.md §4 の呼び出し例）。
EXPECTED_OPTIONS = {
    "--dataset",
    "--platform",
    "--config",
    "--config-name",
    "--judge-model",
    "--out",
    "--overwrite",
    "--judge-only",
}


def _load_entrypoint() -> ModuleType:
    """`script/evaluate.py` をモジュールとして読み込む（`main()` は実行しない）。"""
    spec = importlib.util.spec_from_file_location("script_evaluate", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # 読み込み時に接続・書き込みの副作用が無いことを、この読み込み自体で確かめる。
    spec.loader.exec_module(module)
    return module


def _tree() -> ast.Module:
    """入口の構文木（AST で走査する。contracts §6 の項目 5）。"""
    return ast.parse(ENTRYPOINT.read_text(encoding="utf-8"))


def _imported_modules(tree: ast.Module) -> set[str]:
    """`import` / `from ... import` のモジュール名（`__import__` の文字列も拾う）。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            names.add(str(node.args[0].value))
    return names


def _state_keys(tree: ast.Module) -> Iterator[str]:
    """初期状態（`state`）に載るキー（辞書リテラルと添字代入の両方。contracts §6 の項目 5）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "state":
                # 初期状態を辞書リテラルで組み立てている場合。
                if isinstance(value, ast.Dict):
                    for key in value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            yield key.value
            elif (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "state"
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                yield target.slice.value


def _pytest_section() -> str:
    """`pyproject.toml` の pytest 設定の節。"""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return text.split("[tool.pytest.ini_options]")[1].split("\n[")[0]


# --- (a) 収集対象外（FR-066 / SC-018） ------------------------------------


def test_the_entrypoint_stays_outside_the_test_paths() -> None:
    """`testpaths` を変えず、収集される命名規約にも従わない（FR-066 / SC-018）。"""
    section = _pytest_section()

    assert 'testpaths = ["tests"]' in section
    assert "script" not in section
    assert ENTRYPOINT.parent.name == "script"
    assert not ENTRYPOINT.name.startswith("test_")
    assert ENTRYPOINT.is_file()


# --- (b) 引数の集合（FR-066） ---------------------------------------------


def test_the_option_set_matches_the_contract() -> None:
    """契約のオプションをすべて受け、繰り返し指定（構成ごとに 1 回）も受ける（FR-066）。"""
    parser = _load_entrypoint().build_parser()
    options = {option for action in parser._actions for option in action.option_strings}

    assert EXPECTED_OPTIONS <= options

    parsed = parser.parse_args(
        [
            "--dataset",
            "tr-basic",
            "--platform",
            "x",
            "--config",
            "baseline.json",
            "--config",
            "candidate.json",
            "--config-name",
            "baseline",
            "--config-name",
            "candidate",
            "--judge-model",
            "openai:other",
            "--out",
            "artifacts/eval",
            "--overwrite",
        ]
    )
    assert parsed.config == ["baseline.json", "candidate.json"]
    assert parsed.config_name == ["baseline", "candidate"]
    assert parsed.judge_model == "openai:other"
    assert parsed.overwrite is True

    assert parser.parse_args(["--judge-only", "artifact.jsonl"]).judge_only == "artifact.jsonl"


def test_a_run_without_a_configuration_is_an_argument_error() -> None:
    """構成も `--judge-only` も無い実行は、実走を始める前に引数エラーで終わる（FR-066）。"""
    module = _load_entrypoint()

    assert module.main([]) == 2
    assert module.main(["--dataset", "tr-basic", "--platform", "x"]) == 2


# --- (c) `subprocess` を使わない（FR-065 / SC-035） ------------------------


def test_the_entrypoint_does_not_use_subprocess() -> None:
    """CLI を subprocess として起動しない（FR-065 / SC-035）。"""
    imported = _imported_modules(_tree())

    assert not any(name == "subprocess" or name.startswith("subprocess.") for name in imported)

    module = _load_entrypoint()
    assert "subprocess" not in vars(module)


# --- (d) 公開 API を参照している（FR-065 / SC-035） ------------------------


def test_the_entrypoint_uses_the_public_api_in_process() -> None:
    """公開 API（`trend_researcher.ainvoke` / `render_report`）を in-process で呼ぶ（SC-035）。"""
    tree = _tree()
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert {"trend_researcher", "render_report"} <= names
    assert "ainvoke" in attributes
    assert "ainvoke" in called_attributes  # 参照ではなく呼び出しとして現れる
    assert "render_report" in called_names

    module = _load_entrypoint()
    assert callable(module.trend_researcher.ainvoke)
    assert callable(module.render_report)


# --- (e) 初期状態は 3 項目（FR-065） --------------------------------------


def test_the_initial_state_has_only_the_three_allowed_keys() -> None:
    """初期状態に入れるキーは `messages` / `platform` / `max_results` のみ（FR-065）。"""
    keys = list(_state_keys(_tree()))

    assert keys, "初期状態への代入が 1 つも見つからない（走査が空振りしている）"
    assert set(keys) <= ALLOWED_STATE_KEYS, f"複製してよい項目は 3 つだけ: {sorted(set(keys))}"
    assert "messages" in keys
    assert "platform" in keys
    assert keys.count("max_results") == 1  # 明示指定のときだけ載せる


# --- 補足: 出荷経路を汚さない（FR-065 / FR-069） ---------------------------


def test_the_existing_cli_contract_is_untouched() -> None:
    """既存 CLI の引数解釈を再実装しない。判定モデルを出荷物の設定に足さない（FR-065 / FR-069）。"""
    source = ENTRYPOINT.read_text(encoding="utf-8")
    cli = (REPO_ROOT / "src" / "trend_researcher" / "__main__.py").read_text(encoding="utf-8")
    fields = _configuration_fields()
    positional = [
        action.dest
        for action in _load_entrypoint().build_parser()._actions
        if not action.option_strings and action.dest != "help"
    ]

    assert "trend_researcher.__main__" not in source  # CLI の引数解釈を持ち込まない
    assert "instruction" not in positional  # CLI の位置引数を複製していない
    assert "TR_EVAL_MODEL" not in cli  # 判定モデルは実走の入口に属する値（FR-069）
    assert "judge_model" not in fields
    assert "eval_model" not in fields


def _configuration_fields() -> set[str]:
    """出荷する設定クラス（`Configuration`）の項目名。"""
    module = _load_entrypoint()

    return set(module.Configuration.model_fields)


def test_the_judge_model_is_resolved_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    """判定モデルは `TR_EVAL_MODEL` → 既定の順で解決し、引数が最優先（FR-069）。"""
    module = _load_entrypoint()
    monkeypatch.delenv("TR_EVAL_MODEL", raising=False)
    assert module.resolve_judge_model(None) == module.DEFAULT_JUDGE_MODEL

    monkeypatch.setenv("TR_EVAL_MODEL", "openai:from-env")
    assert module.resolve_judge_model(None) == "openai:from-env"
    assert module.resolve_judge_model("openai:from-arg") == "openai:from-arg"
