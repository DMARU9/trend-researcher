"""上限超過（コンテキスト長超過）の検出と、入力の段階的縮小（US3 / FR-015〜019）。

`contracts/llm-invocation-contract.md` §5・§6 の実装。呼び出しの駆動は
`tools/llm.py` が担い、このモジュールは**判定と縮小の純粋な部分**と、段を作る梯子
（`Ladder`）を持つ。

参照実装（`open_deep_research/src/utils.py:724` の `is_token_limit_exceeded()`）の判定は
**移植しない**（FR-063 / FR-064 / research §R-1）。あちらはクラス名
（`exception.__class__.__name__`）とモジュール名（`'openai' in module_name.lower()`）の
**文字列**で判定し、例外クラスごとに 3 つの checker を呼び分け、既知でないと**すべて
試す**。ここでは `isinstance` による型判定と `body` の構造だけを使い、判定を 1 経路に
保つ。無効な引数をモデルへ渡す経路も作らない（別モデルへの切り替え・引数の組み替えは
しない。contract §6 の禁止事項）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openai import APIStatusError

from trend_researcher.configuration import Configuration
from trend_researcher.models import Degradation

#: `Degradation.reason` の値（data-model §3.2）。圧縮の `"compressed"` と混ぜない（FR-019）。
REASON_TOKEN_LIMIT = "token_limit"

#: 上限超過を判定する HTTP ステータス（400 = リクエスト不正 / 413 = 本文が大きすぎる）。
_LIMIT_STATUS_CODES = frozenset({400, 413})

#: 応答本文の `code` が上限超過そのものを表す値（条件 3 の第 1 経路）。
_TOKEN_LIMIT_CODES = frozenset({"context_length_exceeded"})

#: 条件 3 の第 2 経路で要求する `type`（無効なリクエスト）。
_INVALID_REQUEST_TYPES = frozenset({"invalid_request_error"})

#: 条件 3 の語彙（小文字で比較）。日本語のトピックでも API の応答は英語なので英語語彙のみ。
_TOKEN_LIMIT_WORDS = (
    "context length",
    "maximum context",
    "too many tokens",
    "token limit",
    "reduce the length",
)

#: 条件 4 の除外語彙。無効な引数・設定ミスを示す語が 1 つでもあれば上限超過とみなさない
#: （誤認の禁止。FR-018）。`400` は両方の意味で返るため、この条件が要る。
_EXCLUDED_WORDS = (
    "unsupported",
    "unknown parameter",
    "invalid model",
    "does not exist",
    "invalid api key",
)

#: モデルごとのコンテキスト上限（トークン）。参照実装の表を移植する（research §R-18）。
#:
#: **表に無いモデルは `None` を返し、比率のみで縮退する。** 既定のモデル
#: （`openai:mimo-v2.5`）はこの表に無いため、上限が既知でないと縮退できない設計
#: （参照実装は例外にする）では FR-015 を満たせない（D-2 / R-18 の実測）。
MODEL_TOKEN_LIMITS: dict[str, int] = {
    "openai:gpt-4.1-mini": 1047576,
    "openai:gpt-4.1-nano": 1047576,
    "openai:gpt-4.1": 1047576,
    "openai:gpt-4o-mini": 128000,
    "openai:gpt-4o": 128000,
    "openai:o4-mini": 200000,
    "openai:o3-mini": 200000,
    "openai:o3": 200000,
    "openai:o3-pro": 200000,
    "openai:o1": 200000,
    "openai:o1-pro": 200000,
    "anthropic:claude-opus-4": 200000,
    "anthropic:claude-sonnet-4": 200000,
    "anthropic:claude-3-7-sonnet": 200000,
    "anthropic:claude-3-5-sonnet": 200000,
    "anthropic:claude-3-5-haiku": 200000,
    "google:gemini-1.5-pro": 2097152,
    "google:gemini-1.5-flash": 1048576,
    "google:gemini-pro": 32768,
    "cohere:command-r-plus": 128000,
    "cohere:command-r": 128000,
    "mistral:mistral-large": 32768,
    "mistral:mistral-medium": 32768,
    "mistral:mistral-small": 32768,
}

#: 上限トークンを文字数へ換算する係数。1 トークン = 1 文字として**少なめ**に見積もる
#: （日本語はトークンあたりの文字数が少なく、多めに見積もると上限を超えたまま呼ぶ）。
_CHARS_PER_TOKEN = 1

#: 応答の生成に残すトークン（`tools/llm.py` の `_ROLE_MAX_TOKENS` の最大値に合わせる）。
_OUTPUT_RESERVE_TOKENS = 10000


def _body_strings(exc: APIStatusError) -> list[str]:
    """判定に使う文字列を `body` から集める（dict / str の双方を扱う）。

    `body` は応答本文そのものなので、`error` の入れ子と `message` / `type` / `code` の
    位置が経路によって異なる。`isinstance` で構造を確かめながら両方の位置を見る
    （`getattr` で属性を拾う実装にしない。contract §5）。
    """
    parts: list[str] = []
    body = exc.body
    if isinstance(body, str):
        parts.append(body)
        return parts
    if not isinstance(body, dict):
        return parts

    for source in (body.get("error"), body):
        if not isinstance(source, dict):
            continue
        for key in ("message", "type", "code"):
            value = source.get(key)
            if isinstance(value, str):
                parts.append(value)
    return parts


def _body_values(exc: APIStatusError, key: str) -> list[str]:
    """`body` の `error` 直下と最上位から、指定したキーの文字列値を集める。"""
    values: list[str] = []
    body = exc.body
    if not isinstance(body, dict):
        return values
    for source in (body.get("error"), body):
        if isinstance(source, dict):
            value = source.get(key)
            if isinstance(value, str):
                values.append(value)
    return values


def is_token_limit_exceeded(exc: BaseException) -> bool:
    """コンテキスト長超過の失敗かどうかを判定する（contract §5）。

    4 つの条件を**すべて**満たすときだけ `True`。

    1. `isinstance(exc, openai.APIStatusError)`（**型**で判定する。FR-063）
    2. `exc.status_code in (400, 413)`
    3. `body` にトークン量の指標がある（`code == "context_length_exceeded"`、または
       `type == "invalid_request_error"` ＋ 語彙）
    4. 無効な引数・設定ミスを示す語が**無い**（FR-018）

    判定できない失敗を上限超過と誤認すると、入力を切り詰めて情報を捨てたうえに同じ
    失敗を繰り返す。したがって保守側（`False`）へ倒す。
    """
    # 条件 1: 型で判定する（クラス名・モジュール名の文字列比較をしない）
    if not isinstance(exc, APIStatusError):
        return False

    # 条件 2: HTTP ステータス
    if exc.status_code not in _LIMIT_STATUS_CODES:
        return False

    text = " ".join([*_body_strings(exc), str(exc)]).lower()

    # 条件 4: 除外語彙（条件 3 より先に見る。指標があっても無効な引数なら上限超過ではない）
    if any(word in text for word in _EXCLUDED_WORDS):
        return False

    # 条件 3: トークン量の指標
    if any(code in _TOKEN_LIMIT_CODES for code in _body_values(exc, "code")):
        return True
    return any(value in _INVALID_REQUEST_TYPES for value in _body_values(exc, "type")) and any(
        word in text for word in _TOKEN_LIMIT_WORDS
    )


def get_model_token_limit(model: str) -> int | None:
    """モデルのコンテキスト上限（トークン）を引く。表に無ければ `None`（R-18）。

    規則は**最も長い前方一致**（表の鍵と `provider:model` の形で突き合わせる）。
    登録済みの鍵は自分自身が最長の前方一致になるため、**完全一致が必ず優先される**。

    参照実装（`open_deep_research/src/utils.py:900`）は `model_key in model_string` の
    部分文字列を**辞書の反復順**に見るため、(1) 短い鍵が長い鍵を影にする
    （`openai:o1` の値を変えると `openai:o1-pro` の答えが変わり、登録値が到達不能に
    なる）、(2) 鍵が名前の途中に現れても一致する。どちらも移植しない（FR-063 / FR-064）。
    """
    for key in sorted(MODEL_TOKEN_LIMITS, key=len, reverse=True):
        if model.startswith(key):
            return MODEL_TOKEN_LIMITS[key]
    return None


def shrink(text: str, ratio: float) -> str:
    """入力を `ratio` 倍の長さに切り詰める（末尾を落とし、先頭を残す。contract §6）。"""
    return text[: int(len(text) * ratio)]


def next_ladder(
    text: str,
    *,
    ratio: float,
    min_input_chars: int,
    char_budget: int | None = None,
) -> str | None:
    """次の段の入力長を返す（停止条件を満たすなら `None`）。

    停止条件は (b) 縮小後の長さが前段と同じ、(c) `min_input_chars` 未満（contract §6）。
    段数を使い切る条件 (a) は呼び出し側（`Ladder`）が数える。

    Args:
        text: 直前の段の入力。
        ratio: `shrink_ratio`。
        min_input_chars: 縮退を打ち切る入力長の下限。
        char_budget: 既知モデルの上限に収まる文字数。比率より小さいときだけ効く。
    """
    target = int(len(text) * ratio)
    if char_budget is not None:
        target = min(target, char_budget)
    shrunk = text[:target]
    if len(shrunk) >= len(text):
        # 停止条件 (b): 比率適用で短くならない（例: `shrink_ratio = 1.0`）。同じ呼び出しを
        # 繰り返しても結果は変わらないため打ち切る（無限縮小の禁止。FR-015）
        return None
    if len(shrunk) < min_input_chars:
        # 停止条件 (c): 下限を下回った
        return None
    return shrunk


@dataclass
class DegradeOptions:
    """縮退の設定と、段の記録の受け皿（1 ノード実行につき 1 つ）。

    ノードが `Configuration` から設定を写して作り、呼び出し境界（`tools/llm.py`）が段ごとに
    `records` へ `Degradation` を追記する。ノードは呼び出しの後に
    `{"degradations": options.records}` として状態へ渡す（FR-017）。
    """

    node_name: str
    max_attempts: int
    shrink_ratio: float
    min_input_chars: int
    records: list[Degradation] = field(default_factory=list)


def options_for(settings: Configuration, node_name: str) -> DegradeOptions:
    """`Configuration` から縮退の設定を取り出す（値の出所をノードへ書かない。FR-005）。"""
    return DegradeOptions(
        node_name=node_name,
        max_attempts=settings.degrade_max_attempts,
        shrink_ratio=settings.shrink_ratio,
        min_input_chars=settings.min_input_chars,
    )


class Ladder:
    """入力を段階的に落とす梯子（contract §6 / research §R-4）。

    1 回の呼び出しの失敗を受けて作り、`advance()` で次の段の入力を得る。段を作るたびに
    `Degradation` を記録する（記録は「実際に縮小して呼び直した段」だけを残す）。
    """

    def __init__(self, original: str, options: DegradeOptions, *, model: str = "") -> None:
        """
        Args:
            original: 最初に失敗した入力。
            options: 縮退の設定（記録は `options.records` へ追記する）。
            model: 解決済みのモデル名（`get_model_token_limit` に渡す。空なら未知扱い）。
        """
        self.original = original
        self.options = options
        limit = get_model_token_limit(model) if model else None
        #: 上限が既知かどうか。`Degradation.limit_known` に写す（R-18）。
        self.limit_known = limit is not None
        self._char_budget = self._budget(limit)
        self.stage = 0
        self.current = original

    @staticmethod
    def _budget(limit: int | None) -> int | None:
        """上限トークンから「上限に収まる文字数」を求める（求まらないなら `None`）。

        上限が分からないとき（`None`）だけ `None` を返し、予算の制約を外す（比率のみで
        縮退する。R-18）。上限が分かっているときは**必ず**文字数を返し、0 で下限を切る。

        かつては「控除後のトークンが 0 以下なら `None`」という分岐があったが、これは
        到達不能だった（`MODEL_TOKEN_LIMITS` の最小値は 32768、控除は 10000 なので
        控除後は必ず 22768 以上。分岐カバレッジでも未実行）。到達不能な分岐は残さず、
        下限だけを `max(..., 0)` で表す。**`None`（無制限）へ落とさない**のが要点で、
        予算 0 は「これ以上縮められない」として `next_ladder` の停止条件で打ち切られる
        （上限より大きい入力のまま呼び直して同じ失敗を繰り返さない。FR-065 / T104）。
        """
        if limit is None:
            return None
        return max(limit - _OUTPUT_RESERVE_TOKENS, 0) * _CHARS_PER_TOKEN

    def advance(self) -> str | None:
        """1 段縮めて、その段の入力を返す（停止条件を満たすなら `None`）。

        縮小しない段は記録しない（`Degradation` も同じ不変条件を持つ。R-4 の停止条件 2）。
        """
        if self.stage >= self.options.max_attempts:
            return None
        shrunk = next_ladder(
            self.current,
            ratio=self.options.shrink_ratio,
            min_input_chars=self.options.min_input_chars,
            char_budget=self._char_budget,
        )
        if shrunk is None:
            return None
        self.stage += 1
        record = Degradation(
            node_name=self.options.node_name,
            stage=self.stage,
            before_chars=len(self.current),
            after_chars=len(shrunk),
            reason=REASON_TOKEN_LIMIT,
            limit_known=self.limit_known,
        )
        self.options.records.append(record)
        self.current = shrunk
        return shrunk

    def summary(self) -> str:
        """補足行 1 行（`ProgressEmitter.note()`。FR-017 / FR-029）。"""
        return (
            f"縮退: {self.options.node_name} / {self.stage} 段 / "
            f"{len(self.original)} → {len(self.current)} 文字"
        )

    def reason(self) -> str:
        """使い切った理由（`__main__.py` が stderr に出す。FR-015）。"""
        return (
            f"上限超過のため生成できませんでした（ノード: {self.options.node_name} / "
            f"試した段数: {self.stage} / 縮小前: {len(self.original)} 文字 → "
            f"縮小後: {len(self.current)} 文字）"
        )


class DegradationError(RuntimeError):
    """縮退を使い切った（FR-015 / US3 シナリオ 2）。

    `__main__.py` が `str(exc)` を stderr に出して**終了コード 1** で終わる。段数と
    縮小前後の長さは属性でも持つ（テストが文言に依存しないため）。
    """

    def __init__(self, ladder: Ladder) -> None:
        super().__init__(ladder.reason())
        self.node_name = ladder.options.node_name
        self.stages = ladder.stage
        self.before_chars = len(ladder.original)
        self.after_chars = len(ladder.current)
