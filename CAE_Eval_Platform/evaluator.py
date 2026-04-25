import sqlite3
import json
import uuid
import time
import os
import eval_config
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from db_models import init_db

def run_evaluation():
    """读取未评估的 Trace，使用 LLM-as-a-Judge 进行打分"""
    print("🚀 启动 LLM 自动化评估引擎...")
    init_db(eval_config.DB_PATH) # 确保表存在
    conn = sqlite3.connect(eval_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 获取还没有被评估的 trace
    # 逻辑：在 run_trace 中，但不在 eval_score 中
    cursor.execute('''
        SELECT t.* FROM run_trace t
        LEFT JOIN eval_score e ON t.trace_id = e.trace_id
        WHERE e.trace_id IS NULL AND t.success_flag IS NOT NULL
    ''')
    unevaluated_traces = cursor.fetchall()
    
    if not unevaluated_traces:
        print("✅ 目前没有需要评估的新 Trace。")
        conn.close()
        return

    try:
        llm = ChatOpenAI(
            model=eval_config.EVAL_JUDGE_MODEL,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.1
        )
    except Exception as e:
        print(f"❌ LLM 初始化失败，请检查配置: {e}")
        conn.close()
        return

    system_prompt = """
    你是一个严苛的 AI 智能体评估系统裁判 (LLM-as-a-Judge)。
    你的任务是对一个针对 CAE (计算机辅助工程) 的 Agent 运行轨迹进行打分。
    
    评价维度包括：
    1. 意图理解与沟通 (0-10分)：Agent 是否准确捕捉了用户的意图。
    2. 工具调用合理性 (0-10分)：是否有幻觉工具调用。
    
    请严格返回 JSON 格式结果：
    {
      "score": 8.5,
      "reason": "得分理由简述"
    }
    """
    
    schema = {
        "title": "Evaluation",
        "type": "object",
        "properties": {
            "score": {"type": "number"},
            "reason": {"type": "string"}
        },
        "required": ["score", "reason"]
    }
    structured_llm = llm.with_structured_output(schema)

    for trace in unevaluated_traces:
        trace_id = trace['trace_id']
        print(f"🔍 正在评估 Trace: {trace_id} ...")
        
        # 提取上下文供 LLM 判断
        cursor.execute("SELECT * FROM trace_span WHERE trace_id = ? ORDER BY start_time ASC", (trace_id,))
        spans = cursor.fetchall()
        
        trajectory_str = f"User Query: {trace['user_query']}\n"
        for span in spans:
            trajectory_str += f"\n--- Node: {span['span_name']} ---\n"
            trajectory_str += f"Output/Thought: {span['output_data']}\n"
            
        trajectory_str += f"\nFinal Response: {trace['final_response']}"
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"请评估以下轨迹日志：\n{trajectory_str}")
            ]
            eval_result = structured_llm.invoke(messages)
            
            # 记录回数据库
            conn.execute(
                """INSERT INTO eval_score (eval_id, trace_id, metric_name, score, reason, timestamp) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), trace_id, "Comprehensive_Score", eval_result["score"], eval_result["reason"], time.time())
            )
            conn.commit()
            print(f"  👉 评估完成：得分 {eval_result['score']} | 理由: {eval_result['reason']}")
            
        except Exception as e:
            print(f"  ❌ 评估此 Trace 时发生异常: {e}")

    conn.close()
    print("🏁 当前批次评估全部结束。")

if __name__ == "__main__":
    run_evaluation()
