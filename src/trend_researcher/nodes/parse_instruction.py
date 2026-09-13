"""parse_instruction ノード（FR-001 対応）。X / YouTube 共通。"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration
from trend_researcher.models import OutputFormat, OutputSpec, ResearchInstruction
from trend_researcher.progress import NODE_PARSE_INSTRUCTION, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState
from trend_researcher.tools.llm import build_model
from trend_researcher.tools.parse import extract_json_block

# 期間ラベル（数字+月以外）を投稿日下限の相対日数に変換するマッピング。
_RELATIVE_PERIOD_DAYS = {
    "半年": 182,
    "1年": 365,
    "年": 365,
    "本年": 0,
    "今年": 0,
    "最近": 92,
}

#: 漢数字の位取り（一〜九）。`十` は `_to_number` で位取りとして扱う。
_KANJI_DIGITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

#: 件数抽出の前に取り除く年号・期間表現（件数ではない。FR-011）。
_PERIOD_EXPRESSION_RE = re.compile(
    r"(?:半年"
    r"|[0-9０-９一二三四五六七八九十]+[ヶカ]?月"
    r"|[0-9０-９一二三四五六七八九十]+年"
    r"|本年|今年"
    r"|最近\s*[0-9０-９]+日)"
    r"(?:\s*以内)?"
)

#: 件数の単位（「5件」「五本」の「件」「本」）。
_COUNT_UNITS = "個|件|本|つ|カ国|か国|社|人"


def _to_number(text: str) -> int | None:
    """算用数字または漢数字（一〜九・十・十一〜九十九）を整数へ変換する。"""
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    tens_text, sep, ones_text = text.partition("十")
    if sep:
        if len(tens_text) > 1 or len(ones_text) > 1:
            return None
        tens = _KANJI_DIGITS.get(tens_text, 1) if tens_text else 1
        ones = _KANJI_DIGITS.get(ones_text, 0) if ones_text else 0
        return tens * 10 + ones
    return _KANJI_DIGITS.get(text)


def _extract_published_after_from_text(text: str) -> datetime | None:
    """自然言語から投稿日下限（published_after）を抽出。"""
    now = datetime.now(UTC)
    m = re.search(
        r"(半年|[0-9０-９一二三四五六七八九十]+[ヶカ]?月|1年|年|本年|今年|最近)\s*以内",
        text,
    )
    if m:
        return _period_to_date(m.group(1), now)
    if re.search(r"(今年|本年)", text):
        return datetime(now.year, 1, 1, tzinfo=UTC)
    m = re.search(r"最近\s*([0-9０-９]+)\s*日", text)
    if m:
        return now - timedelta(days=int(m.group(1)))
    return None


def _period_to_date(label: str, now: datetime) -> datetime | None:
    num_m = re.search(r"([0-9０-９一二三四五六七八九十]+)\s*[ヶカ]?\s*月", label)
    if num_m:
        months = _to_number(num_m.group(1))
        if months is None:
            return None
        total_months = now.year * 12 + (now.month - 1) - months
        y = total_months // 12
        mo = total_months % 12 + 1
        return datetime(y, mo, now.day, now.hour, now.minute, now.second, now.microsecond, tzinfo=UTC)
    if label in _RELATIVE_PERIOD_DAYS:
        days = _RELATIVE_PERIOD_DAYS[label]
        return datetime(now.year, 1, 1, tzinfo=UTC) if days == 0 else now - timedelta(days=days)
    return None


def _parse_date_from_text(text: str) -> datetime | None:
    """明示的な日付指定（YYYY-MM-DD 以降）を抽出。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:以降|から|より|以後)", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _extract_count_from_text(text: str) -> int | None:
    """指示本文から件数を取り出す（算用数字 → 漢数字）。

    年号・期間表現（「2025年」「半年以内」）は件数ではないため先に取り除く。
    取り除かないと「2025年の動画を10件」が 2025 件と解釈される（FR-011）。
    """
    text = _PERIOD_EXPRESSION_RE.sub("", text)
    m = re.search(rf"([0-9０-９]+)\s*(?:{_COUNT_UNITS})?", text)
    if m:
        return int(m.group(1))
    m = re.search(rf"([一二三四五六七八九十]+)\s*(?:{_COUNT_UNITS})", text)
    if m:
        return _to_number(m.group(1))
    return None


def parse_instruction(state: AgentState, config: RunnableConfig) -> dict:
    """自然言語指示からトピック・件数・投稿日下限を抽出する。"""
    configurable = Configuration.from_runnable_config(config)
    # platform: ユーザー入力（state）> Configuration。以降 provider.name で上書きするため str として扱う
    platform: str = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    emitter = make_emitter()
    emitter.emit(1, NODE_PARSE_INSTRUCTION, "開始")
    progress_messages = emitter.get_messages()

    # instruction_raw: ユーザーの最新メッセージから抽出
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    # `content` は本文ブロックのリストにもなりうる（LangChain の標準形式）。
    # 以降は文字列前提の解析（正規表現・`ResearchInstruction.raw_text`）なので文字列化する。
    raw = content if isinstance(content, str) else str(content)
    model = build_model("research", provider.env_prefix)
    prompt = provider.parse_instruction_prompt.format(instruction=raw)
    result = model.invoke(prompt)
    text = result.content if hasattr(result, "content") else str(result)
    parsed = extract_json_block(text) or {}

    topic = str(parsed.get("topic", "")).strip() or raw
    # 件数: ユーザー入力（state）> Configuration > 自然言語 > LLM
    input_max = state.get("max_results")
    if input_max is not None:  # ユーザー入力がある場合（未指定はキー不在。FR-011）
        max_results = int(input_max)
    elif configurable.max_results != 5:  # Configuration設定がある場合
        max_results = configurable.max_results
    else:
        nl = _extract_count_from_text(raw)
        max_results = nl if nl is not None else int(parsed.get("max_results", 5) or 5)
    # 出力形式: Configuration設定 > CLI/run（state.output_format）＞自然言語/LLM
    if configurable.output_format is not None:  # Configuration設定がある場合
        output_format = OutputFormat.JSON if configurable.output_format == "json" else OutputFormat.MARKDOWN
    else:
        cli_fmt = state.get("output_format")
        if cli_fmt is not None:
            output_format = cli_fmt
        else:
            fmt = str(parsed.get("output_format", "markdown")).lower()
            output_format = OutputFormat.JSON if fmt == "json" else OutputFormat.MARKDOWN

    # 期間: Configuration.published_after ＞ CLI --since ＞自然言語
    cli_since = state.get("published_after")
    config_since = configurable.published_after
    published_after = (
        datetime.fromisoformat(config_since).replace(tzinfo=UTC)
        if config_since
        else None
    ) or cli_since or _extract_published_after_from_text(raw) or _parse_date_from_text(raw)

    platform = provider.name
    instruction = ResearchInstruction(
        raw_text=raw,
        platform=platform,
        topic=topic,
        max_results=max_results,
        output=OutputSpec(format=output_format),
        published_after=published_after,
        sort_by=str(configurable.sort_by) if configurable.sort_by != "relevance" else str(state.get("sort_by", "relevance")),
        transcript_language=str(configurable.transcript_language) if configurable.transcript_language != "ja" else str(state.get("transcript_language", "ja") or "ja"),
    )

    emitter.emit(1, NODE_PARSE_INSTRUCTION, "完了", detail=f'トピック: "{topic}" / 件数: {max_results}')
    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()
    return {"instruction": instruction, "messages": progress_messages}
