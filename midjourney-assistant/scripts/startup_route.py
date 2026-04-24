import argparse
import json
import re
import sys
from pathlib import Path

from common import (
    BOOTSTRAP_STATE_PATH,
    configure_stdout,
    normalize_automatic_backend,
    normalize_mode_label,
    read_json_file,
)


SKILL_PATTERN = re.compile(r"^\s*\$?midjourney-assistant\b[:：,\s-]*", re.I)
LEADING_MODE_PATTERN = re.compile(
    r"^\s*(后台模式|前台模式|自动模式|手动模式|auto|automatic|manual)\s*[:：,，-]*\s*",
    re.I,
)
MODE_ONLY_TOKENS = {
    "自动模式",
    "手动模式",
    "后台模式",
    "前台模式",
    "auto",
    "automatic",
    "manual",
}


def parse_args():
    parser = argparse.ArgumentParser(description="按启动状态路由 Midjourney 任务入口")
    parser.add_argument("--message", help="用户原始消息")
    parser.add_argument("--input-file", help="输入文件路径")
    parser.add_argument("--bootstrap-file", help="bootstrap 状态文件路径")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def load_input(args):
    if args.message:
        return args.message.strip()
    if args.input_file:
        return Path(args.input_file).read_text(encoding="utf-8-sig").strip()
    return sys.stdin.read().strip()


def extract_message(raw_input: str) -> str:
    if not raw_input:
        return ""
    try:
        parsed = json.loads(raw_input)
    except json.JSONDecodeError:
        return raw_input.strip()
    if isinstance(parsed, dict):
        for key in ["message", "raw_request", "request", "input", "goal"]:
            value = str(parsed.get(key) or "").strip()
            if value:
                return value
    if isinstance(parsed, str):
        return parsed.strip()
    return raw_input.strip()


def detect_explicit_mode(text: str) -> str:
    explicit_backend = detect_explicit_backend(text)
    if explicit_backend:
        return "automatic"
    if re.search(r"(?:^|[\s，,。：:])自动模式(?:$|[\s，,。：:])", text):
        return "automatic"
    if re.search(r"(?:^|[\s，,。：:])手动模式(?:$|[\s，,。：:])", text):
        return "manual"
    normalized = normalize_mode_label(text)
    return normalized if normalized in {"automatic", "manual"} else ""


def detect_explicit_backend(text: str) -> str:
    if re.search(r"(?:^|[\s，,。：:])后台模式(?:$|[\s，,。：:])", text):
        return "isolated_browser"
    if re.search(r"(?:^|[\s，,。：:])前台模式(?:$|[\s，,。：:])", text):
        return "window_uia"
    normalized = normalize_automatic_backend(text)
    return normalized if normalized in {"isolated_browser", "window_uia"} else ""


def clean_request_text(text: str) -> str:
    cleaned = SKILL_PATTERN.sub("", text.strip())
    cleaned = LEADING_MODE_PATTERN.sub("", cleaned)
    return cleaned.strip()


def load_bootstrap_state(path: Path):
    state = read_json_file(path, default={})
    if not isinstance(state, dict):
        return {}
    return state


def main():
    configure_stdout()
    args = parse_args()
    raw_input = load_input(args)
    message = extract_message(raw_input)
    cleaned_request = clean_request_text(message)
    explicit_mode = detect_explicit_mode(message)
    explicit_backend = detect_explicit_backend(message)

    mode_only = bool(explicit_mode or explicit_backend) and not bool(cleaned_request)
    has_task = bool(cleaned_request) and not mode_only

    bootstrap_path = Path(args.bootstrap_file) if args.bootstrap_file else BOOTSTRAP_STATE_PATH
    bootstrap_state = load_bootstrap_state(bootstrap_path)
    setup_completed = bool(bootstrap_state.get("setup_completed"))
    needs_onboarding = not setup_completed

    if needs_onboarding and has_task:
        suggested_next = "cache_request_then_onboard"
    elif needs_onboarding:
        suggested_next = "show_onboarding_intro"
    elif has_task:
        suggested_next = "initialize_task"
    elif mode_only:
        suggested_next = "await_request_after_mode"
    else:
        suggested_next = "show_startup_intro"

    result = {
        "startup_phase": "onboarding_pending" if needs_onboarding else "ready",
        "task_phase": "received" if has_task else "idle",
        "needs_onboarding": needs_onboarding,
        "setup_completed": setup_completed,
        "has_task": has_task,
        "mode_only": mode_only,
        "explicit_mode": explicit_mode,
        "explicit_backend": explicit_backend,
        "raw_message": message,
        "request_text": cleaned_request if has_task else "",
        "should_run_onboarding_test": needs_onboarding,
        "should_preserve_request": bool(needs_onboarding and has_task),
        "should_show_intro": not has_task,
        "should_ask_for_request": not has_task,
        "suggested_next": suggested_next,
        "default_automatic_backend": "isolated_browser",
        "bootstrap_state_path": str(bootstrap_path),
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
