"""レポート描画（Markdown / JSON。FR-016 / FR-017 / FR-018）。

描画はノード実行から独立して検証できる形に分離する（RND-001 / RND-005）。プラットフォーム差は
**引数の `Provider` のフック**だけを通じて表現し、コアは文面を組み立てない。
"""

from __future__ import annotations

from trend_researcher.models import AnalysisFinding, Candidate, ResearchReport
from trend_researcher.providers.base import Provider


def render_report(report: ResearchReport, provider: Provider) -> str:
    """レポートを指示された形式（既定 markdown）で描画する（FR-009）。"""
    if report.instruction.output.format == "json":
        return render_json(report)
    return render_markdown(report, provider)


def render_markdown(report: ResearchReport, provider: Provider) -> str:
    """ResearchReport を Markdown 文字列に整形（FR-009 既定）。"""
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


def _render_candidates_table(report: ResearchReport, provider: Provider) -> list[str]:
    title_line = provider.candidates_section_title
    lines = [title_line, ""]
    head, sep = provider.candidate_table_header()
    lines.append(head)
    lines.append(sep)
    for c in report.candidates:
        lines.append(provider.render_candidate_row(c))
    lines.append("")
    return lines


def _render_analysis_block(
    c: Candidate, a: AnalysisFinding | None, provider: Provider
) -> list[str]:
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


def _render_common_themes(report: ResearchReport, provider: Provider) -> list[str]:
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
