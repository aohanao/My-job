# CAE Agent 项目 AI 前沿技术改进计划

## 架构愿景：从“运行态”走向“可评测态与自进化态”

在 LLM Agent 领域，**Harness Engineering（脚手架工程）** 核心是为了解决 Agent 项目“难评测、难调试、难复现”的问题。同时，结合当下极具代表性的开源 Agent 框架 **Hermes (由 Nous Research 发布)** 和 **OpenClaw** 的前沿设计理念，我们对 `CAE_Agent_project` 制定了以下深度升级方案：

---

## 第一部分：借鉴前沿 Agent 框架 (Hermes & OpenClaw)

### 1. 从“参数复用”走向“动态技能固化” (借鉴 Hermes)
*   **前沿理念**：Hermes 具有强大的“闭环学习系统”，当它成功完成任务后，会将成功的 Workflow 提炼并“硬编码”为未来可直接调用的“技能 (Skill)”。
*   **落地方案**：改造当前的 `experience_manager`。当 `Reflexion` 闭环跑通 Abaqus 后，新增 `Skill_Synthesizer` 节点，自动生成一段 Python 验证器代码并写入 `skills/your_scenario/validator.py`。下次遇到同类问题，系统在 `Extractor` 阶段即可直接拦截，无需大模型试错，实现真正的“系统级进化”。

### 2. 引入 FTS5 + 语义的双轨记忆流 (借鉴 Hermes)
*   **前沿理念**：不盲目迷信 Vector DB，采用 SQLite 的 FTS5（全文检索）与大模型总结相结合的长期记忆，擅长精确找回具体名词。
*   **落地方案**：当前使用 Chroma 处理工程场景时，对具体零件编号、Abaqus 错误代码（如 `Error Code 1044`）极度不敏感。建议在 `checkpoints.sqlite` 中新增开启了 FTS5 的虚拟表日志。遇到问题时，先用 FTS5 进行精确字符串匹配，再用向量进行语义补充，准确率会成倍提升。

### 3. 长生命周期任务的“休眠与唤醒”机制 (借鉴 OpenClaw)
*   **前沿理念**：OpenClaw 专为本地服务器设计，极度擅长处理超长生命周期的自治工作流，状态机允许 Agent 在等待外部慢工具时完全休眠。
*   **落地方案**：CAE 仿真通常耗时数小时。改造目前的 `Executor` 节点（当前会通过 `subprocess` 挂起导致进程一直等待），引入异步回调机制。触发 Abaqus 脚本后 Agent 提交 `WAITING` 状态并完全休眠；通过外部 Watchdog 监听计算结束后的 `.odb` 或 `.msg` 产出，随后唤醒 Agent 继续执行后处理逻辑，完美契合工业仿真场景。

### 4. 从“被动响应”转向“主动干预” (借鉴 Hermes)
*   **前沿理念**：内置 Crons 系统，Agent 可根据时间线或事件主动发起任务，而非永远被动等待人类输入 prompt。
*   **落地方案**：为 Agent 增加“眼睛”后台监控模块。当工程师向指定企业网盘上传新的 `.step` 几何模型时，Agent 自动被唤醒，分析模型并主动推送消息询问工程师是否需要启动一轮预仿真。

---

## 第二部分：Harness Engineering (评测与沙箱脚手架)

### 1. Evaluation Harness (自动化评测脚手架)
目前项目依赖人工验证 Agent 是否闭环，这是不可持续的。需要构建一套类似 SWE-bench 的自动化评测框架。
*   **构建 Benchmark 数据集**：在 `tests/fixtures/` 下建立标准化的评测集（如：100个隧道开挖参数提取测试用例），包含 `Prompt` 和 `Ground Truth`。
*   **自动化流水线集成**：编写批处理脚本让 Agent 自动遍历运行所有测试用例，并与 `CAE_Eval_Platform` 联动，自动推送轨迹 (Trace) 和耗时。
*   **评估指标量化**：除了 Ragas 打分，为 `SimPipelineFlow` 引入 **Reflexion 闭环成功率**（如：在 3 次纠错内成功生成可用脚本的比例）作为核心指标。

### 2. Sandbox Execution Harness (安全执行与 Mock 沙箱)
当前您的 `Executor` 节点依赖宿主机直接调用 Abaqus，这种硬编码方式在 CI/CD 测试和多并发评估中极其脆弱。
*   **引入 Dockerized Workspace**：针对生成的 CAE 脚本，拉起带有 Abaqus 环境的短生命周期 Docker 容器，执行完毕后销毁，实现**用完即弃**与**安全隔离**。
*   **CAE 引擎 Mock 模式**：为加速日常单元测试，当 `TEST_MODE=1` 时，沙箱拦截执行指令，不真正启动工业软件，而是**模拟抛出** `Abaqus Error Logs`，以此快速验证您的 `Critic` 和 `Reflexion` 节点的自愈能力。

### 3. Telemetry & Tracing Harness (无侵入探针与可观测性)
Harness 的一大特征是：**业务代码与监控代码解耦**。
*   **基于 Callback 的无侵入探针**：利用 LangChain/LangGraph 的 `BaseCallbackHandler` 实现 `CAEHarnessCallback`，自动监听各类事件，取代在节点代码内写死 `logger.info(...)`。
*   **MCP Trace 透传**：在与 `mcp_client` 交互时，确保 Trace ID 能够通过 MCP 协议层透传给远端的 RAG Server，实现全链路分布式追踪。

### 4. Testing Harness (开发测试脚手架)
从目前项目状态看，`tests/` 目录结构已建好但测试覆盖率为 0。
*   **LLM 响应录制与回放 (VCR for LLMs)**：引入 LLM Mock 库，首次跑通时录制 API 返回。后续执行 CI 测试时直接回放，节省 Token 费用，排除大模型波动造成的干扰。
*   **Pytest-Asyncio 深度集成**：为 LangGraph 的异步流编写专用 fixture，构建能自动管理 `thread_id` 和持久化检查点（Checkpoints SQLite）生命周期的测试装饰器。

---

## 第三部分：从 Claude Code 源码泄露事件中汲取的启示

近期 Anthropic 旗下的 Claude Code CLI 工具源码泄露事件（约 1900 个文件，超 50 万行核心代码暴露），向业界展示了商用级 Agent 的底层架构设计，其中有三个极具价值的安全与架构理念非常值得我们的仿真系统借鉴：

### 1. 动态系统提示词组装 (Dynamic Prompt Assembly)
*   **前沿启示**：Claude Code 从不使用冗长、写死的静态 Prompt。相反，它基于当前环境、操作权限和上下文，使用 `<system-reminder>` 等标签**动态组装**提示词。这不仅让 Agent 指令更精准，还能完美利用 Prompt Caching（提示词缓存）机制大幅削减成本。
*   **落地方案**：审视我们当前的 `Planner` 和 `Extractor` 节点，把静态 Prompt 重构为“积木式”。分离出“系统人设层 (Core Identity)”、“项目约束层 (如特定项目的 `CAE.md`)”和“动态物理规则层”。只在触发隧道场景时，才将隧道规则动态注入给大模型，不仅防幻觉，更能提速降本。

### 2. 细粒度权限管控与危险拦截 (Action Gating & Permission Boundaries)
*   **前沿启示**：泄露的源码揭示了 Claude Code 对操作系统有着极其严苛的权限分级网，特别是对高危 Shell 操作（如删除文件、强制提权）拥有命令白名单和强制阻断设计。
*   **落地方案**：我们的 `Executor` 节点如果直接在宿主机执行代码是极度危险的（甚至存在 Prompt Injection 攻击导致清空工程师电脑的风险）。必须全面学习其权限模型，在 `Executor` 执行仿真脚本前加入**命令白名单过滤器**与**敏感操作人工确认 (Human-in-the-loop) 机制**。

### 3. “思考-执行-验证”的原子级内省循环 (Agentic Loop & Introspection)
*   **前沿启示**：Claude Code 内部特有的后台自治机制（代号 "Kairos"），其核心在于执行完任何工具后，绝不盲目相信系统的状态，而是强制 Agent 自己去“读取刚才生成的文件”或“二次校验输出”，形成绝对严密的闭环。
*   **落地方案**：升级现有的 `Reflexion` 闭环。当 Abaqus 仿真结束后，不要仅仅通过“没有抛出异常代码”来判断成功。强制大模型自动调用一个专门的后处理探针去检查生成的 `.odb`（结果文件）的体积是否达到预期、关键节点应力是否符合物理常识，只有通过“双重交叉验证”，才算达成真正的仿真闭环。

---

## 🚀 落地实施建议 (Next Steps)

1.  **强化休眠机制**：优先引入 OpenClaw 的状态休眠机制，解决 CAE 仿真计算慢导致进程挂死的核心痛点。
2.  **开发 Tracing Harness**：将 `TraceLogger` 无侵入地挂载到 LangGraph 实例上，跑通主干流程并对接 `CAE_Eval_Platform`。
3.  **闭环防呆验证**：搭建 Mock 沙箱，模拟 Abaqus 报错，确保代码在无真实仿真引擎的环境下也能测试自我纠正逻辑。
4.  **持续进化体系**：在后续迭代中，逐步加入 FTS5 双轨记忆库，以及类似 Hermes 的动态技能固化 (Skill Synthesizer) 功能。
