# core/state_graph/node_utils.py
"""节点公共工具函数 — 消除跨节点的代码重复"""

from langchain_openai import ChatOpenAI
from core import config


def get_memory_window(state, window_size=10):
    """统一的滑窗记忆裁剪"""
    all_msgs = state.get("messages") or []  # 确保即使 key 存在但值为 None 也能回退到空列表
    return all_msgs[-window_size:] if len(all_msgs) > window_size else all_msgs


def create_llm(model=None, temperature=0.1):
    """统一的 LLM 工厂"""
    return ChatOpenAI(
        model=model or config.DEFAULT_MODEL,
        api_key=config.DASHSCOPE_API_KEY,
        base_url=config.OPENAI_API_BASE,
        temperature=temperature
    )


def merge_tools(local_tools, injected_tools):
    """统一的工具合并 + 去重，返回 (tools_list, tools_by_name_dict)"""
    all_tools = list(local_tools)
    existing = {t.name for t in all_tools}
    for t in (injected_tools or []):
        if t.name not in existing:
            all_tools.append(t)
    return all_tools, {t.name: t for t in all_tools}
