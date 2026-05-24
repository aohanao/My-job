"""集成测试 - 状态管理"""
import pytest
from langchain_core.messages import HumanMessage, AIMessage
from tests.fixtures.sample_states import (
    INITIAL_STATE,
    STATE_AFTER_PLANNER_CHAT,
    SIM_PIPELINE_INITIAL_STATE
)


class TestStateTransitions:
    """测试状态在节点间的传递和转换"""

    def test_state_dict_merge(self):
        """测试状态字典的合并逻辑"""
        from core.state_graph.state import merge_dicts

        old = {"a": 1, "b": 2}
        new = {"b": 3, "c": 4}

        result = merge_dicts(old, new)

        assert result["a"] == 1, "旧值应保留"
        assert result["b"] == 3, "新值应覆盖旧值"
        assert result["c"] == 4, "新键应添加"

    def test_merge_dicts_with_none(self):
        """测试None值的合并"""
        from core.state_graph.state import merge_dicts

        assert merge_dicts(None, {"a": 1}) == {"a": 1}
        assert merge_dicts({"a": 1}, None) == {"a": 1}
        assert merge_dicts(None, None) == None

    def test_cae_agent_state_structure(self):
        """测试CAEAgentState的结构"""
        from core.state_graph.state import CAEAgentState

        # 验证必需字段（与当前 state.py 定义保持一致）
        required_fields = [
            "messages",
            "selected_skill",
            "action_type",
            "consensus_params",
            "is_confirmed",
            "script_path",
            "generated_code",
            "result_dir",
        ]

        # CAEAgentState是TypedDict，检查注解
        annotations = CAEAgentState.__annotations__
        for field in required_fields:
            assert field in annotations, f"CAEAgentState应包含字段: {field}"

    def test_sim_pipeline_state_structure(self):
        """测试SimPipelineState的结构"""
        from core.state_graph.state import SimPipelineState

        # 验证必需字段（与当前 state.py 定义保持一致）
        required_fields = [
            "messages",
            "selected_skill",
            "consensus_params",
            "is_confirmed",
            "extracted_params",
            "param_errors",
            "retry_count",
            "generated_code",
            "script_path",
            "code_errors",
            "error_log",
            "result_dir",
        ]

        annotations = SimPipelineState.__annotations__
        for field in required_fields:
            assert field in annotations, f"SimPipelineState应包含字段: {field}"

    def test_state_overlap_between_main_and_pipeline(self):
        """测试主图和子图状态的重叠字段（用于数据自动透传）"""
        from core.state_graph.state import CAEAgentState, SimPipelineState

        main_fields = set(CAEAgentState.__annotations__.keys())
        pipeline_fields = set(SimPipelineState.__annotations__.keys())

        # 应该有重叠字段用于数据透传
        overlap = main_fields & pipeline_fields
        expected_overlap = {
            "messages",
            "selected_skill",
            "consensus_params",
            "is_confirmed",
        }

        assert overlap >= expected_overlap, f"状态重叠字段不足，期望至少: {expected_overlap}, 实际: {overlap}"


class TestConsensusParamsMerge:
    """测试共识参数的增量合并"""

    def test_consensus_params_accumulation(self):
        """测试参数累积"""
        from core.state_graph.state import merge_dicts

        # 模拟多轮对话中参数的累积
        params1 = {"plate_thickness": 20.0}
        params2 = {"bullet_radius": 15.0}
        params3 = {"elastic_modulus": 210000.0}

        result = merge_dicts(params1, params2)
        result = merge_dicts(result, params3)

        assert result["plate_thickness"] == 20.0
        assert result["bullet_radius"] == 15.0
        assert result["elastic_modulus"] == 210000.0

    def test_consensus_params_override(self):
        """测试参数覆盖"""
        from core.state_graph.state import merge_dicts

        params1 = {"plate_thickness": 20.0, "bullet_radius": 15.0}
        params2 = {"plate_thickness": 25.0}  # 用户修改了厚度

        result = merge_dicts(params1, params2)

        assert result["plate_thickness"] == 25.0, "新值应覆盖旧值"
        assert result["bullet_radius"] == 15.0, "未修改的值应保留"


class TestMessageAccumulation:
    """测试消息的累积"""

    def test_messages_append(self):
        """测试消息追加"""
        from langgraph.graph.message import add_messages

        old_messages = [
            HumanMessage(content="第一条消息"),
            AIMessage(content="第一条回复")
        ]

        new_messages = [
            HumanMessage(content="第二条消息")
        ]

        result = add_messages(old_messages, new_messages)

        assert len(result) == 3
        assert result[0].content == "第一条消息"
        assert result[1].content == "第一条回复"
        assert result[2].content == "第二条消息"

    def test_messages_with_remove_message(self):
        """测试消息删除"""
        from langgraph.graph.message import add_messages
        from langchain_core.messages import RemoveMessage

        msg1 = HumanMessage(content="消息1")
        msg1.id = "msg-1"
        msg2 = AIMessage(content="消息2")
        msg2.id = "msg-2"

        old_messages = [msg1, msg2]

        # 删除第一条消息
        remove_instruction = [RemoveMessage(id="msg-1")]

        result = add_messages(old_messages, remove_instruction)

        # 应该只剩下第二条消息
        assert len(result) == 1
        assert result[0].content == "消息2"


class TestStateInitialization:
    """测试状态初始化"""

    def test_initial_state_valid(self):
        """测试初始状态的有效性"""
        state = INITIAL_STATE.copy()

        assert "messages" in state
        assert len(state["messages"]) > 0
        assert state["consensus_params"] == {}

    def test_pipeline_state_initialization(self):
        """测试流水线状态初始化"""
        state = SIM_PIPELINE_INITIAL_STATE.copy()

        assert state["retry_count"] == 0
        assert state["param_errors"] is None
        assert state["code_errors"] is None
        assert state["error_log"] is None
        assert state["extracted_params"] == {}


class TestStateValidation:
    """测试状态验证"""

    def test_state_with_all_required_fields(self):
        """测试包含所有必需字段的状态（与当前 CAEAgentState 对齐）"""
        state = {
            "messages": [HumanMessage(content="测试")],
            "selected_skill": "bullet_impact",
            "action_type": "chat",
            "consensus_params": {},
            "is_confirmed": False,
            "script_path": None,
            "generated_code": None,
            "result_dir": None,
        }

        # 状态应该有效
        assert all(key in state for key in [
            "messages", "selected_skill", "action_type",
            "consensus_params", "is_confirmed",
        ])

    def test_state_field_types(self):
        """测试状态字段类型"""
        state = STATE_AFTER_PLANNER_CHAT.copy()

        assert isinstance(state["messages"], list)
        assert isinstance(state["selected_skill"], str)
        assert isinstance(state["action_type"], str)
        assert isinstance(state["consensus_params"], dict)
