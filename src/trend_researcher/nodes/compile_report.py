"""compile_report ノード（FR-009/FR-010 対応、markdown/json 両対応）。X / YouTube 共通。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from trend_researcher.cache import write_json
from trend_researcher.configuration import Configuration
from trend_researcher.models import (
    Candidate,
    CompressedSource,
    Context,
    Degradation,
    Failure,
    ResearchReport,
)
from trend_researcher.progress import NODE_COMPILE_REPORT, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.rendering import render_markdown
from trend_researcher.state import AgentState


def _breakdown_note(
    compressed: list[CompressedSource],
    degradations: list[Degradation],
    failures: list[Failure],
) -> str:
    """内訳（圧縮・縮退・失敗の件数）の 1 行（FR-029）。

    3 つとも 0 件なら空文字を返す（呼び出し側が `note()` を出さない）。既定の入力
    ではこの補足行は現れない（D-3 / FR-035）。
    """
    if not compressed and not degradations and not failures:
        return ""
    return (
        f"内訳: 圧縮 {len(compressed)} 件 / "
        f"縮退 {len(degradations)} 段 / 失敗 {len(failures)} 件"
    )


def _release_raw_material(contexts: list[Context], candidates: list[Candidate]) -> None:
    """後続段で不要になった生データの中身を解放する（FR-027 / data-model §4.3）。

    `Context` / `Candidate` のレコード（id / url / counts など）は残す。レポートは
    `Candidate` を参照するため、この関数は**レポート確定後**にのみ呼ぶ（順序を
    逆にすると報告書の候補が空になる）。

    引数のオブジェクトを**その場で書き換える**ため、呼び出し側が所有している
    （= 取得元と共有していない）リストだけを渡すこと。`compile_report` は state から
    受け取った直後に写しを取り、その写しを渡す。
    """
    for context in contexts:
        context.text = ""
        context.thread_text = ""
        context.replies = []
    for candidate in candidates:
        candidate.text = ""


def compile_report(state: AgentState, config: RunnableConfig) -> dict:
    """選定コンテンツ・要約・共通ネタをまとめた ResearchReport を組み立てる。"""
    configurable = Configuration.from_runnable_config(config)
    emitter = make_emitter()
    emitter.emit(NODE_COMPILE_REPORT, "開始")
    progress_messages = emitter.get_messages()

    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    instruction = state["instruction"]
    # 生データを解放する（FR-027）ため、この段が state の中身を**占有**する。
    # 渡されたオブジェクトをその場で書き換えると、境界（検索ツールの戻り値・テストの
    # 固定プール）が同じオブジェクトを保持している場合に取得元まで壊れる（実測:
    # 固定プールが空になり、以降の実行で解析が 0 件になった）。写しを取ってから解放する
    candidates = [c.model_copy() for c in state.get("candidates", [])]
    contexts = [c.model_copy() for c in state.get("contexts", [])]
    analyses = state.get("analyses", [])
    common_themes = state.get("common_themes", [])
    # `failures` は前の段の記録（解析・文脈取得）。件数と理由の確認に使う（FR-023）
    failures = list(state.get("failures", []))
    # 中間データ（US2 の圧縮・US3 の縮退）は内訳の補足行と `cache/` の書き出しに使う
    compressed = list(state.get("compressed", []))
    degradations = list(state.get("degradations", []))
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
    elif not analyses and failures:
        # 全件失敗のときだけ 1 行足す（US4 シナリオ 3 / FR-021）。一部失敗では
        # 足さない（既定の入力の `report.notes` を増やさない = FR-035）。
        # 候補 0 件は「全件失敗」ではないので `elif` で外す
        notes.append(f"解析 0 件（すべて失敗: {len(failures)} 件）")

    sources = [c.url for c in candidates if c.url]

    # レポートは候補の**写し**を持つ。解放（FR-027）は state 側の中身を空にするため、
    # 同じオブジェクトを参照させると確定済みレポートの候補まで空になり、書き出した
    # `cache/report.json` と返すレポートが食い違う（data-model §4.3 の順序の効果を
    # レポート側でも保つ）
    report = ResearchReport(
        instruction=instruction,
        candidates=[c.model_copy() for c in candidates],
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
            # 中間データは `include_intermediate` が真のときだけ書く（契約 §5）。
            # 既定（偽）の出力は変更前と一致させる（SC-026）。解放の**前**に書くこと
            # （後だと生データが空になったものが残る。data-model §4.3）
            if configurable.include_intermediate:
                write_json(
                    Path(cache_dir), "compressed", [c.model_dump(mode="json") for c in compressed]
                )
                write_json(
                    Path(cache_dir),
                    "degradations",
                    [d.model_dump(mode="json") for d in degradations],
                )
                write_json(
                    Path(cache_dir), "failures", [f.model_dump(mode="json") for f in failures]
                )
            write_json(Path(cache_dir), "report", report.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001
            emitter.emit(NODE_COMPILE_REPORT, f"キャッシュ書き込み失敗: {exc}")

    # 追加の観測は `note()` に出す（`emit()` の書式と `messages` は不変。FR-030 / D-3）
    breakdown = _breakdown_note(compressed, degradations, failures)
    if breakdown:
        emitter.note(breakdown)

    # レポート・中間データが確定した後に生データを解放する（FR-027 / data-model §4.3）
    _release_raw_material(contexts, candidates)

    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()

    # チャット表示用は常に Markdown で描画（CLI の出力形式指定は影響しない）
    from langchain_core.messages import AIMessage

    rendered = render_markdown(report, provider)

    summary = f"レポート完了: {len(candidates)} 件の候補を分析し、{len(common_themes)} 件の共通テーマを抽出しました。"
    progress_messages.append(AIMessage(content=summary))
    progress_messages.append(AIMessage(content=rendered))
    # 解放したリストを返す（state のレコードは残し、中身だけを空にする）
    updates: dict[str, Any] = {"report": report, "messages": progress_messages}
    if "contexts" in state:
        updates["contexts"] = contexts
    if "candidates" in state:
        updates["candidates"] = candidates
    return updates
