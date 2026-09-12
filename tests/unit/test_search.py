"""nodes/search.py が返す `messages`（進捗行と検索クエリ行）の契約を固定する。

対象は `nodes/search.py` の**戻り値**。この契約は統合テスト（graph 経由）では
検証できない: LangGraph の `add_messages` が同一オブジェクトの id で畳み込む
ため、ノードが「開始」を二重に載せてもグラフの state では 1 行に潰れる
（`tasks.md` の T028「観測点」表 / 変異探針（3）で実測済み）。したがって
ノード単体の戻り値を直接見る以外に検出手段がない（LAYOUT-006-4）。

検索境界（`providers.x.search_tweets`）は conftest のフィクスチャで差し替える
（LAYOUT-003-3）。LLM は呼ばない。
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from trend_researcher.models import ResearchInstruction
from trend_researcher.nodes.search import search_node


def _config(**configurable: Any) -> RunnableConfig:
    return {"configurable": configurable}


def _instruction(**overrides: Any) -> ResearchInstruction:
    base: dict[str, Any] = {
        "raw_text": "オタクの活動における困りごとを調査したい",
        "platform": "x",
        "topic": "オタクの困りごと",
    }
    base.update(overrides)
    return ResearchInstruction(**base)


def _state(queries: list[str] | None = None, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "instruction": _instruction(),
        "search_queries": ["オタク 困りごと", "推し活 大変"] if queries is None else queries,
    }
    base.update(overrides)
    return base


# --- 戻り値の契約（LAYOUT-006-3 / LAYOUT-006-4） ----------------------------


def test_progress_messages_report_start_then_finish(fake_x_search: Any) -> None:
    """戻り値は [開始, 完了, 検索クエリ行] の 3 件で、開始が重複しない。

    末尾の `progress_messages = emitter.get_messages()` を
    `progress_messages.extend(emitter.get_messages())` に戻すと、開始が 2 件に
    なってこの断言が落ちる（T047 の変異探針で実測）。

    候補数は「クエリごとに返る 3 件（conftest の既定応答）を id で重複除去した
    3 件」。詳細行の件数まで固定するのは、進捗行が件数を報告する契約だからである。
    """
    out = search_node(_state(), _config())

    assert [m.content for m in out["messages"]] == [
        "[3/7] search ... 開始",
        "[3/7] search ... 完了（3 件を選定）",
        "検索クエリ: オタク 困りごと, 推し活 大変",
    ]


def test_progress_messages_report_zero_candidates(fake_x_search: Any) -> None:
    """候補 0 件でも戻り値は [開始, 完了, 検索クエリ行] の 3 件のまま。

    検索 0 件は後続をスキップする縮退経路（FR-007）であり、`emitter` に
    エラー行が足される経路ではない。ゼロ件でも行数が増減しないことを固定する。
    """
    fake_x_search.returns([])

    out = search_node(_state(queries=[]), _config())

    assert [m.content for m in out["messages"]] == [
        "[3/7] search ... 開始",
        "[3/7] search ... 完了（0 件を選定）",
        "検索クエリ: ",
    ]


def test_count_comes_from_instruction_even_when_configuration_differs(
    fake_x_search: Any,
) -> None:
    """provider へ渡す件数は `instruction.max_results`（FR-011 の解決結果）に従う。

    `parse_instruction` は件数を state > Configuration > 自然言語 > LLM の順に
    解決して `instruction.max_results` に書き込む（FR-011）。search 側にも
    `configurable.max_results != 5` のセンチネルがあると、state と Configuration が
    食い違う入力で優先順位が逆転し、`instruction.max_results`（報告される件数）と
    実際に取得する件数がずれる。

    ここでは state / instruction が 100 件、Configuration が 1 件という乖離を作る。
    conftest の既定応答は「クエリごとに 3 件 → id 重複除去で 3 件」なので、
    正しくは `ordered[:100]` で 3 件、センチネルがあると `ordered[:1]` で 1 件に
    なる（T049 の変異探針で実測: 3 件 → 1 件）。
    """
    out = search_node(
        _state(instruction=_instruction(max_results=100), max_results=100),
        _config(max_results=1),
    )

    assert len(out["candidates"]) == 3
    # 取得プールが 100 件（= instruction.max_results）基準で組まれていること。
    # 関連度順のプールは `max(max_results * 3, max_results + 20)`。
    assert fake_x_search.calls[0][1]["max_results"] == 300


def test_falsy_count_is_treated_as_the_default_five(fake_x_search: Any) -> None:
    """`instruction.max_results` が 0 のときは既定の 5 件として取得する（FR-011 の既定）。

    `--max-results 0` は 0 が falsy のため `__main__._run_async` の
    `args.max_results or 5` で 5 に戻り、state にだけ 0 が載る
    （`_print_summary` の `instruction.max_results or config.max_results` も同じ扱い）。
    search が 0 をそのまま使うと候補 0 件の縮退経路（FR-007）に入ってしまうため、
    この行でも同じ既定へ戻す。`or 5` を外すと候補が 3 件ではなく 0 件になる。
    """
    out = search_node(_state(instruction=_instruction(max_results=0), max_results=0), _config())

    assert len(out["candidates"]) == 3
