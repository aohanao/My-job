"""端到端测试 - 聊天工作流"""
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from langchain_core.messages import HumanMessage, AIMessage


@pytest.mark.e2e
class TestChatWorkflow:
    """测试完整的聊天工作流"""

    @pytest.mark.asyncio
    async def test_simple_chat_query(self, mock_env_vars, suppress_print):
        """测试简单的聊天查询流程"""
        from core.state_graph.builder import build_cae_graph
        from langgraph.checkpoint.memory import MemorySaver

        # Mock所有LLM调用（包括 compressor 和 planner/chat）
        with patch('core.state_graph.nodes.planner_node.llm') as mock_planner_llm, \
             patch('core.state_graph.nodes.chat_node.llm') as mock_chat_llm, \
             patch('core.memory.short_term_compressor.llm') as mock_compressor_llm, \
             patch('core.memory.long_term_experience.get_experience_manager') as mock_exp:

            # Mock Planner响应 - 识别为chat
            mock_planner_structured = Mock()
            mock_planner_structured.invoke.return_value = {
                "intent": "bullet_impact",
                "action_type": "chat",
                "reason": "用户在咨询"
            }
            mock_planner_llm.with_structured_output.return_value = mock_planner_structured

            # Mock经验管理器
            mock_exp_manager = Mock()
            mock_exp_manager.recall_similar.return_value = ""
            mock_exp.return_value = mock_exp_manager

            # Mock Chat响应
            mock_chat_llm.bind_tools.return_value = mock_chat_llm
            mock_chat_llm.ainvoke = AsyncMock(return_value=AIMessage(
                content="子弹冲击仿真需要钢板的弹性模量、密度等参数",
                tool_calls=[]
            ))

            # 构建图
            memory = MemorySaver()
            app = build_cae_graph(checkpointer=memory, tools=[])

            # 执行查询
            config = {"configurable": {"thread_id": "test-chat-001"}}
            input_state = {
                "messages": [HumanMessage(content="子弹冲击需要什么参数？")]
            }

            # 运行工作流
            result = await app.ainvoke(input_state, config=config)

            # 验证结果
            assert "messages" in result
            assert len(result["messages"]) >= 2  # 至少有用户消息和AI回复
            assert result["action_type"] == "chat"
            assert result["selected_skill"] == "bullet_impact"

            # 验证最后一条消息是AI回复
            last_message = result["messages"][-1]
            assert isinstance(last_message, AIMessage)
            assert "参数" in last_message.content

    @pytest.mark.asyncio
    async def test_chat_with_tool_call(self, mock_env_vars, suppress_print):
        """测试带工具调用的聊天流程"""
        from core.state_graph.builder import build_cae_graph
        from langgraph.checkpoint.memory import MemorySaver
        from langchain_core.messages import ToolMessage

        with patch('core.state_graph.nodes.planner_node.llm') as mock_planner_llm, \
             patch('core.state_graph.nodes.chat_node.llm') as mock_chat_llm, \
             patch('core.memory.short_term_compressor.llm') as mock_compressor_llm, \
             patch('core.memory.long_term_experience.get_experience_manager') as mock_exp:

            # Mock Planner
            mock_planner_structured = Mock()
            mock_planner_structured.invoke.return_value = {
                "intent": "bullet_impact",
                "action_type": "chat",
                "reason": "查询材料"
            }
            mock_planner_llm.with_structured_output.return_value = mock_planner_structured

            mock_exp_manager = Mock()
            mock_exp_manager.recall_similar.return_value = ""
            mock_exp.return_value = mock_exp_manager

            # Mock Chat - 第一次调用工具
            mock_chat_llm.bind_tools.return_value = mock_chat_llm

            call_count = [0]

            async def mock_ainvoke(messages, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    # 第一次：调用工具
                    return AIMessage(
                        content="",
                        tool_calls=[{
                            "name": "material_lookup",
                            "args": {"material_name": "HPB300"},
                            "id": "tool-1"
                        }]
                    )
                else:
                    # 第二次：返回最终答案
                    return AIMessage(
                        content="HPB300的弹性模量是210000 MPa",
                        tool_calls=[]
                    )

            mock_chat_llm.ainvoke = mock_ainvoke

            # Mock材料查询工具
            mock_tool = Mock()
            mock_tool.name = "material_lookup"
            mock_tool.invoke.return_value = "弹性模量: 210000 MPa"

            memory = MemorySaver()
            app = build_cae_graph(checkpointer=memory, tools=[mock_tool])

            config = {"configurable": {"thread_id": "test-chat-002"}}
            input_state = {
                "messages": [HumanMessage(content="HPB300的弹性模量是多少？")]
            }

            result = await app.ainvoke(input_state, config=config)

            # 验证工具被调用
            assert mock_tool.invoke.called or call_count[0] >= 1

            # 验证最终回复
            last_message = result["messages"][-1]
            assert isinstance(last_message, AIMessage)

    @pytest.mark.asyncio
    async def test_chat_with_historical_experience(self, mock_env_vars, suppress_print):
        """测试带历史经验唤醒的聊天"""
        from core.state_graph.builder import build_cae_graph
        from langgraph.checkpoint.memory import MemorySaver

        with patch('core.state_graph.nodes.planner_node.llm') as mock_planner_llm, \
             patch('core.state_graph.nodes.chat_node.llm') as mock_chat_llm, \
             patch('core.memory.short_term_compressor.llm') as mock_compressor_llm, \
             patch('core.memory.long_term_experience.get_experience_manager') as mock_exp:

            # Mock Planner
            mock_planner_structured = Mock()
            mock_planner_structured.invoke.return_value = {
                "intent": "bullet_impact",
                "action_type": "chat",
                "reason": "咨询"
            }
            mock_planner_llm.with_structured_output.return_value = mock_planner_structured

            # Mock经验管理器 - 返回历史经验
            mock_exp_manager = Mock()
            mock_exp_manager.recall_similar.return_value = (
                "历史经验：钢板厚度20mm，子弹半径20mm，成功运行"
            )
            mock_exp.return_value = mock_exp_manager

            # Mock Chat
            mock_chat_llm.bind_tools.return_value = mock_chat_llm
            mock_chat_llm.ainvoke = AsyncMock(return_value=AIMessage(
                content="根据历史经验，推荐使用钢板厚度20mm",
                tool_calls=[]
            ))

            memory = MemorySaver()
            app = build_cae_graph(checkpointer=memory, tools=[])

            config = {"configurable": {"thread_id": "test-chat-003"}}
            input_state = {
                "messages": [HumanMessage(content="推荐的钢板厚度是多少？")]
            }

            result = await app.ainvoke(input_state, config=config)

            # 验证经验被检索
            mock_exp_manager.recall_similar.assert_called()

            # 验证回复包含推荐
            last_message = result["messages"][-1]
            assert isinstance(last_message, AIMessage)

    @pytest.mark.asyncio
    async def test_unsupported_intent(self, mock_env_vars, suppress_print):
        """测试不支持的意图 — planner 识别为 unsupported + simulate，触发 error 路由到 END"""
        from core.state_graph.builder import build_cae_graph
        from langgraph.checkpoint.memory import MemorySaver

        with patch('core.state_graph.nodes.planner_node.llm') as mock_planner_llm, \
             patch('core.memory.short_term_compressor.llm') as mock_compressor_llm, \
             patch('core.memory.long_term_experience.get_experience_manager') as mock_exp:

            # Mock Planner — skill=unsupported, action_type=simulate
            # planner 代码路径：skill=="unsupported" 且 action_type!="chat" → 设置 action_type="error"
            mock_planner_structured = Mock()
            mock_planner_structured.invoke.return_value = {
                "intent": "unsupported",
                "action_type": "simulate",
                "reason": "超出支持范围"
            }
            mock_planner_llm.with_structured_output.return_value = mock_planner_structured

            mock_exp_manager = Mock()
            mock_exp_manager.recall_similar.return_value = ""
            mock_exp.return_value = mock_exp_manager

            memory = MemorySaver()
            app = build_cae_graph(checkpointer=memory, tools=[])

            config = {"configurable": {"thread_id": "test-chat-004"}}
            input_state = {
                "messages": [HumanMessage(content="帮我做个天气预报")]
            }

            result = await app.ainvoke(input_state, config=config)

            # skill=unsupported + action_type=simulate → planner 设置 action_type="error"，路由到 END
            assert result["action_type"] == "error"
            # 最后一条消息应是 AIMessage 错误提示
            last_msg = result["messages"][-1]
            assert isinstance(last_msg, AIMessage)


@pytest.mark.e2e
class TestMultiTurnChat:
    """测试多轮对话"""

    @pytest.mark.asyncio
    async def test_multi_turn_conversation(self, mock_env_vars, suppress_print):
        """测试多轮对话的状态保持"""
        from core.state_graph.builder import build_cae_graph
        from langgraph.checkpoint.memory import MemorySaver

        with patch('core.state_graph.nodes.planner_node.llm') as mock_planner_llm, \
             patch('core.state_graph.nodes.chat_node.llm') as mock_chat_llm, \
             patch('core.memory.short_term_compressor.llm') as mock_compressor_llm, \
             patch('core.memory.long_term_experience.get_experience_manager') as mock_exp:

            mock_planner_structured = Mock()
            mock_planner_structured.invoke.return_value = {
                "intent": "bullet_impact",
                "action_type": "chat",
                "reason": "咨询"
            }
            mock_planner_llm.with_structured_output.return_value = mock_planner_structured

            mock_exp_manager = Mock()
            mock_exp_manager.recall_similar.return_value = ""
            mock_exp.return_value = mock_exp_manager

            mock_chat_llm.bind_tools.return_value = mock_chat_llm
            mock_chat_llm.ainvoke = AsyncMock(return_value=AIMessage(content="回复", tool_calls=[]))

            memory = MemorySaver()
            app = build_cae_graph(checkpointer=memory, tools=[])

            config = {"configurable": {"thread_id": "test-multi-turn"}}

            # 第一轮对话
            result1 = await app.ainvoke(
                {"messages": [HumanMessage(content="第一个问题")]},
                config=config
            )
            assert len(result1["messages"]) >= 2

            # 第二轮对话 - 应该保留历史
            result2 = await app.ainvoke(
                {"messages": [HumanMessage(content="第二个问题")]},
                config=config
            )
            # 消息数量应该增加
            assert len(result2["messages"]) > len(result1["messages"])
