"""ノード進捗エミッタ（FR-013 対応）。LangGraph ストリーミング対応。"""

from __future__ import annotations

import sys
from typing import TextIO

from langchain_core.messages import AIMessage


class ProgressEmitter:
    """全ノードから呼び出される進捗表示ユーティリティ。

    進捗は常に「開始」または「完了」のいずれかで更新され、
    エラー／成功メッセージのみの空白状態を作らない（FR-013）。
    """

    TOTAL = 7

    def __init__(self, total: int = TOTAL, stream: TextIO | None = None) -> None:
        self.total = total
        self._stream = stream or sys.stderr
        self._messages: list[AIMessage] = []

    def emit(self, node_index: int, node_name: str, phase: str, detail: str = "") -> None:
        """進捗を stderr へ出力し、AIMessage を内部リストに追加。"""
        suffix = f"（{detail}）" if detail else ""
        line = f"[{node_index}/{self.total}] {node_name} ... {phase}{suffix}"
        print(line, file=self._stream, flush=True)
        self._messages.append(AIMessage(content=line))

    def get_messages(self) -> list[AIMessage]:
        """蓄積された進捗メッセージのリストを返す。"""
        return list(self._messages)


# ノード名の固定定義（順序と一致させる）
NODE_PARSE_INSTRUCTION = "parse_instruction"
NODE_PLAN_SEARCH = "plan_search"
NODE_SEARCH = "search"
NODE_FETCH = "fetch"
NODE_ANALYZE_CONTENT = "analyze_content"
NODE_EXTRACT_COMMON = "extract_common"
NODE_COMPILE_REPORT = "compile_report"

NODE_ORDER = [
    NODE_PARSE_INSTRUCTION,
    NODE_PLAN_SEARCH,
    NODE_SEARCH,
    NODE_FETCH,
    NODE_ANALYZE_CONTENT,
    NODE_EXTRACT_COMMON,
    NODE_COMPILE_REPORT,
]


def make_emitter() -> ProgressEmitter:
    """標準の ProgressEmitter を生成。"""
    return ProgressEmitter(total=len(NODE_ORDER))
