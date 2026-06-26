# core/state_graph/cae_agent.py
"""CAE Agent 顶层规划智能体 (Orchestrator Agent)"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from functools import partial

from core.state_graph.state import CAEAgentState
from core.state_graph.routing import route_after_planner_agent
from core.state_graph.sim_pipeline import build_sim_pipeline
from core.memory.short_term_compressor import compressor_node
from core.state_graph.nodes.planner_agent import planner_agent


def build_cae_agent(checkpointer=None, tools=None):
    """构建 CAE Agent 顶层规划与对话协调智能体

    分层多智能体拓扑结构：
        Compressor → PlannerAgent (意图规划与对话智能体) 
                        ➔ SimPipeline (仿真自愈执行智能体)
                        ➔ END         (聊天对话或不支持分支)
    """
    workflow = StateGraph(CAEAgentState)

    # 🌟 注入工具到 PlannerAgent 节点
    planner_agent_with_tools = partial(planner_agent, tools=tools)
    sim_pipeline = build_sim_pipeline(tools=tools)

    # 注册节点
    workflow.add_node("Compressor", compressor_node)
    workflow.add_node("PlannerAgent", planner_agent_with_tools)
    workflow.add_node("SimPipeline", sim_pipeline)

    # 流式记忆拦截 → 意图识别与咨询对话统一主控
    workflow.set_entry_point("Compressor")
    workflow.add_edge("Compressor", "PlannerAgent")

    # 路由：决定是进入仿真执行还是结束当前咨询轮次
    workflow.add_conditional_edges("PlannerAgent", route_after_planner_agent, {
        "SimPipeline": "SimPipeline",
        "End": END,
    })

    # SimPipeline 结束后回到 END 等待下次输入
    workflow.add_edge("SimPipeline", END)

    if checkpointer is None:
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)
