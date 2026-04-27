import argparse
import json
from pathlib import Path

from common import (
    BOOTSTRAP_STATE_PATH,
    ENVIRONMENT_NOTES_PATH,
    build_dependency_repair_plan,
    configure_stdout,
    detect_runtime_environment,
    execute_dependency_repair_plan,
    now_iso,
    read_text,
    write_text,
)


DEFAULT_STEPS = [
    "如果你要用自动模式，先把 Codex 的权限切换成**完全访问权限**；手动模式不需要这一步。",
    "自动模式默认走后台模式：我会自己拉起独立浏览器完成首次测试，不需要你先打开当前主浏览器页面，也不会占用你现在正在使用的主浏览器。",
    "如果这套独立浏览器还没登录 Midjourney，首次只需要你在那套独立浏览器里配合登录一次；登录完成后我会继续同一轮测试。",
    "如果这台电脑一个可用的后台浏览器都没检测到，我会直接提示你先安装 Edge，再继续首次测试。",
    "自动模式当前要求 Windows 桌面环境，并且本机要有可用的 PowerShell、Node.js 和受支持的 Chromium 浏览器。",
    "只有你明确说“前台模式”时，我才改用你当前已打开的页面；这时才要求你不要最小化页面，也尽量不要和自动操作同时抢鼠标键盘。",
    "首次测试只做一轮最小闭环：确认页面可识别、prompt 可提交、任务能开始、结果能读回。",
    "如果首测发现缺少 Node.js、PowerShell 或后台浏览器，你可以直接说“修复依赖”，我再尝试安装；默认不会静默安装系统软件。",
    "首轮成功后，我会记录当前站点、执行后端和使用环境，后面就直接进入正式任务。",
]

MINIMAL_FIRST_TEST_CONTRACT = [
    {
        "layer": "preflight",
        "goal": "先确认本机具备自动模式启动前提。",
        "failure_surface": "preflight_layers",
        "blocking_reasons": [
            "unsupported_platform",
            "powershell_runtime_missing",
            "node_runtime_missing",
            "runtime_write_unavailable",
            "no_supported_browser_found",
        ],
    },
    {
        "layer": "browser_session",
        "goal": "后台模式能拉起或复用独立浏览器，并进入 Midjourney 登录态。",
        "failure_surface": "auto_result.execution_governance",
        "blocking_reasons": [
            "needs_isolated_browser_login",
            "isolated_browser_challenge_page",
            "automatic_backend_runtime_error",
        ],
    },
    {
        "layer": "page_input",
        "goal": "页面可识别，prompt 输入区可定位并可提交。",
        "failure_surface": "auto_result.execution_governance",
        "blocking_reasons": [
            "isolated_browser_input_not_ready",
            "prompt_region_not_found",
            "prompt_region_unconfirmed",
        ],
    },
    {
        "layer": "submission",
        "goal": "最小 prompt 能成功发起生成，不在启动阶段超时。",
        "failure_surface": "auto_result.execution_governance",
        "blocking_reasons": [
            "start_timeout",
            "automatic_backend_runtime_error",
        ],
    },
    {
        "layer": "result_readback",
        "goal": "结果区域能对应到本轮 prompt，并在时间预算内读回。",
        "failure_surface": "auto_result.execution_governance",
        "blocking_reasons": [
            "complete_timeout",
            "prompt_region_not_found",
            "prompt_region_unconfirmed",
        ],
    },
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
    parser.add_argument("--repair-dependencies", action="store_true", help="用户明确授权后，尝试安装缺失的系统依赖")
    parser.add_argument("--repair-dry-run", action="store_true", help="只输出依赖修复计划，不实际安装")
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
    steps = [
        str(layer.get("user_message") or "").strip()
        for layer in environment_check.get("required_preflight_blocks") or []
        if str(layer.get("user_message") or "").strip()
    ]
    return steps


def build_dependency_repair_steps(repair_plan: dict):
    if not repair_plan.get("can_attempt_repair"):
        return []
    names = [
        str(action.get("display_name") or "").strip()
        for action in repair_plan.get("repairable_actions") or []
        if str(action.get("display_name") or "").strip()
    ]
    if not names:
        return []
    return [
        "检测到可自动尝试修复的系统依赖："
        + "、".join(names)
        + "；你可以直接说“修复依赖”，我再尝试安装。默认不会静默安装系统软件。"
    ]


def build_dependency_repair_notice(repair_plan: dict) -> str:
    if not repair_plan.get("can_attempt_repair"):
        return ""
    names = [
        str(action.get("display_name") or "").strip()
        for action in repair_plan.get("repairable_actions") or []
        if str(action.get("display_name") or "").strip()
    ]
    if not names:
        return ""
    return "这些属于可尝试自动修复的系统依赖；你可以直接说“修复依赖”，我再尝试安装。默认不会静默安装系统软件。"


def build_message(needs_onboarding: bool, environment_check: dict, repair_plan: dict) -> str:
    first_block = environment_check.get("first_required_preflight_block") or {}
    repair_notice = build_dependency_repair_notice(repair_plan)
    if not needs_onboarding:
        if first_block:
            return (
                "当前基础引导已完成，但自动模式依赖检查未通过。"
                f"{str(first_block.get('user_message') or '').strip()}"
                f"{repair_notice}"
            )
        return "已具备基础启动条件，可直接进入正常任务流程。"
    environment_note = ""
    if first_block:
        environment_note = str(first_block.get("user_message") or "").strip()
    return (
        "这是首次启动或首次引导尚未完成。"
        "如果你要用自动模式，先把 Codex 的权限切换成**完全访问权限**；手动模式不需要这一步。"
        "自动模式默认走后台模式，我会自己拉起独立浏览器完成首次测试；"
        "只有那套独立浏览器还没登录时，才需要你配合登录一次。"
        "如果这台电脑连一个可用的后台浏览器都没检测到，我会直接建议你先安装 Edge。"
        f"{environment_note}"
        f"{repair_notice}"
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
    repair_plan = build_dependency_repair_plan(environment_check)
    dependency_repair = {
        "requested": False,
        "dry_run": False,
        "attempted": False,
        "plan": repair_plan,
        "outcomes": [],
    }

    if args.repair_dependencies:
        repair_execution = execute_dependency_repair_plan(repair_plan, dry_run=args.repair_dry_run)
        environment_check = detect_runtime_environment()
        repair_plan = build_dependency_repair_plan(environment_check)
        dependency_repair = {
            **repair_execution,
            "plan": repair_plan,
            "post_repair_required_preflight_blocks": environment_check.get("required_preflight_blocks") or [],
            "post_repair_can_run_minimal_first_test": bool(environment_check.get("can_run_minimal_first_test")),
        }

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

    recommended_steps = []
    if needs_onboarding:
        recommended_steps.extend(DEFAULT_STEPS)
    if needs_onboarding or environment_check.get("required_preflight_blocks"):
        recommended_steps.extend(build_environment_steps(environment_check))
        recommended_steps.extend(build_dependency_repair_steps(repair_plan))

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
        "message": build_message(needs_onboarding, environment_check, repair_plan),
        "recommended_steps": recommended_steps,
        "environment_check": environment_check,
        "preflight_layers": environment_check.get("preflight_layers") or [],
        "required_preflight_blocks": environment_check.get("required_preflight_blocks") or [],
        "nonfatal_preflight_warnings": environment_check.get("nonfatal_preflight_warnings") or [],
        "can_run_minimal_first_test": bool(environment_check.get("can_run_minimal_first_test")),
        "minimal_first_test_contract": MINIMAL_FIRST_TEST_CONTRACT,
        "dependency_repair_plan": repair_plan,
        "dependency_repair": dependency_repair,
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
