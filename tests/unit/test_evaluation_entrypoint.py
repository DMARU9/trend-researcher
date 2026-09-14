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
import asyncio
import importlib
import importlib.util
import re
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import ModuleType

import pytest

from trend_researcher.models import ModelUsage, ResearchInstruction, ResearchReport

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


# --- (f) 実走の使用量を結果へ記録する（FR-042 / SC-024） -------------------


def _eval_module(name: str) -> ModuleType:
    """`tests/eval/<name>.py` を読み込む（`tests/` はパッケージではないため）。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    return importlib.import_module(f"tests.eval.{name}")


records = _eval_module("records")


def _usage(
    input_tokens: int | None, output_tokens: int | None, total_tokens: int | None
) -> ModelUsage:
    """1 回の呼び出し分の使用量（`state["usage"]` の要素。FR-061）。"""
    return ModelUsage(
        node_name="analyze_content",
        role="summary",
        model="openai:mimo-v2.5",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        structured=False,
    )


def _fold(recorded: object) -> dict[str, int]:
    """`_add_usage` を通した集計（結果へ書く形）。"""
    module = _load_entrypoint()
    usage: dict[str, int] = {}
    module._add_usage(usage, recorded)
    return usage


def test_the_result_usage_keys_follow_the_pipeline_records() -> None:
    """結果へ書く項目がパイプラインの記録（`ModelUsage`）と対応する（FR-042）。"""
    module = _load_entrypoint()
    sources = module.USAGE_SOURCES
    fields = set(ModelUsage.model_fields)

    assert set(sources) == set(records.USAGE_KEYS)
    for key, source in sources.items():
        if source is not None:
            assert source in fields, f"{key} の元の項目 {source} が ModelUsage に無い"


def test_the_usage_of_the_run_is_no_longer_unknown() -> None:
    """`list[ModelUsage]` を畳むと、結果の使用量が「取得」として記録される（SC-024）。"""
    usage = _fold([_usage(120, 30, 150), _usage(10, 5, 15)])
    summary = records.usage_summary(usage)

    assert summary["status"] == "取得"
    assert summary["calls"] == 2
    assert summary["prompt_tokens"] == 130
    assert summary["completion_tokens"] == 35
    assert summary["total_tokens"] == 165


def test_unknown_tokens_stay_unknown_but_the_call_is_counted() -> None:
    """不明なトークン数は 0 に潰さず、呼び出し回数だけを数える（FR-061）。"""
    summary = records.usage_summary(_fold([_usage(None, None, None), _usage(5, 5, 10)]))

    assert summary["calls"] == 2
    assert summary["prompt_tokens"] == 5
    assert summary["completion_tokens"] == 5
    assert summary["total_tokens"] == 10


def test_a_run_without_usage_records_unknown() -> None:
    """使用量がまったく得られない実行は「不明」のままにする（FR-061）。"""
    for recorded in (None, {}, {"calls": 3}, "usage", 42):
        usage = _fold(recorded)

        assert usage == {}, f"{recorded!r} を集計に混ぜてはいけない"
        assert records.usage_summary(usage)["status"] == "不明"


def test_a_recorded_but_empty_usage_is_zero_calls_not_unknown() -> None:
    """並びが得られていて 0 件なら、不明ではなく 0 回として記録する（FR-061）。"""
    usage = _fold([])

    assert usage == {"calls": 0}
    assert records.usage_summary(usage)["status"] == "取得"
    assert records.usage_summary(usage)["calls"] == 0


def test_the_run_passes_the_usage_of_the_graph_to_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """実走の生成がグラフの使用量を結果へ渡す（配線ごと固定する。FR-042 / SC-024）。"""
    module = _load_entrypoint()
    dataset = module.datasets.Dataset.model_validate(
        {"name": "tr-basic", "entries": [{"id": "a", "prompt": "指示"}]}
    )
    report = ResearchReport(instruction=ResearchInstruction(raw_text="指示"))

    async def fake_ainvoke(state: dict[str, object], config: dict[str, object]) -> dict[str, object]:
        return {"report": report, "usage": [_usage(120, 30, 150)]}

    monkeypatch.setattr(module.trend_researcher, "ainvoke", fake_ainvoke)

    _, usage = asyncio.run(
        module._generate(
            dataset,
            module.Configuration(),
            overrides={},
            platform="x",
            provider=module.get_provider("x"),
        )
    )
    summary = records.usage_summary(usage)

    assert summary["status"] == "取得"
    assert summary["calls"] == 1
    assert summary["total_tokens"] == 150


# --- (g) 実行したコミットの解決（FR-043） ----------------------------------

#: `HEAD` に入れる 40 桁の識別子（先頭 7 文字が記録される）。
_LONG = "0123456789abcdef0123456789abcdef01234567"
_OTHER = "fedcba9876543210fedcba9876543210fedcba98"


def _make_repo(tmp_path: Path, *, head: str, refs: Mapping[str, str] | None = None,
               packed: str | None = None, as_file: bool = False) -> Path:
    """偽の `.git` を作り、`REPO_ROOT` に置いたことにする（`git` を起動しない。FR-065）。"""
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    git_dir = root / ".git"
    if as_file:
        # worktree: `.git` は `gitdir:` を書いたファイル。
        worktree = root / "worktrees" / "x"
        worktree.mkdir(parents=True)
        (worktree / "HEAD").write_text(head, encoding="utf-8")
        git_dir.write_text("gitdir: worktrees/x\n", encoding="utf-8")
        return root
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(head, encoding="utf-8")
    for name, value in (refs or {}).items():
        path = git_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8")
    if packed is not None:
        (git_dir / "packed-refs").write_text(packed, encoding="utf-8")
    return root


def _commit_of(monkeypatch: pytest.MonkeyPatch, root: Path) -> str:
    """`REPO_ROOT` を偽のリポジトリへ差し替えて解決する（引数も env も無し）。"""
    module = _load_entrypoint()
    monkeypatch.delenv("TR_EVAL_COMMIT", raising=False)
    monkeypatch.setattr(module, "REPO_ROOT", root)
    return module.resolve_commit(None)


def test_the_argument_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """引数の識別子が最優先（FR-043）。"""
    module = _load_entrypoint()
    monkeypatch.setenv("TR_EVAL_COMMIT", "from-env")

    assert module.resolve_commit("from-arg") == "from-arg"


def test_the_environment_is_used_without_an_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    """引数が無ければ `TR_EVAL_COMMIT`、それも無ければ `.git` を読む（FR-043）。"""
    module = _load_entrypoint()
    monkeypatch.setenv("TR_EVAL_COMMIT", "from-env")

    assert module.resolve_commit(None) == "from-env"


def test_the_commit_is_read_from_the_ref_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`.git/HEAD` の `ref:` を ref ファイルで解決し、先頭 7 文字を記録する（FR-065）。"""
    root = _make_repo(
        tmp_path, head="ref: refs/heads/main\n", refs={"refs/heads/main": _LONG}
    )

    assert _commit_of(monkeypatch, root) == _LONG[:7]


def test_the_commit_is_read_from_the_packed_refs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ref ファイルが無い（clone 直後の）状態は `packed-refs` から解決する（FR-065）。"""
    root = _make_repo(
        tmp_path,
        head="ref: refs/heads/main\n",
        packed=f"# pack-refs with: peeled fully-peeled sorted \n{_OTHER} refs/heads/main\n",
    )

    assert _commit_of(monkeypatch, root) == _OTHER[:7]


def test_a_detached_head_is_recorded_as_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`HEAD` が ref でない（detached）ときは `HEAD` の中身を使う（FR-065）。"""
    root = _make_repo(tmp_path, head=_LONG + "\n")

    assert _commit_of(monkeypatch, root) == _LONG[:7]


def test_a_worktree_gitdir_file_is_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`.git` がファイル（worktree）のときは `gitdir:` の指す先を読む（FR-065）。"""
    root = _make_repo(tmp_path, head="ref: refs/heads/main\n", refs={"refs/heads/main": _LONG}, as_file=True)
    git_dir = root / "worktrees" / "x"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "refs" / "heads" / "main").write_text(_LONG + "\n", encoding="utf-8")

    assert _commit_of(monkeypatch, root) == _LONG[:7]


def test_an_unresolvable_repository_is_recorded_as_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.git` が無い・`HEAD` が空・ref が解決できないときは `unknown`（実行は止めない。FR-043）。"""
    module = _load_entrypoint()
    root = _make_repo(tmp_path, head="ref: refs/heads/missing\n")
    monkeypatch.delenv("TR_EVAL_COMMIT", raising=False)
    monkeypatch.setattr(module, "REPO_ROOT", root)
    assert module.resolve_commit(None) == module.UNKNOWN_COMMIT

    empty = tmp_path / "no-head"
    (empty / ".git").mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", empty)
    assert module.resolve_commit(None) == module.UNKNOWN_COMMIT

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path / "without-git")
    assert module.resolve_commit(None) == module.UNKNOWN_COMMIT


def test_packed_refs_only_accepts_the_matching_line(tmp_path: Path) -> None:
    """`packed-refs` の解釈（一致する行だけを採り、無い・壊れている場合は `None`）。"""
    module = _load_entrypoint()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    assert module._packed_ref(git_dir, "refs/heads/main") is None  # ファイルが無い

    (git_dir / "packed-refs").write_text(
        f"# pack-refs with: peeled\n{_LONG} refs/heads/other\nbroken\n", encoding="utf-8"
    )
    assert module._packed_ref(git_dir, "refs/heads/main") is None  # 一致する行が無い
    assert module._packed_ref(git_dir, "refs/heads/other") == _LONG[:7]


def test_the_real_repository_head_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """このリポジトリの `HEAD` から短い識別子が取れる（作り物の `.git` だけで済ませない）。

    実測: ブランチ `specs/003-pipeline-hardening-and-evaluation` の作業ツリーで
    `resolve_commit(None)` は `git rev-parse --short=7 HEAD` と同じ 7 文字を返す。
    """
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("作業ツリーに .git が無い（書き出したソースだけの環境）")
    module = _load_entrypoint()
    monkeypatch.delenv("TR_EVAL_COMMIT", raising=False)

    assert re.fullmatch(r"[0-9a-f]{7}", module.resolve_commit(None))
