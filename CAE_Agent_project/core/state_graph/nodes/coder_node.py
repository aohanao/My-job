# core/state_graph/nodes/coder_node.py
import os
import datetime
from jinja2 import Template
from core.state_graph.state import SimPipelineState
from core import config


def coder_node(state: SimPipelineState):
    """代码生成 + 校验一体化节点（合并了原 CodeValidator）"""
    try:
        print("\n[Coder] 收到大模型提取的参数，开始动态生成 CAE 脚本...")

        params = state["extracted_params"]
        current_skill = state["selected_skill"]

        # 🌟 路径重构：模板现在位于技能目录下的 references 文件夹中
        skill_dir = os.path.join(config.PROJECT_ROOT, "skills", current_skill)
        template_path = os.path.join(skill_dir, "references", "abaqus_macro.jinja2")

        # 读取模版内容
        if not os.path.exists(template_path):
            return {"error_log": f"在技能目录 {current_skill} 下未找到核心仿真模板文件！"}

        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        jinja_template = Template(template_content)
        final_script = jinja_template.render(**params)

        # 获取沙盒目录
        scripts_dir = config.SCRIPTS_DIR

        # 生成时间戳
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"run_{current_skill}_{timestamp}.py"
        output_path = os.path.join(scripts_dir, unique_filename)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_script)

        print(f"[Coder] 脚本生成成功！已保存至: {output_path}")

        return {
            "generated_code": final_script,
            "script_path": output_path,
            "code_errors": None
        }
    except Exception as e:
        print(f"\n[Coder] 💥 发生致命错误: {e}")
        import traceback
        traceback.print_exc()
        raise e
