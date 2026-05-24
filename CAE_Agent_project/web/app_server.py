from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio
import os
import sys
import json
import time
from typing import Optional, List, Dict, Any

# 🚀 极其重要：挂载路径，确保能找到 core 包
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.append(_ROOT_DIR)

# 🚀 [核心修复 3]: 解决 Windows 下 Ctrl+C 卡死及异步兼容性
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from core.state_graph.builder import build_cae_graph
from integrations.mcp_client.mcp_manager import MCPConnectionManager, StdioConnectionManager
from core.eval_sdk import EvalPlatformCallback
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

app = FastAPI(title="CAE Multi-Agent Web Console", description="CAE 多智能体仿真平台控制台")

# 启用跨域 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局变量，作为 Single Source of Truth
agent_memory = MemorySaver()
mcp_manager = MCPConnectionManager()
tools_manager = StdioConnectionManager()
agent_app = None
mcp_connected = False
mcp_error = ""

class ResetRequest(BaseModel):
    session_id: str

@app.on_event("startup")
async def startup_event():
    global agent_app, mcp_connected, mcp_error
    all_tools = []
    print("[App] 🚀 开始连接外部 MCP 工具服务...")
    
    # 1. 尝试连接 RAG 服务器 (SSE)
    try:
        # 默认连接本地 RAG
        await mcp_manager.connect("http://127.0.0.1:8000/sse")
        rag_tools = await mcp_manager.get_tools()
        all_tools.extend(rag_tools)
        mcp_connected = True
        print(f"[App] ✅ 成功连接 RAG 知识库，加载了 {len(rag_tools)} 个知识检索工具")
    except Exception as e:
        mcp_connected = False
        mcp_error = str(e)
        print(f"[App] ❌ 连接 RAG 知识库失败: {e}")
        
    # 2. 尝试连接本地 Stdio 工具集
    try:
        python_exe = sys.executable
        tools_script = os.path.join(_ROOT_DIR, "integrations", "local_tools_server.py")
        await tools_manager.connect(python_exe, [tools_script])
        simple_tools = await tools_manager.get_tools()
        all_tools.extend(simple_tools)
        print(f"[App] ✅ 成功加载 {len(simple_tools)} 个本地 Stdio 测试工具: {[t.name for t in simple_tools]}")
    except Exception as e:
        print(f"[App] ⚠️ 加载本地测试工具失败: {e}")
        
    # 3. 构造 LangGraph 引擎
    agent_app = build_cae_graph(
        checkpointer=agent_memory, 
        tools=all_tools
    )
    print("[App] 🧠 CAE 智能体推演图已构建完成！")


# ==========================================
# 📊 HTTP REST APIs
# ==========================================

@app.get("/api/mcp_status")
async def get_mcp_status():
    return {
        "mcp_connected": mcp_connected,
        "mcp_error": mcp_error
    }

@app.get("/api/history")
async def get_history(session_id: str):
    if not agent_app:
        return []
    config = {"configurable": {"thread_id": session_id}}
    state = agent_app.get_state(config)
    
    messages = []
    consensus_params = {}
    last_script_path = ""
    current_intent = "待捕获"
    action_type = "休息中"
    
    if state and hasattr(state, "values") and state.values:
        chat_history = state.values.get("messages", [])
        consensus_params = state.values.get("consensus_params", {})
        last_script_path = state.values.get("script_path", "")
        current_intent = state.values.get("selected_skill", "未知")
        action_type = state.values.get("action_type", "待捕捉")
        
        # 序列化消息历史
        for msg in chat_history:
            if isinstance(msg, HumanMessage):
                messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                if msg.content:
                    # 检查是否有求解日志
                    has_log = "✅ 物理机 CAE 计算已完美收官！" in msg.content
                    log_content = ""
                    if has_log and last_script_path:
                        log_path = last_script_path.replace(".py", ".log")
                        if os.path.exists(log_path):
                            try:
                                with open(log_path, "r", encoding="utf-8") as f:
                                    log_content = f.read()
                            except:
                                pass
                    messages.append({
                        "role": "assistant",
                        "content": msg.content,
                        "has_log": has_log,
                        "log_content": log_content
                    })
    
    return {
        "messages": messages,
        "consensus_params": consensus_params,
        "current_intent": current_intent,
        "action_type": action_type,
        "last_script_path": last_script_path
    }

@app.post("/api/reset")
async def reset_session(req: ResetRequest):
    global agent_app
    if not agent_app:
        raise HTTPException(status_code=500, detail="Agent graph not initialized")
    
    config = {"configurable": {"thread_id": req.session_id}}
    agent_app.update_state(config, {
        "messages": [],
        "consensus_params": {},
        "script_path": "",
        "selected_skill": "未知",
        "action_type": "休息中"
    })
    return {"status": "success", "message": f"会话 {req.session_id} 已成功重置"}


# ==========================================
# 📡 WebSocket Real-time Chat
# ==========================================

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    print("[WS] 🔌 客户端已连接到仿真座舱 WebSocket")
    
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            action = payload.get("action")
            session_id = payload.get("session_id", "default-session")
            
            if action == "chat":
                user_message = payload.get("message", "")
                if not user_message:
                    continue
                
                # 开始执行流式推演
                await run_agent_stream(websocket, user_message, session_id)
                
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        print("[WS] 🔌 客户端已断开 WebSocket 连接")
    except Exception as e:
        print(f"[WS] ⚠️ 发生异常: {e}")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except:
            pass

async def run_agent_stream(websocket: WebSocket, user_input: str, session_id: str):
    """在 WebSocket 中执行智能体的实时流式推演"""
    if not agent_app:
        await websocket.send_json({"type": "error", "content": "Agent 引擎未初始化"})
        return
        
    thread_config = {"configurable": {"thread_id": session_id}}
    
    # 挂载零侵入可观测评估探针回调
    eval_api_url = os.environ.get("EVAL_API_URL", "http://127.0.0.1:8001")
    eval_callback = EvalPlatformCallback(
        server_url=eval_api_url,
        session_id=session_id
    )
    thread_config["callbacks"] = [eval_callback]

    initial_input = {
        "messages": [HumanMessage(content=user_input)], 
        "retry_count": 0, 
        "is_confirmed": False,
        "param_errors": None,
        "code_errors": None,
        "error_log": None,
        "extracted_params": {},
        "consensus_params": {},
        "action_type": None
    }
    
    # 发送开始信号
    await websocket.send_json({"type": "start"})
    
    try:
        async for chunk in agent_app.astream(initial_input, config=thread_config):
            for node_name, output in chunk.items():
                print(f"[WS] 🧬 观测到节点产出: node='{node_name}'")
                
                # 1. 实时通知前端当前的推演节点
                await websocket.send_json({"type": "status", "node": node_name})
                
                # 2. 如果产出了消息，实时向前端推送
                if isinstance(output, dict) and "messages" in output:
                    for msg in output["messages"]:
                        if isinstance(msg, AIMessage) and msg.content:
                            await websocket.send_json({
                                "type": "message",
                                "role": "assistant",
                                "content": msg.content
                            })
                
                # 3. 如果提取到了参数，实时向前端推送最新合并结果
                if isinstance(output, dict) and "consensus_params" in output:
                    new_params = output["consensus_params"]
                    if new_params:
                        state = agent_app.get_state(thread_config)
                        accumulated_params = state.values.get("consensus_params", {}) if state else {}
                        await websocket.send_json({
                            "type": "consensus_params",
                            "params": accumulated_params
                        })
                        
        # 4. 推演彻底结束，与图的最终真实状态进行一次硬同步
        state = agent_app.get_state(thread_config)
        if state and hasattr(state, "values") and state.values:
            consensus_params = state.values.get("consensus_params", {})
            last_script_path = state.values.get("script_path", "")
            current_intent = state.values.get("selected_skill", "未知")
            action_type = state.values.get("action_type", "待捕捉")
            
            # 读取求解日志
            log_content = ""
            has_log = False
            if last_script_path:
                log_path = last_script_path.replace(".py", ".log")
                if os.path.exists(log_path):
                    has_log = True
                    try:
                        with open(log_path, "r", encoding="utf-8") as f:
                            log_content = f.read()
                    except:
                        pass
                        
            await websocket.send_json({
                "type": "state_update",
                "params": consensus_params,
                "intent": current_intent,
                "action_type": action_type,
                "last_script_path": last_script_path,
                "has_log": has_log,
                "log_content": log_content
            })
            
        await websocket.send_json({"type": "done"})
        
    except Exception as e:
        print(f"[WS] ❌ 智能体推演阶段异常: {e}")
        import traceback
        traceback.print_exc()
        await websocket.send_json({"type": "error", "content": str(e)})


# ==========================================
# 📂 静态文件资源挂载
# ==========================================

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def read_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "CAE Agent Web Server is running. Place index.html in web/static/ to start chatbot UI."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_server:app", host="0.0.0.0", port=8501, reload=True)
