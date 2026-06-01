import asyncio
import os
import sys
from contextlib import AsyncExitStack
import mcp
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client, get_default_environment, StdioServerParameters as ServerParameters
from pydantic import create_model, Field, BaseModel
from langchain_core.tools import StructuredTool

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

    async def is_alive(self) -> bool:
        if self._session is None:
            return False
        try:
            # 尝试通过列出工具（限制超时 1.0 秒）来确认会话的心跳存活状态
            await asyncio.wait_for(self._session.list_tools(), timeout=1.0)
            return True
        except Exception:
            # 捕获到异常（如连接已关闭、拒绝服务等），进行资源清理并置空
            if self._exit_stack:
                try:
                    await self._exit_stack.aclose()
                except Exception:
                    pass
            self._session = None
            self._exit_stack = None
            return False

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


class UnifiedMCPManager:
    """
    统一 MCP 客户端管理器。
    负责一键式配置、启动并聚合所有的 MCP 连接与工具。
    """
    def __init__(self):
        self.managers = {}

    async def connect_all(self):
        # 1. 连接 RAG MCP (SSE)
        rag_alive = False
        if "rag_mcp" in self.managers:
            try:
                rag_alive = await self.managers["rag_mcp"].is_alive()
            except Exception:
                pass
                
        if not rag_alive:
            sse_manager = MCPConnectionManager()
            try:
                sse_url = os.environ.get("RAG_MCP_URL", "http://127.0.0.1:8000/sse")
                await sse_manager.connect(sse_url)
                self.managers["rag_mcp"] = sse_manager
                print(f"[UnifiedMCP] 成功连接 RAG MCP: {sse_url}")
            except Exception as e:
                print(f"[UnifiedMCP] 连接 RAG MCP 失败 (RAG 模块可能未启动): {e}")

        # 2. 连接本地 SimpleTools (Stdio)
        local_alive = False
        if "local_tools" in self.managers:
            try:
                local_alive = await self.managers["local_tools"].is_alive()
            except Exception:
                pass
                
        if not local_alive:
            stdio_manager = StdioConnectionManager()
            try:
                python_exe = sys.executable
                current_dir = os.path.dirname(os.path.abspath(__file__))
                possible_paths = [
                    os.path.join(current_dir, "..", "local_tools_server.py"),
                    os.path.join(current_dir, "local_tools_server.py"),
                    os.path.join(os.getcwd(), "integrations", "local_tools_server.py"),
                    os.path.join(os.getcwd(), "local_tools_server.py"),
                ]
                tools_script = next((p for p in possible_paths if os.path.exists(p)), None)
                if tools_script:
                    await stdio_manager.connect(python_exe, [tools_script])
                    self.managers["local_tools"] = stdio_manager
                    print(f"[UnifiedMCP] 成功连接本地工具服务器: {tools_script}")
                else:
                    print("[UnifiedMCP] 未找到 local_tools_server.py 路径，跳过连接")
            except Exception as e:
                print(f"[UnifiedMCP] 连接本地工具服务器失败: {e}")

        # 3. 连接 CAE 材料数据库 (Stdio)
        material_alive = False
        if "material_db" in self.managers:
            try:
                material_alive = await self.managers["material_db"].is_alive()
            except Exception:
                pass
                
        if not material_alive:
            material_manager = StdioConnectionManager()
            try:
                python_exe = sys.executable
                current_dir = os.path.dirname(os.path.abspath(__file__))
                possible_material_paths = [
                    os.path.join(current_dir, "server_entry.py"),
                    os.path.join(current_dir, "integrations", "mcp_client", "server_entry.py"),
                    os.path.join(os.getcwd(), "integrations", "mcp_client", "server_entry.py"),
                    os.path.join(os.getcwd(), "mcp_client", "server_entry.py"),
                ]
                material_script = next((p for p in possible_material_paths if os.path.exists(p)), None)
                if material_script:
                    await material_manager.connect(python_exe, [material_script])
                    self.managers["material_db"] = material_manager
                    print(f"[UnifiedMCP] 成功连接材料数据库服务器: {material_script}")
                else:
                    print("[UnifiedMCP] 未找到 server_entry.py 路径，跳过连接")
            except Exception as e:
                print(f"[UnifiedMCP] 连接材料数据库服务器失败: {e}")

    async def get_all_tools(self) -> list[StructuredTool]:
        all_tools = []
        for name, manager in self.managers.items():
            try:
                tools = await manager.get_tools()
                all_tools.extend(tools)
                print(f"[UnifiedMCP] 从 {name} 获取到 {len(tools)} 个工具")
            except Exception as e:
                print(f"[UnifiedMCP] 从 {name} 获取工具失败: {e}")
        return all_tools

    async def disconnect_all(self):
        for name, manager in list(self.managers.items()):
            try:
                await manager.disconnect()
                print(f"[UnifiedMCP] 已断开与 {name} 的连接")
            except BaseException as e:
                print(f"[UnifiedMCP] 断开 {name} 连接失败: {e}")
        self.managers.clear()


if __name__ == "__main__":
    async def main():
        print("=== 开始测试 UnifiedMCPManager ===")
        unified_manager = UnifiedMCPManager()
        
        print("[INFO] 正在建立所有工具连接...")
        await unified_manager.connect_all()
        
        try:
            tools = await unified_manager.get_all_tools()
            print(f"\n[INFO] 最终聚合发现 {len(tools)} 个工具:")
            for i, tool in enumerate(tools, 1):
                print(f"  {i}. {tool.name}")
                print(f"     描述: {tool.description}")
            
            # 测试调用 get_current_time 工具
            time_tool = next((t for t in tools if t.name == "get_current_time"), None)
            if time_tool:
                print("\n[TEST] 测试调用 'get_current_time' 工具...")
                res = await time_tool.ainvoke({"timezone": "Asia/Shanghai"})
                print(f"   调用结果: {res}")
                
            # 测试调用 lookup_material_db 工具（如果有的话）
            mat_tool = next((t for t in tools if t.name == "lookup_material_db"), None)
            if mat_tool:
                print("\n[TEST] 测试调用 'lookup_material_db' 工具...")
                res = await mat_tool.ainvoke({"query": "C30"})
                print(f"   调用结果: {res}")
                
        except Exception as e:
            print(f"[ERROR] 获取或测试工具时出错: {e}")
        finally:
            print("\n[INFO] 正在断开所有连接...")
            await unified_manager.disconnect_all()
            print("[INFO] 测试结束。")

    asyncio.run(main())

