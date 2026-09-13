"""models.py の単体テスト（統合モデル）。

ここはモデルの**宣言**（既定値）を固定する層。出典（`sources`）が候補の URL から
構築されることは `nodes/compile_report.py` の責務であり、`tests/unit/test_compile_report.py`
がノード経由で検証する（LAYOUT-005-5: 同一の振る舞いを複数箇所で検証しない）。
旧 `test_report_sources_invariant` は断言が構築式（`[c.url for c in cands]`）と同一の
恒真アサートで、`compile_report` の出典構築を空にしても緑のままだった（LAYOUT-005-3）。
"""

from trend_researcher.models import (
    Candidate,
    CommonTheme,
    OutputFormat,
    OutputSpec,
    ResearchInstruction,
    ResearchReport,
)


def test_output_spec_has_no_table_for():
    """`table_for` は宣言されていない（FR-008 / REM-004）。

    実行時に誰も読まないフィールドを残すと「どちらが正か」が読めなくなる。
    プラットフォームの型名は `provider.name` が担う。
    """
    assert "table_for" not in OutputSpec.model_fields


def test_research_instruction_has_no_use_trends():
    """`use_trends` は宣言されていない（FR-009 / REM-003）。"""
    assert "use_trends" not in ResearchInstruction.model_fields


def test_candidate_defaults():
    c = Candidate(platform="x", id="1", text="hello")
    assert c.relevance_rank == 0
    assert c.like_count is None
    assert c.url == ""


def test_research_instruction_defaults():
    inst = ResearchInstruction(raw_text="テスト指示", platform="youtube")
    assert inst.max_results == 5
    assert inst.output.format == OutputFormat.MARKDOWN
    assert inst.topic == ""
    assert inst.platform == "youtube"


def test_common_theme_fields():
    t = CommonTheme(theme="abc", supporting_ids=["1", "2"], example_quotes=["x"])
    assert t.theme == "abc"
    assert t.supporting_ids == ["1", "2"]


def test_report_defaults_are_empty_collections():
    """指示以外を渡さないレポートは出典・候補・要約・テーマ・備考がすべて空。

    既定にダミー要素を混ぜると、候補が 0 件のときに存在しない出典が
    レポートへ載る（`render_markdown` の「## 出典」が嘘になる）。
    """
    report = ResearchReport(instruction=ResearchInstruction(raw_text="x"))

    assert report.sources == []
    assert report.candidates == []
    assert report.analyses == []
    assert report.common_themes == []
    assert report.notes == []


def test_common_theme_description_defaults_to_empty_string():
    """説明のないテーマは空文字で描画される（`None` を混ぜない）。

    `compile_report._render_common_themes` は `t.description` をそのまま表へ
    埋めるため、既定が空文字でないと説明のないテーマの行の説明列が埋まる。
    """
    assert CommonTheme(theme="t").description == ""
