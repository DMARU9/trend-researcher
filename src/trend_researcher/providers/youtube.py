"""YouTube 用 provider。"""

from __future__ import annotations

from datetime import datetime

from trend_researcher.config import Config
from trend_researcher.models import Candidate, Context
from trend_researcher.prompts import (
    YOUTUBE_ANALYZE_CONTENT_PROMPT,
    YOUTUBE_EXTRACT_COMMON_PROMPT,
    YOUTUBE_PARSE_INSTRUCTION_PROMPT,
    YOUTUBE_PLAN_SEARCH_PROMPT,
)
from trend_researcher.tools.transcript import fetch_transcript
from trend_researcher.tools.youtube_search import search_videos


class YouTubeProvider:
    name = "youtube"

    # --- コアへ渡す差の表現（コアは値を解釈しない） ---
    env_prefix = "YTR"
    #: 単一クエリ設計のため上限なし（`None` は無制限）
    #: 注: Protocol の可変属性は mypy では不変（invariant）のため `int | None` を明示する。
    max_search_queries: int | None = None
    content_noun = "動画"
    candidates_section_title = "## 選定動画リスト（関連度順上位 N 件）"

    def selection_note(self, sort_by: str) -> str:
        """選定基準の注記（関連度順のみ。`sort_by` は解釈しない）。"""
        return "選定基準: 検索結果の関連度順に上位 N 件を採用"

    def search(
        self,
        queries: list[str],
        max_results: int,
        published_after: datetime | None,
        sort_by: str,
        config: Config,
    ) -> list[Candidate]:
        # YouTube は単一クエリ（plan_search が 1 件生成）
        query = queries[0] if queries else ""
        return search_videos(query, max_results=max_results, published_after=published_after)

    def fetch_contexts(self, candidates: list[Candidate], config: Config) -> tuple[list[Context], list[str]]:
        notes: list[str] = []
        language = config.transcript_language
        contexts: list[Context] = []
        for cand in candidates:
            transcript = fetch_transcript(cand.id, language=language)
            contexts.append(Context(id=cand.id, text=transcript.text))
            if not transcript.text.strip():
                notes.append(f"字幕取得不可: {cand.title} ({cand.id}) - メタデータのみで解析")
        return contexts, notes

    def resort(self, candidates: list[Candidate], sort_by: str) -> list[Candidate]:
        """YouTube は既に関連度順にソート済みのため、順序を維持する。"""
        return candidates

    def candidate_table_header(self) -> tuple[str, str]:
        return (
            "| # | タイトル | チャンネル | 再生数 | URL |",
            "|---|----------|------------|--------|-----|",
        )

    def render_candidate_row(self, c: Candidate) -> str:
        vc = f"{c.view_count:,}" if c.view_count is not None else "-"
        return f"| {c.relevance_rank} | {c.title} | {c.author_name} | {vc} | {c.url} |"

    def render_block_title(self, c: Candidate) -> str:
        return f"### {c.relevance_rank}. {c.title}"

    def render_block_meta(self, c: Candidate) -> list[str]:
        bits = [f"チャンネル: {c.author_name}" if c.author_name else None,
                f"再生数: {c.view_count:,}" if c.view_count is not None else None,
                f"公開日: {c.published_at.date()}" if c.published_at is not None else None]
        return [b for b in bits if b]

    @property
    def parse_instruction_prompt(self) -> str:
        return YOUTUBE_PARSE_INSTRUCTION_PROMPT

    @property
    def plan_search_prompt(self) -> str:
        return YOUTUBE_PLAN_SEARCH_PROMPT

    @property
    def analyze_content_prompt(self) -> str:
        return YOUTUBE_ANALYZE_CONTENT_PROMPT

    @property
    def extract_common_prompt(self) -> str:
        return YOUTUBE_EXTRACT_COMMON_PROMPT

    @property
    def common_theme_supporting_label(self) -> str:
        return "該当動画"
