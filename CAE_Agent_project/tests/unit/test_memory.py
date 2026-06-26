"""单元测试 - 记忆系统"""
import pytest
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from unittest.mock import Mock, patch, MagicMock


class TestShortTermCompressor:
    """测试短期记忆压缩器"""

    def test_no_compression_when_under_threshold(self):
        """测试消息数量未超过阈值时不压缩"""
        from core.memory.short_term_compressor import compressor_node

        state = {
            "messages": [
                HumanMessage(content=f"消息{i}") for i in range(10)
            ],
            "context_summary": ""
        }

        result = compressor_node(state)
        assert "messages" not in result, "消息数量未超过12条时不应返回消息删除指令"
        assert "context_summary" not in result, "消息数量未超过12条时不应返回压缩摘要"
        assert "context_usage_percent" in result, "应返回上下文使用率"
        assert result.get("context_warning") is False, "使用率低时不应触发报警"

    def test_compression_when_over_threshold(self, monkeypatch):
        """测试消息数量超过阈值时触发压缩"""
        from core.memory.short_term_compressor import compressor_node

        # Mock LLM响应
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "这是压缩后的摘要"
        mock_llm.invoke.return_value = mock_response

        # 替换模块中的llm
        import core.memory.short_term_compressor as compressor_module
        monkeypatch.setattr(compressor_module, 'llm', mock_llm)

        # 创建超过阈值的消息（需设置id供RemoveMessage使用）
        messages = []
        for i in range(15):
            msg = HumanMessage(content=f"消息{i}")
            msg.id = f"msg-{i}"
            messages.append(msg)

        state = {
            "messages": messages,
            "context_summary": ""
        }

        result = compressor_node(state)

        # 验证返回了删除指令和摘要
        assert "messages" in result, "应该返回删除消息的指令"
        assert "context_summary" in result, "应该返回压缩摘要"
        assert result["context_summary"] == "这是压缩后的摘要"

        # 验证删除了旧消息（保留最近4条，删除前11条）
        assert len(result["messages"]) == 11, "应该删除11条旧消息（15-4=11）"

    def test_compression_preserves_recent_messages(self, monkeypatch):
        """测试压缩保留最近的消息"""
        from core.memory.short_term_compressor import compressor_node

        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "摘要"
        mock_llm.invoke.return_value = mock_response

        import core.memory.short_term_compressor as compressor_module
        monkeypatch.setattr(compressor_module, 'llm', mock_llm)

        messages = []
        for i in range(20):
            msg = HumanMessage(content=f"消息{i}")
            msg.id = f"msg-{i}"
            messages.append(msg)

        state = {"messages": messages, "context_summary": ""}
        result = compressor_node(state)

        # 应该删除前16条消息（20-4=16）
        assert len(result["messages"]) == 16

    def test_compression_with_existing_summary(self, monkeypatch):
        """测试已有摘要时的累积压缩"""
        from core.memory.short_term_compressor import compressor_node

        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "新摘要"
        mock_llm.invoke.return_value = mock_response

        import core.memory.short_term_compressor as compressor_module
        monkeypatch.setattr(compressor_module, 'llm', mock_llm)

        messages = []
        for i in range(15):
            msg = HumanMessage(content=f"消息{i}")
            msg.id = f"msg-{i}"
            messages.append(msg)

        state = {
            "messages": messages,
            "context_summary": "旧摘要"
        }

        result = compressor_node(state)

        # 验证摘要累积（格式："{旧摘要}\n\n[新增补充记忆]: {新摘要}"）
        assert "旧摘要" in result["context_summary"]
        assert "新摘要" in result["context_summary"]

    def test_compression_handles_llm_error(self, monkeypatch):
        """测试LLM调用失败时的处理"""
        from core.memory.short_term_compressor import compressor_node

        mock_llm = Mock()
        mock_llm.invoke.side_effect = Exception("LLM调用失败")

        import core.memory.short_term_compressor as compressor_module
        monkeypatch.setattr(compressor_module, 'llm', mock_llm)

        messages = []
        for i in range(15):
            msg = HumanMessage(content=f"消息{i}")
            msg.id = f"msg-{i}"
            messages.append(msg)

        state = {"messages": messages, "context_summary": ""}

        result = compressor_node(state)

        # 发生错误时应仅返回水位线和警告相关状态，且不生成删除指令与新摘要
        assert "messages" not in result
        assert "context_summary" not in result
        assert "context_usage_percent" in result
        assert result.get("context_warning") is False

    def test_compression_with_messages_without_id(self, monkeypatch):
        """测试处理没有ID的消息（无ID的消息不会生成RemoveMessage）"""
        from core.memory.short_term_compressor import compressor_node

        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = "摘要"
        mock_llm.invoke.return_value = mock_response

        import core.memory.short_term_compressor as compressor_module
        monkeypatch.setattr(compressor_module, 'llm', mock_llm)

        # 创建没有ID的消息（LangChain默认会自动分配UUID，这里测试有None id的情况）
        messages = [HumanMessage(content=f"消息{i}") for i in range(15)]
        for msg in messages:
            msg.id = None  # 显式设置为None

        state = {"messages": messages, "context_summary": ""}

        # 不应该抛出异常
        result = compressor_node(state)
        assert "context_summary" in result
        # 没有有效ID的消息不会生成删除指令
        assert len(result.get("messages", [])) == 0


class TestLongTermExperience:

    """测试长期经验记忆"""

    def test_engrave_success(self, mock_chroma_db):
        """测试成功经验的存储（兼容性方法，底层转换为 Q&A）"""
        from core.memory.long_term_experience import AgentExperienceManager

        # 同时 patch Chroma 和 DashScopeEmbeddings，避免真实网络调用
        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            # 存储成功经验
            manager.engrave_success(
                user_query="子弹冲击钢板仿真",
                skill="bullet_impact",
                consensus_params={"plate_thickness": 20.0},
                script_name="test_script.py"
            )

            # 验证调用了add_texts
            mock_chroma.add_texts.assert_called_once()
            call_args = mock_chroma.add_texts.call_args
            texts = call_args.kwargs.get('texts') or call_args[0][0]
            metadatas = call_args.kwargs.get('metadatas') or call_args[0][1]

            assert len(texts) == 1
            assert "子弹冲击" in texts[0]
            assert "bullet_impact" in texts[0]
            assert metadatas[0]['skill_domain'] == "bullet_impact"
            assert "created_at" in metadatas[0]
            assert "ttl" in metadatas[0]
            assert metadatas[0]["confidence"] == 1.0

    def test_engrave_qa(self, mock_chroma_db):
        """测试直接存入高优 Q&A 对"""
        from core.memory.long_term_experience import AgentExperienceManager

        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            # 直接存入 Q&A
            doc_id = manager.engrave_qa(
                question="如何配置隧道支护的锚杆间距？",
                answer="建议采用1.2m梅花形布置。",
                skill="tunnel_support",
                ttl=3600
            )

            assert doc_id != ""
            mock_chroma.add_texts.assert_called_once()
            call_args = mock_chroma.add_texts.call_args
            texts = call_args.kwargs.get('texts') or call_args[0][0]
            metadatas = call_args.kwargs.get('metadatas') or call_args[0][1]
            ids = call_args.kwargs.get('ids') or call_args[0][2]

            assert "如何配置隧道支护" in texts[0]
            assert "1.2m梅花形布置" in texts[0]
            assert metadatas[0]["skill_domain"] == "tunnel_support"
            assert metadatas[0]["ttl"] == 3600
            assert ids[0] == doc_id

    def test_engrave_success_with_empty_query(self, mock_chroma_db):
        """测试空查询不存储"""
        from core.memory.long_term_experience import AgentExperienceManager

        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            manager.engrave_success(
                user_query="",
                skill="bullet_impact",
                consensus_params={"plate_thickness": 20.0},
                script_name="test_script.py"
            )

            mock_chroma.add_texts.assert_not_called()

    def test_engrave_success_with_empty_params(self, mock_chroma_db):
        """测试空参数不存储"""
        from core.memory.long_term_experience import AgentExperienceManager

        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            manager.engrave_success(
                user_query="测试查询",
                skill="bullet_impact",
                consensus_params={},
                script_name="test_script.py"
            )

            mock_chroma.add_texts.assert_not_called()

    def test_recall_similar(self, mock_chroma_db):
        """测试相似经验的检索（高置信度召回）"""
        from core.memory.long_term_experience import AgentExperienceManager

        import time
        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()

            # Mock检索结果
            mock_doc1 = Mock()
            mock_doc1.page_content = "经验1：子弹冲击参数..."
            mock_doc1.metadata = {"doc_id": "id1", "created_at": time.time(), "ttl": 3600, "confidence": 1.0}
            
            mock_doc2 = Mock()
            mock_doc2.page_content = "经验2：钢板厚度..."
            mock_doc2.metadata = {"doc_id": "id2", "created_at": time.time(), "ttl": 3600, "confidence": 1.0}

            # 返回的是带有距离分数的二元组，这里设置距离为 0.2 和 0.3 (距离小于0.6即为高置信度)
            mock_chroma.similarity_search_with_score.return_value = [(mock_doc1, 0.2), (mock_doc2, 0.3)]
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            result = manager.recall_similar("子弹冲击", k=2)

            mock_chroma.similarity_search_with_score.assert_called_once_with("子弹冲击", k=2)
            assert "经验1" in result
            assert "经验2" in result
            assert "---" in result  # 分隔符

    def test_recall_similar_with_empty_query(self, mock_chroma_db):
        """测试空查询返回空结果"""
        from core.memory.long_term_experience import AgentExperienceManager

        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            result = manager.recall_similar("", k=1)

            assert result == ""
            mock_chroma.similarity_search_with_score.assert_not_called()

    def test_recall_similar_with_no_results(self, mock_chroma_db):
        """测试没有检索结果"""
        from core.memory.long_term_experience import AgentExperienceManager

        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            mock_chroma.similarity_search_with_score.return_value = []
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            result = manager.recall_similar("不存在的查询", k=1)

            assert result == ""

    def test_recall_similar_handles_error(self, mock_chroma_db):
        """测试检索错误处理"""
        from core.memory.long_term_experience import AgentExperienceManager

        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            mock_chroma.similarity_search_with_score.side_effect = Exception("数据库错误")
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            result = manager.recall_similar("查询", k=1)

            assert result == ""

    def test_recall_similar_low_confidence_filtering(self, mock_chroma_db):
        """测试低置信度只做过滤，不衰减置信度"""
        from core.memory.long_term_experience import AgentExperienceManager

        import time
        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()

            mock_doc = Mock()
            mock_doc.page_content = "不相关的记忆"
            mock_doc.metadata = {"doc_id": "test_id", "created_at": time.time(), "ttl": 3600, "confidence": 1.0}

            # 距离分数为 0.8，大于阈值 0.6，应该被过滤
            mock_chroma.similarity_search_with_score.return_value = [(mock_doc, 0.8)]
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            result = manager.recall_similar("查询词", k=1, distance_threshold=0.6)

            # 应被过滤，不返回内容
            assert result == ""
            # 仅仅做过滤，不应该调用 delete 或 add_texts 进行置信度扣减更新
            mock_chroma.delete.assert_not_called()
            mock_chroma.add_texts.assert_not_called()

    def test_feedback_memory_positive_and_negative(self, mock_chroma_db):
        """测试特定长期记忆的使用反馈逻辑（增减置信度）"""
        from core.memory.long_term_experience import AgentExperienceManager

        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            # 1. 积极反馈 (加分 0.1)
            mock_chroma.get.return_value = {
                "ids": ["test_id"],
                "documents": ["记忆内容"],
                "metadatas": [{"doc_id": "test_id", "confidence": 0.5}]
            }
            manager.feedback_memory("test_id", is_positive=True)
            mock_chroma.delete.assert_called_with(ids=["test_id"])
            mock_chroma.add_texts.assert_called_once()
            call_args = mock_chroma.add_texts.call_args
            metadatas = call_args.kwargs.get('metadatas') or call_args[0][1]
            assert abs(metadatas[0]["confidence"] - 0.6) < 1e-6

            # 重置 mock
            mock_chroma.delete.reset_mock()
            mock_chroma.add_texts.reset_mock()

            # 2. 消极反馈 (减分 0.2)
            mock_chroma.get.return_value = {
                "ids": ["test_id"],
                "documents": ["记忆内容"],
                "metadatas": [{"doc_id": "test_id", "confidence": 0.5}]
            }
            manager.feedback_memory("test_id", is_positive=False)
            mock_chroma.delete.assert_called_with(ids=["test_id"])
            mock_chroma.add_texts.assert_called_once()
            call_args = mock_chroma.add_texts.call_args
            metadatas = call_args.kwargs.get('metadatas') or call_args[0][1]
            assert abs(metadatas[0]["confidence"] - 0.3) < 1e-6

    def test_feedback_memory_elimination(self, mock_chroma_db):
        """测试置信度扣减至 0.3 以下时触发物理淘汰"""
        from core.memory.long_term_experience import AgentExperienceManager

        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            
            # 初始置信度为 0.4，消极反馈扣减 0.2 变为 0.2 (< 0.3)
            mock_chroma.get.return_value = {
                "ids": ["test_id"],
                "documents": ["记忆内容"],
                "metadatas": [{"doc_id": "test_id", "confidence": 0.4}]
            }
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()
            manager.feedback_memory("test_id", is_positive=False)

            # 应该被物理删除且不写回（仅调用 delete，不调用 add_texts 写回）
            mock_chroma.delete.assert_called_with(ids=["test_id"])
            mock_chroma.add_texts.assert_not_called()


    def test_recall_similar_ttl_expired_in_recall(self, mock_chroma_db):
        """测试在检索时自动校验并清理过期的记忆"""
        from core.memory.long_term_experience import AgentExperienceManager

        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()

            mock_doc = Mock()
            mock_doc.page_content = "过期记忆"
            # created_at 为 1000（很久以前），ttl 只有 100
            mock_doc.metadata = {"doc_id": "expired_id", "created_at": 1000, "ttl": 100, "confidence": 1.0}

            mock_chroma.similarity_search_with_score.return_value = [(mock_doc, 0.1)]
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()

            result = manager.recall_similar("查询", k=1)

            assert result == ""
            # 应该直接删除
            mock_chroma.delete.assert_any_call(ids=["expired_id"])

    def test_cleanup_expired_memories(self, mock_chroma_db):
        """测试主动清理过期记忆碎片"""
        from core.memory.long_term_experience import AgentExperienceManager

        import time
        with patch('core.memory.long_term_experience.Chroma') as mock_chroma_class, \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            mock_chroma = Mock()
            
            # Mock get 接口返回的数据
            mock_chroma.get.return_value = {
                "ids": ["doc_ok", "doc_expired"],
                "metadatas": [
                    {"created_at": time.time(), "ttl": 3600}, # 未过期
                    {"created_at": 1000, "ttl": 100}          # 已过期
                ]
            }
            mock_chroma_class.return_value = mock_chroma

            manager = AgentExperienceManager()
            manager.cleanup_expired_memories()

            # 验证只对已过期的文档调用了删除
            mock_chroma.delete.assert_called_once_with(ids=["doc_expired"])

    def test_get_experience_manager_singleton(self):
        """测试get_experience_manager工厂函数"""
        from core.memory.long_term_experience import get_experience_manager

        with patch('core.memory.long_term_experience.Chroma'), \
             patch('core.memory.long_term_experience.DashScopeEmbeddings'):
            manager1 = get_experience_manager()
            manager2 = get_experience_manager()

            assert manager1 is not None
            assert manager2 is not None

