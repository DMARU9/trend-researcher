"""CLI エントリの設定経路（T047 / SET-006）。

固定する契約:

- `main()` は実行時設定を `Configuration.load(env_prefix=provider.env_prefix)` で解決し、
  `RunnableConfig` の `configurable` へ**解決済みの値**を載せる（環境変数が実行まで届く）
- CLI の明示指定（`--max-results` / `--lang` / `--cache-dir`）は環境変数より優先される
- プラットフォーム固有の接頭辞（`XTR_*`）は provider が渡す（`TR_*` は一般名として優先）

`main()` のグラフ呼び出しだけを差し替え、`_parse_args` / `Configuration.load()` /
省略時のメッセージ出力は実物を通す。実リポジトリの `.env` は読み込ませない
（`test_config.py` と同じ隔離。`.env` の内容で結果が変わると検証として成立しない）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from trend_researcher import __main__ as cli
from trend_researcher import config as config_module

#: 設定解決に影響する環境変数（`.env` のキーに対応）。テストごとに全消しする。
_ENV_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    *(
        f"{prefix}_{name}"
        for prefix in ("TR", "XTR", "YTR")
        for name in (
            "MODEL",
            "MAX_RESULTS",
            "SEARCH_POOL_SIZE",
            "ACCOUNTS_DB",
            "TRANSCRIPT_LANG",
            "CACHE_DIR",
            "MAX_RETRIES",
        )
    ),
)


class _FakeReport:
    """`main()` が読む属性だけを持つレポートのダブル（候補 0 件の経路）。"""

    candidates: ClassVar[list[Any]] = []
    instruction = SimpleNamespace(max_results=None)


class _FakeGraph:
    """`ainvoke` に渡された `RunnableConfig` を記録するグラフのダブル。"""

    def __init__(self) -> None:
        self.config: dict[str, Any] | None = None
        self.state: dict[str, Any] | None = None

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.state = state
        self.config = config
        return {"report": _FakeReport()}


@pytest.fixture(autouse=True)
def isolated_cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` の読み込みとプロセス環境を遮断し、検証を決定的にする。"""
    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: None)
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def graph(monkeypatch: pytest.MonkeyPatch) -> _FakeGraph:
    """グラフと描画を差し替え、`configurable` を観測できるようにする。"""
    fake = _FakeGraph()
    monkeypatch.setattr(cli, "trend_researcher", fake)
    monkeypatch.setattr(cli, "render_report", lambda report, provider: "REPORT")
    return fake


def _configurable(graph: _FakeGraph) -> dict[str, Any]:
    assert graph.config is not None
    configurable = graph.config["configurable"]
    assert isinstance(configurable, dict)
    return configurable


# --- 環境変数が RunnableConfig へ届く --------------------------------------


def test_environment_variable_reaches_runnable_config(
    graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`TR_MAX_RESULTS` は `Configuration.load()` 経由でグラフへ渡る（SET-006）。"""
    monkeypatch.setenv("TR_MAX_RESULTS", "9")

    assert cli.main(["AI 動画のトレンド", "--platform", "x"]) == 0

    assert _configurable(graph)["max_results"] == 9


def test_platform_specific_variable_is_used_with_provider_prefix(
    graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`XTR_MAX_RESULTS` は provider が渡す接頭辞で解決される（一般名 `TR_*` が無いとき）。"""
    monkeypatch.setenv("XTR_MAX_RESULTS", "7")

    assert cli.main(["AI 動画のトレンド", "--platform", "x"]) == 0

    assert _configurable(graph)["max_results"] == 7


def test_explicit_cli_options_override_environment(
    graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """明示指定は環境変数より優先される（`--max-results` / `--lang` / `--cache-dir`）。"""
    monkeypatch.setenv("TR_MAX_RESULTS", "9")
    monkeypatch.setenv("TR_TRANSCRIPT_LANG", "ja")
    monkeypatch.setenv("TR_CACHE_DIR", str(tmp_path / "env-cache"))
    explicit = tmp_path / "cli-cache"

    code = cli.main(
        [
            "AI 動画のトレンド",
            "--platform",
            "x",
            "--max-results",
            "3",
            "--lang",
            "en",
            "--cache-dir",
            str(explicit),
        ]
    )

    assert code == 0
    configurable = _configurable(graph)
    assert configurable["max_results"] == 3
    assert configurable["transcript_language"] == "en"
    assert configurable["cache_dir"] == str(explicit.resolve())


def test_language_falls_back_to_environment_when_not_explicit(
    graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--lang` 未指定なら環境変数の字幕言語が使われる。"""
    monkeypatch.setenv("TR_TRANSCRIPT_LANG", "en")

    assert cli.main(["AI 動画のトレンド", "--platform", "x"]) == 0

    assert _configurable(graph)["transcript_language"] == "en"


def test_explicit_max_results_is_also_put_in_state(graph: _FakeGraph) -> None:
    """明示した `--max-results` は state にも載る（FR-011。未指定と「5 件指定」を区別）。"""
    assert cli.main(["AI 動画のトレンド", "--platform", "x", "--max-results", "3"]) == 0

    assert graph.state is not None
    assert graph.state["max_results"] == 3


def test_default_max_results_is_not_put_in_state(graph: _FakeGraph) -> None:
    """未指定のときは state に `max_results` を載せない（既定は Configuration 側で持つ）。"""
    assert cli.main(["AI 動画のトレンド", "--platform", "x"]) == 0

    assert graph.state is not None
    assert "max_results" not in graph.state


# --- 重い import の遅延（SC-013 / T099） ----------------------------------------


def test_importing_the_entry_point_defers_the_graph() -> None:
    """CLI の入口を import しただけではグラフを読み込まない（SC-013 / T099）。

    引数検証だけで終わる起動（`--since` の形式違反など）が `langgraph` / `openai`
    （実測 1.25 秒）を払わないようにする。同時に、参照した時点で読み込まれること
    （遅延が「読まれない」に化けていないこと）も確かめる。
    """
    script = (
        "import json, sys\n"
        "import trend_researcher.__main__ as cli\n"
        "before = 'trend_researcher.graph' in sys.modules\n"
        "entry = cli.trend_researcher\n"
        "after = 'trend_researcher.graph' in sys.modules\n"
        "print(json.dumps({\n"
        "    'before': before,\n"
        "    'after': after,\n"
        "    'has_ainvoke': hasattr(entry, 'ainvoke'),\n"
        "    'timeout_seconds': cli.EXECUTION_TIMEOUT.total_seconds(),\n"
        "}))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["before"] is False, "import だけでグラフを読み込んでいる"
    assert payload["after"] is True, "参照してもグラフが読み込まれない（遅延の実装漏れ）"
    assert payload["has_ainvoke"] is True
    assert payload["timeout_seconds"] > 0


def test_public_names_resolve_lazily_and_unknown_names_raise() -> None:
    """公開名は遅延で解決し、未知の名前は `AttributeError`（T099）。

    遅延化で名前が消えていないこと（`__all__` の全件が解決すること）と、`hasattr` の
    判定が通常のモジュールと同じであることを固定する。
    """
    import trend_researcher as package

    for name in package.__all__:
        assert getattr(package, name) is not None, name
    missing = "does_not_exist"  # 定数名を直接渡すと ruff B009 が禁じるため変数にする
    with pytest.raises(AttributeError):
        getattr(package, missing)
    with pytest.raises(AttributeError):
        getattr(cli, missing)
