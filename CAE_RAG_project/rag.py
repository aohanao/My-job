# rag.py
import os
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough
from langchain_community.chat_models import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory 
import config_data as config
from semantic_cache import global_cache # 👈 引入语义缓存全局实例
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from retriever_service import HybridRetrieverService

class RagService:
    def __init__(self):
        # 1. 初始化大模型与嵌入模型
        self.embeddings = DashScopeEmbeddings(model=config.embedding_model)
        self.chat_model = ChatTongyi(model=config.chat_model)
        # 2. 初始化检索服务 (务必传入 embeddings 实例)
        self.retriever_service = HybridRetrieverService(self.embeddings)
        # 3. 构造核心对话链路
        self.chain = self.__get_chain()

    def __format_docs(self, docs):
        """格式化检索到的文档用于 Prompt 填充，附带完整章节溯源链"""
        formatted = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get("source", "未知来源")
            header_path = doc.metadata.get("header_path", "")
            chunk_index = doc.metadata.get("chunk_index", "")
            content = doc.page_content.replace("\n", " ")

            # 构建精确到章节的溯源标识
            if header_path:
                location = f"{source} ▶ {header_path}"
            else:
                location = source
            if chunk_index != "":
                location += f" [切片#{chunk_index}]"

            formatted.append(f"【资料 {i+1}】(来源: {location}):\n{content}")
        return "\n\n".join(formatted)

    def print_prompt(self, x):
        """调试用：打印最终发送给大模型的 Prompt 内容"""
        print("\n" + "="*50)
        print("🔍 [DEBUG] 最终合成的 Prompt 内容如下：")
        print(x.to_string())
        print("="*50 + "\n")
        return x

    def __get_chain(self):
        """核心业务逻辑编排：Query Rewrite -> Hybrid Search -> Rerank -> QA"""
        
        # 1. 查询重写节点：将带人称代词的提问重写为独立的搜索词
        contextualize_q_system_prompt = (
            "给定一段对话历史和一个最新的用户问题，"
            "该问题可能引用了对话历史中的上下文。请将其重写为一个能够独立理解的、"
            "包含完整语义的问题。不要回答该问题，仅输出重写后的文本，"
            "如果无需重写，则原样返回。"
        )
        contextualize_q_prompt = ChatPromptTemplate.from_messages([
            ("system", contextualize_q_system_prompt),
            MessagesPlaceholder("history"),
            ("human", "{input}"),
        ])
        # 重写链不使用流式，直接输出字符串
        rewrite_chain = contextualize_q_prompt | self.chat_model | StrOutputParser()

        # 2. 专家级 QA 节点：基于检索到的 Context 回答
        qa_system_prompt = (
            "你是一个专业的 CAE 仿真分析专家，请基于以下【参考资料】回答用户的问题。\n"
            "如果你在资料中找不到答案，请直接说：'抱歉，目前我的知识库中没有关于此问题的详细标准规范。'，严禁胡编乱造。\n\n"
            "【参考资料汇编】：\n{context}\n\n"
            "要求：回答应专业、严谨，并尽可能保留原始工程参数。如果涉及到多份参考资料，请在句末标注来源序号，例如 [资料 1]。"
        )
        qa_prompt = ChatPromptTemplate.from_messages([
            ("system", qa_system_prompt),
            MessagesPlaceholder("history"),
            ("human", "{input}"),
        ])

        # 3. 编排完整 LCEL 链条
        base_chain = (
            RunnablePassthrough.assign(
                # 第一步：查询重写
                rewritten_query=rewrite_chain
            )
            | RunnablePassthrough.assign(
                # 第二步：利用重写后的词执行混合检索与重排
                context=lambda x: self.__format_docs(
                    self.retriever_service.search_and_rerank(x["rewritten_query"])
                )
            )
            | qa_prompt
            | self.chat_model
            | StrOutputParser()
        )

        # 👇 内部函数：记忆管理器工厂，负责滑窗摘要压缩
        def get_session_history(session_id: str):
            from file_history_store import SummaryFileChatMessageHistory
            return SummaryFileChatMessageHistory(
                session_id=session_id, 
                storage_path="./chat_history", 
                llm=self.chat_model, 
                max_messages=6 # 这里保留了你刚才修改的阈值 6
            )
        
        # 挂载历史消息记忆
        conversation_chain = RunnableWithMessageHistory(
            base_chain, 
            get_session_history, 
            input_messages_key="input", 
            history_messages_key="history", 
        )

        return conversation_chain

    def stream_with_cache(self, input_data: dict, config: dict):
        """
        带语义缓存探测的流式输出方法。
        app.py 已切换至此接口。
        """
        query = input_data.get("input", "")
        
        # 1. 抛出探针：检查语义缓存（长期记忆）
        cached_result = global_cache.check_cache(query)
        if cached_result:
            yield "✨ [来自长期记忆库的直接召回结果]\n\n"
            yield cached_result
            return

        # 2. 缓存未击中：执行完整 RAG 链路
        full_response = ""
        for chunk in self.chain.stream(input_data, config):
            full_response += chunk
            yield chunk
        
        # 3. 存储：将本次高质量对话结果固化入经验大坝
        if full_response and len(full_response) > 5:
            global_cache.save_cache(query, full_response)