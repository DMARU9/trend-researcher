"""X（Twitter）用 provider。"""

from __future__ import annotations

from datetime import datetime

from trend_researcher.config import Config
from trend_researcher.models import Candidate, Context
from trend_researcher.prompts import (
    X_ANALYZE_CONTENT_PROMPT,
    X_EXTRACT_COMMON_PROMPT,
    X_PARSE_INSTRUCTION_PROMPT,
    X_PLAN_SEARCH_PROMPT,
)
from trend_researcher.tools.x_search import fetch_threads, search_tweets


def _sort_by_likes(candidates: list[Candidate]) -> list[Candidate]:
    """いいね数の多い順に並べ替え、relevance_rank を振り直す。"""
    ordered = sorted(candidates, key=lambda c: (c.like_count or 0), reverse=True)
    for rank, c in enumerate(ordered, start=1):
        c.relevance_rank = rank
    return ordered


def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """同一 id の候補を取得順の先勝ちで除去する（FR-024）。

    ソート種別に関わらず適用する。likes モードでも複数クエリの結果には同じ
    投稿が現れるため、除去しないと同一ツイートが複数枠を占める。
    """
    seen: set[str] = set()
    unique: list[Candidate] = []
    for c in candidates:
        if c.id not in seen:
            seen.add(c.id)
            unique.append(c)
    return unique


class XProvider:
    name = "x"

    # --- コアへ渡す差の表現（コアは値を解釈しない） ---
    env_prefix = "XTR"
    #: 検索クエリ数のハード上限（LLM が 5 件を守らなくても安全に切り詰める）
    #: 注: Protocol の可変属性は mypy では不変（invariant）のため、`int | None` を
    #: 明示しないと `int` 推論になって適合しない。
    max_search_queries: int | None = 8
    content_noun = "ツイート"
    candidates_section_title = "## 選定ツイートリスト（上位 N 件）"

    def selection_note(self, sort_by: str) -> str:
        """選定基準の注記。relevance は fetch 後の「いいね昇順」並べ替えに合わせる。"""
        label = "いいね数の多い順" if sort_by == "likes" else "いいね数の少ない順"
        return f"選定基準: 検索結果から{label}に上位 N 件を採用"

    def search(
        self,
        queries: list[str],
        max_results: int,
        published_after: datetime | None,
        sort_by: str,
        config: Config,
    ) -> list[Candidate]:
        # X 検索は --since をネイティブサポートするため、各クエリに since: を付与する
        if published_after is not None:
            since = published_after.date().isoformat()
            queries = [f"{q} since:{since}" for q in queries]

        # 取得した候補を溜めるプール。likes / relevance で取り方が違うため
        # サイズは分岐内で決め、リスト自体は共通で 1 つだけ宣言する
        pool: list[Candidate] = []

        if sort_by == "likes":
            pool_size = max(config.search_pool_size, max_results)
            for q in queries:
                pool.extend(search_tweets(q, max_results=pool_size, accounts_db=str(config.accounts_db)))
            # 重複を除去してからいいね降順に並べる（除去しないと同一ツイートが複数枠を占める。FR-024）
            ordered = _sort_by_likes(_dedupe(pool))
            candidates = ordered[:max_results]
        else:
            # 関連度順（Top タブ）で取得し、本文欠落分を除外しても max_results 件
            # 確保できるようプールを多めに取る。ただし search_pool_size（likes 用の 50）は
            # 使わず小さなバッファに留め、1アカウント当たりの検索リクエストを抑える。
            pool_size = max(max_results * 3, max_results + 20)
            for q in queries:
                pool.extend(
                    search_tweets(
                        q,
                        max_results=pool_size,
                        accounts_db=str(config.accounts_db),
                        max_retries=config.max_retries,
                    )
                )
            # 重複（id）を除去し、取得順（関連度順）を維持
            ordered = _dedupe(pool)
            # いいね昇順の並び替えは fetch 後（tweet_details で正確な like_count が
            # 確定した後）に resort() で行うため、ここでは取得順のまま截断する
            candidates = ordered[:max_results]
        return candidates

    def resort(self, candidates: list[Candidate], sort_by: str) -> list[Candidate]:
        """fetch 後（正確な like_count 確定後）に並び替える。

        sort_by=="likes" はいいね降順、それ以外（relevance）は「本文あり」のみを残して
        いいね昇順に並べる。いいね数が同じ場合は取得時の relevance_rank 順を維持する。
        """
        if sort_by == "likes":
            ordered = sorted(candidates, key=lambda c: (c.like_count or 0), reverse=True)
        else:
            with_text = [c for c in candidates if (c.text or "").strip()]
            ordered = sorted(with_text, key=lambda c: (c.like_count or 0, c.relevance_rank))
        for rank, c in enumerate(ordered, start=1):
            c.relevance_rank = rank
        return ordered

    def fetch_contexts(self, candidates: list[Candidate], config: Config) -> tuple[list[Context], list[str]]:
        notes: list[str] = []
        if not candidates:
            return [], notes
        try:
            contexts = fetch_threads(candidates, accounts_db=str(config.accounts_db))
            # 検索結果（SearchTimeline）では like_count 等が 0 で埋まることがあるため、
            # tweet_details で取得した正確なカウントで候補を上書きする
            by_id = {c.id: c for c in candidates}
            for ctx in contexts:
                cand = by_id.get(ctx.id)
                if cand is not None and ctx.counts is not None:
                    cand.like_count = ctx.counts.get("like_count")
                    cand.retweet_count = ctx.counts.get("retweet_count")
                    cand.reply_count = ctx.counts.get("reply_count")
                    cand.quote_count = ctx.counts.get("quote_count")
        except Exception as exc:  # noqa: BLE001 - コンテキスト取得失敗は本文のみで解析
            notes.append(f"スレッド取得に失敗しました（本文のみで解析）: {exc}")
            contexts = [Context(id=c.id, text=c.text) for c in candidates]
        return contexts, notes

    def candidate_table_header(self) -> tuple[str, str]:
        return (
            "| # | 本文抜粋 | 投稿者 | いいね | RT | 引用 | URL |",
            "|---|----------|--------|--------|----|------|-----|",
        )

    def render_candidate_row(self, c: Candidate) -> str:
        snippet = (c.text or "").replace("\n", " ")[:50]
        likes = f"{c.like_count:,}" if c.like_count is not None else "-"
        rts = f"{c.retweet_count:,}" if c.retweet_count is not None else "-"
        quotes = f"{c.quote_count:,}" if c.quote_count is not None else "-"
        author = f"@{c.author_handle}" if c.author_handle else c.author_name
        return f"| {c.relevance_rank} | {snippet} | {author} | {likes} | {rts} | {quotes} | {c.url} |"

    def render_block_title(self, c: Candidate) -> str:
        handle = c.author_handle or c.author_name
        return f"### {c.relevance_rank}. @{handle} のツイート"

    def render_block_meta(self, c: Candidate) -> list[str]:
        bits = [f"投稿者: {c.author_name}" if c.author_name else None,
                f"フォロワー: {c.author_followers:,}" if c.author_followers is not None else None,
                f"いいね: {c.like_count:,}" if c.like_count is not None else None,
                f"RT: {c.retweet_count:,}" if c.retweet_count is not None else None,
                f"公開日: {c.published_at.date()}" if c.published_at is not None else None]
        return [b for b in bits if b]

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
        return "該当ツイート"
