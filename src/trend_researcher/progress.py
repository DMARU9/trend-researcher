"""ノード進捗エミッタ（FR-013 対応）。LangGraph ストリーミング対応。"""

from __future__ import annotations

import sys
from typing import TextIO

from langchain_core.messages import AIMessage


class ProgressEmitter:
    """全ノードから呼び出される進捗表示ユーティリティ。

    進捗は常に「開始」または「完了」のいずれかで更新され、
    エラー／成功メッセージのみの空白状態を作らない（FR-013）。

    表示に使う番号と総数は `NODE_ORDER` から導出する（FR-012）。手書きの数値を
    持たないため、ノードを足す・並べ替えると表示が自動で追随し、グラフの実行順と
    ずれない。
    """

    def __init__(self, total: int | None = None, stream: TextIO | None = None) -> None:
        self.total = len(NODE_ORDER) if total is None else total
        self._stream = stream or sys.stderr
        self._messages: list[AIMessage] = []

    def emit(self, node_name: str, phase: str, detail: str = "") -> None:
        """進捗を stderr へ出力し、AIMessage を内部リストに追加。

        番号は `NODE_ORDER.index(node_name) + 1`、分母は `self.total`（既定は
        `len(NODE_ORDER)`）。`NODE_ORDER` に無い名前は、表示だけ進んで実行と
        ずれるのを防ぐため例外にする。
        """
        try:
            node_index = NODE_ORDER.index(node_name) + 1
        except ValueError:
            raise ValueError(
                f"未知のノード名: {node_name}（NODE_ORDER に含まれていません）"
            ) from None
        suffix = f"（{detail}）" if detail else ""
        line = f"[{node_index}/{self.total}] {node_name} ... {phase}{suffix}"
        print(line, file=self._stream, flush=True)
        self._messages.append(AIMessage(content=line))

    def get_messages(self) -> list[AIMessage]:
        """蓄積された進捗メッセージのリストを返す。"""
        return list(self._messages)

    def note(self, text: str) -> None:
        """補足 1 行を stderr へ出力する（追加の観測の唯一の入口。FR-029）。

        `emit()` と違い `self._messages` には**積まない**。`messages` は 7 ノード ×
        開始/完了の契約として凍結されており（T009 の回帰テスト）、圧縮・縮退・失敗・
        使用量の通知を混ぜると既定の入力の `messages` と レポートが変わってしまう
        （D-3）。進捗の番号も進めない（補足は段ではない）。
        """
        print(f"[補足] {text}", file=self._stream, flush=True)


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
