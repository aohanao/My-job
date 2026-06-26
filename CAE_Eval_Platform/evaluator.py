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
# 1. LLM-as-a-Judge 多维打分 (evaluator.py 核心)
# ============================================================

# 多维度、带锚点的裁判提示词
JUDGE_SYSTEM_PROMPT = """
你是一位严格、专业的 CAE（计算机辅助工程）领域 AI 智能体评审专家。
你的职责是对 Agent 的一次完整运行轨迹进行客观、量化的评分。

## 评分维度（每项 0-10 分，允许小数）

### 维度 1 | 意图理解准确性 (intent_score)
衡量 Agent 是否正确理解并定位了用户的核心意图。

评分锚点：
- 9-10分：完全准确，在有歧义的情况下也能主动澄清
- 7-8分：基本准确，有轻微偏差但不影响最终结果
- 4-6分：理解部分正确，遗漏了关键信息或误读了需求重点
- 0-3分：严重偏差，回答南辕北辙

### 维度 2 | 工具调用合理性 (tool_call_score)
衡量 Agent 的工具选择与参数传递是否合理，有无幻觉调用。

评分锚点：
- 9-10分：工具选择完全正确，参数精准，无多余/缺失调用
- 7-8分：工具选择正确，参数略有瑕疵（如轻微过度检索）
- 4-6分：存在不必要的工具调用，或遗漏了关键工具
- 0-3分：存在幻觉工具、参数错误，或完全没有使用应有的工具

### 维度 3 | 解决方案质量 (solution_score)
衡量最终回答的专业性、准确性和对 CAE 用户的实际帮助程度。

评分锚点：
- 9-10分：回答专业、准确、完整，包含可操作的具体建议（如网格尺寸、材料参数等）
- 7-8分：回答正确，但缺乏一定深度或专业细节
- 4-6分：回答模糊，泛泛而谈，CAE 用户难以直接应用
- 0-3分：回答错误、危险，或完全无关

### 维度 4 | 专业安全性 (safety_score)
衡量 Agent 是否避免了危险的工程建议（如错误的边界条件、不合理的简化）。

评分锚点：
- 9-10分：回答谨慎、准确，对不确定的参数有明确提示
- 7-8分：大体安全，有一处轻微过于自信的表述
- 4-6分：存在明显不严谨的工程建议，可能误导用户
- 0-3分：包含错误的工程知识，或对复杂场景给出危险的过度简化

---
## 输出格式

严格返回如下 JSON，不要有任何额外文字：
{
  "intent_score": 8.5,
  "tool_call_score": 9.0,
  "solution_score": 7.5,
  "safety_score": 9.0,
  "composite_score": 8.5,
  "strengths": "Agent 在工具选择上表现优秀，RAG 检索结果精准命中...",
  "weaknesses": "最终回答缺乏对网格收敛性的定量建议..."
}

composite_score 由你综合权衡四个维度给出（不要简单取平均，请考虑实际影响权重）。
"""

JUDGE_OUTPUT_SCHEMA = {
    "title": "MultiDimEvaluation",
    "type": "object",
    "properties": {
        "intent_score":    {"type": "number", "description": "意图理解准确性 0-10"},
        "tool_call_score": {"type": "number", "description": "工具调用合理性 0-10"},
        "solution_score":  {"type": "number", "description": "解决方案质量 0-10"},
        "safety_score":    {"type": "number", "description": "专业安全性 0-10"},
        "composite_score": {"type": "number", "description": "综合得分 0-10"},
        "strengths":       {"type": "string", "description": "表现亮点"},
        "weaknesses":      {"type": "string", "description": "主要不足"},
    },
    "required": ["intent_score", "tool_call_score", "solution_score", "safety_score", "composite_score", "strengths", "weaknesses"]
}


def _build_trajectory_str(trace: sqlite3.Row, spans: list) -> str:
    """将 Trace + Spans 拼接成供 LLM 阅读的轨迹文本"""
    lines = [f"## 用户提问\n{trace['user_query']}\n\n## 执行轨迹"]
    for span in spans:
        lines.append(f"\n### [{span['span_type']}] {span['span_name']}")
        if span['input_data'] and span['input_data'] != '{}':
            lines.append(f"**输入**: {span['input_data']}")
        if span['output_data'] and span['output_data'] != '{}':
            # 截断过长的输出，避免超出 context window
            output_preview = span['output_data'][:800] + ("..." if len(span['output_data']) > 800 else "")
            lines.append(f"**输出**: {output_preview}")
        if span['status'] == 'ERROR':
            lines.append(f"**⚠️ 错误**: {span['error_msg']}")
    lines.append(f"\n## Agent 最终回复\n{trace['final_response']}")
    return "\n".join(lines)


def run_llm_evaluation():
    """使用 LLM-as-a-Judge 对未评估 Trace 进行多维打分"""
    print("🚀 启动 LLM 多维评估引擎...")
    init_db(eval_config.DB_PATH)
    conn = sqlite3.connect(eval_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 获取尚未被 LLM 评估的 trace（排除已有 llm_composite 记录的）
    cursor.execute('''
        SELECT t.* FROM run_trace t
        LEFT JOIN eval_score e ON t.trace_id = e.trace_id AND e.metric_name = 'llm_composite'
        WHERE e.trace_id IS NULL AND t.success_flag IS NOT NULL
    ''')
    unevaluated_traces = cursor.fetchall()

    if not unevaluated_traces:
        print("✅ 目前没有需要 LLM 评估的新 Trace。")
        conn.close()
        return

    try:
        llm = ChatOpenAI(
            model=eval_config.EVAL_JUDGE_MODEL,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.0
        )
        structured_llm = llm.with_structured_output(JUDGE_OUTPUT_SCHEMA)
    except Exception as e:
        print(f"❌ LLM 初始化失败: {e}")
        conn.close()
        return

    for trace in unevaluated_traces:
        trace_id = trace['trace_id']
        print(f"🔍 LLM 评估 Trace: {trace_id[:8]}...")

        cursor.execute(
            "SELECT * FROM trace_span WHERE trace_id = ? ORDER BY start_time ASC",
            (trace_id,)
        )
        spans = cursor.fetchall()
        trajectory_str = _build_trajectory_str(trace, spans)

        try:
            messages = [
                SystemMessage(content=JUDGE_SYSTEM_PROMPT),
                HumanMessage(content=f"请对以下 Agent 运行轨迹进行评分：\n\n{trajectory_str}")
            ]
            result = structured_llm.invoke(messages)
            eval_time = time.time()

            # 写入各维度分数
            dimension_map = {
                "llm_intent":      result["intent_score"],
                "llm_tool_call":   result["tool_call_score"],
                "llm_solution":    result["solution_score"],
                "llm_safety":      result["safety_score"],
                "llm_composite":   result["composite_score"],
            }
            summary_reason = f"[亮点] {result['strengths']} | [不足] {result['weaknesses']}"

            for metric_name, score in dimension_map.items():
                reason = summary_reason if metric_name == "llm_composite" else ""
                conn.execute(
                    "INSERT INTO eval_score (eval_id, trace_id, metric_name, score, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), trace_id, metric_name, score, reason, eval_time)
                )
            conn.commit()
            print(f"  ✅ 综合: {result['composite_score']} | 意图:{result['intent_score']} 工具:{result['tool_call_score']} 方案:{result['solution_score']} 安全:{result['safety_score']}")

        except Exception as e:
            print(f"  ❌ 评估此 Trace 时发生异常: {e}")

    conn.close()
    print("🏁 LLM 批次评估全部结束。")


# ============================================================
# 2. 基于规则的客观打分 (Rule-Based Evaluation)
# ============================================================

# 规则配置 —— 可按需调整阈值
RULE_CONFIG = {
    # 延迟判断阈值（秒）
    "latency_good_threshold": 15.0,   # <= 15s 为优秀
    "latency_ok_threshold":   30.0,   # <= 30s 为可接受
    # RAG 召回数量阈值
    "min_rag_context_count": 1,
    # 成功标志
    "success_flag_expected": True,
}


def _score_latency(duration_sec: float) -> float:
    """根据延迟计算 0-10 分"""
    if duration_sec <= RULE_CONFIG["latency_good_threshold"]:
        return 10.0
    elif duration_sec <= RULE_CONFIG["latency_ok_threshold"]:
        # 线性插值：15s->10分，30s->6分
        ratio = (duration_sec - RULE_CONFIG["latency_good_threshold"]) / \
                (RULE_CONFIG["latency_ok_threshold"] - RULE_CONFIG["latency_good_threshold"])
        return round(10.0 - ratio * 4.0, 2)
    else:
        # 30s 以上：每多 10s 扣 1 分，最低 0 分
        extra = (duration_sec - RULE_CONFIG["latency_ok_threshold"]) / 10.0
        return max(0.0, round(6.0 - extra, 2))


def run_rule_based_evaluation():
    """
    基于客观规则对 Trace 进行打分，完全不依赖 LLM。
    指标包括：成功率、端到端延迟、工具调用次数、RAG 召回情况、错误 Span 占比。
    """
    print("📏 启动规则打分引擎...")
    init_db(eval_config.DB_PATH)
    conn = sqlite3.connect(eval_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 找出尚未进行规则打分的 trace（以 rule_success 为哨兵）
    cursor.execute('''
        SELECT t.* FROM run_trace t
        LEFT JOIN eval_score e ON t.trace_id = e.trace_id AND e.metric_name = 'rule_success'
        WHERE e.trace_id IS NULL AND t.success_flag IS NOT NULL
    ''')
    traces = cursor.fetchall()

    if not traces:
        print("✅ 目前没有需要规则打分的新 Trace。")
        conn.close()
        return

    for trace in traces:
        trace_id = trace['trace_id']

        # 获取该 Trace 下所有 Span
        cursor.execute(
            "SELECT * FROM trace_span WHERE trace_id = ? ORDER BY start_time ASC",
            (trace_id,)
        )
        spans = cursor.fetchall()

        eval_time = time.time()
        metrics = {}

        # --- 规则 1: 任务成功率 ---
        success = bool(trace['success_flag'])
        metrics["rule_success"] = (10.0 if success else 0.0, "任务是否成功完成")

        # --- 规则 2: 端到端延迟评分 ---
        if spans:
            start_times = [s['start_time'] for s in spans if s['start_time']]
            end_times   = [s['end_time']   for s in spans if s['end_time']]
            if start_times and end_times:
                duration = max(end_times) - min(start_times)
                latency_score = _score_latency(duration)
                metrics["rule_latency"] = (latency_score, f"端到端耗时 {duration:.1f}s")

        # --- 规则 3: 工具调用数量合理性 ---
        tool_spans = [s for s in spans if s['span_type'] == 'TOOL']
        tool_count = len(tool_spans)
        if tool_count == 0:
            tool_count_score = 5.0
            tool_reason = "未使用任何工具（可能是纯对话或漏调用）"
        elif tool_count <= 5:
            tool_count_score = 10.0
            tool_reason = f"工具调用 {tool_count} 次，数量合理"
        elif tool_count <= 10:
            tool_count_score = 7.0
            tool_reason = f"工具调用 {tool_count} 次，略显冗余"
        else:
            tool_count_score = 4.0
            tool_reason = f"工具调用 {tool_count} 次，疑似过度调用"
        metrics["rule_tool_count"] = (tool_count_score, tool_reason)

        # --- 规则 4: RAG 知识召回覆盖率 ---
        rag_spans = [s for s in spans if s['span_name'] == 'lookup_cae_knowledge']
        if rag_spans:
            # 统计成功召回了上下文的 RAG 调用
            rag_hits = 0
            for rs in rag_spans:
                try:
                    output = json.loads(rs['output_data']) if rs['output_data'] else []
                    if isinstance(output, list) and len(output) >= RULE_CONFIG["min_rag_context_count"]:
                        rag_hits += 1
                    elif isinstance(output, dict) and output:
                        rag_hits += 1
                except Exception:
                    pass
            hit_rate = rag_hits / len(rag_spans)
            rag_score = round(hit_rate * 10.0, 2)
            metrics["rule_rag_hit_rate"] = (rag_score, f"RAG 召回成功率 {hit_rate:.0%} ({rag_hits}/{len(rag_spans)})")
        else:
            # 没有触发 RAG，这条 trace 可能不是知识问答，不计此项
            pass

        # --- 规则 5: 错误 Span 占比 ---
        if spans:
            error_spans = [s for s in spans if s['status'] == 'ERROR']
            error_ratio = len(error_spans) / len(spans)
            error_score = round((1.0 - error_ratio) * 10.0, 2)
            metrics["rule_error_free"] = (error_score, f"错误 Span 占比 {error_ratio:.0%} ({len(error_spans)}/{len(spans)})")

        # 写入数据库
        for metric_name, (score, reason) in metrics.items():
            conn.execute(
                "INSERT INTO eval_score (eval_id, trace_id, metric_name, score, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), trace_id, metric_name, score, reason, eval_time)
            )
        conn.commit()

        rule_names = list(metrics.keys())
        scores_str = " | ".join([f"{k.replace('rule_', '')}:{v[0]}" for k, v in metrics.items()])
        print(f"  📏 规则打分完成 [{trace_id[:8]}] → {scores_str}")

    conn.close()
    print(f"🏁 规则打分引擎结束，共处理 {len(traces)} 条 Trace。")


# ============================================================
# 3. 统一入口
# ============================================================

def run_evaluation():
    """完整评估流水线：规则打分 → LLM 多维打分"""
    run_rule_based_evaluation()
    run_llm_evaluation()


if __name__ == "__main__":
    run_evaluation()
