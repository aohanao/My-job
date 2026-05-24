import os
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
import config_data as config

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "semantic_cache_db")

class SemanticCacheModule:
    """RAG 语义防线体验：相同/类似语义的提问直接拦截，极速返回，0 token损耗"""
    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.embeddings = DashScopeEmbeddings(model=config.embedding_model)
        self.chroma = Chroma(
            collection_name="rag_semantic_cache",
            embedding_function=self.embeddings,
            persist_directory=CACHE_DIR
        )

    def check_cache(self, query: str, threshold: float = 0.80) -> str:
        """检查是否有语义高相似的历史解答"""
        if not query:
            return ""
            
        try:
            results = self.chroma.similarity_search_with_relevance_scores(query, k=1)
            if not results:
                return ""
            
            doc, score = results[0]
            # Langchain集成Chroma的分数计算机制，分数越长代表相似度越高 (或者L2转余弦)
            if score > threshold:
                print(f"[RAG-SemCache] ⚡ 语义短路触发！命中极高相似历史 (相似度: {score:.2f})")
                return doc.metadata.get("answer", "")
            return ""
        except Exception as e:
            print(f"[RAG-SemCache] 缓存探测异常: {e}")
            return ""

    def save_cache(self, query: str, answer: str):
        """将高质量的解答归档"""
        if not query or not answer:
            return
            
        metadata = {"answer": answer, "original_query": query, "type": "semantic_answer"}
        try:
            self.chroma.add_texts(texts=[query], metadatas=[metadata])
            print("[RAG-SemCache] 💾 新知识已凝固进缓存。")
        except Exception as e:
            print(f"[RAG-SemCache] 缓存写入失败: {e}")

global_cache = SemanticCacheModule()
