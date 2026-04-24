import argparse
import json
import sys
from pathlib import Path

from common import configure_stdout, infer_run_verdict, now_iso, read_json_file, read_json_input


VERDICT_SUMMARIES = {
    "success": "本轮结果已达到当前目标，可以结束当前任务。",
    "usable_but_iterate": "本轮结果已经可用，但仍建议继续做下一轮收敛或修正。",
    "blocked_by_ui": "本轮被页面、窗口或结果读取链路阻断，需先处理界面问题。",
    "blocked_by_context": "当前需求或上下文信息不足，补充关键信息后再继续。",
    "stopped_by_user": "任务已按用户要求停止。",
    "stopped_by_budget": "已达到当前轮次或预算上限，本轮不再继续。",
}


def parse_args():
    parser = argparse.ArgumentParser(description="根据 verdict 决定 Midjourney 任务下一步动作")
    parser.add_argument("--task-file", help="统一任务对象文件路径")
    parser.add_argument("--result-file", help="自动模式或手动反馈结果文件路径")
    parser.add_argument("--input-file", help="输入 JSON 文件路径")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def load_payload(args):
    payload = {}
    if args.task_file:
        task = read_json_file(Path(args.task_file), default={})
        if isinstance(task, dict):
            payload.update(task)
    if args.result_file:
        result = read_json_file(Path(args.result_file), default={})
        if isinstance(result, dict):
            payload.update(result)
    if args.input_file:
        direct = read_json_file(Path(args.input_file), default={})
        if isinstance(direct, dict):
            payload.update(direct)
    elif not payload:
        raw = sys.stdin.read().strip()
        direct = read_json_input(raw)
        if isinstance(direct, dict):
            payload.update(direct)
    if not payload:
        raise ValueError("下一步决策输入不能为空")
    return payload


def decide_next_action(payload: dict):
    round_index = max(1, int(payload.get("round_index") or 1))
    round_budget = max(1, int(payload.get("round_budget") or payload.get("iteration_budget") or 1))
    task_model = payload.get("task_model") if isinstance(payload.get("task_model"), dict) else {}
    revision_mode = str(task_model.get("revision_mode") or payload.get("requested_revision_mode") or "").strip()

    if payload.get("feedback_only") and isinstance(payload.get("feedback_patch"), dict):
        next_round_index = max(round_index, int(payload.get("next_round_index") or round_index))
        task_patch = {
            "task_phase": "iterating",
            "should_continue": True,
            "next_action": "prepare_next_round",
            "round_index": next_round_index,
            "updated_at": now_iso(),
        }
        task_patch.update(payload.get("feedback_patch") or {})
        result_summary = str(payload.get("result_summary") or "").strip()
        return {
            "run_verdict": "",
            "result_summary": result_summary,
            "next_action": "prepare_next_round",
            "next_phase": "iterating",
            "should_continue": True,
            "next_round_index": next_round_index,
            "task_patch": task_patch,
        }

    verdict = infer_run_verdict(payload)

    if verdict == "usable_but_iterate" and round_index >= round_budget:
        verdict = "stopped_by_budget"

    if revision_mode == "colorway_only" and verdict == "usable_but_iterate" and payload.get("result_available"):
        verdict = "success"

    if verdict == "success":
        if revision_mode == "colorway_only":
            next_action = "await_user_feedback"
            next_phase = "finished"
            should_continue = False
            next_round_index = round_index
        else:
            next_action = "finish_task"
            next_phase = "finished"
            should_continue = False
            next_round_index = round_index
    elif verdict == "usable_but_iterate":
        next_action = "prepare_next_round"
        next_phase = "iterating"
        should_continue = True
        next_round_index = round_index + 1
    elif verdict == "blocked_by_ui":
        next_action = "resolve_ui_block"
        next_phase = "blocked"
        should_continue = False
        next_round_index = round_index
    elif verdict == "blocked_by_context":
        next_action = "ask_for_missing_context"
        next_phase = "blocked"
        should_continue = False
        next_round_index = round_index
    elif verdict == "stopped_by_user":
        next_action = "finish_task"
        next_phase = "finished"
        should_continue = False
        next_round_index = round_index
    else:
        next_action = "finish_budget_reached"
        next_phase = "finished"
        should_continue = False
        next_round_index = round_index

    result_summary = str(
        payload.get("result_summary")
        or payload.get("last_result_summary")
        or VERDICT_SUMMARIES.get(verdict, "")
    ).strip()

    task_patch = {
        "task_phase": next_phase,
        "last_run_verdict": verdict,
        "last_result_summary": result_summary,
        "should_continue": should_continue,
        "next_action": next_action,
        "round_index": next_round_index,
        "updated_at": now_iso(),
    }

    return {
        "run_verdict": verdict,
        "result_summary": result_summary,
        "next_action": next_action,
        "next_phase": next_phase,
        "should_continue": should_continue,
        "next_round_index": next_round_index,
        "task_patch": task_patch,
    }


def main():
    configure_stdout()
    args = parse_args()
    payload = load_payload(args)
    decision = decide_next_action(payload)
    output = json.dumps(decision, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
