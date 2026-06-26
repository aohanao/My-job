# core/state_graph/nodes/hitl_node.py
"""
人工介入确认节点 (Human-In-The-Loop Review Node)

设计原则：
  - 在 CAE 仿真脚本生成完毕（通过 CriticCode 校验）后、宿主机执行前介入
  - 向前端输出一条结构化的"待确认"通知消息，前端展示 "确认执行" 按钮
  - 该节点本身不挂起图，而是将 is_confirmed 设为 False；
    外层 WebSocket 路由检测到 HITL_PENDING 后暂停流式循环等待用户回复
  - 用户点击确认后，前端发送 action=confirm_sim，后端更新 is_confirmed=True 后继续执行
"""
import os
from langchain_core.messages import AIMessage
from core.state_graph.state import SimPipelineState


def review_before_exec_node(state: SimPipelineState):
    """HITL 节点：向前端发送确认请求消息，并通过 is_confirmed 标记控制流程挂起"""
    script_path = state.get("script_path", "")
    script_name = os.path.basename(script_path) if script_path else "未知脚本"
    consensus_params = state.get("consensus_params", {})
    selected_skill = state.get("selected_skill", "未知技能")

    # 格式化参数表格用于展示
    param_rows = "\n".join([f"  - **{k}**: `{v}`" for k, v in consensus_params.items()])
    if not param_rows:
        param_rows = "  - （无参数）"

    confirm_msg = (
        f"⚠️ **仿真执行确认请求 (HITL Review)**\n\n"
        f"系统已完成以下仿真脚本的生成与代码合规检查，即将提交宿主机 Abaqus 执行。\n\n"
        f"**请您确认以下内容无误后，点击「确认执行」按钮：**\n\n"
        f"| 项目 | 内容 |\n"
        f"|------|------|\n"
        f"| 仿真技能 | `{selected_skill}` |\n"
        f"| 生成脚本 | `{script_name}` |\n\n"
        f"**参数列表：**\n{param_rows}\n\n"
        f"> 💡 仿真一旦启动即无法中途终止。请确认所有参数正确无误后再执行。"
    )

    print(f"\n[HITL] 🔔 仿真前确认通知已发出，等待用户确认 (script: {script_name})")

    return {
        "messages": [AIMessage(content=confirm_msg)],
        "is_confirmed": False,  # 明确标记为等待确认
    }


def route_after_hitl(state: SimPipelineState):
    """HITL 节点后的路由：is_confirmed 为 True 则继续执行，否则挂起等待"""
    if state.get("is_confirmed", False):
        return "Execute"
    return "WaitConfirm"
