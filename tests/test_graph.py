"""trend_researcher グラフの統合テスト。"""


from trend_researcher.configuration import Configuration
from trend_researcher.graph import build_graph, trend_researcher
from trend_researcher.state import AgentState


class TestGraphBuild:
    """グラフ構築のテスト。"""

    def test_build_graph_returns_compiled_graph(self):
        """build_graph() が CompiledStateGraph を返すこと。"""
        graph = build_graph()
        assert graph is not None
        assert hasattr(graph, "ainvoke")

    def test_trend_researcher_entrypoint_exists(self):
        """trend_researcher エントリポイントが存在すること。"""
        assert trend_researcher is not None
        assert hasattr(trend_researcher, "ainvoke")


class TestAgentState:
    """AgentState のテスト。"""

    def test_agent_state_has_messages_field(self):
        """AgentState が messages フィールドを持つこと。"""
        assert "messages" in AgentState.__annotations__ or "messages" in dir(AgentState)

    def test_agent_state_inherits_messages_state(self):
        """AgentState が MessagesState をベースにしていること。"""
        # TypedDict は動的型付けが制限されるため、__annotations__ で確認
        assert "messages" in AgentState.__annotations__


class TestConfiguration:
    """Configuration のテスト。"""

    def test_default_values(self):
        """デフォルト値が正しく設定されること。"""
        config = Configuration()
        assert config.platform == "x"
        assert config.output_format is None  # 未設定時は LLM が判断
        assert config.max_results == 5
        assert config.sort_by == "relevance"
        assert config.transcript_language == "ja"
        assert config.use_trends is False
        assert config.cache_dir is None

    def test_from_runnable_config(self):
        """RunnableConfig から Configuration を生成できること。"""
        runnable_config = {
            "configurable": {
                "platform": "youtube",
                "output_format": "json",
                "max_results": 10,
            }
        }
        config = Configuration.from_runnable_config(runnable_config)
        assert config.platform == "youtube"
        assert config.output_format == "json"
        assert config.max_results == 10

    def test_from_runnable_config_with_none(self):
        """None の RunnableConfig からデフォルト値で生成されること。"""
        config = Configuration.from_runnable_config(None)
        assert config.platform == "x"
        assert config.max_results == 5

    def test_model_json_schema(self):
        """model_json_schema() が正しい JSON スキーマを生成すること。"""
        schema = Configuration.model_json_schema()
        assert "properties" in schema
        assert "platform" in schema["properties"]
        assert "output_format" in schema["properties"]
        assert "max_results" in schema["properties"]

    def test_model_dump(self):
        """model_dump() が正しい辞書を生成すること。"""
        config = Configuration(platform="youtube", max_results=10)
        data = config.model_dump()
        assert data["platform"] == "youtube"
        assert data["max_results"] == 10
