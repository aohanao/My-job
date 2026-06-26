# core/skill_harvester.py
import os
import json
import importlib.util
from langchain_core.messages import SystemMessage, HumanMessage
from core import config
from core.state_graph.node_utils import create_llm

HARVESTER_SYSTEM_PROMPT = """
你是一个高阶 CAE 智能体架构专家与技能封装中枢。
你的任务是接收用户提供的一个运行成功的 Abaqus/CAE 仿真 Python 脚本，分析其物理特性与参数，将其“参数化”并自动生成标准化、即插即用的智能体 Skill 插件包。

你要生成的 Skill 包含以下 5 个文件，必须全部打包进一个 JSON 中返回：

1. schema.py:
   - 使用 Pydantic 定义提取参数的骨架 Schema (SkillSchema)。
   - 骨架中必须包含 status (默认 "success") 和 message (默认 "") 字段。
   - 其他工程参数根据输入脚本的特性进行结构化分组定义（例如 GeometrySchema, MaterialSchema, PhysicsSchema 等）。
   - 每一个字段必须有 Field 定义，并写明详细 description 和 default。

2. validator.py:
   - 定义 validate(params: dict) -> list[str] 校验函数。
   - 接收 params 字典，检测参数的基本量纲、物理正负边界等。如果有不合规的参数，在列表中添加错误描述信息。无错则返回空列表。

3. tdd_test.py:
   - 定义 TDD 测试用例，包括三个函数：
     - test_parameters(params: dict): 参数的工程安全界限断言（如 `assert params['geometry']['plate_thickness'] >= 0.5`）。
     - test_code_structure(code_content: str): 接收渲染后的最终 Python 代码内容，断言关键的 Abaqus 命令、建模操作或模型结构是否存在（例如 `assert 'BaseSolidExtrude' in code_content`）。
       *【重要限制】：绝对不能对 `{{` 或 `}}` 字符进行断言（即不要包含任何形如 assert '{{ ... }}' in code_content 的语句）！* 因为 code_content 是渲染后的最终 Python 代码，所有的 Jinja2 占位符已经替换为了具体数值，因此断言占位符必定会失败！你应该断言数值所对应的变量名称（如 `assert 'bolt_length =' in code_content`）或者断言 Abaqus 的建模函数（如 `BaseSolidExtrude`）。
     - test_results(output_log: str): 物理结果及收敛性红线断言（如最大位移、沙漏能等）。

4. abaqus_macro.jinja2:
   - 将用户脚本中的硬编码数值替换为 Jinja2 占位符（例如：将几何定义中的长宽厚度替换为 `{{ geometry.plate_length }}`、`{{ geometry.plate_thickness }}`，注意参数路径需与 schema.py 匹配）。
   - 保留原 Python 脚本的所有复杂逻辑和 Abaqus 命令，只对需要由 Agent 动态控制的数值进行参数化。

5. skill.md:
   - 带有 YAML front-matter 的技能描述文件。
   - YAML 部分包含: skill_id, name, description, skill_type, trigger_conditions, few_shot_examples (提供至少 2 个用户输入到 JSON 参数提取的 Few-Shot 对齐示例)。
   - Markdown 部分包含技能的说明和提取指南，必须在主体中保留 {error_log} 占位符以支持自愈。

6. sample_params:
   - 一个符合你定义的 schema.py 结构的 dict，表示用于测试的一组有效参数值。

请严格返回符合 JSON Schema 的标准 JSON，不要有 ```json 等包裹，确保可以直接被 json.loads 解析。
格式要求如下：
{
  "schema_py": "Pydantic 源代码",
  "validator_py": "Validator 源代码",
  "tdd_test_py": "TDD 测试用例源代码",
  "abaqus_macro_jinja2": "Jinja2 模板源代码",
  "skill_md": "Markdown 技能描述源代码",
  "sample_params": { ... }
}
"""

def harvest_new_skill(
    script_content: str, 
    skill_id: str, 
    skill_name: str, 
    description: str
) -> dict:
    """
    TDD-QA 技能自动沉淀核心引擎：接收已通过测试的仿真脚本，自动封装为标准 Skill 插件并部署
    """
    print(f"\n[SkillHarvester] 🚀 开始为新仿真业务沉淀 Skill: {skill_id} ({skill_name}) ...")
    
    # 1. 使用公共工厂 create_llm 建立模型连接
    llm = create_llm(model=config.CRITIC_MODEL, temperature=0.1)
    llm = llm.bind(response_format={"type": "json_object"})
    
    user_prompt = (
        f"请对以下仿真脚本进行分析，并将其封装为 ID 为 '{skill_id}'、"
        f"名称为 '{skill_name}'、描述为 '{description}' 的 Skill 插件。\n\n"
        f"--- 原始 Python 仿真脚本 ---\n"
        f"{script_content}\n"
    )
    
    try:
        messages = [
            SystemMessage(content=HARVESTER_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt)
        ]
        response = llm.invoke(messages)
        res_json = json.loads(response.content)
    except Exception as e:
        print(f"[SkillHarvester] ❌ 大模型解析生成失败: {e}")
        return {"status": "error", "message": f"LLM Generation failed: {str(e)}"}

    # 2. 本地虚拟运行测试与反思自愈 (TDD QA 闭环)
    # 在写入 skills/ 目录前，先在临时目录校验生成的 schema/validator/tdd_test 的自洽性
    import tempfile
    import shutil
    
    temp_dir = tempfile.mkdtemp()
    try:
        # 写入临时文件
        with open(os.path.join(temp_dir, "schema.py"), "w", encoding="utf-8") as f:
            f.write(res_json["schema_py"])
        with open(os.path.join(temp_dir, "validator.py"), "w", encoding="utf-8") as f:
            f.write(res_json["validator_py"])
        with open(os.path.join(temp_dir, "tdd_test.py"), "w", encoding="utf-8") as f:
            f.write(res_json["tdd_test_py"])
            
        print("[SkillHarvester][TDD-QA] 正在对自动生成的 Skill 组件进行本地自洽性校验...")
        
        # 2.1 校验 validator.py 与 sample_params 是否兼容
        spec_val = importlib.util.spec_from_file_location("temp_val", os.path.join(temp_dir, "validator.py"))
        temp_val = importlib.util.module_from_spec(spec_val)
        spec_val.loader.exec_module(temp_val)
        
        sample_params = res_json["sample_params"]
        val_errors = temp_val.validate(sample_params)
        if val_errors:
            raise AssertionError(f"validator 验证 sample_params 报错: {val_errors}")
            
        # 2.2 校验 tdd_test.py 的参数断言是否能通过
        spec_tdd = importlib.util.spec_from_file_location("temp_tdd", os.path.join(temp_dir, "tdd_test.py"))
        temp_tdd = importlib.util.module_from_spec(spec_tdd)
        spec_tdd.loader.exec_module(temp_tdd)
        
        # 运行参数 TDD 校验
        temp_tdd.test_parameters(sample_params)
        
        # 渲染 Jinja2 模板，校验代码结构 TDD 校验
        from jinja2 import Template
        template_obj = Template(res_json["abaqus_macro_jinja2"])
        rendered_code = template_obj.render(**sample_params)
        temp_tdd.test_code_structure(rendered_code)
        
        print("[SkillHarvester][TDD-QA] 🎉 本地 TDD 闭环校验 100% 通过！")
        
    except Exception as e:
        print(f"[SkillHarvester][TDD-QA] ❌ 自动封装自洽性验证失败: {e}")
        shutil.rmtree(temp_dir)
        return {"status": "error", "message": f"TDD self-validation failed: {str(e)}"}
        
    shutil.rmtree(temp_dir)

    # 3. 部署 Skill 到 skills 库
    target_skill_dir = os.path.join(config.PROJECT_ROOT, "skills", skill_id)
    os.makedirs(target_skill_dir, exist_ok=True)
    os.makedirs(os.path.join(target_skill_dir, "references"), exist_ok=True)
    
    try:
        with open(os.path.join(target_skill_dir, "schema.py"), "w", encoding="utf-8") as f:
            f.write(res_json["schema_py"])
        with open(os.path.join(target_skill_dir, "validator.py"), "w", encoding="utf-8") as f:
            f.write(res_json["validator_py"])
        with open(os.path.join(target_skill_dir, "tdd_test.py"), "w", encoding="utf-8") as f:
            f.write(res_json["tdd_test_py"])
        with open(os.path.join(target_skill_dir, "skill.md"), "w", encoding="utf-8") as f:
            f.write(res_json["skill_md"])
        with open(os.path.join(target_skill_dir, "references", "abaqus_macro.jinja2"), "w", encoding="utf-8") as f:
            f.write(res_json["abaqus_macro_jinja2"])
            
        print(f"[SkillHarvester] 💾 技能 '{skill_id}' 已成功自动沉淀部署至 skills/ 库！")
        
        # 4. 清除技能缓存，使主 Planner 立即识别该新技能
        from core import skills
        skills._skills_cache = None
        skills.load_skills(force_reload=True)
        print("[SkillHarvester] 🔄 已刷新全局 Skill 缓存。")
        
        return {
            "status": "success",
            "message": f"Skill '{skill_id}' successfully harvested and registered.",
            "skill_id": skill_id
        }
    except Exception as e:
        print(f"[SkillHarvester] ❌ 部署技能写入磁盘失败: {e}")
        return {"status": "error", "message": f"Failed to deploy skill: {str(e)}"}
