import os
import yaml
from core import config

_skills_cache = None


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
                    "skill_dir": item_path
                }
    
    _skills_cache = skills
    return skills


def get_skill(skill_id):
    """获取指定 ID 的技能信息"""
    return load_skills().get(skill_id)
