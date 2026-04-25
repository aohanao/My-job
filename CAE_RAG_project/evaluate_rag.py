# evaluate_rag.py
import os
from langsmith import Client
from langchain.smith import RunEvalConfig, run_on_dataset
from rag import RagService
import config_data as config
from dotenv import load_dotenv

load_dotenv()

# 1. 初始化 LangSmith 客户端
client = Client()

# 2. 定制你的题库 (Dataset)
# 如果你已经在网页端创建了，可以直接用名字；这里我们演示代码创建
dataset_name = "CAE_Expert_Benchmark_v1"

if not client.has_dataset(dataset_name=dataset_name):
    dataset = client.create_dataset(
        dataset_name=dataset_name, 
        description="CAE 仿真专家系统基准测试集",
    )
    # 添加几道典型的测试题
    examples = [
        ("有限元分析中，C3D8R单元的优点是什么？", "减缩积分单元，计算效率高，能克服剪切自锁现象。"),
        ("什么是沙漏效应？", "减缩积分单元特有的一种零能变形模式，会导致结果不可信。"),
        ("如何解决接触计算不收敛？", "检查法向硬接触设置，尝试增加阻尼或调整载荷步。")
    ]
    for q, a in examples:
        client.create_example(
            inputs={"input": q}, 
            outputs={"answer": a}, 
            dataset_id=dataset.id
        )
    print(f"✅ 题库 {dataset_name} 创建并初始化完成！")

# 3. 定义“考官”逻辑 (Evaluator)
# 我们使用 LangChain 内置的 QA 评估器，它会自动比对模型回答和参考答案
eval_config = RunEvalConfig(
    evaluators=[
        "qa",           # 正确性评估：回答是否和参考答案意思一致
        "context_qa",   # 忠实度评估：回答是否基于检索到的文档内容
    ],
    prediction_key="output"
)

# 4. 执行评估任务
def run_benchmark():
    # 初始化你的 RAG 服务
    rag_service = RagService()
    
    # 构造待测的目标（即你的 RAG 链条）
    # 注意：这里我们包装一下输入，以便符合 LangSmith 的接口
    def target(inputs: dict):
        # 模拟 app.py 中的配置
        conf = {"configurable": {"session_id": "eval_test_001"}}
        # 调用流式之后的完整合并结果
        full_res = ""
        for chunk in rag_service.stream_with_cache(inputs, conf):
            # 过滤掉缓存提示词
            if "✨" not in chunk:
                full_res += chunk
        return {"output": full_res}

    print(f"🚀 正在针对 {dataset_name} 执行自动化评估...")
    
    # 启动评估流
    results = client.run_on_dataset(
        dataset_name=dataset_name,
        llm_or_chain_factory=target,
        evaluation=eval_config,
        project_name="CAE_RAG_Evaluation_v1", # 这是在 LangSmith 网页显示的测试项目名
        concurrency_level=1 # 建议设置较低，防止触发百炼 API 频率限制
    )
    
    print("\n" + "="*50)
    print("📈 评估已完成！")
    print(f"👉 请前往 LangSmith 官网查看项目 [CAE_RAG_Evaluation_v1] 的打分详情。")
    print("="*50)

if __name__ == "__main__":
    run_benchmark()
