"""`tools/youtube_search.py` と YouTube provider の単体テスト（yt-dlp はモック）。

固定する契約:

- `upload_date` の解釈（欠落・桁不足・不正な日付は例外にせず `None`）
- 投稿日下限フィルタは「下限のみ」。未来日付や投稿日不明の動画は落とさない
- 取得元 URL とチャンネル名のフォールバック、`id` 欠落への耐性
- 件数上限（`max_results`）とフィルタ時の過剰取得
- FR-024 の非対称: YouTube は単一クエリ検索のため重複除去を行わない
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from trend_researcher.config import Config
from trend_researcher.models import Candidate
from trend_researcher.providers.youtube import YouTubeProvider
from trend_researcher.tools.transcript import Transcript
from trend_researcher.tools.youtube_search import (
    _entry_to_candidate,
    _parse_upload_date,
    search_videos,
)


def _fake_extract_info(url, download=False):
    return {
        "entries": [
            {
                "id": f"vid{i}",
                "title": f"動画 {i}",
                "url": f"https://www.youtube.com/watch?v=vid{i}",
                "channel": f"チャンネル{i}",
                "channel_id": f"ch{i}",
                "upload_date": "20260101",
                "view_count": 1000 * i,
                "like_count": 10 * i,
            }
            for i in range(1, 8)
        ]
    }


def test_search_videos_returns_top_n_and_respects_max_results():
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        extract = ydl_mock.return_value.__enter__.return_value.extract_info
        extract.side_effect = _fake_extract_info
        top = search_videos("テスト", max_results=5)
        limited = search_videos("テスト", max_results=3)

    assert len(top) == 5
    assert len(limited) == 3
    assert all(isinstance(c, Candidate) for c in top)
    assert [c.relevance_rank for c in top] == [1, 2, 3, 4, 5]
    assert top[0].id == "vid1"
    assert top[0].view_count == 1000
    assert top[0].like_count == 10
    assert top[0].published_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert top[0].author_name == "チャンネル1"
    assert top[0].channel_id == "ch1"
    assert top[0].url == "https://www.youtube.com/watch?v=vid1"
    assert limited == top[:3]


def _fake_extract_info_mixed_dates(url, download=False):
    dates = ["20260601", "20240101", "20260615", "20240115", "20260701"]
    return {
        "entries": [
            {
                "id": f"vid{i}",
                "title": f"動画 {i}",
                "url": f"https://www.youtube.com/watch?v=vid{i}",
                "channel": f"チャンネル{i}",
                "channel_id": f"ch{i}",
                "upload_date": dates[i - 1],
                "view_count": 1000 * i,
                "like_count": 10 * i,
            }
            for i in range(1, 6)
        ]
    }


def test_search_videos_published_after_filter():
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _fake_extract_info_mixed_dates
        candidates = search_videos("テスト", max_results=10, published_after=datetime(2025, 1, 1, tzinfo=UTC))
    assert len(candidates) == 3
    assert all(c.published_at >= datetime(2025, 1, 1, tzinfo=UTC) for c in candidates)


def test_search_videos_published_after_overfetch():
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _fake_extract_info_mixed_dates
        candidates = search_videos("テスト", max_results=2, published_after=datetime(2025, 1, 1, tzinfo=UTC))
    assert len(candidates) == 2
    call_arg = ydl_mock.return_value.__enter__.return_value.extract_info.call_args[0][0]
    assert "ytsearch" in call_arg
    n = int(call_arg.split("ytsearch")[1].split(":")[0])
    assert n >= 6


# --- upload_date の解釈 ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20260101", datetime(2026, 1, 1, tzinfo=UTC)),
        (None, None),
        ("", None),
        ("2026", None),  # 8 桁でない
        ("2026011", None),  # 7 桁
        ("abcdefgh", None),  # 8 桁だが数値でない
        ("20261301", None),  # 月が範囲外
        ("20260230", None),  # 日が範囲外
    ],
)
def test_parse_upload_date_degrades_to_none(raw, expected):
    """解釈できない投稿日は例外にせず `None`（呼び出し側は日付フィルタを素通りさせる）。"""
    assert _parse_upload_date(raw) == expected


def test_entry_to_candidate_fills_defaults_for_missing_fields():
    c = _entry_to_candidate({"id": "vid1"}, rank=2)
    assert c.id == "vid1"
    assert c.url == "https://www.youtube.com/watch?v=vid1"
    assert c.title == ""
    assert c.author_name == ""
    assert c.channel_id == ""
    assert c.published_at is None
    assert c.view_count is None
    assert c.like_count is None
    assert c.relevance_rank == 2


def test_entry_to_candidate_prefers_webpage_url_and_falls_back_to_uploader():
    c = _entry_to_candidate(
        {"id": "v", "webpage_url": "https://youtu.be/v", "uploader": "チャンネル名"}, rank=1
    )
    assert c.url == "https://youtu.be/v"
    assert c.author_name == "チャンネル名"


def test_entry_to_candidate_without_id_keeps_empty_id():
    c = _entry_to_candidate({}, rank=1)
    assert c.id == ""
    assert c.url == "https://www.youtube.com/watch?v="


def test_search_videos_skips_falsy_entries_and_keeps_positional_rank():
    """空エントリは飛ばすが、`relevance_rank` は yt-dlp が返した位置を保つ。"""

    def _info(url, download=False):  # type: ignore[no-untyped-def]
        return {
            "entries": [
                None,
                {"id": "vid1", "title": "A"},
                {},
                {"id": "vid2", "title": "B"},
            ]
        }

    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _info
        candidates = search_videos("テスト", max_results=5)

    assert [c.id for c in candidates] == ["vid1", "vid2"]
    assert [c.relevance_rank for c in candidates] == [2, 4]


def test_search_videos_filter_keeps_future_upload_dates():
    """投稿日フィルタは下限のみ。未来日付を弾く上限判定は無い（現状の挙動）。"""
    future = (datetime.now(UTC) + timedelta(days=365)).strftime("%Y%m%d")

    def _info(url, download=False):  # type: ignore[no-untyped-def]
        return {"entries": [{"id": "future", "upload_date": future}]}

    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _info
        candidates = search_videos("テスト", max_results=5, published_after=datetime(2025, 1, 1, tzinfo=UTC))

    assert [c.id for c in candidates] == ["future"]
    assert candidates[0].published_at is not None
    assert candidates[0].published_at > datetime.now(UTC)


def test_search_videos_filter_keeps_entries_without_upload_date():
    """投稿日が不明な動画は下限フィルタで落とさない（判定材料が無いため）。"""

    def _info(url, download=False):  # type: ignore[no-untyped-def]
        return {
            "entries": [
                {"id": "unknown", "upload_date": None},
                {"id": "too-old", "upload_date": "20240101"},
            ]
        }

    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _info
        candidates = search_videos("テスト", max_results=5, published_after=datetime(2025, 1, 1, tzinfo=UTC))

    assert [c.id for c in candidates] == ["unknown"]


def test_search_videos_does_not_dedupe_ids():
    """FR-024 の非対称: YouTube は単一クエリ検索のため重複除去を行わない。"""

    def _info(url, download=False):  # type: ignore[no-untyped-def]
        return {"entries": [{"id": "vid1"}, {"id": "vid1"}]}

    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _info
        candidates = search_videos("テスト", max_results=5)

    assert [c.id for c in candidates] == ["vid1", "vid1"]


# --- provider 側の契約（providers/youtube.py） ----------------------------


def test_youtube_provider_searches_only_the_first_query():
    """plan_search は 1 クエリしか作らないため、provider も先頭のみを使う。"""
    calls: list[tuple[str, int]] = []

    def _fake_search(query, max_results=5, published_after=None):  # type: ignore[no-untyped-def]
        calls.append((query, max_results))
        return []

    with mock.patch("trend_researcher.providers.youtube.search_videos", _fake_search):
        YouTubeProvider().search(
            ["q1", "q2"], max_results=7, published_after=None, sort_by="relevance", config=Config()
        )
    assert calls == [("q1", 7)]


def test_youtube_provider_searches_empty_query_when_no_queries():
    queries: list[str] = []

    def _fake_search(query, max_results=5, published_after=None):  # type: ignore[no-untyped-def]
        queries.append(query)
        return []

    with mock.patch("trend_researcher.providers.youtube.search_videos", _fake_search):
        YouTubeProvider().search(
            [], max_results=5, published_after=None, sort_by="relevance", config=Config()
        )
    assert queries == [""]


def test_youtube_provider_passes_published_after():
    """YouTube は検索 API の期間フィルタを使うため、provider がそのまま渡す。"""
    seen: list[datetime | None] = []

    def _fake_search(query, max_results=5, published_after=None):  # type: ignore[no-untyped-def]
        seen.append(published_after)
        return []

    bound = datetime(2025, 6, 1, tzinfo=UTC)
    with mock.patch("trend_researcher.providers.youtube.search_videos", _fake_search):
        YouTubeProvider().search(
            ["q1"], max_results=5, published_after=bound, sort_by="relevance", config=Config()
        )
    assert seen == [bound]


def test_youtube_provider_resort_keeps_order_and_identity():
    """YouTube は検索結果が関連度順のため、再ソートは同一リストを返す。"""
    cands = [
        Candidate(platform="youtube", id="v1", relevance_rank=1),
        Candidate(platform="youtube", id="v2", relevance_rank=2),
    ]
    out = YouTubeProvider().resort(cands, "relevance")
    assert out is cands
    # X と違い likes モードでも順序を変えない（--sort は X 専用）
    assert YouTubeProvider().resort(cands, "likes") is cands


def test_youtube_provider_fetch_contexts_notes_missing_transcript():
    """字幕が取れない動画はメタデータのみで解析を続け、notes に残す。"""
    cands = [Candidate(platform="youtube", id="v1", title="タイトル1")]
    transcript = Transcript(video_id="v1", language="ja", text="   ")
    with mock.patch("trend_researcher.providers.youtube.fetch_transcript", return_value=transcript):
        contexts, notes = YouTubeProvider().fetch_contexts(cands, Config())

    assert [c.id for c in contexts] == ["v1"]
    assert contexts[0].text == "   "
    assert notes == ["字幕取得不可: タイトル1 (v1) - メタデータのみで解析"]


def test_youtube_provider_fetch_contexts_uses_transcript_language_from_config():
    langs: list[str] = []

    def _fake_transcript(video_id, language="ja"):  # type: ignore[no-untyped-def]
        langs.append(language)
        return Transcript(video_id=video_id, language=language, text="字幕")

    cands = [Candidate(platform="youtube", id="v1", title="タイトル1")]
    with mock.patch("trend_researcher.providers.youtube.fetch_transcript", _fake_transcript):
        contexts, notes = YouTubeProvider().fetch_contexts(
            cands, Config(transcript_language="en")
        )

    assert langs == ["en"]
    assert contexts[0].text == "字幕"
    assert notes == []
