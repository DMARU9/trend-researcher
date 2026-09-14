"""共有フィクスチャの実効性検証（FR-016 / LAYOUT-005-3）。

`tests/conftest.py` のフィクスチャが**実際に外部境界を差し替えている**ことを
確認する。境界を差し替えているつもりのフィクスチャが差し替えていない場合、
憲法 原則 I の「収集されない fixture」と同じ欠陥クラス（静かに無効なテスト）
になる。ここでは「フィクスチャ適用中の属性が本物と同一でないこと」と
「観測値がフィクスチャ経由で得られること」を固定する。
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from trend_researcher import nodes, providers
from trend_researcher.configuration import Configuration
from trend_researcher.models import Candidate, ResearchInstruction
from trend_researcher.tools import x_search, youtube_search
from trend_researcher.tools.transcript import Transcript, fetch_transcript

#: ノード名 → モジュール。`build_model` の差し替え状況を参照するために使う。
LLM_NODE_MODULES = {
    "parse_instruction": nodes.parse_instruction,
    "plan_search": nodes.plan_search,
    "analyze_content": nodes.analyze_content,
    "extract_common": nodes.extract_common,
}


def _installed_build_model(node: str):
    """ノードモジュールの `build_model` を **現在の** 状態で取り出す。"""
    return LLM_NODE_MODULES[node].build_model


# --- 境界モック（T005） ---------------------------------------------------


def test_fake_x_search_replaces_real_boundary(fake_x_search):
    """`fake_x_search` 適用中は本物の検索境界と同一でない（LAYOUT-003-3）。"""
    assert providers.x.search_tweets is not x_search.search_tweets
    assert providers.x.search_tweets is fake_x_search

    result = providers.x.search_tweets("クエリ", max_results=5, accounts_db="unused.db")
    assert fake_x_search.call_count == 1
    assert [c.id for c in result] == ["x1", "x2", "x3"]
    assert all(isinstance(c, Candidate) for c in result)


def test_fake_x_threads_replaces_real_boundary(fake_x_threads):
    """`fake_x_threads` 適用中は本物のスレッド取得境界と同一でない。"""
    assert providers.x.fetch_threads is not x_search.fetch_threads
    assert providers.x.fetch_threads is fake_x_threads

    cands = [Candidate(platform="x", id="t1", text="本文")]
    contexts = providers.x.fetch_threads(cands, accounts_db="unused.db")
    assert fake_x_threads.call_count == 1
    assert contexts[0].id == "t1"
    assert "本文" in contexts[0].text


def test_fake_yt_search_replaces_real_boundary(fake_yt_search):
    """`fake_yt_search` 適用中は本物の検索境界と同一でない。"""
    assert providers.youtube.search_videos is not youtube_search.search_videos
    assert providers.youtube.search_videos is fake_yt_search

    result = providers.youtube.search_videos("クエリ", max_results=5)
    assert fake_yt_search.call_count == 1
    assert [c.id for c in result] == ["youtube1", "youtube2", "youtube3"]


def test_fake_yt_transcript_replaces_real_boundary(fake_yt_transcript):
    """`fake_yt_transcript` 適用中は本物の字幕取得境界と同一でない。"""
    assert providers.youtube.fetch_transcript is not fetch_transcript
    assert providers.youtube.fetch_transcript is fake_yt_transcript

    transcript = providers.youtube.fetch_transcript("vid1", language="ja")
    assert fake_yt_transcript.call_count == 1
    assert isinstance(transcript, Transcript)
    assert transcript.video_id == "vid1"
    assert transcript.text == "字幕テキスト"


def test_boundary_scenarios_control_response(fake_x_search):
    """境界モックは scenario（empty / partial / raises）を切り替えられる。"""
    fake_x_search.returns([])
    assert providers.x.search_tweets("q") == []

    fake_x_search.raises(RuntimeError("リトライ枯渇"))
    with pytest.raises(RuntimeError, match="リトライ枯渇"):
        providers.x.search_tweets("q")
    assert fake_x_search.call_count == 2


def test_fake_model_factory_replaces_node_build_model(fake_model_factory):
    """`fake_model_factory` はノード単位で `build_model` を差し替える（R-7）。"""
    real = {name: _installed_build_model(name) for name in LLM_NODE_MODULES}

    with fake_model_factory.install({"plan_search": "q1\nq2"}):
        for name in LLM_NODE_MODULES:
            assert _installed_build_model(name) is not real[name]

        model = nodes.plan_search.build_model("research")
        assert model.invoke("プロンプト").content == "q1\nq2"
        assert fake_model_factory.prompts_for("plan_search") == ["プロンプト"]

    # install を抜けると本物へ戻る
    for name in LLM_NODE_MODULES:
        assert _installed_build_model(name) is real[name]


def test_fake_model_factory_raises_for_unspecified_node(fake_model_factory):
    """応答を指定していないノードが呼ばれたら失敗する（暗黙の既定応答を作らない）。"""
    with fake_model_factory.install({"plan_search": "q1"}), pytest.raises(
        AssertionError, match="extract_common"
    ):
        nodes.extract_common.build_model("research")


def test_fake_model_factory_rejects_unknown_node(fake_model_factory):
    """未知のノード名は即座に拒否する。"""
    with pytest.raises(AssertionError, match="未知のノード名"):
        fake_model_factory.install({"unknown_node": "x"}).__enter__()


# --- 非決定性の固定（T006） -----------------------------------------------


def test_frozen_now_fixes_now_but_delegates_parsing(frozen_now):
    """`frozen_now` は `now` のみを固定し、パースは実物へ委譲する（LAYOUT-004-1）。"""
    fixed = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)
    assert frozen_now.now == fixed
    assert nodes.parse_instruction.datetime.now() == fixed
    # wraps により実物のメソッドは生きている
    assert nodes.parse_instruction.datetime.fromisoformat("2025-01-01").year == 2025
    assert nodes.parse_instruction.datetime.strptime("2025-01-01", "%Y-%m-%d").day == 1


def test_frozen_now_can_be_moved(frozen_now):
    """`set` / `advance` で固定時刻を任意の時点へ動かせる。"""
    frozen_now.set(datetime(2030, 5, 5, tzinfo=UTC))
    assert nodes.parse_instruction.datetime.now().year == 2030
    frozen_now.advance(days=10)
    assert nodes.parse_instruction.datetime.now().day == 15


def test_no_retry_sleep_replaces_asyncio_sleep_and_records(no_retry_sleep):
    """`no_retry_sleep` は `tools.x_search` の `asyncio.sleep` を差し替える。"""

    async def _run() -> None:
        for attempt in range(3):
            await x_search.asyncio.sleep(2**attempt)

    asyncio.run(_run())
    assert no_retry_sleep.sleeps == [1, 2, 4]
    assert no_retry_sleep.total == 7


def test_no_retry_sleep_does_not_consume_real_time(no_retry_sleep):
    """差し替えにより待機時間を実時間で消費しない（FR-010 / LAYOUT-004-2）。"""

    async def _run() -> None:
        for _ in range(3):
            await x_search.asyncio.sleep(2.0)

    start = time.monotonic()
    asyncio.run(_run())
    elapsed = time.monotonic() - start

    # 実時間なら 6 秒。差し替えが効いていれば 3 秒未満で完了する
    assert no_retry_sleep.total == 6.0
    assert elapsed < no_retry_sleep.total / 2


def test_tmp_cache_dir_isolates_repository_cache(tmp_cache_dir):
    """`tmp_cache_dir` は実リポジトリの `cache/` ではなく一時ディレクトリを指す。"""
    from trend_researcher.config import _REPO_ROOT

    assert tmp_cache_dir.is_dir()
    assert _REPO_ROOT / "cache" != tmp_cache_dir
    assert Configuration.load().cache_dir == str(tmp_cache_dir)
    assert Configuration.load(env_prefix="YTR").cache_dir == str(tmp_cache_dir)


# --- 構造化出力と使用量のフェイク（T013 / T018） ----------------------------

#: 構造化出力の検証に使うスキーマ（`parse_instruction` の出力型）。
INSTRUCTION = {
    "raw_text": "AI 動画のトレンドを 3 件",
    "topic": "AI 動画",
    "max_results": 3,
}


def test_fake_llm_structured_output_fails_by_default(fake_model_factory):
    """既定では `OutputParserException` を送出する（全回失敗 → フォールバックの経路）。

    構造化出力が黙って成功すると、US2 の「契約を満たさない応答」のテストが
    緑のまま何も検証しなくなる。
    """
    with fake_model_factory.install({"plan_search": "q1"}):
        model = nodes.plan_search.build_model("research")

        with pytest.raises(OutputParserException):
            model.with_structured_output(ResearchInstruction).invoke("プロンプト")


def test_fake_llm_structured_output_awaits_and_fails_too(fake_model_factory):
    """非同期経路も同じく失敗する（`ainvoke` の分岐を素通りさせない）。"""
    with fake_model_factory.install({"plan_search": "q1"}):
        model = nodes.plan_search.build_model("research")

        with pytest.raises(OutputParserException):
            asyncio.run(model.with_structured_output(ResearchInstruction).ainvoke("プロンプト"))


def test_fake_model_factory_structured_output_succeeds_when_configured(fake_model_factory):
    """`structured=` を渡したノードだけ成功し、戻り値はスキーマで検証される。"""
    with fake_model_factory.install({"plan_search": "q1"}, structured={"plan_search": INSTRUCTION}):
        model = nodes.plan_search.build_model("research")

        result = model.with_structured_output(ResearchInstruction).invoke("プロンプト")

        assert isinstance(result, ResearchInstruction)
        assert (result.topic, result.max_results) == ("AI 動画", 3)


def test_fake_model_factory_structured_output_requires_the_configured_schema(
    fake_model_factory,
):
    """`structured=` の値がスキーマに合わなければ失敗する（素通ししない）。"""
    with fake_model_factory.install(
        {"plan_search": "q1"}, structured={"plan_search": {"unknown_field": 1}}
    ):
        model = nodes.plan_search.build_model("research")

        with pytest.raises(ValidationError, match="raw_text"):
            model.with_structured_output(ResearchInstruction).invoke("プロンプト")


def test_fake_model_factory_structured_calls_are_recorded(fake_model_factory):
    """構造化出力のプロンプトも同じ記録に残る（呼び出し回数を数えられる）。"""
    with fake_model_factory.install({"plan_search": "q1"}, structured={"plan_search": INSTRUCTION}):
        model = nodes.plan_search.build_model("research")
        model.with_structured_output(ResearchInstruction).invoke("構造化プロンプト")
        model.invoke("通常プロンプト")

        assert fake_model_factory.prompts_for("plan_search") == [
            "構造化プロンプト",
            "通常プロンプト",
        ]


def test_fake_model_factory_rejects_unknown_structured_node(fake_model_factory):
    """`structured=` の未知のノード名も即座に拒否する（応答を無言で捨てない）。"""
    with pytest.raises(AssertionError, match="未知のノード名"):
        fake_model_factory.install({"plan_search": "q1"}, structured={"unknown": {}}).__enter__()


def test_fake_message_carries_no_usage_by_default(fake_model_factory):
    """`_FakeMessage` は `usage_metadata` を持ち、既定は `None`（FR-061 の欠落経路）。"""
    with fake_model_factory.install({"plan_search": "q1"}):
        message = nodes.plan_search.build_model("research").invoke("プロンプト")

        assert message.usage_metadata is None


def test_no_retry_sleep_covers_every_module(no_retry_sleep):
    """スパイは**どのモジュールからの**待機も捕まえる（ノード以外の境界も含む）。

    `tools/llm.py` のような呼び出し境界は `import asyncio` の属性参照で待つため、
    モジュールを名指しした差し替えは同じ 1 箇所（`asyncio.sleep`）を対象にする。
    """

    async def _run() -> None:
        await asyncio.sleep(3)

    asyncio.run(_run())

    assert no_retry_sleep.sleeps == [3]


def test_sleep_spy_is_installed_without_requesting_the_fixture():
    """`no_retry_sleep` は autouse（要求しないテストでも待機で実時間を消費しない）。

    US2 でリトライ待機が入ると、`retry_wait_seconds` の既定 1 秒 × 試行回数が
    スイート全体（SC-013 の 60 秒）に効いてくる。
    """
    assert hasattr(asyncio.sleep, "sleeps")
    assert hasattr(asyncio.sleep, "total")
