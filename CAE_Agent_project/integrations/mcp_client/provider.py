import os
from langchain_core.tools import tool
from integrations.mcp_client.server import lookup_local_material_db
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class ToolProvider:
    def get_material_tool(self):
        raise NotImplementedError

class LocalToolProvider(ToolProvider):
    def get_material_tool(self):
        return lookup_local_material_db

MCP_SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "server_entry.py")

class MCPClientToolProvider(ToolProvider):
    def get_material_tool(self):
        server_params = StdioServerParameters(
            command="python",
            args=[MCP_SERVER_SCRIPT],
        )
        @tool
        async def lookup_material_db_mcp(query: str) -> str:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "lookup_material_db", 
                        arguments={"query": query}
                    )
                    return result.content[0].text
        return lookup_material_db_mcp

def get_material_lookup_tool():
    backend = os.getenv("TOOL_BACKEND", "local").strip().lower()
    if backend == "mcp":
        return MCPClientToolProvider().get_material_tool()
    return LocalToolProvider().get_material_tool()
