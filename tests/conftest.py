"""テストスイート全体で共有するフィクスチャ（LAYOUT-001-5）。

このモジュールは共有フィクスチャの置き場所である。境界モック（`tools/` /
`providers/` の差し替え）と非決定性の固定（時刻・待機・一時ディレクトリ）を
ここに集約し、各テストはフィクスチャを要求するだけで決定的に実行できる。

フィクスチャ自体が実際に境界を差し替えているかは `tests/unit/test_fixtures.py`
で検証する。静かに無効化されたフィクスチャは憲法 原則 I の「無効なテスト」と
同じ欠陥クラスである。

差し替えの対象は `tools/` / `providers/` の境界に限定する（LAYOUT-003-3）。
`nodes/` の内部関数を差し替えると、ノードのロジックが検証されなくなる。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest import mock

import pytest

from trend_researcher.models import Candidate, Context
from trend_researcher.tools.transcript import Transcript

# --- 境界モックの共通実装 -------------------------------------------------


class Boundary:
    """外部境界の差し替えを記録・制御するテストダブル。

    呼び出しを `calls` に記録し、`scenario`（data-model 1.3）に応じた応答を
    返す。`ok`（既定）以外はテストが明示的に設定する。
    """

    def __init__(self, name: str, responder: Callable[..., Any] | None = None) -> None:
        self.name = name
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.exception: BaseException | None = None
        self._responder = responder

    # --- シナリオ設定 ---
    def returns(self, value: Any) -> Boundary:
        """常に `value` を返す（`ok` / `empty` / `partial` の固定応答）。"""
        self._responder = lambda *args, **kwargs: value
        return self

    def responds(self, func: Callable[..., Any]) -> Boundary:
        """呼び出し引数から応答を組み立てる関数を設定する。"""
        self._responder = func
        return self

    def raises(self, exc: BaseException) -> Boundary:
        """呼び出し時に `exc` を送出する（`raises` シナリオ）。"""
        self.exception = exc
        return self

    # --- 呼び出し ---
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        if self.exception is not None:
            raise self.exception
        if self._responder is None:  # pragma: no cover - 既定応答を持たない境界は無い
            raise AssertionError(f"{self.name}: 応答が設定されていません")
        return self._responder(*args, **kwargs)

    @property
    def call_count(self) -> int:
        return len(self.calls)


def make_candidates(platform: str, count: int) -> list[Candidate]:
    """決定的な候補リストを生成する（境界モックの既定応答）。"""
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


# --- LLM フェイク（R-7: ノード単位の注入） --------------------------------

#: `build_model` を持つノード。プロンプト本文による分岐を避けるため、
#: 応答は「どのノードか」で指定する（LAYOUT-004-4）。
LLM_NODES = ("parse_instruction", "plan_search", "analyze_content", "extract_common")


class _FakeMessage:
    """`invoke` / `ainvoke` の戻り値（`.content` のみを持つ）。"""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """1 ノード分の応答だけを知る LLM フェイク。"""

    def __init__(self, node: str, content: str) -> None:
        self.node = node
        self.content = content
        self.prompts: list[str] = []

    def _next(self, prompt: str) -> _FakeMessage:
        self.prompts.append(prompt)
        return _FakeMessage(self.content)

    def invoke(self, prompt: str, *args: Any, **kwargs: Any) -> _FakeMessage:
        return self._next(prompt)

    async def ainvoke(self, prompt: str, *args: Any, **kwargs: Any) -> _FakeMessage:
        return self._next(prompt)


class FakeModelFactory:
    """ノード単位で `build_model` を差し替えるフェイクファクトリ（R-7）。

    プロンプト本文の部分一致によるディスパッチは**行わない**。テストは
    `install({...})` にノード名 → 応答を渡す。応答が与えられていないノードが
    呼ばれると `AssertionError` になる（暗黙の既定応答でテストを誤って緑に
    しないため）。
    """

    def __init__(self) -> None:
        self.models: dict[str, _FakeLLM] = {}

    def _build_model(self, node: str, content: str | None) -> Callable[..., _FakeLLM]:
        def _build(role: str = "research") -> _FakeLLM:
            if content is None:
                raise AssertionError(
                    f"fake_model_factory: ノード {node} の応答が指定されていません。"
                    "プロンプト本文によるディスパッチは行いません（LAYOUT-004-4）。"
                )
            model = _FakeLLM(node, content)
            self.models[node] = model
            return model

        return _build

    @contextmanager
    def install(self, responses: dict[str, str]) -> Iterator[FakeModelFactory]:
        """`responses` のノードだけ応答を注入した状態を作る。"""
        unknown = set(responses) - set(LLM_NODES)
        if unknown:
            raise AssertionError(f"fake_model_factory: 未知のノード名 {sorted(unknown)}")

        self.models = {}
        with ExitStack() as stack:
            for node in LLM_NODES:
                content = responses.get(node)
                stack.enter_context(
                    mock.patch(
                        f"trend_researcher.nodes.{node}.build_model",
                        side_effect=self._build_model(node, content),
                    )
                )
            yield self

    def prompts_for(self, node: str) -> list[str]:
        """指定ノードの `build_model` に渡されたプロンプトの一覧。"""
        model = self.models.get(node)
        return list(model.prompts) if model else []


# --- 境界モックフィクスチャ 5 種（data-model 1.2 / LAYOUT-003-3） ----------


@pytest.fixture
def fake_x_search() -> Iterator[Boundary]:
    """X の検索境界（`providers.x.search_tweets`）を差し替える。"""
    boundary = Boundary("fake_x_search", lambda query, **kw: make_candidates("x", 3))
    with mock.patch("trend_researcher.providers.x.search_tweets", new=boundary):
        yield boundary


@pytest.fixture
def fake_x_threads() -> Iterator[Boundary]:
    """X のスレッド取得境界（`providers.x.fetch_threads`）を差し替える。"""
    boundary = Boundary(
        "fake_x_threads",
        lambda candidates, **kw: [
            Context(id=c.id, text=f"{c.text} のスレッド") for c in candidates
        ],
    )
    with mock.patch("trend_researcher.providers.x.fetch_threads", new=boundary):
        yield boundary


@pytest.fixture
def fake_yt_search() -> Iterator[Boundary]:
    """YouTube の検索境界（`providers.youtube.search_videos`）を差し替える。"""
    boundary = Boundary("fake_yt_search", lambda query, **kw: make_candidates("youtube", 3))
    with mock.patch("trend_researcher.providers.youtube.search_videos", new=boundary):
        yield boundary


@pytest.fixture
def fake_yt_transcript() -> Iterator[Boundary]:
    """YouTube の字幕境界（`providers.youtube.fetch_transcript`）を差し替える。"""
    boundary = Boundary(
        "fake_yt_transcript",
        lambda video_id, language="ja": Transcript(
            video_id=video_id, language=language, text="字幕テキスト"
        ),
    )
    with mock.patch("trend_researcher.providers.youtube.fetch_transcript", new=boundary):
        yield boundary


@pytest.fixture
def fake_model_factory() -> FakeModelFactory:
    """ノード単位で LLM 応答を注入するファクトリ（R-7 / LAYOUT-004-4）。"""
    return FakeModelFactory()

