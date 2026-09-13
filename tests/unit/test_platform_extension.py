"""US1: 登録だけで新しいプラットフォームが動くことの検証（FR-002 / FR-026 / SC-002）。

コア（`nodes/` / `graph.py` / `configuration.py`）に手を入れず、`Provider` Protocol を
満たすクラスを `register_provider()` で登録するだけでパイプラインが完走することを示す。
境界（検索・コンテキスト取得・LLM）はテスト内のフェイクで置き換え、ネットワーク・実
認証情報を使わない（原則 II / FR-023）。

検証するのは「登録が効くこと」だけであり、プロンプト本文は既存 X のテンプレートを
流用する（コアがプロンプトの中身を解釈しないことの裏返しでもある）。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from trend_researcher.graph import build_graph, render_report
from trend_researcher.models import Candidate, Context, ResearchReport
from trend_researcher.progress import NODE_ORDER
from trend_researcher.prompts import (
    X_ANALYZE_CONTENT_PROMPT,
    X_EXTRACT_COMMON_PROMPT,
    X_PARSE_INSTRUCTION_PROMPT,
    X_PLAN_SEARCH_PROMPT,
)
from trend_researcher.providers import _PROVIDERS, get_provider, register_provider

#: 試験用プラットフォーム名。既存の登録（x / youtube）と衝突しないことだけが要件。
DUMMY_NAME = "dummy"

#: 解析対象件数。検索結果のプールとレポートの件数を一致させる。
MAX_RESULTS = 3


def _dummy_candidates(count: int) -> list[Candidate]:
    """試験用プラットフォームの検索結果（決定的・ネットワーク不要）。"""
    return [
        Candidate(
            platform=DUMMY_NAME,
            id=f"{DUMMY_NAME}{i}",
            title=f"投稿タイトル{i}",
            text=f"投稿本文 {i}",
            url=f"https://example.test/{DUMMY_NAME}/{i}",
            author_name=f"投稿者{i}",
            like_count=100 - i,
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            relevance_rank=i,
        )
        for i in range(1, count + 1)
    ]


class DummyProvider:
    """`Provider` Protocol を満たすだけの試験用プラットフォーム。

    コアが解釈する値（`content_noun` / `candidates_section_title` /
    `selection_note`）は既存 2 件と重ならない文字列にし、レポートへ反映されたことを
    断言できるようにする。検索・取得は境界のフェイクとして固定値を返す。
    """

    name = DUMMY_NAME

    # --- 追加フック（US1 で Protocol に載る 5 つ） ---
    env_prefix = "DUM"
    max_search_queries = None  # 無制限
    content_noun = "投稿"
    candidates_section_title = "## 選定投稿リスト（試験用プラットフォーム順）"

    #: `None` なら `max_results` 件、整数ならその件数を返す（0 で検索 0 件を再現）。
    result_count: int | None = None

    def selection_note(self, sort_by: str) -> str:
        return f"選定基準: 試験用プラットフォームの基準（{sort_by}）で上位 N 件を採用"

    # --- 検索・取得（外部境界はすべてテスト内のフェイク） ---
    def search(
        self,
        queries: list[str],
        max_results: int,
        published_after: datetime | None,
        sort_by: str,
        config: Any,
    ) -> list[Candidate]:
        count = max_results if self.result_count is None else self.result_count
        return _dummy_candidates(count)

    def fetch_contexts(
        self, candidates: list[Candidate], config: Any
    ) -> tuple[list[Context], list[str]]:
        contexts = [Context(id=c.id, text=f"{c.text} の追加文脈") for c in candidates]
        return contexts, ["試験用プラットフォームの取得メモ"]

    def resort(self, candidates: list[Candidate], sort_by: str) -> list[Candidate]:
        return list(candidates)

    # --- レンダリング ---
    def candidate_table_header(self) -> tuple[str, str]:
        return (
            "| # | 投稿 | 投稿者 | いいね | URL |",
            "|---|------|--------|--------|-----|",
        )

    def render_candidate_row(self, c: Candidate) -> str:
        likes = f"{c.like_count:,}" if c.like_count is not None else "-"
        return f"| {c.relevance_rank} | {c.text} | {c.author_name} | {likes} | {c.url} |"

    def render_block_title(self, c: Candidate) -> str:
        return f"### {c.relevance_rank}. {c.author_name} の投稿"

    def render_block_meta(self, c: Candidate) -> list[str]:
        bits = [
            f"投稿者: {c.author_name}" if c.author_name else None,
            f"いいね: {c.like_count:,}" if c.like_count is not None else None,
            f"公開日: {c.published_at.date()}" if c.published_at is not None else None,
        ]
        return [b for b in bits if b]

    # --- プロンプト（本文はコアが解釈しないため既存テンプレートを流用） ---
    @property
    def parse_instruction_prompt(self) -> str:
        return X_PARSE_INSTRUCTION_PROMPT

    @property
    def plan_search_prompt(self) -> str:
        return X_PLAN_SEARCH_PROMPT

    @property
    def analyze_content_prompt(self) -> str:
        return X_ANALYZE_CONTENT_PROMPT

    @property
    def extract_common_prompt(self) -> str:
        return X_EXTRACT_COMMON_PROMPT

    @property
    def common_theme_supporting_label(self) -> str:
        return "該当投稿"


#: LLM ノードごとの応答（プロンプト本文に依存しない。R-7 / LAYOUT-004-4）。
_RESPONSES: dict[str, str] = {
    "parse_instruction": (
        '```json\n{"topic": "試験用プラットフォームの調査", '
        f'"max_results": {MAX_RESULTS}, "output_format": "markdown"}}\n```'
    ),
    "plan_search": "クエリA\nクエリB\nクエリC",
    "analyze_content": "## 概要\n試験用プラットフォームの要約",
    "extract_common": "## 共通テーマ\n### 試験テーマ\n- 説明: 試験用の説明\n- 該当: 全件",
}

#: 進捗行の先頭（`[1/7] node ... phase`）。総数は導出値なので固定しない。
_PROGRESS_RE = re.compile(r"^\[\d+/\d+\] ")


@pytest.fixture
def dummy_platform() -> Iterator[str]:
    """試験用プラットフォームを登録し、テスト終了時に**必ず**解除する。

    登録を残すと `available_platforms()` を使う他のテスト（走査テスト・CLI の
    `--platform` の選択肢）へ影響するため、`finally` で解除する。
    """
    register_provider(DummyProvider)
    try:
        yield DUMMY_NAME
    finally:
        _PROVIDERS.pop(DUMMY_NAME, None)


def _run_graph(platform: str, cache_dir: Path) -> dict[str, Any]:
    """`__main__` と同じ形の入力でグラフを 1 回実行する（CLI は介さない）。"""
    configurable: dict[str, Any] = {
        "platform": platform,
        "max_results": MAX_RESULTS,
        "sort_by": "relevance",
        "output_format": "markdown",
        "cache_dir": str(cache_dir),
    }
    initial_state = {
        "messages": [HumanMessage(content="試験用プラットフォームの調査をしたい")],
        "platform": platform,
        "max_results": MAX_RESULTS,
    }
    return build_graph().invoke(initial_state, {"configurable": configurable})


def _phases(messages: list[Any]) -> list[tuple[str, str]]:
    """進捗行から (ノード名, フェーズ) を出現順に取り出す（重複は畳まない）。"""
    phases: list[tuple[str, str]] = []
    for message in messages:
        content = message.content if hasattr(message, "content") else str(message)
        if not _PROGRESS_RE.match(content):
            continue
        rest = content.split("] ", 1)[1]
        node, _, tail = rest.partition(" ... ")
        phases.append((node, tail.split("（")[0]))
    return phases


def test_registered_platform_completes_the_pipeline(
    dummy_platform: str, fake_model_factory: Any, tmp_path: Path
) -> None:
    """登録しただけで 7 ノードのパイプラインが完走し、レポートが生成される。"""
    with fake_model_factory.install(_RESPONSES):
        result = _run_graph(dummy_platform, tmp_path / "cache")

    report = result["report"]
    assert isinstance(report, ResearchReport)
    # 指示の platform は provider.name から決まる（コアに名前を書かない）
    assert report.instruction.platform == DUMMY_NAME
    assert [c.id for c in report.candidates] == [
        f"{DUMMY_NAME}{i}" for i in range(1, MAX_RESULTS + 1)
    ]
    assert len(report.analyses) == MAX_RESULTS


def test_registered_platform_drives_the_reported_text(
    dummy_platform: str, fake_model_factory: Any, tmp_path: Path
) -> None:
    """`candidates_section_title` と `selection_note` が出力に反映される。"""
    with fake_model_factory.install(_RESPONSES):
        result = _run_graph(dummy_platform, tmp_path / "cache")

    report = result["report"]
    provider = get_provider(dummy_platform)
    markdown = render_report(report)

    assert provider.candidates_section_title in markdown
    # 選定基準の注記は provider の文面がそのまま載る（コアは文面を組み立てない）
    assert provider.selection_note("relevance") in report.notes
    # 選定リストの表も provider が描く
    assert "| # | 投稿 | 投稿者 | いいね | URL |" in markdown


def test_registered_platform_content_noun_is_used_when_no_results(
    dummy_platform: str,
    fake_model_factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """検索 0 件のときの名詞が provider の `content_noun` になる。"""
    monkeypatch.setattr(DummyProvider, "result_count", 0)

    with fake_model_factory.install(_RESPONSES):
        result = _run_graph(dummy_platform, tmp_path / "cache")

    report = result["report"]
    provider = get_provider(dummy_platform)
    assert report.candidates == []
    assert any(
        f"該当する{provider.content_noun}が見つかりませんでした" in note
        for note in report.notes
    )


def test_registered_platform_reports_progress_for_every_node(
    dummy_platform: str, fake_model_factory: Any, tmp_path: Path
) -> None:
    """進捗は 7 ノードそれぞれで「開始 → 完了」の 2 行になる（欠落・重複なし）。"""
    with fake_model_factory.install(_RESPONSES):
        result = _run_graph(dummy_platform, tmp_path / "cache")

    assert _phases(result["messages"]) == [
        (node, phase) for node in NODE_ORDER for phase in ("開始", "完了")
    ]
