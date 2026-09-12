"""tools/parse.py の単体テスト（共通）。"""

from trend_researcher.nodes.analyze_content import _parse_angles_table
from trend_researcher.tools.parse import (
    extract_json_block,
    extract_list_items,
    extract_section,
)


def test_extract_json_block_fenced():
    text = '説明\n```json\n{"topic": "AI", "max_results": 10}\n```\n終わり'
    assert extract_json_block(text) == {"topic": "AI", "max_results": 10}


def test_extract_json_block_bare():
    text = '前置き {"a": 1} 後置き'
    assert extract_json_block(text) == {"a": 1}


def test_extract_json_block_none():
    assert extract_json_block("") is None


def test_extract_list_items_dash():
    text = "- ポイント1\n- ポイント2\n本文"
    assert extract_list_items(text) == ["ポイント1", "ポイント2"]


def test_extract_list_items_numbered():
    text = "1. 最初\n2. 次\n"
    assert extract_list_items(text) == ["最初", "次"]


def test_extract_section():
    text = "# タイトル\n本文\n## 要約\nここが要約\n## 他\n"
    assert extract_section(text, "要約") == "ここが要約"


def test_parse_angles_table():
    md = (
        "## ブログの活用アイデア\n"
        "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n"
        "|--------|--------------|---------------------|\n"
        "| 入門解説 | 初心者に刺さる | 「キーフレーズA」 |\n"
        "| 失敗談 | 共感を呼ぶ | 「キーフレーズB」 |\n"
    )
    angles = _parse_angles_table(md)
    assert len(angles) == 2
    assert angles[0].angle == "入門解説"
    assert angles[0].value == "初心者に刺さる"
    assert angles[0].key_phrase == "「キーフレーズA」"
    assert angles[1].angle == "失敗談"


def test_parse_angles_table_skips_header_and_separator():
    md = (
        "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n"
        "|--------|--------------|---------------------|\n"
        "| 実践例 | 具体性がある | 「例」 |\n"
    )
    angles = _parse_angles_table(md)
    assert len(angles) == 1
    assert angles[0].angle == "実践例"


def test_fallback_summary_from_angles():
    import asyncio
    from unittest import mock

    from trend_researcher.models import Candidate
    from trend_researcher.nodes.analyze_content import _analyze_one
    from trend_researcher.providers import get_provider

    class _FakeResult:
        content = (
            "## ブログの活用アイデア\n"
            "| 切り口 | 読者への価値 | 拾えるキーフレーズ |\n"
            "|--------|--------------|---------------------|\n"
            "| 入門解説 | 初心者向け | 「キーフレーズ」 |\n"
            "| 失敗談 | 共感を呼ぶ | 「例」 |\n\n"
        )

    class _FakeModel:
        async def ainvoke(self, prompt):
            return _FakeResult()

    provider = get_provider("youtube")
    cand = Candidate(platform="youtube", id="v1", title="テスト動画")
    with mock.patch("trend_researcher.nodes.analyze_content.build_model", return_value=_FakeModel()):
        finding = asyncio.run(_analyze_one(cand, "", provider))
    # 概要セクションが空でも、活用アイデアの切り口から簡易概要が合成されること
    assert finding.summary
    assert "入門解説" in finding.summary
