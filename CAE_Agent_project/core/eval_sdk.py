"""
EvalPlatform 通用探针 SDK (Universal Callback Handler)
=====================================================

零侵入式链路追踪：任何 LangChain/LangGraph Agent 只需挂载此回调，
即可自动将运行轨迹上报至 CAE Eval Platform，无需修改一行业务代码。

使用方式 (LangGraph)：
    from eval_sdk import EvalPlatformCallback

    callback = EvalPlatformCallback(
        server_url="http://localhost:8001",
        session_id="user_session_001"
    )
    agent.invoke(
        {"messages": [HumanMessage(content="你好")]},
        config={"callbacks": [callback]}
    )

使用方式 (LangChain)：
    from eval_sdk import EvalPlatformCallback

    callback = EvalPlatformCallback(server_url="http://localhost:8001")
    chain.invoke(query, config={"callbacks": [callback]})

设计原则：
    1. 零侵入 - 不修改任何 Agent 业务代码，通过 config 注入
    2. 静默降级 - 网络异常/API 不可达时绝不影响 Agent 主流程
    3. 自动截断 - 超长 Payload (>5000字符) 自动截断保护
    4. 生命周期自管理 - 自动识别顶层 Chain 的开始/结束，无需手动调用
    5. 复用安全 - Trace 结束后自动重置状态，同一实例可多次使用
"""

import time
import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Union
from uuid import UUID

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

logger = logging.getLogger("eval_sdk")

# ================================
# 常量
# ================================
MAX_PAYLOAD_LENGTH = 5000  # 超长 Payload 自动截断阈值（字符数）


def _safe_serialize(data: Any, max_length: int = MAX_PAYLOAD_LENGTH) -> str:
    """
    安全序列化任意对象为字符串，支持截断保护。
    兼容 LangChain 的 BaseMessage、dict、list、str 等常见类型。
    """
    try:
        if data is None:
            return "{}"

        if isinstance(data, str):
            text = data
        elif isinstance(data, BaseMessage):
            text = json.dumps(
                {"type": type(data).__name__, "content": data.content},
                ensure_ascii=False,
            )
        elif isinstance(data, list) and data and isinstance(data[0], BaseMessage):
            text = json.dumps(
                [{"type": type(m).__name__, "content": m.content} for m in data],
                ensure_ascii=False,
            )
        elif isinstance(data, (dict, list)):
            text = json.dumps(data, ensure_ascii=False, default=str)
        else:
            text = str(data)

        if len(text) > max_length:
            return text[:max_length] + f"...[TRUNCATED, total {len(text)} chars]"
        return text
    except Exception:
        return "<serialization_error>"


class EvalPlatformCallback(BaseCallbackHandler):
    """
    CAE Eval Platform 通用链路追踪回调探针。

    自动拦截 LangChain/LangGraph 的 Chain(Node)、Tool、LLM 三层执行事件，
    将结构化 Span 数据上报至 Eval Platform 的 FastAPI 采集端。

    Attributes:
        server_url: Eval Platform API 地址，默认 http://localhost:8001
        session_id: 会话标识，用于关联同一用户的多次对话
        timeout:    HTTP 请求超时（秒），默认 5s
        silent:     静默模式，True 时网络异常不抛出（默认 True）
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8001",
        session_id: str = "default",
        timeout: float = 5.0,
        silent: bool = True,
    ):
        super().__init__()
        self.server_url = server_url.rstrip("/")
        self.session_id = session_id
        self.timeout = timeout
        self.silent = silent

        # ---- Trace 生命周期状态 ----
        self._trace_id: Optional[str] = None
        self._root_run_id: Optional[UUID] = None  # 标识顶层 Chain
        self._total_tokens: int = 0
        self._final_response: str = ""

        # ---- Span 元数据暂存 (在 start 时捕获，在 end 时消费) ----
        # { run_id: {"name": ..., "type": ..., "start_time": ..., "input_data": ...} }
        self._span_meta: Dict[UUID, dict] = {}

        # ---- 队列与后台线程初始化 ----
        import queue
        import threading
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def _worker_loop(self):
        """后台线程：串行执行 HTTP POST 请求，不阻塞主流程"""
        client = httpx.Client(timeout=self.timeout)
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                # 设定超时以定期响应 stop_event
                import queue as q_mod
                item = self._queue.get(timeout=0.2)
            except q_mod.Empty:
                continue

            endpoint, payload = item
            try:
                resp = client.post(f"{self.server_url}{endpoint}", json=payload)
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"[EvalSDK] 后台数据上报失败 {endpoint}: {e}")
            finally:
                self._queue.task_done()
        try:
            client.close()
        except Exception:
            pass

    # ===========================
    # 内部 HTTP 上报
    # ===========================
    def _post(self, endpoint: str, payload: dict) -> None:
        """非阻塞：将请求写入队列由后台线程处理"""
        self._queue.put((endpoint, payload))

    def _report_span(
        self,
        run_id: UUID,
        output_data: Any,
        status: str = "SUCCESS",
        error_msg: str = "",
    ):
        """从暂存区取出元数据，组装完整 Span 并上报"""
        meta = self._span_meta.pop(run_id, None)
        if not meta or not self._trace_id:
            return

        self._post("/traces/span", {
            "trace_id": self._trace_id,
            "span_type": meta["type"],
            "span_name": meta["name"],
            "start_time": meta["start_time"],
            "end_time": time.time(),
            "input_data": meta["input_data"],
            "output_data": _safe_serialize(output_data),
            "status": status,
            "error_msg": error_msg,
        })

    # ===========================
    # Chain (Graph Node) 回调
    # ===========================
    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        chain_name = (
            kwargs.get("name")
            or serialized.get("name")
            or serialized.get("id", ["chain"])[-1]
        )

        # 顶层 Chain（无父节点）→ 开启 Trace
        if parent_run_id is None and self._trace_id is None:
            self._root_run_id = run_id
            user_query = self._extract_user_query(inputs)
            import uuid
            self._trace_id = str(uuid.uuid4())
            self._post("/traces/start", {
                "session_id": self.session_id,
                "user_query": user_query,
                "trace_id": self._trace_id,
            })

        # 暂存 Span 元数据（顶层 Chain 也记录，但最终只有子节点上报）
        self._span_meta[run_id] = {
            "name": chain_name,
            "type": "NODE",
            "start_time": time.time(),
            "input_data": _safe_serialize(inputs),
        }

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        # 非顶层节点 → 上报 Span
        if run_id != self._root_run_id:
            self._report_span(run_id, outputs)
        else:
            # 顶层 Chain 结束 → 清理暂存 & 关闭 Trace
            self._span_meta.pop(run_id, None)
            self._final_response = _safe_serialize(outputs)
            self._end_trace(success=True)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        if run_id != self._root_run_id:
            self._report_span(
                run_id, {}, status="ERROR", error_msg=str(error)[:1000]
            )
        else:
            self._span_meta.pop(run_id, None)
            self._end_trace(success=False)

    # ===========================
    # Tool 回调
    # ===========================
    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        tool_name = (
            kwargs.get("name")
            or serialized.get("name")
            or "unknown_tool"
        )
        self._span_meta[run_id] = {
            "name": tool_name,
            "type": "TOOL",
            "start_time": time.time(),
            "input_data": _safe_serialize(input_str),
        }

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._report_span(run_id, output)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._report_span(
            run_id, {}, status="ERROR", error_msg=str(error)[:1000]
        )

    # ===========================
    # LLM / ChatModel 回调
    # ===========================
    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        llm_name = (
            kwargs.get("name")
            or serialized.get("name")
            or serialized.get("id", ["llm"])[-1]
        )
        self._span_meta[run_id] = {
            "name": llm_name,
            "type": "LLM",
            "start_time": time.time(),
            "input_data": _safe_serialize(prompts),
        }

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """ChatModel (如 ChatOpenAI) 走此入口，而非 on_llm_start"""
        llm_name = (
            kwargs.get("name")
            or serialized.get("name")
            or serialized.get("id", ["chat_model"])[-1]
        )
        self._span_meta[run_id] = {
            "name": llm_name,
            "type": "LLM",
            "start_time": time.time(),
            "input_data": _safe_serialize(
                messages[0] if messages else []
            ),
        }

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        # 提取 Token 用量
        token_usage = {}
        if response.llm_output:
            token_usage = response.llm_output.get("token_usage", {})
            self._total_tokens += token_usage.get("total_tokens", 0)

        # 提取 LLM 输出文本
        output_text = ""
        if response.generations and response.generations[0]:
            output_text = response.generations[0][0].text

        self._report_span(run_id, {
            "text": output_text,
            "token_usage": token_usage,
        })

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        self._report_span(
            run_id, {}, status="ERROR", error_msg=str(error)[:1000]
        )

    # ===========================
    # 内部工具方法
    # ===========================
    def _extract_user_query(self, inputs: Any) -> str:
        """
        尝试从各种输入格式中提取用户问题。
        兼容 LangGraph (messages list) 和 LangChain (dict with input/query) 两种模式。
        """
        if isinstance(inputs, str):
            return inputs[:500]

        if isinstance(inputs, dict):
            # 优先检查常见 key
            for key in ("input", "question", "query", "user_input", "messages"):
                if key not in inputs:
                    continue
                val = inputs[key]
                if isinstance(val, str):
                    return val[:500]
                if isinstance(val, list) and val:
                    last = val[-1]
                    if isinstance(last, BaseMessage):
                        return last.content[:500]
                    if isinstance(last, dict):
                        return str(last.get("content", last))[:500]
                    return str(last)[:500]
            return str(inputs)[:500]

        return str(inputs)[:500]

    def _end_trace(self, success: bool = True):
        """结束当前 Trace 并重置状态（支持实例复用）"""
        if self._trace_id:
            self._post("/traces/end", {
                "trace_id": self._trace_id,
                "final_response": self._final_response or "",
                "success_flag": success,
                "total_tokens": self._total_tokens,
            })

        # 重置全部状态
        self._trace_id = None
        self._root_run_id = None
        self._total_tokens = 0
        self._final_response = ""
        self._span_meta.clear()

    def __del__(self):
        """析构时通知后台线程退出"""
        try:
            self._stop_event.set()
            self._worker_thread.join(timeout=2.0)
        except Exception:
            pass
