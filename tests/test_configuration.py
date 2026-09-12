"""Configuration クラスの単体テスト。"""

from langchain_core.runnables import RunnableConfig

from trend_researcher.configuration import Configuration


class TestConfigurationInit:
    """Configuration の初期化テスト。"""

    def test_all_defaults(self):
        """全フィールドのデフォルト値。"""
        c = Configuration()
        assert c.platform == "x"
        assert c.output_format is None  # 未設定時は LLM が判断
        assert c.max_results == 5
        assert c.sort_by == "relevance"
        assert c.transcript_language == "ja"
        assert c.use_trends is False
        assert c.cache_dir is None

    def test_custom_values(self):
        """カスタム値での初期化。"""
        c = Configuration(
            platform="youtube",
            output_format="json",
            max_results=10,
            sort_by="likes",
            transcript_language="en",
            use_trends=True,
            cache_dir="/tmp/cache",
        )
        assert c.platform == "youtube"
        assert c.output_format == "json"
        assert c.max_results == 10
        assert c.sort_by == "likes"
        assert c.transcript_language == "en"
        assert c.use_trends is True
        assert c.cache_dir == "/tmp/cache"


class TestFromRunnableConfig:
    """from_runnable_config のテスト。"""

    def test_with_full_config(self):
        """完全な RunnableConfig からの生成。"""
        rc: RunnableConfig = {
            "configurable": {
                "platform": "youtube",
                "output_format": "json",
                "max_results": 10,
                "sort_by": "likes",
                "transcript_language": "en",
                "use_trends": True,
                "cache_dir": "/tmp/cache",
            }
        }
        c = Configuration.from_runnable_config(rc)
        assert c.platform == "youtube"
        assert c.output_format == "json"
        assert c.max_results == 10
        assert c.sort_by == "likes"
        assert c.transcript_language == "en"
        assert c.use_trends is True
        assert c.cache_dir == "/tmp/cache"

    def test_with_partial_config(self):
        """部分的な RunnableConfig からの生成（未指定はデフォルト）。"""
        rc: RunnableConfig = {
            "configurable": {
                "platform": "youtube",
            }
        }
        c = Configuration.from_runnable_config(rc)
        assert c.platform == "youtube"
        assert c.output_format is None  # 未指定時は None（LLM が判断）
        assert c.max_results == 5  # デフォルト

    def test_with_empty_config(self):
        """空の RunnableConfig からの生成。"""
        rc: RunnableConfig = {}
        c = Configuration.from_runnable_config(rc)
        assert c.platform == "x"
        assert c.max_results == 5

    def test_with_none_config(self):
        """None の RunnableConfig からの生成。"""
        c = Configuration.from_runnable_config(None)
        assert c.platform == "x"
        assert c.max_results == 5

    def test_with_none_values_filtered(self):
        """None 値がフィルタリングされること。"""
        rc: RunnableConfig = {
            "configurable": {
                "platform": "youtube",
                "max_results": None,
            }
        }
        c = Configuration.from_runnable_config(rc)
        assert c.platform == "youtube"
        assert c.max_results == 5  # None はフィルタされデフォルトが使用される


class TestJsonSchema:
    """JSON スキーマ生成のテスト。"""

    def test_schema_has_required_properties(self):
        """スキーマが必要なプロパティを持つこと。"""
        schema = Configuration.model_json_schema()
        props = schema.get("properties", {})
        assert "platform" in props
        assert "output_format" in props
        assert "max_results" in props
        assert "sort_by" in props
        assert "transcript_language" in props
        assert "use_trends" in props
        assert "cache_dir" in props

    def test_schema_platform_values(self):
        """platform フィールドの型定義。"""
        schema = Configuration.model_json_schema()
        platform_prop = schema["properties"]["platform"]
        assert platform_prop.get("default") == "x"

    def test_model_dump_roundtrip(self):
        """model_dump → Configuration への復元。"""
        original = Configuration(platform="youtube", max_results=10)
        data = original.model_dump()
        restored = Configuration(**data)
        assert original == restored
