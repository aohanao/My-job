# core/state_graph/sim_pipeline.py
"""仿真流水线子图 — 包含 Extractor -> CriticParams -> Coder -> CriticCode -> ReviewBeforeExec(HITL) -> Executor -> CriticResult 闭环"""

from langgraph.graph import StateGraph, END
from functools import partial
from core.state_graph.state import SimPipelineState
from core.state_graph.nodes.extractor_node import extractor_node
from core.state_graph.nodes.coder_node import coder_node
from core.state_graph.nodes.executor_node import executor_node
from core.state_graph.nodes.critic_agent import critic_params_node, critic_code_node, critic_result_node
from core.state_graph.nodes.hitl_node import review_before_exec_node, route_after_hitl
from core.state_graph.routing import route_after_extractor, route_after_coder, route_after_executor


def build_sim_pipeline(tools=None):
    """构建仿真流水线子图

    分层智能体 + HITL 拓扑结构:
        Extractor → CriticParams → Coder → CriticCode → ReviewBeforeExec(HITL 确认) → Executor → CriticResult
             ↑            │                  │                   │ (is_confirmed=False: 挂起等待)            │
             └── retry ───┴──────── retry ───┴────────────────────────────────────────────────── retry ───────┘

    与主图通过重叠 State 字段自动透传数据。
    """
    workflow = StateGraph(SimPipelineState)

    # 注入工具到 Extractor
    extractor_with_tools = partial(extractor_node, tools=tools)

    # 注册核心执行节点
    workflow.add_node("Extractor", extractor_with_tools)
    workflow.add_node("CriticParams", critic_params_node)
    workflow.add_node("Coder", coder_node)
    workflow.add_node("CriticCode", critic_code_node)
    workflow.add_node("ReviewBeforeExec", review_before_exec_node)   # ← HITL 节点
    workflow.add_node("Executor", executor_node)
    workflow.add_node("CriticResult", critic_result_node)

    # 1. 设置入口
    workflow.set_entry_point("Extractor")

    # 2. Extractor → CriticParams
    workflow.add_edge("Extractor", "CriticParams")

    # 3. CriticParams 路由：参数不合格打回，合格进入 Coder
    workflow.add_conditional_edges("CriticParams", route_after_extractor, {
        "Coder": "Coder",
        "Extractor": "Extractor",
        "WaitHuman": END  # 追问挂起
    })

    # 4. Coder → CriticCode
    workflow.add_edge("Coder", "CriticCode")

    # 5. CriticCode 路由：代码不合格打回 Coder，合格进入 HITL 确认节点
    workflow.add_conditional_edges("CriticCode", route_after_coder, {
        "Retry": "Coder",
        "Execute": "ReviewBeforeExec"   # ← 代码通过后先过 HITL，再执行
    })

    # 6. HITL 路由：is_confirmed=True 进入 Executor，False 挂起等待用户确认
    workflow.add_conditional_edges("ReviewBeforeExec", route_after_hitl, {
        "Execute": "Executor",
        "WaitConfirm": END   # 挂起：等待外部更新 is_confirmed=True 后继续
    })

    # 7. Executor → CriticResult
    workflow.add_edge("Executor", "CriticResult")

    # 8. CriticResult 路由：报错折返自愈或结束
    workflow.add_conditional_edges("CriticResult", route_after_executor, {
        "ReExtract": "Extractor",
        "End": END
    })

    return workflow.compile()
