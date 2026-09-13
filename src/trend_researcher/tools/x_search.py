"""twscrape を用いた検索・コンテキスト取得（単一クエリ・関連度順上位 N 件）。

twscrape は非同期 API のため、本モジュールは asyncio でラップする。
アカウント DB（クッキー保存先）は呼び出し元（`providers/x.py` の `XSettings.accounts_db`）
から引数で受け取る。
統一モデル Candidate / Context を返す。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from twscrape import API, HttpError, NoAccountError, Tweet, gather
from twscrape.queue_client import AbortReqError, HandledError
from twscrape.xclid import XClIdError

from trend_researcher.models import Candidate, Context

logger = logging.getLogger(__name__)

#: スレッド・リプライ取得（best-effort）で縮退してよい例外。
#:
#: 取得できない項目は空のまま `Context` を返し、呼び出し側は候補の本文だけで解析を
#: 続ける（`providers/x.py::fetch_contexts` は空の `text` を候補の要約へフォール
#: バックする）。捕まえる型は twscrape 実測の例外に限定する（素の
#: `except Exception` は実装バグまで飲み込む。S110 / BLE001 の是正・#47）:
#:
#: - `HttpError` … `NetworkError` / `ConnectError` / `HttpStatusError`（通信・HTTP）
#: - `NoAccountError` … accounts DB に有効なアカウントが無い
#: - `AbortReqError` … `GqlFeaturesOutdatedError` 等の中断（queue_client）
#: - `HandledError` … twscrape が内部で処理済みと判定したエラー（queue_client）
#: - `XClIdError` … `XClIdAccountError` / `XClIdParseError`（CSRF トークン解決）
#: - `ValueError` … `int(tweet_id)` の変換失敗、Cookie/JSON 不正（accounts_pool・utils）
#: - `RuntimeError` … curl バックエンドの内部エラー（http.py）
#: - `SystemError` … accounts DB の整合性エラー（db.py）
_CONTEXT_FETCH_ERRORS: tuple[type[Exception], ...] = (
    HttpError,
    NoAccountError,
    AbortReqError,
    HandledError,
    XClIdError,
    ValueError,
    RuntimeError,
    SystemError,
)


def _to_datetime(value: datetime | None) -> datetime | None:
    """twscrape の datetime を UTC に正規化（naive なら UTC 付与）。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _tweet_to_candidate(tweet: Tweet, rank: int) -> Candidate:
    """twscrape の Tweet を Candidate に変換。"""
    url = f"https://x.com/{tweet.user.username}/status/{tweet.id}" if tweet.user else f"https://x.com/i/web/status/{tweet.id}"
    return Candidate(
        platform="x",
        id=str(tweet.id),
        text=(tweet.rawContent or "").strip(),
        url=url,
        author_handle=tweet.user.username if tweet.user else "",
        author_name=tweet.user.displayname if tweet.user else "",
        author_followers=int(tweet.user.followersCount) if tweet.user else None,
        published_at=_to_datetime(tweet.date),
        like_count=int(tweet.likeCount) if tweet.likeCount is not None else None,
        retweet_count=int(tweet.retweetCount) if tweet.retweetCount is not None else None,
        reply_count=int(tweet.replyCount) if tweet.replyCount is not None else None,
        quote_count=int(tweet.quoteCount) if tweet.quoteCount is not None else None,
        relevance_rank=rank,
    )


async def _search_async(
    query: str,
    max_results: int,
    accounts_db: str,
    max_retries: int = 3,
) -> list[Candidate]:
    """単一検索し、関連度順（Top タブ）の Candidate を取得する。

    取得したツイートはそのまま返す（呼び出し側で「いいね昇順ソート＋本文欠落除外＋
    max_results 件数確保」を行う）。max_results より多めに取得しておくことで、
    本文欠落分を除外しても目標件数を満たしやすくする。
    """
    # レート制限等で空振りしないよう、少し多めに取得する
    fetch_limit = max(max_results * 2, max_results + 20)
    api = API(accounts_db)
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            tweets = await gather(api.search(query, limit=fetch_limit, kv={"product": "Top"}))
            candidates: list[Candidate] = []
            for rank, tweet in enumerate(tweets, start=1):
                candidates.append(_tweet_to_candidate(tweet, rank))
            return candidates
        except Exception as exc:  # noqa: BLE001 - リトライ後に上位へ伝播
            last_exc = exc
            await asyncio.sleep(2 ** attempt)
    if last_exc is not None:
        raise last_exc
    return []


def search_tweets(
    query: str,
    max_results: int = 5,
    accounts_db: str = "accounts.db",
    max_retries: int = 3,
) -> list[Candidate]:
    """同期ラッパ: 単一検索で関連度順（Top タブ）の Candidate を取得する。"""
    return asyncio.run(_search_async(query, max_results, accounts_db, max_retries))


async def _fetch_context_async(tweet_id: str, accounts_db: str, max_replies: int = 3) -> Context:
    """指定ツイートのスレッド（親遡り）＋代表リプライを取得する。"""
    api = API(accounts_db)
    ctx = Context(id=tweet_id)

    # 元ツイートの本文
    try:
        main = await api.tweet_details(int(tweet_id))
        if main is not None:
            ctx.text = (main.rawContent or "").strip()
            # 検索結果では 0 で埋まることがある正確なカウントを保持
            ctx.counts = {
                "like_count": int(main.likeCount) if main.likeCount is not None else None,
                "retweet_count": int(main.retweetCount) if main.retweetCount is not None else None,
                "reply_count": int(main.replyCount) if main.replyCount is not None else None,
                "quote_count": int(main.quoteCount) if main.quoteCount is not None else None,
            }
            # 親ツイート（会話ルート）があればスレッド本文として取り込む
            if getattr(main, "inReplyToTweetId", None):
                try:
                    parent = await api.tweet_details(int(main.inReplyToTweetId))
                    if parent is not None:
                        ctx.thread_text = (parent.rawContent or "").strip()
                except _CONTEXT_FETCH_ERRORS as exc:
                    logger.warning(
                        "親ツイートの取得に失敗しました（tweet_id=%s・スレッド本文なしで継続）: %s",
                        main.inReplyToTweetId,
                        exc,
                    )
    except _CONTEXT_FETCH_ERRORS as exc:
        logger.warning(
            "ツイート本文の取得に失敗しました（tweet_id=%s・空の本文で継続）: %s", tweet_id, exc
        )

    # 代表リプライ（上位 max_replies 件）
    try:
        replies = await gather(api.tweet_replies(int(tweet_id), limit=max_replies))
        ctx.replies = [(r.rawContent or "").strip() for r in replies if r.rawContent]
    except _CONTEXT_FETCH_ERRORS as exc:
        logger.warning(
            "リプライの取得に失敗しました（tweet_id=%s・リプライなしで継続）: %s", tweet_id, exc
        )

    return ctx


async def _fetch_threads_async(candidates: list[Candidate], accounts_db: str) -> list[Context]:
    return await asyncio.gather(*[_fetch_context_async(c.id, accounts_db) for c in candidates])


def fetch_threads(candidates: list[Candidate], accounts_db: str = "accounts.db") -> list[Context]:
    """複数ツイートのスレッド＋リプライを一括取得する。"""
    if not candidates:
        return []
    return asyncio.run(_fetch_threads_async(candidates, accounts_db))
