# 🏗️ CAE 技能插件中心 (Skills Registry)

本目录采用了“独立插件化”架构，每个子文件夹代表一个独立的 CAE 专业领域技能。

## 📁 技能目录结构范式
每一个技能包包含以下要素：

```text
skill_name/
├── skill.md                # 🌟 [必选] 技能元定义与 LLM 参数提取指令合一（YAML front-matter 定义元数据，正文为指令主体）
├── schema.py               # 🌟 [必选] Pydantic 物理量纲定义
├── validator.py            # 🌟 [必选] 工程校验核心逻辑
└── references/             # [必选] 技能私有附带品
    └── abaqus_macro.jinja2   # 🌟 专属的 Abaqus 脚本渲染模板
```

## 🚀 自动化挂载机制
1. **意图路由**：`core/state_graph/nodes/planner_node.py` 通过 `core/skills.py` 动态读取所有 `skill.md` 中的属性与触发词，将其配置给 Planner 大模型，自动路由到对应的 `skill_id`。
2. **动态提取**：`core/state_graph/nodes/extractor_node.py` 自动读取对应技能下的 `schema.py` 与 `skill.md` 中的参数提取指令。
3. **渲染生成**：`core/state_graph/nodes/coder_node.py` 会直接调用该技能目录下的 `references/abaqus_macro.jinja2` 进行代码合成。

---
> **增加新技能只需两步**：拷贝一个现有文件夹 ➔ 修改 `skill.md` 的元数据与指令 ➔ 修改 Schema 并编写 Jinja2 模板。无需改动 Core 引擎代码，系统完全自动识别挂载。
