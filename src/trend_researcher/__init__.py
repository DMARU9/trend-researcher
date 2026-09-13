"""Trend Researcher - 自然言語指示から自律的にトレンドリサーチレポートを生成するツール（X / YouTube 共通）。"""

from trend_researcher.graph import trend_researcher
from trend_researcher.models import (
    AnalysisFinding,
    BlogAngle,
    Candidate,
    CommonTheme,
    Context,
    OutputFormat,
    OutputSpec,
    ResearchInstruction,
    ResearchReport,
)
from trend_researcher.rendering import render_report

__all__ = [
    "AnalysisFinding",
    "BlogAngle",
    "Candidate",
    "CommonTheme",
    "Context",
    "OutputFormat",
    "OutputSpec",
    "ResearchInstruction",
    "ResearchReport",
    "render_report",
    "trend_researcher",
]
