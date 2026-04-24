import argparse
import json
from pathlib import Path

from common import (
    BOOTSTRAP_STATE_PATH,
    ENVIRONMENT_NOTES_PATH,
    configure_stdout,
    detect_runtime_environment,
    now_iso,
    read_text,
    write_text,
)


DEFAULT_STEPS = [
    "自动模式默认走后台模式：我会自己拉起独立浏览器完成首次测试，不需要你先打开当前主浏览器页面，也不会占用你现在正在使用的主浏览器。",
    "如果这套独立浏览器还没登录 Midjourney，首次只需要你在那套独立浏览器里配合登录一次；登录完成后我会继续同一轮测试。",
    "如果这台电脑一个可用的后台浏览器都没检测到，我会直接提示你先安装 Edge，再继续首次测试。",
    "自动模式当前要求 Windows 桌面环境，并且本机要有可用的 PowerShell、Node.js 和受支持的 Chromium 浏览器。",
    "只有你明确说“前台模式”时，我才改用你当前已打开的页面；这时才要求你不要最小化页面，也尽量不要和自动操作同时抢鼠标键盘。",
    "首次测试只做一轮最小闭环：确认页面可识别、prompt 可提交、任务能开始、结果能读回。",
    "首轮成功后，我会记录当前站点、执行后端和使用环境，后面就直接进入正式任务。",
]


def parse_args():
    parser = argparse.ArgumentParser(description="检查 Midjourney 使用助手是否仍处于首次引导阶段")
    parser.add_argument("--state-file", help="bootstrap 状态文件路径")
    parser.add_argument("--environment-file", help="环境记录文件路径")
    parser.add_argument("--output-file", help="输出 JSON 文件路径")
    parser.add_argument("--mark-seen", action="store_true", help="记录首次看到这个 skill")
    parser.add_argument("--mark-complete", action="store_true", help="标记首次引导已完成")
    parser.add_argument("--host", help="记录当前站点 host")
    parser.add_argument("--browser", help="记录当前浏览器")
    parser.add_argument("--environment-summary", help="记录当前环境摘要")
    return parser.parse_args()


def load_state(path: Path) -> dict:
    content = read_text(path, default="").strip()
    if not content:
        return {}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def save_state(path: Path, state: dict) -> None:
    write_text(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def environment_ready(path: Path) -> bool:
    return bool(read_text(path, default="").strip())


def append_environment_note(path: Path, note: str) -> None:
    existing = read_text(path, default="")
    lines = [line.rstrip() for line in existing.splitlines()] if existing else []
    if not lines:
        lines = [
            "# 使用环境记录",
            "",
        ]
    lines.extend(
        [
            f"## {now_iso()}",
            "",
            note.strip(),
            "",
        ]
    )
    write_text(path, "\n".join(lines).strip() + "\n")


def build_environment_steps(environment_check: dict):
    steps = []
    if not environment_check.get("os_supported"):
        steps.append("当前自动模式只支持 Windows 桌面环境；如果这台电脑不是 Windows，先直接改走手动模式。")
    if not environment_check.get("powershell_available"):
        steps.append("当前没有检测到可用的 PowerShell；自动模式启动前需要先安装 PowerShell。")
    if not environment_check.get("node_available"):
        steps.append("当前没有检测到 Node.js；后台自动模式启动前需要先安装 Node.js。")
    if environment_check.get("os_supported") and not environment_check.get("supported_browser_found"):
        steps.append("当前没有检测到受支持的 Chromium 浏览器；建议先安装 Edge。")
    return steps


def build_message(needs_onboarding: bool, environment_check: dict) -> str:
    if not needs_onboarding:
        return "已具备基础启动条件，可直接进入正常任务流程。"
    environment_note = ""
    if not environment_check.get("os_supported"):
        environment_note = "当前自动模式只支持 Windows 桌面环境。"
    elif not environment_check.get("powershell_available"):
        environment_note = "当前这台电脑缺少可用的 PowerShell。"
    elif not environment_check.get("node_available"):
        environment_note = "当前这台电脑缺少 Node.js。"
    elif not environment_check.get("supported_browser_found"):
        environment_note = "当前这台电脑没有检测到可用的后台浏览器。"
    return (
        "这是首次启动或首次引导尚未完成。"
        "自动模式默认走后台模式，我会自己拉起独立浏览器完成首次测试；"
        "只有那套独立浏览器还没登录时，才需要你配合登录一次。"
        "如果这台电脑连一个可用的后台浏览器都没检测到，我会直接建议你先安装 Edge。"
        f"{environment_note}"
        "如果你明确说前台模式，我才改用你当前已打开的页面。"
    )


def main():
    configure_stdout()
    args = parse_args()
    state_path = Path(args.state_file) if args.state_file else BOOTSTRAP_STATE_PATH
    environment_path = Path(args.environment_file) if args.environment_file else ENVIRONMENT_NOTES_PATH
    state = load_state(state_path)
    now = now_iso()
    environment_check = detect_runtime_environment()

    if args.mark_seen:
        state.setdefault("first_seen_at", now)
        state["last_checked_at"] = now

    if args.mark_complete:
        state.setdefault("first_seen_at", now)
        state["last_checked_at"] = now
        state["setup_completed"] = True
        state["setup_completed_at"] = now
        if args.host:
            state["last_host"] = args.host.strip()
        if args.browser:
            state["last_browser"] = args.browser.strip()
        if args.environment_summary:
            append_environment_note(environment_path, args.environment_summary)

    has_state = bool(state)
    setup_completed = bool(state.get("setup_completed"))
    has_environment_notes = environment_ready(environment_path)
    needs_onboarding = (not has_state) or (not setup_completed)

    if args.mark_seen or args.mark_complete:
        save_state(state_path, state)

    result = {
        "is_first_run": needs_onboarding,
        "needs_onboarding": needs_onboarding,
        "has_bootstrap_state": has_state,
        "setup_completed": setup_completed,
        "has_environment_notes": has_environment_notes,
        "default_automatic_backend": "isolated_browser",
        "foreground_automatic_backend": "window_uia",
        "state_path": str(state_path),
        "environment_path": str(environment_path),
        "message": build_message(needs_onboarding, environment_check),
        "recommended_steps": (DEFAULT_STEPS + build_environment_steps(environment_check)) if needs_onboarding else [],
        "environment_check": environment_check,
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
