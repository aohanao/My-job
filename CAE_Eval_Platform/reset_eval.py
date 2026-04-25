# 清除评估得分.py
import sqlite3
import os

import eval_config

DB_PATH = eval_config.DB_PATH

def reset_evaluation():
    if not os.path.exists(DB_PATH):
        print(f"❌ 找不到数据库: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        # 清除所有已有的评估得分，但保留原始运行轨迹 (run_trace 和 trace_span)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM eval_score")
        conn.commit()
        print("✅ 评估记录已全部清空！您可以再次运行 python evaluator.py 进行重新评估。")
    except Exception as e:
        print(f"❌ 清理失败: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    confirm = input("⚠️ 确定要清空所有评估得分吗？(y/n): ")
    if confirm.lower() == 'y':
        reset_evaluation()
