from langchain_core.messages import AIMessage
import os
import requests
from core.state_graph.state import SimPipelineState
from core import config
from core.memory.long_term_experience import get_experience_manager

# 本地开发用 localhost；Docker 环境中通过环境变量 CAE_BRIDGE_URL 改为 host.docker.internal
CAE_BRIDGE_URL = os.getenv("CAE_BRIDGE_URL", "http://host.docker.internal:5050/run_cae")

def executor_node(state: SimPipelineState):
    """仿真执行节点"""
    try:
        script_path = state.get("script_path")
        
        if not script_path or not os.path.exists(script_path):
            cwd = os.getcwd()
            try:
                # 检查目录是否存在
                parent_dir = os.path.dirname(script_path) if script_path else "Unknown"
                dir_exists = os.path.exists(parent_dir)
                dir_files = os.listdir(parent_dir) if dir_exists else []
            except Exception as le:
                dir_files = [f"Error listing dir: {le}"]
                
            msg = f"Executor 找不到脚本文件！路径='{script_path}'，CWD='{cwd}'，目录内容='{dir_files}'"
            print(f"[Executor] ⚠️ 错误: {msg}")
            return {"error_log": msg}

        print(f"\n[Executor] 🚀 准备点火！正在通过 HTTP 调用呼叫宿主机 Abaqus...")
        script_name = os.path.basename(script_path)
        
        # 🚀 [复原并增强] 强制优先尝试本地 Bridge
        urls_to_try = [
            "http://127.0.0.1:5050/run_cae",
            "http://localhost:5050/run_cae",
            "http://host.docker.internal:5050/run_cae"
        ]
        
        last_error = ""
        result_data = None
        for url in urls_to_try:
            try:
                # 使用较短的 connect timeout (2s)，防止在无效域名上挂死
                print(f"[Executor] 📡 正在尝试呼叫 Bridge 终端: {url} ...")
                response = requests.post(url, json={"script_name": script_name}, timeout=(2, 360))
                response.raise_for_status()
                result_data = response.json()
                print(f"[Executor] 🔗 连接成功: {url}")
                break 
            except Exception as e:
                last_error = str(e)
                print(f"[Executor] ⚠️ 线路 {url} 不通，切换下一条...")
                continue
        
        if result_data is None:
            error_msg = f"Connection Error: {last_error}"
            print(f"[Executor] ❌ 仿真执行失败: {error_msg}")
            return {"error_log": error_msg}

        if result_data.get("status") == "error":
            error_msg = result_data.get("message", "未知错误")
            detail = result_data.get("detail", "无详细日志")
            print(f"[Executor] ❌ 仿真执行失败: {error_msg}")
            return {"error_log": f"{error_msg}: {detail}"}
                
        print(f"[Executor] ✅ 仿真执行接口返回成功，流转至 Critic 智能体评估结果...")
        return {
            "error_log": None,
            "result_dir": os.path.dirname(script_path)
        }
    except Exception as e:
        print(f"\n[Executor] 💥 发生致命错误: {e}")
        import traceback
        traceback.print_exc()
        raise e
