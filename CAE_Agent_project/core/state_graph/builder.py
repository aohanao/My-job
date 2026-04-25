# core/state_graph/builder.py
"""CAE Agent 主图构建器 — 优化后仅 4 个顶层节点"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from functools import partial

from core.state_graph.state import CAEAgentState
from core.state_graph.routing import route_after_planner
from core.state_graph.sim_pipeline import build_sim_pipeline
from core.memory.short_term_compressor import compressor_node
from core.state_graph.nodes.planner_node import planner_node
from core.state_graph.nodes.chat_node import chat_node


def build_cae_graph(checkpointer=None, tools=None):
    """构建 CAE Agent 主状态图

    优化后的架构（4 个顶层节点 + 1 个仿真子图）：

        Compressor → Planner → Chat        (聊天咨询)
                             → SimPipeline  (仿真闭环子图)
                             → END          (不支持的意图)
    """
    workflow = StateGraph(CAEAgentState)

    # 🌟 注入工具到需要 MCP 的节点
    planner_with_tools = partial(planner_node, tools=tools)
    chat_with_tools = partial(chat_node, tools=tools)
    sim_pipeline = build_sim_pipeline(tools=tools)

    # 注册节点
    workflow.add_node("Compressor", compressor_node)
    workflow.add_node("Planner", planner_with_tools)
    workflow.add_node("Chat", chat_with_tools)
    workflow.add_node("SimPipeline", sim_pipeline)

    # 流式记忆拦截 → 意图识别
    workflow.set_entry_point("Compressor")
    workflow.add_edge("Compressor", "Planner")

    # 路由：根据 action_type 分流（逻辑集中在 routing.py）
    workflow.add_conditional_edges("Planner", route_after_planner, {
        "Chat": "Chat",
        "SimPipeline": "SimPipeline",
        "End": END,
    })

    # Chat 和 SimPipeline 结束后回到 END 等待下次输入
    workflow.add_edge("Chat", END)
    workflow.add_edge("SimPipeline", END)

    if checkpointer is None:
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)
