# 可观测平台
import streamlit as st
import sqlite3
import pandas as pd
import json
import plotly.express as px
import plotly.graph_objects as go
from db_models import init_db
import eval_config
import numpy as np
import streamlit.components.v1 as components



st.set_page_config(page_title="AgentOps 监控大盘", page_icon="📡", layout="wide")

# ==========================================
# 🎨 视觉风格与全局样式 (Custom CSS)
# ==========================================
def apply_custom_style():
    st.markdown("""
        <style>
        /* 🌌 极光暗调网格背景 (Premium Mesh Gradient) */
        .stApp {
            background-color: #030712;
            background-image: 
                radial-gradient(at 0% 0%, rgba(30, 58, 138, 0.5) 0px, transparent 50%),
                radial-gradient(at 100% 0%, rgba(88, 28, 135, 0.4) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(30, 58, 138, 0.5) 0px, transparent 50%),
                radial-gradient(at 0% 100%, rgba(88, 28, 135, 0.4) 0px, transparent 50%),
                radial-gradient(at 50% 50%, rgba(15, 23, 42, 1) 0px, transparent 80%);
            background-attachment: fixed;
            color: #f8fafc;
        }

        /* 🪟 高级玻璃拟态卡片 (Enhanced Glassmorphism) */
        .metric-card {
            background: rgba(255, 255, 255, 0.02);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            padding: 24px;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
            transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            margin-bottom: 20px;
            position: relative;
            overflow: hidden;
        }
        .metric-card::before {
            content: "";
            position: absolute;
            top: 0; left: -100%;
            width: 100%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.05), transparent);
            transition: 0.5s;
        }
        .metric-card:hover::before {
            left: 100%;
        }
        .metric-card:hover {
            transform: translateY(-5px);
            border: 1px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 8px 32px rgba(99, 102, 241, 0.15);
            background: rgba(255, 255, 255, 0.04);
        }
        
        .metric-label {
            color: #94a3b8;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }
        .metric-value {
            color: #f8fafc;
            font-size: 2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #fff 0%, #94a3b8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        /* 🎰 Token 数字滚动滚动动效 */
        .token-ticker {
            display: inline-block;
            overflow: hidden;
            vertical-align: bottom;
            animation: ticker-fade 2s ease-out;
        }
        @keyframes ticker-fade {
            0% { transform: translateY(20px); opacity: 0; }
            100% { transform: translateY(0); opacity: 1; }
        }
        
        /* 🌊 连接线动画 */
        .line-glow {
            filter: drop-shadow(0 0 3px rgba(129, 140, 248, 0.4));
        }


        /* 其他元素优化 */

        .stSelectbox div[data-baseweb="select"] {
            background-color: rgba(255, 255, 255, 0.05) !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            border-radius: 12px !important;
        }
        header, .stToolbar { background: transparent !important; }
        h1, h2, h3 {
            font-weight: 800 !important;
            letter-spacing: -0.5px !important;
        }
        </style>
    """, unsafe_allow_html=True)


apply_custom_style()

DB_PATH = eval_config.DB_PATH

# 🚀 启动时确保数据库架构完整
init_db(DB_PATH)

def get_db_connection():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        st.error(f"无法连接数据库：{e}")
        return None

# ==========================================
# 🧱 UI 组件函数
# ==========================================
def ui_metric_card(label, value, is_token=False):
    content = f'<div class="token-ticker">{value}</div>' if is_token else value
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{content}</div>
        </div>
    """, unsafe_allow_html=True)


st.title("📡 AgentOps 智能体可观测与评估大盘")
st.markdown("这里集中展示了 CAE Agent 的全链路运行轨迹（Traces）、资源开销与自动化评估得分。")

conn = get_db_connection()
if not conn:
    st.stop()

# ==========================================
# 核心指标区 (KPI)
# ==========================================
st.subheader("整体运行健康度")
col1, col2, col3, col4 = st.columns(4)

df_traces = pd.read_sql_query("SELECT * FROM run_trace ORDER BY timestamp DESC", conn)

if not df_traces.empty:
    total_runs = len(df_traces)
    success_runs = len(df_traces[df_traces['success_flag'] == 1])
    success_rate = (success_runs / total_runs) * 100 if total_runs > 0 else 0
    total_tokens = df_traces['total_tokens'].sum()
    
    # 计算平均耗时 (算法：Max(Span End) - Trace Start)
    latency_query = """
        SELECT AVG(max_end - start) as avg_latency
        FROM (
            SELECT t.timestamp as start, MAX(s.end_time) as max_end
            FROM run_trace t
            JOIN trace_span s ON t.trace_id = s.trace_id
            GROUP BY t.trace_id
        )
    """
    df_latency = pd.read_sql_query(latency_query, conn)
    avg_latency = df_latency['avg_latency'].iloc[0] if not df_latency.empty and df_latency['avg_latency'].iloc[0] else 0
    
    with col1:
        ui_metric_card("总调用次数 (Total Runs)", total_runs)
    with col2:
        ui_metric_card("任务闭环率 (Success Rate)", f"{success_rate:.1f}%")
    with col3:
        ui_metric_card("累计Token消耗 (Total Tokens)", f"{total_tokens:,}", is_token=True)
    with col4:
        ui_metric_card("平均耗时 (Avg Latency)", f"{avg_latency:.2f}s")

else:
    st.info("尚无监控数据，请在 Agent 侧发起一次对话。")
    st.stop()

st.markdown("---")

# ==========================================
# 链路追踪瀑布流 (Trace Timeline Explorer)
# ==========================================
st.subheader("🔍 链路详情探查器 (Trace Explorer)")

# 选择要查看的 Session / Trace
trace_options = df_traces['trace_id'].tolist()
selected_trace_id = st.selectbox("选择一次追踪记录 (Trace ID):", trace_options)

if selected_trace_id:
    trace_info = df_traces[df_traces['trace_id'] == selected_trace_id].iloc[0]
    
    # 提取所有 Spans
    df_spans = pd.read_sql_query(f"SELECT * FROM trace_span WHERE trace_id = '{selected_trace_id}' ORDER BY start_time ASC", conn)
    
    # 计算该次 Trace 的真实耗时
    trace_latency = 0
    if not df_spans.empty:
        trace_latency = df_spans['end_time'].max() - trace_info['timestamp']
    
    # --- 指标行 ---
    c1, c2, c3 = st.columns(3)
    with c1:
        ui_metric_card("本次消耗 Token", trace_info['total_tokens'])
    with c2:
        ui_metric_card("本次总耗时", f"{trace_latency:.2f}s")
    with c3:
        ui_metric_card("会话 ID", trace_info['session_id'])
    
    st.markdown(f"""
        <div class="metric-card">
            <div style="color:#94a3b8; font-size:0.9rem; margin-bottom:8px;">用户请求 (User Query)</div>
            <div style="font-size:1.1rem; color:#f8fafc; margin-bottom:16px;">{trace_info['user_query']}</div>
            <div style="color:#94a3b8; font-size:0.9rem; margin-bottom:8px;">最终输出 (Final Response)</div>
            <div style="font-size:1.1rem; color:#f8fafc;">{trace_info['final_response']}</div>
        </div>
    """, unsafe_allow_html=True)
    
    status_color = "#22c55e" if trace_info['success_flag'] else "#ef4444"
    status_text = "✅ 成功" if trace_info['success_flag'] else "❌ 失败"
    st.markdown(f"状态: <span style='color:{status_color}; font-weight:bold;'>{status_text}</span>", unsafe_allow_html=True)
    
    if not df_spans.empty:
        # -----------------------------------------------------
        # 1. 绘制动态增长瀑布流 (Plotly Animated Frames)
        # -----------------------------------------------------
        st.markdown("#### ⏱️ 执行链路瀑布流 (Waterfall Timeline)")

        
        # 准备数据：计算相对时间
        min_start = df_spans['start_time'].min()
        max_end = df_spans['end_time'].max()
        total_duration = max_end - min_start
        
        df_spans['rel_start'] = df_spans['start_time'] - min_start
        df_spans['rel_end'] = df_spans['end_time'] - min_start
        df_spans['actual_duration'] = df_spans['rel_end'] - df_spans['rel_start']
        
        # 确保顺序：最早的在顶端
        df_spans = df_spans.sort_values('start_time', ascending=True)
        span_names_ordered = df_spans['span_name'].tolist()
        
        color_map = {
            "NODE": "#818cf8", 
            "TOOL": "#34d399", 
            "LLM": "#fb7185",  
            "ERROR": "#f43f5e"
        }

        # 生成动画帧 (30帧)
        num_frames = 30
        time_steps = np.linspace(0, total_duration, num_frames)
        
        frames = []
        for t in time_steps:
            # 计算当前时刻每个条形的显示长度
            df_frame = df_spans.copy()
            df_frame['current_len'] = df_frame.apply(
                lambda row: max(0, min(row['rel_end'], t) - row['rel_start']) if row['rel_start'] <= t else 0, 
                axis=1
            )
            
            # 准备连接线数据 (Connection Lines)
            line_x = []
            line_y = []
            for i in range(len(df_frame) - 1):
                row_current = df_frame.iloc[i]
                row_next = df_frame.iloc[i+1]
                # 只有当下一个节点已经开始(或即将开始)且上一个节点有进度时才画线
                if t >= row_next['rel_start']:
                    # 从上一个节点的结束点(或当前进度点) 连到 下一个节点的起点
                    line_x.extend([row_current['rel_end'], row_next['rel_start'], None])
                    line_y.extend([row_current['span_name'], row_next['span_name'], None])

            frames.append(go.Frame(
                data=[
                    # 条形图 Trace
                    go.Bar(
                        y=df_frame['span_name'],
                        x=df_frame['current_len'],
                        base=df_frame['rel_start'],
                        orientation='h',
                        marker_color=[color_map.get(stype, "#94a3b8") for stype in df_frame['span_type']],
                        text=df_frame.apply(lambda r: f"{r['current_len']:.2f}s" if r['current_len'] > 0 else "", axis=1),
                        textposition='inside',
                        insidetextanchor='start',
                        hovertemplate="<b>%{y}</b><br>耗时: %{x:.2f}s<extra></extra>"
                    ),
                    # 连接线 Trace
                    go.Scatter(
                        x=line_x,
                        y=line_y,
                        mode='lines',
                        line=dict(color='rgba(129, 140, 248, 0.4)', width=1, dash='dot'),
                        hoverinfo='skip'
                    )
                ],
                name=f"t_{t:.2f}"
            ))

        # 构建基础图表
        fig = go.Figure(
            data=[
                go.Bar(
                    y=df_spans['span_name'],
                    x=[0] * len(df_spans),
                    base=df_spans['rel_start'],
                    orientation='h',
                    marker=dict(line=dict(width=0))
                ),
                go.Scatter(x=[], y=[], mode='lines') # 占位 Scatter Trace
            ],

            layout=go.Layout(
                yaxis=dict(title=None, categoryorder="array", categoryarray=span_names_ordered[::-1], gridcolor='rgba(255,255,255,0.03)'),
                xaxis=dict(title="执行时长 (s)", range=[0, total_duration * 1.05], gridcolor='rgba(255,255,255,0.03)'),
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color="#f8fafc",
                height=max(350, 150 + len(df_spans)*40),
                margin=dict(l=10, r=10, t=10, b=10),
                showlegend=False,
                updatemenus=[{
                    "buttons": [
                        {
                            "args": [None, {"frame": {"duration": 150, "redraw": True}, "fromcurrent": True, "transition": {"duration": 100, "easing": "linear"}}],
                            "label": "Play",
                            "method": "animate"
                        }
                    ],
                    "direction": "left",
                    "pad": {"r": 10, "t": 70},
                    "showactive": False,
                    "type": "buttons",
                    "x": -0.1, # 移出可视区域
                    "y": 0
                }],
                sliders=[{
                    "active": 0,
                    "yanchor": "top",
                    "xanchor": "left",
                    "currentvalue": {
                        "font": {"size": 14, "color": "#818cf8"}, 
                        "prefix": "⏱️ 执行回放: ", 
                        "visible": True, 
                        "xanchor": "left"
                    },
                    "transition": {"duration": 100, "easing": "cubic-in-out"},
                    "pad": {"b": 10, "t": 40},
                    "len": 1.0,
                    "x": 0,
                    "y": 0,
                    "activebgcolor": "#818cf8",
                    "bgcolor": "rgba(255, 255, 255, 0.05)",
                    "bordercolor": "rgba(255, 255, 255, 0.1)",
                    "tickcolor": "rgba(255, 255, 255, 0.2)",
                    "font": {"color": "#64748b", "size": 9},
                    "steps": [
                        {
                            "args": [[f.name], {"frame": {"duration": 100, "redraw": True}, "mode": "immediate", "transition": {"duration": 50, "easing": "linear"}}],
                            "label": f"{float(f.name.split('_')[1]):.1f}s",
                            "method": "animate"
                        } for f in frames
                    ]
                }]
            ),
            frames=frames
        )

        st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})
        
        # 🧪 自动触发播放的脚本
        components.html(
            """
            <script>
            function tryPlay() {
                const buttons = window.parent.document.querySelectorAll('.updatemenu-button');
                for (const btn of buttons) {
                    if (btn.textContent.includes('Play')) {
                        btn.click();
                        console.log('Plotly Autoplay Triggered');
                        return;
                    }
                }
                setTimeout(tryPlay, 500);
            }
            tryPlay();
            </script>
            """,
            height=0
        )





        # -----------------------------------------------------
        # 2. 节点级 I/O 联动面板 (Linked Detail Panel)
        # -----------------------------------------------------
        st.markdown("#### 🗂️ 节点联动观测面板")
        
        df_spans['dropdown_label'] = df_spans.apply(lambda x: f"{x['span_name']} ({x['span_type']})", axis=1)
        span_options = df_spans['dropdown_label'].tolist()
        selected_label = st.selectbox("🎯 快速聚焦节点:", span_options, index=0)
        
        if selected_label:
            selected_span = df_spans[df_spans['dropdown_label'] == selected_label].iloc[0]
            span_duration = selected_span['end_time'] - selected_span['start_time']
            
            st.markdown(f"""
                <div class="metric-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                        <span style="font-size:1.2rem; font-weight:bold; color:#f8fafc;">📍 {selected_span['span_name']}</span>
                        <span style="background:rgba(99, 102, 241, 0.2); padding:4px 12px; border-radius:12px; font-size:0.85rem; color:#818cf8;">{selected_span['span_type']}</span>
                    </div>
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px; color:#94a3b8; font-size:0.9rem;">
                        <div>状态: <span style="color:#f8fafc;">{selected_span['status']}</span></div>
                        <div>耗时: <span style="color:#f8fafc;">{span_duration:.2f}s</span></div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            def safe_render_json(container, data_str):
                if data_str is None:
                    container.code("None", language='json')
                    return
                try:
                    parsed = json.loads(data_str)
                    if isinstance(parsed, (dict, list)):
                        container.json(parsed)
                    else:
                        container.code(str(parsed), language='json')
                except Exception:
                    container.code(str(data_str), language='json')

            col_in, col_out = st.columns(2)
            with col_in:
                st.write("📥 **输入载荷 (Input Payload):**")
                container = st.container(border=True)
                safe_render_json(container, selected_span['input_data'])
            
            with col_out:
                st.write("📤 **输出载荷 (Output Payload):**")
                container = st.container(border=True)
                safe_render_json(container, selected_span['output_data'])
    else:
        st.warning("该 Trace 未记录任何被执行的子节点 Span。")

st.markdown("---")
# ==========================================
# RAGAS 评估监控舱
# ==========================================
st.subheader("💡 知识库质量监控舱 (RAGAS Quality Metrics)")

df_eval = pd.read_sql_query("SELECT trace_id, metric_name, score, timestamp FROM eval_score WHERE metric_name LIKE 'ragas_%' ORDER BY timestamp DESC", conn)

if not df_eval.empty:
    st.write("近期的 RAG 检索评分结果（使用 RAGAS 官方体系）：")
    
    avg_scores = df_eval.groupby("metric_name")["score"].mean().reset_index()
    c1, c2 = st.columns(2)
    with c1:
        f_score = avg_scores[avg_scores['metric_name'] == 'ragas_faithfulness']
        f_val = f_score['score'].values[0] if not f_score.empty else 0.0
        st.metric("平均忠实度 (Faithfulness)", f"{f_val:.2f} / 1.0", help="模型是否完全基于检索到的文档生成答案，无幻觉。")
    with c2:
        r_score = avg_scores[avg_scores['metric_name'] == 'ragas_answer_relevancy']
        r_val = r_score['score'].values[0] if not r_score.empty else 0.0
        st.metric("平均回答相关度 (Answer Relevancy)", f"{r_val:.2f} / 1.0", help="生成的答案是否精准回答了用户的提问，无废话。")
        
    st.write("📊 评分历史明细表：")
    st.dataframe(df_eval, width="stretch")
else:
    st.info("尚未发现 RAGAS 评测数据。请在后台运行 `python ragas_evaluator.py` 触发自动打分流。")

conn.close()