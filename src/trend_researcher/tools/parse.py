"""LLM 出力の軽いパース関数（構造化出力の強制はしない）。X / YouTube 共通。"""

from __future__ import annotations

import json
import re
from typing import Any


def _load_json_object(text: str) -> dict[str, Any] | None:
    """JSON として読める「オブジェクト」のときだけ返す。

    配列・文字列・数値・真偽値・`null` は構造化ブロックではないため `None` に
    する。呼び出し側（`parse_instruction`）は戻り値を `.get()` で読むので、その
    まま返すと `AttributeError` でノードごと落ちる。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def extract_json_block(text: str) -> dict[str, Any] | None:
    """LLM 出力から最初の JSON オブジェクト（```json 含む）を抽出する。"""
    if not text:
        return None
    # ```json ... ``` を優先
    fenced = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    data = _load_json_object(candidate)
    if data is not None:
        return data
    # 波括弧内を探す
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        return _load_json_object(brace.group(0))
    return None


def extract_list_items(text: str, marker: str = "-") -> list[str]:
    """Markdown リスト（"- " または "1. "）から項目を抽出する。"""
    if not text:
        return []
    items: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(rf"^(?:{marker}\s+|\d+\.\s+)(.*)$", line)
        if m:
            items.append(m.group(1).strip())
    return items


def extract_section(text: str, heading: str) -> str:
    """Markdown から指定見出し直下の本文を抽出する。"""
    if not text:
        return ""
    lines = text.splitlines()
    collected: list[str] = []
    capturing = False
    # f-string 内の量指定子 {1,6} は {{ }} でエスケープ
    heading_re = re.compile(rf"^#{{1,6}}\s+{re.escape(heading)}\s*$")
    for line in lines:
        if heading_re.match(line):
            capturing = True
            continue
        if capturing and re.match(r"^#{1,6}\s+", line):
            # 次の見出しで終了
            break
        if capturing:
            collected.append(line)
    return "\n".join(collected).strip()
