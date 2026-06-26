"""
core/skills.py — Skill 注册中心 + 装饰器系统

提供两个核心能力：
1. load_skills() / get_skill()：动态扫描 skills/ 目录，解析 YAML front-matter
2. @skill 装饰器：将 CAE 核心业务函数标注为 Skill，自动注入 Few-Shot 示例
   并在 Prompt 构建时提升 LLM 的参数提取准确率。
"""
import os
import yaml
from functools import wraps
from core import config

_skills_cache = None


# ─────────────────────────────────────────────
# 1. Skill 文件解析
# ─────────────────────────────────────────────

def parse_skill_markdown(file_path):
    """
    解析带有 YAML front-matter 的 skill.md 文件。
    返回: (metadata_dict, markdown_body_str)
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 去除 BOM 字符并清理首部空白
    if content.startswith("\ufeff"):
        content = content[1:]
        
    stripped_content = content.lstrip()
    if stripped_content.startswith("---"):
        parts = stripped_content.split("---", 2)
        if len(parts) >= 3:
            try:
                metadata = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
                return metadata, body
            except Exception as e:
                print(f"[Skills] 警告: 无法解析 {file_path} 中的 YAML front-matter: {e}")
                
    return {}, content.strip()


def load_skills(force_reload=False):
    """
    动态扫描 skills 目录下的所有技能，解析其 skill.md。
    返回: dict[skill_id, skill_info]
    
    skill_info 结构：
      - skill_id, name, description, skill_type
      - trigger_conditions: list[str]
      - prompt_instruction: str（Markdown body，可含 {error_log} 占位符）
      - few_shot_examples: list[{"user": str, "assistant": str}]
      - skill_dir: str
    """
    global _skills_cache
    if _skills_cache is not None and not force_reload:
        return _skills_cache

    skills = {}
    skills_dir = os.path.join(config.PROJECT_ROOT, "skills")
    if not os.path.exists(skills_dir):
        _skills_cache = skills
        return skills

    for item in os.listdir(skills_dir):
        item_path = os.path.join(skills_dir, item)
        if os.path.isdir(item_path):
            skill_md_path = os.path.join(item_path, "skill.md")
            if os.path.exists(skill_md_path):
                metadata, body = parse_skill_markdown(skill_md_path)
                skill_id = metadata.get("skill_id") or item
                skills[skill_id] = {
                    "skill_id": skill_id,
                    "name": metadata.get("name", skill_id),
                    "description": metadata.get("description", ""),
                    "skill_type": metadata.get("skill_type", ""),
                    "trigger_conditions": metadata.get("trigger_conditions", []),
                    "prompt_instruction": body,
                    # ✨ 新增：从 YAML front-matter 中加载 Few-Shot 示例
                    "few_shot_examples": metadata.get("few_shot_examples", []),
                    "skill_dir": item_path
                }
    
    _skills_cache = skills
    return skills


def get_skill(skill_id):
    """获取指定 ID 的技能信息"""
    return load_skills().get(skill_id)


# ─────────────────────────────────────────────
# 2. @skill 装饰器
# ─────────────────────────────────────────────

def build_few_shot_block(examples: list) -> str:
    """
    将 few_shot_examples 列表渲染为可插入 Prompt 的文本块。
    格式：
        ### 参考示例 (Few-Shot)
        [示例 1]
        用户：...
        输出：...
    """
    if not examples:
        return ""
    
    lines = ["\n### 参考示例 (Few-Shot)"]
    lines.append("以下是标准参数提取的示例，请严格参考格式：\n")
    for i, ex in enumerate(examples, 1):
        lines.append(f"[示例 {i}]")
        lines.append(f"用户：{ex.get('user', '')}")
        lines.append(f"输出：{ex.get('assistant', '').strip()}")
        lines.append("")
    return "\n".join(lines)


def skill(skill_id: str):
    """
    Skill 装饰器。

    作用：
    - 将被装饰的节点函数（通常是 extractor_node）与指定 Skill 绑定
    - 在调用时自动读取该 Skill 的 few_shot_examples，拼接到 system_prompt 末尾
    - 通过 kwargs["_few_shot_block"] 将渲染好的 Few-Shot 文本传递给节点

    用法：
        @skill("bullet_impact")
        async def extractor_node(state, tools=None, _few_shot_block=""):
            ...

    注意：若节点函数不接受 _few_shot_block，装饰器会静默跳过注入（向后兼容）。
    """
    def decorator(fn):
        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            skill_info = get_skill(skill_id)
            if skill_info:
                examples = skill_info.get("few_shot_examples", [])
                few_shot_block = build_few_shot_block(examples)
            else:
                few_shot_block = ""
                print(f"[skill decorator] ⚠️ 未找到 skill_id={skill_id} 的定义")
            
            # 只在函数签名支持该参数时才注入，保证向后兼容
            import inspect
            sig = inspect.signature(fn)
            if "_few_shot_block" in sig.parameters:
                kwargs["_few_shot_block"] = few_shot_block
            
            return await fn(*args, **kwargs)

        @wraps(fn)
        def sync_wrapper(*args, **kwargs):
            skill_info = get_skill(skill_id)
            if skill_info:
                examples = skill_info.get("few_shot_examples", [])
                few_shot_block = build_few_shot_block(examples)
            else:
                few_shot_block = ""
            
            import inspect
            sig = inspect.signature(fn)
            if "_few_shot_block" in sig.parameters:
                kwargs["_few_shot_block"] = few_shot_block
            
            return fn(*args, **kwargs)

        import asyncio
        import inspect
        if inspect.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper

    return decorator
