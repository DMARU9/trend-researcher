"""tools/llm.py の単体テスト（init_chat_model をモック）。"""

from unittest import mock

from trend_researcher.tools.llm import build_model


def test_build_model_returns_callable():
    with mock.patch("trend_researcher.tools.llm.init_chat_model") as m:
        m.return_value = "fake-model"
        model = build_model("research")
    assert model == "fake-model"
    m.assert_called_once()
    _, kwargs = m.call_args
    assert "configurable_fields" in kwargs
    assert kwargs["configurable_fields"] == ("model", "max_tokens", "api_key")
