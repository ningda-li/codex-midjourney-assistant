import argparse
import json
import re
import sys
from pathlib import Path

from common import (
    configure_stdout,
    normalize_automatic_backend,
    normalize_mode_label,
    read_json_file,
)


AUTO_HINTS = [
    "你帮我生成",
    "你帮我操作",
    "你来操作",
    "你直接操作",
    "你去提交",
    "代我操作",
    "帮我在midjourney",
    "帮我出图",
    "直接生成",
    "你来跑",
]

MANUAL_HINTS = [
    "给我prompt",
    "给我提示词",
    "只要prompt",
    "只要提示词",
    "我自己生成",
    "我自己来",
    "我来生成",
    "不要操作网页",
    "别操作网页",
    "只对话",
    "参数建议就行",
]

BACKGROUND_HINTS = [
    "后台模式",
    "后台自动模式",
    "后台自动",
    "后台生成",
    "后台跑",
    "独立浏览器",
    "不要打断我",
    "不碰我当前浏览器",
]

FOREGROUND_HINTS = [
    "前台模式",
    "前台自动模式",
    "前台自动",
    "当前页面",
    "当前网页",
    "当前窗口",
    "复用当前页面",
    "复用当前窗口",
    "沿用当前页面",
]

ENGLISH_MODE_PREFIX = (
    r"background(?:\s+mode)?|foreground(?:\s+mode)?|automatic(?:\s+mode)?|auto(?:\s+mode)?|manual(?:\s+mode)?"
)
MODE_BOUNDARY_PATTERN = r"(?:^|[\s,.:;,\uFF0C\u3002\uFF1A])"
LEADING_MODE_PATTERN = re.compile(
    rf"^\s*(\u540e\u53f0\u6a21\u5f0f|\u524d\u53f0\u6a21\u5f0f|\u81ea\u52a8\u6a21\u5f0f|\u624b\u52a8\u6a21\u5f0f|{ENGLISH_MODE_PREFIX})\s*[:\uFF1A,\uFF0C-]*\s*",
    re.I,
)


def parse_args():
    parser = argparse.ArgumentParser(description="为 Midjourney 任务路由自动模式或手动模式")
    parser.add_argument("--message", help="用户消息")
    parser.add_argument("--input-file", help="输入文件路径")
    parser.add_argument("--task-file", help="统一任务对象文件路径")
    parser.add_argument("--mode", help="显式模式覆盖")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def load_raw_input(args):
    if args.message:
        return args.message.strip()
    if args.input_file:
        return Path(args.input_file).read_text(encoding="utf-8-sig").strip()
    return sys.stdin.read().strip()


def extract_payload(text: str):
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text.strip(), {}
    if isinstance(parsed, dict):
        for key in ["message", "raw_request", "request", "input", "goal"]:
            value = str(parsed.get(key) or "").strip()
            if value:
                return value, parsed
        return "", parsed
    if isinstance(parsed, str):
        return parsed.strip(), {}
    return text.strip(), {}


def detect_explicit_backend(text: str, override: str = "") -> str:
    normalized_override = normalize_automatic_backend(override)
    if normalized_override in {"isolated_browser", "window_uia"}:
        return normalized_override
    if re.search(r"(?:^|[\s，。：:])后台模式(?:$|[\s，。：:])", text):
        return "isolated_browser"
    if re.search(r"(?:^|[\s，。：:])前台模式(?:$|[\s，。：:])", text):
        return "window_uia"
    if re.search(rf"{MODE_BOUNDARY_PATTERN}background(?:\s+mode)?(?:$|[\s,.:;,\uFF0C\u3002\uFF1A])", text, re.I):
        return "isolated_browser"
    if re.search(rf"{MODE_BOUNDARY_PATTERN}foreground(?:\s+mode)?(?:$|[\s,.:;,\uFF0C\u3002\uFF1A])", text, re.I):
        return "window_uia"
    normalized_text = normalize_automatic_backend(text)
    return normalized_text if normalized_text in {"isolated_browser", "window_uia"} else ""


def detect_explicit_mode(text: str, override: str = "") -> str:
    normalized_override = normalize_mode_label(override)
    if normalized_override in {"automatic", "manual"}:
        return normalized_override
    if detect_explicit_backend(text, override):
        return "automatic"
    if re.search(r"(?:^|[\s，。：:])自动模式(?:$|[\s，。：:])", text):
        return "automatic"
    if re.search(r"(?:^|[\s，。：:])手动模式(?:$|[\s，。：:])", text):
        return "manual"
    if re.search(rf"{MODE_BOUNDARY_PATTERN}(?:automatic|auto)(?:\s+mode)?(?:$|[\s,.:;,\uFF0C\u3002\uFF1A])", text, re.I):
        return "automatic"
    if re.search(rf"{MODE_BOUNDARY_PATTERN}manual(?:\s+mode)?(?:$|[\s,.:;,\uFF0C\u3002\uFF1A])", text, re.I):
        return "manual"
    normalized_text = normalize_mode_label(text)
    return normalized_text if normalized_text in {"automatic", "manual"} else ""


def strip_mode_prefix(text: str) -> str:
    return LEADING_MODE_PATTERN.sub("", text.strip()).strip()


def infer_mode(text: str) -> str:
    lowered = text.lower()
    if any(token in text for token in BACKGROUND_HINTS + FOREGROUND_HINTS):
        return "automatic"
    if any(token in text for token in AUTO_HINTS):
        return "automatic"
    if any(token in text for token in MANUAL_HINTS):
        return "manual"
    if "自己生成" in text or "自己来" in text:
        return "manual"
    if "帮我" in text and ("生成" in text or "出图" in text or "操作" in text):
        return "automatic"
    if "给我" in text and ("prompt" in lowered or "提示词" in text):
        return "manual"
    return ""


def infer_backend(text: str, override: str = "", existing_backend: str = "") -> str:
    explicit_backend = detect_explicit_backend(text, override)
    if explicit_backend:
        return explicit_backend
    if any(token in text for token in BACKGROUND_HINTS):
        return "isolated_browser"
    if any(token in text for token in FOREGROUND_HINTS):
        return "window_uia"
    normalized_existing = normalize_automatic_backend(existing_backend)
    if normalized_existing in {"isolated_browser", "window_uia"}:
        return normalized_existing
    return "isolated_browser"


def main():
    configure_stdout()
    args = parse_args()
    raw_input = load_raw_input(args)
    message, payload = extract_payload(raw_input)
    task = read_json_file(Path(args.task_file), default={}) if args.task_file else {}
    if not isinstance(task, dict):
        task = {}

    existing_mode = normalize_mode_label(task.get("mode"))
    existing_backend = normalize_automatic_backend(task.get("automatic_execution_backend"))
    backend_override = str(
        payload.get("automatic_execution_backend")
        or payload.get("execution_backend")
        or payload.get("backend")
        or ""
    ).strip()
    explicit_mode = detect_explicit_mode(message, args.mode or str(payload.get("mode") or ""))
    request_text = strip_mode_prefix(message)
    has_task = bool(request_text)

    if explicit_mode:
        selected_mode = explicit_mode
        reason = "explicit_mode"
    else:
        inferred_mode = infer_mode(request_text or str(task.get("raw_request") or ""))
        if inferred_mode:
            selected_mode = inferred_mode
            reason = "semantic_inference"
        elif existing_mode in {"automatic", "manual"}:
            selected_mode = existing_mode
            reason = "existing_task_mode"
        else:
            selected_mode = ""
            reason = "needs_confirmation"

    selected_backend = ""
    if selected_mode == "automatic":
        selected_backend = infer_backend(
            message or request_text or str(task.get("raw_request") or ""),
            override=backend_override,
            existing_backend=existing_backend,
        )

    result = {
        "selected_mode": selected_mode,
        "selected_backend": selected_backend,
        "automatic_execution_backend": selected_backend,
        "reason": reason,
        "should_ask_mode": has_task and not bool(selected_mode),
        "should_ask_for_request": not has_task,
        "has_task": has_task,
        "request_text": request_text,
        "explicit_mode": explicit_mode,
        "existing_mode": existing_mode,
        "explicit_backend": detect_explicit_backend(message, backend_override),
        "existing_backend": existing_backend,
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
