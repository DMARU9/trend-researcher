"""`tools/compression.py` の圧縮契約テスト（US1 / FR-001〜008 / SC-001〜004）。

固定する振る舞い:

- 発動条件は `len(text) > max_chars`。しきい値**以下**では LLM を 1 回も呼ばない（FR-008）
- しきい値超過では**素材全体**を 1 回の呼び出しで圧縮する（分割・逐次にしない。FR-001 / FR-032）
- 出力は `<summary>` / `<key_excerpts>` の 2 部（FR-002）を連結し、`max_chars` で切り詰める（FR-007）
- 失敗（例外・タイムアウト・空応答）では生素材を `max_chars` で切って返し、理由を
  `CompressedSource.reason` に残す（FR-003 / FR-004）

判定は「モデルへ渡されたプロンプト」と「返り値の記録」の両方で行う。返り値だけを見ると
素材の先頭だけを渡して後半を捨てる実装でも緑になる（US1 の目的そのものが失われる）。
"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage

from trend_researcher.tools.compression import compress_text

#: テストで使うしきい値（短い文字列で境界を作る）
LIMIT = 100


class _FakeModel:
    """`compress_text` に注入する最小のモデル（`ainvoke` だけを持つ）。"""

    def __init__(
        self,
        response: str = "",
        *,
        error: BaseException | None = None,
        hang: bool = False,
    ) -> None:
        self.response = response
        self.error = error
        self.hang = hang
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str) -> AIMessage:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        if self.hang:
            # `asyncio.sleep` は `no_retry_sleep` が握るため実時間で待てない。
            # イベントは誰も set しないので `wait_for` だけが打ち切れる。
            await asyncio.Event().wait()
        return AIMessage(content=self.response)


def _run(model: _FakeModel, text: str, *, limit: int = LIMIT, instruction: str = "指示"):
    return asyncio.run(
        compress_text(
            text,
            model=model,
            max_chars=limit,
            timeout=0.05,
            instruction=instruction,
            source_id="src1",
        )
    )


def _long_text(*, head: str = "前半の話。", tail: str = "後半のキーワード：独自用語XYZ") -> str:
    """しきい値を確実に超え、後半にだけ固有語を含む素材。"""
    filler = "埋め草" * 40
    return f"{head}{filler}{tail}"


def test_below_the_threshold_makes_no_call():
    """しきい値未満では LLM を呼ばず、素材を切らない（FR-001 / FR-008 / SC-003）。"""
    model = _FakeModel("<summary>使われない</summary>")
    text = "短い素材"

    out, record = _run(model, text)

    assert model.prompts == []
    assert out == text
    assert record is None


def test_exactly_at_the_threshold_makes_no_call():
    """発動条件は「超えた場合」だけ（しきい値ちょうどは対象外。spec Edge Cases）。"""
    model = _FakeModel()
    text = "あ" * LIMIT

    out, record = _run(model, text)

    assert model.prompts == []
    assert out == text
    assert record is None


def test_one_call_per_source_over_the_threshold():
    """1 文字超えたら圧縮を 1 回だけ実行する（FR-001 / FR-032）。"""
    model = _FakeModel("<summary>要点</summary>")

    out, record = _run(model, "あ" * (LIMIT + 1))

    assert len(model.prompts) == 1
    assert out == "要点"
    assert record is not None
    assert (record.applied, record.reason) == (True, "compressed")


def test_the_whole_material_is_passed_to_the_prompt():
    """素材の**後半**もプロンプトに載る（先頭だけを渡して捨てない。FR-001）。"""
    model = _FakeModel("<summary>要点</summary>")
    text = _long_text()

    _run(model, text, instruction="ブログのネタを集めたい")

    prompt = model.prompts[0]
    assert "独自用語XYZ" in prompt
    assert "ブログのネタを集めたい" in prompt  # 元の指示文も含める（R-5）


def test_summary_and_excerpts_are_joined():
    """`<summary>` と `<key_excerpts>` の 2 部を連結する（FR-002）。"""
    model = _FakeModel(
        "<summary>要約の本文</summary>\n<key_excerpts>- 原文の抜粋</key_excerpts>"
    )

    out, _ = _run(model, _long_text())

    assert "要約の本文" in out
    assert "原文の抜粋" in out


def test_output_is_truncated_to_the_limit():
    """モデルが長い出力を返しても `max_chars` 以内に切り詰める（FR-007）。"""
    model = _FakeModel("<summary>" + "長" * 400 + "</summary>")

    out, record = _run(model, _long_text())

    assert len(out) <= LIMIT
    assert record is not None
    assert record.output_chars == len(out)
    assert record.output_chars <= LIMIT


def test_truncation_keeps_the_excerpts_that_fit():
    """切り詰めはタグを落とした本文に対して行い、抜粋を丸ごと捨てない（FR-007）。

    生の応答（タグ込み）を切ると `</summary>` が予算を食い、抜粋が 1 文字も入らない。
    """
    summary = "要点の本文"
    model = _FakeModel(
        f"<summary>{summary}</summary>"
        f"<key_excerpts>- 抜粋{'い' * 200}</key_excerpts>"
    )

    out, record = _run(model, _long_text())

    assert len(out) <= LIMIT
    assert out.startswith(summary)  # 要約は丸ごと残る
    assert "抜粋" in out  # 抜粋も（入る分だけ）残る
    assert "<summary>" not in out  # タグは予算を食わない
    assert record is not None
    assert record.applied is True


def test_a_response_without_tags_is_used_as_the_summary():
    """タグが無い応答でも本文を捨てない（タグは形式であって内容ではない）。"""
    model = _FakeModel("見出しの無い要約文です。")

    out, record = _run(model, _long_text())

    assert out == "見出しの無い要約文です。"
    assert record is not None
    assert (record.applied, record.reason) == (True, "compressed")


def test_empty_response_falls_back_to_the_raw_material():
    """空応答は失敗として扱い、生素材（切り詰め）を使う（FR-003）。"""
    model = _FakeModel("   ")

    out, record = _run(model, _long_text())

    assert out.startswith("前半の話。")
    assert record is not None
    assert (record.applied, record.reason) == (False, "empty")
    assert record.output_chars == min(len(_long_text()), LIMIT)


def test_timeout_falls_back_to_the_raw_material():
    """応答が返らない場合も実行を止めず、理由を残す（FR-004 / SC-004）。"""
    model = _FakeModel(hang=True)

    out, record = _run(model, _long_text())

    assert out.startswith("前半の話。")
    assert record is not None
    assert (record.applied, record.reason) == (False, "timeout")


def test_exception_falls_back_to_the_raw_material():
    """例外も同じく縮退する（FR-003）。"""
    model = _FakeModel(error=RuntimeError("接続失敗"))

    out, record = _run(model, _long_text())

    assert out.startswith("前半の話。")
    assert record is not None
    assert (record.applied, record.reason) == (False, "error")


@pytest.mark.parametrize("reason_case", ["empty", "timeout", "error"])
def test_fallback_output_never_exceeds_the_limit(reason_case: str):
    """縮退経路でも切り詰めを守る（FR-007 は成功時だけの約束ではない）。"""
    model = _FakeModel(
        "",
        error=RuntimeError("x") if reason_case == "error" else None,
        hang=reason_case == "timeout",
    )

    out, record = _run(model, _long_text())

    assert len(out) <= LIMIT
    assert record is not None
    assert record.applied is False


def test_record_carries_the_source_identity_and_sizes():
    """記録には対象・入出力長・理由が入る（FR-006 / data-model 3.1）。"""
    model = _FakeModel("<summary>短い要点</summary>")
    text = _long_text()

    out, record = _run(model, text)

    assert record is not None
    assert record.source_id == "src1"
    assert record.input_chars == len(text)
    assert record.output_chars == len(out)
    assert record.applied is True


def test_a_cancelled_call_is_not_swallowed():
    """`CancelledError` は再送出する（部分失敗として飲み込まない。contract §3）。"""
    model = _FakeModel(error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        _run(model, _long_text())
