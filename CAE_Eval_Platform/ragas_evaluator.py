import sqlite3
import json
import uuid
import time
import os
import numpy as np
import pandas as pd
import eval_config
from datasets import Dataset
from db_models import init_db

# ================================
# Ragas 专属拦截器
# ================================
try:
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy
    from langchain_community.chat_models import ChatTongyi
    from langchain_community.embeddings import DashScopeEmbeddings
except ImportError:
    print("❌ 未检测到 RAGAS 库！请执行 `pip install ragas datasets`")
    exit(1)

def build_judge_llm():
    """加载裁判模型"""
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("请在环境变量中设置 DASHSCOPE_API_KEY")
        
    judge_model = ChatTongyi(model=eval_config.EVAL_JUDGE_MODEL, max_retries=5)
    judge_embeddings = DashScopeEmbeddings(model=eval_config.EVAL_EMBEDDING_MODEL)
    return judge_model, judge_embeddings

def fetch_unevaluated_rag_samples():
    """抓取尚未被 RAGAS 评测过的知识检索样本"""
    conn = sqlite3.connect(eval_config.DB_PATH)
    cursor = conn.cursor()
    
    # 寻找所有的 RAG Tool Call Span
    cursor.execute('''
        SELECT span_id, trace_id, input_data, output_data 
        FROM trace_span 
        WHERE span_name = 'lookup_cae_knowledge'
    ''')
    rag_spans = cursor.fetchall()
    
    samples = []
    for span_id, trace_id, input_data, output_data in rag_spans:
        cursor.execute("SELECT 1 FROM eval_score WHERE trace_id = ? AND metric_name LIKE 'ragas_%'", (trace_id,))
        if cursor.fetchone():
            continue
            
        try:
            # 从 run_trace 中获取原始的用户提问和最终回答
            cursor.execute("SELECT user_query, final_response FROM run_trace WHERE trace_id = ?", (trace_id,))
            trace_res = cursor.fetchone()
            
            # 【修复点1】问题应该取用户原始提问，而不是 Tool 的输入（Tool输入通常是关键词，会导致相关性评分极低）
            user_query = trace_res[0] if trace_res and trace_res[0] else "未知问题"
            answer = trace_res[1] if trace_res and trace_res[1] else "未生成回答"
            
            # 【修复点2】将结构化数据转为自然语言，防止 Ragas 看不懂 JSON 导致忠实度 0 分
            contexts_raw = json.loads(output_data) if output_data else ""
            
            def dict_to_nl(d):
                if not isinstance(d, dict): return str(d)
                lines = []
                for k, v in d.items():
                    if isinstance(v, dict):
                        lines.append(f"{k} 包含以下属性: {', '.join([f'{sub_k}为{sub_v}' for sub_k, sub_v in v.items()])}")
                    else:
                        lines.append(f"{k} 为 {v}")
                return "；".join(lines)

            if isinstance(contexts_raw, list):
                contexts = [dict_to_nl(c) if isinstance(c, dict) else str(c) for c in contexts_raw]
            elif isinstance(contexts_raw, dict):
                contexts = [dict_to_nl(contexts_raw)]
            else:
                contexts = [str(contexts_raw)] if contexts_raw else [""]
            
            samples.append({
                "question": user_query,
                "answer": answer,
                "contexts": contexts,
                "trace_id": trace_id
            })
        except Exception as e:
            print(f"解析跨度 {span_id} 时出错: {e}")
            
    conn.close()
    return samples

def execute_ragas():
    print("🎯 正在拉取待评测的 RAG 黄金样本...")
    init_db(eval_config.DB_PATH) 
    samples = fetch_unevaluated_rag_samples()
    
    if not samples:
        print("☕ 暂无新的 RAG 检索记录需要评测。")
        return
        
    print(f"📊 发现 {len(samples)} 条新生 RAG 记录，正在唤醒 RAGAS 仲裁机(模型: {eval_config.EVAL_JUDGE_MODEL})...")
    
    llm, embeddings = build_judge_llm()
    
    dataset_dict = {
        "question": [s["question"] for s in samples],
        "answer": [s["answer"] for s in samples],
        "contexts": [s["contexts"] for s in samples]
    }
    eval_dataset = Dataset.from_dict(dataset_dict)
    
    # 为各指标显式挂载模型实例以兼容新版 Ragas
    for metric in [faithfulness, answer_relevancy]:
        metric.llm = llm
        if hasattr(metric, "embeddings"):
            metric.embeddings = embeddings
            
    # 启动评估
    result = evaluate(
        dataset=eval_dataset,
        metrics=[faithfulness, answer_relevancy],
        raise_exceptions=False
    )
    
    df_result = result.to_pandas()
    
    conn = sqlite3.connect(eval_config.DB_PATH)
    for index, row in df_result.iterrows():
        trace_id = samples[index]["trace_id"]
        eval_time = time.time()
        
        # 写入 faithfulness
        f_score = row.get("faithfulness", 0.0)
        if pd.isna(f_score): f_score = 0.0  # 防止 API 超时返回 NaN 导致报错
        
        conn.execute("INSERT INTO eval_score (eval_id, trace_id, metric_name, score, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), trace_id, "ragas_faithfulness", f_score, "RAGAS客观指标(无文字解释)", eval_time))
                     
        # 写入 answer_relevancy
        r_score = row.get("answer_relevancy", 0.0)
        if pd.isna(r_score): r_score = 0.0
        
        conn.execute("INSERT INTO eval_score (eval_id, trace_id, metric_name, score, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), trace_id, "ragas_answer_relevancy", r_score, "RAGAS客观指标(无文字解释)", eval_time))
                     
    conn.commit()
    conn.close()
    print("✅ RAGAS 批量评测结果已成功入库！")

if __name__ == "__main__":
    execute_ragas()
