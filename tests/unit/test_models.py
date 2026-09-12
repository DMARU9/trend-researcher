"""models.py の単体テスト（統合モデル）。"""

from trend_researcher.models import (
    AnalysisFinding,
    BlogAngle,
    Candidate,
    CommonTheme,
    Context,
    OutputFormat,
    ResearchInstruction,
    ResearchReport,
)


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


def test_report_sources_invariant():
    cands = [
        Candidate(platform="youtube", id="a", url="https://www.youtube.com/watch?v=a"),
        Candidate(platform="youtube", id="b", url="https://www.youtube.com/watch?v=b"),
    ]
    report = ResearchReport(
        instruction=ResearchInstruction(raw_text="x", platform="youtube"),
        candidates=cands,
        analyses=[AnalysisFinding(id="a")],
        common_themes=[CommonTheme(theme="t", supporting_ids=["a", "b"])],
        sources=[c.url for c in cands],
    )
    assert set(report.sources) == {c.url for c in cands}
