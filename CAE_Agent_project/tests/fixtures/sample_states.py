"""示例状态数据 - 用于测试状态管理和工作流"""
from langchain_core.messages import HumanMessage, AIMessage


# ============ CAEAgentState 示例 ============

INITIAL_STATE = {
    "messages": [HumanMessage(content="我想做一个子弹冲击钢板的仿真")],
    "context_summary": "",
    "user_query": "我想做一个子弹冲击钢板的仿真",
    "selected_skill": "",
    "action_type": None,
    "consensus_params": {}
}

STATE_AFTER_PLANNER_CHAT = {
    "messages": [
        HumanMessage(content="子弹冲击需要什么材料参数？"),
        AIMessage(content="需要钢板的弹性模量、密度等参数")
    ],
    "context_summary": "",
    "user_query": "子弹冲击需要什么材料参数？",
    "selected_skill": "bullet_impact",
    "action_type": "chat",
    "consensus_params": {}
}

STATE_AFTER_PLANNER_SIMULATE = {
    "messages": [
        HumanMessage(content="我想做一个子弹冲击钢板的仿真"),
        AIMessage(content="请确认参数..."),
        HumanMessage(content="好的，就按这个参数开始仿真吧")
    ],
    "context_summary": "",
    "user_query": "好的，就按这个参数开始仿真吧",
    "selected_skill": "bullet_impact",
    "action_type": "simulate",
    "consensus_params": {
        "plate_thickness": 20.0,
        "bullet_radius": 20.0
    }
}


# ============ SimPipelineState 示例 ============

SIM_PIPELINE_INITIAL_STATE = {
    "messages": [HumanMessage(content="开始仿真")],
    "selected_skill": "bullet_impact",
    "consensus_params": {},
    "user_query": "开始仿真",
    "extracted_params": {},
    "generated_code": None,
    "script_path": None,
    "param_errors": None,
    "code_errors": None,
    "retry_count": 0,
    "error_log": None,
    "result_dir": None
}

SIM_PIPELINE_AFTER_EXTRACTOR = {
    "messages": [HumanMessage(content="开始仿真")],
    "selected_skill": "bullet_impact",
    "consensus_params": {},
    "user_query": "开始仿真",
    "extracted_params": {
        "status": "success",
        "message": "",
        "geometry": {
            "plate_length": 200.0,
            "plate_thickness": 20.0,
            "bullet_radius": 20.0
        },
        "material": {
            "density": 7.85e-9,
            "elastic_modulus": 210000.0
        },
        "physics": {
            "step_time": 0.01
        }
    },
    "generated_code": None,
    "script_path": None,
    "param_errors": None,
    "code_errors": None,
    "retry_count": 1,
    "error_log": None,
    "result_dir": None
}

SIM_PIPELINE_AFTER_CODER = {
    "messages": [HumanMessage(content="开始仿真")],
    "selected_skill": "bullet_impact",
    "consensus_params": {},
    "user_query": "开始仿真",
    "extracted_params": {
        "geometry": {"plate_thickness": 20.0},
        "material": {"elastic_modulus": 210000.0},
        "physics": {"step_time": 0.01}
    },
    "generated_code": "# Generated CAE script\nprint('test')",
    "script_path": "/tmp/test_script.py",
    "param_errors": None,
    "code_errors": None,
    "retry_count": 1,
    "error_log": None,
    "result_dir": None
}

SIM_PIPELINE_WITH_PARAM_ERROR = {
    "messages": [HumanMessage(content="开始仿真")],
    "selected_skill": "bullet_impact",
    "consensus_params": {},
    "user_query": "开始仿真",
    "extracted_params": {
        "geometry": {"plate_thickness": -5.0},  # 错误参数
    },
    "generated_code": None,
    "script_path": None,
    "param_errors": "错误：钢板厚度必须大于 0。",
    "code_errors": None,
    "retry_count": 1,
    "error_log": None,
    "result_dir": None
}

SIM_PIPELINE_WITH_CODE_ERROR = {
    "messages": [HumanMessage(content="开始仿真")],
    "selected_skill": "bullet_impact",
    "consensus_params": {},
    "user_query": "开始仿真",
    "extracted_params": {
        "geometry": {"plate_thickness": 20.0},
    },
    "generated_code": "",  # 空代码
    "script_path": "/tmp/empty_script.py",
    "param_errors": None,
    "code_errors": "生成的脚本文件内容异常（体积过小）",
    "retry_count": 1,
    "error_log": None,
    "result_dir": None
}


# ============ 带历史记忆的状态 ============

STATE_WITH_MEMORY = {
    "messages": [
        HumanMessage(content="第一个问题"),
        AIMessage(content="第一个回答"),
        HumanMessage(content="第二个问题"),
        AIMessage(content="第二个回答"),
        HumanMessage(content="第三个问题"),
    ],
    "context_summary": "用户之前询问了关于材料参数的问题",
    "user_query": "第三个问题",
    "selected_skill": "bullet_impact",
    "action_type": "chat",
    "consensus_params": {"plate_thickness": 20.0}
}
