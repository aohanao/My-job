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

# 🚀 [优化] 统一使用项目内部探针
from core.tracer import tracer as logger

# 🌟 重构后的导入路径
from core.state_graph.builder import build_cae_graph
from integrations.mcp_client.mcp_manager import RAGConnectionManager
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

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
    print("🤖 CAE 多智能体仿真平台 (重构架构版)")
    print("="*55)

    mcp_manager = RAGConnectionManager()
    try:
        await mcp_manager.connect("http://127.0.0.1:8000/sse")
        rag_tools = await mcp_manager.get_all_rag_tools()
    except Exception as e:
        print(f"❌ MCP 连接失败: {e}")
        return

    session_name = input("📌 会话名称: ").strip() or "default-session"
    thread_config = {"configurable": {"thread_id": session_name}}

    if HAS_SQLITE:
        async with AsyncSqliteSaver.from_conn_string("checkpoints.sqlite") as memory:
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
            user_input = input(f"\n👤 [{session_name}] > ")
            if user_input.strip().lower() in ['/exit', 'quit', 'exit']: break
            if not user_input.strip(): continue

            initial_input = {"messages": [HumanMessage(content=user_input)]}

            # 🚀 [新增] 初始化追踪状态
            current_trace_id = None
            st = {} # 临时存储当前处理中的 Span 信息
            if logger:
                current_trace_id = logger.start_trace(session_id=session_name, user_query=user_input)

            try:
                async for chunk in app.astream(initial_input, config=thread_config):
                    for node_name, output in chunk.items():
                        print(f"⚙️ [{node_name}] 处理中...")
                        
                        # 🚀 [安全性修复] 增加对 output 的 None 检查
                        if output is None:
                            continue
                        
                        # 🚀 [新增] 专门捕获 RAG 工具调用并记入 Span
                        if logger and current_trace_id and isinstance(output, dict) and "messages" in output:
                            messages_to_check = output.get("messages")
                            if messages_to_check:
                                for msg in messages_to_check:
                                    # (1) 识别工具调用意图 (AIMessage with tool_calls)
                                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                                        for tool_call in msg.tool_calls:
                                            if tool_call.get("name") == "lookup_cae_knowledge":
                                                # 创建 Span 记录输入
                                                st["active_tool_span"] = {
                                                    "trace_id": current_trace_id,
                                                    "span_name": "lookup_cae_knowledge",
                                                    "input": tool_call.get("args"),
                                                    "start_time": time.time()
                                                }

                                    # (2) 识别工具返回内容 (ToolMessage)
                                    from langchain_core.messages import ToolMessage
                                    if isinstance(msg, ToolMessage) and st.get("active_tool_span"):
                                        active = st["active_tool_span"]
                                        # 抓取到了真正的检索结果！
                                        logger.log_span(
                                            trace_id=active["trace_id"],
                                            span_type="TOOL",
                                            span_name=active["span_name"],
                                            start_time=active["start_time"],
                                            end_time=time.time(),
                                            input_data=active["input"],
                                            output_data=msg.content, # 这里的 content 就是 RAG 返回的文本块
                                            status="SUCCESS"
                                        )
                                        st["active_tool_span"] = None # 处理完清空

                final_state = await app.aget_state(thread_config)
                last_msg = final_state.values.get("messages")[-1]
                
                if isinstance(last_msg, AIMessage):
                    print(f"\n🤖 Bot: {last_msg.content}")
                    # 🚀 [新增] 提取 Token 消耗并结束 Trace
                    tokens = logger.get_token_usage(last_msg)
                    if logger and current_trace_id:
                        logger.end_trace(
                            trace_id=current_trace_id, 
                            final_response=last_msg.content,
                            total_tokens=tokens
                        )

                if not HAS_SQLITE:
                    save_history_json(session_name, final_state.values.get("messages", []))
            except Exception as e:
                print(f"❌ 运行错误: {e}")
                if logger and current_trace_id:
                    logger.end_trace(trace_id=current_trace_id, final_response=f"Error: {str(e)}", success_flag=False)
    finally:
        await mcp_manager.disconnect()

if __name__ == "__main__":
    asyncio.run(main())