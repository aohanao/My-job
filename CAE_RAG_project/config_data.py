import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 1. 核心 API 配置 (优先从环境变量读取)
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# 2. LangSmith 可观测性配置验证
if os.getenv("LANGCHAIN_TRACING_V2") == "true":
    print(f"🚀 [可观测性] LangSmith 追踪已激活，项目: {os.getenv('LANGCHAIN_PROJECT', 'Default')}")
else:
    print("⚠️ [可观测性] LangSmith 追踪未开启，如需监控请在 .env 中设置 LANGCHAIN_TRACING_V2=true")

# 获取当前文件所在目录作为项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

md5_path = os.path.join(PROJECT_ROOT, "data/md5.text")

collection_name = "rag"
persist_directory = os.path.join(PROJECT_ROOT, "data/chroma_db")

chunk_size = 1000
chunk_overlap = 100
separators = ["\n\n", "\n", " ", ".", "。", "!", "！", "?", "？", "\n$$\n", "$$"]

max_spliter_char_number = 1000
similarity_threshold = 2

embedding_model = "text-embedding-v4"
chat_model = "qwen-turbo"
vlm_model = "qwen-vl-max"

session_config = {
    "configurable": {"session_id": "user_001"}
}