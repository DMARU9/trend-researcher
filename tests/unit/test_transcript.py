"""`tools/transcript.py` の単体テスト（yt-dlp はモック）。

固定する契約:

- 字幕の優先順位（手動字幕 > 自動字幕）と、要求言語が無い場合の先頭言語への
  フォールバック
- `requested_subtitles` の欠落・空文字・空白のみの字幕は例外にせず空文字で縮退する
- `DownloadError` と `info` 非辞書（部分応答）でも空文字で縮退する
- 字幕ファイルの形式判定（VTT / json3）とインラインタグ・タイムスタンプの除去
- json3 の解析（`data.events` 経由とファイル経由の両方）
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest import mock

import pytest
import yt_dlp

from trend_researcher.models import TranscriptSource
from trend_researcher.tools.transcript import (
    _load_json,
    _parse_json3,
    _parse_vtt,
    _read_subtitle_file,
    fetch_transcript,
)


def _write_sub_file(content: str, suffix: str = ".vtt") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="tr_t_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _fake_info_with_requested_subs(url, download=False):
    ja_path = _write_sub_file(
        "WEBVTT\nKind: captions\nLanguage: ja\n\n"
        "00:00:01.000 --> 00:00:02.000\n皆<00:00:01.500><c>さん</c>、こんにちは\n"
    )
    return {
        "subtitles": {"ja": [{"ext": "vtt", "url": "http://sub.example/ja"}]},
        "automatic_captions": {"en": [{"ext": "vtt", "url": "http://sub.example/en"}]},
        "requested_subtitles": {
            "ja": {"ext": "vtt", "filepath": ja_path},
        },
    }


def _fake_info_only_auto(url, download=False):
    en_path = _write_sub_file(
        "WEBVTT\nKind: captions\nLanguage: en\n\n"
        "00:00:01.000 --> 00:00:02.000\nHello world\n"
    )
    return {
        "subtitles": {},
        "automatic_captions": {"en": [{"ext": "vtt", "url": "http://sub.example/en"}]},
        "requested_subtitles": {
            "en": {"ext": "vtt", "filepath": en_path},
        },
    }


def _fake_info_no_subs(url, download=False):
    return {"subtitles": {}, "automatic_captions": {}, "requested_subtitles": {}}


def test_fetch_transcript_caption_preferred():
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _fake_info_with_requested_subs
        t = fetch_transcript("vid1", language="ja")
    assert t.source == TranscriptSource.CAPTION
    assert t.language == "ja"
    assert "皆さん、こんにちは" in t.text


def test_fetch_transcript_fallback_to_auto():
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _fake_info_only_auto
        t = fetch_transcript("vid1", language="ja")
    assert t.source == TranscriptSource.AUTOMATIC_CAPTION
    assert "Hello world" in t.text


def test_fetch_transcript_fallback_empty():
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _fake_info_no_subs
        t = fetch_transcript("vid1", language="ja")
    assert t.text == ""
    assert t.source == TranscriptSource.AUTOMATIC_CAPTION


def test_parse_vtt_removes_inline_tags():
    raw = (
        "WEBVTT\nKind: captions\nLanguage: ja\n\n"
        "00:00:00.320 --> 00:00:02.149 align:start position:0%\n"
        "皆<00:00:00.520><c>さん</c>、エージェントは使っていますか\n"
    )
    assert _parse_vtt(raw) == "皆さん、エージェントは使っていますか"


def test_parse_vtt_drops_headers_and_timestamps_without_separators():
    """WEBVTT / Kind / Language / タイムスタンプ行はテキストに混ぜない。"""
    raw = (
        "WEBVTT\nKind: captions\nLanguage: ja\n"
        "\n"
        "00:00:01.000 --> 00:00:02.000 align:start position:0%\n"
        "こんにちは\n"
        "\n"
        "00:00:02.000 --> 00:00:03.000\n"
        "世界\n"
    )
    assert _parse_vtt(raw) == "こんにちは世界"


def test_parse_json3_joins_segments_and_tolerates_missing_fields():
    data = {
        "events": [
            {"segs": [{"utf8": "こんにちは"}, {"utf8": "、世界"}]},
            {"segs": None},  # segs が無いイベントは寄与しない
            {},  # events の中の空要素も落ちない
            {"segs": [{}, {"utf8": "。"}]},  # utf8 が無いセグメントは空文字
        ]
    }
    assert _parse_json3(data) == "こんにちは、世界。"
    assert _parse_json3({}) == ""


def test_load_json_returns_empty_dict_for_broken_json():
    """壊れた JSON は例外にせず空辞書（呼び出し側は空字幕として縮退する）。"""
    assert _load_json('{"events": []}') == {"events": []}
    assert _load_json("これは JSON ではない") == {}


def test_load_json_returns_empty_dict_for_non_object_json():
    """JSON として読めてもオブジェクトでなければ空辞書（#47）。

    `_parse_json3` は `data.get("events", [])` を呼ぶため、配列や文字列をそのまま
    返すと AttributeError で落ちる。読めない場合と同じ「空字幕」へ畳む。
    """
    assert _load_json("[1, 2, 3]") == {}
    assert _load_json('"字幕"') == {}
    assert _load_json("null") == {}


def test_fetch_transcript_reads_json3_from_data_events():
    """`requested_subtitles` のエントリに `data` が入っている場合（json3 直埋め）。"""
    info = {
        "subtitles": {"ja": [{"ext": "json3"}]},
        "automatic_captions": {},
        "requested_subtitles": {
            "ja": {"ext": "json3", "data": {"events": [{"segs": [{"utf8": "直埋めの字幕"}]}]}}
        },
    }
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.return_value = info
        t = fetch_transcript("vid1", language="ja")
    assert t.text == "直埋めの字幕"
    assert t.source == TranscriptSource.CAPTION


def test_fetch_transcript_reads_json3_file():
    path = _write_sub_file(
        json.dumps({"events": [{"segs": [{"utf8": "JSON3 "}, {"utf8": "ファイル"}]}]}),
        suffix=".json3",
    )
    info = {
        "subtitles": {},
        "automatic_captions": {"ja": [{"ext": "json3"}]},
        "requested_subtitles": {"ja": {"ext": "json3", "filepath": path}},
    }
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.return_value = info
        t = fetch_transcript("vid1", language="ja")
    assert t.text == "JSON3 ファイル"
    assert t.source == TranscriptSource.AUTOMATIC_CAPTION


def test_fetch_transcript_broken_json3_file_yields_empty_text():
    path = _write_sub_file("{壊れた JSON", suffix=".json3")
    info = {
        "subtitles": {"ja": [{"ext": "json3"}]},
        "automatic_captions": {},
        "requested_subtitles": {"ja": {"ext": "json3", "filepath": path}},
    }
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.return_value = info
        t = fetch_transcript("vid1", language="ja")
    assert t.text == ""


def test_fetch_transcript_empty_vtt_file_yields_empty_text():
    info = {
        "subtitles": {"ja": [{"ext": "vtt"}]},
        "automatic_captions": {},
        "requested_subtitles": {"ja": {"ext": "vtt", "filepath": _write_sub_file("")}},
    }
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.return_value = info
        t = fetch_transcript("vid1", language="ja")
    assert t.text == ""
    assert t.source == TranscriptSource.CAPTION


def test_fetch_transcript_missing_subtitle_file_yields_empty_text():
    info = {
        "subtitles": {"ja": [{"ext": "vtt"}]},
        "automatic_captions": {},
        "requested_subtitles": {"ja": {"ext": "vtt", "filepath": "/nonexistent/tr_t_missing.vtt"}},
    }
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.return_value = info
        t = fetch_transcript("vid1", language="ja")
    assert t.text == ""
    assert t.source == TranscriptSource.CAPTION


def test_read_subtitle_file_without_data_or_filepath_returns_empty():
    assert _read_subtitle_file({}) == ""
    assert _read_subtitle_file({"ext": "vtt"}) == ""
    # data が辞書でも events が空ならファイル側へフォールバックする
    assert _read_subtitle_file({"data": {"events": []}}) == ""


def test_fetch_transcript_without_requested_subtitles_returns_empty():
    """`requested_subtitles` キー自体が無い応答でも落ちない。"""
    info = {"subtitles": {"ja": [{"ext": "vtt"}]}, "automatic_captions": {}}
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.return_value = info
        t = fetch_transcript("vid1", language="ja")
    assert t.text == ""
    assert t.source == TranscriptSource.AUTOMATIC_CAPTION


def test_fetch_transcript_suppresses_yt_dlp_progress_output():
    """yt-dlp の進捗バーを stdout に出さない。

    字幕は `download=True` で取得するため、`quiet` だけでは進捗バー
    （`[download] 1.00KiB at ...`）が stdout に残り、`--output` 指定時に stdout を
    0 バイトにする契約（CLI-002-6）を破る。`noprogress` の指定を固定する。
    """
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = _fake_info_no_subs
        fetch_transcript("vid1", language="ja")

    opts = ydl_mock.call_args.args[0]
    assert opts["quiet"] is True
    assert opts["noprogress"] is True
    download = ydl_mock.return_value.__enter__.return_value.extract_info.call_args.kwargs["download"]
    assert download is True, "進捗が出る経路（download=True）で検証していること"


def test_fetch_transcript_falls_back_to_first_requested_language():
    """要求言語が取得できなかった場合は、取得できた先頭の言語を使う。"""
    info = {
        "subtitles": {},
        "automatic_captions": {"en": [{"ext": "vtt"}]},
        "requested_subtitles": {
            "en": {"ext": "vtt", "data": {"events": [{"segs": [{"utf8": "Hello"}]}]}}
        },
    }
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.return_value = info
        t = fetch_transcript("vid1", language="ja")
    assert t.text == "Hello"
    assert t.source == TranscriptSource.AUTOMATIC_CAPTION
    assert t.language == "ja"  # 要求言語を記録する（実際に得た言語ではない）


def test_fetch_transcript_degrades_on_download_error(caplog):
    """yt-dlp の `DownloadError` は例外にせず空字幕へ縮退し、理由をログに残す。"""
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = yt_dlp.DownloadError(
            "字幕がありません"
        )
        with caplog.at_level("WARNING", logger="trend_researcher.tools.transcript"):
            t = fetch_transcript("vid1", language="ja")
    assert t.text == ""
    assert t.source == TranscriptSource.AUTOMATIC_CAPTION
    assert "字幕取得に失敗しました" in caplog.text
    assert "vid1" in caplog.text


@pytest.mark.parametrize("info", [[], "not a dict", None])
def test_fetch_transcript_degrades_when_info_is_not_dict(info):
    """部分応答（辞書でない `info`）でも落ちない。"""
    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.return_value = info
        t = fetch_transcript("vid1", language="ja")
    assert t.text == ""
    assert t.source == TranscriptSource.AUTOMATIC_CAPTION


def test_fetch_transcript_keeps_the_automatic_source_when_the_language_is_not_listed():
    """`requested_subtitles` にある言語が `subtitles` / `automatic_captions` の
    どちらにも無い場合は `AUTOMATIC_CAPTION` のまま（T104）。

    この分岐は既定値（`AUTOMATIC_CAPTION`）と同じ値の再代入でしかなく、条件が偽でも
    真でも観測結果が変わらない。到達不能で冗長な分岐は残さない（FR-063 の「常に真に
    なる条件分岐」を持ち込まない）ため実装からは削除し、**観測結果が変わらないこと**を
    この検査で固定する（字幕本文は `requested_subtitles` のエントリから読む）。
    """
    path = _write_sub_file("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n字幕本文\n")
    info = {
        "subtitles": {},
        "automatic_captions": {},
        "requested_subtitles": {"ja": {"ext": "vtt", "filepath": path}},
    }

    with mock.patch("yt_dlp.YoutubeDL") as ydl_mock:
        ydl_mock.return_value.__enter__.return_value.extract_info.side_effect = (
            lambda url, download=False: info
        )
        t = fetch_transcript("vid1", language="ja")

    assert t.source == TranscriptSource.AUTOMATIC_CAPTION
    assert "字幕本文" in t.text
