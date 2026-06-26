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

from core.state_graph.cae_agent import build_cae_agent
from integrations.mcp_client.mcp_manager import UnifiedMCPManager
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
agent_memory_manager = None
agent_memory = None
mcp_manager = UnifiedMCPManager()
agent_app = None
mcp_connected = False
mcp_error = ""

class ResetRequest(BaseModel):
    session_id: str

class HitlConfirmRequest(BaseModel):
    session_id: str

@app.on_event("startup")
async def startup_event():
    global agent_app, agent_memory, agent_memory_manager, mcp_connected, mcp_error
    print("[App] 开始连接外部 MCP 工具服务...")
    
    await mcp_manager.connect_all()
    all_tools = []
    try:
        all_tools = await mcp_manager.get_all_tools()
        # 仅当 RAG MCP (SSE) 连接成功时，RAG 知识库才显示为在线状态
        mcp_connected = "rag_mcp" in mcp_manager.managers and mcp_manager.managers["rag_mcp"]._session is not None
        print(f"[App] 成功聚合加载了 {len(all_tools)} 个 MCP 工具: {[t.name for t in all_tools]}")
    except Exception as e:
        mcp_connected = False
        mcp_error = str(e)
        print(f"[App] 获取工具列表失败: {e}")
        
    # 初始化 SQLite 持久化检查点存储
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        os.makedirs(".data", exist_ok=True)
        agent_memory_manager = AsyncSqliteSaver.from_conn_string(".data/checkpoints.sqlite")
        agent_memory = await agent_memory_manager.__aenter__()
        print("[App] 成功加载 SQLite 异步持久化检查点存储 (.data/checkpoints.sqlite)")
    except Exception as e:
        from langgraph.checkpoint.memory import MemorySaver
        agent_memory = MemorySaver()
        print(f"[App] 加载 SQLite 存储失败，已降级为内存存储 MemorySaver: {e}")
        
    agent_app = build_cae_agent(
        checkpointer=agent_memory, 
        tools=all_tools
    )
    print("[App] CAE 智能体推演图已构建完成！")
    
    # 打印可访问的网址信息
    import socket
    local_ip = "127.0.0.1"
    try:
        # 纯本地获取局域网 IPv4，无需联网或连接外部服务器 (如 8.8.8.8)
        hostname = socket.gethostname()
        ip_addresses = socket.gethostbyname_ex(hostname)[2]
        for ip in ip_addresses:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                local_ip = ip
                break
    except Exception:
        pass
            
    print("=" * 60)
    print(f"[App] CAE 增强智能体 Web 控制座舱已成功启动！")
    print(f"[App] 本地访问地址: http://localhost:8501")
    print(f"[App] 本地访问地址: http://127.0.0.1:8501")
    if local_ip != "127.0.0.1":
        print(f"[App] 局域网访问地址: http://{local_ip}:8501")
    print("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    global agent_memory_manager
    print("[App] 正在关闭并清理所有 MCP 连接...")
    await mcp_manager.disconnect_all()
    if agent_memory_manager:
        try:
            await agent_memory_manager.__aexit__(None, None, None)
            print("[App] 已安全关闭 SQLite 异步持久化存储连接。")
        except Exception as e:
            print(f"[App] 关闭 SQLite 存储连接时发生异常: {e}")
    print("[App] 所有连接已释放。")


# ==========================================
# 📊 HTTP REST APIs
# ==========================================

@app.get("/api/mcp_status")
async def get_mcp_status():
    global mcp_connected, agent_app, mcp_error
    
    # 检查当前 RAG 连接状态是否存活 (支持动态断开感知)
    rag_active = False
    if "rag_mcp" in mcp_manager.managers:
        try:
            rag_active = await mcp_manager.managers["rag_mcp"].is_alive()
        except:
            pass
            
    if not rag_active:
        # 如果未存活，尝试动态重连
        try:
            await mcp_manager.connect_all()
            new_rag_active = False
            if "rag_mcp" in mcp_manager.managers:
                new_rag_active = await mcp_manager.managers["rag_mcp"].is_alive()
                
            if new_rag_active:
                # 重新获取全部工具并动态重构智能体推演图 (加载 RAG)
                all_tools = await mcp_manager.get_all_tools()
                agent_app = build_cae_graph(
                    checkpointer=agent_memory, 
                    tools=all_tools
                )
                mcp_connected = True
                mcp_error = ""
                print(f"[App] 动态连接 RAG MCP 成功！已重新构建智能体推演图，当前聚合工具: {[t.name for t in all_tools]}")
            else:
                # 重连失败，如果之前是连接状态，说明刚刚被关闭了，需要热重构图以移出失效的 RAG 工具
                if mcp_connected:
                    all_tools = await mcp_manager.get_all_tools()
                    agent_app = build_cae_graph(
                        checkpointer=agent_memory, 
                        tools=all_tools
                    )
                    mcp_connected = False
                    print(f"[App] 检测到 RAG MCP 已关闭！已重新热构建图（移除 RAG 工具），当前聚合工具: {[t.name for t in all_tools]}")
        except Exception as e:
            mcp_error = str(e)
            if mcp_connected:
                # 捕获异常且原先为连接状态，进行图重构防错
                try:
                    all_tools = await mcp_manager.get_all_tools()
                    agent_app = build_cae_graph(
                        checkpointer=agent_memory, 
                        tools=all_tools
                    )
                except:
                    pass
                mcp_connected = False
    else:
        # 如果依然存活，确保全局状态 mcp_connected 正确设为 True
        mcp_connected = True
            
    return {
        "mcp_connected": mcp_connected,
        "mcp_error": mcp_error
    }

@app.get("/api/history")
async def get_history(session_id: str):
    if not agent_app:
        return []
    session_id = session_id.strip() if session_id else "default"
    if not session_id:
        session_id = "default"
    config = {"configurable": {"thread_id": session_id}}
    state = await agent_app.aget_state(config)
    
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
    
    session_id = req.session_id.strip() if req.session_id else "default"
    if not session_id:
        session_id = "default"
    config = {"configurable": {"thread_id": session_id}}
    await agent_app.aupdate_state(config, {
        "messages": [],
        "consensus_params": {},
        "script_path": "",
        "selected_skill": "未知",
        "action_type": "休息中"
    })
    return {"status": "success", "message": f"会话 {req.session_id} 已成功重置"}


@app.post("/api/hitl/confirm")
async def hitl_confirm(req: HitlConfirmRequest):
    """🌟 HITL REST 接口：用户确认仿真参数，更新 is_confirmed=True 使工作流继续执行"""
    global agent_app
    if not agent_app:
        raise HTTPException(status_code=500, detail="Agent graph not initialized")
    
    session_id = req.session_id.strip() if req.session_id else "default"
    if not session_id:
        session_id = "default"
    config = {"configurable": {"thread_id": session_id}}
    
    # 将 is_confirmed 更新为 True，下次图继续执行时将从 ReviewBeforeExec 节点通过
    await agent_app.aupdate_state(config, {"is_confirmed": True})
    print(f"[HITL] ✅ 用户已通过 REST API 确认仿真 (session: {session_id})")
    return {"status": "confirmed", "message": "仿真确认成功，工作流将从上次挂起位置继续执行"}


class HarvestSkillRequest(BaseModel):
    script_content: str
    skill_id: str
    skill_name: str
    description: str


@app.post("/api/harvest_skill")
async def api_harvest_skill(req: HarvestSkillRequest):
    """
    🌟 TDD-QA 技能自动沉淀接口：用户提交运行成功的仿真脚本，智能体自动将其参数化、编写测试用例并保存为新 Skill。
    """
    from core.skill_harvester import harvest_new_skill
    
    # 清洗输入
    skill_id = req.skill_id.strip()
    skill_name = req.skill_name.strip()
    description = req.description.strip()
    
    if not skill_id or not skill_name:
        raise HTTPException(status_code=400, detail="skill_id 和 skill_name 不能为空。")
        
    try:
        res = harvest_new_skill(
            script_content=req.script_content,
            skill_id=skill_id,
            skill_name=skill_name,
            description=description
        )
        if res["status"] == "success":
            return {"status": "success", "message": res["message"]}
        else:
            raise HTTPException(status_code=400, detail=res["message"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            session_id = payload.get("session_id", "default").strip()
            if not session_id:
                session_id = "default"
            
            if action == "chat":
                user_message = payload.get("message", "")
                if not user_message:
                    continue
                
                # 开始执行流式推演
                await run_agent_stream(websocket, user_message, session_id)

            elif action == "confirm_sim":
                # 🌟 HITL 确认：用户点击确认执行按钮，恢复挂起的仿真工作流
                await handle_hitl_confirm(websocket, session_id)
                
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
                        state = await agent_app.aget_state(thread_config)
                        accumulated_params = state.values.get("consensus_params", {}) if state else {}
                        await websocket.send_json({
                            "type": "consensus_params",
                            "params": accumulated_params
                        })
                        
        # 4. 推演彻底结束，与图的最终真实状态进行一次硬同步
        state = await agent_app.aget_state(thread_config)
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

            # 🌟 HITL 挂起检测：脚本已生成但 is_confirmed=False 表示等待用户确认
            is_confirmed = state.values.get("is_confirmed", True)
            if not is_confirmed and last_script_path and os.path.exists(last_script_path):
                print(f"[WS] 🔔 检测到 HITL 挂起状态，通知前端展示确认按钮 (session: {session_id})")
                await websocket.send_json({
                    "type": "hitl_waiting",
                    "script_path": last_script_path,
                    "params": consensus_params,
                    "message": "⚠️ 仿真脚本已就绪，等待您确认执行。"
                })
                return  # 不发送 done，保持 WebSocket 连接等待用户确认

        await websocket.send_json({"type": "done"})
        
    except Exception as e:
        print(f"[WS] ❌ 智能体推演阶段异常: {e}")
        import traceback
        traceback.print_exc()
        await websocket.send_json({"type": "error", "content": str(e)})


# ==========================================
# 🔔 HITL 确认恢复逻辑
# ==========================================

async def handle_hitl_confirm(websocket: WebSocket, session_id: str):
    """HITL 确认处理：更新 is_confirmed=True，并恢复图的流式执行"""
    if not agent_app:
        await websocket.send_json({"type": "error", "content": "Agent 引擎未初始化"})
        return

    thread_config = {"configurable": {"thread_id": session_id}}

    # 1. 将 is_confirmed 写入检查点，令 ReviewBeforeExec 的路由判断为 True
    await agent_app.aupdate_state(thread_config, {"is_confirmed": True})
    print(f"[HITL] ✅ 用户已通过 WebSocket 确认仿真 (session: {session_id})")

    await websocket.send_json({"type": "status", "node": "HITL_Confirmed"})
    await websocket.send_json({
        "type": "message",
        "role": "assistant",
        "content": "✅ **仿真确认已收到！** 正在启动宿主机 Abaqus 执行引擎，请稍候..."
    })

    # 2. 以 None 输入恢复图（LangGraph 中输入 None 表示从当前检查点继续执行）
    eval_api_url = os.environ.get("EVAL_API_URL", "http://127.0.0.1:8001")
    from core.eval_sdk import EvalPlatformCallback
    eval_callback = EvalPlatformCallback(server_url=eval_api_url, session_id=session_id)
    thread_config["callbacks"] = [eval_callback]

    try:
        async for chunk in agent_app.astream(None, config=thread_config):
            for node_name, output in chunk.items():
                print(f"[WS/HITL] 🧬 恢复执行节点: node='{node_name}'")
                await websocket.send_json({"type": "status", "node": node_name})

                if isinstance(output, dict) and "messages" in output:
                    from langchain_core.messages import AIMessage
                    for msg in output["messages"]:
                        if isinstance(msg, AIMessage) and msg.content:
                            await websocket.send_json({
                                "type": "message",
                                "role": "assistant",
                                "content": msg.content
                            })

        await websocket.send_json({"type": "done"})

    except Exception as e:
        print(f"[WS/HITL] ❌ HITL 恢复执行异常: {e}")
        import traceback
        traceback.print_exc()
        await websocket.send_json({"type": "error", "content": str(e)})

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def read_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(
            index_path,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )
    return {"message": "CAE Agent Web Server is running. Place index.html in web/static/ to start chatbot UI."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_server:app", host="0.0.0.0", port=8501, reload=True)
