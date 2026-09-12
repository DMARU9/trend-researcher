"""統合: グラフ全体の流れと境界の失敗経路（network / LLM はノード単位でモック）。

LLM 応答は `fake_model_factory` に**ノード名で**注入する（R-7 / LAYOUT-004-4）。
プロンプト本文の部分一致で応答を切り替えると、`extract_common` のプロンプトが
たまたま検索クエリ側の語を含む場合に別ノードの応答が返り、共通テーマが静かに
0 件になる（テストが無意味に緑になる）。

外部境界（検索・スレッド・字幕・ファイルシステム）は `tests/conftest.py` の
モックフィクスチャで差し替える（LAYOUT-003-3）。テストが実リポジトリの
`cache/` や `.env` の値に依存しないよう、このモジュールは `.env` を読ませない。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from trend_researcher import __main__ as main_module
from trend_researcher import config as config_module
from trend_researcher.config import Config, get_config
from trend_researcher.graph import render_report, trend_researcher
from trend_researcher.models import Candidate, Context, OutputFormat, ResearchReport

# --- ノード単位の LLM 応答（プロンプト本文に依存しない） ---------------------------------

_PARSE_RESPONSE_X = (
    "```json\n"
    '{"topic": "オタクの困りごと", "max_results": 5, "output_format": "markdown"}\n'
    "```"
)
_PARSE_RESPONSE_YOUTUBE = (
    "```json\n"
    '{"topic": "Claude Code の会社運用", "max_results": 5, "output_format": "json"}\n'
    "```"
)
#: 年号・期間表現は plan_search の `_clean_query` で除去される
_PLAN_RESPONSE_X = "オタク 困りごと\n推し活 大変\n同人 在庫"
_PLAN_RESPONSE_YOUTUBE = "Claude Code 会社運用 解説"
_ANALYZE_RESPONSE = """## 概要
要約です。ブログでどう扱えるかを詳しく説明します。

## ブログの活用アイデア
| 切り口 | 読者への価値 | 拾えるキーフレーズ |
|--------|--------------|---------------------|
| ポイントA | 価値A | 「キーフレーズA」 |
| ポイントB | 価値B | 「キーフレーズB」 |

## そのまま使える引用
- 「抜粋1」（文脈1）
- 「抜粋2」（文脈2）
"""
_EXTRACT_RESPONSE = """## 共通テーマ
### 自動化
- 説明: どちらも自動化の話をしている
- 該当: 全件
- 代表抜粋: 抜粋A
"""
_EMPTY_RESPONSE = ""

_X_RESPONSES: dict[str, str] = {
    "parse_instruction": _PARSE_RESPONSE_X,
    "plan_search": _PLAN_RESPONSE_X,
    "analyze_content": _ANALYZE_RESPONSE,
    "extract_common": _EXTRACT_RESPONSE,
}

_YOUTUBE_RESPONSES: dict[str, str] = {
    "parse_instruction": _PARSE_RESPONSE_YOUTUBE,
    "plan_search": _PLAN_RESPONSE_YOUTUBE,
    "analyze_content": _ANALYZE_RESPONSE,
    "extract_common": _EXTRACT_RESPONSE,
}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """実 `.env` と `TR_*` 環境変数を遮断する（FR-021: 実行環境に依存しない）。"""
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **k: None)
    for key in list(os.environ):
        if key.startswith(("TR_", "XTR_", "YTR_")):
            monkeypatch.delenv(key, raising=False)
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _candidates(platform: str, count: int) -> list[Candidate]:
    """境界モックが返す決定的な候補リスト（複数クエリで同じ id が返る状況も再現できる）。"""
    return [
        Candidate(
            platform=platform,
            id=f"{platform}{i}",
            title=f"タイトル{i}" if platform == "youtube" else "",
            text=f"本文 {i}" if platform == "x" else "",
            url=f"https://example.test/{platform}/{i}",
            author_handle=f"user{i}" if platform == "x" else "",
            author_name=f"チャンネル{i}" if platform == "youtube" else "",
            like_count=100 - i if platform == "x" else None,
            view_count=1000 * i if platform == "youtube" else None,
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            relevance_rank=i,
        )
        for i in range(1, count + 1)
    ]


#: 検索境界が返す固定プール（取得件数の上限はここで決まる）
_X_POOL = _candidates("x", 12)
_YOUTUBE_POOL = _candidates("youtube", 12)


def _x_search_responder(query: str, max_results: int = 5, **kwargs: Any) -> list[Candidate]:
    return _X_POOL[:max_results]


def _youtube_search_responder(query: str, max_results: int = 5, **kwargs: Any) -> list[Candidate]:
    return _YOUTUBE_POOL[:max_results]


def _run_graph(
    instruction: str,
    *,
    platform: str = "x",
    output_format: OutputFormat = OutputFormat.MARKDOWN,
    max_results: int = 5,
    sort_by: str = "relevance",
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """`__main__._run_async` と同じ形の入力でグラフを 1 回実行する。"""
    configurable: dict[str, Any] = {
        "platform": platform,
        "output_format": output_format.value,
        "max_results": max_results,
        "sort_by": sort_by,
    }
    if cache_dir is not None:
        configurable["cache_dir"] = str(cache_dir)
    initial_state = {
        "messages": [HumanMessage(content=instruction)],
        "platform": platform,
        "max_results": max_results,
    }
    return trend_researcher.invoke(initial_state, {"configurable": configurable})


def _node_phases(messages: list[Any]) -> list[tuple[str, str]]:
    """進捗行から (ノード名, フェーズ) を出現順に取り出す。

    重複は畳まない。ノードごとに「開始」「完了」が 1 回ずつ並ぶことを
    そのまま検証できるようにするため（重複を許す畳み込みは、進捗行が
    二重に emit されても緑になる）。
    """
    phases: list[tuple[str, str]] = []
    for message in messages:
        content = message.content if hasattr(message, "content") else str(message)
        if not re.match(r"^\[\d/7\] ", content):
            continue
        rest = content.split("] ", 1)[1]
        node, _, tail = rest.partition(" ... ")
        phases.append((node, tail.split("（")[0]))
    return phases


def _all_phases(*nodes: str) -> list[tuple[str, str]]:
    """指定ノードが「開始 → 完了」の順で並ぶ期待値を作る。"""
    return [(node, phase) for node in nodes for phase in ("開始", "完了")]


# --- 境界応答を固定プールにした実行フィクスチャ ---------------------------------


@pytest.fixture
def x_flow(fake_x_search, fake_x_threads) -> Iterator[Any]:
    """X の検索・スレッド境界を固定プールで差し替える。"""
    fake_x_search.responds(_x_search_responder)
    yield fake_x_search, fake_x_threads


@pytest.fixture
def youtube_flow(fake_yt_search, fake_yt_transcript) -> Iterator[Any]:
    """YouTube の検索・字幕境界を固定プールで差し替える。"""
    fake_yt_search.responds(_youtube_search_responder)
    yield fake_yt_search, fake_yt_transcript


# --- ノード単位の応答注入（R-7） ------------------------------------------------


def test_each_node_consumes_only_its_own_response(fake_model_factory, x_flow) -> None:
    """プロンプト本文の部分一致ではなく、ノード名で応答が決まる（R-7）。

    部分一致ディスパッチでは `extract_common` のプロンプトが検索クエリ応答と
    同一視され、共通テーマが静かに 0 件になっていた。
    """
    search, _threads = x_flow
    with fake_model_factory.install(
        {
            "parse_instruction": '{"topic": "注入トピック"}',
            "plan_search": "クエリA\nクエリB",
            "analyze_content": "## 概要\n注入された要約",
            "extract_common": "## 共通テーマ\n### 注入テーマ\n- 説明: 注入された説明",
        }
    ):
        result = _run_graph("オタクの困りごとを調査したい")

    report = result["report"]
    assert report.instruction.topic == "注入トピック"
    assert result["search_queries"] == ["クエリA", "クエリB"]
    assert search.call_count == 2  # クエリごとに 1 回
    assert {a.summary for a in report.analyses} == {"注入された要約"}
    assert [t.theme for t in report.common_themes] == ["注入テーマ"]


def test_node_responses_are_recorded_per_node(fake_model_factory, x_flow) -> None:
    with fake_model_factory.install(_X_RESPONSES):
        _run_graph("オタクの困りごとを調査したい")

    for node in ("parse_instruction", "plan_search", "analyze_content", "extract_common"):
        assert fake_model_factory.prompts_for(node), f"{node} にプロンプトが渡っていない"
    # analyze_content は候補ごとに 1 回（5 候補）、extract_common は 1 回だけ
    assert len(fake_model_factory.prompts_for("analyze_content")) == 5
    assert len(fake_model_factory.prompts_for("extract_common")) == 1


# --- X: 正常系 ----------------------------------------------------------------


def test_x_flow_produces_full_report(fake_model_factory, x_flow) -> None:
    with fake_model_factory.install(_X_RESPONSES):
        result = _run_graph("オタクの活動における困りごとを調査したい")

    report = result["report"]
    assert isinstance(report, ResearchReport)
    assert report.instruction.platform == "x"
    assert len(report.candidates) == 5
    assert len(report.analyses) == 5
    # R-7 の回帰ガード: 共通テーマが 0 件に潰れていない
    assert [t.theme for t in report.common_themes] == ["自動化"]
    assert report.common_themes[0].supporting_ids == [c.id for c in report.candidates]
    assert report.sources == [c.url for c in report.candidates]
    assert any("選定基準: 検索結果からいいね数の少ない順" in n for n in report.notes)

    md = render_report(report)
    assert "選定ツイートリスト" in md
    assert "**概要**" in md
    assert "| 切り口 | 読者への価値 | 拾えるキーフレーズ |" in md
    assert "| 自動化 |" in md


def test_x_flow_feeds_thread_and_replies_into_analysis(fake_model_factory, x_flow) -> None:
    """fetch が返したスレッド／リプライが要約プロンプトのソース本文に載る。"""
    _search, threads = x_flow
    threads.responds(
        lambda candidates, **kw: [
            Context(id=c.id, text=c.text, thread_text="親ツイート本文", replies=["リプライ1"])
            for c in candidates
        ]
    )

    with fake_model_factory.install(_X_RESPONSES):
        _run_graph("オタクの困りごとを調査したい")

    prompt = fake_model_factory.prompts_for("analyze_content")[0]
    assert "[親ツイート（スレッド）]" in prompt
    assert "[代表的なリプライ]" in prompt
    assert "- リプライ1" in prompt


def test_x_likes_sort_orders_candidates_descending_without_duplicates(fake_model_factory, x_flow) -> None:
    """likes モードでも重複した id はレポートに残らない（FR-024）。"""
    with fake_model_factory.install(_X_RESPONSES):
        result = _run_graph("Claude Code の使い方", sort_by="likes")

    candidates = result["report"].candidates
    ids = [c.id for c in candidates]
    assert len(candidates) == 5
    assert len(ids) == len(set(ids))
    assert [c.like_count for c in candidates] == sorted(
        [c.like_count for c in candidates], reverse=True
    )
    assert [c.relevance_rank for c in candidates] == [1, 2, 3, 4, 5]


def test_x_flow_progress_messages_follow_node_order(fake_model_factory, x_flow) -> None:
    with fake_model_factory.install(_X_RESPONSES):
        result = _run_graph("オタクの困りごとを調査したい")

    contents = [m.content for m in result["messages"]]
    assert "検索クエリ: オタク 困りごと, 推し活 大変, 同人 在庫" in contents
    # 7 ノード × (開始 + 完了) = 14 行。重複も欠落も許さない。
    assert _node_phases(result["messages"]) == _all_phases(
        "parse_instruction",
        "plan_search",
        "search",
        "fetch",
        "analyze_content",
        "extract_common",
        "compile_report",
    )


# --- YouTube: 正常系（出力形式の差） ---------------------------------------------


def test_youtube_flow_renders_markdown_table(fake_model_factory, youtube_flow) -> None:
    with fake_model_factory.install(_YOUTUBE_RESPONSES):
        result = _run_graph("機械学習チュートリアルを参考にブログを書きたい", platform="youtube")

    report = result["report"]
    assert report.instruction.platform == "youtube"
    assert len(report.candidates) == 5
    md = render_report(report)
    assert "選定動画リスト" in md
    assert "チャンネル" in md
    assert "再生数" in md
    assert "**本文**" not in md  # YouTube は本文ブロックを出さない


def test_youtube_flow_renders_json_when_requested(fake_model_factory, youtube_flow) -> None:
    with fake_model_factory.install(_YOUTUBE_RESPONSES):
        result = _run_graph(
            "機械学習チュートリアルを参考にブログを書きたい",
            platform="youtube",
            output_format=OutputFormat.JSON,
            max_results=10,
        )

    report = result["report"]
    assert report.instruction.output.format == OutputFormat.JSON
    assert len(report.candidates) == 10

    parsed = json.loads(render_report(report))
    assert len(parsed["candidates"]) == 10
    assert parsed["instruction"]["platform"] == "youtube"
    assert parsed["common_themes"][0]["theme"] == "自動化"


# --- 検索 0 件 → fetch / analyze / extract をスキップ（FR-007） --------------------


@pytest.mark.parametrize(
    ("platform", "flow_fixture", "subject"),
    [("x", "x_flow", "ツイート"), ("youtube", "youtube_flow", "動画")],
)
def test_empty_search_skips_the_rest_of_the_pipeline(
    request: pytest.FixtureRequest, fake_model_factory, platform: str, flow_fixture: str, subject: str
) -> None:
    search, fetch = request.getfixturevalue(flow_fixture)
    search.returns([])
    responses = _X_RESPONSES if platform == "x" else _YOUTUBE_RESPONSES

    with fake_model_factory.install(responses):
        result = _run_graph("存在しない話題を調査したい", platform=platform)

    report = result["report"]
    assert report.candidates == []
    assert report.analyses == []
    assert report.common_themes == []
    assert any(f"該当する{subject}が見つかりませんでした" in n for n in report.notes)
    # 後続ノードは実行されない（境界も LLM も呼ばれない）
    assert fetch.call_count == 0
    assert fake_model_factory.prompts_for("analyze_content") == []
    assert fake_model_factory.prompts_for("extract_common") == []
    assert _node_phases(result["messages"]) == _all_phases(
        "parse_instruction",
        "plan_search",
        "search",
        "compile_report",
    )


# --- 境界の失敗経路（data-model 1.3: partial / raises） ---------------------------


def test_search_failure_propagates(fake_model_factory, x_flow) -> None:
    """検索のリトライ枯渇は握りつぶさず伝播する（data-model 1.3: x_search raises）。"""
    search, _threads = x_flow
    search.raises(RuntimeError("リトライ枯渇"))

    with fake_model_factory.install(_X_RESPONSES), pytest.raises(RuntimeError, match="リトライ枯渇"):
        _run_graph("オタクの困りごとを調査したい")


def test_thread_fetch_failure_degrades_to_text_only(fake_model_factory, x_flow) -> None:
    """スレッド取得の失敗は備考に残し、本文だけで解析を続ける。"""
    _search, threads = x_flow
    threads.raises(ConnectionError("スレッド取得に失敗"))

    with fake_model_factory.install(_X_RESPONSES):
        result = _run_graph("オタクの困りごとを調査したい")

    report = result["report"]
    assert any("スレッド取得に失敗しました（本文のみで解析）" in n for n in report.notes)
    assert len(report.analyses) == 5
    # フォールバックのコンテキストは本文のみ
    assert result["contexts"][0].thread_text == ""
    prompt = fake_model_factory.prompts_for("analyze_content")[0]
    assert "[親ツイート（スレッド）]" not in prompt
    assert "[本文]" in prompt


def test_partial_thread_contexts_are_reported_in_progress(fake_model_factory, x_flow) -> None:
    """一部の候補で追加文脈が取れない場合、その件数が進捗に残る。"""
    _search, threads = x_flow
    threads.responds(lambda candidates, **kw: [Context(id=c.id, text="") for c in candidates])

    with fake_model_factory.install(_X_RESPONSES):
        result = _run_graph("オタクの困りごとを調査したい")

    contents = [m.content for m in result["messages"]]
    assert any("コンテキスト取得 5 件（追加文脈なし 5 件）" in c for c in contents)
    assert len(result["report"].analyses) == 5


def test_youtube_missing_transcript_records_note(fake_model_factory, youtube_flow) -> None:
    """字幕が空でもメタデータのみで解析を続け、理由を備考に残す（FR-009）。"""
    _search, transcript = youtube_flow
    transcript.responds(lambda video_id, language="ja": Context(id=video_id, text="   "))

    with fake_model_factory.install(_YOUTUBE_RESPONSES):
        result = _run_graph("機械学習チュートリアルを参考にブログを書きたい", platform="youtube")

    report = result["report"]
    assert any("字幕取得不可" in n for n in report.notes)
    assert len(report.analyses) == 5


def test_llm_empty_response_degrades_without_crashing(fake_model_factory, x_flow) -> None:
    """LLM の空応答（data-model 1.3: llm empty）でもレポートは組み上がる。"""
    with fake_model_factory.install(
        {
            "parse_instruction": _EMPTY_RESPONSE,
            "plan_search": _EMPTY_RESPONSE,
            "analyze_content": _EMPTY_RESPONSE,
            "extract_common": _EMPTY_RESPONSE,
        }
    ):
        result = _run_graph("オタクの困りごとを調査したい")

    report = result["report"]
    # 構造化ブロックが無い場合はトピックが指示本文全体にフォールバックする
    assert report.instruction.topic == "オタクの困りごとを調査したい"
    assert report.candidates == []  # クエリが空 → 検索 0 件 → ルーティング skip
    assert report.common_themes == []
    assert "（特筆すべき共通点なし）" in render_report(report)


def test_llm_unstructured_responses_fall_back_to_defaults(fake_model_factory, x_flow) -> None:
    """JSON ブロックなし・見出しなしの応答でも既定値で処理を続ける（partial）。"""
    with fake_model_factory.install(
        {
            "parse_instruction": "特に指定はありません",
            "plan_search": "オタク 困りごと",
            "analyze_content": "見出しのない要約文です。",
            "extract_common": "共通点は見つかりませんでした。",
        }
    ):
        result = _run_graph("オタクの困りごとを調査したい")

    report = result["report"]
    assert report.instruction.topic == "オタクの困りごとを調査したい"
    assert report.instruction.max_results == 5
    assert len(report.analyses) == 5
    assert {a.summary for a in report.analyses} == {"見出しのない要約文です。"}
    assert report.common_themes == []


# --- ファイルシステム境界（data-model 1.3: ok / raises） -------------------------


def test_report_is_written_to_the_configured_cache_dir(
    fake_model_factory, x_flow, tmp_path: Path
) -> None:
    """`--cache-dir`（Configuration.cache_dir）が永続化先として機能する（FR-012/FR-014）。"""
    cache_dir = tmp_path / "cache"

    with fake_model_factory.install(_X_RESPONSES):
        result = _run_graph("オタクの困りごとを調査したい", cache_dir=cache_dir)

    written = json.loads((cache_dir / "report.json").read_text(encoding="utf-8"))
    assert written == result["report"].model_dump(mode="json")


def test_unwritable_cache_dir_is_recorded_and_the_run_succeeds(
    fake_model_factory, x_flow, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """書き込み不可のパスでも縮退して継続し、理由を進捗に残す（FR-009）。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("ファイルなので配下にディレクトリを作れない", encoding="utf-8")

    with fake_model_factory.install(_X_RESPONSES):
        result = _run_graph("オタクの困りごとを調査したい", cache_dir=blocker / "cache")

    assert result["report"].candidates  # レポートは返る
    assert any("キャッシュ書き込み失敗" in m.content for m in result["messages"])
    assert "キャッシュ書き込み失敗" in capsys.readouterr().err


def _capture_cli_invocation(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], config: Config
) -> dict[str, Any]:
    """`_run_async` がグラフへ渡した state / config を記録する（グラフだけ差し替える）。"""
    captured: dict[str, Any] = {}

    class _Recorder:
        async def ainvoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
            captured["state"] = state
            captured["config"] = config
            return {"report": None}

    monkeypatch.setattr(main_module, "trend_researcher", _Recorder())
    args = main_module._parse_args(argv)
    asyncio.run(main_module._run_async(args, config))
    return captured


def test_cli_wires_cache_dir_into_the_runnable_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--cache-dir` が Configuration まで届く（`_run_async` の配線）。"""
    config = Config.load(platform="x", cache_dir=str(tmp_path))
    captured = _capture_cli_invocation(
        monkeypatch, ["オタクの困りごと", "--platform", "x", "--cache-dir", str(tmp_path)], config
    )

    assert captured["config"]["configurable"]["cache_dir"] == str(tmp_path)
    assert captured["state"]["platform"] == "x"


def test_cli_omits_max_results_from_state_when_not_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--max-results` 未指定では件数を state に載せない。

    常に 5 を載せると、ノード側で「明示指定」と区別できず本文の自然言語
    （「20件」）が無視される（FR-011）。
    """
    config = Config.load(platform="x", cache_dir=str(tmp_path))
    captured = _capture_cli_invocation(monkeypatch, ["20件の動画を調べて", "--platform", "x"], config)

    assert "max_results" not in captured["state"]


def test_cli_passes_explicit_max_results_even_when_it_is_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """明示指定は既定値と同じ 5 でも state に載せる（FR-011: 明示指定が最優先）。"""
    config = Config.load(platform="x", cache_dir=str(tmp_path))
    captured = _capture_cli_invocation(
        monkeypatch, ["20件の動画を調べて", "--platform", "x", "--max-results", "5"], config
    )

    assert captured["state"]["max_results"] == 5
