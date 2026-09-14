"""extract_common ノード（FR-008 対応、X / YouTube 共通）。"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration
from trend_researcher.models import AnalysisFinding, CommonTheme, CommonThemes
from trend_researcher.progress import NODE_EXTRACT_COMMON, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState
from trend_researcher.tools.degradation import (
    DegradationError,
    DegradeOptions,
    options_for,
)
from trend_researcher.tools.llm import build_model, invoke_structured, invoke_text
from trend_researcher.tools.parse import extract_list_items, extract_section


def _format_analyses(analyses: list[AnalysisFinding]) -> str:
    lines = []
    for a in analyses:
        lines.append(f"### コンテンツ {a.id}")
        lines.append(f"要約: {a.summary}")
        lines.append("ポイント: " + " / ".join(a.key_points))
        lines.append("根拠: " + " / ".join(a.evidence))
        lines.append("")
    return "\n".join(lines)


def extract_common(state: AgentState, config: RunnableConfig) -> dict:
    """コンテンツ間の共通ネタを抽出する。"""
    configurable = Configuration.from_runnable_config(config)
    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    emitter = make_emitter()
    emitter.emit(NODE_EXTRACT_COMMON, "開始")
    progress_messages = emitter.get_messages()

    analyses = state.get("analyses", [])
    model = build_model("research", provider.env_prefix)
    # 縮退（US3）は 1 ノード実行につき 1 つの梯子を使い、記録を状態へ返す（FR-017）
    degrade = options_for(configurable, NODE_EXTRACT_COMMON)
    prompt = provider.extract_common_prompt.format(analyses=_format_analyses(analyses))
    themes, fallback_note = _extract_themes(
        prompt,
        model=model,
        configurable=configurable,
        ids=[a.id for a in analyses],
        degrade=degrade,
        env_prefix=provider.env_prefix,
    )
    if fallback_note:
        # 進捗行（`messages`）ではなく補足行に出す（D-3 / FR-029）。
        emitter.note(fallback_note)

    emitter.emit(NODE_EXTRACT_COMMON, "完了", detail=f"{len(themes)} 件の共通テーマ")
    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()
    return {
        "common_themes": themes,
        "degradations": degrade.records,
        "messages": progress_messages,
    }


def _extract_themes(
    prompt: str,
    *,
    model: Any,
    configurable: Configuration,
    ids: list[str],
    degrade: DegradeOptions,
    env_prefix: str | None,
) -> tuple[list[CommonTheme], str]:
    """LLM の応答から共通テーマを得る（構造化出力 → 全失敗なら見出し解析）。

    戻り値は `(テーマの一覧, 補足行)`。補足行はフォールバックしたときだけ空でない。
    規定回数を使い切ったら**例外を送出せず**既存の `tools/parse.py` の経路
    （`_parse_themes` 経由の `extract_section` / `extract_list_items`）へ切り替える
    （FR-011 / FR-012）。空のリストは正常（共通点なし）。

    縮退（上限超過）を使い切った場合だけは例外を伝える（FR-015 の「終了コード 1」を
    このフォールバックで飲み込むと、失敗が成功に化ける）。
    """
    try:
        structured = invoke_structured(
            CommonThemes,
            prompt,
            model=model,
            env_prefix=env_prefix,
            retry_max=configurable.retry_max,
            retry_wait_seconds=configurable.retry_wait_seconds,
            method=configurable.structured_method,
            degrade=degrade,
        )
    except DegradationError:
        raise
    except Exception as exc:  # noqa: BLE001 - 応答の失敗はすべてフォールバックで継続する（FR-011）
        text = invoke_text(
            prompt,
            model=model,
            env_prefix=env_prefix,
            retry_max=configurable.retry_max,
            retry_wait_seconds=configurable.retry_wait_seconds,
            degrade=degrade,
        )
        content = text.content if hasattr(text, "content") else str(text)
        return _parse_themes(content, ids), (
            "構造化出力を取得できなかったため見出し解析へ切り替えました"
            f"（{type(exc).__name__}）"
        )
    return list(structured.themes), ""


def _split_sections(text: str) -> list[list[str]]:
    """見出し（`###` / `####`）ごとに節へ分割する。

    節の境界は「現在の節と同じか浅い見出し」に限り、深い見出しは同じ節に
    残す。`### テーマ` の下の `#### 説明` / `#### 代表抜粋` を節境界にすると、
    `_parse_themes` が `説明` や `代表抜粋` という名前の別テーマを生成し、
    本来のテーマの説明文が失われるため（FR-023）。
    """
    heading_re = re.compile(r"^(#{3,4})\s+.*$")
    sections: list[list[str]] = []
    current: list[str] = []
    level = 0  # 0 = 見出しで始まっていない（前書き）
    for line in text.splitlines():
        m = heading_re.match(line)
        if m:
            line_level = len(m.group(1))
            if current and (level == 0 or line_level <= level):
                sections.append(current)
                current = []
            if not current:
                level = line_level
        current.append(line)
    if current:
        sections.append(current)
    return sections


def _parse_themes(text: str, ids: list[str]) -> list[CommonTheme]:
    themes: list[CommonTheme] = []
    heading_re = re.compile(r"^#{3,4}\s+(.*)$")

    idx = 0
    for sec in _split_sections(text):
        hm = heading_re.match(sec[0])
        if not hm:
            continue
        theme_name = hm.group(1).strip()
        if theme_name in ("共通テーマ", "テーマ", "テーマ名") or "特筆" in theme_name:
            continue
        body = "\n".join(sec[1:]).strip()
        if not body and theme_name:
            body = theme_name
        idx += 1
        desc = extract_section(body, "説明") or body
        supporting = ids
        quotes = extract_list_items(extract_section(body, "代表抜粋")) or extract_list_items(body)
        themes.append(
            CommonTheme(
                theme=theme_name or f"共通テーマ{idx}",
                description=desc,
                supporting_ids=supporting,
                example_quotes=quotes,
            )
        )
    return themes
