from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Any
import db_models
import os
import sqlite3
import json
import eval_config

app = FastAPI(title="CAE Eval Platform API", description="接收 Agent 运行状态并持久化至 SQLite")

# 启用跨域支持 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启动时初始化数据库
@app.on_event("startup")
async def startup_event():
    db_models.init_db()

class TraceStartRequest(BaseModel):
    session_id: str
    user_query: str
    trace_id: Optional[str] = None

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

def get_db_connection():
    conn = sqlite3.connect(eval_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ==========================================
# 📥 遥测数据接收接口 (POST)
# ==========================================

@app.post("/traces/start")
async def start_trace(req: TraceStartRequest):
    try:
        trace_id = logger.start_trace(req.session_id, req.user_query, req.trace_id)
        return {"trace_id": trace_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/traces/span")
async def log_span(req: SpanLogRequest):
    try:
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


# ==========================================
# 📊 遥测数据查询接口 (GET)
# ==========================================

@app.get("/api/stats")
async def get_stats():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. 总调用次数
        cursor.execute("SELECT COUNT(*) FROM run_trace")
        total_runs = cursor.fetchone()[0]
        
        if total_runs == 0:
            conn.close()
            return {
                "total_runs": 0,
                "success_rate": 0.0,
                "total_tokens": 0,
                "avg_latency": 0.0,
                "avg_faithfulness": 0.0,
                "avg_answer_relevancy": 0.0
            }
        
        # 2. 任务闭环成功率
        cursor.execute("SELECT COUNT(*) FROM run_trace WHERE success_flag = 1")
        success_runs = cursor.fetchone()[0]
        success_rate = round((success_runs / total_runs) * 100, 1)
        
        # 3. 累计 Token 消耗
        cursor.execute("SELECT SUM(total_tokens) FROM run_trace")
        total_tokens = cursor.fetchone()[0] or 0
        
        # 4. 平均耗时 (基于 Span 最大结束时间与 Trace 开始时间的差)
        latency_query = """
            SELECT AVG(max_end - start) as avg_latency
            FROM (
                SELECT t.timestamp as start, MAX(s.end_time) as max_end
                FROM run_trace t
                JOIN trace_span s ON t.trace_id = s.trace_id
                GROUP BY t.trace_id
            )
        """
        cursor.execute(latency_query)
        row = cursor.fetchone()
        avg_latency = round(row[0], 2) if row and row[0] is not None else 0.0
        
        # 5. 平均 RAGAS 评估得分
        cursor.execute("SELECT AVG(score) FROM eval_score WHERE metric_name = 'ragas_faithfulness'")
        row = cursor.fetchone()
        avg_faithfulness = round(row[0], 2) if row and row[0] is not None else 0.0
        
        cursor.execute("SELECT AVG(score) FROM eval_score WHERE metric_name = 'ragas_answer_relevancy'")
        row = cursor.fetchone()
        avg_answer_relevancy = round(row[0], 2) if row and row[0] is not None else 0.0
        
        conn.close()
        
        return {
            "total_runs": total_runs,
            "success_rate": success_rate,
            "total_tokens": total_tokens,
            "avg_latency": avg_latency,
            "avg_faithfulness": avg_faithfulness,
            "avg_answer_relevancy": avg_answer_relevancy
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/traces")
async def get_traces():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 查询所有 Trace，并聚合耗时与 RAGAS 平均得分
        query = """
            SELECT 
                t.trace_id, 
                t.session_id, 
                t.timestamp, 
                t.total_tokens, 
                t.success_flag, 
                t.user_query, 
                t.final_response,
                COALESCE(MAX(s.end_time) - t.timestamp, 0) as latency,
                MAX(CASE WHEN e.metric_name = 'ragas_faithfulness' THEN e.score END) as faithfulness,
                MAX(CASE WHEN e.metric_name = 'ragas_answer_relevancy' THEN e.score END) as answer_relevancy
            FROM run_trace t
            LEFT JOIN trace_span s ON t.trace_id = s.trace_id
            LEFT JOIN eval_score e ON t.trace_id = e.trace_id
            GROUP BY t.trace_id
            ORDER BY t.timestamp DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        
        traces = []
        for row in rows:
            traces.append({
                "trace_id": row["trace_id"],
                "session_id": row["session_id"],
                "timestamp": row["timestamp"],
                "total_tokens": row["total_tokens"],
                "success_flag": bool(row["success_flag"]) if row["success_flag"] is not None else False,
                "user_query": row["user_query"],
                "final_response": row["final_response"],
                "latency": round(row["latency"], 2),
                "faithfulness": round(row["faithfulness"], 2) if row["faithfulness"] is not None else None,
                "answer_relevancy": round(row["answer_relevancy"], 2) if row["answer_relevancy"] is not None else None
            })
            
        conn.close()
        return traces
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/traces/{trace_id}")
async def get_trace_detail(trace_id: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. 详情查询
        cursor.execute("""
            SELECT 
                t.trace_id, 
                t.session_id, 
                t.timestamp, 
                t.total_tokens, 
                t.success_flag, 
                t.user_query, 
                t.final_response,
                COALESCE(MAX(s.end_time) - t.timestamp, 0) as latency
            FROM run_trace t
            LEFT JOIN trace_span s ON t.trace_id = s.trace_id
            WHERE t.trace_id = ?
            GROUP BY t.trace_id
        """, (trace_id,))
        trace_row = cursor.fetchone()
        if not trace_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Trace not found")
            
        trace_info = {
            "trace_id": trace_row["trace_id"],
            "session_id": trace_row["session_id"],
            "timestamp": trace_row["timestamp"],
            "total_tokens": trace_row["total_tokens"],
            "success_flag": bool(trace_row["success_flag"]) if trace_row["success_flag"] is not None else False,
            "user_query": trace_row["user_query"],
            "final_response": trace_row["final_response"],
            "latency": round(trace_row["latency"], 2)
        }
        
        # 2. 查询相关的 spans 
        cursor.execute("SELECT * FROM trace_span WHERE trace_id = ? ORDER BY start_time ASC", (trace_id,))
        span_rows = cursor.fetchall()
        spans = []
        for s in span_rows:
            try:
                input_val = json.loads(s["input_data"]) if s["input_data"] else {}
            except:
                input_val = s["input_data"]
            try:
                output_val = json.loads(s["output_data"]) if s["output_data"] else {}
            except:
                output_val = s["output_data"]
                
            spans.append({
                "span_id": s["span_id"],
                "span_type": s["span_type"],
                "span_name": s["span_name"],
                "start_time": s["start_time"],
                "end_time": s["end_time"],
                "input_data": input_val,
                "output_data": output_val,
                "status": s["status"],
                "error_msg": s["error_msg"],
                "duration": round(s["end_time"] - s["start_time"], 3) if s["end_time"] and s["start_time"] else 0.0
            })
            
        # 3. 查询关联的 RAGAS 等打分
        cursor.execute("SELECT * FROM eval_score WHERE trace_id = ? ORDER BY timestamp DESC", (trace_id,))
        eval_rows = cursor.fetchall()
        evals = []
        for e in eval_rows:
            evals.append({
                "eval_id": e["eval_id"],
                "metric_name": e["metric_name"],
                "score": e["score"],
                "reason": e["reason"],
                "timestamp": e["timestamp"]
            })
            
        conn.close()
        return {
            "trace": trace_info,
            "spans": spans,
            "evals": evals
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 📂 静态网页托管
# ==========================================

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)

# 挂载静态资源
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def read_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "CAE Eval Platform API is running. Place index.html in the static directory to view dashboard."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8001, reload=True)
