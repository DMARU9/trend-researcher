"""provider 抽象基底クラス（X / YouTube の差を吸収）。"""

from __future__ import annotations

from typing import Protocol

from trend_researcher.models import Candidate, Context


class Provider(Protocol):
    """プラットフォームごとの検索・取得・レンダリング差を吸収するインターフェース。"""

    name: str  # "x" | "youtube"

    # --- 検索 ---
    def search(
        self,
        queries: list[str],
        max_results: int,
        published_after: "datetime | None",  # noqa: F821
        sort_by: str,
        config: "Config",  # noqa: F821
    ) -> list[Candidate]:
        """クエリから候補（Candidate）を検索し、上位 max_results 件を返す。"""
        ...

    # --- 要約用ソース取得（X: スレッド/リプライ, YouTube: 字幕）---
    def fetch_contexts(
        self, candidates: list[Candidate], config: "Config"  # noqa: F821
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
