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
你有以下工具可用，请根据问题的性质自行选择最合适的工具：

1. lookup_local_material_db（本地参数速查表）：
   - 适用场景：查询常见材料的基础力学参数（弹性模量、泊松比、密度、粘聚力等数值）
   - 特点：速度快、精确，但内容有限，仅包含常见围岩等级、混凝土标号、钢筋型号
   - 示例：「V级围岩弹性模量是多少」、「C30混凝土密度」

2. lookup_cae_knowledge（RAG 知识库深度检索）：
   - 适用场景：查询工程规范、施工流程、设计标准、技术文档等深层工程知识
   - 特点：内容丰富，基于用户上传的工程文档进行语义检索
   - 示例：「钻爆法隧道施工流程」、「新奥法支护设计规范」、「围岩分级标准依据」
   - 注意：只有当 MCP 知识库在线时此工具才可用

3. record_consensus_params（参数共识记录）：
   - 每当确认了一个具体数值（无论来自哪个工具、用户口述、还是系统推荐），必须立即调用此工具记录
   - 记录后参数会实时显示在用户的"实时参数共识板"上

【智能选择策略】
- 用户问具体数值 → 优先 lookup_local_material_db
- 用户问流程/规范/原理 → 优先 lookup_cae_knowledge
- 如果本地速查表没有找到需要的信息，可以再尝试 lookup_cae_knowledge
- 当用户说"使用默认参数"时，先用 lookup_local_material_db 查标准值

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
                if tool_name == "lookup_local_material_db":
                    print(f"[Chat] 📦 调用本地速查表: {tool_name}({tool_args})")
                elif tool_name == "lookup_cae_knowledge":
                    print(f"[Chat] 🌐 调用 MCP-RAG 知识库: {tool_name}({tool_args})")
                else:
                    print(f"[Chat] 🔌 调用工具: {tool_name}({tool_args})")
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
