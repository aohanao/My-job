import sqlite3
import json
import uuid
import time
from typing import Dict, Any, Optional

import eval_config

DB_PATH = eval_config.DB_PATH

def init_db(db_path: str = DB_PATH):
    """初始化监控平台的本地 SQLite 数据库"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 核心链路追踪表：记录用户的一次完整请求
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS run_trace (
        trace_id TEXT PRIMARY KEY,
        session_id TEXT,
        timestamp REAL,
        total_tokens INTEGER DEFAULT 0,
        success_flag BOOLEAN,
        user_query TEXT,
        final_response TEXT
    )
    ''')
    
    # Span表：记录某次 Trace 下具体的每一跳 (Node/Tool)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trace_span (
        span_id TEXT PRIMARY KEY,
        trace_id TEXT,
        span_type TEXT, -- 'NODE', 'TOOL', 'LLM'
        span_name TEXT,
        start_time REAL,
        end_time REAL,
        input_data TEXT, -- JSON
        output_data TEXT, -- JSON
        status TEXT, -- 'SUCCESS', 'ERROR'
        error_msg TEXT,
        FOREIGN KEY (trace_id) REFERENCES run_trace(trace_id)
    )
    ''')
    
    # 评分表：存放 LLM-as-a-Judge 的评分结果
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS eval_score (
        eval_id TEXT PRIMARY KEY,
        trace_id TEXT,
        metric_name TEXT,
        score REAL,
        reason TEXT,
        timestamp REAL,
        FOREIGN KEY (trace_id) REFERENCES run_trace(trace_id)
    )
    ''')
    
    conn.commit()
    conn.close()

class TraceLogger:
    """供 CAE Agent 引入的简易探针 SDK"""
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        init_db(db_path)
        
    def start_trace(self, session_id: str, user_query: str, trace_id: Optional[str] = None) -> str:
        if not trace_id:
            trace_id = str(uuid.uuid4())
        timestamp = time.time()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO run_trace (trace_id, session_id, timestamp, user_query) VALUES (?, ?, ?, ?)",
            (trace_id, session_id, timestamp, user_query)
        )
        conn.commit()
        conn.close()
        return trace_id
        
    def log_span(self, trace_id: str, span_type: str, span_name: str, 
                 start_time: float, end_time: float, input_data: Any, output_data: Any, status: str = "SUCCESS", error_msg: str = ""):
        span_id = str(uuid.uuid4())
        
        # 防御双重序列化：如果是字符串类型，说明已经是序列化后的 JSON，直接存储
        def get_clean_payload(payload):
            if payload is None:
                return "{}"
            if isinstance(payload, str):
                return payload
            return json.dumps(payload, ensure_ascii=False)

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO trace_span 
            (span_id, trace_id, span_type, span_name, start_time, end_time, input_data, output_data, status, error_msg) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (span_id, trace_id, span_type, span_name, start_time, end_time, 
             get_clean_payload(input_data),
             get_clean_payload(output_data),
             status, error_msg)
        )
        conn.commit()
        conn.close()

    def end_trace(self, trace_id: str, final_response: str, success_flag: bool = True, total_tokens: int = 0):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE run_trace SET final_response = ?, success_flag = ?, total_tokens = ? WHERE trace_id = ?",
            (final_response, success_flag, total_tokens, trace_id)
        )
        conn.commit()
        conn.close()

if __name__ == "__main__":
    init_db()
    print("✅ CAE Eval 平台数据库结构已初始化！")
