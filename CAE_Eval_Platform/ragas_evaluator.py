import sqlite3
import json
import uuid
import time
import os
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
        
    judge_model = ChatTongyi(model=eval_config.EVAL_JUDGE_MODEL)
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
            question_dict = json.loads(input_data)
            question = question_dict.get("query", "") if isinstance(question_dict, dict) else str(question_dict)
            
            contexts_raw = json.loads(output_data) if output_data else ""
            contexts = [str(contexts_raw)] if contexts_raw else [""]
            
            cursor.execute("SELECT final_response FROM run_trace WHERE trace_id = ?", (trace_id,))
            trace_res = cursor.fetchone()
            answer = trace_res[0] if trace_res and trace_res[0] else "未生成回答"
            
            samples.append({
                "question": question,
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
    
    # 启动评估 (仅包含无需标准答案的指标)
    result = evaluate(
        dataset=eval_dataset,
        metrics=[faithfulness, answer_relevancy],
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=False
    )
    
    df_result = result.to_pandas()
    
    conn = sqlite3.connect(eval_config.DB_PATH)
    for index, row in df_result.iterrows():
        trace_id = samples[index]["trace_id"]
        eval_time = time.time()
        
        # 写入 faithfulness
        f_score = row.get("faithfulness", 0.0)
        conn.execute("INSERT INTO eval_score (eval_id, trace_id, metric_name, score, timestamp) VALUES (?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), trace_id, "ragas_faithfulness", f_score, eval_time))
                     
        # 写入 answer_relevancy
        r_score = row.get("answer_relevancy", 0.0)
        conn.execute("INSERT INTO eval_score (eval_id, trace_id, metric_name, score, timestamp) VALUES (?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), trace_id, "ragas_answer_relevancy", r_score, eval_time))
                     
    conn.commit()
    conn.close()
    print("✅ RAGAS 批量评测结果已成功入库！")

if __name__ == "__main__":
    execute_ragas()
