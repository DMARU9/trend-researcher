"""両プラットフォームの統合テスト（ネットワーク・LLM はモック）。

グラフ全体の流れ（parse→plan→search→fetch→analyze→extract→compile）
が期待通りのレポートを产出することを確認する。
"""

import asyncio
from unittest import mock

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from trend_researcher.config import Config
from trend_researcher.graph import render_report, trend_researcher
from trend_researcher.models import (
    AnalysisFinding,
    Candidate,
    CommonTheme,
    Context,
    OutputFormat,
    ResearchReport,
)


def _fake_candidates_x(n: int) -> list[Candidate]:
    return [
        Candidate(
            platform="x",
            id=f"t{i}",
            author_handle=f"user{i}",
            text=f"ツイート本文 {i}",
            url=f"https://x.com/user{i}/status/{i}",
            like_count=100 - i,
            relevance_rank=i,
        )
        for i in range(1, n + 1)
    ]


def _fake_candidates_youtube(n: int) -> list[Candidate]:
    return [
        Candidate(
            platform="youtube",
            id=f"v{i}",
            title=f"タイトル{i}",
            url=f"https://www.youtube.com/watch?v=v{i}",
            author_name=f"チャンネル{i}",
            view_count=1000 * i,
            relevance_rank=i,
        )
        for i in range(1, n + 1)
    ]


def _fake_contexts(cands: list[Candidate]) -> list[Context]:
    return [Context(id=c.id, text=f"{c.title or c.text} のソーステキスト") for c in cands]


def _fake_analysis(cands: list[Candidate]) -> list[AnalysisFinding]:
    return [
        AnalysisFinding(
            id=c.id,
            title=c.title,
            summary=f"{c.title or c.text} の要約",
            key_points=["ポイントA", "ポイントB"],
            evidence=["根拠1"],
        )
        for c in cands
    ]


class _FakeModel:
    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, prompt: str):
        return self._make(prompt)

    async def ainvoke(self, prompt: str):
        return self._make(prompt)

    def _make(self, prompt: str):
        class _R:
            def __init__(self, content):
                self.content = content

        if "検索クエリ" in prompt or "関連" in prompt:
            if "X（Twitter）" in prompt:
                return _R("オタク 困りごと\n推し活 大変\n同人 在庫")
            return _R("Claude Code 会社運用 解説")
        if "要約" in prompt or "ブログ" in prompt:
            return _R(
                "## 概要\n要約です。ブログでどう扱えるかを詳しく説明します。\n\n"
                "## ブログの活用アイデア\n"
                "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n"
                "|--------|--------------|---------------------|\n"
                "| ポイントA | 価値A | 「キーフレーズA」 |\n"
                "| ポイントB | 価値B | 「キーフレーズB」 |\n\n"
                "## そのまま使える引用\n"
                "- 「抜粋1」（文脈1）\n"
                "- 「抜粋2」（文脈2）"
            )
        if "共通" in prompt:
            return _R(
                "## 共通テーマ\n### 自動化\n- 説明: 両方で語られている\n- 該当: 全件\n- 代表抜粋: 抜粋"
            )
        return _R("{}")


@pytest.fixture
def patched_x():
    with mock.patch(
        "trend_researcher.nodes.parse_instruction.build_model",
        side_effect=_FakeModel,
    ), mock.patch(
        "trend_researcher.nodes.plan_search.build_model",
        side_effect=_FakeModel,
    ), mock.patch(
        "trend_researcher.nodes.analyze_content.build_model",
        side_effect=_FakeModel,
    ), mock.patch(
        "trend_researcher.nodes.extract_common.build_model",
        side_effect=_FakeModel,
    ), mock.patch(
        "trend_researcher.providers.x.search_tweets",
        side_effect=lambda q, max_results=5, accounts_db="accounts.db", **kw: _fake_candidates_x(max_results),
    ), mock.patch(
        "trend_researcher.providers.x.fetch_threads",
        side_effect=lambda cands, accounts_db="accounts.db": _fake_contexts(cands),
    ):
        yield


@pytest.fixture
def patched_youtube():
    with mock.patch(
        "trend_researcher.nodes.parse_instruction.build_model",
        side_effect=_FakeModel,
    ), mock.patch(
        "trend_researcher.nodes.plan_search.build_model",
        side_effect=_FakeModel,
    ), mock.patch(
        "trend_researcher.nodes.analyze_content.build_model",
        side_effect=_FakeModel,
    ), mock.patch(
        "trend_researcher.nodes.extract_common.build_model",
        side_effect=_FakeModel,
    ), mock.patch(
        "trend_researcher.providers.youtube.search_videos",
        side_effect=lambda q, max_results=5, published_after=None: _fake_candidates_youtube(max_results),
    ), mock.patch(
        "trend_researcher.providers.youtube.fetch_transcript",
        side_effect=lambda vid, language="ja": Context(id=vid, text="字幕テキスト"),
    ):
        yield


def _run_graph_sync(instruction: str, platform: str = "x", **kwargs) -> dict:
    """テスト用の同期ラッパー: trend_researcher グラフを実行する。"""
    config = Config.load(platform=platform, cache_dir=kwargs.get("cache_dir"), max_results=kwargs.get("max_results"))
    output_format = kwargs.pop("output_format", OutputFormat.MARKDOWN)
    initial_state = {
        "messages": [HumanMessage(content=instruction)],
    }
    runnable_config: RunnableConfig = {
        "configurable": {
            "platform": platform,
            "output_format": output_format.value,
            "max_results": kwargs.get("max_results", 5),
            "sort_by": kwargs.get("sort_by", "relevance"),
            "transcript_language": kwargs.get("transcript_language", "ja"),
            "use_trends": kwargs.get("use_trends", False),
            "cache_dir": str(config.cache_dir),
        },
    }
    return trend_researcher.invoke(initial_state, runnable_config)


# --- X: 既定 5 件・Markdown ---
def test_x_default_markdown(patched_x):
    result = _run_graph_sync("オタクの活動における困りごとを調査したい", platform="x")
    report = result["report"]
    assert isinstance(report, ResearchReport)
    assert report.instruction.platform == "x"
    assert len(report.candidates) == 5
    assert len(report.analyses) == 5
    md = render_report(report)
    assert "選定ツイートリスト" in md
    assert "共通ネタ" in md
    assert "**概要**" in md
    assert "| 切り口 | 読者への価値 | 拾えるキーフレーズ |" in md


# --- X: いいね順 ---
def test_x_sort_likes(patched_x):
    result = _run_graph_sync("Claude Code の使い方", platform="x", sort_by="likes", max_results=5)
    report = result["report"]
    likes = [c.like_count for c in report.candidates]
    assert likes == sorted(likes, reverse=True)


# --- YouTube: 件数指定・JSON ---
def test_youtube_max_results_json(patched_youtube):
    result = _run_graph_sync(
        "機械学習チュートリアルを参考にブログを書きたい",
        platform="youtube",
        max_results=10,
        output_format=OutputFormat.JSON,
    )
    report = result["report"]
    assert len(report.candidates) == 10
    assert report.instruction.output.format == OutputFormat.JSON
    rendered = render_report(report)
    import json

    parsed = json.loads(rendered)
    assert len(parsed["candidates"]) == 10
    assert parsed["instruction"]["platform"] == "youtube"


# --- YouTube: Markdown 表ヘッダ ---
def test_youtube_markdown_table(patched_youtube):
    result = _run_graph_sync("Claude Code で会社を回す方法", platform="youtube")
    report = result["report"]
    md = render_report(report)
    assert "選定動画リスト" in md
    assert "チャンネル" in md
    assert "再生数" in md
