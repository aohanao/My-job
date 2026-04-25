# mcp_server_entry.py
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from langsmith import traceable # 导入追踪装饰器

# 加载环境变量 (包括 LangSmith 的 API Key)
load_dotenv()

from retriever_service import HybridRetrieverService
from langchain_community.embeddings import DashScopeEmbeddings
from semantic_cache import global_cache
import config_data as config

# 这里的 print 随便写，完全没关系！
print("🚀 [MCP 模式] 正在初始化 RAG 工具中心 (已挂载追踪与语义缓存)...")

embedding = DashScopeEmbeddings(model=config.embedding_model)
retriever_service = HybridRetrieverService(embedding)

# 实例化 FastMCP
app = FastMCP("CAE-RAG-Center")

@app.tool()
@traceable(name="lookup_cae_knowledge")
def lookup_cae_knowledge(query: str, final_k: int = 3) -> str:
    """查询隧道与桥梁的工程规范、参数标准。"""
    print(f"📥 收到 Agent 请求: {query}")
    
    # [新增核心]: 先向长记忆大坝(Cache)抛出探针
    cached_result = global_cache.check_cache(query)
    if cached_result:
        return f"【基于过去长效记忆的直接召回结果：】\n{cached_result}"

    # Cache 没命中，才去查厚重的文件实体向量库
    print(f"🧩 未命中缓存，开始底层物理切片检索...")
    docs = retriever_service.search_and_rerank(query, initial_k=10, final_k=final_k)
    
    if not docs:
        return "未检索到相关的规范片段。"

    formatted = [f"来源: {d.metadata.get('source')}\n内容: {d.page_content}" for d in docs]
    final_answer = "\n\n---\n\n".join(formatted)
    
    # [新增核心]: 查都查出来了，花一点点时间把这个好结果塞入经验缓冲池
    global_cache.save_cache(query, final_answer)
    
    return final_answer

if __name__ == "__main__":
    # 🌟 关键：改用 sse 传输。它会自动基于 Starlette/FastAPI 创建一个 Web 服务
    # 默认会监听 http://0.0.0.0:8000
    app.run(transport="sse")