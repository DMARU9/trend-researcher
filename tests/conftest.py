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

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel

from trend_researcher.models import Candidate, Context
from trend_researcher.nodes import parse_instruction as parse_instruction_module
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
    """`invoke` / `ainvoke` の戻り値（`.content` と `usage_metadata`）。"""

    def __init__(self, content: str, usage_metadata: dict[str, int] | None = None) -> None:
        self.content = content
        #: 使用量は既定で**欠落**させる。実 API の応答に含まれない場合と同じ
        #: 状態を既定にして、観測できない経路（FR-061）を素通りさせない。
        self.usage_metadata = usage_metadata


class _FakeStructuredRunnable:
    """`with_structured_output()` の戻り値（ラン）。

    既定では**必ず** `OutputParserException` を送出する。構造化出力が黙って
    成功すると、US2 の「契約を満たさない応答」を通すテストが緑のまま何も
    検証しなくなるため、成功は `install(..., structured={...})` でのみ有効化する。
    """

    def __init__(self, llm: _FakeLLM, schema: type[BaseModel], options: dict[str, Any]) -> None:
        self._llm = llm
        self._schema = schema
        #: `method=` などの引き渡し値をテストから観測できるように残す。
        self.options = options

    def _parse(self, prompt: str) -> Any:
        self._llm.record(prompt)
        if self._llm.structured is None:
            raise OutputParserException(
                f"{self._llm.node}: 構造化出力が設定されていません"
                "（fake_model_factory.install(..., structured={...}) で指定します）"
            )
        return self._schema.model_validate(self._llm.structured)

    def invoke(self, prompt: str, *args: Any, **kwargs: Any) -> Any:
        return self._parse(prompt)

    async def ainvoke(self, prompt: str, *args: Any, **kwargs: Any) -> Any:
        return self._parse(prompt)


class _FakeLLM:
    """1 ノード分の応答だけを知る LLM フェイク。"""

    def __init__(
        self,
        node: str,
        content: str | None,
        prompts: list[str] | None = None,
        structured: Any | None = None,
    ) -> None:
        self.node = node
        self.content = content
        #: 構造化出力の応答（`None` なら必ず `OutputParserException`）。
        self.structured = structured
        # 同一ノードの複数インスタンスで共有できるよう、外部からリストを注入できる
        self.prompts: list[str] = prompts if prompts is not None else []

    def record(self, prompt: str) -> None:
        """プロンプトを記録する（通常／構造化の両経路の唯一の入口）。"""
        self.prompts.append(prompt)

    def _next(self, prompt: str) -> _FakeMessage:
        self.record(prompt)
        if self.content is None:
            raise AssertionError(
                f"fake_model_factory: ノード {self.node} の応答が指定されていません。"
                " 構造化出力だけを指定したノードで `invoke` は呼べません。"
            )
        return _FakeMessage(self.content)

    def invoke(self, prompt: str, *args: Any, **kwargs: Any) -> _FakeMessage:
        return self._next(prompt)

    async def ainvoke(self, prompt: str, *args: Any, **kwargs: Any) -> _FakeMessage:
        return self._next(prompt)

    def with_structured_output(self, schema: type[BaseModel], **kwargs: Any) -> Any:
        """構造化出力のランを返す（既定では失敗する）。"""
        return _FakeStructuredRunnable(self, schema, kwargs)


class FakeModelFactory:
    """ノード単位で `build_model` を差し替えるフェイクファクトリ（R-7）。

    プロンプト本文の部分一致によるディスパッチは**行わない**。テストは
    `install({...})` にノード名 → 応答を渡す。応答が与えられていないノードが
    呼ばれると `AssertionError` になる（暗黙の既定応答でテストを誤って緑に
    しないため）。
    """

    def __init__(self) -> None:
        self.models: dict[str, _FakeLLM] = {}
        #: ノードごとのプロンプト記録。`build_model` が複数回呼ばれるノード
        #: （例: analyze_content は候補ごとに呼ぶ）でも全件残すため、
        #: インスタンスごとのリストではなくノード単位で共有する。
        self.prompt_log: dict[str, list[str]] = {}
        #: ノードごとの `env_prefix` 記録。各ノードが provider の接頭辞を渡して
        #: いるか（コアが接頭辞を組み立てていないか）を観測できる。
        self.env_prefix_log: dict[str, list[str | None]] = {}

    def _build_model(
        self, node: str, content: str | None, structured: Any | None
    ) -> Callable[..., _FakeLLM]:
        def _build(role: str = "research", env_prefix: str | None = None) -> _FakeLLM:
            self.env_prefix_log.setdefault(node, []).append(env_prefix)
            if content is None and structured is None:
                raise AssertionError(
                    f"fake_model_factory: ノード {node} の応答が指定されていません。"
                    "プロンプト本文によるディスパッチは行いません（LAYOUT-004-4）。"
                )
            model = _FakeLLM(node, content, self.prompt_log.setdefault(node, []), structured)
            self.models[node] = model
            return model

        return _build

    @contextmanager
    def install(
        self,
        responses: dict[str, str],
        *,
        structured: dict[str, Any] | None = None,
    ) -> Iterator[FakeModelFactory]:
        """`responses` のノードだけ応答を注入した状態を作る。

        `structured` を渡すと、そのノードの `with_structured_output()` だけが
        成功する（他のノードは `OutputParserException` のまま）。
        """
        structured = structured or {}
        unknown = (set(responses) | set(structured)) - set(LLM_NODES)
        if unknown:
            raise AssertionError(f"fake_model_factory: 未知のノード名 {sorted(unknown)}")

        self.models = {}
        self.prompt_log = {}
        self.env_prefix_log = {}
        with ExitStack() as stack:
            for node in LLM_NODES:
                content = responses.get(node)
                structured_content = structured.get(node)
                stack.enter_context(
                    mock.patch(
                        f"trend_researcher.nodes.{node}.build_model",
                        side_effect=self._build_model(node, content, structured_content),
                    )
                )
            yield self

    def prompts_for(self, node: str) -> list[str]:
        """指定ノードの `build_model` に渡されたプロンプトの一覧（全インスタンス分）。"""
        instance = self.models.get(node)
        return list(instance.prompts) if instance else []

    def env_prefixes_for(self, node: str) -> list[str | None]:
        """指定ノードが `build_model` に渡した `env_prefix` の一覧（呼び出し順）。"""
        return list(self.env_prefix_log.get(node, []))


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


# --- 非決定性の固定（data-model 1.2 / FR-010 / LAYOUT-004） ----------------

#: 既定の固定時刻。テストは `frozen_now.set(...)` で任意の時点を再現できる。
DEFAULT_FROZEN_NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


class FrozenClock:
    """`parse_instruction` モジュールの `datetime` を `now` だけ固定する。

    `MagicMock(wraps=datetime)` を使うため、`fromisoformat` / `strptime` などは
    実物へ委譲される（`wraps` なしで差し替えると `fromisoformat` が壊れる。
    R-3 の注意）。
    """

    def __init__(self, mock_datetime: mock.MagicMock, now: datetime) -> None:
        self._mock = mock_datetime
        self._now = now

    @property
    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> FrozenClock:
        """固定時刻を差し替える（既に適用済みの patch に対して有効）。"""
        self._now = value
        self._mock.now.return_value = value
        return self

    def advance(self, **kwargs: float) -> FrozenClock:
        """固定時刻を相対移動する（`timedelta` のキーワードを受け付ける）。"""
        return self.set(self._now + timedelta(**kwargs))


@pytest.fixture
def frozen_now() -> Iterator[FrozenClock]:
    """`parse_instruction` の現在時刻を固定する（LAYOUT-004-1）。"""
    frozen = mock.MagicMock(wraps=datetime)
    frozen.now.return_value = DEFAULT_FROZEN_NOW
    with mock.patch.object(parse_instruction_module, "datetime", frozen):
        yield FrozenClock(frozen, DEFAULT_FROZEN_NOW)


class SleepSpy:
    """`asyncio.sleep` のスパイ。待機値を実時間で消費せず観測する。

    `0` 以下の待機は実物へ委譲する。`asyncio.sleep(0)` は待機ではなく
    「制御を譲る」意図であり、並列性（同時実行数の上限）の検証には譲渡が
    必要である。観測値（`sleeps`）には正の待機だけを記録する。
    """

    def __init__(self, real_sleep: Callable[..., Awaitable[None]] | None = None) -> None:
        self.sleeps: list[float] = []
        self._real_sleep = real_sleep

    async def __call__(self, seconds: float, *args: Any, **kwargs: Any) -> None:
        if seconds > 0:
            self.sleeps.append(seconds)
            return
        if self._real_sleep is not None:
            await self._real_sleep(seconds)

    @property
    def total(self) -> float:
        """観測した待機値の合計（実時間で消費したら失われていた時間）。"""
        return sum(self.sleeps)


@pytest.fixture(autouse=True)
def no_retry_sleep() -> Iterator[SleepSpy]:
    """リトライ待機をスパイに差し替える（FR-010 / LAYOUT-004-2）。

    `asyncio.sleep` は各モジュールが `import asyncio` の属性参照で解決するため、
    1 箇所（`asyncio` モジュールの属性）の差し替えで `tools/` のどの境界にも効く。
    モジュールを名指しした差し替えは、新しい境界（`tools/llm.py` 等）を追加した
    ときに静かに漏れる。

    `autouse=True` の理由: リトライ待機（US2）が入ると既定 1 秒 × 試行回数が
    スイート全体の実行時間（SC-013 の 60 秒）に効くため、フィクスチャを要求して
    いないテストでも実時間の待機を排除する。観測値は `spy.sleeps` / `spy.total`。
    """
    spy = SleepSpy(real_sleep=asyncio.sleep)
    with mock.patch("asyncio.sleep", new=spy):
        yield spy


@pytest.fixture
def tmp_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """一時ディレクトリを返し、`Configuration.load()` の既定 cache 先をそこへ向ける。

    実リポジトリの `cache/` を汚さない（LAYOUT-003-4）。`TR_CACHE_DIR` を
    上書きするため、`cache_dir` を明示しない `Configuration.load()` でも隔離される。
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TR_CACHE_DIR", str(cache_dir))
    return cache_dir


