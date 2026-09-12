"""tools/youtube_search.py の単体テスト（yt-dlp をモック、Candidate モデル）。"""

from datetime import UTC, datetime
from unittest import mock

from trend_researcher.models import Candidate
from trend_researcher.tools.youtube_search import search_videos


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


def test_search_videos_top_n():
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _fake_extract_info
        candidates = search_videos("テスト", max_results=5)

    assert len(candidates) == 5
    assert all(isinstance(c, Candidate) for c in candidates)
    assert candidates[0].id == "vid1"
    assert candidates[0].relevance_rank == 1
    assert candidates[0].view_count == 1000
    assert candidates[0].published_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert candidates[0].url == "https://www.youtube.com/watch?v=vid1"


def test_search_videos_limits_to_max():
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _fake_extract_info
        candidates = search_videos("テスト", max_results=3)
    assert len(candidates) == 3


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
