"""層 B の CLI 起動ハーネス（LAYOUT-001-6 / plan.md Structure Decision）。

`cli_runner` フィクスチャが `sys.executable tests/integration/cli_harness.py <CLI 引数>`
として起動する。ファイル名を `test_` で始めないため pytest の収集対象にならない
（ハーネスがテストとして収集されると、素の `main()` 呼び出しが exit code の検証を
すり抜ける）。

役割は 3 つ。

1. 外部境界（X / YouTube の検索・字幕、LLM）をテストダブルへ差し替える
2. シナリオに応じて異常系（0 件・例外・時間上限・レポート欠落）を注入する
3. `trend_researcher.__main__.main()` を呼び、終了コードを `SystemExit` で返す

シナリオは環境変数 `TR_CLI_SCENARIO` で選ぶ。`main()` の**戻り値だけ**を検証する
ことは契約の検証とみなさない（FR-002）ため、契約テスト側は常に
`(exit_code, stdout, stderr)` を実プロセスから観測する。
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
import openai

if __package__ in (None, ""):  # スクリプトとして起動された場合のパス解決
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langchain_core.exceptions import OutputParserException

from trend_researcher.models import Candidate, Context
from trend_researcher.tools.transcript import Transcript

#: 既定シナリオ（X の成功経路）
DEFAULT_SCENARIO = "x_success"

# --- LLM 応答（ノード単位の固定応答。R-7 / LAYOUT-004-4） -----------------

_PARSE_OK = '```json\n{"topic": "AI 動画トレンド", "max_results": 3}\n```'

_PLAN_OK = "AI 動画 トレンド\nAI 動画 編集\nAI 動画 収益化"

_ANALYZE_OK = """### 概要

編集ワークフローの自動化が進んでいる。

### ブログの活用アイデア

| 切り口 | 読者への価値 | 拾えるキーフレーズ |
|--------|--------------|---------------------|
| 編集の自動化 | 時短の具体策が分かる | 自動カット |

### そのまま使える引用

- 編集時間が半分になった
"""

_COMMON_OK = """### 編集の自動化

複数のコンテンツで編集の自動化が共通して語られている。

説明: AI が編集作業を肩代わりする流れが共通している。

- 編集時間が半分になった
"""

_COMMON_EMPTY = "共通テーマは見つかりませんでした。"

#: ノード名 → 応答。`analyze_content` / `extract_common` はシナリオで差し替える。
LLM_RESPONSES: dict[str, str] = {
    "parse_instruction": _PARSE_OK,
    "plan_search": _PLAN_OK,
    "analyze_content": _ANALYZE_OK,
    "extract_common": _COMMON_OK,
}

#: シナリオ名 → 変更する LLM 応答（既定からの差分）
LLM_OVERRIDES: dict[str, dict[str, str]] = {
    "no_themes": {"extract_common": _COMMON_EMPTY},
}

#: LLM 応答を必要とするノード（conftest の `LLM_NODES` と同じ集合）
LLM_NODES = ("parse_instruction", "plan_search", "analyze_content", "extract_common")

#: 境界（検索・字幕）を持たないシナリオ
_NO_BOUNDARY_SCENARIOS = frozenset({"no_report"})

#: 縮退（US3 / FR-015）のシナリオ。`parse_instruction` の LLM だけを上限超過の
#: ダブルに差し替える（他ノードは既定の応答のまま）。
_DEGRADE_SCENARIOS = frozenset({"degrade_success", "degrade_exhausted", "degrade_other_error"})


# --- テストダブル ---------------------------------------------------------


class _FakeMessage:
    """`.content` と `usage_metadata` を持つ LLM 応答（conftest の同名ダブルと同型）。"""

    def __init__(self, content: str, usage_metadata: dict[str, int] | None = None) -> None:
        self.content = content
        #: 既定は `None`（実 API が使用量を返さない場合と同じ欠落経路）。
        self.usage_metadata = usage_metadata


class _FakeLLM:
    """1 ノード分の応答を返す LLM フェイク。

    `with_structured_output()` は conftest の同名ダブルと同じ契約（既定で
    `OutputParserException`）を持つ。CLI のシナリオは構造化出力に依存しないため、
    既定の失敗のままでよい。
    """

    def __init__(self, content: str | None) -> None:
        self._content = content

    def invoke(self, *args: Any, **kwargs: Any) -> _FakeMessage:
        return _FakeMessage(self._content)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> _FakeMessage:
        return _FakeMessage(self._content)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> _FakeStructuredRunnable:
        return _FakeStructuredRunnable(schema)


class _FakeStructuredRunnable:
    """`with_structured_output()` のラン（常に `OutputParserException`）。"""

    def __init__(self, schema: Any) -> None:
        self._schema = schema

    def _fail(self) -> Any:
        raise OutputParserException(
            "cli_harness: 構造化出力は差し替えていません（既定の失敗経路）"
        )

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        return self._fail()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        return self._fail()


def _limit_error() -> Exception:
    """上限超過（400 ＋ `context_length_exceeded`）を模した例外（契約 §5 の条件 1〜3）。"""
    return openai.BadRequestError(
        message="This endpoint's maximum context length is 1048576 tokens.",
        response=httpx.Response(400, request=_request()),
        body={"error": {"code": "context_length_exceeded"}},
    )


def _excluded_error() -> Exception:
    """400 でも上限超過とみなさない例外（除外語彙。契約 §5 の条件 4）。"""
    return openai.BadRequestError(
        message="Invalid API key provided.",
        response=httpx.Response(400, request=_request()),
        body={"error": {"code": "invalid_api_key"}},
    )


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.test/v1/chat/completions")


class _DegradingLLM:
    """上限超過 → 縮小 → 成功（または使い切って失敗）を作る LLM フェイク。

    `fail_times` 回までは `error`（既定は上限超過）を投げ、その後は応答を返す。
    `None` なら常に投げる（梯子を使い切る経路）。テキスト経路だけが縮退の対象
    なので、構造化経路は既定の失敗（`OutputParserException`）のままにする。
    """

    def __init__(
        self, content: str, *, fail_times: int | None, error: Exception | None = None
    ) -> None:
        self._content = content
        self._fail_times = fail_times
        self._error = error
        self.calls = 0

    def _outcome(self) -> _FakeMessage:
        self.calls += 1
        if self._fail_times is None or self.calls <= self._fail_times:
            raise self._error if self._error is not None else _limit_error()
        return _FakeMessage(self._content)

    def invoke(self, *args: Any, **kwargs: Any) -> _FakeMessage:
        return self._outcome()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> _FakeMessage:
        return self._outcome()

    def with_structured_output(self, schema: Any, **kwargs: Any) -> _FakeStructuredRunnable:
        return _FakeStructuredRunnable(schema)


def _degrade_double(scenario: str, content: str) -> _DegradingLLM:
    """縮退のシナリオに応じた `parse_instruction` 用のダブルを作る。"""
    if scenario == "degrade_exhausted":
        # 常に上限超過 → 3 段を使い切って `DegradationError`（CLI は exit 1）
        return _DegradingLLM(content, fail_times=None)
    if scenario == "degrade_other_error":
        # 400 でも除外語彙を含むものは上限超過ではない（縮退へ渡さない）
        return _DegradingLLM(content, fail_times=1, error=_excluded_error())
    return _DegradingLLM(content, fail_times=1)


class _RecordingBoundary:
    """呼び出し回数を記録する境界ダブル（ハーネス内では応答のみが要点）。"""

    def __init__(self, responder: Callable[..., Any]) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self._responder = responder

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self._responder(*args, **kwargs)


class _NoReportGraph:
    """`report` を含まない結果を返すグラフのダブル（CLI-001-9）。"""

    async def ainvoke(self, *args: Any, **kwargs: Any) -> dict:
        return {}


# --- 候補の生成 -----------------------------------------------------------


def make_candidates(platform: str, count: int) -> list[Candidate]:
    """決定的な候補リスト（conftest の同名ヘルパと同型・サブプロセス内で自己完結）。"""
    return [
        Candidate(
            platform=platform,
            id=f"{platform}{i}",
            title=f"タイトル{i}" if platform == "youtube" else "",
            text=f"本文 {i}" if platform == "x" else "",
            url=f"https://example.test/{platform}/{i}",
            author_handle=f"user{i}" if platform == "x" else "",
            author_name=f"チャンネル{i}" if platform == "youtube" else "",
            like_count=100 - i if platform == "x" else None,
            view_count=1000 * i if platform == "youtube" else None,
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            relevance_rank=i,
        )
        for i in range(1, count + 1)
    ]


def _contexts_for(candidates: list[Candidate]) -> list[Context]:
    return [Context(id=c.id, text=f"{c.text} のスレッド") for c in candidates]


# --- シナリオのパッチ -----------------------------------------------------


@contextmanager
def _patched_boundaries(scenario: str) -> Iterator[None]:
    """X / YouTube の検索・字幕境界と LLM をテストダブルへ差し替える。"""
    x_candidates = {
        "x_success": make_candidates("x", 3),
        "x_zero": [],
        "x_fewer": make_candidates("x", 1),
        "no_themes": make_candidates("x", 3),
        "write_error": make_candidates("x", 3),
    }.get(scenario, make_candidates("x", 3))
    yt_candidates = make_candidates("youtube", 0 if scenario == "youtube_zero" else 3)

    with ExitStack() as stack:
        if scenario == "raise_search":
            def _boom(*args: Any, **kwargs: Any) -> list[Candidate]:
                raise RuntimeError("X API が失敗しました")

            stack.enter_context(
                mock.patch("trend_researcher.providers.x.search_tweets", new=_RecordingBoundary(_boom))
            )
            stack.enter_context(
                mock.patch(
                    "trend_researcher.providers.x.fetch_threads",
                    new=_RecordingBoundary(lambda cands, **kw: _contexts_for(cands)),
                )
            )
        else:
            stack.enter_context(
                mock.patch(
                    "trend_researcher.providers.x.search_tweets",
                    new=_RecordingBoundary(lambda *a, **kw: list(x_candidates)),
                )
            )
            stack.enter_context(
                mock.patch(
                    "trend_researcher.providers.x.fetch_threads",
                    new=_RecordingBoundary(lambda cands, **kw: _contexts_for(cands)),
                )
            )

        stack.enter_context(
            mock.patch(
                "trend_researcher.providers.youtube.search_videos",
                new=_RecordingBoundary(lambda *a, **kw: [c.model_copy(deep=True) for c in yt_candidates]),
            )
        )
        stack.enter_context(
            mock.patch(
                "trend_researcher.providers.youtube.fetch_transcript",
                new=_RecordingBoundary(
                    lambda video_id, language="ja": Transcript(
                        video_id=video_id, language=language, text=f"{video_id} の字幕"
                    )
                ),
            )
        )

        responses = {**LLM_RESPONSES, **LLM_OVERRIDES.get(scenario, {})}
        for node in LLM_NODES:
            if node == "parse_instruction" and scenario in _DEGRADE_SCENARIOS:
                # 縮退のシナリオは `parse_instruction` だけを上限超過のダブルにする
                stack.enter_context(
                    mock.patch(
                        f"trend_researcher.nodes.{node}.build_model",
                        side_effect=lambda role="research", _content=responses[node], _s=scenario: (
                            _degrade_double(_s, _content)
                        ),
                    )
                )
                continue
            stack.enter_context(
                mock.patch(
                    f"trend_researcher.nodes.{node}.build_model",
                    side_effect=lambda role="research", _content=responses[node]: _FakeLLM(_content),
                )
            )

        yield


@contextmanager
def _patched_failures(scenario: str) -> Iterator[None]:
    """時間上限・レポート欠落を注入する（異常終了系のシナリオ専用）。"""
    with ExitStack() as stack:
        if scenario == "timeout":
            stack.enter_context(
                mock.patch("trend_researcher.__main__.EXECUTION_TIMEOUT", new=timedelta(seconds=0))
            )
        if scenario in _NO_BOUNDARY_SCENARIOS:
            stack.enter_context(
                mock.patch("trend_researcher.__main__.trend_researcher", new=_NoReportGraph())
            )
        yield


def run(scenario: str) -> int:
    """シナリオを適用して CLI の `main()` を呼び、終了コードを返す。"""
    from trend_researcher.__main__ import main as cli_main

    with _patched_failures(scenario), _patched_boundaries(scenario):
        return cli_main()


def main() -> None:
    scenario = os.environ.get("TR_CLI_SCENARIO", DEFAULT_SCENARIO)
    known = (
        set(LLM_OVERRIDES)
        | _NO_BOUNDARY_SCENARIOS
        | _DEGRADE_SCENARIOS
        | {"x_success", "x_zero", "x_fewer", "youtube_success", "youtube_zero", "raise_search", "timeout", "write_error"}
    )
    if scenario not in known:
        print(
            f"[ハーネス] 未知のシナリオ: {scenario}（既知: {sorted(known)}）",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(99)

    code = run(scenario)
    sys.stdout.flush()
    sys.stderr.flush()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
