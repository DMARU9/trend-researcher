"""fetch ノード（FR-006 対応、X: スレッド/リプライ / YouTube: 字幕、共通）。"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration
from trend_researcher.models import Candidate, Context, Failure
from trend_researcher.progress import NODE_FETCH, make_emitter
from trend_researcher.providers import get_provider
from trend_researcher.state import AgentState

#: 追加文脈が 1 つも取れなかったときの `Failure.error_type`。
#: 取得の失敗は provider の内側で握られ、空の `Context` として外に出てくる
#: （`providers/x.py` / `tools/x_search.py` は例外型を外へ渡さない）。例外が
#: 伴わない失敗なので、例外型名ではなく**失敗の種類**として固定の名前を入れる
#: （data-model §3.3 の `error_type` の目的は「後から理由を辿れること」であり、
#: 例外型名であること自体は目的ではない。例外型名を捏造するよりは空の文脈で
#: あることをそのまま示す方が辿れる）。
CONTEXT_FAILURE_TYPE = "MissingContext"


def _context_failures(candidates: list[Candidate], contexts: list[Context]) -> list[Failure]:
    """追加文脈を 1 つも取得できなかった候補を `Failure(kind="context")` にする（FR-022 / FR-021）。

    判定は「対応する `Context` が無い」または「`text` / `thread_text` / `replies` が
    すべて空」だけを見る。platform ごとの差（どの例外を握るか、取得できなかった
    ときに何を返すか）は provider が既に `Context` の空欄として表しているので、
    コアは理由を解釈しない（原則 IV）。

    一括取得が丸ごと失敗した場合は provider が候補の本文で `Context` を作る
    （非空）ため、ここには載らない。その場合は既存の `notes` の文言
    （`スレッド取得に失敗しました（本文のみで解析）`）が失敗を伝えているので、
    無言の欠落にはならない（契約 §7-1 の文言は変更しない）。
    """
    by_id = {c.id: c for c in contexts}
    failures: list[Failure] = []
    for candidate in candidates:
        context = by_id.get(candidate.id)
        if context is not None and (
            context.text.strip() or context.thread_text.strip() or context.replies
        ):
            continue
        failures.append(
            Failure(
                kind="context",
                id=candidate.id,
                error_type=CONTEXT_FAILURE_TYPE,
                message="追加文脈を取得できませんでした（本文のみで解析）",
            )
        )
    return failures


def fetch_node(state: AgentState, config: RunnableConfig) -> dict:
    """provider.fetch_contexts を呼び出し、要約用ソースを取得する。"""
    configurable = Configuration.from_runnable_config(config)
    emitter = make_emitter()
    emitter.emit(NODE_FETCH, "開始")
    progress_messages = emitter.get_messages()

    platform = state.get("platform") or configurable.platform
    provider = get_provider(platform)
    # 固有設定（X の accounts_db 等）の解決は provider の内部で行われる
    # （ノードは解決の実装にも環境にも触れない。SET-003 / SET-004）
    candidates = state.get("candidates", [])
    instruction = state.get("instruction")
    sort_by = (instruction.sort_by if instruction else None) or "relevance"
    contexts, notes = provider.fetch_contexts(candidates, configurable)

    # tweet_details で正確な like_count 等が確定したので、fetch 後に並び替える
    if candidates:
        candidates = provider.resort(candidates, sort_by)

    notes = list(state.get("notes", [])) + notes
    # 取得できなかった候補は記録に残す（FR-021 / FR-022）。前の段の記録は上書きしない
    failures = list(state.get("failures", [])) + _context_failures(candidates, contexts)
    no_context = sum(1 for c in contexts if not c.text.strip() and not c.thread_text and not c.replies)
    emitter.emit(

        NODE_FETCH,
        "完了",
        detail=f"コンテキスト取得 {len(contexts)} 件（追加文脈なし {no_context} 件）",
    )
    # 蓄積済みの「開始」を二重に載せない（`extend` すると開始行が重複する）。
    progress_messages = emitter.get_messages()
    return {
        "candidates": candidates,
        "contexts": contexts,
        "notes": notes,
        "failures": failures,
        "messages": progress_messages,
    }
