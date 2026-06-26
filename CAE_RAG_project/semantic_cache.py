import os
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
import config_data as config

import time

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "semantic_cache_db")
TTL_SECONDS = 7 * 24 * 3600  # 缓存失效时间：7天
MAX_CACHE_SIZE = 500         # 缓存容量上限，超出后启动 LRU 淘汰机制
EVICTION_COUNT = 50          # 触发淘汰时清理最老的前 50 条

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
            
            # 🕰️ TTL 校验：若缓存已过期，执行物理删除并返回空
            create_time = doc.metadata.get("create_time", 0.0)
            if time.time() - create_time > TTL_SECONDS:
                print(f"[RAG-SemCache] ⏰ 缓存条目已过期 (存活了 {time.time() - create_time:.1f} 秒)，正在物理删除...")
                # 寻找该文本的 id 并进行删除
                all_data = self.chroma.get()
                for i, meta in enumerate(all_data.get("metadatas", [])):
                    if meta.get("original_query") == doc.metadata.get("original_query"):
                        doc_id = all_data["ids"][i]
                        self.chroma.delete([doc_id])
                        print(f"[RAG-SemCache] 🗑️ 成功物理删除过期缓存 ID: {doc_id}")
                        break
                return ""

            # Langchain集成Chroma的分数计算机制，分数越高代表相似度越高
            if score > threshold:
                print(f"[RAG-SemCache] ⚡ 语义短路触发！命中极高相似历史 (相似度: {score:.2f})")
                return doc.metadata.get("answer", "")
            return ""
        except Exception as e:
            print(f"[RAG-SemCache] 缓存探测异常: {e}")
            return ""

    def save_cache(self, query: str, answer: str):
        """将高质量的解答归档，并在超出阈值时执行 LRU 淘汰"""
        if not query or not answer:
            return
            
        metadata = {
            "answer": answer, 
            "original_query": query, 
            "type": "semantic_answer",
            "create_time": time.time() # 记录时间戳
        }
        
        try:
            # 🚀 检查缓存容量，若超出 MAX_CACHE_SIZE，启动 LRU 淘汰
            all_data = self.chroma.get()
            total_items = len(all_data.get("ids", []))
            if total_items >= MAX_CACHE_SIZE:
                print(f"[RAG-SemCache] ⚠️ 缓存池已满 ({total_items}/{MAX_CACHE_SIZE})，启动 LRU 淘汰清理最老的前 {EVICTION_COUNT} 条记录...")
                
                # 按照创建时间对所有缓存进行排序
                items = []
                for i in range(total_items):
                    items.append({
                        "id": all_data["ids"][i],
                        "create_time": all_data["metadatas"][i].get("create_time", 0.0)
                    })
                items.sort(key=lambda x: x["create_time"])
                
                # 提取最老的前 EVICTION_COUNT 个 ID 并删除
                ids_to_delete = [item["id"] for item in items[:EVICTION_COUNT]]
                self.chroma.delete(ids_to_delete)
                print(f"[RAG-SemCache] 🗑️ 已物理清理最旧的 {len(ids_to_delete)} 条缓存。")

            self.chroma.add_texts(texts=[query], metadatas=[metadata])
            print("[RAG-SemCache] 💾 新知识已凝固进缓存。")
        except Exception as e:
            print(f"[RAG-SemCache] 缓存写入失败: {e}")

global_cache = SemanticCacheModule()
