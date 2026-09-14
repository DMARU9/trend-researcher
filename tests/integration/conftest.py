"""`tests/integration/` 層に固有のフィクスチャ（LAYOUT-001-5）。

層固有のフィクスチャは各層の `conftest.py` に置く（憲法 原則 I の配置規約）。
`tests/conftest.py` がスイート全体の共有フィクスチャ（境界モック・非決定性の
固定）を担うのに対し、このモジュールは統合層だけが必要とする実行基盤
（CLI のサブプロセス起動など）を置く場所である。

CLI の外部契約は `main()` の戻り値ではなく**実行プロセスの観測結果**で検証する
（FR-002）。そのため起動は `subprocess.run` で行い、終了コード・stdout・stderr を
`CliResult` として返す。
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple

import pytest

#: リポジトリルート（`tests/integration/conftest.py` から 2 つ上）
REPO_ROOT = Path(__file__).resolve().parents[2]

#: 層 B の起動ハーネス（`test_` で始まらないため pytest は収集しない）
HARNESS_PATH = Path(__file__).resolve().parent / "cli_harness.py"

#: サブプロセスの既定タイムアウト（秒）。無限待ちを避ける。
DEFAULT_TIMEOUT = 120.0


class CliResult(NamedTuple):
    """CLI 実行プロセスの観測結果。`(exit_code, stdout, stderr)` として展開できる。"""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def stdout_bytes(self) -> bytes:
        return self.stdout.encode("utf-8")

    @property
    def stderr_bytes(self) -> bytes:
        return self.stderr.encode("utf-8")

    def stdout_lines(self) -> list[str]:
        return self.stdout.splitlines()

    def stderr_lines(self) -> list[str]:
        return self.stderr.splitlines()


def build_env(**overrides: str | None) -> dict[str, str]:
    """サブプロセス用の環境変数を**明示的に組み立てる**（data-model 1.2）。

    実認証情報（`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `XTR_*` / `YTR_*`）は継承しない
    （CLI-006-2）。`None` を渡した項目は削除される。
    """
    env: dict[str, str] = {
        # 実行に必要な最小限のみ継承する
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "NO_COLOR": "1",
        # 実認証情報を渡さない（空文字を明示。`.env` の override=False で上書きされない）
        "OPENAI_API_KEY": "",
        # 再試行の待機を実時間で払わない（SC-013。実測: 1 シナリオ 10.06 秒 → 1.32 秒）。
        # 待機の**回数と値**は `tests/unit/test_llm.py`（`SleepSpy`）が固定しており、
        # ここで 0 を渡しても再試行の回数・結果・出力（stdout / stderr / 終了コード）は
        # 変わらない（実測で確認）。0 を渡すことは `TR_RETRY_WAIT_SECONDS` の配線の
        # 確認にもなる。
        "TR_RETRY_WAIT_SECONDS": "0",
    }
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _run(argv: list[str], env: dict[str, str], timeout: float) -> CliResult:
    completed = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    return CliResult(completed.returncode, completed.stdout, completed.stderr)


@pytest.fixture
def cli_runner(tmp_path: Path) -> Callable[..., CliResult]:
    """層 B: 境界モックを注入したハーネス経由で CLI を起動する。

    使い方: `cli_runner("指示", "--platform", "x", scenario="x_zero")`

    `--cache-dir` は常に一時ディレクトリを指す（実リポジトリの `cache/` を汚さない。
    LAYOUT-003-4）。
    """

    def _run_cli(
        *args: str,
        scenario: str = "x_success",
        env: Mapping[str, str] | None = None,
        cache_dir: Path | None = None,
        accounts_db: Path | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> CliResult:
        cache_target = cache_dir or (tmp_path / "cache")
        script_env = build_env(
            TR_CLI_SCENARIO=scenario,
            TR_CACHE_DIR=str(cache_target),
            TR_ACCOUNTS_DB=str(accounts_db or (tmp_path / "accounts.db")),
            **(dict(env) if env else {}),
        )
        argv = [sys.executable, str(HARNESS_PATH), *args]
        if cache_dir is None and "--cache-dir" not in args:
            argv += ["--cache-dir", str(cache_target)]
        return _run(argv, script_env, timeout)

    return _run_cli


@pytest.fixture
def cli_module_runner(tmp_path: Path) -> Callable[..., CliResult]:
    """層 A: `python -m trend_researcher` を直接起動する（モック不要な引数検証用）。

    `python` ではなく `sys.executable` を使い、実行中の仮想環境を指すことを保証する
    （LAYOUT-003 の実行環境依存を避ける）。
    """

    def _run_cli(
        *args: str,
        env: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> CliResult:
        script_env = build_env(
            TR_CACHE_DIR=str(tmp_path / "cache"),
            TR_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
            **(dict(env) if env else {}),
        )
        return _run([sys.executable, "-m", "trend_researcher", *args], script_env, timeout)

    return _run_cli

