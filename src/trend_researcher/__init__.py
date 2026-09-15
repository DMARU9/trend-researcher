"""Trend Researcher - 自然言語指示から自律的にトレンドリサーチレポートを生成するツール（X / YouTube 共通）。

公開名は**参照された時だけ**読み込む（PEP 562 のモジュール level `__getattr__`）。
`__init__` がグラフを巻き込むと、`trend_researcher.*` のサブモジュールを 1 つ import
するだけで `langgraph` / `openai`（実測 1.25 秒）を払うことになり、引数検証だけの CLI
起動まで遅くなる（SC-013 / T099）。`from trend_researcher import X` も
`trend_researcher.X` も従来どおり解決する（`__all__` は変えない）。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 型検査のためだけの import（実行時は __getattr__ が解決する）
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

#: 公開名 → 実体を持つモジュール（公開名の一覧は `__all__` と一致させる）
_LAZY: dict[str, str] = {
    "trend_researcher": "trend_researcher.graph",
    "AnalysisFinding": "trend_researcher.models",
    "BlogAngle": "trend_researcher.models",
    "Candidate": "trend_researcher.models",
    "CommonTheme": "trend_researcher.models",
    "Context": "trend_researcher.models",
    "OutputFormat": "trend_researcher.models",
    "OutputSpec": "trend_researcher.models",
    "ResearchInstruction": "trend_researcher.models",
    "ResearchReport": "trend_researcher.models",
    "render_report": "trend_researcher.rendering",
}


def __getattr__(name: str) -> Any:
    """公開名を初回参照時に読み込む（SC-013 / T099）。

    未定義の名前は通常のモジュールと同じように `AttributeError` を投げる
    （`hasattr` の判定や `mock.patch` の後始末の挙動を変えない）。
    """
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_name), name)
