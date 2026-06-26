# core/state_graph/nodes/planner_agent.py
"""PlannerAgent 智能体节点 — 组合意图识别与咨询对话统一入口"""

from core.state_graph.state import CAEAgentState
from core.state_graph.nodes.planner_node import planner_node
from core.state_graph.nodes.chat_node import chat_node


async def planner_agent(state: CAEAgentState, tools=None):
    """PlannerAgent 智能体节点

    1. 执行意图识别 (planner_node)
    2. 如果为仿真意图，则设置状态并直接返回，交由底层 SimPipeline 仿真智能体执行
    3. 如果为咨询对话意图，则在节点内直接运行 ReAct 咨询对话循环 (chat_node) 并返回回复
    """
    # 1. 运行意图识别
    planner_res = planner_node(state, tools=tools)

    # 2. 如果是意图不支持导致的报错
    if planner_res.get("action_type") == "error":
        return planner_res

    # 3. 如果是确认启动仿真，直接返回（随后路由至 SimPipeline）
    if planner_res.get("action_type") == "simulate":
        return planner_res

    # 4. 如果是咨询对话 (chat)，在 PlannerAgent 内部直接执行 chat 逻辑
    # 构造包含最新已识别技能的 state 传递给 chat_node
    updated_state = {
        **state,
        "selected_skill": planner_res.get("selected_skill", "unsupported"),
        "action_type": "chat"
    }

    chat_res = await chat_node(updated_state, tools=tools)

    # 合并意图分类与对话生成的结果
    merged_res = {
        "selected_skill": planner_res.get("selected_skill"),
        "action_type": "chat",
        **chat_res
    }
    return merged_res
