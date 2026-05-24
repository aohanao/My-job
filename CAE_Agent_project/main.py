# main.py
import asyncio
import uuid
import os
import sys
import sqlite3
import json
import time

# 🚀 手动挂载路径，确保能找到 core 和 integrations
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _ROOT_DIR not in sys.path:
    sys.path.append(_ROOT_DIR)

# 🚀 [优化] 引入零侵入式探针 SDK
from core.eval_sdk import EvalPlatformCallback

# 🌟 重构后的导入路径
from core.state_graph.builder import build_cae_graph
from integrations.mcp_client.mcp_manager import UnifiedMCPManager
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

try:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    HAS_SQLITE = True
except ImportError:
    from langgraph.checkpoint.memory import MemorySaver
    HAS_SQLITE = False

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

def save_history_json(session_name, messages):
    path = os.path.join(SESSIONS_DIR, f"{session_name}.json")
    serializable_msgs = []
    for m in messages:
        m_dict = {"type": m.__class__.__name__, "content": m.content}
        if hasattr(m, "tool_calls"): m_dict["tool_calls"] = m.tool_calls
        serializable_msgs.append(m_dict)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable_msgs, f, ensure_ascii=False, indent=2)

def load_history_json(session_name):
    path = os.path.join(SESSIONS_DIR, f"{session_name}.json")
    if not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    msgs = []
    for d in data:
        if d["type"] == "HumanMessage": msgs.append(HumanMessage(content=d["content"]))
        elif d["type"] == "AIMessage": msgs.append(AIMessage(content=d["content"]))
        elif d["type"] == "SystemMessage": msgs.append(SystemMessage(content=d["content"]))
    return msgs

async def main():
    print("="*55)
    print("[Agent] CAE 多智能体仿真平台 (重构架构版)")
    print("="*55)

    mcp_manager = UnifiedMCPManager()
    rag_tools = []
    
    try:
        await mcp_manager.connect_all()
        rag_tools = await mcp_manager.get_all_tools()
        print(f"[OK] 成功加载并聚合了 {len(rag_tools)} 个 MCP 工具: {[t.name for t in rag_tools]}")
    except Exception as e:
        print(f"[ERROR] 初始化 MCP 服务聚合器失败: {e}")

    session_name = input("[ID] 会话名称: ").strip() or "default-session"
    thread_config = {"configurable": {"thread_id": session_name}}

    if HAS_SQLITE:
        async with AsyncSqliteSaver.from_conn_string(".data/checkpoints.sqlite") as memory:
            await run_agent_loop(memory, rag_tools, thread_config, session_name, mcp_manager)
    else:
        memory = MemorySaver()
        await run_agent_loop(memory, rag_tools, thread_config, session_name, mcp_manager)

async def run_agent_loop(memory, rag_tools, thread_config, session_name, mcp_manager):
    app = build_cae_graph(checkpointer=memory, tools=rag_tools)
    
    if not HAS_SQLITE:
        history = load_history_json(session_name)
        if history:
            app.update_state(thread_config, {"messages": history})

    try:
        while True:
            user_input = input(f"\n[User] [{session_name}] > ")
            if user_input.strip().lower() in ['/exit', 'quit', 'exit']: break
            if not user_input.strip(): continue

            # 🚀 [重构] 使用 EvalPlatformCallback 实现真正的零侵入监控
            eval_callback = EvalPlatformCallback(
                server_url=os.environ.get("EVAL_API_URL", "http://127.0.0.1:8001"),
                session_id=session_name
            )
            run_config = thread_config.copy()
            run_config["callbacks"] = [eval_callback]

            initial_input = {
                "messages": [HumanMessage(content=user_input)]
            }

            try:
                async for chunk in app.astream(initial_input, config=thread_config):
                    for node_name, output in chunk.items():
                        print(f"[Run] [{node_name}] 处理中...")
                        
                        # 🚀 [安全性修复] 增加对 output 的 None 检查
                        if output is None:
                            continue
                        
                        # 由于使用了零侵入探针，无需手动捕捉 tool_calls 和 log_span

                final_state = await app.aget_state(thread_config)
                last_msg = final_state.values.get("messages")[-1]
                
                if isinstance(last_msg, AIMessage):
                    print(f"\n[Bot]: {last_msg.content}")

                if not HAS_SQLITE:
                    save_history_json(session_name, final_state.values.get("messages", []))
            except Exception as e:
                print(f"[ERROR] 运行错误: {e}")
    finally:
        await mcp_manager.disconnect_all()

if __name__ == "__main__":
    asyncio.run(main())