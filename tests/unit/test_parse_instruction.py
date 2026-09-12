"""nodes/parse_instruction.py の期間抽出・共通ロジックの単体テスト。"""

from datetime import UTC, datetime
from unittest import mock

from trend_researcher.nodes import parse_instruction
from trend_researcher.nodes.parse_instruction import _extract_published_after_from_text


def _with_fixed_now(fixed: datetime):
    real_datetime = datetime
    frozen = mock.MagicMock(wraps=real_datetime)
    frozen.now.return_value = fixed
    return mock.patch.object(parse_instruction, "datetime", frozen)


def test_half_year():
    fixed = datetime(2026, 8, 27, tzinfo=UTC)
    with _with_fixed_now(fixed):
        result = _extract_published_after_from_text("半年以内に公開された機械学習動画")
    assert result is not None
    assert (fixed - result).days == 182


def test_three_months():
    fixed = datetime(2026, 8, 27, tzinfo=UTC)
    with _with_fixed_now(fixed):
        result = _extract_published_after_from_text("3ヶ月以内のAI解説")
    assert result is not None
    assert (fixed - result).days == 92


def test_one_year():
    fixed = datetime(2026, 8, 27, tzinfo=UTC)
    with _with_fixed_now(fixed):
        result = _extract_published_after_from_text("1年以内のチュートリアル")
    assert result is not None
    assert (fixed - result).days == 365


def test_this_year():
    fixed = datetime(2026, 8, 27, tzinfo=UTC)
    with _with_fixed_now(fixed):
        result = _extract_published_after_from_text("今年公開の動画")
    assert result is not None
    assert result == datetime(2026, 1, 1, tzinfo=UTC)


def test_recent_n_days():
    fixed = datetime(2026, 8, 27, tzinfo=UTC)
    with _with_fixed_now(fixed):
        result = _extract_published_after_from_text("最近30日のニュース")
    assert result is not None
    assert (fixed - result).days == 30


def test_no_period():
    result = _extract_published_after_from_text("機械学習の基礎を解説している動画")
    assert result is None
