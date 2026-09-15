"""プロンプト定数が持つ節と重要制約の契約（FR-055〜058 / 契約 §3）。

`prompts.py` の各プロンプトは、LLM の出力を機械的に扱えるように次の節を持つ。

| 節 | 何を固定するか |
|---|---|
| **停止条件** | 出力できるのは指定の形式のみ。前置き・後書き・謝辞を書かない（FR-055） |
| **判定不能表現の禁止** | 「おそらく」などで埋めず、不明は空にする（FR-056） |
| **出力形式** | 種類別の構造例を持つ（固定テンプレートの指示を書かない。FR-057） |
| **重要制約の二重明示** | 出力言語・件数・引用形式を、出力形式の節の**前**と**中**の 2 箇所に置く（FR-058） |

ここで見るのは「節と制約が在るか」だけ。文章の質は測らない（それは評価基盤の役目。
FR-044）。禁止語の不在も固定する（「テンプレートをそのまま使う」＝固定テンプレート）。
"""

from __future__ import annotations

import re

import pytest

from trend_researcher import prompts

#: 停止条件の節の見出し。
STOP_CONDITION_MARK = "停止条件"

#: 出力形式の節の見出し。二重明示の境界としても使う。
OUTPUT_FORMAT_MARK = "出力形式"

#: 重要制約（FR-058）。出力形式の節の前と中に 1 回ずつ現れること。
IMPORTANT_CONSTRAINTS = ("出力言語", "件数", "引用形式")

#: 判定不能表現の禁止（FR-056）を示す文言。不明な値は空にする。
NO_GUESS_MARK = "推測で埋めない"

#: 固定テンプレートを指示する語（FR-057 が禁じる）。
FORBIDDEN_TEMPLATE_MARK = "テンプレートをそのまま"

#: 停止条件が「機械が判定できる」と言える根拠の 1 つ目（件数。FR-055）。
COUNT_PATTERN = re.compile(r"\d+ *(件|行|箇条|つ|個|テーマ)")

#: 根拠の 2 つ目（出力形式による打ち切り。FR-055）。
#:
#: `COMPRESSION_PROMPT` はタグの外側を禁じる形で同じことを言う。
PROSE_CUTOFF_MARKS = ("出力形式", "前置き")

#: 停止条件に置いてはならない判定不能な表現（FR-056。T108 で固定する）。
#:
#: FR-056 は「判定不能な表現**のみ**で示してはならない」としているが、ここでは
#: その出現自体を落とす（1 文でも混ざると、そこを根拠に打ち切られて出力が崩れる）。
VAGUE_MARKS = (
    "適切に",
    "適切な",
    "適宜",
    "必要なら",
    "必要に応じて",
    "できれば",
    "できるだけ",
    "なるべく",
    "十分な",
    "うまく",
    "柔軟に",
    "終わった時点",
    "終わり次第",
    "と判断したら",
)


def _prompt_constants() -> dict[str, str]:
    """`prompts.py` のプロンプト定数（大文字 ＋ 文字列）を全部集める。"""
    return {
        name: value
        for name, value in vars(prompts).items()
        if name.isupper() and name.endswith("_PROMPT") and isinstance(value, str)
    }


CONSTANTS = _prompt_constants()


def _split_at_output_format(text: str) -> tuple[str, str]:
    """出力形式の節を境に「前」と「そこから後ろ」に割る。"""
    index = text.index(OUTPUT_FORMAT_MARK)
    return text[:index], text[index:]


def _stop_condition(text: str) -> str:
    """停止条件の節の中身（見出しから次の節の手前まで）。"""
    mark = f"【{STOP_CONDITION_MARK}】"
    rest = text[text.index(mark) + len(mark) :]
    end = rest.find("【")
    return rest if end == -1 else rest[:end]


# --- 走査対象そのものの健全性 ---------------------------------------------


def test_the_scan_covers_every_prompt_constant() -> None:
    """走査対象が空や少数にならない（命名を変えると静かに無効化されるため）。"""
    assert len(CONSTANTS) >= 9
    for name, text in CONSTANTS.items():
        assert text.strip(), name


@pytest.mark.parametrize("name", sorted(CONSTANTS))
def test_every_prompt_has_a_stop_condition(name: str) -> None:
    """停止条件の節を持つ（FR-055。機械判定の入口）。"""
    assert STOP_CONDITION_MARK in CONSTANTS[name]


def test_the_stop_condition_section_stops_at_the_next_heading() -> None:
    """切り出した停止条件の節が、次の節を巻き込んだり空になったりしない。"""
    for name, text in CONSTANTS.items():
        section = _stop_condition(text)

        assert 0 < len(section) < len(text), name
        assert "判定不能表現の禁止" not in section, name
        assert section.strip(), name


@pytest.mark.parametrize("name", sorted(CONSTANTS))
def test_the_stop_condition_is_decidable_by_a_machine(name: str) -> None:
    """停止条件は件数と出力形式の両方で打ち切る（モデルの裁量に委ねない。FR-055）。

    件数だけでは「出力の前後に何を書くか」が残り、出力形式だけでは「いつ止めるか」が
    残る。どちらも機械側で判定できる形で書かれていることを見る。
    """
    bullets = [
        line for line in _stop_condition(CONSTANTS[name]).splitlines() if line.startswith("- ")
    ]

    assert bullets, f"{name}: 停止条件が箇条書きで書かれていない"
    assert any(COUNT_PATTERN.search(line) for line in bullets), (
        f"{name}: 件数による打ち切りが無い"
    )
    assert any(mark in line for mark in PROSE_CUTOFF_MARKS for line in bullets), (
        f"{name}: 出力形式以外を書かせない指示が無い"
    )


@pytest.mark.parametrize("name", sorted(CONSTANTS))
def test_no_stop_condition_leaves_the_cutoff_to_the_model(name: str) -> None:
    """判定不能な表現を停止条件に書かない（FR-056 / T108）。"""
    section = _stop_condition(CONSTANTS[name])
    found = [mark for mark in VAGUE_MARKS if mark in section]

    assert not found, f"{name}: 判定不能な表現が停止条件にある: {found}"


@pytest.mark.parametrize("name", sorted(CONSTANTS))
def test_every_prompt_has_an_output_format_section(name: str) -> None:
    """出力形式の節を持つ（FR-057。種類別の構造例）。"""
    assert OUTPUT_FORMAT_MARK in CONSTANTS[name]


@pytest.mark.parametrize("name", sorted(CONSTANTS))
def test_every_prompt_forbids_filling_with_guesses(name: str) -> None:
    """判定不能表現の禁止（FR-056）。不明は空にする。"""
    assert NO_GUESS_MARK in CONSTANTS[name]


@pytest.mark.parametrize("name", sorted(CONSTANTS))
def test_no_prompt_orders_a_fixed_template(name: str) -> None:
    """固定テンプレートの指示を書かない（FR-057）。"""
    assert FORBIDDEN_TEMPLATE_MARK not in CONSTANTS[name]


@pytest.mark.parametrize("constraint", IMPORTANT_CONSTRAINTS)
@pytest.mark.parametrize("name", sorted(CONSTANTS))
def test_important_constraints_are_stated_twice(name: str, constraint: str) -> None:
    """重要制約は出力形式の節の**前**と**中**の 2 箇所で明示する（FR-058）。

    節の中だけ・前だけでは足りない（後半を読むモデルと前半を読むモデルの両方に届かせる）。
    """
    before, from_format = _split_at_output_format(CONSTANTS[name])

    assert constraint in before, f"{name}: {constraint} が出力形式の節より前に無い"
    assert constraint in from_format, f"{name}: {constraint} が出力形式の節の中に無い"
