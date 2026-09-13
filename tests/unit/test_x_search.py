"""`tools/x_search.py` と `providers/x.py` の単体テスト（twscrape はモック）。

固定する契約:

- twscrape のデータを `Candidate` / `Context` へ写す変換（`_to_datetime` の UTC 正規化）
- リトライ枯渇時は最後の例外を送出し、待機は指数バックオフ（1, 2, 4 秒）になる
- スレッド・リプライ取得は例外・`None`・部分応答でも落ちずに縮退する
  （縮退してよい型は twscrape 実測の例外に限定し、握り潰さず WARNING で残す・#47）
- FR-024: 同一 `id` の重複除去は先勝ち・取得順維持・**除去後に**截断
- 選定基準（relevance = いいね昇順＋本文欠落除外 / likes = いいね降順）
- 描画（表ヘッダ・行・ブロック見出し・メタ）

待機時間は `no_retry_sleep` フィクスチャでスパイし、実時間を消費しない
（LAYOUT-004-2）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest import mock

import pytest
from twscrape import HttpError, NoAccountError, Tweet, User
from twscrape.queue_client import HandledError

from trend_researcher.config import _REPO_ROOT
from trend_researcher.configuration import Configuration
from trend_researcher.models import Candidate, Context
from trend_researcher.providers.x import XProvider, XSettings, _sort_by_likes
from trend_researcher.tools import x_search
from trend_researcher.tools.x_search import (
    _to_datetime,
    _tweet_to_candidate,
    fetch_threads,
    search_tweets,
)


@pytest.fixture(autouse=True)
def isolated_x_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """X 固有設定の環境変数を消し、既定（`accounts.db` / 50 / 3）で検証する。

    実環境の `TR_*` / `XTR_*` がテスト結果を変えないようにする（SET-003）。
    """
    for name in ("ACCOUNTS_DB", "SEARCH_POOL_SIZE", "MAX_RETRIES"):
        for prefix in ("TR", "XTR", "YTR"):
            monkeypatch.delenv(f"{prefix}_{name}", raising=False)


def test_fetch_thread_is_removed():
    """単数版のスレッド取得は削除された（FR-010 / REM-005）。

    `fetch_threads`（複数形）は常にリストを返すため、単数版は実行時の参照が 0。
    1 件だけ返る場合は同じ経路で検証する（`test_fetch_threads_*` 参照）。
    """
    assert not hasattr(x_search, "fetch_thread")
    assert hasattr(x_search, "fetch_threads")


def _fake_user(tid: int) -> User:
    return User(
        id=tid * 10,
        username=f"user{tid}",
        displayname=f"User {tid}",
        followersCount=100 + tid,
        friendsCount=10,
        statusesCount=5,
        rawDescription="",
        id_str=str(tid * 10),
        url=f"https://x.com/user{tid}",
        favouritesCount=0,
        listedCount=0,
        mediaCount=0,
        location="",
        profileImageUrl="",
        profileBannerUrl="",
        verified=False,
        created=datetime(2020, 1, 1, tzinfo=UTC),
    )


#: 未指定を表すセンチネル（`None` は「欠落した応答」として意味を持つため区別する）
_UNSET: Any = object()


def _fake_tweet(
    tid: int,
    *,
    raw_content: str | None = None,
    user_missing: bool = False,
    date_missing: bool = False,
    counts_none: bool = False,
    in_reply_to: int | None = None,
    like_count: Any = _UNSET,
    retweet_count: Any = _UNSET,
    reply_count: Any = _UNSET,
    quote_count: Any = _UNSET,
) -> Tweet:
    """テスト用の Tweet。`*_missing` / `counts_none` で欠落した応答を再現する。"""
    return Tweet(
        id=tid,
        id_str=str(tid),
        url=f"https://x.com/user{tid}/status/{tid}",
        date=None if date_missing else datetime(2026, 1, 1, tzinfo=UTC),
        rawContent=f"ツイート本文 {tid}" if raw_content is None else raw_content,
        lang="ja",
        conversationId=tid,
        conversationIdStr=str(tid),
        cashtags=[],
        likeCount=None if counts_none else (tid * 3 if like_count is _UNSET else like_count),
        retweetCount=None
        if counts_none
        else (tid * 2 if retweet_count is _UNSET else retweet_count),
        replyCount=None if counts_none else (tid if reply_count is _UNSET else reply_count),
        quoteCount=None if counts_none else (tid if quote_count is _UNSET else quote_count),
        isQuoteStatus=False,
        retweetedTweet=None,
        quotedTweet=None,
        mentionedUsers=[],
        hashtags=[],
        links=[],
        media=[],
        viewCount=None,
        bookmarkedCount=None,
        user=None if user_missing else _fake_user(tid),
        source=None,
        inReplyToTweetId=in_reply_to,
    )


async def _gather(*items: Any) -> list[Any]:  # type: ignore[no-untyped-def]
    """twscrape の `gather`（非同期ジェネレータ）と `asyncio.gather`（コルーチン）を兼ねる。

    `tools/x_search.py` は両方に同じ名前を使うため、テストダブルも両方を捌く。
    """
    out: list[Any] = []
    for item in items:
        if hasattr(item, "__aiter__"):
            async for element in item:
                out.append(element)
        else:
            out.append(await item)
    return out


async def _tweet_stream(tweets: list[Tweet]):  # type: ignore[no-untyped-def]
    for t in tweets:
        yield t


class _ThreadAPI:
    """`tweet_details` / `tweet_replies` だけを持つ twscrape API の代役。"""

    def __init__(
        self,
        *,
        details: dict[int, Tweet | None] | None = None,
        errors: dict[int, Exception] | None = None,
        replies: list[Tweet] | None = None,
        replies_error: Exception | None = None,
    ) -> None:
        self.details = details if details is not None else {}
        self.errors = errors if errors is not None else {}
        self.replies = replies if replies is not None else []
        self.replies_error = replies_error
        self.detail_ids: list[int] = []
        self.reply_calls: list[tuple[int, int]] = []

    async def tweet_details(self, tid: int) -> Tweet | None:
        self.detail_ids.append(tid)
        if tid in self.errors:
            raise self.errors[tid]
        return self.details.get(tid)

    async def tweet_replies(self, tid: int, limit: int = 3):  # type: ignore[no-untyped-def]
        self.reply_calls.append((tid, limit))
        if self.replies_error is not None:
            raise self.replies_error
        for r in self.replies:
            yield r


def _install_thread_api(api: _ThreadAPI) -> Any:
    return mock.patch("trend_researcher.tools.x_search.API", lambda db: api)


def test_to_datetime_normalizes_naive_and_aware_to_utc():
    assert _to_datetime(None) is None
    # naive は UTC 付与のみ（時刻は動かさない）
    naive = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC).replace(tzinfo=None)
    assert naive.tzinfo is None
    assert _to_datetime(naive) == datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    # aware は UTC へ換算する（JST 09:00 = UTC 00:00）
    jst = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))
    assert _to_datetime(jst) == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_tweet_to_candidate_mapping():
    t = _fake_tweet(42)
    c = _tweet_to_candidate(t, rank=1)
    assert isinstance(c, Candidate)
    assert c.id == "42"
    assert c.author_handle == "user42"
    assert c.like_count == 126
    assert c.retweet_count == 84
    assert c.relevance_rank == 1


def test_tweet_to_candidate_without_user_falls_back_to_web_url():
    """投稿者が削除済みなどで `user` が欠けても落ちない（URL は /i/web/ 形式）。"""
    c = _tweet_to_candidate(_fake_tweet(7, user_missing=True), rank=3)
    assert c.url == "https://x.com/i/web/status/7"
    assert c.author_handle == ""
    assert c.author_name == ""
    assert c.author_followers is None


def test_tweet_to_candidate_absent_values_stay_absent():
    """`None` のカウント・投稿日時・本文は 0 やダミー値に潰さない。"""
    c = _tweet_to_candidate(_fake_tweet(5, counts_none=True, date_missing=True, raw_content="  "), rank=1)
    assert c.like_count is None
    assert c.retweet_count is None
    assert c.reply_count is None
    assert c.quote_count is None
    assert c.published_at is None
    assert c.text == ""


def test_search_tweets_top_n():
    tweets = [_fake_tweet(i) for i in range(1, 8)]

    class _FakeAPI:
        def __init__(self, db):  # type: ignore[no-untyped-def]
            self.db = db

        def search(self, query, limit=5, kv=None):  # type: ignore[no-untyped-def]
            return _tweet_stream(tweets[:limit])

    with mock.patch("trend_researcher.tools.x_search.API", _FakeAPI), mock.patch(
        "trend_researcher.tools.x_search.gather", _gather
    ):
        candidates = search_tweets("test", max_results=5)
    # fetch_limit は max_results*2 以上になるため、元ツイート（7件）全件が返る
    assert len(candidates) == 7
    assert all(isinstance(c, Candidate) for c in candidates)


def test_sort_by_likes_orders_descending_and_renumbers():
    cands = [
        Candidate(platform="x", id="a", like_count=10, relevance_rank=1),
        Candidate(platform="x", id="b", like_count=300, relevance_rank=2),
        Candidate(platform="x", id="c", like_count=50, relevance_rank=3),
        Candidate(platform="x", id="d", like_count=None, relevance_rank=4),
    ]
    ordered = _sort_by_likes(cands)
    assert [c.id for c in ordered] == ["b", "c", "a", "d"]
    assert [c.relevance_rank for c in ordered] == [1, 2, 3, 4]
    assert ordered[-1].like_count is None


def test_x_provider_search_relevance_dedupes_keeps_order():
    pool_a = [Candidate(platform="x", id=f"a{i}", text=f"本文{i}", like_count=100 - i, relevance_rank=i) for i in range(1, 6)]
    pool_b = [Candidate(platform="x", id=f"b{i}", text=f"本文{i}", like_count=50 - i, relevance_rank=i) for i in range(1, 6)]
    pool_b.append(Candidate(platform="x", id="a1", text="本文重複", like_count=0, relevance_rank=99))

    def _fake_search(query, max_results=5, accounts_db="accounts.db", max_retries=3):
        return pool_a if query == "q1" else pool_b

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        provider = XProvider()
        cfg = Configuration()
        cands = provider.search(["q1", "q2"], max_results=10, published_after=None, sort_by="relevance", configuration=cfg)
    ids = [c.id for c in cands]
    # search は重複排除＋取得順（関連度順）で截断するのみ。本文除外・いいね昇順は resort の責務
    assert len(cands) == 10
    assert ids.count("a1") == 1
    assert ids == [f"a{i}" for i in range(1, 6)] + [f"b{i}" for i in range(1, 6)]


def test_resort_relevance_asc_excludes_empty_text():
    cands = [
        Candidate(platform="x", id="ok1", text="本文あり", like_count=30, relevance_rank=1),
        Candidate(platform="x", id="empty1", text="", like_count=5, relevance_rank=2),
        Candidate(platform="x", id="ok2", text="本文あり2", like_count=10, relevance_rank=3),
        Candidate(platform="x", id="empty2", text="   ", like_count=1, relevance_rank=4),
    ]
    provider = XProvider()
    ordered = provider.resort(cands, "relevance")
    # 本文欠落（empty1, empty2）は除外され、残りはいいね昇順（ok2=10, ok1=30）
    assert [c.id for c in ordered] == ["ok2", "ok1"]
    assert [c.relevance_rank for c in ordered] == [1, 2]


def test_resort_likes_desc():
    cands = [
        Candidate(platform="x", id="a", text="t", like_count=10, relevance_rank=1),
        Candidate(platform="x", id="b", text="", like_count=300, relevance_rank=2),
        Candidate(platform="x", id="c", text="t", like_count=50, relevance_rank=3),
    ]
    provider = XProvider()
    ordered = provider.resort(cands, "likes")
    # likes モードは本文欠落でもいいね降順（b=300, c=50, a=10）
    assert [c.id for c in ordered] == ["b", "c", "a"]


def test_x_provider_likes_sort_top_n():
    pool = [Candidate(platform="x", id=f"t{i}", like_count=i * 5, relevance_rank=i) for i in range(1, 61)]

    def _fake_search(query, max_results=50, accounts_db="accounts.db", max_retries=3):  # type: ignore[no-untyped-def]
        return pool[:max_results]

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        provider = XProvider()
        cfg = Configuration()
        cands = provider.search(["python"], max_results=10, published_after=None, sort_by="likes", configuration=cfg)
    assert len(cands) == 10
    likes = [c.like_count for c in cands]
    assert likes == sorted(likes, reverse=True)


def test_search_tweets_requests_top_tab_and_overfetches(no_retry_sleep):
    """関連度順（Top タブ）で取得し、本文欠落分を見込んで多めに取る。"""
    calls: list[tuple[str, int, Any]] = []

    class _FakeAPI:
        def __init__(self, db):  # type: ignore[no-untyped-def]
            self.db = db

        def search(self, query, limit=5, kv=None):  # type: ignore[no-untyped-def]
            calls.append((query, limit, kv))
            return _tweet_stream([])

    with mock.patch("trend_researcher.tools.x_search.API", _FakeAPI), mock.patch(
        "trend_researcher.tools.x_search.gather", _gather
    ):
        search_tweets("テスト", max_results=5)

    assert len(calls) == 1
    assert calls[0][0] == "テスト"
    assert calls[0][2] == {"product": "Top"}
    assert calls[0][1] > 5  # ちょうど 5 件だと本文欠落時に不足する
    assert no_retry_sleep.sleeps == []  # 成功時は待機しない


def test_search_tweets_exhausts_retries_and_raises_last_error(no_retry_sleep):
    """リトライを枯渇させたら最後の例外を送出し、待機は 1/2/4 秒。"""

    class _FailingAPI:
        def __init__(self, db):  # type: ignore[no-untyped-def]
            self.db = db

        def search(self, query, limit=5, kv=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("rate limited")

    with mock.patch("trend_researcher.tools.x_search.API", _FailingAPI), mock.patch(
        "trend_researcher.tools.x_search.gather", _gather
    ), pytest.raises(RuntimeError, match="rate limited"):
        search_tweets("test", max_results=5)

    assert no_retry_sleep.sleeps == [1, 2, 4]


def test_search_tweets_recovers_after_transient_failure(no_retry_sleep):
    """一時的な失敗のあと成功すれば、例外を表に出さず結果を返す。"""
    tweets = [_fake_tweet(i) for i in range(1, 4)]
    attempts: list[str] = []

    class _FlakyAPI:
        def __init__(self, db):  # type: ignore[no-untyped-def]
            self.db = db

        def search(self, query, limit=5, kv=None):  # type: ignore[no-untyped-def]
            attempts.append(query)
            if len(attempts) == 1:
                raise RuntimeError("temporary failure")
            return _tweet_stream(tweets[:limit])

    with mock.patch("trend_researcher.tools.x_search.API", _FlakyAPI), mock.patch(
        "trend_researcher.tools.x_search.gather", _gather
    ):
        candidates = search_tweets("test", max_results=3)

    assert [c.id for c in candidates] == ["1", "2", "3"]
    assert attempts == ["test", "test"]
    assert no_retry_sleep.sleeps == [1]


def test_search_tweets_with_zero_retries_returns_empty():
    """`max_retries=0` では試行せず空リストを返す（例外も待機も発生しない）。"""
    constructed: list[str] = []

    class _FakeAPI:
        def __init__(self, db):  # type: ignore[no-untyped-def]
            constructed.append(db)

    with mock.patch("trend_researcher.tools.x_search.API", _FakeAPI):
        assert search_tweets("test", max_results=5, max_retries=0) == []
    assert constructed == ["accounts.db"]


# --- スレッド取得の縮退（tools/x_search.py・fetch_threads 経由） -------------
#
# 旧 `fetch_thread`（単数）は FR-010 で削除したため、同じ経路を 1 件の
# `fetch_threads` で通す。複数件の経路は test_fetch_threads_gathers_each_candidate。


def _threads(tweet_id: str = "100") -> Context:
    """1 件だけの `fetch_threads` 呼び出し（旧 `fetch_thread` と同一の経路）。"""
    cands = [Candidate(platform="x", id=tweet_id)]
    return fetch_threads(cands, accounts_db=":memory:")[0]


def test_fetch_threads_reads_main_parent_and_replies():
    main = _fake_tweet(
        100,
        raw_content="メインの本文",
        in_reply_to=99,
        like_count=11,
        retweet_count=2,
        reply_count=1,
        quote_count=0,
    )
    api = _ThreadAPI(
        details={100: main, 99: _fake_tweet(99, raw_content="親ツイートの本文")},
        replies=[_fake_tweet(101, raw_content="リプライ1"), _fake_tweet(102, raw_content="")],
    )
    with _install_thread_api(api), mock.patch("trend_researcher.tools.x_search.gather", _gather):
        ctx = _threads()

    assert ctx.id == "100"
    assert ctx.text == "メインの本文"
    assert ctx.thread_text == "親ツイートの本文"
    # 空本文のリプライは採用しない
    assert ctx.replies == ["リプライ1"]
    assert ctx.counts == {"like_count": 11, "retweet_count": 2, "reply_count": 1, "quote_count": 0}
    assert api.detail_ids == [100, 99]
    assert api.reply_calls == [(100, 3)]


def test_fetch_threads_without_parent_keeps_thread_text_none():
    api = _ThreadAPI(details={100: _fake_tweet(100, raw_content="単独の本文")})
    with _install_thread_api(api), mock.patch("trend_researcher.tools.x_search.gather", _gather):
        ctx = _threads()
    assert ctx.text == "単独の本文"
    # 親が無い場合は thread_text を埋めない（Context の既定は空文字）
    assert ctx.thread_text == ""
    assert api.detail_ids == [100]


def test_fetch_threads_keeps_whitespace_only_reply_as_empty_string():
    """空白のみのリプライは「本文あり」と判定され、空文字として残る（現状の挙動）。

    除外判定は `rawContent` の真偽のみを見ており、`strip` 後の空文字は除外しない。
    下流（analyze_content）では空行になるだけで実害はないため、挙動を固定する。
    """
    api = _ThreadAPI(
        details={100: _fake_tweet(100, raw_content="本文")},
        replies=[_fake_tweet(101, raw_content="  \n ")],
    )
    with _install_thread_api(api), mock.patch("trend_researcher.tools.x_search.gather", _gather):
        ctx = _threads()
    assert ctx.replies == [""]


def test_fetch_threads_degrades_when_details_raise():
    """元ツイート取得の例外は握りつぶし、空の Context を返す（呼び出し元は本文のみで解析）。"""
    api = _ThreadAPI(errors={100: RuntimeError("404")})
    with _install_thread_api(api), mock.patch("trend_researcher.tools.x_search.gather", _gather):
        ctx = _threads()
    assert ctx.id == "100"
    assert ctx.text == ""
    assert ctx.counts is None
    assert ctx.replies == []


def test_fetch_threads_degrades_when_details_return_none():
    api = _ThreadAPI(details={100: None})
    with _install_thread_api(api), mock.patch("trend_researcher.tools.x_search.gather", _gather):
        ctx = _threads()
    assert ctx.text == ""
    assert ctx.counts is None


def test_fetch_threads_degrades_when_parent_lookup_fails():
    """親ツイートだけ取得できなくても、元ツイート本文は保持する。"""
    api = _ThreadAPI(
        details={100: _fake_tweet(100, raw_content="元ツイート", in_reply_to=99)},
        errors={99: RuntimeError("親が削除済み")},
    )
    with _install_thread_api(api), mock.patch("trend_researcher.tools.x_search.gather", _gather):
        ctx = _threads()
    assert ctx.text == "元ツイート"
    assert ctx.thread_text == ""
    assert api.detail_ids == [100, 99]


def test_fetch_threads_degrades_when_replies_raise():
    api = _ThreadAPI(
        details={100: _fake_tweet(100, raw_content="元ツイート")},
        replies_error=RuntimeError("replies unavailable"),
    )
    with _install_thread_api(api), mock.patch("trend_researcher.tools.x_search.gather", _gather):
        ctx = _threads()
    assert ctx.text == "元ツイート"
    assert ctx.replies == []


def test_fetch_threads_logs_and_degrades_on_http_error(caplog):
    """twscrape の通信系（`HttpError`）は縮退し、握り潰さず WARNING に残す（#47）。

    捕まえる型から `HttpError` を外すと例外が伝播して失敗し、ログ出力を `pass`
    へ戻すと caplog の検証で失敗する（S110 / BLE001 の是正を固定する）。
    """
    api = _ThreadAPI(errors={100: HttpError("502 Bad Gateway")})
    with (
        caplog.at_level(logging.WARNING, logger="trend_researcher.tools.x_search"),
        _install_thread_api(api),
        mock.patch("trend_researcher.tools.x_search.gather", _gather),
    ):
        ctx = _threads()

    assert ctx.id == "100"
    assert ctx.text == ""
    assert ctx.counts is None
    assert "ツイート本文の取得に失敗" in caplog.text
    assert "tweet_id=100" in caplog.text


def test_fetch_threads_logs_and_degrades_on_parent_lookup_error(caplog):
    """親ツイートの取得失敗（`HandledError`）も縮退し、WARNING に残す（#47）。

    元ツイート本文は保持したまま `thread_text` だけを諦める。
    """
    api = _ThreadAPI(
        details={100: _fake_tweet(100, raw_content="元ツイート", in_reply_to=99)},
        errors={99: HandledError("親が削除済み")},
    )
    with (
        caplog.at_level(logging.WARNING, logger="trend_researcher.tools.x_search"),
        _install_thread_api(api),
        mock.patch("trend_researcher.tools.x_search.gather", _gather),
    ):
        ctx = _threads()

    assert ctx.text == "元ツイート"
    assert ctx.thread_text == ""
    assert api.detail_ids == [100, 99]
    assert "親ツイートの取得に失敗" in caplog.text
    assert "tweet_id=99" in caplog.text


def test_fetch_threads_degrades_on_no_account_error_for_replies(caplog):
    """アカウント枯渇（`NoAccountError`）でもリプライだけ諦めて本文は保持する（#47）。"""
    api = _ThreadAPI(
        details={100: _fake_tweet(100, raw_content="元ツイート")},
        replies_error=NoAccountError("No account available for queue TweetDetails"),
    )
    with (
        caplog.at_level(logging.WARNING, logger="trend_researcher.tools.x_search"),
        _install_thread_api(api),
        mock.patch("trend_researcher.tools.x_search.gather", _gather),
    ):
        ctx = _threads()

    assert ctx.text == "元ツイート"
    assert ctx.replies == []
    assert "リプライの取得に失敗" in caplog.text


def test_fetch_threads_propagates_error_types_outside_the_degradation_list():
    """列挙した型の外は縮退させない（実装バグを握り潰さない・#47）。

    素の `except Exception` へ戻すと本テストは失敗する（`KeyError` が吸われる）。
    """
    api = _ThreadAPI(
        details={100: _fake_tweet(100, raw_content="元ツイート")},
        replies_error=KeyError("実装バグ相当"),
    )
    with (
        _install_thread_api(api),
        mock.patch("trend_researcher.tools.x_search.gather", _gather),
        pytest.raises(KeyError),
    ):
        _threads()


def test_fetch_threads_returns_empty_for_no_candidates():
    assert fetch_threads([]) == []


def test_fetch_threads_gathers_each_candidate():
    api = _ThreadAPI(
        details={
            11: _fake_tweet(11, raw_content="本文11"),
            12: _fake_tweet(12, raw_content="本文12"),
        }
    )
    cands = [Candidate(platform="x", id="11"), Candidate(platform="x", id="12")]
    with _install_thread_api(api), mock.patch("trend_researcher.tools.x_search.gather", _gather):
        contexts = fetch_threads(cands, accounts_db=":memory:")
    assert [c.id for c in contexts] == ["11", "12"]
    assert [c.text for c in contexts] == ["本文11", "本文12"]


# --- 選定基準と重複排除（providers/x.py, FR-024） -------------------------


def test_x_provider_appends_since_to_every_query():
    """`published_after` は X ネイティブの `since:` として各クエリに付く。"""
    queries: list[str] = []

    def _fake_search(query, max_results=5, accounts_db="accounts.db", max_retries=3):  # type: ignore[no-untyped-def]
        queries.append(query)
        return []

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        XProvider().search(
            ["q1", "q2"],
            max_results=5,
            published_after=datetime(2026, 1, 2, 6, 30, tzinfo=UTC),
            sort_by="relevance",
            configuration=Configuration(),
        )
    assert queries == ["q1 since:2026-01-02", "q2 since:2026-01-02"]


def test_x_provider_relevance_pool_size_and_retries_come_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, int]] = []

    def _fake_search(query, max_results=5, accounts_db="accounts.db", max_retries=3):  # type: ignore[no-untyped-def]
        calls.append((query, max_results, max_retries))
        return []

    monkeypatch.setenv("XTR_MAX_RETRIES", "2")

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        XProvider().search(
            ["q1"],
            max_results=5,
            published_after=None,
            sort_by="relevance",
            configuration=Configuration(),
        )
    # likes 用の search_pool_size(50) は使わず、relevance は小さめのバッファに留める
    assert calls == [("q1", max(5 * 3, 5 + 20), 2)]


def test_x_provider_likes_pool_size_is_at_least_max_results():
    calls: list[tuple[str, int]] = []

    def _fake_search(query, max_results=5, accounts_db="accounts.db", max_retries=3):  # type: ignore[no-untyped-def]
        calls.append((query, max_results))
        return []

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        XProvider().search(
            ["q1", "q2"],
            max_results=80,
            published_after=None,
            sort_by="likes",
            configuration=Configuration(),
        )
    assert calls == [("q1", 80), ("q2", 80)]


def test_x_provider_relevance_dedupe_keeps_first_occurrence():
    """FR-024: 同一 id は先に取得したものを残す（後発で上書きしない）。"""
    first = Candidate(platform="x", id="dup", text="先に取得した本文", like_count=1, relevance_rank=1)
    later = Candidate(platform="x", id="dup", text="後から取得した本文", like_count=9, relevance_rank=2)

    def _fake_search(query, max_results=5, accounts_db="accounts.db", max_retries=3):  # type: ignore[no-untyped-def]
        return [first, later] if query == "q1" else [later]

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        cands = XProvider().search(
            ["q1", "q2"], max_results=5, published_after=None, sort_by="relevance", configuration=Configuration()
        )
    assert [c.text for c in cands] == ["先に取得した本文"]
    assert [c.like_count for c in cands] == [1]


def test_x_provider_relevance_truncates_after_dedupe():
    """FR-024: 截断は重複除去の**後**（先に截断すると枠を重複が食う）。"""
    pool = [
        Candidate(platform="x", id="a1", text="t1", relevance_rank=1),
        Candidate(platform="x", id="a1", text="t1-dup", relevance_rank=2),
        Candidate(platform="x", id="a2", text="t2", relevance_rank=3),
        Candidate(platform="x", id="a3", text="t3", relevance_rank=4),
        Candidate(platform="x", id="a4", text="t4", relevance_rank=5),
    ]

    def _fake_search(query, max_results=5, accounts_db="accounts.db", max_retries=3):  # type: ignore[no-untyped-def]
        return pool

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        cands = XProvider().search(
            ["q1"], max_results=4, published_after=None, sort_by="relevance", configuration=Configuration()
        )
    assert [c.id for c in cands] == ["a1", "a2", "a3", "a4"]


def test_x_provider_likes_dedupes_pool_before_sorting():
    """likes モードも複数クエリの重複を取得順の先勝ちで除去する（FR-024）。

    除去をソート後に行うと、先勝ちの保証が崩れて後発の値が残る（マージ禁止）。
    """
    pool_q1 = [
        Candidate(platform="x", id="a1", text="q1 の本文", like_count=10, relevance_rank=1),
        Candidate(platform="x", id="a2", text="q2", like_count=8, relevance_rank=2),
    ]
    pool_q2 = [
        Candidate(platform="x", id="b1", text="b1", like_count=30, relevance_rank=1),
        Candidate(platform="x", id="a1", text="q2 の本文", like_count=999, relevance_rank=2),
    ]

    def _fake_search(query, max_results=5, accounts_db="accounts.db", max_retries=3):  # type: ignore[no-untyped-def]
        return pool_q1 if query == "q1" else pool_q2

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        cands = XProvider().search(
            ["q1", "q2"], max_results=10, published_after=None, sort_by="likes", configuration=Configuration()
        )
    ids = [c.id for c in cands]
    # 重複が除去され、いいね降順（b1=30, a1=10, a2=8）
    assert ids == ["b1", "a1", "a2"]
    assert len(ids) == len(set(ids))
    # 先勝ち: a1 は q1 側の値のまま（後発の 999 で上書き・マージしない）
    assert cands[1].like_count == 10
    assert cands[1].text == "q1 の本文"


def test_resort_relevance_keeps_rank_order_on_tie():
    """いいね数が同じ場合は取得時の relevance_rank 順を維持する。"""
    cands = [
        Candidate(platform="x", id="b", text="t", like_count=5, relevance_rank=2),
        Candidate(platform="x", id="a", text="t", like_count=5, relevance_rank=1),
    ]
    assert [c.id for c in XProvider().resort(cands, "relevance")] == ["a", "b"]


# --- コンテキスト取得と縮退（providers/x.py） -----------------------------


def test_x_provider_fetch_contexts_returns_empty_without_candidates():
    assert XProvider().fetch_contexts([], Configuration()) == ([], [])


def test_x_provider_fetch_contexts_overwrites_counts_from_details():
    """検索結果の like_count は 0 埋めされることがあるため、詳細取得で上書きする。"""
    cands = [Candidate(platform="x", id="1", text="本文", like_count=0)]
    contexts = [
        Context(
            id="1",
            text="本文",
            counts={"like_count": 42, "retweet_count": 3, "reply_count": 1, "quote_count": 0},
        )
    ]
    with mock.patch("trend_researcher.providers.x.fetch_threads", return_value=contexts):
        out, notes = XProvider().fetch_contexts(cands, Configuration())

    assert notes == []
    assert out is contexts
    assert cands[0].like_count == 42
    assert cands[0].retweet_count == 3
    assert cands[0].reply_count == 1
    assert cands[0].quote_count == 0


def test_x_provider_fetch_contexts_degrades_to_candidate_text():
    """スレッド取得に失敗したら本文のみで解析を続け、理由を notes に残す。"""
    cands = [Candidate(platform="x", id="1", text="本文", like_count=5)]
    with mock.patch(
        "trend_researcher.providers.x.fetch_threads", side_effect=RuntimeError("threads down")
    ):
        contexts, notes = XProvider().fetch_contexts(cands, Configuration())

    assert len(contexts) == 1
    assert contexts[0].id == "1"
    assert contexts[0].text == "本文"
    assert len(notes) == 1
    assert "スレッド取得に失敗しました" in notes[0]
    assert "threads down" in notes[0]
    # 失敗時はカウントを上書きしない（検索結果の値を保持）
    assert cands[0].like_count == 5


# --- 描画（providers/x.py） -----------------------------------------------


def test_x_provider_table_header_columns_align():
    head, sep = XProvider().candidate_table_header()
    assert head.startswith("| # | 本文抜粋 |")
    assert head.endswith("| URL |")
    assert len(head.split("|")) == len(sep.split("|"))


def test_x_provider_render_candidate_row_formats_numbers_and_snippet():
    snippet_src = "改行\nを含む長い本文"
    c = Candidate(
        platform="x",
        id="1",
        text=snippet_src + "あ" * 60,
        url="https://x.com/u/status/1",
        author_handle="user1",
        author_name="User One",
        like_count=12345,
        retweet_count=None,
        quote_count=7,
        relevance_rank=2,
    )
    cells = [cell.strip() for cell in XProvider().render_candidate_row(c).split("|")]
    assert cells[1] == "2"
    assert cells[2] == (snippet_src.replace("\n", " ") + "あ" * 60)[:50]
    assert len(cells[2]) == 50
    assert cells[3] == "@user1"
    assert cells[4] == "12,345"
    assert cells[5] == "-"  # 未取得の RT は "-"
    assert cells[6] == "7"
    assert cells[7] == "https://x.com/u/status/1"


def test_x_provider_render_candidate_row_falls_back_to_author_name():
    c = Candidate(platform="x", id="1", text="t", url="u", author_name="表示名", relevance_rank=1)
    assert "表示名" in XProvider().render_candidate_row(c)


def test_x_provider_render_block_title_prefers_handle():
    provider = XProvider()
    assert (
        provider.render_block_title(
            Candidate(platform="x", id="1", author_handle="u1", relevance_rank=3)
        )
        == "### 3. @u1 のツイート"
    )
    assert (
        provider.render_block_title(
            Candidate(platform="x", id="1", author_name="表示名", relevance_rank=1)
        )
        == "### 1. @表示名 のツイート"
    )


def test_x_provider_render_block_meta_omits_missing_fields():
    provider = XProvider()
    full = provider.render_block_meta(
        Candidate(
            platform="x",
            id="1",
            author_name="名前",
            author_followers=1234,
            like_count=10,
            retweet_count=2,
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            relevance_rank=1,
        )
    )
    assert full == ["投稿者: 名前", "フォロワー: 1,234", "いいね: 10", "RT: 2", "公開日: 2026-01-01"]
    assert provider.render_block_meta(Candidate(platform="x", id="2", relevance_rank=1)) == []


def test_x_provider_exposes_prompts_and_supporting_label():
    from trend_researcher.prompts import X_EXTRACT_COMMON_PROMPT, X_PLAN_SEARCH_PROMPT

    provider = XProvider()
    assert provider.name == "x"
    assert provider.plan_search_prompt == X_PLAN_SEARCH_PROMPT
    assert provider.extract_common_prompt == X_EXTRACT_COMMON_PROMPT
    assert provider.common_theme_supporting_label == "該当ツイート"
    assert provider.parse_instruction_prompt


# --- X 固有設定の解決（providers/x.py, SET-003） -------------------------


def test_x_settings_defaults_use_repository_root() -> None:
    settings = XProvider().settings(Configuration())

    assert isinstance(settings, XSettings)
    assert settings.accounts_db == (_REPO_ROOT / "accounts.db").resolve()
    assert settings.search_pool_size == 50
    assert settings.max_retries == 3


def test_x_settings_use_platform_prefix_and_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """`XTR_*` は X でだけ読まれ、相対パスはリポジトリ直下基準で解決される。"""
    monkeypatch.setenv("XTR_ACCOUNTS_DB", "data/accounts.db")
    monkeypatch.setenv("XTR_SEARCH_POOL_SIZE", "80")
    monkeypatch.setenv("XTR_MAX_RETRIES", "1")

    settings = XProvider().settings(Configuration())

    assert settings.accounts_db == (_REPO_ROOT / "data/accounts.db").resolve()
    assert settings.search_pool_size == 80
    assert settings.max_retries == 1


def test_x_settings_prefer_generic_over_platform_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TR_SEARCH_POOL_SIZE", "70")
    monkeypatch.setenv("XTR_SEARCH_POOL_SIZE", "80")

    assert XProvider().settings(Configuration()).search_pool_size == 70


def test_x_settings_ignore_youtube_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTR_ACCOUNTS_DB", "youtube.db")

    settings = XProvider().settings(Configuration())

    assert settings.accounts_db == (_REPO_ROOT / "accounts.db").resolve()


def test_x_settings_ignore_empty_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_SEARCH_POOL_SIZE", "")

    assert XProvider().settings(Configuration()).search_pool_size == 50


def test_x_settings_prefer_explicit_configuration_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同名フィールドが明示指定されていれば環境変数より優先する（SET-006）。

    現行の `Configuration` は X 固有の 3 項目を持たない（同名項目の定義を 2 箇所に
    しない。SET-001 / SET-005）ため、同名フィールドを持つ派生型で規則を固定する。
    """

    class _WithPoolSize(Configuration):
        search_pool_size: int = 0

    monkeypatch.setenv("XTR_SEARCH_POOL_SIZE", "80")

    explicit = _WithPoolSize(search_pool_size=60)

    assert "search_pool_size" in explicit.model_fields_set
    assert XProvider().settings(explicit).search_pool_size == 60
