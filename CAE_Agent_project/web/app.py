import streamlit as st
import asyncio
import os
import sys
import json
import sqlite3
import nest_asyncio
import time
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
# 🚀 极其重要：由于 path_utils 就在 core 包内，
# 所以在入口文件中必须先【手动】挂载路径，才能让后续的 from core... 正常工作。
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.append(_ROOT_DIR)

nest_asyncio.apply()

from core.state_graph.builder import build_cae_graph
from integrations.mcp_client.mcp_manager import RAGConnectionManager
from core.tracer import tracer
from langgraph.checkpoint.memory import MemorySaver

# 页面配置
st.set_page_config(page_title="CAE 多智能体仿真平台", page_icon="🤖", layout="wide")

# 🎨 注入自定义样式
def local_css(file_name):
    if os.path.exists(file_name):
        with open(file_name, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

style_path = os.path.join(os.path.dirname(__file__), "style.css")
local_css(style_path)

async def init_mcp_and_graph(session_id: str):
    """初始化 MCP 连接并构建 LangGraph"""
    if "mcp_manager" not in st.session_state:
        st.session_state.mcp_manager = RAGConnectionManager()
        try:
            # 默认连接本地 RAG 服务
            await st.session_state.mcp_manager.connect("http://127.0.0.1:8000/sse")
            st.session_state.rag_tools = await st.session_state.mcp_manager.get_all_rag_tools()
            st.session_state.mcp_connected = True
        except Exception as e:
            st.session_state.mcp_connected = False
            st.session_state.mcp_error = str(e)
            st.session_state.rag_tools = []
    
    if "agent_app" not in st.session_state:
        memory = MemorySaver()
        st.session_state.agent_app = build_cae_graph(checkpointer=memory, tools=st.session_state.rag_tools)

# 强制基于 SSOT (Single Source of Truth) 更新所有状态
def sync_state_from_graph(session_id: str):
    if "agent_app" not in st.session_state:
        return
    app = st.session_state.agent_app
    config = {"configurable": {"thread_id": session_id}}
    
    # 彻底使用同步版 get_state 防止 asyncio 与 Streamlit 的重载死锁
    state = app.get_state(config)
    
    if state and hasattr(state, "values") and state.values:
        st.session_state.chat_history = state.values.get("messages", [])
        st.session_state.consensus_params = state.values.get("consensus_params", {})
        st.session_state.last_script_path = state.values.get("script_path", "")
        st.session_state.current_intent = state.values.get("selected_skill", "未知")
        st.session_state.action_type = state.values.get("action_type", "待捕捉")
    else:
        st.session_state.chat_history = []
        st.session_state.consensus_params = {}
        st.session_state.last_script_path = ""
        st.session_state.current_intent = "待捕获"
        st.session_state.action_type = "休息中"

async def run_agent_step(user_input: str, session_id: str):
    """执行一次 Agent 图的流式推导"""
    print(f"[App] 🚀 开始执行步骤: user_input='{user_input}', session_id='{session_id}'")
    app = st.session_state.agent_app
    thread_config = {"configurable": {"thread_id": session_id}}
    
    trace_id = tracer.start_trace(session_id, user_query=user_input)
    initial_input = {
        "messages": [HumanMessage(content=user_input)], 
        "retry_count": 0, 
        "trace_id": trace_id,
        "is_confirmed": False,
        "param_errors": None,
        "code_errors": None,
        "error_log": None,
        "extracted_params": {},
        "consensus_params": {},
        "action_type": None
    }
    status_placeholder = st.empty()
    active_spans = {} 

    # 先在界面显示用户当前输入，给用户即时反馈，但不污染真实状态数组
    user_msg = HumanMessage(content=user_input)

    chat_container = st.container()
    processed_msg_hashes = set()
    
    def render_msg(msg):
        msg_hash = hash(f"{msg.type}_{msg.content}")
        if msg_hash in processed_msg_hashes: return
        processed_msg_hashes.add(msg_hash)
        
        with chat_container:
            if isinstance(msg, HumanMessage):
                with st.chat_message("user"): st.write(msg.content)
            elif isinstance(msg, AIMessage):
                if msg.content:
                    with st.chat_message("assistant"):
                        st.write(msg.content)
                        if "✅ 物理机 CAE 计算已完美收官！" in msg.content and st.session_state.get("last_script_path"):
                            log_path = st.session_state.last_script_path.replace(".py", ".log")
                            if os.path.exists(log_path):
                                with st.expander("📄 查看宿主机 Abaqus 完整求解日志"):
                                    try:
                                        with open(log_path, "r", encoding="utf-8") as f:
                                            st.code(f.read(), language="text")
                                    except: pass

    # 🌟 内部函数：刷新侧边栏实时看板
    def sync_sidebar_params(params):
        if not params: return
        with params_placeholder.container():
            st.markdown("### 📊 实时参数看板")
            icon_map = {"geometry": "📐", "material": "🧱", "physics": "⚡", "mesh": "🕸️", "tunnel": "🚇", "soil": "🕳️", "fluid": "🌊"}
            for key, value in params.items():
                display_icon = icon_map.get(key.lower(), "🔹")
                if isinstance(value, dict):
                    st.markdown(f"**{display_icon} {key}**")
                    for sub_k, sub_v in value.items():
                        st.markdown(f"""<div class="consensus-card"><div class="consensus-label">{sub_k}</div><div class="consensus-value">{sub_v}</div></div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div class="consensus-card"><div class="consensus-label">{display_icon} {key}</div><div class="consensus-value">{value}</div></div>""", unsafe_allow_html=True)

    # 静默预加载历史记忆的哈希，防止在流式追加时重影
    for m in st.session_state.chat_history: 
        processed_msg_hashes.add(hash(f"{m.type}_{m.content}"))
        
    # 渲染本地新提问，待流式传输完毕后，用图状态全局覆盖
    render_msg(user_msg)

    try:
        async for chunk in app.astream(initial_input, config=thread_config):
            for node_name, output in chunk.items():
                print(f"[App] 🧬 观测到节点产出: node='{node_name}', keys={list(output.keys()) if isinstance(output, dict) else 'non-dict'}")
                status_placeholder.markdown(f"""<div class="status-container"><span style="color: #00D1FF; font-weight: 600;">⚡ 引擎推演中:</span> <span style="font-family: 'JetBrains Mono';">{node_name}</span></div>""", unsafe_allow_html=True)
                
                if isinstance(output, dict) and "messages" in output:
                    for msg in output["messages"]:
                        # 仅负责将流式中生成的新消息实时显示
                        render_msg(msg)

                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                if tc["name"] in ("lookup_cae_knowledge", "lookup_local_material_db"):
                                    active_spans["rag"] = {
                                        "name": tc["name"],
                                        "input": tc["args"],
                                        "start": time.time()
                                    }
                        
                        if isinstance(msg, ToolMessage) and active_spans.get("rag"):
                            rag_span = active_spans["rag"]
                            tracer.log_span(
                                trace_id=trace_id, span_type="TOOL", 
                                span_name=rag_span["name"],
                                start_time=rag_span["start"],
                                input_data=rag_span["input"],
                                output_data=msg.content, 
                                status="SUCCESS"
                            )
                            active_spans["rag"] = None

                if isinstance(output, dict) and "consensus_params" in output:
                    new_params = output["consensus_params"]
                    if new_params:
                        st.session_state.consensus_params.update(new_params)
                        # 在侧边栏占位符中实时同步参数
                        sync_sidebar_params(st.session_state.consensus_params)
                        
                tracer.log_span(trace_id=trace_id, span_type="NODE", span_name=node_name,
                                start_time=time.time(), input_data={"node": node_name},
                                output_data=str(output)[:100], status="SUCCESS")

                if node_name == "ReviewParams":
                    st.session_state.waiting_for_approval = True
                        
        status_placeholder.empty()
        
        # 🚀 【核心修复】推演结束后，强制与图节点真实状态对齐，杜绝错位！
        sync_state_from_graph(session_id)
        
        final_response_str = "Agent 推演结束"
        total_tokens = 0
        if st.session_state.chat_history:
             ai_msgs = [m for m in st.session_state.chat_history if isinstance(m, AIMessage)]
             if ai_msgs:
                 last_ai = ai_msgs[-1]
                 final_response_str = last_ai.content
                 total_tokens = tracer.get_token_usage(last_ai)
        
        tracer.end_trace(trace_id, final_response=final_response_str, success_flag=True, total_tokens=total_tokens)
        
        st.session_state.is_running = False
        st.rerun()

    except Exception as e:
        st.session_state.is_running = False
        status_placeholder.error(f"运行发生错误: {e}")
        import traceback
        traceback.print_exc()

if "session_id" not in st.session_state:
    st.session_state.session_id = "default-session"
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "consensus_params" not in st.session_state:
    st.session_state.consensus_params = {}
if "temp_thread_id" not in st.session_state:
    st.session_state.temp_thread_id = "default-session"

def get_or_create_event_loop():
    """安全获取或创建事件循环，解决 Streamlit 重载冲突"""
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop

# 初始连接
loop = get_or_create_event_loop()
try:
    loop.run_until_complete(init_mcp_and_graph(st.session_state.session_id))
except Exception as e:
    st.error(f"初始化基础连接失败: {e}")

# ID 变更事件回调函数：纯同步！不涉及 async 阻塞，彻底避免卡死
def on_thread_id_change():
    new_id = st.session_state.input_thread_id
    if new_id and new_id != st.session_state.session_id:
        st.session_state.session_id = new_id
        # 读取对应老历史！
        sync_state_from_graph(new_id)

with st.sidebar:
    st.markdown('<h1 class="sidebar-title">⚙️ 仿真座舱</h1>', unsafe_allow_html=True)
    # 使用 callback 处理切换，避免渲染循环锁死
    st.text_input("📝 映射会话 ID", value=st.session_state.session_id, key="input_thread_id", on_change=on_thread_id_change)
    
    col1, col2 = st.columns(2)
    with col1:
        status_color = "#10B981" if st.session_state.get("mcp_connected") else "#EF4444"
        st.markdown(f"""
            <div class="consensus-card" style="text-align: center; padding: 10px;">
                <div class="consensus-label">知识库</div>
                <div style="color: {status_color}; font-weight: 600;">● {'在线' if st.session_state.get("mcp_connected") else '离线'}</div>
            </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
            <div class="consensus-card" style="text-align: center; padding: 10px;">
                <div class="consensus-label">线程 ID</div>
                <div class="consensus-value" style="font-size: 0.75rem; word-break: break-all;">{st.session_state.session_id[:12]}...</div>
            </div>
        """, unsafe_allow_html=True)

    # 🚀 定义看板占位符
    params_placeholder = st.empty()
    
    with params_placeholder.container():
        if st.session_state.get("consensus_params"):
            st.markdown("### 📊 实时参数看板")
            icon_map = {"geometry": "📐", "material": "🧱", "physics": "⚡", "mesh": "🕸️", "tunnel": "🚇", "soil": "🕳️", "fluid": "🌊"}
            for key, value in st.session_state.consensus_params.items():
                display_icon = icon_map.get(key.lower(), "🔹")
                if isinstance(value, dict):
                    st.markdown(f"**{display_icon} {key}**")
                    for sub_k, sub_v in value.items():
                        st.markdown(f"""<div class="consensus-card"><div class="consensus-label">{sub_k}</div><div class="consensus-value">{sub_v}</div></div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div class="consensus-card"><div class="consensus-label">{display_icon} {key}</div><div class="consensus-value">{value}</div></div>""", unsafe_allow_html=True)
        else:
            st.info("💡 系统正在监听并提取关键物理参数...")

    st.markdown("### 🧠 深度意图引擎")
    intent = st.session_state.get('current_intent', '待捕获')
    action = st.session_state.get('action_type', '休息中')
    st.markdown(f"""<div class="consensus-card" style="border-left: 3px solid #00D1FF;"><div class="consensus-label">技能方向</div><div class="consensus-value">{intent}</div><div class="consensus-label" style="margin-top: 10px;">驱动模式</div><div class="consensus-value">{action}</div></div>""", unsafe_allow_html=True)

    st.markdown("---")
    if st.button("🔄 重置当前仿真会话", use_container_width=True, type="primary"):
        st.session_state.chat_history = []
        st.session_state.consensus_params = {}
        st.session_state.is_running = False
        st.session_state.current_intent = "待捕获"
        st.session_state.action_type = "休息中"
        if "agent_app" in st.session_state: del st.session_state.agent_app 
        st.rerun()

st.markdown("""<div style="margin-bottom: 25px;"><h1 class="sidebar-title">🤖 CAE 增强智能体 <span style="font-size: 0.8rem; vertical-align: middle; color: #94A3B8; font-weight: 300;">v2.0 Professional</span></h1><p style="color: var(--text-secondary); margin-top: -10px;">基于核心 Core 引擎与标准化技能集，为精密仿真而生。</p></div>""", unsafe_allow_html=True)

if st.session_state.chat_history:
    for msg in st.session_state.chat_history:
        if isinstance(msg, HumanMessage): 
            with st.chat_message("user"): st.write(msg.content)
        elif isinstance(msg, AIMessage):
            if msg.content:
                with st.chat_message("assistant"):
                    st.write(msg.content)
                    if "✅ 物理机 CAE 计算已完美收官！" in msg.content and st.session_state.get("last_script_path"):
                        log_path = st.session_state.last_script_path.replace(".py", ".log")
                        if os.path.exists(log_path):
                            with st.expander("📄 查看宿主机 Abaqus 完整求解日志"):
                                try:
                                    with open(log_path, "r", encoding="utf-8") as f: st.code(f.read(), language="text")
                                except: pass

if prompt := st.chat_input("输入工程描述..."):
    st.session_state.is_running = True
    try:
        loop = get_or_create_event_loop()
        loop.run_until_complete(run_agent_step(prompt, st.session_state.session_id))
    except Exception as e: st.error(f"推演失败: {e}")
    finally: st.session_state.is_running = False
