from langchain_core.messages import AIMessage
from core.state_graph.state import SimPipelineState
import json

def review_node(state: SimPipelineState):
    """参数评审节点：向用户展示提取结果并挂起流程"""
    print("\n[ReviewNode] 🔍 正在格式化参数摘要并准备挂起流程...")
    params = state.get("extracted_params", {})
    skill = state.get("selected_skill", "未知")
    
    # 构造摘要消息
    summary_md = f"### 📝 仿真参数检查 ({skill})\n"
    summary_md += "Agent 已根据您的描述自动提取并初始化了以下参数，请确认：\n\n"
    
    # 格式化展示参数
    if isinstance(params, dict):
        # 排除掉状态字段
        display_params = {k: v for k, v in params.items() if k not in ["status", "message"]}
        summary_md += f"```json\n{json.dumps(display_params, indent=2, ensure_ascii=False)}\n```\n"
    
    summary_md += "\n> [!TIP]\n> **确认无误后请点击下方的『确认参数』按钮**。如果需要修改，请随时在对话框中告诉我。"

    return {
        "messages": [AIMessage(content=summary_md)],
        "param_errors": "HITL_INTERRUPT" # 触发路由中的中断
    }
