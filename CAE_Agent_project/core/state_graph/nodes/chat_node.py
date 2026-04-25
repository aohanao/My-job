# core/state_graph/nodes/chat_node.py
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage
from langchain_core.tools import tool
from integrations.mcp_client.provider import get_material_lookup_tool
from core.state_graph.state import CAEAgentState
from core.state_graph.node_utils import get_memory_window, create_llm, merge_tools
from core import config
from core.tracer import tracer
import json
import time

# 初始化工具（local 模式下同步 OK，MCP 模式下由 builder 注入异步工具）
_local_rag_tool = get_material_lookup_tool()

@tool
def record_consensus_params(key: str, value: str) -> str:
    """
    将用户已确认的仿真参数记录到共识池中。
    无论参数来自用户口述还是数据库查询，只要确认，都必须立即调用此工具。
    参数说明:
        key: 参数名称，如 "elastic_modulus", "rock_grade", "tunnel_diameter"
        value: 参数值，字符串格式
    """
    return f"✅ 参数已记录: {key} = {value}"

# 使用公共 LLM 工厂
llm = create_llm(model=config.CHAT_MODEL, temperature=0.3)

SYSTEM_PROMPT_TEMPLATE = """你是一位专业的 CAE（计算机辅助工程）仿真顾问，专注于隧道开挖支护与显式碰撞仿真领域。

【你的工作模式】
你现在处于"前期咨询"阶段。你的任务是与用户进行工程对话，帮助他们确定仿真所需的全部参数。
用户还没有发出"开始仿真"的指令，所以你不会直接启动仿真。

【工具使用规范 — 这是最重要的规则】
你有两个工具，在以下情况下【必须】使用：

1. lookup_cae_knowledge：
   - 只要用户提到任何材料名称、围岩等级、混凝土标号、钢筋型号等，你必须立即查询！
   - 特别注意：当用户说"使用默认参数"或"按推荐来"时，你应首先调用此工具查询相关等级的推荐标准值（如 V 级围岩的推荐弹性模量等）。
   - 查询完毕后，将数据库返回的数值如实告知用户，并说明"已根据技能库规范为您加载默认参数"。

2. record_consensus_params：
   - 每当确认了一个具体数值（无论来自数据库、用户口述、还是系统默认推荐码），必须立即调用此工具记录。
   - 记录后，这些参数会实时显示在用户的"实时参数共识板"上，增加系统透明度。

【当前已确认的共识参数池】
{consensus_params}

【对话风格】
- 专业、简洁，用工程师的语气
- 在回复结尾列出"📋 待确认清单"，提示用户还缺哪些参数
- 如果用户的问题超出 CAE 范围，婉转引导回工程话题
"""


async def chat_node(state: CAEAgentState, tools=None):
    """咨询与专家指导节点（异步版本，支持 MCP 异步工具调用）"""
    trace_id = state.get("trace_id")
    node_start_time = time.time()

    memory_window = get_memory_window(state)
    current_consensus = state.get("consensus_params", {})

    print(f"\n[Chat] 💬 开始工程咨询...")

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        consensus_params=json.dumps(current_consensus, ensure_ascii=False, indent=2) if current_consensus else "（暂无）"
    )
    messages = [SystemMessage(content=system_prompt)] + list(memory_window)

    # 合并本地工具 + 外部注入的 MCP 工具（使用公共 merge_tools）
    all_tools, tools_by_name = merge_tools([_local_rag_tool, record_consensus_params], tools)

    llm_with_tools = llm.bind_tools(all_tools)
    consensus_updates = {}
    response = None

    # ReAct 循环：最多 5 轮工具调用，避免死循环
    for turn in range(5):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            print(f"[Chat] ✅ 第 {turn+1} 轮推理完成，无更多工具调用")
            break

        print(f"[Chat] 🔧 第 {turn+1} 轮，触发 {len(response.tool_calls)} 个工具调用")

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_result = ""

            if tool_name == "record_consensus_params":
                key = tool_args.get("key", "")
                value = tool_args.get("value", "")
                if key and value:
                    consensus_updates[key] = value
                tool_result = f"✅ 已记录: {key} = {value}"
                print(f"[Chat] 📝 共识参数: {key} = {value}")

            elif tool_name in tools_by_name:
                print(f"[Chat] 🔌 调用知识库: {tool_name}({tool_args})")
                tool_instance = tools_by_name[tool_name]
                try:
                    tool_result = await tool_instance.ainvoke(tool_args)

                    # 🌟 埋点：记录 RAG 调用
                    if trace_id:
                        tracer.log_span(
                            trace_id=trace_id,
                            span_type="TOOL",
                            span_name=tool_name,
                            start_time=time.time(),
                            input_data=tool_args,
                            output_data=str(tool_result)[:500]
                        )
                except Exception as e:
                    tool_result = f"工具调用失败: {e}"
                    print(f"[Chat] ❌ 工具调用异常: {e}")
            else:
                tool_result = f"错误：工具 {tool_name} 不存在"

            messages.append(ToolMessage(
                tool_call_id=tool_call["id"],
                name=tool_name,
                content=str(tool_result)
            ))

    final_response = messages[-1]

    # 🌟 埋点：记录节点整体执行
    if trace_id:
        tracer.log_span(
            trace_id=trace_id,
            span_type="NODE",
            span_name="chat_node",
            start_time=node_start_time,
            input_data={"turns": len(state.get("messages", []))},
            output_data=final_response.content if hasattr(final_response, "content") else str(final_response)
        )

    return_payload = {"messages": [final_response]}
    if consensus_updates:
        return_payload["consensus_params"] = consensus_updates
        print(f"[Chat] 🎯 本轮新增共识参数: {consensus_updates}")

    return return_payload
