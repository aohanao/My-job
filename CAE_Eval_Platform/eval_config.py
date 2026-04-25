# CAE_Eval_Platform 专属配置文件
# 独立于业务系统的配置，保证评测时的纯净性

import os
from dotenv import load_dotenv, find_dotenv

# 加载当前目录或上层目录的 .env 文件
load_dotenv(find_dotenv())

# 1. 评测专门指定的模型型号 (通常裁判模型应当采用最强版本)
# 优先从环境变量读取，实现配置与代码的分离
EVAL_JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "qwen-max")
EVAL_EMBEDDING_MODEL = os.getenv("EVAL_EMBEDDING_MODEL", "text-embedding-v4")

# 2. 评测数据库路径
DB_PATH = os.getenv("EVAL_DB_PATH", os.path.join(os.path.dirname(__file__), "traces.db"))
