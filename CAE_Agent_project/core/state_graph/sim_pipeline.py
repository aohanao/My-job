# core/state_graph/sim_pipeline.py
"""仿真流水线子图 — 封装 Extractor → Coder → Executor 闭环"""

from langgraph.graph import StateGraph, END
from functools import partial
from core.state_graph.state import SimPipelineState
from core.state_graph.nodes.extractor_node import extractor_node
from core.state_graph.nodes.coder_node import coder_node
from core.state_graph.nodes.executor_node import executor_node
from core.state_graph.routing import route_after_extractor, route_after_coder, route_after_executor


def build_sim_pipeline(tools=None):
    """构建仿真流水线子图

    子图内部拓扑:
        Extractor(提取+校验) ──→ ReviewParams(人机确认) ──pass──→ Coder(生成+校验) ──pass──→ Executor
              ↑                      │
              └── retry ─────────────┘

    与主图通过重叠 State 字段自动透传数据。
    """
    workflow = StateGraph(SimPipelineState)

    # 注入工具到 Extractor
    extractor_with_tools = partial(extractor_node, tools=tools)

    # 注册节点
    workflow.add_node("Extractor", extractor_with_tools)
    workflow.add_node("Coder", coder_node)
    workflow.add_node("Executor", executor_node)

    # 1. 设置入口
    workflow.set_entry_point("Extractor")

    # 2. 路由：Extractor 自纠与挂起
    workflow.add_conditional_edges("Extractor", route_after_extractor, {
        "Coder": "Coder",
        "Extractor": "Extractor",
        "WaitHuman": END
    })

    # 3. 路由：Coder 代码自愈
    workflow.add_conditional_edges("Coder", route_after_coder, {
        "Retry": "Coder",
        "Execute": "Executor"
    })

    # 4. 路由：Executor 报错折返自愈
    workflow.add_conditional_edges("Executor", route_after_executor, {
        "ReExtract": "Extractor",
        "End": END
    })

    return workflow.compile()
