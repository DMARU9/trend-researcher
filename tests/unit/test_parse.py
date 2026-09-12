"""tools/parse.py の単体テスト（共通）。

対象は LLM 出力の軽いパース関数（JSON ブロック・箇条書き・見出し直下の本文）。
JSON でない応答・JSON であってもオブジェクトでない値のような崩れた入力でも
例外にせず、取れる値だけを返す契約を固定する（FR-012）。

活用アイデア表（`| 切り口 | ... |`）の解釈は表を組み立てるノードの契約なので
`tests/unit/test_analyze_content.py` が持つ（重複させない。FR-017）。
"""

from __future__ import annotations

import pytest

from trend_researcher.tools.parse import (
    extract_json_block,
    extract_list_items,
    extract_section,
)

# --- extract_json_block ---------------------------------------------------


def test_extract_json_block_fenced():
    text = '説明\n```json\n{"topic": "AI", "max_results": 10}\n```\n終わり'
    assert extract_json_block(text) == {"topic": "AI", "max_results": 10}


def test_extract_json_block_bare():
    text = '前置き {"a": 1} 後置き'
    assert extract_json_block(text) == {"a": 1}


def test_extract_json_block_none_for_empty_text():
    assert extract_json_block("") is None


def test_extract_json_block_none_without_any_json():
    assert extract_json_block("特に指定はありません。\nよろしくお願いします。") is None


def test_extract_json_block_prefers_fenced_block():
    text = '```json\n{"a": 1}\n```\n補足 {"b": 2}'
    assert extract_json_block(text) == {"a": 1}


def test_extract_json_block_falls_back_to_braces_when_fenced_is_broken():
    # フェンスの中味が JSON 文字列でないときは、本文中の波括弧から探し直す。
    text = '```json\nこれは JSON ではありません\n```\n補足 {"b": 2}'
    assert extract_json_block(text) == {"b": 2}


@pytest.mark.parametrize(
    "text",
    ['```json\n{"a": }\n```', '```json\n{"a": }\n```\n補足 {"b": 2}'],
    ids=["fenced-only", "fenced-and-bare"],
)
def test_extract_json_block_none_when_nothing_parses(text: str):
    # 壊れたブロックしか無い場合は `None`（例外にしない）。2 件目は波括弧の探索が
    # 最初の `{` から最後の `}` までを貪欲に取るため、壊れたオブジェクトに
    # 引きずられて `None` になる（安全側に倒れる）。
    assert extract_json_block(text) is None


@pytest.mark.parametrize("text", ["[1, 2]", '"AI"', "5", "true", "null"], ids=lambda t: t[:2])
def test_extract_json_block_ignores_non_object_json(text: str):
    # JSON オブジェクト以外（配列・文字列・数値・真偽値・null）は構造化ブロックと
    # みなさない。呼び出し側（`parse_instruction`）は `.get()` で読むため、そのまま
    # 返すと `AttributeError` でノードごと落ちる。
    assert extract_json_block(text) is None


@pytest.mark.parametrize("text", ["```json\n[1, 2]\n```", "配列だけ [1, 2]"])
def test_extract_json_block_ignores_non_object_json_in_text(text: str):
    assert extract_json_block(text) is None


# --- extract_list_items ---------------------------------------------------


def test_extract_list_items_dash():
    text = "- ポイント1\n- ポイント2\n本文"
    assert extract_list_items(text) == ["ポイント1", "ポイント2"]


def test_extract_list_items_numbered():
    text = "1. 最初\n2. 次\n"
    assert extract_list_items(text) == ["最初", "次"]


def test_extract_list_items_empty_text():
    assert extract_list_items("") == []


def test_extract_list_items_custom_marker():
    assert extract_list_items("* 最初\n* 次\n", marker=r"\*") == ["最初", "次"]


def test_extract_list_items_ignores_lines_without_marker():
    assert extract_list_items("前置き\n- 項目\n本文\n1. 番号\n") == ["項目", "番号"]


# --- extract_section ------------------------------------------------------


def test_extract_section():
    text = "# タイトル\n本文\n## 要約\nここが要約\n## 他\n"
    assert extract_section(text, "要約") == "ここが要約"


def test_extract_section_accepts_any_heading_level():
    assert extract_section("# 概要\nH1 の本文\n", "概要") == "H1 の本文"
    assert extract_section("###### 概要\nH6 の本文\n", "概要") == "H6 の本文"


def test_extract_section_with_empty_body():
    assert extract_section("## 概要\n## 他\n本文\n", "概要") == ""


def test_extract_section_missing_heading():
    assert extract_section("## 他\n本文\n", "概要") == ""


def test_extract_section_empty_text():
    assert extract_section("", "概要") == ""
