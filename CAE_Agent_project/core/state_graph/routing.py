# core/state_graph/routing.py
"""状态图路由决策引擎 — 所有条件边逻辑的唯一归属地"""

from core import config


def route_after_planner(state):
    """Planner 之后的三分叉路由

    Returns:
        'End'         — action_type 为 error（不支持的意图）
        'Chat'        — action_type 为 chat（咨询阶段）
        'SimPipeline' — action_type 为 simulate（启动仿真）
    """
    action = state.get("action_type")
    if action == "error":
        return "End"
    if action == "chat":
        return "Chat"
    return "SimPipeline"


def route_after_extractor(state):
    """Extractor 之后的路由 — 支持 Reflexion 自愈与人机交互"""
    errors = state.get("param_errors")
    if errors == "HIT_INTERRUPT":
        return "WaitHuman"
    if errors and state.get("retry_count", 0) < 3:
        return "Extractor"
    return "Coder"


def route_after_coder(state):
    """Coder（含代码验证）之后的路由

    Returns:
        'Retry'   — 代码校验失败，需要重新生成
        'Execute' — 校验通过，进入执行阶段
    """
    if state.get("code_errors"):
        return "Retry"
    return "Execute"


def route_after_executor(state):
    """Executor 之后的路由 — 仿真报错折返至 Extractor"""
    if state.get("error_log") and state.get("retry_count", 0) < 3:
        return "ReExtract"
    return "End"
