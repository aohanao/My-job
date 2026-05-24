import asyncio
import os
from contextlib import AsyncExitStack
import mcp
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client, get_default_environment, StdioServerParameters as ServerParameters
from pydantic import create_model, Field, BaseModel

def json_schema_to_pydantic(model_name: str, schema: dict):
    """将 JSON Schema 字典动态转换为 Pydantic BaseModel"""
    if not schema or schema.get("type") != "object":
        return None
        
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    
    fields = {}
    for field_name, field_info in properties.items():
        field_type = str
        schema_type = field_info.get("type")
        if schema_type == "integer":
            field_type = int
        elif schema_type == "number":
            field_type = float
        elif schema_type == "boolean":
            field_type = bool
        elif schema_type == "array":
            field_type = list
        elif schema_type == "object":
            field_type = dict
            
        desc = field_info.get("description", "")
        default_val = field_info.get("default")
        
        if field_name in required and default_val is None:
            fields[field_name] = (field_type, Field(..., description=desc))
        else:
            fields[field_name] = (field_type, Field(default=default_val, description=desc))
            
    return create_model(model_name, **fields)


class MCPConnectionManager:
    """
    MCP Server 连接管理器。
    支持与多个 MCP Server 建立独立连接。
    """
    def __init__(self):
        self._session = None
        self._exit_stack = None

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

    async def get_tools(self) -> list[StructuredTool]:
        if not self._session:
            raise RuntimeError("MCP 会话未建立")
        
        mcp_tools = await self._session.list_tools()
        langchain_tools = []
        
        for t in mcp_tools.tools:
            def create_async_caller(tool_name):
                async def async_caller(**kwargs) -> str:
                    # 🚀 [核心修复 1]: 处理 LLM 的嵌套幻觉
                    # 如果参数被裹在了 {'kwargs': {...}} 里，手动拆出来
                    if "kwargs" in kwargs and len(kwargs) == 1:
                        actual_args = kwargs["kwargs"]
                    else:
                        actual_args = kwargs
                    
                    try:
                        # 增加一层超时保护，防止无限等待
                        result = await asyncio.wait_for(
                            self._session.call_tool(tool_name, arguments=actual_args),
                            timeout=30.0
                        )
                        return result.content[0].text
                    except asyncio.TimeoutError:
                        return "错误：知识库响应超时（30s），请稍后重试。"
                    except Exception as e:
                        return f"工具调用内部错误: {str(e)}"
                return async_caller

            schema_model = None
            if hasattr(t, "inputSchema") and t.inputSchema:
                try:
                    schema_model = json_schema_to_pydantic(f"{t.name}Schema", t.inputSchema)
                except Exception as se:
                    print(f"[MCP] ⚠️ 动态为工具 {t.name} 解析 Schema 失败: {se}")

            lc_tool = StructuredTool.from_function(
                coroutine=create_async_caller(t.name),
                name=t.name,
                description=t.description,
                args_schema=schema_model,
            )
            langchain_tools.append(lc_tool)
        return langchain_tools

    async def disconnect(self):
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._session = None
            self._exit_stack = None


class StdioConnectionManager(MCPConnectionManager):
    """
    通过 stdio (命令行流) 启动并连接到本地或互联网上的 MCP Server (比如 npx 或 python 命令)
    """
    async def connect(self, command: str, args: list[str], env: dict = None):
        if self._session is not None:
            return

        self._exit_stack = AsyncExitStack()
        try:
            # 合并默认环境变量，防止找不到命令
            server_env = get_default_environment()
            if env:
                server_env.update(env)
                
            server_parameters = ServerParameters(
                command=command,
                args=args,
                env=server_env
            )
            streams = await self._exit_stack.enter_async_context(stdio_client(server_parameters))
            read_stream, write_stream = streams
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()
        except Exception as e:
            await self._exit_stack.aclose()
            self._session = None
            raise e
