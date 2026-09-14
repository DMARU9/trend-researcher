"""nodes/extract_common.py の共通テーマ抽出テスト（FR-012 / FR-008）。

対象: LLM が返す自由文（見出し・本文・箇条書き・表）から、テーマ名・説明・
全コンテンツへの紐づけ・代表抜粋を取り出す経路。正常系と崩れた入力の両方を
固定する（FR-012）。LLM 応答は `fake_model_factory` でノード単位に注入する
（LAYOUT-004-4 / R-7）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest import mock

import httpx
import openai
import pytest
from langchain_core.runnables import RunnableConfig

from trend_researcher.models import AnalysisFinding
from trend_researcher.nodes.extract_common import extract_common
from trend_researcher.tools.degradation import DegradationError

#: プロンプトが要求する形式（`### テーマ名` + `- 説明:` / `- 代表抜粋:`）。
PROMPT_STYLE = (
    "## 共通テーマ\n"
    "### 自動化\n"
    "- 説明: どちらも自動化の話をしている\n"
    "- 該当: 全件\n"
    "- 代表抜粋: 抜粋A\n"
)
#: 自由文として崩れた形式（`#### 説明` / `#### 代表抜粋` を入れ子にした形）。
NESTED_STYLE = "### テーマA\n#### 説明\n説明A\n#### 代表抜粋\n- 抜粋A1\n- 抜粋A2\n"

_ANALYSES = [
    AnalysisFinding(
        id="t1",
        summary="要約1",
        key_points=["要点1", "要点1b"],
        evidence=["根拠1"],
    ),
    AnalysisFinding(
        id="t2",
        summary="要約2",
        key_points=["要点2"],
        evidence=["根拠2", "根拠2b"],
    ),
]


def _config(**configurable: Any) -> RunnableConfig:
    return {"configurable": configurable}


def _run(
    fake_model_factory: Any,
    response: str,
    *,
    platform: str | None = "x",
    config: RunnableConfig | None = None,
    analyses: list[AnalysisFinding] | None = None,
) -> dict[str, Any]:
    """`extract_common` をノード単位注入で 1 回実行し、出力 state を返す。"""
    node_state: dict[str, Any] = {"analyses": _ANALYSES if analyses is None else analyses}
    if platform is not None:
        node_state["platform"] = platform
    with fake_model_factory.install({"extract_common": response}):
        return extract_common(node_state, config if config is not None else _config())


# --- LLM 境界へ渡すプロンプト ---------------------------------------------------


def test_prompt_lists_every_analysis(fake_model_factory: Any) -> None:
    """各コンテンツの要約・ポイント・根拠がプロンプトへ載る（`{analyses}` が埋まる）。"""
    _run(fake_model_factory, PROMPT_STYLE)
    prompt = fake_model_factory.prompts_for("extract_common")[0]
    assert "### コンテンツ t1" in prompt
    assert "要約: 要約1" in prompt
    assert "ポイント: 要点1 / 要点1b" in prompt
    assert "根拠: 根拠1" in prompt
    assert "### コンテンツ t2" in prompt
    assert "根拠: 根拠2 / 根拠2b" in prompt
    # プレースホルダが未置換のまま渡っていないこと
    assert "{analyses}" not in prompt


def test_prompt_without_analyses_leaves_no_content_block(fake_model_factory: Any) -> None:
    _run(fake_model_factory, PROMPT_STYLE, analyses=[])
    prompt = fake_model_factory.prompts_for("extract_common")[0]
    assert "### コンテンツ" not in prompt
    assert "{analyses}" not in prompt


def test_prompt_follows_the_platform(fake_model_factory: Any) -> None:
    """platform は state 優先、無ければ Configuration。プロンプトが切り替わる。"""
    _run(fake_model_factory, PROMPT_STYLE, platform=None, config=_config(platform="youtube"))
    youtube_prompt = fake_model_factory.prompts_for("extract_common")[0]
    _run(fake_model_factory, PROMPT_STYLE, platform="x")
    x_prompt = fake_model_factory.prompts_for("extract_common")[0]
    assert "以下の各動画の要約" in youtube_prompt
    assert "該当動画" in youtube_prompt
    assert "以下の各ツイートの要約" in x_prompt
    assert "該当ツイート" in x_prompt


# --- 見出しと本文だけの出力 -----------------------------------------------------


def test_description_falls_back_to_the_whole_body(fake_model_factory: Any) -> None:
    """セクション見出しが無いときは本文全体を説明として残す（情報を捨てない）。"""
    out = _run(fake_model_factory, PROMPT_STYLE)
    themes = out["common_themes"]
    assert [t.theme for t in themes] == ["自動化"]
    assert themes[0].description == "- 説明: どちらも自動化の話をしている\n- 該当: 全件\n- 代表抜粋: 抜粋A"


def test_theme_name_only_uses_the_heading_as_description(fake_model_factory: Any) -> None:
    """本文が無いテーマでも名前を説明として残す（本文欠落の縮退）。"""
    out = _run(fake_model_factory, "### 自動化\n")
    assert [t.theme for t in out["common_themes"]] == ["自動化"]
    assert out["common_themes"][0].description == "自動化"


def test_nested_explanation_heading_is_used_as_description(fake_model_factory: Any) -> None:
    """`### テーマ` の下の `#### 説明` はテーマの説明として扱う（FR-023）。"""
    out = _run(fake_model_factory, NESTED_STYLE)
    assert len(out["common_themes"]) == 1
    assert out["common_themes"][0].theme == "テーマA"
    assert out["common_themes"][0].description == "説明A"


def test_nested_field_headings_do_not_become_themes(fake_model_factory: Any) -> None:
    """`#### 説明` / `#### 代表抜粋` が独立したテーマとして混入しない（FR-023）。"""
    out = _run(fake_model_factory, NESTED_STYLE + "### テーマB\n本文B\n")
    assert [t.theme for t in out["common_themes"]] == ["テーマA", "テーマB"]


def test_same_level_headings_start_new_themes(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "### テーマA\n本文A\n### テーマB\n本文B\n")
    assert [(t.theme, t.description) for t in out["common_themes"]] == [
        ("テーマA", "本文A"),
        ("テーマB", "本文B"),
    ]


def test_level_four_headings_are_themes_when_there_is_no_parent(
    fake_model_factory: Any,
) -> None:
    out = _run(fake_model_factory, "#### テーマ四\n本文\n")
    assert [(t.theme, t.description) for t in out["common_themes"]] == [("テーマ四", "本文")]


def test_preamble_before_the_first_heading_is_ignored(fake_model_factory: Any) -> None:
    text = "## 共通テーマ\n抽出結果は以下です。\n### テーマA\n本文A\n"
    out = _run(fake_model_factory, text)
    assert [t.theme for t in out["common_themes"]] == ["テーマA"]


def test_empty_heading_name_falls_back_to_a_numbered_theme(fake_model_factory: Any) -> None:
    """見出し記号だけの行でもテーマ名は既定の連番で埋める（例外にしない）。"""
    out = _run(fake_model_factory, "### \n")
    themes = out["common_themes"]
    assert [t.theme for t in themes] == ["共通テーマ1"]
    assert themes[0].description == ""


def test_multiple_themes_keep_document_order(fake_model_factory: Any) -> None:
    text = "### A\n本文A\n### B\n本文B\n### C\n本文C\n"
    out = _run(fake_model_factory, text)
    assert [t.theme for t in out["common_themes"]] == ["A", "B", "C"]


# --- 代表抜粋（箇条書き） -------------------------------------------------------


def test_quotes_come_from_dash_list(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "### 自動化\n- 抜粋A\n- 抜粋B\n")
    assert out["common_themes"][0].example_quotes == ["抜粋A", "抜粋B"]


def test_quotes_come_from_numbered_list(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "### 自動化\n1. 抜粋A\n2. 抜粋B\n")
    assert out["common_themes"][0].example_quotes == ["抜粋A", "抜粋B"]


def test_quotes_come_from_nested_excerpt_heading(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, NESTED_STYLE)
    assert out["common_themes"][0].example_quotes == ["抜粋A1", "抜粋A2"]


def test_quotes_are_empty_for_a_table_body(fake_model_factory: Any) -> None:
    """表形式の本文は箇条書きではないため抜粋は空（例外にしない）。"""
    text = "### 自動化\n| 列A | 列B |\n|-----|-----|\n| a | b |\n"
    out = _run(fake_model_factory, text)
    assert out["common_themes"][0].description.startswith("| 列A | 列B |")
    assert out["common_themes"][0].example_quotes == []


# --- 紐づけ（全コンテンツ） -----------------------------------------------------


def test_supporting_ids_are_all_analyses(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, PROMPT_STYLE)
    assert out["common_themes"][0].supporting_ids == ["t1", "t2"]


def test_supporting_ids_are_empty_without_analyses(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, PROMPT_STYLE, analyses=[])
    assert out["common_themes"][0].supporting_ids == []


def test_supporting_ids_follow_the_analysis_order(fake_model_factory: Any) -> None:
    reordered = list(reversed(_ANALYSES))
    out = _run(fake_model_factory, PROMPT_STYLE, analyses=reordered)
    assert out["common_themes"][0].supporting_ids == ["t2", "t1"]


# --- テーマが無い出力 -----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n\n",
        "共通テーマはありません",
        "### テーマ\n本文\n",  # 「テーマ」は見出しラベルであり中身ではない
        "### テーマ名\n本文\n",
        "### 共通テーマ\n本文\n",
        "### 特筆すべき共通点なし\n",
        "##### テーマ五\n本文\n",  # 見出しは ###/#### のみ
        "| テーマ | 説明 |\n|--------|------|\n| 自動化 | 共通 |\n",  # 表のみ
    ],
)
def test_no_theme_output_yields_an_empty_list(fake_model_factory: Any, text: str) -> None:
    out = _run(fake_model_factory, text)
    assert out["common_themes"] == []


# --- 進捗メッセージ -------------------------------------------------------------


def test_progress_messages_report_the_theme_count(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "### A\n本文A\n### B\n本文B\n")
    assert len(out["messages"]) == 2
    assert "[6/7] extract_common" in out["messages"][0].content
    assert "開始" in out["messages"][0].content
    assert "完了" in out["messages"][1].content
    assert "2 件の共通テーマ" in out["messages"][1].content


def test_progress_messages_report_zero_themes(fake_model_factory: Any) -> None:
    out = _run(fake_model_factory, "")
    assert "0 件の共通テーマ" in out["messages"][1].content


# --- US2: 構造化出力とフォールバック（FR-009 / FR-011 / FR-012） ----------------

#: 構造化出力で受け取る共通テーマ（`CommonThemes.themes`）。
_STRUCTURED_THEMES: dict[str, Any] = {
    "themes": [
        {
            "theme": "自動化",
            "description": "どちらも自動化の話",
            "supporting_ids": ["t1", "t2"],
            "example_quotes": ["抜粋1"],
        }
    ]
}


def _run_structured(
    fake_model_factory: Any,
    *,
    structured: dict[str, Any],
    response: str = PROMPT_STYLE,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """構造化出力を注入して 1 回実行する（テキスト応答も注入しておく）。"""
    with fake_model_factory.install(
        {"extract_common": response}, structured={"extract_common": structured}
    ):
        return extract_common(
            {"analyses": _ANALYSES, "platform": "x"},
            config if config is not None else _config(),
        )


def test_structured_output_is_used_as_is(fake_model_factory: Any, capsys: Any) -> None:
    """構造化出力が成功したら、その内容がそのまま状態に入る（見出し解析は走らない）。"""
    out = _run_structured(fake_model_factory, structured=_STRUCTURED_THEMES)

    themes = out["common_themes"]
    assert len(themes) == 1
    assert themes[0].theme == "自動化"
    assert themes[0].supporting_ids == ["t1", "t2"]
    assert "[補足]" not in capsys.readouterr().err
    # 正常系ではテキスト呼び出しを行わない
    assert fake_model_factory.prompts_for("extract_common") == []
    assert len(fake_model_factory.structured_prompts_for("extract_common")) == 1


def test_structured_empty_themes_are_kept(fake_model_factory: Any) -> None:
    """共通点なし（空リスト）も正常な結果として扱う（フォールバックしない）。"""
    out = _run_structured(fake_model_factory, structured={"themes": []})

    assert out["common_themes"] == []
    assert "0 件の共通テーマ" in out["messages"][1].content


def test_structured_failure_falls_back_to_the_heading_parser(
    fake_model_factory: Any, capsys: Any
) -> None:
    """規定回数失敗したら見出し解析へ切り替え、補足行に残す（FR-011 / FR-012）。"""
    out = _run(fake_model_factory, PROMPT_STYLE)

    err = capsys.readouterr().err
    assert (
        "[補足] 構造化出力を取得できなかったため見出し解析へ切り替えました"
        "（OutputParserException）" in err
    )
    themes = out["common_themes"]
    assert [t.theme for t in themes] == ["自動化"]
    # 決定的解析は「説明」の中身を丸ごと本文として扱う（既存の挙動を変えない）
    assert "どちらも自動化の話をしている" in themes[0].description
    assert themes[0].supporting_ids == ["t1", "t2"]
    assert "抜粋A" in " ".join(themes[0].example_quotes)
    # 試行回数 = 1 + retry_max（既定 3）。テキスト呼び出しはフォールバックの 1 回だけ
    assert len(fake_model_factory.structured_prompts_for("extract_common")) == 3
    assert len(fake_model_factory.prompts_for("extract_common")) == 1


def test_fallback_extracts_quotes_with_the_existing_parsers(fake_model_factory: Any) -> None:
    """フォールバックは既存の `extract_section` / `extract_list_items` の経路を通る。"""
    out = _run(fake_model_factory, response=NESTED_STYLE)

    themes = out["common_themes"]
    assert themes[0].theme == "テーマA"
    assert themes[0].description == "説明A"
    assert themes[0].example_quotes == ["抜粋A1", "抜粋A2"]


def test_fallback_does_not_add_progress_lines(fake_model_factory: Any) -> None:
    """フォールバックは進捗行を増やさない（補足は stderr のみ。既定の出力は不変）。"""
    out = _run(fake_model_factory, PROMPT_STYLE)

    contents = [m.content for m in out["messages"]]
    assert len(contents) == 2
    assert not any("補足" in c or "構造化出力" in c for c in contents)


# --- US3: 構造化出力が上限超過を使い切ったらフォールバックしない（FR-015 / T104） --


class _AlwaysLimitStructured:
    """構造化出力が常に上限超過になる runnable（縮退を使い切る経路を作る）。"""

    def __init__(self) -> None:
        self.attempts = 0

    async def ainvoke(self, prompt: str) -> Any:
        self.attempts += 1
        raise _context_length_error()


class _StructuredLimitLLM:
    """構造化だけが上限超過で失敗するフェイク（テキスト呼び出しは成功する）。

    テキストを成功させておくと「`DegradationError` を握り潰して見出し解析へ落ちる」
    実装ではノードが正常終了するため、テストが確実に赤になる（非空虚）。
    """

    def __init__(self, content: str) -> None:
        self.content = content
        self.text_calls = 0
        self.structured = _AlwaysLimitStructured()

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        return self.structured

    async def ainvoke(self, prompt: str) -> Any:
        self.text_calls += 1
        return SimpleNamespace(content=self.content)


def _context_length_error() -> Exception:
    """上限超過（400 ＋ `context_length_exceeded`）を模した例外（契約 §5）。"""
    return openai.BadRequestError(
        message="This endpoint's maximum context length is 1048576 tokens.",
        response=httpx.Response(400, request=httpx.Request("POST", "https://example.test/v1")),
        body={"error": {"code": "context_length_exceeded"}},
    )


def test_the_exhausted_degradation_is_not_swallowed_by_the_fallback() -> None:
    """縮退を使い切ったら見出し解析へ落とさず例外を伝える（FR-015 / T104）。

    飲み込むと、失敗した呼び出しが「共通テーマ 0 件の成功」に化けて終了コード 1 に
    ならない（`__main__.py` は `DegradationError` を見て exit 1 にする）。
    """
    llm = _StructuredLimitLLM(PROMPT_STYLE)

    with (
        mock.patch("trend_researcher.nodes.extract_common.build_model", return_value=llm),
        pytest.raises(DegradationError),
    ):
        extract_common({"analyses": _ANALYSES, "platform": "x"}, _config())

    assert llm.structured.attempts >= 1
    assert llm.text_calls == 0


# 対照（上限超過**以外**の失敗は見出し解析へフォールバックする）は既存の
# `test_fallback_extracts_quotes_with_the_existing_parsers` が固定している。
