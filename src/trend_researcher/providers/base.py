"""provider 抽象基底クラス（X / YouTube の差を吸収）。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trend_researcher.configuration import Configuration
from trend_researcher.models import Candidate, Context


class Provider(Protocol):
    """プラットフォームごとの検索・取得・レンダリング差を吸収するインターフェース。

    コア（`nodes/` / `graph.py` / `__main__.py`）はここに載る値を**解釈しない**。
    文字列・数値はそのまま出力や設定の解決に使われ、差の表現（文面・件数上限・
    環境変数の接頭辞）は provider 側がすべて担う。新しいプラットフォームは
    `register_provider()` で登録するだけでよい（コアの変更は不要。FR-002）。
    """

    name: str  # "x" | "youtube"

    # --- コアへ渡す差の表現（コアは値を解釈せず、そのまま出力に載せる） ---
    #: 環境変数の接頭辞（`{env_prefix}_MODEL` / `{env_prefix}_*`）。
    #: 固有設定の解決（`configuration.resolve_env`）に引数として渡す。
    env_prefix: str
    #: 検索クエリ数の上限。`None` は無制限（単一クエリ設計のプラットフォーム用）。
    max_search_queries: int | None
    #: 検索 0 件時の文面に使う名詞（「該当する<content_noun>が見つかりませんでした」）。
    content_noun: str
    #: 選定リストの見出し行（`render_markdown` がそのまま使う）。
    candidates_section_title: str

    def selection_note(self, sort_by: str) -> str:
        """選定基準の注記（`sort_by` を解釈してよいのは provider 側だけ）。"""
        ...

    # --- 検索 ---
    def search(
        self,
        queries: list[str],
        max_results: int,
        published_after: datetime | None,
        sort_by: str,
        configuration: Configuration,
    ) -> list[Candidate]:
        """クエリから候補（Candidate）を検索し、上位 max_results 件を返す。

        `configuration` は実行時設定の 1 つの値（SET-001）。固有設定の解決
        （`settings()`）は provider の内部で行い、コアは呼ばない（SET-003）。
        """
        ...

    # --- 要約用ソース取得（X: スレッド/リプライ, YouTube: 字幕）---
    def fetch_contexts(
        self, candidates: list[Candidate], configuration: Configuration
    ) -> tuple[list[Context], list[str]]:
        """候補から要約用ソースを取得する。戻り値は (contexts, notes)。"""
        ...

    # --- レンダリング（Markdown）用ヘルパ ---
    def candidate_table_header(self) -> tuple[str, str]:
        """選定リスト表のヘッダ行（タイトル行, 区切り行）。"""
        ...

    def render_candidate_row(self, c: Candidate) -> str:
        """選定リスト表の 1 行。"""
        ...

    def render_block_title(self, c: Candidate) -> str:
        """個別要約ブロックの見出し（### N. ...）。"""
        ...

    def render_block_meta(self, c: Candidate) -> list[str]:
        """個別要約ブロックのメタ情報行（> ... の一部）。"""
        ...

    # --- プロンプト ---
    @property
    def parse_instruction_prompt(self) -> str:
        ...

    @property
    def plan_search_prompt(self) -> str:
        ...

    @property
    def analyze_content_prompt(self) -> str:
        ...

    @property
    def extract_common_prompt(self) -> str:
        ...

    # --- 共通テーマの「該当」列ラベル ---
    @property
    def common_theme_supporting_label(self) -> str:
        """「該当ツイート」「該当動画」などのラベル。"""
        ...

    # --- 再ソート ---
    def resort(self, candidates: list[Candidate], sort_by: str) -> list[Candidate]:
        """候補を指定された基準で再ソートする（デフォルトは順序変更なし）。"""
        return candidates
