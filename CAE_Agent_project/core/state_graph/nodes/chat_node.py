# core/state_graph/nodes/chat_node.py
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage
from langchain_core.tools import tool
from integrations.mcp_client.provider import get_material_lookup_tool
from core.state_graph.state import CAEAgentState
from core.state_graph.node_utils import get_memory_window, create_llm, merge_tools
from core import config
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
你有以下工具可用，必须严格按照适用场景选择，不得随意混用：

■ 工程专业工具（CAE 相关）：
  1. lookup_local_material_db：查询常见材料的基础力学参数（弹性模量、泊松比、密度等）
     示例：「V级围岩弹性模量」、「C30混凝土密度」
  2. lookup_cae_knowledge：查询工程规范、施工流程、设计标准等深层工程知识（RAG 知识库）
     示例：「钻爆法隧道施工流程」、「新奥法支护设计规范」
  3. record_consensus_params：用户确认了一个具体参数数值时，立即调用记录到共识池

■ 通用工具（与 CAE 无关）：
  4. get_current_time：用户询问当前时间/日期时调用，其他情况不调用
  5. simple_calculator：用户需要计算明确的数学表达式时调用
  6. get_mock_weather：用户询问某城市天气时调用

【工具选择决策树】
- 问题涉及 CAE/仿真/材料/工程 → 用 1、2 或 3
- 问题是时间/日期查询 → 用 4
- 问题是数学计算 → 用 5
- 问题是天气查询 → 用 6
- 如果工具返回了错误或空结果，不要重复调用同一工具，改为直接用已知知识作答

【当前已确认的共识参数池】
{consensus_params}

【对话风格】
- 专业、简洁，用工程师的语气
- 在回复结尾列出\"📋 待确认清单\"，提示用户还缺哪些参数
- 如果用户的问题超出以上所有工具范围，直接用文字回答，不要强行调用工具
"""


# 同一工具连续调用相同参数视为死循环，最多循环轮数
MAX_REACT_TURNS = 5


async def chat_node(state: CAEAgentState, tools=None):
    """咨询与专家指导节点（异步版本，支持 MCP 异步工具调用）"""
    node_start_time = time.time()

    memory_window = get_memory_window(state)
    current_consensus = state.get("consensus_params", {})

    print(f"\n[Chat] 💬 开始工程咨询...")

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        consensus_params=json.dumps(current_consensus, ensure_ascii=False, indent=2) if current_consensus else "（暂无）"
    )

    # 🌟 注入压缩后的早期上下文记忆，防止失忆
    short_term_memory = state.get("context_summary", "")
    if short_term_memory:
        system_prompt += f"\n\n【已被归档压缩的早期历史背景与参数约束】：\n{short_term_memory}"

    messages = [SystemMessage(content=system_prompt)] + list(memory_window)

    # 合并本地工具 + 外部注入的 MCP 工具（使用公共 merge_tools）
    all_tools, tools_by_name = merge_tools([_local_rag_tool, record_consensus_params], tools)

    llm_with_tools = llm.bind_tools(all_tools)
    consensus_updates = {}
    response = None

    # 如果有上下文预警，可以在这里动态干预 Prompt（降级机制）
    if state.get("context_warning"):
        warning_msg = SystemMessage(content="【系统底层警告】您的上下文记忆已超过预警线（40%），处理能力受限。请务必使用极简语言回复，并尽快引导用户结束当前话题或开启新对话。")
        messages.insert(1, warning_msg)

    # ── ReAct 循环：最多 MAX_REACT_TURNS 轮 ──
    for turn in range(MAX_REACT_TURNS):
        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as e:
            # LLM 调用本身出错，直接兜底返回
            print(f"[Chat] ❌ LLM 调用异常 (turn {turn+1}): {e}")
            response = AIMessage(content=f"抱歉，处理您的请求时遇到了问题：{e}\n请重新描述您的问题。")
            break

        messages.append(response)

        if not response.tool_calls:
            print(f"[Chat] ✅ 第 {turn+1} 轮推理完成，无更多工具调用")
            break

        print(f"[Chat] 🔧 第 {turn+1} 轮，触发 {len(response.tool_calls)} 个工具调用")

        # ── 达到最后一轮仍有 tool_calls，强制终止并兜底回复 ──
        if turn == MAX_REACT_TURNS - 1:
            print(f"[Chat] ⚠️ 已达到最大推理轮数 ({MAX_REACT_TURNS})，强制终止")
            response = AIMessage(content="非常抱歉，我在多轮尝试后仍无法给出准确结果。请尝试换一种方式提问，或直接提供具体参数值，我将帮您继续。")
            messages.append(response)
            break

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
                    tool_start_time = time.time()
                    tool_result = await tool_instance.ainvoke(tool_args)
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

    return_payload = {"messages": [final_response]}
    if consensus_updates:
        return_payload["consensus_params"] = consensus_updates
        print(f"[Chat] 🎯 本轮新增共识参数: {consensus_updates}")

    return return_payload
