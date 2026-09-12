"""tools/x_search.py の単体テスト（twscrape をモック、Candidate モデル）。"""

from datetime import datetime, timezone
from unittest import mock

from twscrape import Tweet, User

from trend_researcher.models import Candidate
from trend_researcher.providers.x import XProvider, _sort_by_likes
from trend_researcher.tools.x_search import _tweet_to_candidate, search_tweets


def _fake_tweet(tid: int) -> Tweet:
    user = User(
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
        created=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    return Tweet(
        id=tid,
        id_str=str(tid),
        url=f"https://x.com/user{tid}/status/{tid}",
        date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rawContent=f"ツイート本文 {tid}",
        lang="ja",
        conversationId=tid,
        conversationIdStr=str(tid),
        cashtags=[],
        likeCount=tid * 3,
        retweetCount=tid * 2,
        replyCount=tid,
        quoteCount=tid,
        isQuoteStatus=False,
        retweetedTweet=None,
        quotedTweet=None,
        mentionedUsers=[],
        hashtags=[],
        links=[],
        media=[],
        viewCount=None,
        bookmarkedCount=None,
        user=user,
        source=None,
        inReplyToTweetId=None,
    )


def test_tweet_to_candidate_mapping():
    t = _fake_tweet(42)
    c = _tweet_to_candidate(t, rank=1)
    assert isinstance(c, Candidate)
    assert c.id == "42"
    assert c.author_handle == "user42"
    assert c.like_count == 126
    assert c.retweet_count == 84
    assert c.relevance_rank == 1


def test_search_tweets_top_n():
    tweets = [_fake_tweet(i) for i in range(1, 8)]

    class _FakeAPI:
        def __init__(self, db):
            pass

        async def search(self, query, limit=5, kv=None):
            for t in tweets[:limit]:
                yield t

    async def _fake_gather(gen):
        out = []
        async for x in gen:
            out.append(x)
        return out

    with mock.patch("trend_researcher.tools.x_search.API", _FakeAPI), \
         mock.patch("trend_researcher.tools.x_search.gather", _fake_gather):
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
    from trend_researcher.config import Config

    pool_a = [Candidate(platform="x", id=f"a{i}", text=f"本文{i}", like_count=100 - i, relevance_rank=i) for i in range(1, 6)]
    pool_b = [Candidate(platform="x", id=f"b{i}", text=f"本文{i}", like_count=50 - i, relevance_rank=i) for i in range(1, 6)]
    pool_b.append(Candidate(platform="x", id="a1", text="本文重複", like_count=0, relevance_rank=99))

    def _fake_search(query, max_results=5, accounts_db="accounts.db", max_retries=3):
        return pool_a if query == "q1" else pool_b

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        provider = XProvider()
        cfg = Config()
        cands = provider.search(["q1", "q2"], max_results=10, published_after=None, sort_by="relevance", config=cfg)
    ids = [c.id for c in cands]
    # search は重複排除＋取得順（関連度順）で截断するのみ。本文除外・いいね昇順は resort の責務
    assert len(cands) == 10
    assert ids.count("a1") == 1
    assert ids == [f"a{i}" for i in range(1, 6)] + [f"b{i}" for i in range(1, 6)]


def test_resort_relevance_asc_excludes_empty_text():
    from trend_researcher.config import Config

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
    from trend_researcher.config import Config

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
    from trend_researcher.config import Config

    pool = [Candidate(platform="x", id=f"t{i}", like_count=i * 5, relevance_rank=i) for i in range(1, 61)]

    def _fake_search(query, max_results=50, accounts_db="accounts.db", max_retries=3):
        return pool[:max_results]

    with mock.patch("trend_researcher.providers.x.search_tweets", _fake_search):
        provider = XProvider()
        cfg = Config(search_pool_size=50)
        cands = provider.search(["python"], max_results=10, published_after=None, sort_by="likes", config=cfg)
    assert len(cands) == 10
    likes = [c.like_count for c in cands]
    assert likes == sorted(likes, reverse=True)
