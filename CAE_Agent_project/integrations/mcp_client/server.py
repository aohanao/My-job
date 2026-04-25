import os
import json
from langchain_core.tools import tool

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

@tool
def lookup_cae_knowledge(query: str) -> str:
    """
    查询 CAE 工程规范与材料参数数据库。
    当需要围岩等级、材料弹性模量、泊松比、密度、粘聚力、摩擦角等任何材料或
    工程参数时，必须调用此工具。直接传入自然语言描述即可，无需精确名称。
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
