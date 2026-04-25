---
skill_id: tunnel_support
name: 隧道工程开挖决策与支护设计
description: 处理钻爆法隧道的围岩类别判断、初期支护厚度推荐及锚杆长度设计等 CAE 前置决策逻辑。
skill_type: cae_simulation_expert
---

# 隧道工程技能 (Tunnel Support Skill)

本技能模块专为地下工程设计。它能够感知隧道工程的专业术语，并将其转化为 Abaqus 建模所需的几何与材料参数。

## 核心能力
- **围岩分类感应**：自动根据等级调整安全系数。
- **机械化推荐**：匹配适合当前工位的大型装备。

## 关联文件
- **Schema**: `schema.py` (定义物理量纲)
- **Validator**: `validator.py` (执行工程准则审计)
- **Prompt**: `references/prompt_instruction.md`
- **Macro**: `references/abaqus_macro.jinja2`
