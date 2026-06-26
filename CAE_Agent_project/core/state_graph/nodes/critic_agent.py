# core/state_graph/nodes/critic_agent.py
import os
import importlib
from langchain_core.messages import AIMessage, HumanMessage
from core.state_graph.state import SimPipelineState
from core.memory.long_term_experience import get_experience_manager
from core import config


def _run_param_validation(params, skill_name):
    """进行物理量纲与工程规则校验"""
    print("\n[CriticAgent] 正在进行物理量纲与工程规则校验...")
    try:
        module_path = f"skills.{skill_name}.validator"
        module = importlib.import_module(module_path)
        validate_func = getattr(module, "validate")
        error_msgs = validate_func(params)
        if error_msgs:
            final_error = " | ".join(error_msgs)
            print(f"[CriticAgent] ❌ 参数校验失败：{final_error}")
            return final_error
    except (ImportError, AttributeError):
        print(f"[CriticAgent] ⚠️ 未找到技能 {skill_name} 的验证器，跳过校验。")

    print("[CriticAgent] ✅ 参数校验通过！")
    return None


def critic_params_node(state: SimPipelineState):
    """评判智能体：参数校验分支"""
    print("\n[CriticAgent] === 启动参数校验 ===")
    
    # 前置检查：若大模型直接返回需要澄清（HIT_INTERRUPT），则无需本地规则校验，直接保持原状态
    if state.get("param_errors") == "HIT_INTERRUPT":
        return {"param_errors": "HIT_INTERRUPT"}

    extracted_params = state.get("extracted_params", {})
    current_skill = state.get("selected_skill", "未知")

    # 执行内联参数范围校验
    validation_error = _run_param_validation(extracted_params, current_skill)

    return {
        "param_errors": validation_error
    }


def _validate_script(script_path):
    """代码质量与物理宏指令基础完整性校验"""
    print("\n[CriticAgent] 正在校验生成的脚本文件...")

    if not script_path or not os.path.exists(script_path):
        return "未检测到生成的脚本文件或文件不存在"

    if os.path.getsize(script_path) < 50:
        return "生成的脚本文件内容异常（体积过小）"

    print(f"[CriticAgent] ✅ 脚本校验通过：{os.path.basename(script_path)}")
    return None


def critic_code_node(state: SimPipelineState):
    """评判智能体：生成脚本代码质量校验分支"""
    print("\n[CriticAgent] === 启动脚本代码校验 ===")
    script_path = state.get("script_path")

    # 基础脚本合法性校验
    code_error = _validate_script(script_path)

    return {
        "code_errors": code_error
    }


def critic_result_node(state: SimPipelineState):
    """评判智能体：仿真运行结果及物理发散性校验分支"""
    print("\n[CriticAgent] === 启动仿真结果评估 ===")
    error_log = state.get("error_log")
    script_path = state.get("script_path", "")
    script_name = os.path.basename(script_path) if script_path else "run_script.py"
    consensus_params = state.get("consensus_params", {})
    messages = state.get("messages", [])

    # 从历史消息中找出最开始的用户查询，用于经验存盘
    human_msgs = [m.content for m in messages if isinstance(m, HumanMessage)]
    user_query = human_msgs[0] if human_msgs else ""

    exp_manager = get_experience_manager()

    if error_log:
        # 1. 仿真运行或 TDD 校验报错：执行负反馈扣分与淘汰机制
        print(f"[CriticAgent] ❌ 仿真执行或 TDD 校验未通过，进行差评反馈以防记忆污染...")
        for doc_id in exp_manager.last_recalled_ids:
            exp_manager.feedback_memory(doc_id, is_positive=False)

        # 格式化精美的 Markdown 错误反馈消息
        if error_log.startswith("Connection Error"):
            error_msg = "无法建立与宿主机仿真网桥的物理连接"
            detail = error_log
            help_tip = "\n💡 **排查建议**：\n1. 请确认宿主机上已运行 `python integrations/cae_host_bridge/host_cae_bridge.py`。\n2. 检查网络连接及端口 5050 是否被占用。"
        else:
            parts = error_log.split(": ", 1)
            error_msg = parts[0]
            detail = parts[1] if len(parts) > 1 else "无详细日志"
            help_tip = "\n💡 **排查建议**: 请检查 G:\\...\\sandbox\\generated_scripts\\ 下脚本的物理参数或模型定义是否正确。"

        full_error_md = (
            f"❌ **仿真执行或网络通信失败**\n\n"
            f"**错误简述**: `{error_msg}`\n"
            f"**错误细节描述**:\n"
            f"```text\n{detail}\n```\n"
            f"{help_tip}"
        )
        return {
            "error_log": error_log,
            "messages": [AIMessage(content=full_error_md)]
        }
    else:
        # 2. 仿真成功完成：记入长期经验数据库，并进行正向反馈加分
        print(f"[CriticAgent] ✅ 仿真执行成功！正在将成功经验存盘入库...")
        exp_manager.engrave_success(
            user_query=user_query,
            skill=current_skill,
            consensus_params=consensus_params,
            script_name=script_name
        )

        for doc_id in exp_manager.last_recalled_ids:
            exp_manager.feedback_memory(doc_id, is_positive=True)

        success_msg = f"✅ 物理机 CAE 计算已完美收官！\n- 脚本名称: `{script_name}`\n- 运行状态: 求解成功并归档"
        return {
            "error_log": None,
            "messages": [AIMessage(content=success_msg)]
        }
