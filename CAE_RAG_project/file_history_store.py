import json
import os
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict, SystemMessage
from langchain_core.chat_history import BaseChatMessageHistory

class SummaryFileChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, session_id, storage_path, llm, max_messages=6):
        import re
        if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
            raise ValueError("Invalid session_id format to prevent path traversal.")
        self.session_id = session_id
        self.storage_path = storage_path
        self.llm = llm  # 👈 核心：接收从外部传进来的大模型
        self.max_messages = max_messages # 触发摘要的阈值（6条=3轮对话）
        
        self.file_path = os.path.join(self.storage_path, self.session_id)
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    @property
    def messages(self) -> list[BaseMessage]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return messages_from_dict(json.load(f))
        except FileNotFoundError:
            return []

    def add_message(self, message: BaseMessage) -> None:
        all_messages = self.messages
        all_messages.append(message)

        # 🚨 触发摘要机制：如果对话超过 max_messages 条
        if len(all_messages) > self.max_messages:
            # 切割策略：保留最近的两轮对话（即 4 条 message），其余的历史记录投入“高压锅”进行提纯
            keep = 4
            messages_to_summarize = all_messages[:-keep]
            recent_messages = all_messages[-keep:]

            # 拼接待总结的文本，把更早前的系统摘要也一起合并炼丹（俗称滚雪球）
            text_to_summarize = "\n".join([f"{m.type}: {m.content}" for m in messages_to_summarize])
            
            # 编写摘要 Prompt
            summary_prompt = (
                "你是系统底层的 RAG 记忆中枢。请你进行“折叠式总结”。"
                "针对以下这段历史废话拉扯，提取其中达成共识的参数条件、工程场景特征以及最后决定的规范条目。"
                "绝不输出废话，控制在150字。：\n\n"
                f"{text_to_summarize}"
            )

            # 🧠 呼叫大模型进行脑力劳动
            print("\n🔄 [RAG-MemManager] 上下文逼近红线，正在执行冷酷的记忆洗牌...")
            summary_text = self.llm.invoke([SystemMessage(content=summary_prompt)]).content
            print(f"[RAG-MemManager] 获得高密结晶: {summary_text[:80]}...\n")

            # 重组历史：[系统摘要] + [最近的4轮对话]
            new_summary_message = SystemMessage(content=f"【前文情境摘要脉络】：{summary_text}\n请在回答最新提问时，不要遗忘上面的大背景事实。")
            all_messages = [new_summary_message] + recent_messages

        # 覆写保存
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump([message_to_dict(m) for m in all_messages], f)

    def clear(self) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump([], f)

# 暴露一个简单的清理函数给前端使用
def clear_history_by_id(session_id, storage_path="./chat_history"):
    import re
    if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
        raise ValueError("Invalid session_id format to prevent path traversal.")
    file_path = os.path.join(storage_path, session_id)
    if os.path.exists(file_path):
        os.remove(file_path)