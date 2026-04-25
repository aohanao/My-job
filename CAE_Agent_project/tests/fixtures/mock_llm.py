"""Mock LLM for testing - 避免真实API调用"""
from typing import Any, Dict, List, Optional, Callable
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult


class MockLLM(BaseChatModel):
    """可配置的Mock LLM，用于测试"""

    responses: List[Any] = []
    current_index: int = 0

    def __init__(self, responses: Optional[List[Any]] = None, **kwargs):
        super().__init__(**kwargs)
        self.responses = responses or []
        self.current_index = 0

    @property
    def _llm_type(self) -> str:
        return "mock"

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs) -> ChatResult:
        """生成mock响应"""
        if self.current_index >= len(self.responses):
            response = {"content": "Mock response"}
        else:
            response = self.responses[self.current_index]
            self.current_index += 1

        if isinstance(response, dict):
            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])
            message = AIMessage(content=content, tool_calls=tool_calls)
        elif isinstance(response, str):
            message = AIMessage(content=response)
        else:
            message = response

        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    def with_structured_output(self, schema: Any, **kwargs):
        """返回支持结构化输出的mock"""
        return MockStructuredLLM(responses=self.responses, schema=schema)

    def bind_tools(self, tools: List[Any], **kwargs):
        """返回绑定工具的mock"""
        return MockToolBoundLLM(responses=self.responses, tools=tools)


class MockStructuredLLM:
    """支持结构化输出的Mock LLM"""

    def __init__(self, responses: List[Any], schema: Any):
        self.responses = responses
        self.schema = schema
        self.current_index = 0

    def invoke(self, messages: List[BaseMessage], **kwargs) -> Any:
        """返回结构化响应"""
        if self.current_index >= len(self.responses):
            # 返回默认结构
            if hasattr(self.schema, 'model_fields'):
                # Pydantic模型
                return self.schema()
            return {}

        response = self.responses[self.current_index]
        self.current_index += 1

        # 如果响应是字典且schema是Pydantic模型，转换为模型实例
        if isinstance(response, dict) and hasattr(self.schema, 'model_validate'):
            return self.schema.model_validate(response)

        return response


class MockToolBoundLLM:
    """绑定工具的Mock LLM"""

    def __init__(self, responses: List[Any], tools: List[Any]):
        self.responses = responses
        self.tools = tools
        self.current_index = 0

    def invoke(self, messages: List[BaseMessage], **kwargs) -> AIMessage:
        """返回可能包含工具调用的响应"""
        if self.current_index >= len(self.responses):
            return AIMessage(content="Mock response")

        response = self.responses[self.current_index]
        self.current_index += 1

        if isinstance(response, dict):
            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])
            return AIMessage(content=content, tool_calls=tool_calls)
        elif isinstance(response, AIMessage):
            return response
        else:
            return AIMessage(content=str(response))


def create_mock_llm(responses: List[Any]) -> MockLLM:
    """创建Mock LLM的工厂函数"""
    return MockLLM(responses=responses)
