import streamlit as st  # 构建简易的前端网页
import uuid  # 引入 uuid 生成唯一标识
from rag import RagService # 引入写好的 RagService 类串联整个流程
from file_history_store import clear_history_by_id

st.set_page_config(page_title="CAE 仿真专家助手", layout="wide")
st.title("🛠️ CAE 智能客服与文档助手")
st.divider()  # 添加分隔线

# 👇 全局初始化 RagService 实例，仅首次加载时执行
@st.cache_resource(show_spinner="正在全局初始化大模型引擎与知识库...")
def init_rag_engine():
    return RagService()
rag_engine = init_rag_engine() # 👈 初始化 RagService 实例

# 👇 为当前用户（浏览器标签页）生成唯一的 session_id
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4()) # 例如：'e3b0c442-989b-464c-8693-...'

# 👇 初始化当前用户的聊天记录（如果不存在）
if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": "你好，我是专注于 CAE 领域的智能客服。请问有什么工程仿真方面的问题可以帮助你？"}]

with st.sidebar:
    st.header("⚙️ 系统管理")
    if st.button("🔄 同步最新知识库"):
        with st.spinner("正在对齐稀疏索引与向量库数据..."):
            rag_engine.retriever_service.sync_bm25_from_chroma()
            st.success("同步完成！检索器已就绪。")

    if st.button("🗑️ 清空当前对话"):
        clear_history_by_id(st.session_state["session_id"])
        st.session_state["messages"] = [{"role": "assistant", "content": "对话已清空，让我们重新开始吧！\n\n 你好，我是专注于 CAE 领域的智能客服。请问有什么工程仿真方面的问题可以帮助你？"}]
        st.rerun()

# 渲染历史聊天记录
for message in st.session_state["messages"]:
    st.chat_message(message["role"]).write(message["content"])

# 👇 处理用户输入
prompt = st.chat_input("在这里输入你的问题，例如：在 Abaqus 中材料屈服强度参数应该如何设置？")
if prompt:
    st.chat_message("user").write(prompt)
    st.session_state["messages"].append({"role": "user", "content": prompt})
    
    with st.chat_message("assistant"):
        with st.spinner("🧠 正在进行多路召回与交叉重排..."):
            
            # 动态构造属于当前用户的 config，覆盖掉全局的 session_id
            user_config = {
                "configurable": {
                    "session_id": st.session_state["session_id"]
                }
            }
            # 使用带缓存探测的增强流式方法
            res_stream = rag_engine.stream_with_cache(
                {"input": prompt}, 
                user_config 
            )
            full_response = st.write_stream(res_stream)                   
    st.session_state["messages"].append({"role": "assistant", "content": full_response})