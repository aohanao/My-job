"""
human_evaluator.py — CAE Eval Platform 人工评审 CLI 工具

使用方式：
    python human_evaluator.py           # 逐条评审待审 Trace
    python human_evaluator.py --list    # 仅列出所有待审 Trace，不进入评审
    python human_evaluator.py --id <trace_id>  # 仅评审指定 Trace
"""

import argparse
import sqlite3
import uuid
import time
import json
import os
import sys
import textwrap
import eval_config
from db_models import init_db


# ------------------------------------------------------------------ #
#  显示工具                                                            #
# ------------------------------------------------------------------ #

def _separator(char="─", width=70):
    print(char * width)


def _print_trace_summary(trace: sqlite3.Row, spans: list):
    """在终端格式化打印一条 Trace 的完整内容供人工审阅"""
    _separator("═")
    print(f"  Trace ID : {trace['trace_id']}")
    print(f"  提问时间 : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(trace['timestamp']))}")
    print(f"  成功标志 : {'✅ 成功' if trace['success_flag'] else '❌ 失败'}")
    _separator()
    print("\n📌 用户提问：")
    print(textwrap.fill(trace['user_query'] or "(空)", width=68, initial_indent="  ", subsequent_indent="  "))
    
    print("\n📋 执行轨迹：")
    for i, span in enumerate(spans, 1):
        status_icon = "✅" if span['status'] == 'SUCCESS' else "❌"
        duration = ""
        if span['start_time'] and span['end_time']:
            duration = f"  [{span['end_time'] - span['start_time']:.2f}s]"
        print(f"  {i:2}. {status_icon} [{span['span_type']}] {span['span_name']}{duration}")
        if span['status'] == 'ERROR' and span['error_msg']:
            print(f"      ⚠️  {span['error_msg']}")

    print("\n💬 Agent 最终回复：")
    response = trace['final_response'] or "(无回复)"
    print(textwrap.fill(response, width=68, initial_indent="  ", subsequent_indent="  "))
    _separator()


def _get_existing_llm_scores(cursor: sqlite3.Cursor, trace_id: str) -> dict:
    """获取已有的 LLM 评分结果，作为人工评审参考"""
    cursor.execute(
        "SELECT metric_name, score, reason FROM eval_score WHERE trace_id = ?",
        (trace_id,)
    )
    scores = {}
    for row in cursor.fetchall():
        scores[row['metric_name']] = {"score": row['score'], "reason": row['reason']}
    return scores


def _print_llm_reference(llm_scores: dict):
    """打印 LLM 参考打分，供人工参考"""
    if not llm_scores:
        return
    print("\n🤖 LLM 参考评分（仅供参考，你可以覆盖）：")
    display_map = {
        "llm_intent":      "意图理解",
        "llm_tool_call":   "工具调用",
        "llm_solution":    "解决方案",
        "llm_safety":      "专业安全",
        "llm_composite":   "综合得分",
    }
    for key, label in display_map.items():
        if key in llm_scores:
            entry = llm_scores[key]
            print(f"  {label:6}: {entry['score']:5.1f}  ", end="")
            if entry.get('reason') and key == "llm_composite":
                print(f"| {entry['reason'][:60]}...")
            else:
                print()
    _separator()


# ------------------------------------------------------------------ #
#  输入工具                                                            #
# ------------------------------------------------------------------ #

def _get_score_input(prompt: str, allow_skip: bool = False) -> float | None:
    """安全获取 0-10 分的用户输入"""
    while True:
        try:
            raw = input(prompt).strip()
            if allow_skip and raw == "":
                return None
            val = float(raw)
            if 0.0 <= val <= 10.0:
                return val
            print("  ⚠️  请输入 0 到 10 之间的数值。")
        except ValueError:
            print("  ⚠️  无效输入，请输入数字（如 7.5）。")
        except (EOFError, KeyboardInterrupt):
            print("\n⚡ 用户中断，退出评审。")
            sys.exit(0)


def _get_text_input(prompt: str) -> str:
    """获取用户文本输入"""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n⚡ 用户中断，退出评审。")
        sys.exit(0)


# ------------------------------------------------------------------ #
#  核心评审流程                                                        #
# ------------------------------------------------------------------ #

def _review_single_trace(conn: sqlite3.Connection, cursor: sqlite3.Cursor, trace: sqlite3.Row):
    """对单条 Trace 进行人工评审并写库"""
    trace_id = trace['trace_id']
    cursor.execute(
        "SELECT * FROM trace_span WHERE trace_id = ? ORDER BY start_time ASC",
        (trace_id,)
    )
    spans = cursor.fetchall()

    _print_trace_summary(trace, spans)

    llm_scores = _get_existing_llm_scores(cursor, trace_id)
    _print_llm_reference(llm_scores)

    print("📝 请进行人工评分（直接回车可跳过该项，0-10 分，允许小数）：\n")
    intent_score   = _get_score_input("  [1] 意图理解准确性 (0-10): ")
    solution_score = _get_score_input("  [2] 解决方案质量   (0-10): ")
    safety_score   = _get_score_input("  [3] 专业安全性     (0-10): ")
    overall_score  = _get_score_input("  [4] 综合印象分     (0-10): ")
    comment        = _get_text_input( "  [5] 文字评语（直接回车跳过）: ")

    # 计算加权综合分（若用户没给 overall，则自动加权平均）
    if overall_score is None:
        scores = [s for s in [intent_score, solution_score, safety_score] if s is not None]
        overall_score = round(sum(scores) / len(scores), 2) if scores else 0.0

    reviewer = os.getenv("REVIEWER_NAME", "human")
    review_id = str(uuid.uuid4())
    now = time.time()

    conn.execute(
        """INSERT INTO human_review 
           (review_id, trace_id, reviewer, intent_score, solution_score, safety_score, overall_score, comment, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (review_id, trace_id, reviewer,
         intent_score, solution_score, safety_score, overall_score,
         comment or None, now)
    )
    conn.commit()
    print(f"\n  ✅ 已保存人工评审结果（综合分: {overall_score}）")


def _fetch_pending_traces(cursor: sqlite3.Cursor, trace_id_filter: str = None) -> list:
    """获取尚未被人工评审的 Trace"""
    if trace_id_filter:
        cursor.execute(
            """SELECT t.* FROM run_trace t
               WHERE t.trace_id = ? AND t.success_flag IS NOT NULL""",
            (trace_id_filter,)
        )
    else:
        cursor.execute(
            """SELECT t.* FROM run_trace t
               LEFT JOIN human_review h ON t.trace_id = h.trace_id
               WHERE h.trace_id IS NULL AND t.success_flag IS NOT NULL
               ORDER BY t.timestamp DESC"""
        )
    return cursor.fetchall()


# ------------------------------------------------------------------ #
#  命令行入口                                                          #
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(
        description="CAE Eval Platform — 人工评审 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python human_evaluator.py              # 评审所有待审 Trace
              python human_evaluator.py --list       # 仅列出待审 Trace
              python human_evaluator.py --id abc123  # 评审指定 Trace
              REVIEWER_NAME=张工 python human_evaluator.py  # 指定评审人
        """)
    )
    parser.add_argument("--list", action="store_true", help="仅列出待审 Trace，不进入评审")
    parser.add_argument("--id", type=str, default=None, metavar="TRACE_ID", help="仅评审指定 Trace ID")
    args = parser.parse_args()

    init_db(eval_config.DB_PATH)
    conn = sqlite3.connect(eval_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    traces = _fetch_pending_traces(cursor, args.id)

    if not traces:
        print("✅ 没有需要人工评审的 Trace。" if not args.id else f"⚠️  未找到 Trace: {args.id}")
        conn.close()
        return

    # 仅列出模式
    if args.list:
        print(f"📋 共有 {len(traces)} 条 Trace 待人工评审：\n")
        _separator()
        for i, t in enumerate(traces, 1):
            ts = time.strftime('%m-%d %H:%M', time.localtime(t['timestamp']))
            q_preview = (t['user_query'] or "")[:50].replace('\n', ' ')
            success = "✅" if t['success_flag'] else "❌"
            print(f"  {i:3}. {success} [{ts}] {t['trace_id'][:8]}... | {q_preview}")
        _separator()
        conn.close()
        return

    # 评审模式
    print(f"\n🧑‍⚖️  人工评审模式 — 共 {len(traces)} 条待审 Trace\n")
    print("  提示：每项 0-10 分，支持小数。直接按 Ctrl+C 可随时退出。\n")

    reviewed = 0
    for i, trace in enumerate(traces, 1):
        print(f"\n[ 第 {i}/{len(traces)} 条 ]")
        try:
            _review_single_trace(conn, cursor, trace)
            reviewed += 1

            if i < len(traces):
                cont = _get_text_input("\n  继续下一条？ [Enter 继续 / q 退出]: ")
                if cont.lower() == 'q':
                    break
        except Exception as e:
            print(f"  ❌ 处理此 Trace 时出错: {e}")

    conn.close()
    print(f"\n🏁 本次评审完成，共完成 {reviewed} 条。")


if __name__ == "__main__":
    main()
