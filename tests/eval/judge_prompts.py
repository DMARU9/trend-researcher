"""観点ごとの判定プロンプト（FR-040 / FR-048）。

判定プロンプトは**生成側のプロンプトが課す制約**を評価基準に取り込む。制約は
識別子で持ち（`CONSTRAINTS`）、どの観点がどの制約を測るかを `AXIS_CONSTRAINTS`
で対応させる。`CONSTRAINT_EVIDENCE` には「生成側のプロンプト（`prompts.py`）に
実際に現れる文言」を並べ、制約が実在することを機械的に確かめられるようにする
（実在しない制約を評価項目に作らない。FR-048 / FR-074）。

判定プロンプトは冒頭で観点の識別子を自己記述する（`観点の識別子: <axis>`）。
呼び出し側はこの行で応答を観点へ結び付け、結果の識別子は呼び出し側が決める。
"""

from __future__ import annotations

#: すべての判定プロンプトに共通の指示。
COMMON_RULES = """\
あなたはリサーチレポートの品質を採点する評価者です。レポートと採点基準を読み、
基準に照らした点数（1〜5 の整数。1 = 全く満たしていない、5 = すべて満たしている）
と、その点数にした理由を返してください。

- 理由には、レポート中の具体的な記述（見出し・数値・引用）を挙げること。
- 判断できない項目を「おそらく」「問題ないと思われる」のような曖昧な表現で
  埋めないこと。基準に照らして足りない点は減点し、その根拠を書くこと。
- 日本語で答えること。
"""

#: 生成側のプロンプトが課す制約（FR-048 の対応表の「制約側」）。
CONSTRAINTS: dict[str, str] = {
    "output_language": "出力言語はトピック（ユーザー指示）の言語に合わせる（日本語トピックなら日本語）",
    "query_count": "検索クエリは生成側が定めた件数を守る（X は 5 件ちょうど、YouTube は 1 件）",
    "citation": "素材からの引用は原文のままで、改変・創作をしない",
    "relevance_target": "集める対象は「バズっている投稿」ではなく「トピックに関連する投稿」である",
    "output_structure": "出力は決められた見出し構成（概要・活用アイデア・引用）に従う",
}

#: 制約が生成側のプロンプトに実在することの根拠（`prompts.py` に現れる文言）。
CONSTRAINT_EVIDENCE: dict[str, tuple[str, ...]] = {
    "output_language": ("日本語トピックなら日本語クエリ",),
    "query_count": ("5 件", "1 つだけ"),
    "citation": ("そのまま引用できる形",),
    "relevance_target": ("トピックに関連する投稿",),
    "output_structure": ("## 概要", "## ブログの活用アイデア"),
}

#: 観点が測る制約（FR-040 / FR-048）。
AXIS_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "overall_quality": ("output_language", "citation", "relevance_target"),
    "relevance": ("relevance_target",),
    "structure": ("output_structure",),
    "groundedness": ("citation",),
    "completeness": ("query_count",),
    "output_language": ("output_language",),
}

#: 観点ごとの判定プロンプト（`{report}` をレポート本文へ置換する。FR-040）。
JUDGE_PROMPTS: dict[str, str] = {
    "overall_quality": COMMON_RULES
    + """
観点の識別子: overall_quality

6 つの下位基準をそれぞれ採点してください（整数 1〜5）:
研究の深さ（research_depth）/ 情報源の質（source_quality）/ 分析の厳密さ（analytical_rigor）/
実用的価値（practical_value）/ 中立性と客観性（balance_and_objectivity）/ 文章の質（writing_quality）。
総合の点数は聞きません（下位基準から集約します）。理由は 6 つに共通で 1 つ書いてください。

レポート:
{report}
""",
    "relevance": COMMON_RULES
    + """
観点の識別子: relevance

依頼したトピックに即した内容かを採点してください。関連しない話題へ流れている、
依頼の主題から外れた一般論で埋めている場合は減点します。

レポート:
{report}
""",
    "structure": COMMON_RULES
    + """
観点の識別子: structure

見出しの構成と順序、表の使い方が読み手に追えるかを採点してください。見出しの
階層が崩れている、節の順序が読み手の理解を妨げる場合は減点します。

レポート:
{report}
""",
    "groundedness": COMMON_RULES
    + """
観点の識別子: groundedness

引用と根拠が素材（収集した投稿・文字起こし）に基づいているかを採点して
ください。素材に無い事実を足している、引用を改変している場合は大幅に減点します。

レポート:
{report}
""",
    "completeness": COMMON_RULES
    + """
観点の識別子: completeness

依頼で求められた件数・観点が揃っているかを採点してください。要求より少ない、
または要求された側面が欠けている場合は減点します。

レポート:
{report}
""",
    "output_language": COMMON_RULES
    + """
観点の識別子: output_language

レポートの出力言語がトピック（ユーザー指示）の言語と一致しているかを採点して
ください。指示が日本語なのに英語で書かれている場合は減点します。

レポート:
{report}
""",
}


def axis_constraints(axis: str) -> tuple[str, ...]:
    """観点が測る制約の識別子（未定義の観点は空）。"""
    return AXIS_CONSTRAINTS.get(axis, ())


def build_judge_prompt(axis: str, report: str) -> str:
    """観点の判定プロンプトを組み立てる（FR-040）。

    生成側の制約（`CONSTRAINTS`）を評価基準として本文の後ろに付ける。未知の
    観点は `ValueError`。
    """
    template = JUDGE_PROMPTS.get(axis)
    if template is None:
        raise ValueError(f"判定プロンプトがありません: {axis}")
    prompt = template.replace("{report}", report)
    lines = [f"- {CONSTRAINTS[name]}" for name in axis_constraints(axis)]
    if not lines:
        return prompt
    return prompt + "\nこの観点で測る生成側の制約:\n" + "\n".join(lines) + "\n"
