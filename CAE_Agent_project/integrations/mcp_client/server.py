import os
import json
from langchain_core.tools import tool

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

@tool
def lookup_local_material_db(query: str) -> str:
    """
    快速查询本地材料参数速查表（小型 JSON 数据库）。
    仅包含常见围岩等级、混凝土标号、钢筋型号的基础力学参数（弹性模量、泊松比、密度等）。
    适合简单的参数数值速查。如果需要查询工程规范、施工流程、设计标准等深层知识，
    请使用 lookup_cae_knowledge 工具。
    示例输入: "V级围岩的参数", "C30混凝土弹性模量", "HPB300钢密度"
    """
    db_path = os.path.join(_CURRENT_DIR, "material_db.json")
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except FileNotFoundError:
        return json.dumps({"error": f"未找到材料库文件: {db_path}"}, ensure_ascii=False)

    query_lower = query.lower()

    # 模糊匹配：只要 query 中包含 key 的关键字，就返回对应记录
    matched_results = {}
    for key, value in db.items():
        # 双向匹配：query 包含 key 关键词，或 key 包含 query 关键词
        key_lower = key.lower()
        if any(kw in query_lower for kw in key_lower.split()) or \
           any(kw in key_lower for kw in query_lower.split()):
            matched_results[key] = value

    if not matched_results:
        # 没有精确匹配时，返回全部，让 LLM 自己推断
        result = {
            "tip": "未找到精确匹配，以下是数据库全部内容，请自行参考",
            "all_data": db
        }
    else:
        result = matched_results

    return json.dumps(result, ensure_ascii=False, indent=2)
