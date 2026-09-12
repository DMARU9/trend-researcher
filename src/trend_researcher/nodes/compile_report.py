"""compile_report ノード（FR-009/FR-010 対応、markdown/json 両対応）。X / YouTube 共通。"""

from __future__ import annotations

from pathlib import Path

from langchain_core.runnables import RunnableConfig

from trend_researcher.cache import write_json
from trend_researcher.configuration import Configuration
from trend_researcher.models import ResearchReport
from trend_researcher.progress import NODE_COMPILE_REPORT, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState


def compile_report(state: AgentState, config: RunnableConfig) -> dict:
    """選定コンテンツ・要約・共通ネタをまとめた ResearchReport を組み立てる。"""
    configurable = Configuration.from_runnable_config(config)
    emitter = make_emitter()
    emitter.emit(7, NODE_COMPILE_REPORT, "開始")
    progress_messages = emitter.get_messages()

    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    instruction = state["instruction"]
    candidates = state.get("candidates", [])
    analyses = state.get("analyses", [])
    common_themes = state.get("common_themes", [])
    notes = list(state.get("notes", []))

    published_after = instruction.published_after
    if published_after is not None:
        notes.append(f"投稿日フィルタ: {published_after.date()} 以降に公開された投稿を対象")

    if provider.name == "x":
        # relevance モードは fetch 後に「いいね昇順」で並べ替えるため、ラベルもそれに合わせる
        sort_label = "いいね数の多い順" if (instruction.sort_by or "relevance") == "likes" else "いいね数の少ない順"
        notes.append(f"選定基準: 検索結果から{sort_label}に上位 N 件を採用")
    else:
        notes.append("選定基準: 検索結果の関連度順に上位 N 件を採用")

    if not candidates:
        subject = "ツイート" if provider.name == "x" else "動画"
        notes.append(f"該当する{subject}が見つかりませんでした（検索クエリまたは期間フィルタの条件に一致する投稿なし）。")

    sources = [c.url for c in candidates if c.url]

    report = ResearchReport(
        instruction=instruction,
        candidates=candidates,
        analyses=analyses,
        common_themes=common_themes,
        sources=sources,
        notes=notes,
    )

    emitter.emit(7, NODE_COMPILE_REPORT, "完了")

    cache_dir = state.get("cache_dir")
    if cache_dir:
        try:
            write_json(Path(cache_dir), "report", report.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            emitter.emit(7, NODE_COMPILE_REPORT, f"キャッシュ書き込み失敗: {exc}")

    progress_messages.extend(emitter.get_messages())

    # チャット表示用は常に Markdown で描画（CLI の出力形式指定は影響しない）
    from langchain_core.messages import AIMessage

    rendered = render_markdown(report, provider)

    summary = f"レポート完了: {len(candidates)} 件の候補を分析し、{len(common_themes)} 件の共通テーマを抽出しました。"
    progress_messages.append(AIMessage(content=summary))
    progress_messages.append(AIMessage(content=rendered))
    return {"report": report, "messages": progress_messages}


def _render_candidates_table(report: ResearchReport, provider: "Provider") -> list[str]:  # noqa: F821
    title_line = "## 選定ツイートリスト（上位 N 件）" if provider.name == "x" else "## 選定動画リスト（関連度順上位 N 件）"
    lines = [title_line, ""]
    head, sep = provider.candidate_table_header()
    lines.append(head)
    lines.append(sep)
    for c in report.candidates:
        lines.append(provider.render_candidate_row(c))
    lines.append("")
    return lines


def _render_analysis_block(c: "Candidate", a: "AnalysisFinding | None", provider: "Provider") -> list[str]:  # noqa: F821
    lines: list[str] = [provider.render_block_title(c)]
    meta_line = " ｜ ".join(provider.render_block_meta(c))
    if meta_line:
        lines.append(f"> {meta_line}")
        lines.append("")
    # 本文（X のみ）
    if c.text:
        lines.append("**本文**")
        lines.append("")
        lines.append(c.text or "（本文なし）")
        lines.append("")
    if a is None:
        lines.append("- 要約: （解析なし）")
        lines.append("")
        return lines
    lines.append("**概要**")
    lines.append("")
    lines.append(a.summary)
    lines.append("")
    if a.angles:
        lines.append("**ブログの活用アイデア**")
        lines.append("")
        lines.append("| 切り口 | 読者への価値 | 拾えるキーフレーズ |")
        lines.append("|--------|--------------|---------------------|")
        for ang in a.angles:
            angle = ang.angle.replace("\n", " ")
            value = ang.value.replace("\n", " ")
            phrase = ang.key_phrase.replace("\n", " ")
            lines.append(f"| {angle} | {value} | {phrase} |")
        lines.append("")
    if a.evidence:
        lines.append("**そのまま使える引用**")
        lines.append("")
        for ev in a.evidence:
            lines.append(f"- {ev}")
        lines.append("")
    return lines


def _render_common_themes(report: ResearchReport, provider: "Provider") -> list[str]:  # noqa: F821
    label = provider.common_theme_supporting_label
    lines = ["## 共通ネタ（表）", ""]
    if report.common_themes:
        lines.append(f"| テーマ | 説明 | {label} | 代表抜粋 |")
        lines.append("|--------|------|----------|----------|")
        for t in report.common_themes:
            supporting = ", ".join(t.supporting_ids) or "-"
            quotes = " / ".join(t.example_quotes) or "-"
            lines.append(f"| {t.theme} | {t.description} | {supporting} | {quotes} |")
    else:
        lines.append("（特筆すべき共通点なし）")
    lines.append("")
    return lines


def render_markdown(report: ResearchReport, provider: "Provider") -> str:  # noqa: F821
    """ResearchReport を Markdown 文字列に整形（FR-009 既定）。"""
    from trend_researcher.providers import get_provider

    provider = get_provider(report.instruction.platform)
    instruction = report.instruction
    lines: list[str] = []
    title = instruction.topic or instruction.raw_text[:40]
    lines.append(f"# リサーチレポート: {title}")
    lines.append("")

    lines.extend(_render_candidates_table(report, provider))

    lines.append("## 各コンテンツのブログ向け要約")
    lines.append("")
    analyses_by_id = {a.id: a for a in report.analyses}
    for c in report.candidates:
        lines.extend(_render_analysis_block(c, analyses_by_id.get(c.id), provider))

    lines.extend(_render_common_themes(report, provider))

    lines.append("## 出典")
    lines.append("")
    for s in report.sources:
        lines.append(f"- {s}")
    lines.append("")

    if report.notes:
        lines.append("## 備考")
        lines.append("")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines)


def render_json(report: ResearchReport) -> str:
    """ResearchReport を JSON 文字列に整形（FR-009/SC-004）。"""
    return report.model_dump_json(indent=2, exclude_none=True)
