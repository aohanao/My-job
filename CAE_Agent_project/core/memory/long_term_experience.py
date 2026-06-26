import os
import json
import time
import uuid
from typing import List, Dict, Any, Optional, Tuple
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
# 注意：重构后 config 位于 core.config
# 但是在这里我们暂时先保留硬编码或从环境变量读，等到 config.py 搬迁后再统一修复 import
from core import config 

# 经验库数据存放的物理隔离目录
EXP_DB_DIR = os.path.join(os.path.dirname(__file__), "data", "long_term_experience")

class AgentExperienceManager:
    """Agent 的跨域高级长期记忆管理中枢 (引入 TTL 与置信度淘汰机制)"""
    
    def __init__(self):
        os.makedirs(EXP_DB_DIR, exist_ok=True)
        # 我们这里同样使用目前行业领先的阿里嵌入模型，以便能抓住复杂的工程语境
        self.embeddings = DashScopeEmbeddings(model=config.EMBEDDING_MODEL)
        self.chroma = Chroma(
            collection_name="cae_success_experience",
            embedding_function=self.embeddings,
            persist_directory=EXP_DB_DIR
        )
        self.last_recalled_ids = []


    def engrave_qa(self, question: str, answer: str, skill: str = "general", ttl: Optional[int] = None) -> str:
        """
        将高价值的 Q&A 问答对存入 Chroma 长期记忆库
        
        Args:
            question: 问题描述 (Q)
            answer: 解答/解决方案 (A)
            skill: 所属技能领域
            ttl: 生存时间 (秒)，默认 30 天 (30 * 24 * 3600)
            
        Returns:
            doc_id: 存入文档的唯一 ID
        """
        if not question or not answer:
            return ""
            
        doc_id = uuid.uuid4().hex
        content = (
            f"【高优问答】问题: {question}\n"
            f"【高优问答】解答: {answer}"
        )
        
        # 默认 TTL 设为 30 天
        actual_ttl = ttl if ttl is not None else (30 * 24 * 3600)
        
        metadata = {
            "doc_id": doc_id,
            "skill_domain": skill,
            "record_type": "high_priority_qa",
            "created_at": time.time(),
            "ttl": actual_ttl,
            "confidence": 1.0
        }
        
        try:
            self.chroma.add_texts(texts=[content], metadatas=[metadata], ids=[doc_id])
            print(f"[LongTermMem] 💾 已将高优 Q&A 存入长期记忆库，ID: {doc_id}，TTL: {actual_ttl}s")
            return doc_id
        except Exception as e:
            print(f"[LongTermMem] 写入高优 Q&A 长期记忆失败: {e}")
            return ""

    def engrave_success(self, user_query: str, skill: str, consensus_params: dict, script_name: str, ttl: Optional[int] = None):
        """将完美通关的任务状态刻碑，写入 Chroma (核心向量写操作，向后兼容，内部转为结构化 Q&A)"""
        # 没有用户原话或者空参数就不存，避免冲乱记忆
        if not user_query or not consensus_params:
            return
            
        question = user_query
        answer = (
            f"决策技能: {skill}\n"
            f"共识参数: {json.dumps(consensus_params, ensure_ascii=False)}\n"
            f"可复用脚本: {script_name}"
        )
        
        doc_id = self.engrave_qa(
            question=question,
            answer=answer,
            skill=skill,
            ttl=ttl
        )
        if doc_id:
            print(f"[LongTermMem] 📖 完美通过！已将经验参数入库，留作后世之鉴。")

    def recall_similar(self, current_query: str, k: int = 1, distance_threshold: float = 0.6) -> str:
        """
        从经验库长河中唤起与当前意图相似的过往回忆
        自动触发 TTL 清理，当匹配距离 score 超过设定阈值时仅过滤该条记忆，绝不在检索时扣分
        """
        if not current_query:
            return ""
            
        try:
            # 1. 自动触发过期清理
            self.cleanup_expired_memories()
            self.last_recalled_ids = []
            
            # 2. 相似度检索并带有分数 (即距离)
            results = self.chroma.similarity_search_with_score(current_query, k=k)
            if not results:
                return ""
                
            high_confidence_docs = []
            
            for doc, score in results:
                metadata = doc.metadata or {}
                doc_id = metadata.get("doc_id")
                created_at = metadata.get("created_at", 0)
                ttl = metadata.get("ttl", 30 * 24 * 3600)
                
                # 双重校验 TTL
                if created_at > 0 and (created_at + ttl < time.time()):
                    if doc_id:
                        self.chroma.delete(ids=[doc_id])
                    continue
                
                # 3. 低置信度过滤 (score 越大代表距离越大，越不相似)
                # 仅仅做过滤防止当前不相关的记忆污染大模型上下文，不进行扣分和物理淘汰
                if score > distance_threshold:
                    print(f"[LongTermMem] ⚠️ 唤起记忆 [ID: {doc_id}] 距离分数 {score:.4f} > {distance_threshold}，与当前意图不匹配，已被过滤。")
                    continue
                
                if doc_id:
                    self.last_recalled_ids.append(doc_id)
                high_confidence_docs.append(doc.page_content)
                
            if not high_confidence_docs:
                return ""
                
            return "\n\n---\n\n".join(high_confidence_docs)
            
        except Exception as e:
            print(f"[LongTermMem] 唤起记忆发生故障: {e}")
            return ""

    def feedback_memory(self, doc_id: str, is_positive: bool):
        """
        对特定长期记忆进行使用效果反馈，引入低置信度物理淘汰机制以防记忆污染
        只有在真实采纳了该条记忆后产生效果反馈（如自愈失败/执行成功）时，才触发置信度增减及淘汰
        
        Args:
            doc_id: 记忆片段的唯一 ID
            is_positive: 反馈方向，True 为加分，False 为扣分
        """
        if not doc_id:
            return
        try:
            res = self.chroma.get(ids=[doc_id])
            if not res or not res["ids"] or not res["metadatas"]:
                return
            
            metadata = res["metadatas"][0]
            content = res["documents"][0]
            confidence = metadata.get("confidence", 1.0)
            
            if is_positive:
                new_confidence = min(1.0, confidence + 0.1)
            else:
                new_confidence = confidence - 0.2
                
            if new_confidence < 0.3:
                # 触发物理淘汰
                self.chroma.delete(ids=[doc_id])
                print(f"[LongTermMem] 🚫 反馈淘汰：记忆 [ID: {doc_id}] 置信度过低 ({new_confidence:.2f} < 0.3)，已被物理淘汰清除")
            else:
                # 更新置信度并写回
                metadata["confidence"] = new_confidence
                self.chroma.delete(ids=[doc_id])
                self.chroma.add_texts(texts=[content], metadatas=[metadata], ids=[doc_id])
                print(f"[LongTermMem] 📝 记忆反馈：更新 [ID: {doc_id}] 置信度为 {new_confidence:.2f}")
        except Exception as e:
            print(f"[LongTermMem] 长期记忆反馈处理失败: {e}")

    def cleanup_expired_memories(self):
        """定期扫描并物理清理所有已过期的长期记忆"""
        try:
            all_data = self.chroma.get()
            if not all_data or "ids" not in all_data or "metadatas" not in all_data:
                return
                
            ids = all_data["ids"]
            metadatas = all_data["metadatas"]
            current_time = time.time()
            
            expired_ids = []
            for doc_id, meta in zip(ids, metadatas):
                if not meta:
                    continue
                created_at = meta.get("created_at", 0)
                ttl = meta.get("ttl", 0)
                if created_at > 0 and ttl > 0:
                    if created_at + ttl < current_time:
                        expired_ids.append(doc_id)
                        
            if expired_ids:
                self.chroma.delete(ids=expired_ids)
                print(f"[LongTermMem] 🧹 自动清理机制：成功物理清除 {len(expired_ids)} 条过期的长期记忆")
        except Exception as e:
            print(f"[LongTermMem] 清理过期记忆遇到异常: {e}")

_manager_instance = None

# 获取单例
def get_experience_manager():
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = AgentExperienceManager()
    return _manager_instance

