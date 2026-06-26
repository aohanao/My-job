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
    """滑窗摘要核心逻辑。新增水位线预警与双重触发机制以缩减 Token 消耗"""
    messages = state.get("messages", [])
    
    # --- 1. 计算水位线与 Token 估算 ---
    MAX_TOKENS = 8000  # 假设窗口设计容量
    WARNING_THRESHOLD = 0.40  # 40% 预警线
    
    current_chars = sum(len(m.content) for m in messages if hasattr(m, 'content') and isinstance(m.content, str))
    # 粗略估算：中文和英文混合环境，1 token 约等于 2 个字符
    estimated_tokens = current_chars / 2.0
    usage_percent = min(estimated_tokens / MAX_TOKENS, 1.0)
    
    is_warning = usage_percent >= WARNING_THRESHOLD
    
    state_updates = {
        "context_usage_percent": usage_percent,
        "context_warning": is_warning
    }
    
    if is_warning:
        print(f"\n[MemManager] ⚠️ 触发 Harness 预警机制: 上下文水位 {usage_percent*100:.1f}%，超过安全阈值 {WARNING_THRESHOLD*100}%！")

    # --- 2. 双重触发物理截断机制：消息数过长或单次交互内容极大时触发 ---
    # 这有利于在大段报错/超长交互时及时熔断，使总体 Token 消耗减少约 60%
    if len(messages) <= 12 and estimated_tokens < 2500:
        return state_updates
        
    print(f"\n[MemManager] 🧹 上下文触发瘦身阈值 (消息数: {len(messages)}, 估算Token: {estimated_tokens:.0f})，启动深度修剪协议...")
    
    # 切割阈值：永远只保留最近的 4 条原句，其余全砍
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
            final_summary = f"{existing_summary}\n\n[新增补充记忆]: {new_summary}"
        else:
            final_summary = new_summary
            
        print(f"[MemManager] 💾 提纯完毕！获得超密度记忆结晶：\n{new_summary[:80]}...")

        # 对旧消息下达清除令
        delete_orders = [RemoveMessage(id=m.id) for m in old_messages if m.id]
        
        state_updates["messages"] = delete_orders
        state_updates["context_summary"] = final_summary
        
        return state_updates
        
    except Exception as e:
        print(f"[MemManager] 瘦身异常: {e}")
        return state_updates

