# core/state_graph/nodes/extractor_node.py
import os
import importlib
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.prompts import PromptTemplate
from core.state_graph.state import SimPipelineState
from core.state_graph.node_utils import get_memory_window, create_llm, merge_tools
from integrations.mcp_client.provider import get_material_lookup_tool
from core import config

# 初始化工具
material_lookup_tool = get_material_lookup_tool()

# 使用公共 LLM 工厂
llm = create_llm(model=config.EXTRACTOR_MODEL, temperature=0.1)


def _run_param_validation(params, skill_name):
    """内联的参数校验逻辑（原 param_validator_node）"""
    print("\n[Extractor] 正在进行物理量纲与工程规则校验...")
    try:
        module_path = f"skills.{skill_name}.validator"
        module = importlib.import_module(module_path)
        validate_func = getattr(module, "validate")
        error_msgs = validate_func(params)
        if error_msgs:
            final_error = " | ".join(error_msgs)
            print(f"[Extractor] ❌ 参数校验失败：{final_error}")
            return final_error
    except (ImportError, AttributeError):
        print(f"[Extractor] ⚠️ 未找到技能 {skill_name} 的验证器，跳过校验。")

    print("[Extractor] ✅ 参数校验通过！")
    return None


async def extractor_node(state: SimPipelineState, tools=None):
    """参数提取 + 校验一体化节点（合并了原 ParamValidator）"""
    try:
        memory_window = get_memory_window(state)

        print(f"\n[Extractor] 正在调用大模型大脑...")

        current_skill = state.get("selected_skill", "未知")
        param_errors = state.get("param_errors")

        # 🌟 路径重构：技能现在在 skills 目录下有更清晰的结构
        skill_dir = os.path.join(config.PROJECT_ROOT, "skills", current_skill)

        # 1. 动态加载该技能专属的 Pydantic 类 (SkillSchema)
        try:
            module_path = f"skills.{current_skill}.schema"
            module = importlib.import_module(module_path)
            DynamicSchema = getattr(module, "SkillSchema")
        except Exception as e:
            print(f"\n[Extractor] ❌ 无法加载 Schema: {e}")
            return {"param_errors": f"Schema加载失败: {e}"}

        # 2. 读取技能专属的提示词指令
        try:
            instruction_path = os.path.join(skill_dir, "references", "prompt_instruction.md")
            with open(instruction_path, "r", encoding="utf-8") as f:
                template_str = f.read()
        except FileNotFoundError:
            return {"param_errors": f"技能指令文件丢失"}

        # 3. 组装 System Prompt
        prompt_engine = PromptTemplate(
            template=template_str,
            input_variables=["error_log"]
        )
        final_system_prompt = prompt_engine.format(
            error_log=f"纠正建议：{param_errors}" if param_errors else "无"
        )

        current_consensus = state.get("consensus_params", {})
        if current_consensus:
            final_system_prompt += f"\n\n【核心共识池数据】\n{current_consensus}\n请优先采用这些数据。"

        # 🌟 注入压缩后的早期上下文记忆，防止失忆
        short_term_memory = state.get("context_summary", "")
        if short_term_memory:
            final_system_prompt += f"\n\n【已被归档压缩的早期历史背景与参数约束】：\n{short_term_memory}"

        messages = [SystemMessage(content=final_system_prompt)] + memory_window

        # 4. 工具循环（使用公共 merge_tools）
        active_tools, tools_by_name = merge_tools([material_lookup_tool], tools)
        llm_with_tools = llm.bind_tools(active_tools)

        for _ in range(3):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)
            if not response.tool_calls:
                break

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                if tool_name in tools_by_name:
                    print(f"\n[Extractor] 🔌 触发了工具调用: {tool_name}")
                    tool_instance = tools_by_name[tool_name]
                    try:
                        tool_result = await tool_instance.ainvoke(tool_args)
                    except Exception as e:
                        tool_result = f"工具异常: {e}"

                    messages.append(ToolMessage(
                        tool_call_id=tool_call["id"],
                        name=tool_name,
                        content=str(tool_result)
                    ))

        # 5. 调用大模型，强制输出结构化对象
        structured_llm = llm.with_structured_output(DynamicSchema)
        extracted_obj = await structured_llm.ainvoke(messages)
        extracted_data = extracted_obj.dict() if hasattr(extracted_obj, "dict") else extracted_obj

        # 6. 处理追问和返回逻辑
        status = extracted_data.get("status", "success")
        if status == "need_clarification":
            return {"param_errors": "HIT_INTERRUPT"}

        # 7. 内联参数校验（原 ParamValidator 逻辑）
        validation_error = _run_param_validation(extracted_data, current_skill)

        print(f"[Extractor] 📤 确认数据已准备就绪，即将提交至路由引擎...")
        
        return {
            "extracted_params": extracted_data,
            "consensus_params": extracted_data,
            "retry_count": state.get("retry_count", 0) + 1,
            "param_errors": validation_error,  
            "is_confirmed": False
        }
    except Exception as e:
        print(f"\n[Extractor] 💥 发生致命错误: {e}")
        import traceback
        traceback.print_exc()
        raise e
