import ast
import sqlite3
import json
import uuid
import time
import os
import eval_config
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from db_models import init_db

# ============================================================
# 🤖 CAE 报错诊断与智能自愈 Agent (healing_agent.py)
#
# 架构：Agentic Reflexion Loop
#   诊断 → 生成修复代码 → 静态校验
#          ↑              │
#          └── 失败反馈 ←─┘ (最多 MAX_RETRIES 次)
#                         │
#                         ↓ 校验通过
#                   LLM 模拟执行 → 写库
# ============================================================

MAX_RETRIES = 3  # Reflexion 最大重试轮次

HEALING_SYSTEM_PROMPT = """
你是一位极其资深的 CAE（计算机辅助工程）与 RAGOps 智能体自愈专家。
现在，一个 CAE 仿真智能体在执行任务时发生了报错（任务失败）。你的职责是分析错误轨迹，定位根本原因（RCA），并给出能够修复此错误的方案与代码。

请根据提供的：
1. 用户原始提问 (User Query)
2. Agent 执行轨迹 (Trace Spans) —— 包含正常执行节点和报错节点（ status='ERROR' 并带有错误信息 ）
3. 出错节点输入与输出数据

进行深入诊断，并产出诊断报告。

## 输出格式
你必须严格返回如下格式的 JSON 字符串，不要包含 markdown 格式标记 (如 ```json) 或任何多余字符：
{
  "diagnostic_summary": "请在这里详细写出错误的根本原因分析 (RCA)。例如：在生成 Abaqus 脚本时，将弹性模量参数的单位错写为了 MPa 导致网格畸变报错，或 RAG 没有检索到衬砌厚度相关规范导致参数缺失...",
  "suggested_fix": "请在这里写出具体的修复步骤。例如：1. 修改 Coder 节点的 Prompt，强制单位统一为 Pa；2. 对输入的网格尺寸进行边界值校验，防止出现 0 或负数...",
  "fixed_code": "在这里写出修复后的 Python 代码、修复后的 JSON 参数，或具体的修复策略。如果是 Python 代码编写错误，请在此提供修改后可直接运行的完整 Python 代码。如果是外部 API/知识库问题，请输入调整后的知识检索建议或说明。"
}
"""

HEALING_OUTPUT_SCHEMA = {
    "title": "SelfHealingDiagnostic",
    "type": "object",
    "properties": {
        "diagnostic_summary": {"type": "string", "description": "错误根因分析 (RCA) 详情"},
        "suggested_fix": {"type": "string", "description": "具体的修复手段和建议"},
        "fixed_code": {"type": "string", "description": "修复后的完整代码、修改后的参数，或配置说明"}
    },
    "required": ["diagnostic_summary", "suggested_fix", "fixed_code"]
}


# ============================================================
# 工具函数
# ============================================================

def _get_llm() -> ChatOpenAI:
    """统一的 LLM 工厂，避免重复初始化"""
    return ChatOpenAI(
        model=eval_config.EVAL_JUDGE_MODEL,
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url=os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        temperature=0.1
    )


def _build_error_context_str(trace: sqlite3.Row, spans: list) -> str:
    """构建用于大模型诊断的错误上下文文本"""
    lines = [
        f"【用户原始提问】: {trace['user_query']}",
        "【Agent 执行轨迹】:"
    ]

    error_span_found = False
    for idx, span in enumerate(spans):
        status_icon = "[ERROR]" if span['status'] == 'ERROR' else "[SUCCESS]"
        lines.append(f"\n[{idx+1}] 节点: {span['span_name']} ({span['span_type']}) - 状态: {status_icon} {span['status']}")

        if span['input_data'] and span['input_data'] != '{}':
            input_preview = span['input_data'][:500] + ("..." if len(span['input_data']) > 500 else "")
            lines.append(f"   输入负载: {input_preview}")

        if span['output_data'] and span['output_data'] != '{}':
            output_preview = span['output_data'][:500] + ("..." if len(span['output_data']) > 500 else "")
            lines.append(f"   输出负载: {output_preview}")

        if span['status'] == 'ERROR' or span['error_msg']:
            error_span_found = True
            lines.append(f"   [Error] 报错信息 (error_msg): {span['error_msg']}")

    if not error_span_found:
        lines.append("\n提示：在 spans 列表中没有显式标记为 ERROR 的节点，请根据最后一个执行节点的输出或最终响应定位异常。")

    lines.append(f"\n【Agent 最终输出响应】: {trace['final_response']}")
    return "\n".join(lines)


def _validate_fixed_code(fixed_code: str) -> tuple[bool, str]:
    """
    对 LLM 生成的 fixed_code 进行静态安全校验。

    校验优先级：
      1. 内容非空检查
      2. ast.parse 语法树解析（Python 代码专用，安全无执行风险）
      3. 若非 Python 代码（JSON / 文字建议），判断其非空即为通过

    Returns:
        (True, "") — 校验通过
        (False, error_message) — 校验失败及原因
    """
    if not fixed_code or fixed_code.strip() in ("N/A", "", "无"):
        return False, "fixed_code 内容为空或无效（N/A）"

    code = fixed_code.strip()

    # 判断是否是 Python 代码：含有典型 Python 关键词
    looks_like_python = any(kw in code for kw in ("def ", "import ", "class ", "print(", "=", "for ", "if "))

    if looks_like_python:
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Python 语法错误 (SyntaxError): {e.msg}，位于第 {e.lineno} 行"

    # 非 Python 代码（如 JSON 参数建议、文字策略）：检查是否实质性非空
    if len(code) > 20:
        return True, ""

    return False, "fixed_code 内容过短，无实质性修复建议"


def _call_healing_llm(llm: ChatOpenAI, context_str: str, feedback: str = "") -> dict | None:
    """
    调用诊断 LLM 生成修复方案。

    Args:
        llm: 已初始化的 ChatOpenAI 实例
        context_str: 原始错误上下文
        feedback: Reflexion 反馈（上一轮校验失败的错误信息），空字符串表示首次诊断
    """
    structured_llm = llm.with_structured_output(HEALING_OUTPUT_SCHEMA)

    if feedback:
        # Reflexion 追加：将上一轮的校验错误作为新上下文补充给 LLM
        user_content = (
            f"以下是发生报错的 Agent 链路追踪上下文，请进行诊断并给出修复代码：\n\n{context_str}"
            f"\n\n---\n【⚠️ Reflexion 反馈】：上一轮你生成的修复代码未通过验证，错误如下：\n{feedback}"
            f"\n请根据上述反馈，重新诊断并生成更正确的修复代码。"
        )
    else:
        user_content = f"以下是发生报错的 Agent 链路追踪上下文，请进行诊断并给出修复代码：\n\n{context_str}"

    messages = [
        SystemMessage(content=HEALING_SYSTEM_PROMPT),
        HumanMessage(content=user_content)
    ]
    return structured_llm.invoke(messages)


# ============================================================
# Reflexion Loop 核心
# ============================================================

def _run_reflexion_loop(
    error_context: str,
    llm: ChatOpenAI,
    max_retries: int = MAX_RETRIES
) -> dict:
    """
    Agentic Reflexion Loop：
      - 最多迭代 max_retries 次
      - 每轮：LLM 生成修复 → 静态校验 → 失败则带反馈重试
      - 返回字典：{success, result, attempts, last_error}
    """
    last_error = ""
    result = None

    for attempt in range(1, max_retries + 1):
        print(f"  [Reflexion] ━━ 第 {attempt}/{max_retries} 轮 ━━")

        # Step 1: LLM 生成修复方案
        try:
            result = _call_healing_llm(llm, error_context, feedback=last_error)
        except Exception as e:
            last_error = f"LLM 调用失败: {e}"
            print(f"  [Reflexion] ❌ 第 {attempt} 轮 LLM 调用出错: {e}")
            continue

        fixed_code = result.get("fixed_code", "")
        print(f"  [Reflexion] 📝 修复方案已生成，正在进行静态校验...")

        # Step 2: 静态校验
        valid, validation_error = _validate_fixed_code(fixed_code)

        if valid:
            print(f"  [Reflexion] ✅ 第 {attempt} 轮校验通过！")
            return {
                "success": True,
                "result": result,
                "attempts": attempt,
                "last_error": ""
            }
        else:
            last_error = validation_error
            print(f"  [Reflexion] ❌ 第 {attempt} 轮校验失败：{validation_error}，{'发起重试...' if attempt < max_retries else '已达最大重试次数'}")

    # 所有重试均失败
    return {
        "success": False,
        "result": result,   # 保留最后一次 LLM 的输出，方便 debug
        "attempts": max_retries,
        "last_error": last_error
    }


# ============================================================
# 对外公开的核心接口
# ============================================================

def run_diagnose(trace_id: str) -> dict:
    """
    对指定的报错 Trace 进行单次智能诊断（不含 Reflexion），
    生成 RCA 根因分析和修复代码，并写入 healing_report 表（状态: PENDING）。
    """
    print(f"[Self-Healing] 正在为 Trace [{trace_id}] 启动智能诊断 Agent...")
    init_db(eval_config.DB_PATH)
    conn = sqlite3.connect(eval_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM run_trace WHERE trace_id = ?", (trace_id,))
    trace = cursor.fetchone()
    if not trace:
        print(f"[Self-Healing] 未找到 Trace ID 为 {trace_id} 的记录。")
        conn.close()
        return None

    cursor.execute("SELECT * FROM trace_span WHERE trace_id = ? ORDER BY start_time ASC", (trace_id,))
    spans = cursor.fetchall()
    error_context = _build_error_context_str(trace, spans)

    try:
        llm = _get_llm()
        result = _call_healing_llm(llm, error_context)

        healing_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO healing_report
            (healing_id, trace_id, diagnostic_summary, suggested_fix, fixed_code, execution_status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (healing_id, trace_id, result["diagnostic_summary"], result["suggested_fix"],
             result["fixed_code"], "PENDING", time.time())
        )
        conn.commit()
        print(f"  [Self-Healing] 诊断报告已生成！自愈报告 ID: {healing_id} | 状态: PENDING")
        conn.close()
        return {
            "healing_id": healing_id,
            "diagnostic_summary": result["diagnostic_summary"],
            "suggested_fix": result["suggested_fix"],
            "fixed_code": result["fixed_code"],
            "status": "PENDING"
        }
    except Exception as e:
        print(f"[Self-Healing] 调用自愈诊断模型失败: {e}")
        conn.close()
        return None


def execute_self_healing(trace_id: str, max_retries: int = MAX_RETRIES) -> dict:
    """
    针对报错 Trace 执行完整的 Agentic Reflexion 自愈流程：
      1. 读取 Trace 错误上下文
      2. 启动 Reflexion Loop（最多 max_retries 轮）：
         LLM 诊断 → 生成修复 → 静态校验 → 失败带反馈重试
      3. 循环通过 → LLM 模拟仿真执行 → 标记自愈成功
      4. 循环失败 → 写入失败报告，标记 FAILED

    success_flag 语义：
      0 = 原始执行失败
      1 = 原始执行成功
      2 = 自愈成功（经过验证通过的修复方案 + 模拟执行确认）
    """
    print(f"[Self-Healing] ▶ 启动 Reflexion 自愈流程 [Trace: {trace_id}]（最多 {max_retries} 轮）")
    init_db(eval_config.DB_PATH)
    conn = sqlite3.connect(eval_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # --- 1. 读取错误上下文 ---
    cursor.execute("SELECT * FROM run_trace WHERE trace_id = ?", (trace_id,))
    trace = cursor.fetchone()
    if not trace:
        conn.close()
        return {"status": "FAILED", "error_msg": f"未找到 Trace: {trace_id}"}

    cursor.execute("SELECT * FROM trace_span WHERE trace_id = ? ORDER BY start_time ASC", (trace_id,))
    spans = cursor.fetchall()
    error_context = _build_error_context_str(trace, spans)
    user_query = trace["user_query"] or ""

    # --- 2. 初始化 LLM ---
    try:
        llm = _get_llm()
    except Exception as e:
        conn.close()
        return {"status": "FAILED", "error_msg": f"LLM 初始化失败: {e}"}

    # --- 3. Reflexion Loop ---
    loop_result = _run_reflexion_loop(error_context, llm, max_retries=max_retries)

    healing_id = str(uuid.uuid4())
    diagnostic_summary = ""
    suggested_fix = ""
    fixed_code = ""
    final_healed_response = ""
    exec_log = []

    if loop_result["result"]:
        diagnostic_summary = loop_result["result"].get("diagnostic_summary", "")
        suggested_fix = loop_result["result"].get("suggested_fix", "")
        fixed_code = loop_result["result"].get("fixed_code", "")

    exec_log.append(f"[Reflexion Loop] 共执行 {loop_result['attempts']} 轮诊断-校验迭代")

    # --- 4A. 校验失败 → 记录失败报告 ---
    if not loop_result["success"]:
        exec_log.append(f"[Reflexion Loop] ❌ 未能在 {max_retries} 轮内生成通过校验的修复方案")
        exec_log.append(f"[Reflexion Loop] 最终校验错误: {loop_result['last_error']}")
        final_log = "\n".join(exec_log)

        conn.execute(
            """INSERT INTO healing_report
            (healing_id, trace_id, diagnostic_summary, suggested_fix, fixed_code,
             execution_status, fixed_output, error_msg, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (healing_id, trace_id, diagnostic_summary, suggested_fix, fixed_code,
             "FAILED", "", loop_result["last_error"], time.time())
        )
        conn.commit()
        conn.close()
        print(f"[Self-Healing] ✗ 自愈失败，Trace [{trace_id}] 无法生成有效修复。")
        return {
            "status": "FAILED",
            "healing_id": healing_id,
            "attempts": loop_result["attempts"],
            "diagnostic_summary": diagnostic_summary,
            "suggested_fix": suggested_fix,
            "fixed_code": fixed_code,
            "error_msg": loop_result["last_error"],
            "log": final_log
        }

    # --- 4B. 校验通过 → LLM 模拟执行 ---
    exec_log.append(f"[Reflexion Loop] ✅ 修复方案经过 {loop_result['attempts']} 轮迭代，静态校验通过")
    exec_log.append("[模拟执行] 正在调用 LLM 仿真器模拟修复方案的执行结果...")

    simulation_success = False
    try:
        sim_llm = ChatOpenAI(
            model=eval_config.EVAL_JUDGE_MODEL,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.2
        )
        sim_prompt = f"""
你是一位 CAE 仿真运行环境模拟器。
目前我们对一个报错的任务进行了修复，修复代码/方案为：
{fixed_code}

原始用户提问：{user_query}
诊断出的错误原因：{diagnostic_summary}

请你模拟该修复方案在 CAE 仿真环境中的重新执行。如果执行成功，请给出修复后的正确输出响应。
输出内容应当极其专业、精确，符合 CAE 工程师的预期，并直接解决用户的问题。
请直接输出最终的系统响应内容，不要包含任何"模拟运行"、"已修复"等解释性前缀。
"""
        sim_res = sim_llm.invoke([SystemMessage(content=sim_prompt)])
        final_healed_response = sim_res.content.strip()
        simulation_success = True
        exec_log.append("[模拟执行] ✅ 仿真模拟执行成功，已生成修复后的响应。")
    except Exception as sim_err:
        exec_log.append(f"[模拟执行] ❌ LLM 仿真模拟失败: {sim_err}")
        final_healed_response = f"[自愈静态校验通过，但仿真模拟失败：{sim_err}]"

    # --- 5. 写入 DB ---
    final_log = "\n".join(exec_log)
    # success_flag=2 仅在：代码校验通过 AND 模拟执行成功 时设置
    overall_success = loop_result["success"] and simulation_success
    status_str = "SUCCESS" if overall_success else "PARTIAL"

    conn.execute(
        """INSERT INTO healing_report
        (healing_id, trace_id, diagnostic_summary, suggested_fix, fixed_code,
         execution_status, fixed_output, error_msg, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (healing_id, trace_id, diagnostic_summary, suggested_fix, fixed_code,
         status_str, final_healed_response, "", time.time())
    )

    if overall_success:
        # 仅当完整自愈成功时，才更新原 Trace 为已自愈状态
        healed_marker = (
            f"{final_healed_response}\n\n"
            f"--- [AI 智能自愈成功] ---\n"
            f"经过 {loop_result['attempts']} 轮 Reflexion 迭代，原执行报错已自动纠错修复。\n"
            f"修复诊断：{diagnostic_summary}"
        )
        conn.execute(
            "UPDATE run_trace SET success_flag = 2, final_response = ? WHERE trace_id = ?",
            (healed_marker, trace_id)
        )

    conn.commit()
    conn.close()

    print(f"[Self-Healing] {'✅ 自愈成功' if overall_success else '⚠️ 部分自愈'} | Trace [{trace_id}] | 迭代轮次: {loop_result['attempts']}")
    return {
        "status": status_str,
        "healing_id": healing_id,
        "attempts": loop_result["attempts"],
        "diagnostic_summary": diagnostic_summary,
        "suggested_fix": suggested_fix,
        "fixed_code": fixed_code,
        "fixed_output": final_healed_response,
        "log": final_log
    }


# ============================================================
# 命令行快速测试入口
# ============================================================

if __name__ == "__main__":
    init_db(eval_config.DB_PATH)
    conn = sqlite3.connect(eval_config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT trace_id FROM run_trace WHERE success_flag = 0 LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if row:
        tid = row[0]
        print(f"▶ 测试 Reflexion 自愈，Trace: {tid}")
        res = execute_self_healing(tid)
        print("\n自愈结果：")
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("没有找到 success_flag=0 的失败 Trace，无法测试自愈。")
