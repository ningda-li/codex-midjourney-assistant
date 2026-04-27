import argparse
import json
import re
import sys
from pathlib import Path

from brief_compile import normalize as compile_brief
from common import (
    configure_stdout,
    infer_subject_contract,
    merge_subject_contract,
    new_task_id,
    normalize_automatic_backend,
    normalize_mode_label,
    normalize_prompt_policy,
    normalize_string_list,
    now_iso,
    read_json_file,
    read_json_input,
    slugify_project_id,
    subject_contract_to_brief_constraints,
)


PROJECT_PATTERNS = [
    re.compile(r"(?:项目|系列|栏目|主题)(?:名|名字|叫|名为|是|为)?[:：\s]*([^，。；;]+)"),
    re.compile(r"为([^，。；;]{2,30}?)(?:项目|系列)"),
]


def parse_args():
    parser = argparse.ArgumentParser(description="初始化 Midjourney 统一任务对象")
    parser.add_argument("--request-text", help="原始需求文本")
    parser.add_argument("--input-file", help="输入文件路径")
    parser.add_argument("--existing-task-file", help="已有任务对象文件路径")
    parser.add_argument("--startup-file", help="startup_route 输出文件路径")
    parser.add_argument("--mode-file", help="mode_route 输出文件路径")
    parser.add_argument("--brief-file", help="已有 brief 文件路径")
    parser.add_argument("--mode", help="显式模式")
    parser.add_argument("--project-id", help="显式 project_id")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def load_input_payload(args):
    if args.request_text:
        return args.request_text.strip(), {}
    if args.input_file:
        raw = Path(args.input_file).read_text(encoding="utf-8-sig").strip()
    else:
        raw = sys.stdin.read().strip()
    parsed = read_json_input(raw)
    if isinstance(parsed, dict):
        for key in ["raw_request", "request", "message", "input", "goal"]:
            value = str(parsed.get(key) or "").strip()
            if value:
                return value, parsed
        return "", parsed
    if isinstance(parsed, str):
        return parsed.strip(), {}
    return raw.strip(), {}


def extract_project_candidate(raw_request: str) -> str:
    for pattern in PROJECT_PATTERNS:
        match = pattern.search(raw_request)
        if match:
            value = match.group(1).strip()
            value = re.sub(r"^(?:是|为|叫|名为)\s*", "", value)
            return value.strip(" ：:，,。；;")
    return ""


def resolve_project_id(explicit_project_id: str, existing_task: dict, payload: dict, raw_request: str) -> str:
    for candidate in [
        explicit_project_id,
        str(payload.get("project_id") or "").strip(),
        str(existing_task.get("project_id") or "").strip(),
        extract_project_candidate(raw_request),
    ]:
        project_id = slugify_project_id(candidate)
        if project_id:
            return project_id
    return ""


def load_brief(args, payload: dict, existing_task: dict, raw_request: str):
    if args.brief_file:
        brief = read_json_file(Path(args.brief_file), default={})
        if isinstance(brief, dict):
            return brief
    if isinstance(payload.get("brief"), dict):
        return payload["brief"]
    if raw_request:
        return compile_brief(raw_request)
    if isinstance(existing_task.get("brief"), dict):
        return existing_task["brief"]
    raise ValueError("无法初始化任务对象：缺少需求文本或 brief")


def main():
    configure_stdout()
    args = parse_args()
    raw_request, payload = load_input_payload(args)
    existing_task = (
        read_json_file(Path(args.existing_task_file), default={}) if args.existing_task_file else {}
    )
    startup = read_json_file(Path(args.startup_file), default={}) if args.startup_file else {}
    mode_snapshot = read_json_file(Path(args.mode_file), default={}) if args.mode_file else {}

    if not isinstance(existing_task, dict):
        existing_task = {}
    if not isinstance(startup, dict):
        startup = {}
    if not isinstance(mode_snapshot, dict):
        mode_snapshot = {}

    startup_request = str(startup.get("request_text") or "").strip()
    if startup_request:
        raw_request = startup_request
    if not raw_request:
        raw_request = str(existing_task.get("raw_request") or "").strip()

    brief = dict(load_brief(args, payload, existing_task, raw_request) or {})
    project_id = resolve_project_id(args.project_id or "", existing_task, payload, raw_request)
    if project_id:
        brief["project_id"] = project_id
    brief["must_have"] = normalize_string_list(brief.get("must_have"))
    brief["style_bias"] = normalize_string_list(brief.get("style_bias"))
    brief["must_not_have"] = normalize_string_list(brief.get("must_not_have"))

    subject_contract = merge_subject_contract(
        existing_task.get("subject_contract"),
        infer_subject_contract(raw_request, brief, existing_task.get("subject_contract")),
    )
    subject_constraints = subject_contract_to_brief_constraints(subject_contract)
    for value in subject_constraints.get("must_have", []):
        if value not in brief["must_have"]:
            brief["must_have"].append(value)
    for value in subject_constraints.get("must_not_have", []):
        if value not in brief["must_not_have"]:
            brief["must_not_have"].append(value)

    selected_mode = normalize_mode_label(
        args.mode
        or str(mode_snapshot.get("selected_mode") or "")
        or str(payload.get("selected_mode") or "")
        or str(payload.get("assistant_mode") or "")
        or str(existing_task.get("mode") or "")
    )
    selected_backend = normalize_automatic_backend(
        str(mode_snapshot.get("selected_backend") or "")
        or str(payload.get("automatic_execution_backend") or "")
        or str(payload.get("execution_backend") or "")
        or str(existing_task.get("automatic_execution_backend") or "")
    )
    prompt_policy = normalize_prompt_policy(
        payload.get("prompt_policy")
        or existing_task.get("prompt_policy")
        or ""
    )

    now = now_iso()
    task_id = str(payload.get("task_id") or existing_task.get("task_id") or new_task_id()).strip()
    startup_phase = str(
        startup.get("startup_phase")
        or existing_task.get("startup_phase")
        or ("onboarding_pending" if startup.get("needs_onboarding") else "ready")
    ).strip()
    task_phase = str(payload.get("task_phase") or existing_task.get("task_phase") or "").strip()
    if not task_phase:
        task_phase = "brief_compiled" if raw_request else "idle"

    round_budget = max(
        1,
        int(
            payload.get("round_budget")
            or existing_task.get("round_budget")
            or brief.get("iteration_budget")
            or 1
        ),
    )
    round_index = max(1, int(payload.get("round_index") or existing_task.get("round_index") or 1))
    prompt_version = max(
        1, int(payload.get("prompt_version") or existing_task.get("prompt_version") or 1)
    )

    task = {
        "task_id": task_id,
        "task_object_version": "v0.2-draft1",
        "project_id": project_id,
        "mode": selected_mode,
        "automatic_execution_backend": str(
            selected_backend
            or payload.get("automatic_execution_backend")
            or existing_task.get("automatic_execution_backend")
            or "isolated_browser"
        ).strip(),
        "prompt_policy": prompt_policy,
        "prompt_language": "en" if prompt_policy == "english_only" else str(
            payload.get("prompt_language") or existing_task.get("prompt_language") or ""
        ).strip(),
        "startup_phase": startup_phase,
        "task_phase": task_phase,
        "round_index": round_index,
        "round_budget": round_budget,
        "raw_request": raw_request,
        "goal": str(brief.get("goal") or raw_request).strip(),
        "brief": brief,
        "subject_contract": subject_contract,
        "memory_snapshot": payload.get("memory_snapshot") or existing_task.get("memory_snapshot") or {},
        "current_prompt": str(payload.get("current_prompt") or existing_task.get("current_prompt") or "").strip(),
        "prompt_version": prompt_version,
        "last_run_verdict": str(
            payload.get("last_run_verdict") or existing_task.get("last_run_verdict") or ""
        ).strip(),
        "last_result_summary": str(
            payload.get("last_result_summary") or existing_task.get("last_result_summary") or ""
        ).strip(),
        "should_continue": bool(
            payload.get("should_continue")
            if "should_continue" in payload
            else existing_task.get("should_continue", False)
        ),
        "next_action": str(payload.get("next_action") or existing_task.get("next_action") or "").strip(),
        "ui_state": payload.get("ui_state") or existing_task.get("ui_state") or {},
        "artifacts": payload.get("artifacts") or existing_task.get("artifacts") or {},
        "startup_snapshot": startup,
        "mode_route_snapshot": mode_snapshot,
        "created_at": str(existing_task.get("created_at") or now),
        "updated_at": now,
    }

    output = json.dumps(task, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
