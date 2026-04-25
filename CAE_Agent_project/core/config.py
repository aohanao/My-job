import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 项目根目录 (当前在 core/，所以往上退一级得到根目录)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# API 配置
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY")
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen-turbo")

# 模型分级配置
PLANNER_MODEL = os.environ.get("PLANNER_MODEL", "qwen-turbo")    # 规划者：轻量、快速
EXTRACTOR_MODEL = os.environ.get("EXTRACTOR_MODEL", "qwen-plus") # 提取器：中等、稳定
CRITIC_MODEL = os.environ.get("CRITIC_MODEL", "qwen-plus")       # 校验器：逻辑严密
CODER_MODEL = os.environ.get("CODER_MODEL", "qwen-plus")         # 代码员：代码专项
CHAT_MODEL = os.environ.get("CHAT_MODEL", "qwen-turbo")          # 聊天节点配套
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-v4") # 向量模型

# Abaqus 配置
# 注意：在重构后的 HTTP Bridge 架构下，这些路径应当在宿主机的 bridge 脚本中配置。
# 这里的配置仅作为本地方向引导或降级方案使用。
ABAQUS_BAT_PATH = os.environ.get("ABAQUS_BAT_PATH", r"F:\SIMULIA\Commands\abaqus.bat")
ABAQUS_OUTPUT_DIR = os.environ.get("ABAQUS_OUTPUT_DIR", r"G:\Abaqus\agent_project")

# 沙盒与日志配置 (依然保持在项目根目录下)
SANDBOX_DIR = os.path.join(PROJECT_ROOT, "sandbox")
SCRIPTS_DIR = os.path.join(SANDBOX_DIR, "generated_scripts")
LOGS_DIR = os.path.join(SANDBOX_DIR, "run_logs")

# 确保文件夹存在
os.makedirs(SCRIPTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# 流程控制
MAX_PARAM_RETRY = int(os.environ.get("MAX_PARAM_RETRY", "3"))  # 参数提取最大重试次数

# 工具后端
TOOL_BACKEND = os.environ.get("TOOL_BACKEND", "local")
