"""レポート描画の golden 比較（SC-006 / FR-018 / RND-003 / RND-007）。

golden は「変更前のツリー」から採取した期待出力（`tests/unit/golden/`）である。
本モジュールは 2 つの役割を持つ。

1. `build_golden_cases()`: 代表入力 3 件の `ResearchReport` と `Provider` の組を作る。
   **既定値に依存する値を明示する**（US1 で `platform` の既定が `"x"` → `""` に変わるため、
   既定に委ねると golden が意図せず変化する）。`generated_at` も固定する
   （`default_factory=datetime.now` のままだと `render_json` が毎回変わり flaky になる）。
2. golden ファイルとの byte 比較（Markdown は完全一致、JSON は削除対象 2 キーのみ除外）。

LLM・LangGraph・境界モックを使わない（RND-007）。
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trend_researcher.models import (
    AnalysisFinding,
    BlogAngle,
    Candidate,
    CommonTheme,
    OutputFormat,
    OutputSpec,
    ResearchInstruction,
    ResearchReport,
)
from trend_researcher.providers import get_provider
from trend_researcher.providers.base import Provider
from trend_researcher.rendering import render_json, render_markdown

#: 代表入力 3 件のキー。golden ファイル名の接頭辞でもある。
GOLDEN_CASE_NAMES = ("x_full", "youtube_full", "sparse")

#: 決定論のため固定する生成時刻（`ResearchReport.generated_at` の既定は `datetime.now`）。
FIXED_GENERATED_AT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

#: golden ファイルの置き場所。
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

#: JSON 比較で両側から除去するキー（RND-003）。
#:
#: `render_json` は `report.model_dump_json(indent=2, exclude_none=True)` を返すため、
#: FR-009 で削除する `ResearchInstruction.use_trends` と FR-008 で削除する
#: `OutputSpec.table_for` が JSON から消える。これは削除要件に必然的に伴う
#: **意図的な差分**であり、当該 2 キーだけを比較対象から外す。
JSON_EXCLUDED_KEYS = frozenset({"use_trends", "table_for"})


def build_golden_cases() -> dict[str, tuple[ResearchReport, Provider]]:
    """golden 比較の代表入力 3 件を組み立てる（RND-003）。

    戻り値は `{ケース名: (report, provider)}`。`provider` は `build_graph()` を
    通さずに `get_provider()` で解決した「本番と同じ実装」を使う（描画の
    プラットフォーム差を実装そのもので代表させるため）。
    """
    return {
        "x_full": _x_full_case(),
        "youtube_full": _youtube_full_case(),
        "sparse": _sparse_case(),
    }


def _output() -> OutputSpec:
    """既定に依存しないよう `format` を明示した出力指定。"""
    return OutputSpec(format=OutputFormat.MARKDOWN)


def _instruction(platform: str, topic: str, *, sort_by: str = "relevance", max_results: int = 3) -> ResearchInstruction:
    return ResearchInstruction(
        raw_text=f"{topic} について調べて",
        platform=platform,
        topic=topic,
        max_results=max_results,
        output=_output(),
        sort_by=sort_by,
        transcript_language="ja",
    )


def _x_candidate(idx: int, **overrides: Any) -> Candidate:
    base: dict[str, Any] = {
        "platform": "x",
        "id": f"t{idx}",
        "text": f"本文{idx}です。2行目のテキスト。",
        "url": f"https://example.test/x/{idx}",
        "author_handle": f"user{idx}",
        "author_name": f"ユーザー{idx}",
        "author_followers": 100 * idx,
        "like_count": 10 * idx,
        "retweet_count": 2 * idx,
        "quote_count": idx,
        "published_at": datetime(2026, 1, idx, 9, 0, tzinfo=UTC),
        "relevance_rank": idx,
    }
    base.update(overrides)
    return Candidate(**base)


def _youtube_candidate(idx: int, **overrides: Any) -> Candidate:
    base: dict[str, Any] = {
        "platform": "youtube",
        "id": f"v{idx}",
        "title": f"動画{idx}のタイトル",
        "url": f"https://example.test/youtube/{idx}",
        "channel_id": f"channel{idx}",
        "author_name": f"チャンネル{idx}",
        "view_count": 1000 * idx,
        "published_at": datetime(2026, 1, idx, 9, 0, tzinfo=UTC),
        "relevance_rank": idx,
    }
    base.update(overrides)
    return Candidate(**base)


def _x_full_case() -> tuple[ResearchReport, Provider]:
    """(1) X の完全形。本文・解析（アイデア／引用）・共通テーマ・備考が揃う。"""
    c1, c2 = _x_candidate(1), _x_candidate(2, like_count=None, retweet_count=None, quote_count=None)
    analyses = [
        AnalysisFinding(
            id="t1",
            title="タイトル1",
            summary="要約1",
            angles=[
                BlogAngle(angle="切り口A", value="価値A", key_phrase="フレーズA"),
                BlogAngle(angle="切り口B", value="価値B", key_phrase="フレーズB"),
            ],
            key_points=["要点1"],
            evidence=["引用1", "引用2"],
        ),
        AnalysisFinding(id="t2", summary="要約2"),
    ]
    themes = [
        CommonTheme(
            theme="テーマA",
            description="説明A",
            supporting_ids=["t1", "t2"],
            example_quotes=["引用A"],
        ),
        CommonTheme(theme="テーマB", description="説明B"),
    ]
    report = ResearchReport(
        instruction=_instruction("x", "AI 動向", sort_by="likes", max_results=2),
        generated_at=FIXED_GENERATED_AT,
        candidates=[c1, c2],
        analyses=analyses,
        common_themes=themes,
        sources=[c.url for c in (c1, c2)],
        notes=[
            "投稿日フィルタ: 2026-01-05 以降に公開された投稿を対象",
            "選定基準: 検索結果からいいね数の多い順に上位 N 件を採用",
        ],
    )
    return report, get_provider("x")


def _youtube_full_case() -> tuple[ResearchReport, Provider]:
    """(2) YouTube の完全形。本文セクションを持たないブロックを代表させる。"""
    c1, c2 = _youtube_candidate(1), _youtube_candidate(2, view_count=None)
    analyses = [
        AnalysisFinding(
            id="v1",
            title="動画1のタイトル",
            summary="要約1",
            angles=[BlogAngle(angle="切り口A", value="価値A", key_phrase="フレーズA")],
            evidence=["引用1"],
        ),
        AnalysisFinding(id="v2", title="動画2のタイトル", summary="要約2"),
    ]
    themes = [
        CommonTheme(theme="テーマA", description="説明A", supporting_ids=["v1"], example_quotes=["引用A"])
    ]
    report = ResearchReport(
        instruction=_instruction("youtube", "Python 入門", max_results=2),
        generated_at=FIXED_GENERATED_AT,
        candidates=[c1, c2],
        analyses=analyses,
        common_themes=themes,
        sources=[c.url for c in (c1, c2)],
        notes=[
            "投稿日フィルタ: 2026-01-05 以降に公開された投稿を対象",
            "選定基準: 検索結果の関連度順に上位 N 件を採用",
        ],
    )
    return report, get_provider("youtube")


def _sparse_case() -> tuple[ResearchReport, Provider]:
    """(3) 欠落形。分析・共通テーマ・出典・備考が空で、本文も持たない。

    RND-004 の「本文なし」「要約なし（解析なしプレースホルダ）」「テーマなし」を
    代表させる。
    """
    candidate = _x_candidate(1, text="", url="", author_followers=None, like_count=None)
    report = ResearchReport(
        instruction=_instruction("x", "欠落ケース", max_results=1),
        generated_at=FIXED_GENERATED_AT,
        candidates=[candidate],
        analyses=[],
        common_themes=[],
        sources=[],
        notes=[],
    )
    return report, get_provider("x")


# ---------------------------------------------------------------------------
# golden 比較（SC-006 / FR-018）
# ---------------------------------------------------------------------------


def test_golden_case_names_match_build_cases() -> None:
    """`GOLDEN_CASE_NAMES` と実際に生成されるケースが一致する（golden の取り違え防止）。"""
    assert tuple(build_golden_cases()) == GOLDEN_CASE_NAMES


def _normalize_json(raw: str) -> str:
    """JSON を辞書へ読み戻し、除外キーを除いてから比較用の文字列にする。

    両側を同じ手順で正規化するため、キー順と値の差だけが残る（RND-003）。
    """
    return json.dumps(_drop_excluded_keys(json.loads(raw)), indent=2, ensure_ascii=False)


def _drop_excluded_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_excluded_keys(v) for k, v in value.items() if k not in JSON_EXCLUDED_KEYS}
    if isinstance(value, list):
        return [_drop_excluded_keys(v) for v in value]
    return value


def _golden_text(name: str, suffix: str) -> str:
    path = GOLDEN_DIR / f"{name}.{suffix}"
    if not path.exists():
        pytest.fail(
            f"golden が未採取です: {path}\n"
            "quickstart.md の手順 4-1（変更前のツリーでの採取）を実行してください。"
        )
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", GOLDEN_CASE_NAMES)
def test_render_markdown_matches_golden(name: str) -> None:
    """Markdown は分離前後で byte 一致する（末尾の改行を含む）。"""
    report, provider = build_golden_cases()[name]

    assert render_markdown(report, provider) == _golden_text(name, "md")


@pytest.mark.parametrize("name", GOLDEN_CASE_NAMES)
def test_render_json_matches_golden(name: str) -> None:
    """JSON は削除対象 2 キー（use_trends / table_for）を除いて byte 一致する。"""
    report, _provider = build_golden_cases()[name]

    assert _normalize_json(render_json(report)) == _normalize_json(_golden_text(name, "json"))

def test_markdown_uses_passed_provider() -> None:
    """描画は**渡された** provider を使う（FR-017 / RND-007）。

    X のレポートに YouTube の provider を渡す組で検証する。描画が引数を無視して
    `report.instruction.platform` から解決し直すと、出力はレポート側の表現になる。
    """
    report, x_provider = build_golden_cases()["x_full"]
    youtube_provider = get_provider("youtube")

    passed = render_markdown(report, youtube_provider)
    resolved = render_markdown(report, x_provider)

    # 節見出し・共通テーマの列名は provider が文面を持つ（コアは文面を組み立てない）
    assert youtube_provider.candidates_section_title in passed
    assert youtube_provider.common_theme_supporting_label in passed
    assert x_provider.candidates_section_title not in passed
    assert passed != resolved

#: 骨格モジュール（描画を参照してはならない）。
GRAPH_PATH = Path(__file__).resolve().parents[2] / "src" / "trend_researcher" / "graph.py"


#: 骨格が参照してはならない描画の名前（FR-016）。
RENDERING_NAMES = frozenset({"render_report", "render_markdown", "render_json"})


def test_graph_does_not_reference_rendering() -> None:
    """`graph.py` は描画を参照しない（FR-016）。

    骨格（グラフ構築と実行エントリ）が描画を知ると、描画の変更が骨格に波及する。
    AST で import と名前（属性アクセス・関数定義名を含む）を走査する。
    """
    tree = ast.parse(GRAPH_PATH.read_text(encoding="utf-8"))
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            referenced.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            referenced.add((node.module or "").split(".")[-1])
            referenced.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)

    assert "rendering" not in referenced
    assert not (RENDERING_NAMES & referenced)

# ---------------------------------------------------------------------------
# 単体の描画契約（旧 `tests/unit/test_compile_report.py` から移設。REM-009 / SC-008）
# ---------------------------------------------------------------------------


def _candidate(idx: int = 1, platform: str = "x", **overrides: Any) -> Candidate:
    """テスト用候補。counts は idx から決定的に導出する。"""
    base: dict[str, Any] = {
        "platform": platform,
        "id": f"t{idx}" if platform == "x" else f"v{idx}",
        "url": f"https://example.test/{idx}",
        "relevance_rank": idx,
    }
    if platform == "x":
        base.update(
            {
                "text": f"本文{idx}",
                "author_handle": f"user{idx}",
                "author_name": f"ユーザー{idx}",
                "author_followers": 100 * idx,
                "like_count": 10 * idx,
                "retweet_count": 2 * idx,
                "quote_count": idx,
                "published_at": datetime(2026, 1, idx, 9, 0, tzinfo=UTC),
            }
        )
    else:
        base.update(
            {
                "title": f"動画{idx}",
                "author_name": f"チャンネル{idx}",
                "view_count": 100 * idx,
                "published_at": datetime(2026, 1, idx, 9, 0, tzinfo=UTC),
            }
        )
    base.update(overrides)
    return Candidate(**base)


def _analysis(cid: str, **overrides: Any) -> AnalysisFinding:
    base: dict[str, Any] = {"id": cid, "summary": f"要約{cid}"}
    base.update(overrides)
    return AnalysisFinding(**base)


def _render_instruction(platform: str = "x", **overrides: Any) -> ResearchInstruction:
    base: dict[str, Any] = {
        "raw_text": "AI の最新動向を調べて",
        "platform": platform,
        "topic": "AI 動向",
    }
    base.update(overrides)
    return ResearchInstruction(**base)

def _report(platform: str = "x", **overrides: Any) -> ResearchReport:
    base: dict[str, Any] = {
        "instruction": _render_instruction(platform),
        "candidates": [_candidate(1, platform)],
        "analyses": [_analysis(_candidate(1, platform).id)],
        "common_themes": [],
        "sources": ["https://example.test/1"],
        "notes": [],
    }
    base.update(overrides)
    return ResearchReport(**base)


def _markdown(report: ResearchReport) -> str:
    return render_markdown(report, get_provider(report.instruction.platform))


def test_render_markdown_uses_topic_as_title() -> None:
    report = _report()

    assert _markdown(report).startswith("# リサーチレポート: AI 動向\n")


def test_render_markdown_truncates_raw_text_to_40_chars_when_topic_is_empty() -> None:
    instruction = _render_instruction().model_copy(update={"topic": "", "raw_text": "あ" * 50})
    report = _report(instruction=instruction)

    assert f"# リサーチレポート: {'あ' * 40}\n" in _markdown(report)


@pytest.mark.parametrize(
    ("platform", "title_line", "header"),
    [
        ("x", "## 選定ツイートリスト（上位 N 件）", "| # | 本文抜粋 | 投稿者 | いいね | RT | 引用 | URL |"),
        (
            "youtube",
            "## 選定動画リスト（関連度順上位 N 件）",
            "| # | タイトル | チャンネル | 再生数 | URL |",
        ),
    ],
)
def test_render_markdown_candidates_table_differs_by_platform(
    platform: str, title_line: str, header: str
) -> None:
    report = _report(platform)

    body = _markdown(report)

    assert title_line in body
    assert header in body


def test_render_markdown_flattens_newlines_in_snippet_and_angles() -> None:
    candidate = _candidate(1, text="1行目\n2行目")
    analysis = _analysis(
        "t1",
        angles=[BlogAngle(angle="切り口\n改行", value="価値\n改行", key_phrase="フレーズ\n改行")],
    )
    report = _report(candidates=[candidate], analyses=[analysis])

    body = _markdown(report)

    assert "| 切り口 改行 | 価値 改行 | フレーズ 改行 |" in body
    # 表の 1 行目（本文抜粋）は改行を潰して表を分断しない
    row = next(line for line in body.splitlines() if line.startswith("| 1 |"))
    assert "| 1 | 1行目 2行目 |" in row
    # 本文ブロックは原文のまま（改行を保持）
    assert "\n1行目\n2行目\n" in body


def test_render_markdown_renders_evidence_as_list() -> None:
    report = _report(analyses=[_analysis("t1", evidence=["引用A", "引用B"])])

    body = _markdown(report)

    assert "**そのまま使える引用**" in body
    assert "- 引用A\n- 引用B\n" in body


def test_render_markdown_places_missing_analysis_placeholder() -> None:
    """解析結果のない候補は「（解析なし）」で穴を埋め、他の候補の描画は続ける。"""
    c1, c2 = _candidate(1), _candidate(2)
    report = _report(candidates=[c1, c2], analyses=[_analysis("t1", summary="要約t1あり")])

    body = _markdown(report)

    assert "- 要約: （解析なし）" in body
    assert "要約t1あり" in body
    # プレースホルダ候補のブロックには概要表題を出さない
    without_analysis = body.split("### 2.")[1].split("## 共通ネタ")[0]
    assert "**概要**" not in without_analysis
    assert "**ブログの活用アイデア**" not in without_analysis


def test_render_markdown_youtube_block_has_no_body_section() -> None:
    report = _report("youtube")

    body = _markdown(report)

    assert "### 1. 動画1" in body
    assert "**本文**" not in body


def test_render_markdown_omits_meta_block_when_all_fields_are_empty() -> None:
    candidate = Candidate(platform="youtube", id="v1", title="", url="", relevance_rank=1)
    report = _report(
        "youtube", candidates=[candidate], analyses=[], sources=[], common_themes=[]
    )

    body = _markdown(report)

    assert "### 1. " in body
    assert not any(line.startswith("> ") for line in body.splitlines())


def test_render_markdown_renders_meta_line_for_x() -> None:
    report = _report()

    body = _markdown(report)

    assert "> 投稿者: ユーザー1 ｜ フォロワー: 100 ｜ いいね: 10 ｜ RT: 2 ｜ 公開日: 2026-01-01" in body


def test_render_common_themes_table_rows_use_platform_label() -> None:
    themes = [
        CommonTheme(theme="テーマA", description="説明A", supporting_ids=["t1"], example_quotes=["引用A"]),
        CommonTheme(theme="テーマB", description="説明B"),
    ]
    report = _report(common_themes=themes)

    body = _markdown(report)

    assert "| テーマ | 説明 | 該当ツイート | 代表抜粋 |" in body
    assert "| テーマA | 説明A | t1 | 引用A |" in body
    # 空リストは "-" で埋める（列がずれない）
    assert "| テーマB | 説明B | - | - |" in body


def test_render_common_themes_table_uses_youtube_label() -> None:
    report = _report("youtube", common_themes=[CommonTheme(theme="A", description="B")])

    assert "| テーマ | 説明 | 該当動画 | 代表抜粋 |" in _markdown(report)


def test_render_markdown_marks_when_no_common_themes() -> None:
    report = _report(common_themes=[])

    assert "（特筆すべき共通点なし）" in _markdown(report)


def test_render_markdown_omits_notes_section_when_notes_are_empty() -> None:
    report = _report(notes=[])

    assert "## 備考" not in _markdown(report)


def test_render_markdown_includes_notes_and_sources_sections() -> None:
    report = _report(sources=["https://a.test", "https://b.test"], notes=["メモ1", "メモ2"])

    body = _markdown(report)

    assert "## 出典" in body
    assert "- https://a.test\n- https://b.test\n" in body
    assert "## 備考" in body
    assert "- メモ1\n- メモ2\n" in body


def test_render_json_excludes_none_fields() -> None:
    candidate = _candidate(1, retweet_count=None, quote_count=None, author_followers=None)
    report = _report(candidates=[candidate], analyses=[_analysis("t1")])

    parsed = json.loads(render_json(report))

    assert parsed["candidates"][0]["id"] == "t1"
    assert all(v is not None for v in parsed["candidates"][0].values())
    assert "retweet_count" not in parsed["candidates"][0]


def test_render_json_round_trips_report_payload() -> None:
    report = _report(notes=["メモ"], sources=["https://example.test/1"])

    parsed = json.loads(render_json(report))

    assert parsed == json.loads(report.model_dump_json(indent=2, exclude_none=True))
    assert parsed["notes"] == ["メモ"]
    assert parsed["sources"] == ["https://example.test/1"]
