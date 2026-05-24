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
    """滑窗摘要核心逻辑。新增水位线预警 (Harness Engineering)"""
    messages = state.get("messages", [])
    
    # --- 1. 探针设计：计算水位线 (近似估算 token) ---
    MAX_TOKENS = 8000  # 假设窗口设计容量
    WARNING_THRESHOLD = 0.40  # 40% 预警线
    
    current_chars = sum(len(m.content) for m in messages if hasattr(m, 'content') and isinstance(m.content, str))
    # 粗略估算：中文和英文混合环境，1 token 约等于 2-3 个字符，我们按保守 2 字符估算
    estimated_tokens = current_chars / 2.0
    usage_percent = min(estimated_tokens / MAX_TOKENS, 1.0)
    
    is_warning = usage_percent >= WARNING_THRESHOLD
    
    state_updates = {
        "context_usage_percent": usage_percent,
        "context_warning": is_warning
    }
    
    if is_warning:
        print(f"\n[MemManager] ⚠️ 触发 Harness 预警机制: 上下文水位 {usage_percent*100:.1f}%，超过安全阈值 {WARNING_THRESHOLD*100}%！")

    # --- 2. 物理截断：消息数超过上限时触发 ---
    if len(messages) <= 12:
        return state_updates
        
    print(f"\n[MemManager] 🧹 上下文消息数 (当前: {len(messages)}) 触顶，启动深度瘦身修剪协议...")
    
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

        # 对旧时代残党下达清除令
        delete_orders = [RemoveMessage(id=m.id) for m in old_messages if m.id]
        
        state_updates["messages"] = delete_orders
        state_updates["context_summary"] = final_summary
        
        return state_updates
        
    except Exception as e:
        print(f"[MemManager] 瘦身异常: {e}")
        return state_updates
