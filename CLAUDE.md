# My-job — CAE 智能体生态项目

## 项目总览

这是一个面向 **CAE（计算机辅助工程）仿真领域**的 AI 智能体生态系统，由 4 个相互协同的项目组成，实现了从知识检索、智能体决策、仿真执行到质量评估的完整闭环。

```
My-job/
├── CAE_RAG_project/        # 📚 知识引擎 — 工业级 RAG 检索系统
├── CAE_Agent_project/      # 🧠 决策引擎 — 多智能体仿真协作架构
├── CAE_Eval_Platform/      # 📊 评估中枢 — 可观测性与 RAG 质量治理平台
└── Tunnel_GraphRag/        # 🕸️ 知识图谱 — GraphRAG 隧道工程演示
```

---

## 项目一：CAE_RAG_project — 工业级仿真工程 RAG 专家系统

**定位**：专为 CAE 领域打造的检索增强生成（RAG）系统，提供工程知识检索服务。

### 核心架构
```
CAE_RAG_project/
├── app.py                    # Streamlit 对话门户（流式响应 + 运维侧边栏）
├── rag.py                    # RAG 核心总线（LCEL 编排：查询重写 → 检索 → 生成）
├── knowledge_base.py         # 向量知识库（ChromaDB + 混合分块 + VLM 视觉注入）
├── file_uploader.py          # 数据入库（PDF/Word/MD 多模态解析 + MD5 去重）
├── file_history_store.py     # 会话记忆管理（滑窗摘要压缩 + 并发文件安全锁）
├── mcp_server_entry.py       # MCP 外部接口（SSE 传输，暴露给 Agent 调用）
├── config_data.py            # 全局配置中心（API Key / 模型 / 检索阈值）
├── semantic_cache.py         # 语义缓存（含 TTL 时效与 LRU 淘汰，0-Token 秒回）
├── retriever_service.py      # 混合检索引擎（双路召回 + BGE重排，含 BM25 序列化热更新）
├── evaluate/                 # 离线评估（Golden Dataset + RAGAS 评测）
└── data/                     # ChromaDB 向量库 + 语义缓存数据
```

### 技术栈
| 组件 | 技术选型 |
|:---|:---|
| 编排 | LangChain / LCEL |
| 大模型 | 阿里百炼 (Qwen-Max/Turbo/VL) |
| 向量库 | ChromaDB |
| 检索 | Jieba + Rank-BM25 + BGE Cross-Encoder 重排 |
| 解析 | Marker (PDF) + Unstructured (Word) |
| Web | Streamlit |

### 工作流程
1. **知识入库**：文件上传 → MD5 指纹校验 → 多模态解析 → 层次化切片 → 向量化入库
2. **在线推理**：用户提问 → 语义缓存探测 → 查询重写 → 多路召回 (向量 + BM25) → RRF 融合 → Cross-Encoder 重排 → LLM 生成答复

---

## 项目二：CAE_Agent_project — 基于 Reflexion 的多智能体仿真协作架构

**定位**：专为高精度 CAE 仿真设计的反思型多智能体系统，实现从意图识别到仿真后处理的端到端自动化。

### 核心架构
```
CAE_Agent_project/
├── core/                       # 🧠 核心引擎层
│   ├── memory/                 # 双记忆架构：短期压缩 + 长期经验向量库
│   ├── state_graph/            # LangGraph 状态机编排 (Nodes, State, cae_agent)
│   ├── config.py               # 单一事实来源 (SSOT) 配置
│   ├── skills.py               # 技能插件加载器
│   ├── skill_harvester.py      # 🚀 TDD-QA 技能自动沉淀与封装中枢
│   ├── eval_sdk.py             # 零侵入评估回调探针
│   └── path_utils.py           # 路径工具
├── skills/                     # 🛠️ 联邦化技能插件层 (隧道/冲击等场景)
├── integrations/               # 🔌 外部集成层
│   ├── mcp_client/             # MCP 客户端 (Provider + Manager + Server)
│   └── cae_host_bridge/        # 宿主机 Abaqus 网关
├── web/                        # 🌐 Web 交互层 (FastAPI 后端 + 赛博朋克前端)
├── sandbox/                    # 仿真沙箱 (脚本生成 + 执行隔离)
├── main.py                     # CLI 终端入口
└── .data/                      # SQLite 状态持久化
```

### 系统拓扑 (Workflow)
```
用户输入 → Compressor (记忆压缩) → Planner (意图分流)
  ├─ chat → ChatNode (ReAct 工具循环: MCP/本地工具查询)
  └─ simulate → SimPipeline (仿真自愈闭环)
       ├─ Extractor (参数提取 + TDD 参数断言校验)
       ├─ Coder (Jinja2 模板渲染 + TDD 代码规范断言)
       └─ Executor (沙箱执行 + TDD 结果物理数值断言)
            └─ 失败 → 报错回流 → Extractor (Reflexion 自修正)
```

### 关键设计
- **Reflexion 闭环**：不信任一次性输出，Critic 节点作为物理准入闸门，失败时回灌修正。
- **Simulation-TDD 断言约束**：在 CriticParams、CriticCode、CriticResult 节点中引入 TDD 开发流程，动态加载各 Skill 下的 `tdd_test.py` 进行参数、代码和物理结果的硬断言（Assert），以红灯报错回灌机制驱动 Agent 自动进化。
- **Autonomous Skill Harvester (TDD-QA 技能自动沉淀)**：**[New]** 支持工程师上传经过验证的 Python 仿真代码，智能体自动提取参数特征，生成对应的 Pydantic Schema、边界限制 Validator、Jinja2 模板、TDD 断言套件及 Markdown 文档，并在临时沙箱内进行 TDD 闭环绿灯校验后，热注册进技能库中，实现技能横向自繁殖。
- **双记忆架构**：短期滑窗压缩 (12条针对会话上限的压缩阈值) + 长期全局经验向量库 (ChromaDB, 跨会话闪回与低置信度淘汰)。
- **联邦化插件**：新增仿真技能只需在 `skills/` 下添加文件夹并实现参数提取 Schema、Jinja 模板、Validator 与 `tdd_test.py`。
- **MCP 协议**：支持 Stdio (本地材料库) + SSE (远程 RAG 服务) 双传输模式。
- **沙箱隔离**：Abaqus 脚本在独立沙箱执行，日志实时捕获异常回传自愈。

### 技术栈
| 组件 | 技术选型 |
|:---|:---|
| 编排 | LangGraph (有向状态图 + 循环控制) |
| 状态持久化 | AsyncSqliteSaver (SQLite) |
| LLM | LangChain-OpenAI (兼容百炼) |
| 模板 | Jinja2 |
| API | FastAPI + Uvicorn |
| 向量库 | ChromaDB |

---

## 项目三：CAE_Eval_Platform — CAE 可观测性与 RAG 质量治理中枢

**定位**：面向 CAE 智能体的工业级监控评估平台，解决 RAG 质量难量化、幻觉难监控的痛点。

### 核心架构
```
CAE_Eval_Platform/
├── api_server.py           # FastAPI 采集服务 + 静态资源 (端口 8001)
├── static/index.html       # 极客霓虹暗黑科技大盘 (Vue.js + Chart.js)
├── eval_sdk.py             # 零侵入回调探针 SDK (LangChain Callback)
├── db_models.py            # SQLite 表结构 + TraceLogger 探针
├── eval_config.py          # 全局配置 (.env 管理)
├── evaluator.py            # LLM-as-a-Judge 意图/工具评估引擎
├── ragas_evaluator.py      # RAGAS 框架 RAG 质量评估引擎
├── dashboard.py            # Streamlit 可视化监控 (备用)
├── reset_eval.py           # 评估数据重置工具
└── traces.db               # SQLite 运行时数据库
```

### 数据库设计 (三表)
| 表名 | 用途 |
|:---|:---|
| `run_trace` | 完整用户请求生命周期 (trace_id, session_id, tokens, query, response) |
| `trace_span` | 每跳执行详情 (NODE/TOOL/LLM, input/output, 耗时, 状态) |
| `eval_score` | 自动化评分结果 (metric_name, score, reason) |

### 三位一体架构
```
1. 离线优化 (RAG Project) — Golden Dataset → RAG 引擎 → RAGAS 离线评测
2. 业务集成 (Agent Project) — 用户请求 → CAE Agent → 异步上报轨迹 → 探针 SDK
3. 在线审计 (Eval Platform) — Trace → SQLite → RAGAS 在线审计 → FastAPI 大盘
```

### 技术栈
| 组件 | 技术选型 |
|:---|:---|
| API | FastAPI + Uvicorn |
| 评估 | RAGAS 框架 + LLM-as-a-Judge |
| 存储 | SQLite |
| 可视化 | Streamlit + Plotly / Vue.js + Chart.js |
| 探针 | LangChain Callback (零侵入) |

---

## 项目四：Tunnel_GraphRag — GraphRAG 隧道工程知识图谱演示

**定位**：基于图数据库的 RAG 系统，面向隧道工程领域的知识图谱构建与检索。

### 核心架构
```
Tunnel_GraphRag/
├── main.py                   # GraphRAG 主程序 (SimpleGraphRAG 类)
├── test_llm.py               # LLM 连接测试
├── input/tunnel_project.txt  # 隧道工程输入文档
├── output/                   # 图谱状态 + Pyvis 可视化
├── lib/                      # 前端可视化库 (vis-network, tom-select)
└── requirements.txt
```

### 工作流程
1. **实体关系提取**：LLM 从文本提取实体 (name, type) 和关系 (source, target, description)
2. **图构建**：NetworkX 构建知识图谱
3. **社区发现**：Louvain 算法自动聚类相关实体
4. **社区摘要**：LLM 为每个社区生成语义摘要 (Global Search 基础)
5. **双模搜索**：
   - **Local Search**：匹配节点 + 一度邻居扩展
   - **Global Search**：汇总所有社区摘要回答
6. **可视化**：Pyvis 生成交互式 HTML 图谱

### 技术栈
| 组件 | 技术选型 |
|:---|:---|
| 图数据库 | NetworkX |
| LLM | OpenAI SDK (兼容百炼 DashScope) |
| 社区发现 | python-louvain |
| 可视化 | Pyvis (vis.js) |
| 配置 | python-dotenv |

---

## 项目间协作关系

```
                    ┌─────────────────┐
                    │  Tunnel_GraphRag │
                    │  (知识图谱探索)   │
                    └────────┬────────┘
                             │ 概念验证
                             ▼
┌──────────────┐    MCP SSE    ┌───────────────┐    eval_sdk    ┌──────────────────┐
│ CAE_RAG      │ ◄──────────► │ CAE_Agent     │ ◄────────────► │ CAE_Eval         │
│ (知识检索引擎) │   工具调用    │ (决策与执行引擎) │   轨迹上报     │ (评估与监控平台)  │
└──────────────┘               └───────┬───────┘                 └──────────────────┘
        │                              │
        │ 向量化知识                    │ Abaqus 仿真
        ▼                              ▼
   [ChromaDB]                     [sandbox/ 沙箱]
```

- **CAE_RAG** 通过 MCP SSE 协议为 **CAE_Agent** 提供专业知识检索工具
- **CAE_Agent** 通过 `eval_sdk` 零侵入探针向 **CAE_Eval_Platform** 上报执行轨迹
- **CAE_Eval_Platform** 对 Agent 运行质量进行 LLM-as-a-Judge 和 RAGAS 自动化评估
- **Tunnel_GraphRag** 是知识图谱方向的独立探索项目

---

## 通用配置

所有项目使用 **阿里百炼 DashScope** 作为 LLM 后端：
- `OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1`
- 模型：qwen-max / qwen-turbo / qwen-plus / qwen-vl-max
- Embedding：text-embedding-v4

各项目通过 `.env` 文件配置 `DASHSCOPE_API_KEY` 和模型参数。
