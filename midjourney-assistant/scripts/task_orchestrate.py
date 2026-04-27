import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from common import (
    ACTIVE_TASK_STATE_PATH,
    MEMORY_ROOT,
    PROMPT_POLICY_ENGLISH_ONLY,
    build_backend_health_snapshot,
    classify_execution_governance,
    configure_stdout,
    detect_runtime_environment,
    get_powershell_command,
    is_english_prompt_text,
    managed_runtime_paths,
    normalize_prompt_policy,
    normalize_string_list,
    now_iso,
    read_json_file,
    read_json_input,
    validate_execution_prompt,
    write_json_file,
)
from feedback_apply import apply_feedback_to_task, classify_feedback_intent, looks_like_new_task_request
from manual_mode_prepare import prepare_task_prompt
from next_action_decide import decide_next_action


SCRIPT_ROOT = Path(__file__).resolve().parent
AUTOMATIC_ROUND_START_TIMEOUT_SEC = 30
AUTOMATIC_ROUND_COMPLETE_TIMEOUT_SEC = 240
AUTOMATIC_PARENT_TIMEOUT_SEC = 300
AUTOMATIC_TIMEOUT_BLOCKED_REASONS = {"start_timeout", "complete_timeout", "automatic_parent_timeout"}
AUTOMATIC_AMBIGUOUS_BLOCKED_REASONS = {"prompt_region_not_found", "prompt_region_unconfirmed"}
MEMORY_WRITEBACK_SCOPES = {"log", "profile", "experience", "template"}
MEMORY_WRITEBACK_SCOPE_KEYWORDS = {
    "log": [
        "记录日志",
        "保存日志",
        "记录过程",
        "保存过程",
        "记录本次过程",
        "记录这次结果",
        "记录本次结果",
        "记录运行日志",
        "保存运行记录",
        "排障",
    ],
    "profile": [
        "记录到画像",
        "写入画像",
        "保存到画像",
        "记录我的偏好",
        "记住我的偏好",
        "保存我的偏好",
        "写入我的偏好",
        "记录用户画像",
        "更新用户画像",
    ],
    "experience": [
        "记录经验",
        "保存经验",
        "写入经验",
        "复盘",
        "记录复盘",
        "保存复盘",
        "总结经验",
    ],
    "template": [
        "记录为模板",
        "记录为模版",
        "保存为模板",
        "保存为模版",
        "存为模板",
        "存为模版",
        "作为模板记录",
        "作为模版记录",
    ],
}
MEMORY_WRITEBACK_ALL_KEYWORDS = [
    "记录全部",
    "记录所有",
    "写回全部",
    "写回所有",
    "保存全部记忆",
    "保存所有记忆",
]
MEMORY_WRITEBACK_DENY_PHRASES = [
    "不要记录",
    "别记录",
    "不记录",
    "无需记录",
    "不用记录",
    "不要写回",
    "别写回",
    "不写回",
    "不要写入记忆",
    "不写本地记忆",
]
PERSISTENT_WRITEBACK_SKIPPED_REASON = "persistent_memory_writeback_requires_explicit_record_review_or_troubleshoot"


class AutomaticSubprocessTimeout(RuntimeError):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="编排 Midjourney v0.2 任务流")
    parser.add_argument("--message", help="用户消息")
    parser.add_argument("--input-file", help="输入文件路径")
    parser.add_argument("--task-file", help="统一任务对象读写路径")
    parser.add_argument("--mode", help="显式模式覆盖")
    parser.add_argument("--output-file", help="输出结果文件路径")
    parser.add_argument("--checkpoint-file", help="可选 checkpoint 输出路径")
    parser.add_argument("--execute-automatic", action="store_true", help="自动模式下立即执行网页提交流程")
    parser.add_argument("--skip-memory", action="store_true", help="跳过记忆检索")
    parser.add_argument("--regenerate-prompt", action="store_true", help="强制重生 prompt")
    parser.add_argument(
        "--allow-memory-writeback",
        action="store_true",
        help="用户明确要求写回全部本地记忆类别时才允许使用",
    )
    return parser.parse_args()


def load_message(args):
    if args.message:
        return args.message.strip()
    if args.input_file:
        content = Path(args.input_file).read_text(encoding="utf-8-sig").strip()
    else:
        content = sys.stdin.read().strip()
    parsed = read_json_input(content)
    if isinstance(parsed, dict):
        for key in ["message", "raw_request", "request", "input", "goal"]:
            value = str(parsed.get(key) or "").strip()
            if value:
                return value
    if isinstance(parsed, str):
        return parsed.strip()
    return content


def run_python_script(script_name: str, arguments):
    command = [sys.executable, str(SCRIPT_ROOT / script_name)] + arguments
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        stderr_text = str(result.stderr or "").strip()
        stdout_text = str(result.stdout or "").strip()
        raise RuntimeError(stderr_text or stdout_text or f"{script_name} 执行失败")
    output = (result.stdout or "").strip()
    if not output:
        for index, argument in enumerate(arguments):
            if argument == "--output-file" and index + 1 < len(arguments):
                output = Path(arguments[index + 1]).read_text(encoding="utf-8-sig").strip()
                break
    parsed = read_json_input(output)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{script_name} 输出不是 JSON 对象")
    return parsed


def run_powershell_script(script_name: str, arguments, timeout_sec: int | None = None):
    shell_command = get_powershell_command()
    if not shell_command:
        raise RuntimeError("powershell_runtime_missing")
    command = [
        shell_command,
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT_ROOT / script_name),
    ] + arguments
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise AutomaticSubprocessTimeout(f"{script_name} 超过外层自动执行时间上限") from exc
    if result.returncode != 0:
        stderr_text = str(result.stderr or "").strip()
        stdout_text = str(result.stdout or "").strip()
        raise RuntimeError(stderr_text or stdout_text or f"{script_name} 执行失败")
    output = (result.stdout or "").strip()
    parsed = read_json_input(output)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{script_name} 输出不是 JSON 对象")
    return parsed


def build_environment_blocked_auto_result(blocked_reason: str, environment_check: dict):
    return {
        "ok": False,
        "completed": False,
        "result_available": False,
        "blocked_by_context": True,
        "blocked_reason": blocked_reason,
        "environment_check": environment_check,
    }


def detect_backend_environment_block(backend: str):
    normalized_backend = str(backend or "isolated_browser").strip() or "isolated_browser"
    environment_check = detect_runtime_environment(normalized_backend)
    first_block = environment_check.get("first_required_preflight_block") or {}
    blocked_reason = str(first_block.get("blocked_reason") or "").strip()
    if blocked_reason:
        return blocked_reason, environment_check
    return "", environment_check


def prepare_isolated_browser_setup(timeout_sec: int | None = None):
    return run_powershell_script("midjourney_isolated_browser_setup.ps1", [], timeout_sec=timeout_sec)


def run_node_script(script_name: str, arguments, timeout_sec: int | None = None):
    command = ["node", str(SCRIPT_ROOT / script_name)] + arguments
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise AutomaticSubprocessTimeout(f"{script_name} 超过外层自动执行时间上限") from exc
    if result.returncode != 0:
        stderr_text = str(result.stderr or "").strip()
        stdout_text = str(result.stdout or "").strip()
        raise RuntimeError(stderr_text or stdout_text or f"{script_name} 执行失败")
    output = (result.stdout or "").strip()
    if not output:
        for index, argument in enumerate(arguments):
            if argument == "--output-file" and index + 1 < len(arguments):
                output = Path(arguments[index + 1]).read_text(encoding="utf-8-sig").strip()
                break
    parsed = read_json_input(output)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{script_name} 输出不是 JSON 对象")
    return parsed


def remaining_automatic_timeout(deadline: float) -> int:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AutomaticSubprocessTimeout("automatic round exceeded parent timeout")
    return max(1, int(remaining))


def run_task_script(script_name: str, task: dict, arguments=None):
    extra_arguments = list(arguments or [])
    with managed_runtime_paths("mj-v03-knowledge") as temp_path:
        task_path = temp_path("task.json")
        output_path = temp_path("output.json")
        write_json_file(task_path, task)
        response = run_python_script(
            script_name,
            ["--task-file", str(task_path), "--output-file", str(output_path)] + extra_arguments,
        )
    updated_task = response.get("task") if isinstance(response.get("task"), dict) else dict(task)
    return updated_task, response


def run_knowledge_pipeline(task: dict, force_regenerate: bool = False):
    updated_task, classify_response = run_task_script("task_classify.py", task)
    updated_task, diagnose_response = run_task_script("prompt_diagnose.py", updated_task)
    updated_task, solution_response = run_task_script("solution_plan_build.py", updated_task)
    updated_task, reference_response = run_task_script("reference_knowledge_retrieve.py", updated_task)
    prompt_arguments = ["--regenerate-prompt"] if force_regenerate else []
    updated_task, prompt_response = run_task_script("prompt_strategy_select.py", updated_task, prompt_arguments)
    prompt_package = prompt_response.get("prompt_package") if isinstance(prompt_response.get("prompt_package"), dict) else {}
    knowledge_snapshot = {
        "task_model": classify_response.get("task_model") or updated_task.get("task_model") or {},
        "diagnosis_report": diagnose_response.get("diagnosis_report") or updated_task.get("diagnosis_report") or {},
        "solution_plan": solution_response.get("solution_plan") or updated_task.get("solution_plan") or {},
        "reference_knowledge": reference_response.get("reference_knowledge_snapshot")
        or updated_task.get("reference_knowledge_snapshot")
        or {},
    }
    return updated_task, prompt_package, knowledge_snapshot


def rerun_post_execution_diagnosis(task: dict):
    updated_task, diagnose_response = run_task_script("prompt_diagnose.py", task)
    diagnosis_report = (
        diagnose_response.get("diagnosis_report")
        if isinstance(diagnose_response.get("diagnosis_report"), dict)
        else updated_task.get("diagnosis_report")
        if isinstance(updated_task.get("diagnosis_report"), dict)
        else {}
    )
    return updated_task, diagnosis_report


def initialize_task_from_message(message: str, mode_override: str = ""):
    with managed_runtime_paths("mj-v02-init") as temp_path:
        input_file = temp_path("input.json")
        startup_file = temp_path("startup.json")
        mode_file = temp_path("mode.json")
        task_file = temp_path("task.json")

        input_file.write_text(
            json.dumps({"message": message}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        startup = run_python_script(
            "startup_route.py",
            ["--input-file", str(input_file), "--output-file", str(startup_file)],
        )

        if not startup.get("has_task"):
            return None, startup, {}

        mode_args = ["--input-file", str(input_file), "--output-file", str(mode_file)]
        if mode_override:
            mode_args.extend(["--mode", mode_override])
        mode_snapshot = run_python_script("mode_route.py", mode_args)

        task_args = [
            "--input-file",
            str(input_file),
            "--startup-file",
            str(startup_file),
            "--mode-file",
            str(mode_file),
            "--output-file",
            str(task_file),
        ]
        if mode_override:
            task_args.extend(["--mode", mode_override])
        task = run_python_script("task_state_init.py", task_args)
        return task, startup, mode_snapshot


def ensure_memory_snapshot(task: dict):
    with managed_runtime_paths("mj-v02-memory") as temp_path:
        task_path = temp_path("task.json")
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        memory = run_python_script("memory_retrieve.py", ["--task-file", str(task_path)])
    updated_task = dict(task)
    updated_task["memory_snapshot"] = memory
    updated_task["task_phase"] = "memory_loaded"
    updated_task["updated_at"] = now_iso()
    return updated_task, memory


def extract_hit_lines(entries, limit: int = 3):
    results = []
    if not isinstance(entries, list):
        return results
    for item in entries:
        if not isinstance(item, dict):
            continue
        line = str(item.get("line") or "").strip()
        if line and line not in results:
            results.append(line)
        if len(results) >= limit:
            break
    return results


def profile_hit_fields(user_profile: dict) -> set[str]:
    fields = set()
    for item in user_profile.get("hits") or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        if field:
            fields.add(field)
    return fields


def profile_values_for_hit_field(structured: dict, hit_fields: set[str], field: str):
    if field not in hit_fields:
        return []
    return normalize_string_list(structured.get(field) if isinstance(structured, dict) else [])


def profile_text_for_hit_field(structured: dict, hit_fields: set[str], field: str) -> str:
    if field not in hit_fields or not isinstance(structured, dict):
        return ""
    return str(structured.get(field) or "").strip()


def build_memory_consumption_snapshot(memory_snapshot: dict, task: dict | None = None):
    user_profile = memory_snapshot.get("user_profile") if isinstance(memory_snapshot, dict) else {}
    structured = user_profile.get("structured") if isinstance(user_profile, dict) else {}
    project_memory = memory_snapshot.get("project_memory") if isinstance(memory_snapshot, dict) else {}
    hit_fields = profile_hit_fields(user_profile if isinstance(user_profile, dict) else {})
    snapshot = {
        "profile_hit_fields": sorted(hit_fields),
        "profile_hit_lines": extract_hit_lines(user_profile.get("hits") if isinstance(user_profile, dict) else []),
        "profile_work_types": profile_values_for_hit_field(structured, hit_fields, "work_types"),
        "profile_style_preferences": profile_values_for_hit_field(structured, hit_fields, "style_preferences"),
        "profile_content_preferences": profile_values_for_hit_field(structured, hit_fields, "content_preferences"),
        "profile_taboos": profile_values_for_hit_field(structured, hit_fields, "taboos"),
        "profile_quality_tendency": profile_text_for_hit_field(structured, hit_fields, "quality_tendency"),
        "project_memory_lines": extract_hit_lines(project_memory.get("hits") if isinstance(project_memory, dict) else []),
        "distilled_pattern_lines": extract_hit_lines(memory_snapshot.get("distilled_patterns")),
        "site_change_lines": extract_hit_lines(memory_snapshot.get("site_changes")),
        "sources_applied": [],
    }
    if (
        snapshot["profile_work_types"]
        or snapshot["profile_style_preferences"]
        or snapshot["profile_content_preferences"]
        or snapshot["profile_taboos"]
        or snapshot["profile_quality_tendency"]
    ):
        snapshot["sources_applied"].append("user_profile")
    if snapshot["project_memory_lines"]:
        snapshot["sources_applied"].append("project_memory")
    if snapshot["distilled_pattern_lines"]:
        snapshot["sources_applied"].append("distilled_patterns")
    if snapshot["site_change_lines"]:
        snapshot["sources_applied"].append("site_changes")
    return snapshot


def attach_memory_consumption_snapshot(task: dict, memory_snapshot: dict):
    updated_task = dict(task)
    consumption = build_memory_consumption_snapshot(memory_snapshot, task)
    updated_task["memory_snapshot"] = memory_snapshot
    updated_task["memory_consumption_snapshot"] = consumption
    artifacts = dict(updated_task.get("artifacts") or {})
    artifacts["memory_consumption"] = consumption
    updated_task["artifacts"] = artifacts
    updated_task["updated_at"] = now_iso()
    return updated_task, consumption


def merge_project_context(task: dict, writeback: bool = False):
    with managed_runtime_paths("mj-v02-project") as temp_path:
        task_path = temp_path("task.json")
        output_path = temp_path("project.json")
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        arguments = ["--task-file", str(task_path), "--output-file", str(output_path)]
        if writeback:
            arguments.append("--writeback")
        response = run_python_script("project_context_merge.py", arguments)
    updated_task = response.get("task") if isinstance(response.get("task"), dict) else dict(task)
    return updated_task, response


def merge_mode_route(task: dict, message: str, mode_override: str = ""):
    with managed_runtime_paths("mj-v02-mode") as temp_path:
        input_path = temp_path("input.json")
        task_path = temp_path("task.json")
        input_path.write_text(
            json.dumps({"message": message or task.get("raw_request", "")}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args = ["--input-file", str(input_path), "--task-file", str(task_path)]
        if mode_override:
            args.extend(["--mode", mode_override])
        snapshot = run_python_script("mode_route.py", args)
    updated_task = dict(task)
    updated_task["mode_route_snapshot"] = snapshot
    if snapshot.get("selected_mode"):
        updated_task["mode"] = snapshot["selected_mode"]
        updated_task["task_phase"] = "mode_routed"
    if snapshot.get("selected_backend"):
        updated_task["automatic_execution_backend"] = snapshot["selected_backend"]
    updated_task["updated_at"] = now_iso()
    return updated_task, snapshot


def apply_task_patch(task: dict, patch: dict):
    updated = dict(task)
    updated.update(patch or {})
    updated["updated_at"] = now_iso()
    return updated


def ensure_prompt_policy_defaults(task: dict):
    updated = dict(task)
    prompt_policy = normalize_prompt_policy(updated.get("prompt_policy"))
    updated["prompt_policy"] = prompt_policy
    if prompt_policy == PROMPT_POLICY_ENGLISH_ONLY:
        updated["prompt_language"] = "en"
    return updated


def build_prompt_policy_blocked_message(reason: str) -> str:
    normalized = str(reason or "").strip()
    lowered = normalized.lower()
    if "基底图" in normalized or "base" in lowered:
        return "当前是配色任务，但还没有锁定基底图，先确认要沿用哪一张设计。"
    if "english" in lowered or "英文" in normalized or "不是英文" in normalized:
        return "当前需求无法稳定生成合规英文 prompt，已停止提交。"
    if "术语" in normalized or "terminology" in lowered:
        return "当前需求里有无法稳定转成英文 prompt 的术语，已停止提交。"
    return "当前 prompt 不符合提交规则，已停止提交。"


def build_prompt_policy_blocked_result(
    task: dict,
    reason: str,
    checkpoint_file: str = "",
    task_file: str = "",
    persist_memory_writeback: bool = False,
):
    blocked_task = ensure_prompt_policy_defaults(task)
    blocked_task["task_phase"] = "prompt_blocked"
    blocked_task["next_action"] = "fix_prompt_policy"
    blocked_task["should_continue"] = False
    blocked_task["updated_at"] = now_iso()
    checkpoint_info = save_task_outputs(
        blocked_task,
        task_file=task_file,
        checkpoint_file=checkpoint_file,
        persist=persist_memory_writeback,
    )
    return {
        "ok": False,
        "orchestration_status": "prompt_policy_blocked",
        "task": blocked_task,
        "runtime_receipts": {"checkpoint": checkpoint_info},
        "message": build_prompt_policy_blocked_message(reason),
    }


def build_user_facing_block_message(auto_result: dict) -> str:
    blocked_reason = str(auto_result.get("blocked_reason") or "").strip()
    if blocked_reason == "unsupported_platform":
        return "当前自动模式只支持 Windows 桌面环境；这台电脑请改用手动模式，或换到 Windows 电脑再继续。"
    if blocked_reason == "powershell_runtime_missing":
        return "这台电脑缺少可用的 PowerShell，自动模式暂时不可用；你明确要求修复依赖后，我可以尝试安装。"
    if blocked_reason == "node_runtime_missing":
        return "这台电脑缺少 Node.js，后台自动模式暂时不可用；你明确要求修复依赖后，我可以尝试安装。"
    if blocked_reason == "no_supported_browser_found":
        return "这台电脑没有检测到可用的后台浏览器。建议先安装 Edge；你明确要求修复依赖后，我可以尝试安装。"
    if blocked_reason == "runtime_write_unavailable":
        return "当前运行目录不可写，自动模式暂时不可用；请先确认 Codex 已开启完全访问权限，或修复运行目录权限。"
    if blocked_reason == "automatic_backend_runtime_error":
        return "自动执行环境异常，已停止本轮提交。"
    if blocked_reason in {"needs_isolated_browser_login", "isolated_browser_challenge_page"}:
        return "后台浏览器需要先登录 Midjourney。"
    if blocked_reason in {"isolated_browser_input_not_ready", "midjourney_window_not_found"}:
        return "Midjourney 页面当前不可提交。"
    if blocked_reason in AUTOMATIC_TIMEOUT_BLOCKED_REASONS:
        return "本轮已达到 5 分钟内的自动执行上限，已停止继续尝试。"
    if blocked_reason in AUTOMATIC_AMBIGUOUS_BLOCKED_REASONS:
        return "本轮结果还不能可靠对应到当前 prompt，已停止继续尝试。"
    if blocked_reason == "english_prompt_required":
        return "当前 prompt 不符合英文视觉 prompt 规则，已停止提交。"
    if auto_result.get("blocked_by_ui"):
        return "页面状态阻塞，已停止本轮提交。"
    if auto_result.get("blocked_by_context"):
        return "上下文阻塞，已停止本轮提交。"
    return "本轮生成未完成。"


def apply_automatic_round_stop_flags(auto_result: dict) -> None:
    blocked_reason = str(auto_result.get("blocked_reason") or "").strip()
    if blocked_reason in AUTOMATIC_TIMEOUT_BLOCKED_REASONS:
        auto_result.pop("blocked_by_ui", None)
        auto_result.pop("blocked_by_context", None)
        auto_result["stopped_by_budget"] = True
        auto_result["should_continue"] = False
    elif blocked_reason in AUTOMATIC_AMBIGUOUS_BLOCKED_REASONS:
        auto_result.pop("stopped_by_budget", None)
        auto_result["blocked_by_ui"] = True
        auto_result["should_continue"] = False


def message_memory_writeback_scopes(message: str) -> set[str]:
    normalized = str(message or "").strip()
    if not normalized:
        return set()
    if any(phrase in normalized for phrase in MEMORY_WRITEBACK_DENY_PHRASES):
        return set()
    if any(keyword in normalized for keyword in MEMORY_WRITEBACK_ALL_KEYWORDS):
        return set(MEMORY_WRITEBACK_SCOPES)
    scopes = set()
    for scope, keywords in MEMORY_WRITEBACK_SCOPE_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            scopes.add(scope)
    return scopes


def message_requests_memory_writeback(message: str) -> bool:
    return bool(message_memory_writeback_scopes(message))


def resolve_memory_writeback_scopes(args, message: str, task: dict) -> set[str]:
    if getattr(args, "allow_memory_writeback", False):
        return set(MEMORY_WRITEBACK_SCOPES)
    scopes = set(message_memory_writeback_scopes(message))
    raw_request = str((task or {}).get("raw_request") or "").strip()
    if raw_request:
        scopes.update(message_memory_writeback_scopes(raw_request))
    latest_feedback = (task or {}).get("latest_feedback")
    if isinstance(latest_feedback, dict):
        feedback_text = " ".join(
            str(latest_feedback.get(key) or "")
            for key in ["raw_feedback", "raw_text", "summary", "message"]
        )
        scopes.update(message_memory_writeback_scopes(feedback_text))
    return scopes


def skipped_persistent_writeback_receipt(kind: str = "") -> dict:
    return {
        "ok": True,
        "skipped": True,
        "kind": kind,
        "reason": PERSISTENT_WRITEBACK_SKIPPED_REASON,
    }


def get_runtime_thread_id() -> str:
    return str(os.environ.get("CODEX_THREAD_ID") or "").strip()


def bind_task_to_runtime_scope(task: dict) -> dict:
    updated = dict(task or {})
    current_thread_id = get_runtime_thread_id()
    existing_thread_id = str(updated.get("thread_id") or "").strip()
    if current_thread_id:
        updated["thread_id"] = current_thread_id
    elif existing_thread_id:
        updated["thread_id"] = existing_thread_id
    return updated


def active_task_thread_scope_matches(state_payload: dict, task_payload: dict) -> bool:
    current_thread_id = get_runtime_thread_id()
    state_thread_id = str((state_payload or {}).get("thread_id") or "").strip()
    task_thread_id = str((task_payload or {}).get("thread_id") or "").strip()
    if current_thread_id:
        return state_thread_id == current_thread_id and task_thread_id == current_thread_id
    if state_thread_id or task_thread_id:
        return bool(state_thread_id) and state_thread_id == task_thread_id
    return True


def is_terminal_task(task: dict) -> bool:
    if not isinstance(task, dict) or not task:
        return False
    next_action = str(task.get("next_action") or "").strip()
    if next_action == "await_user_feedback":
        return False
    task_phase = str(task.get("task_phase") or "").strip()
    last_run_verdict = str(task.get("last_run_verdict") or task.get("run_verdict") or "").strip()
    if next_action in {"finish_task", "finish_budget_reached"}:
        return True
    if last_run_verdict in {"stopped_by_user", "stopped_by_budget"}:
        return True
    if task_phase == "finished" and last_run_verdict == "success":
        return True
    return False


def save_task_outputs(task: dict, task_file: str = "", checkpoint_file: str = "", persist: bool = False):
    task_payload = bind_task_to_runtime_scope(task)
    task.clear()
    task.update(task_payload)
    if task_file:
        write_json_file(Path(task_file), task_payload)
    if not persist:
        return skipped_persistent_writeback_receipt("checkpoint")
    with managed_runtime_paths("mj-v02-checkpoint") as temp_path:
        input_path = temp_path("task.json")
        input_path.write_text(json.dumps(task_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        arguments = ["--input-file", str(input_path)]
        if checkpoint_file:
            arguments.extend(["--output-file", checkpoint_file])
        checkpoint_info = run_python_script("run_checkpoint.py", arguments)
    write_json_file(
        ACTIVE_TASK_STATE_PATH,
        {
            "task_id": str(task_payload.get("task_id") or "").strip(),
            "project_id": str(task_payload.get("project_id") or "").strip(),
            "thread_id": str(task_payload.get("thread_id") or "").strip(),
            "checkpoint_path": str(checkpoint_info.get("path") or "").strip(),
            "task_phase": str(task_payload.get("task_phase") or "").strip(),
            "last_run_verdict": str(task_payload.get("last_run_verdict") or "").strip(),
            "next_action": str(task_payload.get("next_action") or "").strip(),
            "updated_at": str(task_payload.get("updated_at") or now_iso()).strip(),
        },
    )
    return checkpoint_info


def load_active_task_candidate():
    state_payload = read_json_file(ACTIVE_TASK_STATE_PATH, default={})
    if not isinstance(state_payload, dict):
        return {}

    checkpoint_path = str(state_payload.get("checkpoint_path") or "").strip()
    if not checkpoint_path:
        return {}

    checkpoint_file = Path(checkpoint_path)
    if not checkpoint_file.exists():
        return {}

    payload = read_json_file(checkpoint_file, default={})
    if not isinstance(payload, dict):
        return {}

    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        return {}

    expected_task_id = str(state_payload.get("task_id") or "").strip()
    if expected_task_id and task_id != expected_task_id:
        return {}

    expected_project_id = str(state_payload.get("project_id") or "").strip()
    project_id = str(payload.get("project_id") or "").strip()
    if expected_project_id and project_id != expected_project_id:
        return {}

    if not active_task_thread_scope_matches(state_payload, payload):
        return {}

    return payload


def build_run_record(task: dict, prompt_package: dict, auto_result: dict, decision: dict):
    return {
        "task_id": task.get("task_id", ""),
        "project_id": task.get("project_id", ""),
        "mode": task.get("mode", ""),
        "automatic_execution_backend": task.get("automatic_execution_backend", ""),
        "prompt_policy": task.get("prompt_policy", ""),
        "round_index": task.get("round_index", 1),
        "prompt_version": task.get("prompt_version", 1),
        "goal": task.get("goal", ""),
        "brief": task.get("brief") or {},
        "task_model": task.get("task_model") or {},
        "solution_plan": task.get("solution_plan") or {},
        "diagnosis_report": task.get("diagnosis_report") or {},
        "brief_summary": prompt_package.get("brief_summary", ""),
        "feedback_summary": prompt_package.get("feedback_summary", ""),
        "current_prompt": task.get("current_prompt", ""),
        "prompt_stage": prompt_package.get("prompt_stage", ""),
        "task_phase": task.get("task_phase", ""),
        "result_available": bool(auto_result.get("result_available", False)),
        "result_summary": decision.get("result_summary", ""),
        "run_verdict": decision.get("run_verdict", ""),
        "next_action": decision.get("next_action", ""),
        "should_continue": bool(decision.get("should_continue", False)),
        "execution_governance": auto_result.get("execution_governance") or {},
        "executed_prompt_source": str(auto_result.get("prompt_source") or "").strip(),
        "final_capture": auto_result.get("final_capture", ""),
        "window_state": auto_result.get("window_state") or {},
        "latest_feedback": task.get("latest_feedback") or {},
        "memory_consumption_snapshot": task.get("memory_consumption_snapshot") or {},
        "updated_at": task.get("updated_at") or now_iso(),
    }


def append_run_record(record: dict):
    with managed_runtime_paths("mj-v02-runlog") as temp_path:
        input_path = temp_path("run.json")
        input_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_python_script("memory_append.py", ["--input-file", str(input_path)])


def build_run_summary(record: dict):
    with managed_runtime_paths("mj-v02-summary") as temp_path:
        input_path = temp_path("run.json")
        input_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_python_script("run_summary.py", ["--input-file", str(input_path)])


def extract_profile_signal(record: dict):
    with managed_runtime_paths("mj-v03-profile-signal") as temp_path:
        input_path = temp_path("run.json")
        input_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_python_script("profile_signal_extract.py", ["--input-file", str(input_path)])


def merge_profile_candidate(candidate: dict):
    if not isinstance(candidate, dict) or not candidate:
        return {
            "ok": True,
            "profile_updated": False,
            "promoted_values": {},
            "path": "",
        }
    with managed_runtime_paths("mj-v03-profile-merge") as temp_path:
        input_path = temp_path("candidate.json")
        input_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_python_script("profile_merge.py", ["--input-file", str(input_path)])


def distill_experience(record: dict):
    with managed_runtime_paths("mj-v03-distill") as temp_path:
        input_path = temp_path("run.json")
        input_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_python_script("experience_distill.py", ["--input-file", str(input_path)])


def upsert_template_candidate(record: dict):
    with managed_runtime_paths("mj-v03-template") as temp_path:
        input_path = temp_path("run.json")
        input_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_python_script("template_candidate_upsert.py", ["--input-file", str(input_path)])


def is_mode_only_message(message: str) -> bool:
    normalized = str(message or "").strip()
    return normalized in {"自动模式", "手动模式", "后台模式", "前台模式"}


def is_new_task_reset(message: str) -> bool:
    normalized = str(message or "").strip()
    if not normalized:
        return False
    return any(
        token in normalized
        for token in [
            "新任务",
            "新需求",
            "重新开始",
            "重开",
            "另一个任务",
            "换个任务",
            "换个项目",
            "另一个项目",
            "重新做一张新的",
            "重新生成一个新的",
        ]
    )


def should_continue_from_feedback(task: dict, message: str, mode_override: str = "") -> bool:
    if not task or not str(message or "").strip():
        return False
    if mode_override:
        return False
    if is_mode_only_message(message) or is_new_task_reset(message):
        return False
    if str(task.get("startup_phase") or "").strip() == "onboarding_pending":
        return False
    if not str(task.get("mode") or "").strip():
        return False
    if is_terminal_task(task):
        return False
    return classify_feedback_intent(task, message)


def should_restart_task_from_message(task: dict, message: str, mode_override: str = "") -> bool:
    if not task or not str(message or "").strip():
        return False
    if mode_override:
        return False
    if is_mode_only_message(message):
        return False
    if is_new_task_reset(message):
        return True
    if looks_like_new_task_request(task, message):
        return True
    return False


def main():
    configure_stdout()
    args = parse_args()

    message = load_message(args)
    task = read_json_file(Path(args.task_file), default={}) if args.task_file and Path(args.task_file).exists() else {}
    startup_snapshot = {}
    mode_snapshot = {}
    feedback_snapshot = {}
    restored_from_active_task = False

    if not isinstance(task, dict):
        task = {}

    if task and should_restart_task_from_message(task, message, args.mode or ""):
        task = {}

    if not task and not args.task_file:
        active_task = load_active_task_candidate()
        if active_task and should_continue_from_feedback(active_task, message, args.mode or ""):
            task = active_task
            restored_from_active_task = True

    if not task:
        task, startup_snapshot, mode_snapshot = initialize_task_from_message(message, mode_override=args.mode or "")
        if task is None:
            result = {
                "ok": False,
                "orchestration_status": "needs_request",
                "message": "当前没有可执行需求，先给我具体出图需求。",
                "startup_snapshot": startup_snapshot,
            }
            output = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output_file:
                Path(args.output_file).write_text(output + "\n", encoding="utf-8")
            else:
                print(output)
            return
    else:
        task, mode_snapshot = merge_mode_route(task, message or str(task.get("raw_request") or ""), args.mode or "")
        if restored_from_active_task:
            startup_snapshot = task.get("startup_snapshot") if isinstance(task.get("startup_snapshot"), dict) else {}

    task = ensure_prompt_policy_defaults(task)
    memory_writeback_scopes = resolve_memory_writeback_scopes(args, message, task)
    persist_runtime_state = "log" in memory_writeback_scopes

    if startup_snapshot:
        task["startup_snapshot"] = startup_snapshot
    if mode_snapshot:
        task["mode_route_snapshot"] = mode_snapshot

    task, project_context_snapshot = merge_project_context(task, writeback=False)

    if str(task.get("startup_phase") or "").strip() == "onboarding_pending":
        checkpoint_info = save_task_outputs(
            task,
            task_file=args.task_file or "",
            checkpoint_file=args.checkpoint_file or "",
            persist=persist_runtime_state,
        )
        result = {
            "ok": True,
            "orchestration_status": "onboarding_pending",
            "task": task,
            "startup_snapshot": task.get("startup_snapshot") or {},
            "project_context": project_context_snapshot,
            "runtime_receipts": {"checkpoint": checkpoint_info},
            "message": "首次启动测试尚未完成，需求已缓存，先完成首次测试再继续当前任务。",
        }
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return

    if not args.skip_memory and not task.get("memory_snapshot"):
        task, memory_snapshot = ensure_memory_snapshot(task)
    else:
        memory_snapshot = task.get("memory_snapshot") or {}
    task, memory_consumption = attach_memory_consumption_snapshot(task, memory_snapshot)

    if should_continue_from_feedback(task, message, args.mode or ""):
        feedback_snapshot = apply_feedback_to_task(task, message, increment_round=True)
        task = ensure_prompt_policy_defaults(feedback_snapshot["task"])
        memory_writeback_scopes = resolve_memory_writeback_scopes(args, message, task)
        persist_runtime_state = "log" in memory_writeback_scopes

    try:
        task, prompt_package, knowledge_snapshot = run_knowledge_pipeline(
            task,
            force_regenerate=args.regenerate_prompt or bool(feedback_snapshot),
        )
    except (RuntimeError, ValueError) as exc:
        result = build_prompt_policy_blocked_result(
            task,
            str(exc),
            checkpoint_file=args.checkpoint_file or "",
            task_file=args.task_file or "",
            persist_memory_writeback=persist_runtime_state,
        )
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return

    selected_mode = str(task.get("mode") or "").strip()
    if not selected_mode:
        checkpoint_info = save_task_outputs(
            task,
            task_file=args.task_file or "",
            checkpoint_file=args.checkpoint_file or "",
            persist=persist_runtime_state,
        )
        result = {
            "ok": True,
            "orchestration_status": "needs_mode_selection",
            "task": task,
            "task_model": knowledge_snapshot.get("task_model") or {},
            "solution_plan": knowledge_snapshot.get("solution_plan") or {},
            "diagnosis_report": knowledge_snapshot.get("diagnosis_report") or {},
            "prompt_package": prompt_package,
            "mode_route_snapshot": task.get("mode_route_snapshot") or {},
            "project_context": project_context_snapshot,
            "runtime_receipts": {"checkpoint": checkpoint_info},
            "message": "需求已接住，但模式还不明确；自动模式默认走后台模式，如需复用当前页面可显式说前台模式。",
        }
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return

    prompt_validation = validate_execution_prompt(task.get("current_prompt"))
    if not prompt_validation.get("ok"):
        result = build_prompt_policy_blocked_result(
            task,
            "execution prompt 不合规：" + "；".join(prompt_validation["issues"]),
            checkpoint_file=args.checkpoint_file or "",
            task_file=args.task_file or "",
            persist_memory_writeback=persist_runtime_state,
        )
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return

    if normalize_prompt_policy(task.get("prompt_policy")) == PROMPT_POLICY_ENGLISH_ONLY and not is_english_prompt_text(
        task.get("current_prompt")
    ):
        result = build_prompt_policy_blocked_result(
            task,
            "当前任务仍然不是英文 prompt，已阻断执行。",
            checkpoint_file=args.checkpoint_file or "",
            task_file=args.task_file or "",
            persist_memory_writeback=persist_runtime_state,
        )
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return

    task["task_phase"] = "prompt_ready" if selected_mode == "automatic" else "manual_handoff"

    if selected_mode == "manual":
        try:
            task, prompt_package = prepare_task_prompt(task, force_regenerate=False)
        except ValueError as exc:
            result = build_prompt_policy_blocked_result(
                task,
                str(exc),
                checkpoint_file=args.checkpoint_file or "",
                task_file=args.task_file or "",
                persist_memory_writeback=persist_runtime_state,
            )
            output = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output_file:
                Path(args.output_file).write_text(output + "\n", encoding="utf-8")
            else:
                print(output)
            return
        task["mode"] = "manual"
        task["next_action"] = "await_user_feedback"
        task["should_continue"] = False
        artifacts = dict(task.get("artifacts") or {})
        artifacts["manual_handoff"] = prompt_package
        task["artifacts"] = artifacts
        task, project_writeback = merge_project_context(task, writeback=persist_runtime_state)
        checkpoint_info = save_task_outputs(
            task,
            task_file=args.task_file or "",
            checkpoint_file=args.checkpoint_file or "",
            persist=persist_runtime_state,
        )
        result = {
            "ok": True,
            "orchestration_status": "manual_handoff_ready",
            "task": task,
            "task_model": knowledge_snapshot.get("task_model") or {},
            "solution_plan": knowledge_snapshot.get("solution_plan") or {},
            "diagnosis_report": knowledge_snapshot.get("diagnosis_report") or {},
            "memory_snapshot": memory_snapshot,
            "memory_consumption_snapshot": memory_consumption,
            "prompt_package": prompt_package,
            "feedback_snapshot": feedback_snapshot,
            "project_context": project_writeback,
            "runtime_receipts": {"checkpoint": checkpoint_info},
        }
        if feedback_snapshot:
            result["message"] = "已更新手动模式 prompt。"
        else:
            result["message"] = "已生成手动模式 prompt。"
    else:
        task["mode"] = "automatic"
        if not args.execute_automatic:
            task["next_action"] = "execute_automatic_round"
            task["should_continue"] = False
            task, project_writeback = merge_project_context(task, writeback=persist_runtime_state)
            checkpoint_info = save_task_outputs(
                task,
                task_file=args.task_file or "",
                checkpoint_file=args.checkpoint_file or "",
                persist=persist_runtime_state,
            )
            result = {
                "ok": True,
                "orchestration_status": "automatic_ready_to_submit",
                "task": task,
                "task_model": knowledge_snapshot.get("task_model") or {},
                "solution_plan": knowledge_snapshot.get("solution_plan") or {},
                "diagnosis_report": knowledge_snapshot.get("diagnosis_report") or {},
                "memory_snapshot": memory_snapshot,
                "memory_consumption_snapshot": memory_consumption,
                "prompt_package": prompt_package,
                "feedback_snapshot": feedback_snapshot,
                "project_context": project_writeback,
                "runtime_receipts": {"checkpoint": checkpoint_info},
                "message": "已接住修改，正在后台生成。" if feedback_snapshot else "已接住需求，正在后台生成。",
            }
        else:
            automatic_backend = str(task.get("automatic_execution_backend") or "isolated_browser").strip()
            backend_health_before = build_backend_health_snapshot(task)
            blocked_reason, environment_check = detect_backend_environment_block(automatic_backend)
            automatic_deadline = time.monotonic() + AUTOMATIC_PARENT_TIMEOUT_SEC
            with managed_runtime_paths("mj-v02-auto") as temp_path:
                task_path = Path(args.task_file) if args.task_file else temp_path("task.json")
                result_path = temp_path("auto-result.json")
                write_json_file(task_path, task)
                if blocked_reason:
                    auto_result = build_environment_blocked_auto_result(blocked_reason, environment_check)
                else:
                    try:
                        if automatic_backend == "isolated_browser":
                            setup_result = prepare_isolated_browser_setup(
                                timeout_sec=remaining_automatic_timeout(automatic_deadline)
                            )
                            auto_result = run_node_script(
                                "midjourney_isolated_browser_once.mjs",
                                [
                                    "--task-file",
                                    str(task_path),
                                    "--output-file",
                                    str(result_path),
                                    "--state-path",
                                    str(setup_result.get("state_path") or ""),
                                    "--profile-dir",
                                    str(setup_result.get("profile_dir") or ""),
                                    "--browser",
                                    str(setup_result.get("browser_key") or ""),
                                    "--browser-path",
                                    str(setup_result.get("browser_path") or ""),
                                    "--port",
                                    str(setup_result.get("port") or ""),
                                    "--start-timeout-sec",
                                    str(AUTOMATIC_ROUND_START_TIMEOUT_SEC),
                                    "--complete-timeout-sec",
                                    str(AUTOMATIC_ROUND_COMPLETE_TIMEOUT_SEC),
                                ],
                                timeout_sec=remaining_automatic_timeout(automatic_deadline),
                            )
                            auto_result["setup"] = setup_result
                        else:
                            auto_result = run_powershell_script(
                                "midjourney_generate_once.ps1",
                                [
                                    "-TaskFile",
                                    str(task_path),
                                    "-OutputFile",
                                    str(result_path),
                                    "-StartTimeoutSec",
                                    str(AUTOMATIC_ROUND_START_TIMEOUT_SEC),
                                    "-CompleteTimeoutSec",
                                    str(AUTOMATIC_ROUND_COMPLETE_TIMEOUT_SEC),
                                ],
                                timeout_sec=remaining_automatic_timeout(automatic_deadline),
                            )
                    except AutomaticSubprocessTimeout as exc:
                        auto_result = {
                            "ok": False,
                            "completed": False,
                            "result_available": False,
                            "blocked_by_context": True,
                            "blocked_reason": "automatic_parent_timeout",
                            "error": str(exc),
                        }
                    except RuntimeError as exc:
                        auto_result = {
                            "ok": False,
                            "completed": False,
                            "result_available": False,
                            "blocked_by_context": True,
                            "blocked_reason": "automatic_backend_runtime_error",
                            "error": str(exc),
                        }

            execution_governance = classify_execution_governance(auto_result, automatic_backend)
            execution_governance["health_before"] = backend_health_before
            verdict_hint = str(execution_governance.get("verdict_hint") or "").strip()
            if verdict_hint == "blocked_by_ui":
                auto_result["blocked_by_ui"] = True
            elif verdict_hint == "blocked_by_context":
                auto_result["blocked_by_context"] = True
            apply_automatic_round_stop_flags(auto_result)
            if execution_governance.get("message") and not str(auto_result.get("result_summary") or "").strip():
                auto_result["result_summary"] = execution_governance["message"]
            auto_result["execution_governance"] = execution_governance

            artifacts = dict(task.get("artifacts") or {})
            artifacts["last_auto_result"] = auto_result
            artifacts["automatic_execution_backend"] = str(
                task.get("automatic_execution_backend") or auto_result.get("automatic_execution_backend") or ""
            ).strip()
            artifacts["execution_governance"] = execution_governance
            if auto_result.get("final_capture"):
                artifacts["final_capture"] = auto_result["final_capture"]
            if auto_result.get("window_state"):
                ui_state = dict(task.get("ui_state") or {})
                window_handle = auto_result["window_state"].get("window_handle")
                if window_handle:
                    ui_state["window_handle"] = window_handle
                task["ui_state"] = ui_state
            execution_governance["health_after"] = build_backend_health_snapshot(task)

            task["artifacts"] = artifacts
            task["last_result_summary"] = str(
                auto_result.get("result_summary") or task.get("last_result_summary") or ""
            ).strip()
            task["result_summary"] = task["last_result_summary"]
            task, post_run_diagnosis = rerun_post_execution_diagnosis(task)
            knowledge_snapshot["diagnosis_report"] = post_run_diagnosis
            merged_for_decision = dict(task)
            merged_for_decision.update(auto_result)
            merged_for_decision["artifacts"] = artifacts
            merged_for_decision["diagnosis_report"] = post_run_diagnosis
            decision = decide_next_action(merged_for_decision)
            task = apply_task_patch(task, decision["task_patch"])
            task, project_writeback = merge_project_context(task, writeback=persist_runtime_state)
            run_record = build_run_record(task, prompt_package, auto_result, decision)
            if "log" in memory_writeback_scopes:
                run_log_info = append_run_record(run_record)
                run_summary = build_run_summary(run_record)
            else:
                run_log_info = skipped_persistent_writeback_receipt("run_log")
                run_summary = skipped_persistent_writeback_receipt("run_summary")
            if "profile" in memory_writeback_scopes:
                profile_signal_info = extract_profile_signal(run_record)
                profile_candidate = (
                    profile_signal_info.get("candidate")
                    if isinstance(profile_signal_info.get("candidate"), dict)
                    else {}
                )
                profile_merge_info = merge_profile_candidate(profile_candidate)
            else:
                profile_signal_info = skipped_persistent_writeback_receipt("profile_signal")
                profile_merge_info = skipped_persistent_writeback_receipt("profile_merge")
            if "experience" in memory_writeback_scopes:
                experience_distill_info = distill_experience(run_record)
            else:
                experience_distill_info = skipped_persistent_writeback_receipt("experience_distill")
            if "template" in memory_writeback_scopes:
                template_candidate_info = upsert_template_candidate(run_record)
            else:
                template_candidate_info = skipped_persistent_writeback_receipt("template_candidate")
            artifacts = dict(task.get("artifacts") or {})
            artifacts["run_summary"] = run_summary
            artifacts["profile_signal"] = profile_signal_info
            artifacts["profile_merge"] = profile_merge_info
            artifacts["experience_distill"] = experience_distill_info
            artifacts["template_candidate"] = template_candidate_info
            task["artifacts"] = artifacts
            if str(template_candidate_info.get("candidate_key") or "").strip():
                task["template_candidate_keys"] = normalize_string_list(
                    list(task.get("template_candidate_keys") or [])
                    + [template_candidate_info["candidate_key"]]
                )
            if persist_runtime_state:
                task, project_writeback = merge_project_context(task, writeback=True)
            checkpoint_info = save_task_outputs(
                task,
                task_file=args.task_file or "",
                checkpoint_file=args.checkpoint_file or "",
                persist=persist_runtime_state,
            )

            result = {
                "ok": True,
                "orchestration_status": "automatic_round_executed",
                "task": task,
                "task_model": knowledge_snapshot.get("task_model") or {},
                "solution_plan": knowledge_snapshot.get("solution_plan") or {},
                "diagnosis_report": knowledge_snapshot.get("diagnosis_report") or {},
                "memory_snapshot": memory_snapshot,
                "memory_consumption_snapshot": memory_consumption,
                "prompt_package": prompt_package,
                "feedback_snapshot": feedback_snapshot,
                "auto_result": auto_result,
                "decision": decision,
                "project_context": project_writeback,
                "runtime_receipts": {
                    "checkpoint": checkpoint_info,
                    "run_log": run_log_info,
                    "run_summary": run_summary,
                    "profile_signal": profile_signal_info,
                    "profile_merge": profile_merge_info,
                    "experience_distill": experience_distill_info,
                    "template_candidate": template_candidate_info,
                },
            }
            if auto_result.get("completed") and auto_result.get("result_available"):
                result["message"] = "已按修改完成生成。" if feedback_snapshot else "生成完成。"
            else:
                result["message"] = build_user_facing_block_message(auto_result)

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
