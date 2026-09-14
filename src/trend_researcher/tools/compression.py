"""長文素材の圧縮（US1 / FR-001〜008 / contract: context-management-contract §1）。

素材が `compression_threshold` を超える場合に限り、素材**全体**を 1 回の LLM 呼び出しで
圧縮してから解析に渡す。失敗（例外・タイムアウト・空応答）では生素材を切り詰めて使い、
理由を `CompressedSource.reason` に残す（実行は止めない。SC-004）。

このモジュールは 2 段の入口を持つ。

- `compress_source`: ノード向け。しきい値を判定し、超えていれば**モデルを構築して**
  `compress_text` へ渡す（`build_model` は `tools/llm.py` の 1 経路に限る。FR-045）
- `compress_text`: 圧縮の単位。モデルは呼び出し側から注入する（テストの境界）

タグ抽出は `tools/parse.py` を使わない。`parse.py` の `extract_section` は Markdown
見出しを想定しており `<summary>` 形式のタグを扱えない（T008 の実測）。`parse.py` を
無理に一般化せず、この用途の実装をここに置く（YAGNI）。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from trend_researcher.models import CompressedSource
from trend_researcher.prompts import COMPRESSION_PROMPT
from trend_researcher.tools.llm import build_model

#: 圧縮の出力契約のタグ（`prompts.COMPRESSION_PROMPT` と対）
SUMMARY_TAG = "summary"
EXCERPTS_TAG = "key_excerpts"

#: `CompressedSource.reason` の値（data-model §3.1）。`token_limit` は使わない（FR-019）
REASON_COMPRESSED = "compressed"
REASON_TIMEOUT = "timeout"
REASON_ERROR = "error"
REASON_EMPTY = "empty"

#: 元の指示文が無い場合にプロンプトへ載せる文言（空欄にしない）
NO_INSTRUCTION = "（指定なし）"


def _extract_tag(text: str, tag: str) -> str:
    """`<tag>…</tag>` の中身を返す（無ければ空文字）。

    タグは入れ子にならない前提で最短一致にする。応答がタグを閉じ忘れている場合は
    「タグ無し」として扱い、本文全体を使う（`_to_compressed_text`）。
    """
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _to_compressed_text(response: str) -> str:
    """応答から圧縮結果を組み立てる（要約と重要抜粋を連結。FR-002）。

    タグが 1 つも無い応答は本文全体を要約とみなす。形式は内容ではなく、従えた
    応答を捨てると圧縮の意味が失われるため。
    """
    summary = _extract_tag(response, SUMMARY_TAG)
    excerpts = _extract_tag(response, EXCERPTS_TAG)
    if not summary and not excerpts:
        return response.strip()
    return "\n\n".join(part for part in (summary, excerpts) if part)


def _reason_for_exception(exc: BaseException) -> str:
    """失敗の型を `CompressedSource.reason` の語彙へ写す。"""
    return REASON_TIMEOUT if isinstance(exc, TimeoutError) else REASON_ERROR


async def _collect_response(model: Any, prompt: str, timeout: float) -> tuple[str, str | None]:
    """1 回だけ呼び出し、`(本文, 失敗理由)` を返す（例外は投げない）。

    `asyncio.CancelledError` だけは再送出する。サービス終了要求を「圧縮できなかった」
    として飲み込むと、停止要求が部分失敗に化ける（contract §3）。
    """
    try:
        result = await asyncio.wait_for(model.ainvoke(prompt), timeout=timeout)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 失敗の型を問わず縮退する（FR-003）
        return "", _reason_for_exception(exc)

    content = result.content if hasattr(result, "content") else str(result)
    content = content if isinstance(content, str) else str(content)
    if not content.strip():
        return "", REASON_EMPTY
    return content, None


async def compress_text(
    text: str,
    *,
    model: Any,
    max_chars: int,
    timeout: float,
    instruction: str = "",
    source_id: str = "",
) -> tuple[str, CompressedSource | None]:
    """素材を 1 回の呼び出しで圧縮し、`(解析に渡す素材, 記録)` を返す。

    `len(text) <= max_chars` のときは**呼び出しを行わず** `(text, None)` を返す
    （FR-008 / SC-003）。超過時は結果を `max_chars` で切り詰める（FR-007。LLM の
    文字数遵守に依存しない）。

    Args:
        text: 素材（`_build_source_text` の結果。切り捨てずに**全体**を渡す）。
        model: `ainvoke(prompt)` を持つモデル。
        max_chars: しきい値（= `compression_threshold`）。出力の上限でもある。
        timeout: 1 回の呼び出しの上限秒（`compression_timeout_seconds`）。
        instruction: 素材の文脈を失わないためにプロンプトへ載せる元の指示文（R-5）。
        source_id: 記録に残す素材の識別子（`Candidate.id`）。
    """
    if len(text) <= max_chars:
        return text, None

    prompt = COMPRESSION_PROMPT.format(
        instruction=instruction or NO_INSTRUCTION, material=text
    )
    response, failure = await _collect_response(model, prompt, timeout)

    if failure is not None:
        # 縮退: 生素材をしきい値で切って使う（素材は捨てない。FR-003）
        truncated = text[:max_chars]
        return truncated, CompressedSource(
            source_id=source_id,
            input_chars=len(text),
            output_chars=len(truncated),
            applied=False,
            reason=failure,
        )

    compressed = _to_compressed_text(response)[:max_chars]
    return compressed, CompressedSource(
        source_id=source_id,
        input_chars=len(text),
        output_chars=len(compressed),
        applied=True,
        reason=REASON_COMPRESSED,
    )


async def compress_source(
    text: str,
    *,
    env_prefix: str | None,
    max_chars: int,
    timeout: float,
    instruction: str = "",
    source_id: str = "",
) -> tuple[str, CompressedSource | None]:
    """ノード向けの入口。しきい値を判定し、超過時のみモデルを構築して圧縮する。

    しきい値以下では `build_model` を**呼ばない**（追加の呼び出し 0 回。FR-008）。
    """
    if len(text) <= max_chars:
        return text, None
    model = build_model("compression", env_prefix)
    return await compress_text(
        text,
        model=model,
        max_chars=max_chars,
        timeout=timeout,
        instruction=instruction,
        source_id=source_id,
    )
