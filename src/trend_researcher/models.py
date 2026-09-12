"""Pydantic エンティティ定義（X / YouTube 共通）。

X（Twitter）と YouTube の両方で使う統一モデル。
プラットフォーム固有のフィールド（ツイートの RT 数や動画の再生数など）は
すべて同一モデルに収容し、レンダリング時に provider が判別する。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class OutputFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class OutputSpec(BaseModel):
    """出力指定。"""

    format: OutputFormat = OutputFormat.MARKDOWN
    table_for: list[str] = Field(default_factory=lambda: ["common_points"])


class ResearchInstruction(BaseModel):
    """ユーザー指示を構造化したもの（parse_instruction で抽出）。"""

    raw_text: str
    platform: str = "x"  # "x" | "youtube"
    topic: str = ""
    max_results: int = 5
    output: OutputSpec = Field(default_factory=OutputSpec)
    published_after: datetime | None = None
    # X 特有（--trends / --sort）
    use_trends: bool = False
    sort_by: str = "relevance"  # "relevance" | "likes"
    # YouTube 特有（--lang）
    transcript_language: str = "ja"


class Candidate(BaseModel):
    """検索で選定された 1 件（ツイートまたは動画）。プラットフォーム共通。"""

    platform: str = "x"
    id: str  # tweet_id または video_id
    title: str = ""  # 動画タイトル（YouTube）/ ツイートは空
    text: str = ""  # ツイート本文（X）/ 動画は空
    url: str = ""
    author_handle: str = ""  # X
    author_name: str = ""  # X 表示名 / YouTube チャンネル名
    author_followers: int | None = None  # X
    channel_id: str = ""  # YouTube
    published_at: datetime | None = None
    view_count: int | None = None  # YouTube
    like_count: int | None = None
    retweet_count: int | None = None  # X
    reply_count: int | None = None  # X
    quote_count: int | None = None  # X
    relevance_rank: int = 0


class Context(BaseModel):
    """要約用ソース（X: スレッド＋リプライ / YouTube: 字幕）。"""

    id: str
    text: str = ""  # 親ツイート本文 / 字幕テキスト
    thread_text: str = ""  # X のみ
    replies: list[str] = Field(default_factory=list)  # X のみ
    # 検索結果の like_count 等が 0 で埋まる場合があるため、tweet_details で確定した
    # 正確なカウントを一時保持する（fetch_contexts で Candidate に反映後に参照）
    counts: dict[str, int | None] | None = None  # {"like_count", "retweet_count", ...}


class TranscriptSource(str, Enum):
    CAPTION = "caption"
    AUTOMATIC_CAPTION = "automatic_caption"


class BlogAngle(BaseModel):
    """ブログの活用アイデア（切り口 × 読者への価値 × 拾えるキーフレーズ）。"""

    angle: str = ""
    value: str = ""
    key_phrase: str = ""


class AnalysisFinding(BaseModel):
    """個別コンテンツのブログ執筆向け要約。"""

    id: str  # tweet_id または video_id
    title: str = ""
    summary: str = ""
    angles: list[BlogAngle] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class CommonTheme(BaseModel):
    """複数コンテンツ間の共通ネタ。"""

    theme: str = ""
    description: str = ""
    supporting_ids: list[str] = Field(default_factory=list)
    example_quotes: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """最終アウトプット。"""

    instruction: ResearchInstruction
    generated_at: datetime = Field(default_factory=datetime.now)
    candidates: list[Candidate] = Field(default_factory=list)
    analyses: list[AnalysisFinding] = Field(default_factory=list)
    common_themes: list[CommonTheme] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
