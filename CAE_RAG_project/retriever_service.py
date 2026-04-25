import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import jieba # 导入 jieba 分词库，用于中文文本的分词
from rank_bm25 import BM25Okapi # 导入 BM25 算法，用于文本检索和排名
from sentence_transformers import CrossEncoder # 导入 BGE-Reranker 模型，用于文本重排序
from langchain_chroma import Chroma
from langchain_core.documents import Document
import config_data as config
from langchain_community.embeddings import DashScopeEmbeddings
from dotenv import load_dotenv
load_dotenv()

# 👇 定义混合检索器服务类
class HybridRetrieverService:
    def __init__(self, embedding):
        print("\n" + "="*50)
        print("🚀 初始化混合检索引擎 (Chroma Vector + BM25 Sparse + Reranker)")
        
        # 1. 挂载已有的 Chroma 向量数据库
        self.embedding = embedding
        self.vector_store = Chroma(
            collection_name=config.collection_name,
            embedding_function=self.embedding,
            persist_directory=config.persist_directory,
        )
        # 2. 构建 BM25 索引
        self.bm25 = None
        self.chunks = []
        self.sync_bm25_from_chroma()
        # 3. 初始化重排序引擎
        print("🧠 正在加载 BGE-Reranker 交叉编码重排序模型...")
        self.reranker = CrossEncoder('BAAI/bge-reranker-base')
        print("="*50 + "\n")

    #  👇 同步 Chroma 向量库到 BM25 索引
    def sync_bm25_from_chroma(self):
        """
        核心桥接逻辑：从 Chroma 中提取所有切片文本，实时构建 BM25 词频索引。
        """
        #print("📚 正在从 Chroma 向量库同步数据构建 BM25 索引...")
        try:
            db_data = self.vector_store.get() 
            
            # 严格检查空数据，防止冷启动崩溃
            if not db_data or not db_data.get('documents'):
                #print("⚠️ 当前向量库为空，暂不构建 BM25 索引。")
                self.bm25 = None
                self.chunks = []
                return
            self.chunks = [
                Document(page_content=txt, metadata=meta) 
                for txt, meta in zip(db_data['documents'], db_data['metadatas'])
            ]

            # 使用 jieba 对文档内容进行分词，用于 BM25 索引
            tokenized_corpus = [list(jieba.cut_for_search(doc.page_content)) for doc in self.chunks]
            # 确保语料库不为空才初始化 BM25
            if tokenized_corpus:
                self.bm25 = BM25Okapi(tokenized_corpus)
                print(f"✅ BM25 索引构建完毕，共计 {len(self.chunks)} 个文档切片。")
            else:
                self.bm25 = None
                
        except Exception as e:
            print(f"❌ 构建 BM25 索引时发生错误: {e}")
            self.bm25 = None
            self.chunks = []

    #  👇 双路召回与 RRF 融合
    def _hybrid_retrieve(self, query: str, top_k: int = 10, rrf_k: int = 60) -> list[Document]:
        """第一阶段：双路召回与 RRF 融合"""
        # --- 路线 A：Chroma 向量检索 ---
        dense_results = self.vector_store.similarity_search(query, k=top_k)
        
        # --- 路线 B：BM25 关键词检索 ---
        # 安全熔断：如果没有 BM25 索引，直接返回向量检索结果，不再执行 RRF
        if not self.bm25 or not self.chunks:
            print("⚠️ 未发现 BM25 索引，自动降级为纯向量检索。")
            return dense_results 
        tokenized_query = list(jieba.cut_for_search(query)) # 对查询进行分词
        bm25_scores = self.bm25.get_scores(tokenized_query) # 计算 BM25 得分
        bm25_top_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:top_k] # 取 BM25 得分最高的 top_k 个文档索引
        sparse_results = [self.chunks[i] for i in bm25_top_indices] # 从 BM25 索引中提取 top_k 个文档

        # --- 路线 C：RRF (倒数排名融合) ---
        fused_scores = {}
        # (1)Chroma 向量检索的 RRF 贡献
        for rank, doc in enumerate(dense_results):
            doc_key = doc.page_content 
            if doc_key not in fused_scores:
                fused_scores[doc_key] = {"doc": doc, "score": 0.0}
            fused_scores[doc_key]["score"] += 1.0 / (rrf_k + rank + 1)
        # (2)BM25 关键词检索的 RRF 贡献
        for rank, doc in enumerate(sparse_results):
            doc_key = doc.page_content
            if doc_key not in fused_scores:
                fused_scores[doc_key] = {"doc": doc, "score": 0.0}
            fused_scores[doc_key]["score"] += 1.0 / (rrf_k + rank + 1)
        # (3)按 RRF 得分降序并截取
        reranked_results = sorted(fused_scores.values(), key=lambda x: x["score"], reverse=True)
        return [item["doc"] for item in reranked_results[:top_k]]

    #  👇 重排序
    def search_and_rerank(self, query: str, initial_k: int = 10, final_k: int = 3) -> list[Document]:
        """第二阶段：调用此方法执行完整的 RAG 检索链路"""
        print(f"🔍 [阶段 1] 混合检索召回前 {initial_k} 个片段...")
        initial_docs = self._hybrid_retrieve(query, top_k=initial_k)
        if not initial_docs:
            return []

        print(f"⚖️ [阶段 2] BGE-Reranker 进行深度交叉语义打分...")
        cross_inp = [[query, doc.page_content] for doc in initial_docs]
        scores = self.reranker.predict(cross_inp)
        # 绑定得分并排序
        scored_docs = list(zip(initial_docs, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        print(f"🎯 [阶段 3] 优中选优，输出最终的 Top-{final_k}！")
        # 只要文档，剔除分数，方便后续 LangChain 调用
        final_docs = [doc for doc, score in scored_docs[:final_k]]
        return final_docs


if __name__ == "__main__":   
    # 初始化嵌入模型和检索服务
    embedding = DashScopeEmbeddings(model="text-embedding-v4")
    retriever_service = HybridRetrieverService(embedding)
    
    # 执行混合检索 + 重排序
    query_text = "什么是有限元分析？"
    results = retriever_service.search_and_rerank(query_text, initial_k=10, final_k=3)
    
    print("\n📝 最终检索结果：")
    for i, doc in enumerate(results):
        print(f"[{i+1}] 来源: {doc.metadata.get('source', '未知')} | 内容: {doc.page_content[:50]}...")