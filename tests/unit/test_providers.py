"""provider 層（レジストリ / 描画差分）の契約を固定する（FR-009 / 憲法 原則 IV）。

X と YouTube の差は「provider が吸収する」設計なので、ノード側は provider の
インターフェースだけに依存する。ここではレジストリ解決と、両者の描画差分が
入れ替わっていないことを固定する。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from trend_researcher.models import Candidate
from trend_researcher.providers import _PROVIDERS, available_platforms, get_provider
from trend_researcher.providers.base import Provider
from trend_researcher.providers.x import XProvider
from trend_researcher.providers.youtube import YouTubeProvider


def _candidate(idx: int = 1, platform: str = "x", **overrides: Any) -> Candidate:
    base: dict[str, Any] = {
        "platform": platform,
        "id": f"t{idx}" if platform == "x" else f"v{idx}",
        "url": f"https://example.test/{idx}",
        "relevance_rank": idx,
    }
    if platform == "x":
        base.update(
            {
                "text": f"本文{idx}",
                "author_handle": f"user{idx}",
                "author_name": f"ユーザー{idx}",
                "author_followers": 100 * idx,
                "like_count": 10 * idx,
                "retweet_count": 2 * idx,
                "quote_count": idx,
                "published_at": datetime(2026, 1, idx, 9, 0, tzinfo=UTC),
            }
        )
    else:
        base.update(
            {
                "title": f"動画{idx}",
                "author_name": f"チャンネル{idx}",
                "view_count": 100 * idx,
                "published_at": datetime(2026, 1, idx, 9, 0, tzinfo=UTC),
            }
        )
    base.update(overrides)
    return Candidate(**base)


class _StubProvider(Provider):
    """`base.Provider` の既定実装だけを検証するための最小 provider。"""

    name = "stub"

    def search(self, queries, max_results, published_after, sort_by, config):  # type: ignore[no-untyped-def]
        return []

    def fetch_contexts(self, candidates, config):  # type: ignore[no-untyped-def]
        return [], []

    def candidate_table_header(self) -> tuple[str, str]:
        return ("| h |", "|---|")

    def render_candidate_row(self, c: Candidate) -> str:
        return f"| {c.id} |"

    def render_block_title(self, c: Candidate) -> str:
        return f"### {c.id}"

    def render_block_meta(self, c: Candidate) -> list[str]:
        return []

    @property
    def parse_instruction_prompt(self) -> str:
        return "stub-parse"

    @property
    def plan_search_prompt(self) -> str:
        return "stub-plan"

    @property
    def analyze_content_prompt(self) -> str:
        return "stub-analyze"

    @property
    def extract_common_prompt(self) -> str:
        return "stub-common"

    @property
    def common_theme_supporting_label(self) -> str:
        return "stub-label"


# ---------------------------------------------------------------------------
# レジストリ解決
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("x", XProvider), ("X", XProvider), (" x ", XProvider), ("youtube", YouTubeProvider), ("YouTube", YouTubeProvider)],
)
def test_get_provider_normalizes_platform_name(platform: str, expected: type) -> None:
    assert isinstance(get_provider(platform), expected)


@pytest.mark.parametrize("platform", ["reddit", "", "   ", "x/youtube", "ツイッター"])
def test_get_provider_rejects_unknown_platform(platform: str) -> None:
    with pytest.raises(ValueError) as exc:
        get_provider(platform)

    message = str(exc.value)
    assert f"未知のプラットフォーム: {platform}" in message
    assert "'x' または 'youtube'" in message


def test_get_provider_returns_a_fresh_instance_per_call() -> None:
    assert get_provider("x") is not get_provider("x")


def test_available_platforms_lists_registry_keys_in_order() -> None:
    assert available_platforms() == ["x", "youtube"]


def test_available_platforms_returns_a_copy() -> None:
    platforms = available_platforms()
    platforms.append("reddit")

    assert available_platforms() == ["x", "youtube"]


def test_registry_key_matches_provider_name_attribute() -> None:
    """レジストリのキーと provider が自己申告する name がずれていないこと。

    compile_report は `provider.name` で分岐するため、ずれると描画だけが
    別プラットフォームの実装になる。
    """
    assert {key: cls().name for key, cls in _PROVIDERS.items()} == {"x": "x", "youtube": "youtube"}


@pytest.mark.parametrize("platform", ["x", "youtube"])
def test_provider_exposes_the_full_interface(platform: str) -> None:
    provider = get_provider(platform)

    for method in (
        "search",
        "fetch_contexts",
        "resort",
        "candidate_table_header",
        "render_candidate_row",
        "render_block_title",
        "render_block_meta",
    ):
        assert callable(getattr(provider, method)), method
    for prompt in (
        "parse_instruction_prompt",
        "plan_search_prompt",
        "analyze_content_prompt",
        "extract_common_prompt",
        "common_theme_supporting_label",
    ):
        assert isinstance(getattr(provider, prompt), str), prompt


# ---------------------------------------------------------------------------
# base.Provider の既定実装
# ---------------------------------------------------------------------------


def test_base_provider_resort_default_is_identity() -> None:
    """resort を実装しない provider は順序を変えない（既定実装）。"""
    candidates = [_candidate(2), _candidate(1)]

    result = _StubProvider().resort(candidates, "likes")

    assert result is candidates


# ---------------------------------------------------------------------------
# 描画差分（表ヘッダ / 行 / 見出し / メタ / ラベル / プロンプト）
# ---------------------------------------------------------------------------


def test_candidate_table_headers_differ_between_platforms() -> None:
    x_head, x_sep = get_provider("x").candidate_table_header()
    yt_head, yt_sep = get_provider("youtube").candidate_table_header()

    assert (x_head, x_sep) == (
        "| # | 本文抜粋 | 投稿者 | いいね | RT | 引用 | URL |",
        "|---|----------|--------|--------|----|------|-----|",
    )
    assert (yt_head, yt_sep) == (
        "| # | タイトル | チャンネル | 再生数 | URL |",
        "|---|----------|------------|--------|-----|",
    )
    assert x_head != yt_head
    assert x_sep.count("|") == x_head.count("|")
    assert yt_sep.count("|") == yt_head.count("|")


@pytest.mark.parametrize(
    ("overrides", "expected_counts"),
    [
        ({}, "10 | 2 | 1"),
        ({"like_count": None, "retweet_count": None, "quote_count": None}, "- | - | -"),
    ],
)
def test_render_candidate_row_x_uses_snippet_and_counts(overrides: dict, expected_counts: str) -> None:
    row = get_provider("x").render_candidate_row(_candidate(1, **overrides))

    assert row == f"| 1 | 本文1 | @user1 | {expected_counts} | https://example.test/1 |"


def test_render_candidate_row_x_falls_back_to_author_name_without_handle() -> None:
    row = get_provider("x").render_candidate_row(_candidate(1, author_handle=""))

    assert "| ユーザー1 |" in row


def test_render_candidate_row_x_truncates_snippet_and_flattens_newlines() -> None:
    row = get_provider("x").render_candidate_row(_candidate(1, text="あ" * 60))

    assert f"| 1 | {'あ' * 50} |" in row
    assert "あ" * 60 not in row
    assert "\n" not in get_provider("x").render_candidate_row(_candidate(1, text="1行目\n2行目"))


@pytest.mark.parametrize(
    ("overrides", "expected_view"),
    [({}, "100"), ({"view_count": None}, "-")],
)
def test_render_candidate_row_youtube_uses_title_and_view_count(
    overrides: dict, expected_view: str
) -> None:
    row = get_provider("youtube").render_candidate_row(_candidate(1, "youtube", **overrides))

    assert row == f"| 1 | 動画1 | チャンネル1 | {expected_view} | https://example.test/1 |"


def test_render_block_title_differs_between_platforms() -> None:
    x = get_provider("x")
    yt = get_provider("youtube")

    assert x.render_block_title(_candidate(1)) == "### 1. @user1 のツイート"
    assert x.render_block_title(_candidate(1, author_handle="")) == "### 1. @ユーザー1 のツイート"
    assert yt.render_block_title(_candidate(1, "youtube")) == "### 1. 動画1"


def test_render_block_meta_x_lists_present_fields_in_order() -> None:
    meta = get_provider("x").render_block_meta(_candidate(1))

    assert meta == [
        "投稿者: ユーザー1",
        "フォロワー: 100",
        "いいね: 10",
        "RT: 2",
        "公開日: 2026-01-01",
    ]


def test_render_block_meta_x_omits_none_fields() -> None:
    candidate = _candidate(
        1, author_followers=None, like_count=None, retweet_count=None, published_at=None
    )

    assert get_provider("x").render_block_meta(candidate) == ["投稿者: ユーザー1"]


def test_render_block_meta_youtube_omits_none_fields() -> None:
    meta = get_provider("youtube").render_block_meta(_candidate(1, "youtube"))
    assert meta == ["チャンネル: チャンネル1", "再生数: 100", "公開日: 2026-01-01"]

    empty = Candidate(platform="youtube", id="v9", relevance_rank=1)
    assert get_provider("youtube").render_block_meta(empty) == []


def test_common_theme_supporting_labels_differ() -> None:
    assert get_provider("x").common_theme_supporting_label == "該当ツイート"
    assert get_provider("youtube").common_theme_supporting_label == "該当動画"


@pytest.mark.parametrize(
    "attribute",
    ["parse_instruction_prompt", "plan_search_prompt", "analyze_content_prompt", "extract_common_prompt"],
)
def test_prompts_differ_between_platforms(attribute: str) -> None:
    x_prompt = getattr(get_provider("x"), attribute)
    yt_prompt = getattr(get_provider("youtube"), attribute)

    assert x_prompt and yt_prompt
    assert x_prompt != yt_prompt


# ---------------------------------------------------------------------------
# resort（fetch 後の再ソート）
# ---------------------------------------------------------------------------


def test_x_resort_likes_sorts_descending_and_reranks() -> None:
    candidates = [
        _candidate(1, like_count=5),
        _candidate(2, like_count=90),
        _candidate(3, like_count=None),
    ]

    ordered = get_provider("x").resort(candidates, "likes")

    assert [c.id for c in ordered] == ["t2", "t1", "t3"]
    assert [c.relevance_rank for c in ordered] == [1, 2, 3]


def test_x_resort_relevance_drops_empty_text_and_sorts_ascending_stably() -> None:
    candidates = [
        _candidate(1, like_count=30, relevance_rank=1),
        _candidate(2, like_count=10, relevance_rank=2),
        _candidate(3, like_count=10, relevance_rank=3, text="   "),
        _candidate(4, like_count=None, text=""),
    ]

    ordered = get_provider("x").resort(candidates, "relevance")

    # 本文なし（空白のみ含む）は除外し、いいね昇順・同数は取得時の rank 順を維持
    assert [c.id for c in ordered] == ["t2", "t1"]
    assert [c.relevance_rank for c in ordered] == [1, 2]


def test_youtube_resort_keeps_input_order() -> None:
    candidates = [_candidate(3, "youtube"), _candidate(1, "youtube")]

    ordered = get_provider("youtube").resort(candidates, "likes")

    assert ordered is candidates
    assert [c.relevance_rank for c in ordered] == [3, 1]
