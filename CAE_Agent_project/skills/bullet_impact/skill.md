---
skill_id: bullet_impact
name: 子弹高速冲击钢板仿真
description: 专门处理高速物体侵彻金属靶板的显式动力学场景，自动生成 Abaqus 对应的建模与分析步脚本。
skill_type: dynamic_cae_expert
---

# 子弹冲击技能 (Bullet Impact Skill)

本模块集成了高速冲击动力学的仿真模板。

## 核心能力
- **高速响应提取**：自动计算适合高速碰撞的分析步时间。
- **材料损伤建模**：内置常见的钢材损伤演化参数。

## 关联文件
- **Schema**: `schema.py`
- **Validator**: `validator.py`
- **Prompt**: `references/prompt_instruction.md`
- **Macro**: `references/abaqus_macro.jinja2`
