from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Any
import db_models
import os

app = FastAPI(title="CAE Eval Platform API", description="接收 Agent 运行状态并持久化至 SQLite")

# 启动时初始化数据库
@app.on_event("startup")
async def startup_event():
    db_models.init_db()

class TraceStartRequest(BaseModel):
    session_id: str
    user_query: str

class SpanLogRequest(BaseModel):
    trace_id: str
    span_type: str
    span_name: str
    start_time: float
    end_time: Optional[float] = None
    input_data: Any
    output_data: Any
    status: str = "SUCCESS"
    error_msg: str = ""

class TraceEndRequest(BaseModel):
    trace_id: str
    final_response: str
    success_flag: bool = True
    total_tokens: int = 0

# 实例化底层数据库操作类
logger = db_models.TraceLogger()

@app.post("/traces/start")
async def start_trace(req: TraceStartRequest):
    try:
        trace_id = logger.start_trace(req.session_id, req.user_query)
        return {"trace_id": trace_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/traces/span")
async def log_span(req: SpanLogRequest):
    try:
        # 如果请求里没带 end_time，就用当前时间
        import time
        end_time = req.end_time or time.time()
        logger.log_span(
            trace_id=req.trace_id,
            span_type=req.span_type,
            span_name=req.span_name,
            start_time=req.start_time,
            end_time=end_time,
            input_data=req.input_data,
            output_data=req.output_data,
            status=req.status,
            error_msg=req.error_msg
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/traces/end")
async def end_trace(req: TraceEndRequest):
    try:
        logger.end_trace(
            trace_id=req.trace_id,
            final_response=req.final_response,
            success_flag=req.success_flag,
            total_tokens=req.total_tokens
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
