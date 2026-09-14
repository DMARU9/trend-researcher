"""上限超過の検出と段階的縮小の単体テスト（US3 / FR-015〜019 / contract §5・§6）。

固定する契約（`contracts/llm-invocation-contract.md`）:

- 検出は 4 条件を**すべて**満たすときだけ `True`（§5）。判定できない失敗を上限超過と
  誤認すると、情報を捨てたうえに同じ失敗を繰り返す（FR-018）
- 検出は**型**で行い、クラス名・モジュール名の**文字列**に依存しない（FR-063 / FR-064）。
  参照実装（`open_deep_research/src/utils.py:724`）の判定を移植していないことを、
  名前だけを模した偽の例外クラスで固定する
- 縮小は直前の入力長 × `shrink_ratio`、切り詰めは末尾（素材の先頭を残す）
- 停止条件は (a) 段数を使い切った (b) 縮小しない (c) `min_input_chars` 未満（§6）
- 未知のモデルでも比率のみで縮退し、記録に `limit_known = False` を残す（R-18 / D-2）
"""

from __future__ import annotations

import httpx
import openai
import pytest

from trend_researcher.tools.degradation import (
    MODEL_TOKEN_LIMITS,
    REASON_TOKEN_LIMIT,
    DegradeOptions,
    Ladder,
    get_model_token_limit,
    is_token_limit_exceeded,
    next_ladder,
    shrink,
)

#: 上限超過を判定する HTTP ステータス（contract §5 条件 2）
_LIMIT_STATUSES = (400, 413)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.test/v1/chat/completions")


def _status_error(
    status: int,
    *,
    message: str = "",
    body: object | None = None,
    error_type: type[openai.APIStatusError] | None = None,
) -> openai.APIStatusError:
    """HTTP ステータス付きの例外を作る（`body` は dict / str の双方を渡せる）。"""
    cls = error_type or (openai.BadRequestError if status == 400 else openai.APIStatusError)
    return cls(
        message=message,
        response=httpx.Response(status, request=_request()),
        body=body,
    )


def _context_length_body(*, extra_message: str = "") -> dict[str, object]:
    """実際の応答に近い上限超過の本文（`code` で判定できる形）。"""
    return {
        "error": {
            "message": f"This model's maximum context length is 128000 tokens.{extra_message}",
            "type": "invalid_request_error",
            "code": "context_length_exceeded",
        }
    }


# --- §5 条件 3: トークン量の指標 ------------------------------------------


@pytest.mark.parametrize("status", _LIMIT_STATUSES)
def test_a_context_length_code_is_detected(status: int) -> None:
    """条件 3 の `code == context_length_exceeded` で判定する（400 と 413 の両方）。"""
    exc = _status_error(status, message="bad request", body=_context_length_body())

    assert is_token_limit_exceeded(exc) is True


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {
                "error": {
                    "message": "This model's maximum context length is 128000 tokens.",
                    "type": "invalid_request_error",
                }
            },
            id="nested-error-object",
        ),
        pytest.param(
            {
                "message": "This model's maximum context length is 128000 tokens.",
                "type": "invalid_request_error",
            },
            id="top-level-message",
        ),
    ],
)
def test_an_invalid_request_with_the_vocabulary_is_detected(body: dict[str, object]) -> None:
    """条件 3 の第 2 経路（`invalid_request_error` ＋ 語彙）で判定する。"""
    exc = _status_error(400, message="bad request", body=body)

    assert is_token_limit_exceeded(exc) is True


@pytest.mark.parametrize(
    "vocabulary",
    [
        pytest.param("maximum context length", id="maximum-context"),
        pytest.param("context length exceeded", id="context-length"),
        pytest.param("too many tokens", id="too-many-tokens"),
        pytest.param("token limit exceeded", id="token-limit"),
        pytest.param("Please reduce the length of the messages", id="reduce-the-length"),
    ],
)
def test_the_vocabulary_variants_are_all_detected(vocabulary: str) -> None:
    """語彙の一覧（contract §5 条件 3）のどれでも判定できる（1 語だけの実装にしない）。"""
    body = {"error": {"message": vocabulary, "type": "invalid_request_error"}}

    assert is_token_limit_exceeded(_status_error(400, message=vocabulary, body=body)) is True


def test_a_string_body_is_handled_without_reading_attributes() -> None:
    """`body` が str でも例外にせず、保守側（`False`）に倒す（contract §5）。

    条件 3 は `body` の構造（`code` / `type`）を要求するため、str では成立しない。
    `body` を `isinstance` で分岐せず `getattr(exc, "code")` のように拾う実装にすると、
    構造の無い本文から「指標がある」と誤読して上限超過と誤認する（FR-018）。
    """
    exc = _status_error(
        400,
        message="This model's maximum context length is 128000 tokens.",
        body="This model's maximum context length is 128000 tokens.",
    )

    assert is_token_limit_exceeded(exc) is False


# --- §5 条件 3 の反例 -----------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"error": {"message": "bad request"}}, id="no-metric"),
        pytest.param({"error": {"type": "invalid_request_error"}}, id="type-without-vocabulary"),
        pytest.param({"error": {"code": "invalid_api_key"}}, id="other-code"),
        pytest.param({}, id="empty-body"),
        pytest.param(None, id="no-body"),
    ],
)
def test_a_400_without_a_token_metric_is_not_detected(body: object | None) -> None:
    """条件 3 を満たさない 400 は上限超過とみなさない（誤認の禁止。FR-018）。"""
    exc = _status_error(400, message="bad request", body=body)

    assert is_token_limit_exceeded(exc) is False


# --- §5 条件 2 ------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 422, 429, 500])
def test_other_status_codes_are_not_detected(status: int) -> None:
    """条件 2 を満たさない（400 / 413 以外）は上限超過とみなさない。"""
    exc = _status_error(status, message="maximum context length", body=_context_length_body())

    assert is_token_limit_exceeded(exc) is False


# --- §5 条件 4: 除外条件 --------------------------------------------------


@pytest.mark.parametrize(
    "word",
    [
        pytest.param("unsupported", id="unsupported"),
        pytest.param("unknown parameter", id="unknown-parameter"),
        pytest.param("invalid model", id="invalid-model"),
        pytest.param("does not exist", id="does-not-exist"),
        pytest.param("invalid api key", id="invalid-api-key"),
    ],
)
def test_the_exclusion_words_win_over_the_metric(word: str) -> None:
    """除外語があるときは、トークンの指標があっても上限超過とみなさない（条件 4）。

    指標（`code`）だけを見る実装にすると、無効な引数の 400 が縮退へ流れ、入力を
    切り詰めたうえに同じ失敗を繰り返す（FR-018 / FR-063）。
    """
    body = _context_length_body(extra_message=f" {word}")
    exc = _status_error(400, message=f"{word}: maximum context length exceeded", body=body)

    assert is_token_limit_exceeded(exc) is False


# --- §5 条件 1: 型で判定する（FR-063 / FR-064） ---------------------------


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(ValueError("maximum context length"), id="value-error"),
        pytest.param(TimeoutError("token limit"), id="timeout"),
        pytest.param(openai.APIConnectionError(request=_request()), id="connection-error"),
        pytest.param(
            openai.AuthenticationError(
                message="invalid api key",
                response=httpx.Response(401, request=_request()),
                body=None,
            ),
            id="authentication-error",
        ),
        pytest.param(
            openai.RateLimitError(
                message="429 Too Many Requests",
                response=httpx.Response(429, request=_request()),
                body=None,
            ),
            id="rate-limit",
        ),
    ],
)
def test_non_limit_exceptions_are_not_detected(exc: BaseException) -> None:
    """上限超過以外の例外（接続エラー・認証失敗・レート制限）は `False`。"""
    assert is_token_limit_exceeded(exc) is False


def test_a_class_that_only_imitates_the_name_is_not_detected() -> None:
    """クラス名だけを模した例外（`APIStatusError` の派生でない）は `False`。

    参照実装は `exception.__class__.__name__` と `__module__` の**文字列**で判定する
    ため、名前が一致すれば型が違っても通ってしまう（FR-064）。
    """

    class BadRequestError(Exception):
        status_code = 400
        body = _context_length_body()

    assert is_token_limit_exceeded(BadRequestError("maximum context length")) is False


def test_a_renamed_subclass_of_the_real_exception_is_detected() -> None:
    """**実物の派生**ならクラス名・モジュール名が一致しなくても検出する。

    `isinstance` による型判定を固定する反例（文字列比較の実装では落ちる）。
    """

    class _CustomLimitError(openai.BadRequestError):
        status_code = 400

    exc = _CustomLimitError(
        message="maximum context length",
        response=httpx.Response(400, request=_request()),
        body=_context_length_body(),
    )

    assert type(exc).__module__ != "openai"
    assert is_token_limit_exceeded(exc) is True


# --- モデル上限テーブル（R-18） -------------------------------------------


def test_a_known_model_returns_its_token_limit() -> None:
    """表にあるモデルは上限トークンを返す（登録済みの鍵は**自分の値**を返す。R-18）。"""
    assert get_model_token_limit("openai:gpt-4o") == 128000
    assert get_model_token_limit("openai:gpt-4.1-mini") == 1047576


def test_an_unknown_model_returns_none() -> None:
    """表に無いモデルは `None`（既定の `openai:mimo-v2.5` は表に無い。R-18）。"""
    assert get_model_token_limit("openai:mimo-v2.5") is None
    assert get_model_token_limit("") is None


def test_no_registered_key_is_shadowed() -> None:
    """表のすべての鍵が**自分の値**を返す（短い鍵が長い鍵を影にしない。FR-063 / FR-064）。

    参照実装は `key in model` の部分文字列を辞書の反復順に見るため、`openai:o1` が
    `openai:o1-pro` を覆い、`openai:o1-pro` 自身の登録値は到達不能になる。
    """
    shadowed = {
        key: get_model_token_limit(key)
        for key, limit in MODEL_TOKEN_LIMITS.items()
        if get_model_token_limit(key) != limit
    }

    assert shadowed == {}


def test_the_reported_shadowing_does_not_come_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """実測した影（`openai:o1` → `openai:o1-pro`）が戻らない（FR-063）。

    収束チェックの実測: 参照実装の規則では `openai:o1` の値を 111111 に変えると
    `openai:o1-pro` の答えが 111111 になり、自身の登録値 200000 は到達不能だった。
    """
    assert get_model_token_limit("openai:o1-pro") == MODEL_TOKEN_LIMITS["openai:o1-pro"]

    monkeypatch.setitem(MODEL_TOKEN_LIMITS, "openai:o1", 111111)

    assert get_model_token_limit("openai:o1-pro") == MODEL_TOKEN_LIMITS["openai:o1-pro"]
    assert get_model_token_limit("openai:o1") == 111111


def test_no_key_shadows_a_longer_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """影になり得る組を**値の差**で炙り出す（表の値が等しい組でも検出する。FR-063）。

    `openai:o1` と `openai:o1-pro` はどちらも 200000 なので、値の比較だけでは影を
    見つけられない。短い鍵の値を反転しても長い鍵の答えが動かないことを確かめる。
    """
    pairs = [
        (short, long)
        for short in MODEL_TOKEN_LIMITS
        for long in MODEL_TOKEN_LIMITS
        if short != long and long.startswith(short)
    ]

    assert pairs, "影になり得る組が表に無い（この検査が空振りしている）"
    for short, long in pairs:
        monkeypatch.setitem(MODEL_TOKEN_LIMITS, short, -1)

        assert get_model_token_limit(long) == MODEL_TOKEN_LIMITS[long], (short, long)


def test_the_longest_registered_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """前方一致では**最も長い**鍵が勝つ（短い鍵が覆い隠さない。FR-063）。"""
    monkeypatch.setitem(MODEL_TOKEN_LIMITS, "openai:aaa", 111)
    monkeypatch.setitem(MODEL_TOKEN_LIMITS, "openai:aaa-bbb", 222)

    assert get_model_token_limit("openai:aaa-bbb") == 222
    assert get_model_token_limit("openai:aaa-bbb-ccc") == 222
    assert get_model_token_limit("openai:aaa-ccc") == 111


def test_a_variant_name_matches_by_prefix() -> None:
    """日付つきの派生名は前方一致で引ける（鍵は `provider:model` の形。R-18）。"""
    assert get_model_token_limit("openai:gpt-4o-2024-08-06") == 128000
    assert get_model_token_limit("anthropic:claude-3-5-sonnet-20241022") == 200000
    assert get_model_token_limit("google:gemini-pro-vision") == 32768


def test_a_key_inside_the_name_is_not_matched() -> None:
    """鍵が名前の**途中**に現れても一致にしない（部分文字列ではなく前方一致。FR-063）。"""
    assert get_model_token_limit("mimo-v2.5:openai:gpt-4o") is None
    assert get_model_token_limit("gpt-4o") is None


# --- `shrink` ------------------------------------------------------------


def test_shrink_keeps_the_head_and_drops_the_tail() -> None:
    """縮小は末尾を切る（素材の先頭を残す。contract §6）。"""
    text = "0123456789"

    assert shrink(text, 0.5) == "01234"
    assert shrink(text, 0.9) == "012345678"


def test_shrink_is_monotonic_for_the_configured_ratios() -> None:
    """比率を下げれば必ず短くなる（段ごとに前進する）。"""
    text = "x" * 1000

    assert len(shrink(text, 0.9)) < len(shrink(text, 0.95)) < len(text)


# --- 段階的縮小（§6 / R-4） -----------------------------------------------


def _options(**overrides: object) -> DegradeOptions:
    """検証用の縮退の設定（既定は `Configuration` の既定値と同じ）。"""
    values: dict[str, object] = {
        "node_name": "analyze_content",
        "max_attempts": 3,
        "shrink_ratio": 0.9,
        "min_input_chars": 1000,
    }
    values.update(overrides)
    return DegradeOptions(**values)  # type: ignore[arg-type]


def _drain(ladder: Ladder) -> list[str]:
    """梯子を最後まで進め、各段で呼び直す入力を集める。"""
    stages: list[str] = []
    while (shrunk := ladder.advance()) is not None:
        stages.append(shrunk)
    return stages


def test_the_ladder_does_not_exceed_the_max_attempts() -> None:
    """段数は `degrade_max_attempts` を超えない（使い切ったら停止する）。"""
    ladder = Ladder("x" * 100000, _options(max_attempts=3))

    stages = _drain(ladder)

    assert len(stages) == 3
    assert ladder.stage == 3
    assert [record.stage for record in ladder.options.records] == [1, 2, 3]


@pytest.mark.parametrize("max_attempts", [1, 2, 4])
def test_the_stage_count_follows_the_configuration(max_attempts: int) -> None:
    """段数は設定から注入される（コードに固定値を持たない。FR-005）。"""
    ladder = Ladder("x" * 100000, _options(max_attempts=max_attempts))

    assert len(_drain(ladder)) == max_attempts


def test_each_stage_shrinks_by_the_ratio() -> None:
    """各段の入力長は直前の段の `shrink_ratio` 倍になる。"""
    ladder = Ladder("x" * 20000, _options(shrink_ratio=0.9))

    stages = _drain(ladder)

    expected = 20000
    for stage in stages:
        expected = int(expected * 0.9)
        assert len(stage) == expected
    assert [r.after_chars for r in ladder.options.records] == [
        int(20000 * 0.9),
        int(int(20000 * 0.9) * 0.9),
        int(int(int(20000 * 0.9) * 0.9) * 0.9),
    ]


def test_the_ladder_stops_when_the_input_cannot_shrink() -> None:
    """停止条件 2: 縮小しても短くならないなら打ち切る（同じ呼び出しを繰り返さない）。"""
    ladder = Ladder("x" * 5000, _options(shrink_ratio=1.0))

    assert _drain(ladder) == []
    assert ladder.stage == 0
    assert ladder.options.records == []


def test_the_ladder_stops_below_the_minimum_input_length() -> None:
    """停止条件 3: 縮小後の長さが `min_input_chars` を下回るなら打ち切る。"""
    ladder = Ladder("x" * 1000, _options(shrink_ratio=0.5, min_input_chars=600))

    assert _drain(ladder) == []
    assert ladder.stage == 0


def test_the_minimum_input_length_is_inclusive() -> None:
    """`min_input_chars` ちょうどは縮退できる（未満のみ打ち切る）。"""
    ladder = Ladder("x" * 1000, _options(shrink_ratio=0.5, min_input_chars=500))

    assert [len(stage) for stage in _drain(ladder)] == [500]


def test_a_known_model_uses_the_token_limit_for_the_first_stage() -> None:
    """既知のモデルでは上限トークンから「上限に収まる文字数」を初回の目標にする。"""
    ladder = Ladder(
        "x" * 200000,
        _options(max_attempts=1, shrink_ratio=0.9),
        model="openai:gpt-4o",
    )

    assert ladder.limit_known is True
    stages = _drain(ladder)

    assert len(stages) == 1
    # 128000 トークン − 出力枠の控除（10000 トークン）= 118000 文字
    assert len(stages[0]) == 118000
    assert ladder.options.records[0].limit_known is True


def test_an_unknown_model_shrinks_by_the_ratio_and_records_limit_known_false() -> None:
    """未知のモデルでも縮退は成立し、`limit_known = False` が記録される（R-18）。"""
    ladder = Ladder("x" * 20000, _options(), model="openai:mimo-v2.5")

    stages = _drain(ladder)

    assert ladder.limit_known is False
    assert len(stages) == 3
    assert all(record.limit_known is False for record in ladder.options.records)


def test_a_model_without_a_name_is_treated_as_unknown() -> None:
    """モデル名が分からない場合も比率のみで縮退する（縮退を諦めない。R-18）。"""
    ladder = Ladder("x" * 20000, _options(max_attempts=1))

    assert ladder.limit_known is False
    assert [len(stage) for stage in _drain(ladder)] == [18000]


def test_the_record_carries_the_node_stage_lengths_and_reason() -> None:
    """記録は `Degradation(node, stage, before, after, "token_limit", limit_known)`。"""
    ladder = Ladder("x" * 10000, _options(max_attempts=1, node_name="parse_instruction"))

    _drain(ladder)
    record = ladder.options.records[0]

    assert record.node_name == "parse_instruction"
    assert record.stage == 1
    assert record.before_chars == 10000
    assert record.after_chars == 9000
    assert record.reason == REASON_TOKEN_LIMIT
    assert record.limit_known is False


def test_the_reason_is_not_the_compression_reason() -> None:
    """縮退は圧縮と別の段階として記録する（FR-019）。"""
    ladder = Ladder("x" * 10000, _options(max_attempts=1))

    _drain(ladder)

    assert ladder.options.records[0].reason != "compressed"


# --- 到達不能な分岐の棚卸し（T104 / FR-063 / FR-064） ------------------------
#
# 分岐カバレッジの実測で「未実行」だった分岐を triage した結果を固定する。判定の
# 規則は 2 つ: (a) 到達不能を論証でき、削除しても危険が増えないなら**削除**する、
# (b) 削除すると危険が増える（未検証の入力で KeyError になる等）なら**残して根拠を
# コメントとテストで固定する**。ここは (a) の対象（`_budget` の `tokens <= 0`）。


def test_the_budget_is_positive_for_every_registered_limit() -> None:
    """表の**すべて**の上限で予算が正になる（`tokens <= 0` は到達しない。T104）。

    上限テーブルの最小値は 32768 で、出力枠の控除 10000 を引いても 22768 が残る。
    したがって「予算が 0 以下」の分岐は現行の表からは到達できない。到達不能な
    分岐は削除し（`max(..., 0)` で下限だけを残す）、この検査がその前提を固定する。
    """
    budgets = {key: Ladder._budget(limit) for key, limit in MODEL_TOKEN_LIMITS.items()}

    assert all(budget is not None and budget > 0 for budget in budgets.values())
    assert budgets == {key: limit - 10000 for key, limit in MODEL_TOKEN_LIMITS.items()}
    # 削除した分岐の前提そのもの（表の最小値でも控除を引いて正が残る）
    assert min(MODEL_TOKEN_LIMITS.values()) - 10000 > 0


def test_the_budget_is_none_only_when_the_limit_is_unknown() -> None:
    """上限が分からないときだけ `None`（予算の制約なし＝比率のみで縮退する。R-18）。"""
    assert Ladder._budget(None) is None
    assert Ladder._budget(32768) == 22768


def test_a_limit_within_the_output_reserve_leaves_no_budget() -> None:
    """上限が出力枠以下なら予算は 0（`None` に落とさない。T104）。

    0 は「これ以上縮められない」を意味し、梯子は 1 段も進まない（`min_input_chars`
    の停止条件で打ち切られる）。`None`（＝無制限）へ落とすと、上限より大きい入力の
    まま呼び直して同じ失敗を繰り返す。
    """
    assert Ladder._budget(5000) == 0
    assert Ladder._budget(10000) == 0
    assert next_ladder("x" * 10000, ratio=0.9, min_input_chars=100, char_budget=0) is None
