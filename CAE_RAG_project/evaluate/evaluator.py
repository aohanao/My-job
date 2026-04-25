# evaluate/evaluator.py
import os
# 🚀 必须在所有导入之前设置，强制使用国内镜像
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

"""
CAE RAG 自动化评估系统 (RAGAS 升级版)
=====================================
功能：
1. 专业评估：引入 RAGAS 指标（忠实度、相关性、检索精准率、检索召回率）。
2. 全程入湖：所有 Trace 和 RAGAS 指标自动同步至 LangSmith。
3. 闭环优化：为检索和生成质量提供客观、可量化的数据支持。
"""
import sys
import json
import time
import pandas as pd
from datasets import Dataset
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Ragas 相关导入
try:
    from ragas import evaluate
    # 使用推荐的导入路径以消除 DeprecationWarning
    from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
    from langchain_community.chat_models import ChatTongyi
    from langchain_community.embeddings import DashScopeEmbeddings
except ImportError:
    print("❌ 未检测到 RAGAS 相关库，请运行 `pip install ragas datasets` 后重试。")
    sys.exit(1)

from rag import RagService

# ==========================================
# 📋 评估配置
# ==========================================
EVAL_DATASET_PATH = os.path.join(os.path.dirname(__file__), "eval_dataset.json")
EVAL_REPORT_PATH = os.path.join(os.path.dirname(__file__), "eval_report.json")
LANGSMITH_PROJECT = os.getenv("LANGCHAIN_PROJECT", "CAE_RAG_Evaluation")

def run_evaluation():
    print("🚀 启动 CAE 专属 RAG 自动化评估体系 (Standard RAGAS Metrics)...")

    # 1. 初始化 RAG 服务
    rag_engine = RagService()
    
    # 2. 初始化裁判模型（用于 RAGAS 内部判分）
    # Ragas 如果不显式传入 llm/embeddings，会默认调用 OpenAI
    judge_llm = ChatTongyi(model="qwen-max", temperature=0.0)
    judge_embeddings = DashScopeEmbeddings(model="text-embedding-v4")

    # 3. 加载本地题库 (包含 question 和 ground_truth)
    with open(EVAL_DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    print(f"📝 已加载 {len(dataset)} 道考题，开始执行检索与预测...\n")

    eval_data = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": []
    }

    # 4. 逐题运行，收集预测结果
    for idx, item in enumerate(dataset):
        print(f"--- 正在执行 Case {idx+1}/{len(dataset)} ---")
        question = item["question"]
        ground_truth = item["ground_truth"]

        try:
            # (1) 获取系统回答 (Stream 接口拼接)
            full_answer = ""
            eval_config = {"configurable": {"session_id": f"eval_test_{idx}"}}
            for chunk in rag_engine.stream_with_cache({"input": question}, eval_config):
                if "✨" not in chunk:
                    full_answer += chunk

            # (2) 获取检索到的 Context
            # RAGAS 期望 contexts 为字符串列表
            raw_docs = rag_engine.retriever_service.search_and_rerank(question)
            doc_contents = [doc.page_content for doc in raw_docs]

            eval_data["question"].append(question)
            eval_data["answer"].append(full_answer)
            eval_data["contexts"].append(doc_contents)
            eval_data["ground_truth"].append(ground_truth)

            print(f"✅ Case {idx+1} 完成执行\n")

        except Exception as e:
            print(f"❌ Case {idx+1} 运行失败: {e}\n")

    if not eval_data["question"]:
        print("⚠️ 未收集到有效测试结果。")
        return

    # 5. 启动 RAGAS 评估
    print("🧑‍⚖️ 正在唤醒 RAGAS 仲裁机解析指标...")
    
    # 构建 RAGAS/HuggingFace 格式数据集
    eval_dataset = Dataset.from_dict(eval_data)

    # 开启 LangSmith 追踪 (RAGAS 评估过程也会同步到云端)
    os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT
    print(f"☁️  评估过程将归档至 LangSmith 项目: [{LANGSMITH_PROJECT}]")

    result = evaluate(
        dataset=eval_dataset,
        metrics=[
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall
        ],
        llm=judge_llm,
        embeddings=judge_embeddings,
        raise_exceptions=False
    )

    # 6. 输出结果并保存报告
    print("\n" + "="*50)
    print("📊 【CAE RAGAS 标准评测报告】")
    print(result)
    print("="*50)

    # 汇总报告
    # 适配新版本 EvaluationResult：直接从 result 中提取分数
    summary_data = {}
    try:
        # Ragas 结果对象通常可以直接以字典形式访问
        for m in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
            try:
                val = result[m]
                summary_data[m] = float(val)
            except:
                summary_data[m] = 0.0
    except Exception as e:
        print(f"⚠️ 提取汇总分数时遇到障碍: {e}")
    
    df_details = result.to_pandas()
    
    report = {
        "summary": summary_data,
        "details": df_details.to_dict(orient="records")
    }

    with open(EVAL_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=4)
    
    print(f"📂 详细得分报告已保存至 {EVAL_REPORT_PATH}")
    print(f"🔗 前往 LangSmith 查看评估采样详情。")

if __name__ == "__main__":
    run_evaluation()