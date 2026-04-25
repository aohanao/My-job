import os
import json
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
# 注意：重构后 config 位于 core.config
# 但是在这里我们暂时先保留硬编码或从环境变量读，等到 config.py 搬迁后再统一修复 import
from core import config 

# 经验库数据存放的物理隔离目录
EXP_DB_DIR = os.path.join(os.path.dirname(__file__), "data", "long_term_experience")

class AgentExperienceManager:
    """Agent 的跨域高级长期记忆管理中枢"""
    
    def __init__(self):
        os.makedirs(EXP_DB_DIR, exist_ok=True)
        # 我们这里同样使用目前行业领先的阿里嵌入模型，以便能抓住复杂的工程语境
        self.embeddings = DashScopeEmbeddings(model=config.EMBEDDING_MODEL)
        self.chroma = Chroma(
            collection_name="cae_success_experience",
            embedding_function=self.embeddings,
            persist_directory=EXP_DB_DIR
        )

    def engrave_success(self, user_query: str, skill: str, consensus_params: dict, script_name: str):
        """将完美通关的任务状态刻碑，写入 Chroma (核心向量写操作)"""
        # 没有用户原话或者空参数就不存，避免冲乱记忆
        if not user_query or not consensus_params:
            return
            
        content = (
            f"【历史任务摘要】用户需求: {user_query}\n"
            f"【决策技能】: {skill}\n"
            f"【最终采纳并成功验证的参数体系】: {json.dumps(consensus_params, ensure_ascii=False)}\n"
            f"【对应的可复用脚本产物】: {script_name}"
        )
        metadata = {"skill_domain": skill, "record_type": "gold_standard_success"}
        
        try:
            self.chroma.add_texts(texts=[content], metadatas=[metadata])
            print(f"[LongTermMem] 📖 完美通过！已将经验参数入库，留作后世之鉴。")
        except Exception as e:
            print(f"[LongTermMem] 写入长期记忆碎片失败: {e}")
            
    def recall_similar(self, current_query: str, k: int = 1) -> str:
        """从经验库长河中唤起与当前意图相似的过往回忆"""
        if not current_query:
            return ""
            
        try:
            results = self.chroma.similarity_search(current_query, k=k)
            if not results:
                return ""
                
            return "\n\n---\n\n".join([doc.page_content for doc in results])
        except Exception as e:
            print(f"[LongTermMem] 唤起记忆发生故障: {e}")
            return ""

# 获取单例
def get_experience_manager():
    return AgentExperienceManager()
