"""プラットフォーム（X / YouTube）ごとの振る舞いを抽象化する provider 層。"""

from __future__ import annotations

from trend_researcher.providers.base import Provider
from trend_researcher.providers.x import XProvider
from trend_researcher.providers.youtube import YouTubeProvider

# プラットフォーム名 → provider クラス
_PROVIDERS: dict[str, type[Provider]] = {
    "x": XProvider,
    "youtube": YouTubeProvider,
}


def get_provider(platform: str) -> Provider:
    """プラットフォーム名から provider インスタンスを取得する。"""
    key = platform.strip().lower()
    if key not in _PROVIDERS:
        raise ValueError(
            f"未知のプラットフォーム: {platform}（'x' または 'youtube' を指定してください）"
        )
    return _PROVIDERS[key]()


def available_platforms() -> list[str]:
    """利用可能なプラットフォーム名のリスト。"""
    return list(_PROVIDERS.keys())
