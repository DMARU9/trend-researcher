"""プラットフォーム（X / YouTube）ごとの振る舞いを抽象化する provider 層。"""

from __future__ import annotations

from trend_researcher.providers.base import Provider
from trend_researcher.providers.x import XProvider
from trend_researcher.providers.youtube import YouTubeProvider

# プラットフォーム名 → provider クラス
# この辞書が登録の唯一の置き場である（初期登録の 2 件だけがリテラルを持つ）。
_PROVIDERS: dict[str, type[Provider]] = {
    "x": XProvider,
    "youtube": YouTubeProvider,
}


def register_provider(provider_class: type[Provider]) -> None:
    """新しいプラットフォームを登録する（FR-002 / FR-026）。

    コア（`nodes/` / `graph.py` / `__main__.py`）を変更せずにプラットフォームを
    追加できるようにするための入口。登録キーは `provider_class.name` を正規化
    した値（小文字・前後の空白除去）を使う。
    """
    _PROVIDERS[provider_class.name.strip().lower()] = provider_class


def _resolve_key(platform: str) -> str:
    """プラットフォーム名を登録キーへ解決する。

    空文字・空白のみは「未指定」とみなし、**登録の先頭**のプラットフォームを返す
    （`Configuration.platform` の既定が空文字のため。research.md R-8 / EXT-007）。
    """
    key = platform.strip().lower()
    if key:
        return key
    if not _PROVIDERS:  # pragma: no cover - 登録が空になるのはテストの後始末のみ
        raise ValueError("プラットフォームが 1 つも登録されていません")
    return next(iter(_PROVIDERS))


def get_provider(platform: str) -> Provider:
    """プラットフォーム名から provider インスタンスを取得する。

    エラー文言は登録キーから生成する（プラットフォーム名のリテラルを持たない）。
    登録を追加すれば利用可能な値の提示も自動で追随する。
    """
    key = _resolve_key(platform)
    if key not in _PROVIDERS:
        choices = "、".join(f"'{name}'" for name in _PROVIDERS)
        raise ValueError(
            f"未知のプラットフォーム: {platform}（{choices} のいずれかを指定してください）"
        )
    return _PROVIDERS[key]()


def available_platforms() -> list[str]:
    """利用可能なプラットフォーム名のリスト。"""
    return list(_PROVIDERS.keys())
