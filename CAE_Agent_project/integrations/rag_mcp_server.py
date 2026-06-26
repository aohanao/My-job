"""
integrations/rag_mcp_server.py
— CAE 知识库 RAG MCP Server（Streamable HTTP 传输）

将 RAG 向量检索系统封装为标准 MCP Server，对外暴露 /mcp 端点。
Agent 侧通过 streamablehttp_client 连接，实现异步双向通信。

启动命令：
    python integrations/rag_mcp_server.py
    # 或指定端口
    RAG_MCP_PORT=8001 python integrations/rag_mcp_server.py

环境变量：
    RAG_MCP_PORT      监听端口，默认 8000
    RAG_MCP_HOST      监听地址，默认 127.0.0.1
    CHROMA_PATH       ChromaDB 持久化目录，默认 .data/chroma
    RAG_EMBED_MODEL   嵌入模型名称，默认 text-embedding-3-small
"""
import os
import sys
import json

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP

# ─────────────────────────────────────────────
# 初始化 FastMCP Server
# ─────────────────────────────────────────────
mcp = FastMCP(
    "cae-rag-knowledge",
    instructions=(
        "CAE 工程知识库检索服务。包含隧道工程规范、"
        "显式动力学仿真指南、材料手册等专业文档。"
        "通过语义向量检索返回最相关的知识片段。"
    )
)


# ─────────────────────────────────────────────
# 懒加载 RAG 检索器（避免启动时长过长）
# ─────────────────────────────────────────────
_retriever = None

def _get_retriever():
    """懒加载 ChromaDB 向量检索器"""
    global _retriever
    if _retriever is not None:
        return _retriever

    try:
        from langchain_chroma import Chroma
        from langchain_openai import OpenAIEmbeddings

        chroma_path = os.environ.get("CHROMA_PATH", os.path.join(_PROJECT_ROOT, ".data", "chroma"))
        embed_model = os.environ.get("RAG_EMBED_MODEL", "text-embedding-3-small")

        embeddings = OpenAIEmbeddings(model=embed_model)
        vectorstore = Chroma(
            persist_directory=chroma_path,
            embedding_function=embeddings,
            collection_name="cae_knowledge"
        )
        _retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
        print(f"[RAG MCP] ✅ 向量库已就绪: {chroma_path}")
    except Exception as e:
        print(f"[RAG MCP] ⚠️ 向量库加载失败，将使用 Mock 响应: {e}")
        _retriever = None

    return _retriever


# ─────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────

@mcp.tool()
def lookup_cae_knowledge(query: str) -> str:
    """
    从 CAE 工程知识库中检索与查询最相关的专业知识片段。

    覆盖领域：
    - 隧道工程规范（围岩分级、开挖工法、支护设计标准）
    - 显式动力学仿真（弹体冲击、爆炸载荷）
    - 建筑结构规范（混凝土、钢筋、荷载组合）
    - 材料力学手册（弹性模量、泊松比、屈服强度）

    适用场景：
    - 用户询问工程规范、设计标准、施工规程
    - 参数提取时需要查阅行业手册默认值
    - 不适用于实时天气、时间等非专业知识

    示例查询：
    - "V级围岩超前支护规范"
    - "C30混凝土弹性模量标准值"
    - "子弹冲击仿真step_time推荐值"
    """
    retriever = _get_retriever()

    if retriever is None:
        # Mock 模式：向量库未就绪时返回内置知识片段
        mock_kb = {
            "围岩": (
                "【规范】GB 50086-2015：V级围岩（极软岩或破碎带），"
                "必须采用超前支护（小导管注浆或管棚），严禁全断面开挖，"
                "应采用台阶法或CRD工法，初期支护应在开挖后4h内完成喷射混凝土。"
            ),
            "混凝土": (
                "【材料手册】C30混凝土：弹性模量 Ec=3.0×10⁴ MPa，"
                "轴心抗压强度标准值 fck=20.1 MPa，泊松比 ν=0.2，"
                "密度 ρ=2400 kg/m³（2.4×10⁻⁹ T/mm³ in mm-MPa-s体系）。"
            ),
            "子弹": (
                "【仿真指南】高速冲击仿真推荐参数：step_time 取 0.005s~0.02s，"
                "子弹速度 100~1000 m/s 时建议开启沙漏控制（HGEN=2）；"
                "钢板厚度 < 10mm 时需加密网格，单元尺寸建议 ≤ 1mm。"
            ),
            "钢筋": (
                "【材料手册】HPB300钢筋：弹性模量 Es=2.1×10⁵ MPa，"
                "屈服强度 fy=300 MPa，密度 ρ=7850 kg/m³（7.85×10⁻⁹ T/mm³），"
                "泊松比 ν=0.3，适用于一般构造配筋。"
            ),
        }
        # 简单关键词匹配
        results = []
        query_lower = query.lower()
        for keyword, content in mock_kb.items():
            if keyword in query_lower or keyword in query:
                results.append(content)

        if results:
            return "\n\n---\n\n".join(results)
        return (
            f"知识库中未找到与「{query}」直接相关的条目。"
            "建议参考国标规范 GB 50086、GB 50010，或提供更具体的查询词。"
        )

    # 真实 RAG 检索
    try:
        docs = retriever.invoke(query)
        if not docs:
            return f"知识库中未找到与「{query}」相关的文档片段。"
        
        chunks = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "未知来源")
            chunks.append(f"[片段 {i}｜来源: {source}]\n{doc.page_content.strip()}")
        return "\n\n---\n\n".join(chunks)
    except Exception as e:
        return f"检索过程中发生错误: {e}"


@mcp.tool()
def list_knowledge_domains() -> str:
    """
    列出当前 CAE 知识库所覆盖的工程领域和文档类型。
    用于帮助 Agent 了解知识库边界，避免超范围查询。
    """
    domains = {
        "tunnel_engineering": {
            "name": "隧道工程",
            "documents": ["GB 50086-2015 岩土锚杆与喷射混凝土支护规范",
                          "JTG D70-2004 公路隧道设计规范", "围岩分级手册"],
        },
        "dynamic_simulation": {
            "name": "显式动力学仿真",
            "documents": ["LS-DYNA 用户手册", "子弹冲击仿真参数指南", "爆炸载荷计算规程"],
        },
        "materials": {
            "name": "材料力学手册",
            "documents": ["GB 50010-2010 混凝土结构设计规范", "钢材力学性能数据库"],
        },
    }
    return json.dumps(domains, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# 启动入口
# ─────────────────────────────────────────────

if __name__ == "__main__":
    host = os.environ.get("RAG_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("RAG_MCP_PORT", "8000"))

    print(f"[RAG MCP Server] 🚀 启动 CAE 知识库 MCP Server")
    print(f"[RAG MCP Server] 📡 传输协议: Streamable HTTP (官方标准)")
    print(f"[RAG MCP Server] 🔗 MCP Endpoint: http://{host}:{port}/mcp")
    print(f"[RAG MCP Server] 客户端连接示例:")
    print(f"    from mcp.client.streamable_http import streamablehttp_client")
    print(f"    async with streamablehttp_client('http://{host}:{port}/mcp') as (r, w, _):")
    print(f"        ...")

    # Streamable HTTP 传输模式（官方推荐，替代 SSE）
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        path="/mcp",        # 官方规范端点路径
    )
