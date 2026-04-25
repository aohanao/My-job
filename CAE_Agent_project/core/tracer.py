import time
import uuid
import json
import os
import httpx
from typing import Any

# 🌟 从环境变量获取评估平台 API 地址
EVAL_API_URL = os.environ.get("EVAL_API_URL", "http://127.0.0.1:8001")

class TraceLogger:
    """Agent 端使用的探针 SDK，将运行状态上报至远程监控服务"""
    def __init__(self, api_base_url: str = EVAL_API_URL):
        self.api_url = api_base_url.rstrip("/")
        print(f"[Tracer] 🚀 初始化监控上报，目标 API: {self.api_url}")
        
    def start_trace(self, session_id: str, user_query: str) -> str:
        """开启一个新的追踪记录"""
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.post(
                    f"{self.api_url}/traces/start",
                    json={"session_id": session_id, "user_query": user_query}
                )
                resp.raise_for_status()
                return resp.json().get("trace_id")
        except Exception as e:
            print(f"[Tracer] ⚠️ 开启 Trace 失败 (降级为本地 ID): {e}")
            return str(uuid.uuid4())
        
    def log_span(self, trace_id: str, span_type: str, span_name: str, 
                 start_time: float, input_data: Any, output_data: Any, status: str = "SUCCESS", error_msg: str = ""):
        """记录一个任务或工具执行片段 (Span)"""
        if not trace_id: return
        
        try:
            # 强化序列化处理与数据截断 (防止 Payload 过大)
            def _safe_data(obj):
                try:
                    if hasattr(obj, "to_json"): data = obj.to_json()
                    else: data = json.loads(json.dumps(obj, default=str))
                    
                    # 如果数据过长，进行截断（例如超过 5000 字符）
                    str_data = str(data)
                    if len(str_data) > 5000:
                        return str_data[:5000] + "... [数据过长已截断]"
                    return data
                except:
                    return str(obj)[:5000]

            payload = {
                "trace_id": trace_id,
                "span_type": span_type,
                "span_name": span_name,
                "start_time": start_time,
                "input_data": _safe_data(input_data),
                "output_data": _safe_data(output_data),
                "status": status,
                "error_msg": error_msg
            }
            
            with httpx.Client(timeout=3.0) as client:
                client.post(f"{self.api_url}/traces/span", json=payload)
        except Exception as e:
            print(f"[Tracer] ⚠️ 记录 Span 失败: {e}")

    def get_token_usage(self, response: Any) -> int:
        """从 LangChain 的响应（AIMessage 或 Chunk）中提取总 Token 消耗"""
        try:
            # 兼容 LangChain 0.2+ 的 usage_metadata
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                return response.usage_metadata.get("total_tokens", 0)
            
            # 兼容旧版本或 OpenAI 原始格式
            if hasattr(response, "additional_kwargs"):
                usage = response.additional_kwargs.get("token_usage")
                if usage:
                    return usage.get("total_tokens", 0)
            
            # 兼容流式输出的 response_metadata
            if hasattr(response, "response_metadata"):
                usage = response.response_metadata.get("token_usage")
                if usage:
                    return usage.get("total_tokens", 0)
                    
            return 0
        except:
            return 0

    def end_trace(self, trace_id: str, final_response: str, success_flag: bool = True, total_tokens: int = 0):
        """闭环 Trace 记录"""
        if not trace_id: return
        try:
            payload = {
                "trace_id": trace_id,
                "final_response": final_response,
                "success_flag": success_flag,
                "total_tokens": total_tokens
            }
            with httpx.Client(timeout=3.0) as client:
                client.post(f"{self.api_url}/traces/end", json=payload)
        except Exception as e:
            print(f"[Tracer] ⚠️ 结束 Trace 失败: {e}")

# 实例化全局探针
tracer = TraceLogger()
