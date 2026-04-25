# core/state_graph/state.py
from typing import TypedDict, Dict, Any, Optional, Annotated, List
from langgraph.graph.message import add_messages


def merge_dicts(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """合并字典的 reducer，用于增量更新共识参数"""
    if not old: return new
    if not new: return old
    result = old.copy()
    result.update(new)
    return result


# ═══════════════════════════════════════════════════════════════
# 主图状态 — 仅保留全局共享的 7 个核心字段
# ═══════════════════════════════════════════════════════════════
class CAEAgentState(TypedDict):
    """CAE Agent 全局状态"""
    # 核心历史与记忆
    messages: Annotated[List[Any], add_messages]
    
    # 策略与意图
    selected_skill: str        # 当前选中的工程技能 (如: bullet_impact)
    action_type: str           # 当前动作类型 (chat/simulate)
    
    # 全局参数共识
    consensus_params: Annotated[Dict[str, Any], merge_dicts]

    # 可观测性
    trace_id: Optional[str]
    is_confirmed: bool  # 是否已通过人工确认

    # 仿真结果透传
    script_path: Optional[str]
    generated_code: Optional[str]
    result_dir: Optional[str]


# ═══════════════════════════════════════════════════════════════
# 仿真流水线子图状态 — 与主图重叠的字段 + 局部字段
# ═══════════════════════════════════════════════════════════════
class SimPipelineState(TypedDict):
    """仿真子图状态：Extractor → Coder → Executor"""
    # ─── 与主图重叠（自动透传） ───
    messages: Annotated[List[Any], add_messages]
    selected_skill: str
    consensus_params: Annotated[Dict[str, Any], merge_dicts]
    trace_id: Optional[str]
    is_confirmed: bool # 🌟 是否已通过人工确认

    # ─── 仿真流水线局部字段 ───
    extracted_params: Dict[str, Any]
    param_errors: Optional[str] 
    retry_count: int
    generated_code: Optional[str]
    script_path: Optional[str]
    code_errors: Optional[str]
    error_log: Optional[str]
    result_dir: Optional[str]
