# mcp_manager.py
import asyncio
import os
from contextlib import AsyncExitStack
from mcp import ClientSession
from mcp.client.sse import sse_client
from langchain_core.tools import StructuredTool

class RAGConnectionManager:
    """
    单例模式：维护与 RAG MCP Server (HTTP SSE) 的全局长连接。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._session = None
            cls._instance._exit_stack = None
        return cls._instance

    async def connect(self, sse_url: str = "http://127.0.0.1:8000/sse"):
        if self._session is not None:
            return

        self._exit_stack = AsyncExitStack()
        try:
            streams = await self._exit_stack.enter_async_context(sse_client(sse_url))
            read_stream, write_stream = streams
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()
        except Exception as e:
            await self._exit_stack.aclose()
            self._session = None
            raise e

    async def get_all_rag_tools(self) -> list[StructuredTool]:
        if not self._session:
            raise RuntimeError("MCP 会话未建立")
        mcp_tools = await self._session.list_tools()
        langchain_tools = []
        for t in mcp_tools.tools:
            def create_async_caller(tool_name):
                async def async_caller(**kwargs) -> str:
                    result = await self._session.call_tool(tool_name, arguments=kwargs)
                    return result.content[0].text
                return async_caller
            lc_tool = StructuredTool.from_function(
                coroutine=create_async_caller(t.name),
                name=t.name,
                description=t.description,
            )
            langchain_tools.append(lc_tool)
        return langchain_tools

    async def disconnect(self):
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._session = None
            self._exit_stack = None
