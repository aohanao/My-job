"""单元测试 - 路由逻辑"""
import pytest
from core.state_graph.routing import (
    route_after_planner,
    route_after_extractor,
    route_after_coder
)


class TestRouteAfterPlanner:
    """测试Planner之后的路由决策"""

    def test_route_to_chat(self):
        """测试路由到Chat节点"""
        state = {"action_type": "chat"}
        result = route_after_planner(state)
        assert result == "Chat", "action_type为chat时应路由到Chat"

    def test_route_to_simulate(self):
        """测试路由到SimPipeline"""
        state = {"action_type": "simulate"}
        result = route_after_planner(state)
        assert result == "SimPipeline", "action_type为simulate时应路由到SimPipeline"

    def test_route_to_end_on_error(self):
        """测试错误时路由到End"""
        state = {"action_type": "error"}
        result = route_after_planner(state)
        assert result == "End", "action_type为error时应路由到End"

    def test_route_with_missing_action_type(self):
        """测试缺失action_type时默认路由到SimPipeline"""
        state = {}
        result = route_after_planner(state)
        assert result == "SimPipeline", "缺失action_type时应有默认行为"

    def test_route_with_none_action_type(self):
        """测试action_type为None"""
        state = {"action_type": None}
        result = route_after_planner(state)
        assert result == "SimPipeline", "action_type为None时应路由到SimPipeline"


class TestRouteAfterExtractor:
    """测试Extractor之后的路由决策

    当前实现为全自动模式：route_after_extractor 始终返回 'Coder'，
    不再根据 param_errors/retry_count 分叉。
    """

    def test_always_routes_to_coder(self):
        """全自动模式：无论任何状态都路由到Coder"""
        state = {"param_errors": None, "retry_count": 0}
        result = route_after_extractor(state)
        assert result == "Coder", "全自动模式应始终路由到Coder"

    def test_routes_to_coder_with_param_errors(self):
        """全自动模式：即使有参数错误也路由到Coder（错误由Extractor内部处理）"""
        state = {"param_errors": "错误：钢板厚度必须大于 0。", "retry_count": 1}
        result = route_after_extractor(state)
        assert result == "Coder", "全自动模式下param_errors不影响路由"

    def test_routes_to_coder_with_high_retry_count(self):
        """全自动模式：高重试次数也路由到Coder"""
        state = {"param_errors": "错误：参数无效", "retry_count": 99}
        result = route_after_extractor(state)
        assert result == "Coder", "全自动模式下retry_count不影响路由"

    def test_routes_to_coder_with_empty_state(self):
        """全自动模式：空状态也路由到Coder"""
        state = {}
        result = route_after_extractor(state)
        assert result == "Coder", "全自动模式下空状态应路由到Coder"

    def test_routes_to_coder_with_hitl_interrupt(self):
        """全自动模式：HITL_INTERRUPT标记也路由到Coder"""
        state = {"param_errors": "HITL_INTERRUPT", "retry_count": 1}
        result = route_after_extractor(state)
        assert result == "Coder", "全自动模式下HITL_INTERRUPT不触发中断路由"


class TestRouteAfterCoder:
    """测试Coder之后的路由决策"""

    def test_route_to_execute_on_success(self):
        """测试成功时路由到Execute"""
        state = {"code_errors": None}
        result = route_after_coder(state)
        assert result == "Execute", "代码校验通过时应路由到Execute"

    def test_route_to_retry_on_code_error(self):
        """测试代码错误时重试"""
        state = {"code_errors": "生成的脚本文件内容异常（体积过小）"}
        result = route_after_coder(state)
        assert result == "Retry", "代码错误时应重试"

    def test_route_with_empty_code_error(self):
        """测试空字符串错误（空字符串在Python中为False，视为无错误）"""
        state = {"code_errors": ""}
        result = route_after_coder(state)
        assert result == "Execute", "空字符串错误应视为无错误"

    def test_route_with_missing_code_errors(self):
        """测试缺失code_errors"""
        state = {}
        result = route_after_coder(state)
        assert result == "Execute", "缺失code_errors时应路由到Execute"


class TestRoutingIntegration:
    """测试路由逻辑的集成场景"""

    def test_full_success_path(self):
        """测试完整成功路径"""
        # Planner -> SimPipeline
        state = {"action_type": "simulate"}
        assert route_after_planner(state) == "SimPipeline"

        # Extractor -> Coder（全自动）
        state = {"param_errors": None, "retry_count": 0}
        assert route_after_extractor(state) == "Coder"

        # Coder -> Execute
        state = {"code_errors": None}
        assert route_after_coder(state) == "Execute"

    def test_coder_retry_path(self):
        """测试Coder阶段重试路径"""
        # Planner -> SimPipeline
        state = {"action_type": "simulate"}
        assert route_after_planner(state) == "SimPipeline"

        # Extractor -> Coder（全自动）
        state = {"param_errors": "参数错误", "retry_count": 1}
        assert route_after_extractor(state) == "Coder"

        # Coder -> Retry（代码校验失败）
        state = {"code_errors": "脚本文件内容异常"}
        assert route_after_coder(state) == "Retry"

    def test_chat_path(self):
        """测试聊天路径"""
        state = {"action_type": "chat"}
        assert route_after_planner(state) == "Chat"

    def test_error_path(self):
        """测试错误路径"""
        state = {"action_type": "error"}
        assert route_after_planner(state) == "End"
