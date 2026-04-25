"""
MCP Server 启动入口。
"""
import sys
import os

# 确保能找到同目录下的 server 模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from server import lookup_material_db

def main():
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as e:
        raise RuntimeError("请安装 mcp: pip install mcp") from e

    app = FastMCP("cae-material-db")
    # 注意：FastMCP 的 tool() 装饰器需要接收函数对象
    app.tool()(lookup_material_db.func if hasattr(lookup_material_db, "func") else lookup_material_db)
    app.run(transport="stdio")

if __name__ == "__main__":
    main()
