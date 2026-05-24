"""单元测试 - 路由逻辑"""
import pytest
from core.state_graph.routing import (
    route_after_planner,
    route_after_extractor,
    route_after_coder,
    route_after_executor
)


class TestRouteAfterPlanner:
    """测试Planner之后的路由决策"""

    def test_route_to_chat(self):
        """测试路由到Chat节点"""
        state = {"action_type": "chat"}
        assert route_after_planner(state) == "Chat"

    def test_route_to_simulate(self):
        """测试路由到SimPipeline"""
        state = {"action_type": "simulate"}
        assert route_after_planner(state) == "SimPipeline"

    def test_route_to_end_on_error(self):
        """测试错误时路由到End"""
        state = {"action_type": "error"}
        assert route_after_planner(state) == "End"


class TestRouteAfterExtractor:
    """测试Extractor之后的路由决策"""

    def test_routes_to_coder_when_no_errors(self):
        """测试正常时路由到Coder"""
        state = {"param_errors": None, "retry_count": 0}
        result = route_after_extractor(state)
        assert result == "Coder", "没有参数错误时应路由到Coder"

    def test_routes_to_extractor_with_param_errors(self):
        """测试有参数错误且未超限时重试"""
        state = {"param_errors": "错误：钢板厚度必须大于 0。", "retry_count": 1}
        result = route_after_extractor(state)
        assert result == "Extractor", "有参数错误且重试未超限应路由到Extractor"

    def test_routes_to_coder_with_high_retry_count(self):
        """测试重试次数超限后强行路由到Coder"""
        state = {"param_errors": "错误：参数无效", "retry_count": 3}
        result = route_after_extractor(state)
        assert result == "Coder", "重试次数超限后应路由到Coder"

    def test_routes_to_coder_with_empty_state(self):
        """测试空状态默认路由到Coder"""
        state = {}
        result = route_after_extractor(state)
        assert result == "Coder", "空状态应路由到Coder"

    def test_routes_to_waithuman_with_hit_interrupt(self):
        """测试需要人工澄清时路由到WaitHuman"""
        state = {"param_errors": "HIT_INTERRUPT", "retry_count": 1}
        result = route_after_extractor(state)
        assert result == "WaitHuman", "HIT_INTERRUPT标记应路由到WaitHuman"


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


class TestRouteAfterExecutor:
    """测试Executor之后的路由决策"""

    def test_routes_to_end_on_success(self):
        """测试无错误时路由到End"""
        state = {"error_log": None, "retry_count": 0}
        assert route_after_executor(state) == "End"

    def test_routes_to_reextract_on_error(self):
        """测试有执行错误时折返自愈"""
        state = {"error_log": "求解中途发生崩溃", "retry_count": 1}
        assert route_after_executor(state) == "ReExtract"

    def test_routes_to_end_on_high_retry_error(self):
        """测试有错误但重试超限时路由到End"""
        state = {"error_log": "求解中途发生崩溃", "retry_count": 3}
        assert route_after_executor(state) == "End"


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

        # Extractor -> Coder
        state = {"param_errors": None, "retry_count": 0}
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
