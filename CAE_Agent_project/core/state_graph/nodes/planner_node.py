# core/state_graph/nodes/planner_node.py
from langchain_core.messages import SystemMessage, AIMessage
from core.tracer import tracer
import time
from core.state_graph.state import CAEAgentState
from core.state_graph.node_utils import get_memory_window, create_llm
from core import config

# 使用公共 LLM 工厂
llm = create_llm(model=config.PLANNER_MODEL, temperature=0.1)

def planner_node(state: CAEAgentState, tools=None):
    """意图识别节点"""
    # 使用公共滑窗工具
    memory_window = get_memory_window(state)

    # 获取前面世代通过 RemoveMessage 砍掉的历史遗留记忆
    short_term_memory = state.get("context_summary", "")
    short_term_injection = ""
    if short_term_memory:
        short_term_injection = f"\n【早期记忆脉络提醒】：\n以下是很久以前被系统归档压缩的聊天记录与参数要求：\n{short_term_memory}\n（请在分析本次意图时以此为重要铺垫）\n"

    # 获取当前用户的最新输入（用于打印日志）
    query = memory_window[-1].content if memory_window else "空输入"
    print(f"\n[Planner] 正在调用大模型分析任务意图: {query}")

    from core.memory.long_term_experience import get_experience_manager

    exp_manager = get_experience_manager()
    historical_exp = exp_manager.recall_similar(query, k=1)

    exp_injection = ""
    if historical_exp:
        print("[Planner] ✨ 潜意识唤醒：发现该工程过去曾有成功运行经验...")
        exp_injection = f"\n【跨项目全局历史经验唤醒】\n系统回忆起之前在处理类似这句需求时，有过这样一次完美的仿真全链路经验：\n{historical_exp}\n这仅仅是参考，用来帮助您在与用户聊天（chat模式）时，如有必要可以推荐这些历史上已成功的经验参数给当前用户参考。"

    system_prompt = f"""
    你是一个资深的 CAE 仿真平台总指挥官。
    你需要判断用户的意图，将用户的需求分类到支持的技能库中。
    参考之前的对话历史来判断当前的真实意图。
    {short_term_injection}
    
    目前系统仅支持以下两种仿真类型：
    1. bullet_impact: 子弹冲击钢板相关的显式动力学仿真。
    2. tunnel_support: 隧道开挖与支护（如围岩等级、支护厚度等）相关的仿真。
    如果超出范围，则 intent 为 'unsupported'。意图如果没有明显倾向可以填 'unsupported'。

    【核心判别标准】
    动作类型 (action_type) 分为两类：
    - "chat": 用户在提问、查询规范、商量参数、或者对刚结束的仿真结果进行评价。**只要用户没有明确表示"确认参数"、"按这个跑吧"、"开始执行仿真"等执行意图，你必须选择 chat**！特别注意：如果历史消息中刚刚显示了一次"仿真完美运行结束"，此时用户不论说什么（比如"太棒了"、"结果在哪"），都应该是 chat，不要重复触发仿真！
    - "simulate": 只有在用户明确确认了参数，或者直接发出"开始执行仿真"、"OK就这样跑"等强烈的开工指令时，才选择 simulate。请注意结合历史消息，如果助手刚问"是否可以开始跑仿真了"，用户回复"好的/可以"，这就是 simulate。
    {exp_injection}
    """

    planner_schema = {
        "title": "Intent_Classification",
        "description": "判断用户仿真的意图类别及下一步动作",
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["bullet_impact", "tunnel_support", "unsupported"],
                "description": "用户的仿真意图归类。"
            },
            "action_type": {
                "type": "string",
                "enum": ["chat", "simulate"],
                "description": "判断用户是仅聊天问询，还是明确要求执行仿真。"
            },
            "reason": {
                "type": "string",
                "description": "简要说明分类理由"
            }
        },
        "required": ["intent", "action_type", "reason"]
    }

    # 组装完整上下文
    messages = [SystemMessage(content=system_prompt)] + memory_window

    structured_llm = llm.with_structured_output(planner_schema)
    result = structured_llm.invoke(messages)

    skill = result["intent"]
    reason = result["reason"]
    action_type = result["action_type"]

    print(f"[Planner] 💡 意图分析: {skill}, 动作: {action_type} (原因: {reason})")

    if action_type == "chat":
        output = {"selected_skill": skill, "action_type": "chat"}
    elif skill == "unsupported":
        error_msg = f"抱歉，系统暂不支持该类型的仿真。原因：{reason}"
        print(f"[Planner] ⚠️ 拦截非法请求: {error_msg}")
        # 🌟 优化：使用 action_type="error" 路由到 END，并通过 AIMessage 通知用户
        output = {
            "action_type": "error",
            "messages": [AIMessage(content=error_msg)]
        }
    else:
        print(f"[Planner] ✅ 获取开工指令，准备进入仿真流程: {skill}")
        output = {"selected_skill": skill, "action_type": "simulate"}

    # 🌟 轨迹埋点
    trace_id = state.get("trace_id")
    if trace_id:
        tracer.log_span(
            trace_id=trace_id,
            span_type="NODE",
            span_name="planner_node",
            start_time=time.time(),
            input_data={"query": query},
            output_data=output
        )

    return output
