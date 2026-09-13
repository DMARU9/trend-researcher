"""compile_report ノード（FR-009/FR-010 対応、markdown/json 両対応）。X / YouTube 共通。"""

from __future__ import annotations

from pathlib import Path

from langchain_core.runnables import RunnableConfig

from trend_researcher.cache import write_json
from trend_researcher.configuration import Configuration
from trend_researcher.models import ResearchReport
from trend_researcher.progress import NODE_COMPILE_REPORT, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.rendering import render_markdown
from trend_researcher.state import AgentState


def compile_report(state: AgentState, config: RunnableConfig) -> dict:
    """選定コンテンツ・要約・共通ネタをまとめた ResearchReport を組み立てる。"""
    configurable = Configuration.from_runnable_config(config)
    emitter = make_emitter()
    emitter.emit(NODE_COMPILE_REPORT, "開始")
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

    # 選定基準の注記は provider が文面を持つ（コアは文面を組み立てない）
    notes.append(provider.selection_note(instruction.sort_by or "relevance"))

    if not candidates:
        notes.append(
            f"該当する{provider.content_noun}が見つかりませんでした"
            "（検索クエリまたは期間フィルタの条件に一致する投稿なし）。"
        )

    sources = [c.url for c in candidates if c.url]

    report = ResearchReport(
        instruction=instruction,
        candidates=candidates,
        analyses=analyses,
        common_themes=common_themes,
        sources=sources,
        notes=notes,
    )

    emitter.emit(NODE_COMPILE_REPORT, "完了")

    # 永続化先は Configuration（CLI --cache-dir / TR_CACHE_DIR）から渡る。
    # state は Studio 入力や将来の途中再開による上書き用。
    cache_dir = state.get("cache_dir") or configurable.cache_dir
    if cache_dir:
        try:
            write_json(Path(cache_dir), "report", report.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            emitter.emit(NODE_COMPILE_REPORT, f"キャッシュ書き込み失敗: {exc}")

    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()

    # チャット表示用は常に Markdown で描画（CLI の出力形式指定は影響しない）
    from langchain_core.messages import AIMessage

    rendered = render_markdown(report, provider)

    summary = f"レポート完了: {len(candidates)} 件の候補を分析し、{len(common_themes)} 件の共通テーマを抽出しました。"
    progress_messages.append(AIMessage(content=summary))
    progress_messages.append(AIMessage(content=rendered))
    return {"report": report, "messages": progress_messages}
