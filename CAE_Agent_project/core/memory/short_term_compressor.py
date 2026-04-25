from langchain_openai import ChatOpenAI
from langchain_core.messages import RemoveMessage, SystemMessage, HumanMessage
from core.state_graph.state import CAEAgentState
from core import config 
import os

llm = ChatOpenAI(
    model=config.CHAT_MODEL, 
    api_key=config.DASHSCOPE_API_KEY, 
    base_url=config.OPENAI_API_BASE,
    temperature=0.1
)

def compressor_node(state: CAEAgentState):
    """滑窗摘要核心逻辑。拦截过长上下文，生成高密摘要并销毁冗余的原始流"""
    messages = state.get("messages", [])
    
    # 如果总消息没超过12条 (约6次对话往返)，则安然无恙，直接放行
    if len(messages) <= 12:
        return {}
        
    print(f"\n[MemManager] 🧹 警报！上下文已逼近红线 (当前量: {len(messages)})！启动自动瘦身修剪协议...")
    
    # 切割阈值：永远只保留最近的 4 条原句，其余的全砍！
    keep = 4
    old_messages = messages[:-keep]
    
    # 丢给专门的小脑进行极速浓缩
    prompt = "你是工程平台的记忆管理中枢。请你极为精炼地总结下面这些已经老旧的拉扯记录（150字以内）。最重要的是提取里面提到的数值、厚度、尺寸等工程参数字典以及你们达成的关键意图目标。\n\n"
    for msg in old_messages:
        role = "User" if isinstance(msg, HumanMessage) else "Agent"
        prompt += f"{role}: {msg.content}\n"
        
    try:
        summary_res = llm.invoke([SystemMessage(content=prompt)])
        new_summary = summary_res.content
        
        # 兼容连续总结的滚雪球机制
        existing_summary = state.get("context_summary", "")
        if existing_summary:
             # 如果雪球滚得太大了，也可以考虑交给 LLM 再次做二度融合
            final_summary = f"{existing_summary}\n\n[新增补充记忆]: {new_summary}"
        else:
            final_summary = new_summary
            
        print(f"[MemManager] 💾 提纯完毕！获得超密度记忆结晶：\n{new_summary[:80]}...")

        # 对旧时代残党下达清除令 (用 LangGraph 原生的神技 RemoveMessage)
        delete_orders = [RemoveMessage(id=m.id) for m in old_messages if m.id]
        
        return {"messages": delete_orders, "context_summary": final_summary}
        
    except Exception as e:
        print(f"[MemManager] 瘦身异常: {e}")
        return {}
