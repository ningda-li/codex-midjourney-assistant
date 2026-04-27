import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4


CODEX_HOME = Path(__file__).resolve().parents[3]
SKILL_ROOT = Path(__file__).resolve().parents[1]
MEMORY_ROOT = CODEX_HOME / "memories" / "midjourney-assistant"
ASSET_ROOT = SKILL_ROOT / "assets"
PROFILE_PATH = MEMORY_ROOT / "user-profile" / "profile.md"
PREFERENCE_SIGNALS_PATH = MEMORY_ROOT / "user-profile" / "preference-signals.jsonl"
TABOO_SIGNALS_PATH = MEMORY_ROOT / "user-profile" / "taboo-signals.jsonl"
DISTILLED_PATTERNS_PATH = MEMORY_ROOT / "distilled-patterns.md"
FAILURE_PATTERNS_PATH = MEMORY_ROOT / "failure-patterns.md"
SITE_CHANGELOG_PATH = MEMORY_ROOT / "site-changelog.md"
BOOTSTRAP_STATE_PATH = MEMORY_ROOT / "bootstrap-state.json"
ENVIRONMENT_NOTES_PATH = MEMORY_ROOT / "environment-notes.md"
TEMPLATE_CANDIDATES_ROOT = MEMORY_ROOT / "template-candidates"
TASK_TEMPLATE_CANDIDATES_DIR = TEMPLATE_CANDIDATES_ROOT / "task-templates"
SUBSKILL_PROPOSALS_DIR = TEMPLATE_CANDIDATES_ROOT / "subskills"
REVIEW_QUEUE_PATH = MEMORY_ROOT / "review-queue.jsonl"
TASK_PATTERNS_PATH = MEMORY_ROOT / "task-patterns.md"
ISOLATED_BROWSER_ROOT = MEMORY_ROOT / "isolated-browser"
ISOLATED_BROWSER_PROFILE_DIR = ISOLATED_BROWSER_ROOT / "edge-profile"
ISOLATED_BROWSER_STATE_PATH = ISOLATED_BROWSER_ROOT / "runtime-state.json"
RUNTIME_WORK_ROOT = MEMORY_ROOT / "runtime"
ACTIVE_TASK_STATE_PATH = MEMORY_ROOT / "runs" / "active-task.json"
PROMPT_TERMINOLOGY_PATH = ASSET_ROOT / "prompt-terminology.json"

ALLOWED_VERDICTS = {
    "success",
    "usable_but_iterate",
    "blocked_by_ui",
    "blocked_by_context",
    "stopped_by_user",
    "stopped_by_budget",
}

HARD_DIAGNOSIS_ISSUES = {
    "subject_mismatch",
    "feedback_not_applied",
    "structure_drift",
    "base_lock_missing",
    "colorway_axis_broken",
}

CHARACTER_SUBJECT_KEYWORDS = [
    "character",
    "game character",
    "hero",
    "\u89d2\u8272",
    "\u4eba\u7269",
    "\u4e3b\u89d2",
]
PRODUCT_SUBJECT_KEYWORDS = ["product", "\u5546\u54c1", "\u4ea7\u54c1"]
SCENE_SUBJECT_KEYWORDS = ["scene", "environment", "\u573a\u666f", "\u73af\u5883"]
GAME_CHARACTER_ROLE_KEYWORDS = [
    "game character",
    "hero shooter",
    "playable hero",
    "\u6e38\u620f\u89d2\u8272",
    "\u53ef\u73a9\u89d2\u8272",
]
MODERN_IDENTITY_KEYWORDS = ["modern", "\u73b0\u4ee3"]
NO_WOMEN_CONSTRAINT_KEYWORDS = [
    "\u4e0d\u8981\u5973\u6027",
    "\u4e0d\u8981\u5973\u7684",
    "\u4e0d\u8981\u5973\u4eba",
    "no women",
    "no woman",
]
NO_MEN_CONSTRAINT_KEYWORDS = [
    "\u4e0d\u8981\u7537\u6027",
    "\u4e0d\u8981\u7537\u7684",
    "\u4e0d\u8981\u7537\u4eba",
    "no men",
    "no man",
]
NO_GROUP_CONSTRAINT_KEYWORDS = [
    "\u4e0d\u8981\u591a\u4eba",
    "\u4e0d\u8981\u7fa4\u50cf",
    "\u4e0d\u8981\u591a\u4e2a\u4eba",
    "no group",
    "no extra characters",
    "single character only",
]
MALE_SUBJECT_KEYWORDS = [
    "\u7537\u6027",
    "\u7537\u89d2\u8272",
    "\u7537\u4eba",
    "male",
    "man",
    "boy",
]
FEMALE_SUBJECT_KEYWORDS = [
    "\u5973\u6027",
    "\u5973\u89d2\u8272",
    "\u5973\u4eba",
    "female",
    "woman",
    "girl",
]
SINGLE_SUBJECT_KEYWORDS = [
    "\u5355\u4eba",
    "\u5355\u4e2a",
    "solo",
    "single character",
    "one character",
    "one man",
    "one woman",
]
GROUP_SUBJECT_KEYWORDS = [
    "\u591a\u4eba",
    "\u7fa4\u50cf",
    "group",
    "multiple characters",
    "four characters",
    "4 characters",
]
YOUTH_SUBJECT_KEYWORDS = [
    "\u7537\u5b69",
    "\u5973\u5b69",
    "\u5c11\u5e74",
    "\u5c11\u5973",
    "boy",
    "girl",
]
ADULT_SUBJECT_KEYWORDS = [
    "\u6210\u5e74",
    "\u7537\u6027",
    "\u5973\u6027",
    "\u7537\u4eba",
    "\u5973\u4eba",
    "adult",
    "male",
    "female",
    "man",
    "woman",
]
FRONT_VIEW_KEYWORDS = ["\u6b63\u9762", "front-facing", "front facing", "front view"]
FULL_BODY_KEYWORDS = ["\u5168\u8eab", "full-body", "full body"]
HALF_BODY_KEYWORDS = ["\u534a\u8eab", "half-body", "half body", "close-up", "close up"]
STANDING_POSE_KEYWORDS = ["\u7ad9\u7acb", "\u7ad9\u59ff", "standing pose", "standing"]

PROMPT_POLICY_ENGLISH_ONLY = "english_only"
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_PROMPT_TERMINOLOGY_CACHE = None
SUPPORTED_DESKTOP_BROWSERS = [
    {
        "key": "edge",
        "name": "Edge",
        "process_name": "msedge.exe",
        "candidate_paths": [
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        ],
    },
    {
        "key": "chrome",
        "name": "Chrome",
        "process_name": "chrome.exe",
        "candidate_paths": [
            os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ],
    },
    {
        "key": "brave",
        "name": "Brave",
        "process_name": "brave.exe",
        "candidate_paths": [
            os.path.join(os.environ.get("ProgramFiles", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        ],
    },
    {
        "key": "vivaldi",
        "name": "Vivaldi",
        "process_name": "vivaldi.exe",
        "candidate_paths": [
            os.path.join(os.environ.get("ProgramFiles", ""), "Vivaldi", "Application", "vivaldi.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Vivaldi", "Application", "vivaldi.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Vivaldi", "Application", "vivaldi.exe"),
        ],
    },
    {
        "key": "arc",
        "name": "Arc",
        "process_name": "arc.exe",
        "candidate_paths": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Arc", "Arc.exe"),
        ],
    },
]
EXECUTION_PROMPT_META_MARKERS = [
    "target output",
    "this round focus",
    "preferred deliverable cues",
    "preferred style cues",
    "preferred content cues",
    "project continuity cues",
    "proven pattern cues",
    "quality tendency",
    "lock the subject and style",
    "prioritize validating",
]
EXECUTION_PROMPT_SELECTION_MARKERS = [
    "options for selection",
    "draft options",
    "for review",
    "moodboard options",
]
EXECUTION_PROMPT_REQUEST_PATTERNS = [
    (re.compile(r"\bi want\b", re.I), "包含请求语 i want"),
    (re.compile(r"\bhelp me\b", re.I), "包含请求语 help me"),
    (re.compile(r"\bplease\b", re.I), "包含请求语 please"),
    (re.compile(r"^\s*(create|make|generate)\b", re.I), "以请求动作词开头"),
    (
        re.compile(r"\bcreate(?:male|female|boy|girl|character|cat|warrior|poster|concept)\b", re.I),
        "包含疑似词语粘连",
    ),
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def get_powershell_command() -> str:
    candidates = [
        shutil.which("powershell"),
        shutil.which("pwsh"),
        os.path.join(os.environ.get("SystemRoot", r"C:\WINDOWS"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "PowerShell", "7", "pwsh.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    return ""


def get_node_command() -> str:
    candidates = [
        shutil.which("node"),
        os.path.join(os.environ.get("ProgramFiles", ""), "nodejs", "node.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "nodejs", "node.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    return ""


def detect_supported_browser_installations():
    installations = []
    for definition in SUPPORTED_DESKTOP_BROWSERS:
        resolved_path = ""
        for candidate_path in definition["candidate_paths"]:
            if candidate_path and Path(candidate_path).exists():
                resolved_path = str(Path(candidate_path))
                break
        if resolved_path:
            installations.append(
                {
                    "key": definition["key"],
                    "name": definition["name"],
                    "path": resolved_path,
                    "process_name": definition["process_name"],
                }
            )
    return installations


def build_preflight_layer(
    name: str,
    ok: bool,
    *,
    required: bool = True,
    blocked_reason: str = "",
    recoverability: str = "",
    recommended_action: str = "",
    user_message: str = "",
    details: dict | None = None,
):
    return {
        "name": name,
        "ok": bool(ok),
        "required": bool(required),
        "blocked_reason": str(blocked_reason or "").strip(),
        "recoverability": str(recoverability or "").strip(),
        "recommended_action": str(recommended_action or "").strip(),
        "user_message": str(user_message or "").strip(),
        "details": details or {},
    }


def resolve_command_path(command: str) -> str:
    command_text = str(command or "").strip()
    if not command_text:
        return ""
    command_path = Path(command_text)
    if command_path.exists():
        return str(command_path)
    return shutil.which(command_text) or ""


def probe_command_execution(command: str, arguments=None, timeout_sec: int = 5):
    resolved_command = resolve_command_path(command)
    result = {
        "command": str(command or "").strip(),
        "path": resolved_command,
        "available": bool(resolved_command),
        "executable": False,
        "returncode": None,
        "error": "",
        "stdout_preview": "",
        "stderr_preview": "",
    }
    if not resolved_command:
        result["error"] = "command_not_found"
        return result
    command_line = [resolved_command] + [str(item) for item in (arguments or [])]
    try:
        completed = subprocess.run(
            command_line,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
    except PermissionError as exc:
        result["error"] = f"permission_denied: {exc}"
        return result
    except subprocess.TimeoutExpired as exc:
        result["error"] = f"timeout: {exc}"
        return result
    except OSError as exc:
        result["error"] = f"os_error: {exc}"
        return result

    result["returncode"] = completed.returncode
    result["executable"] = completed.returncode == 0
    result["stdout_preview"] = str(completed.stdout or "").strip()[:200]
    result["stderr_preview"] = str(completed.stderr or "").strip()[:200]
    if completed.returncode != 0:
        result["error"] = result["stderr_preview"] or result["stdout_preview"] or f"returncode={completed.returncode}"
    return result


def probe_runtime_write_access():
    probe_path = None
    try:
        RUNTIME_WORK_ROOT.mkdir(parents=True, exist_ok=True)
        probe_path = RUNTIME_WORK_ROOT / f"first-run-write-{uuid4().hex[:8]}.probe"
        probe_path.write_text("ok", encoding="utf-8")
        ok = probe_path.read_text(encoding="utf-8") == "ok"
        probe_path.unlink(missing_ok=True)
        return {
            "ok": ok,
            "path": str(RUNTIME_WORK_ROOT),
            "error": "" if ok else "readback_mismatch",
        }
    except OSError as exc:
        if probe_path:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                pass
        return {
            "ok": False,
            "path": str(RUNTIME_WORK_ROOT),
            "error": str(exc),
        }


def build_runtime_preflight_layers(
    *,
    automatic_backend: str,
    powershell_command: str,
    node_command: str,
    installed_browsers: list[dict],
):
    normalized_backend = normalize_automatic_backend(automatic_backend) or "isolated_browser"
    os_supported = sys.platform.startswith("win")
    powershell_probe = probe_command_execution(
        powershell_command,
        ["-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"],
    )
    node_required = normalized_backend == "isolated_browser"
    node_probe = probe_command_execution(node_command, ["--version"]) if node_command else {
        "available": False,
        "executable": False,
        "path": "",
        "error": "command_not_found",
    }
    runtime_write = probe_runtime_write_access()
    rg_probe = probe_command_execution("rg", ["--version"])
    rg_ok = (not rg_probe.get("available")) or bool(rg_probe.get("executable"))

    layers = [
        build_preflight_layer(
            "platform",
            os_supported,
            blocked_reason="" if os_supported else "unsupported_platform",
            recoverability="" if os_supported else "recoverable_environment_block",
            recommended_action="" if os_supported else "use_windows_desktop_or_manual_mode",
            user_message="" if os_supported else "当前自动模式只支持 Windows 桌面环境；这台电脑请改用手动模式，或换到 Windows 电脑再继续。",
            details={"platform": sys.platform},
        ),
        build_preflight_layer(
            "powershell_runtime",
            bool(powershell_probe.get("executable")),
            blocked_reason="" if powershell_probe.get("executable") else "powershell_runtime_missing",
            recoverability="" if powershell_probe.get("executable") else "recoverable_environment_block",
            recommended_action="" if powershell_probe.get("executable") else "install_or_fix_powershell_runtime",
            user_message="" if powershell_probe.get("executable") else "当前没有检测到可执行的 PowerShell；自动模式启动前需要先安装或修复 PowerShell。",
            details=powershell_probe,
        ),
        build_preflight_layer(
            "node_runtime",
            (not node_required) or bool(node_probe.get("executable")),
            required=node_required,
            blocked_reason="" if ((not node_required) or node_probe.get("executable")) else "node_runtime_missing",
            recoverability="" if ((not node_required) or node_probe.get("executable")) else "recoverable_environment_block",
            recommended_action="" if ((not node_required) or node_probe.get("executable")) else "install_or_fix_node_runtime",
            user_message="" if ((not node_required) or node_probe.get("executable")) else "当前没有检测到可执行的 Node.js；后台自动模式启动前需要先安装或修复 Node.js。",
            details=node_probe,
        ),
        build_preflight_layer(
            "runtime_write",
            bool(runtime_write.get("ok")),
            blocked_reason="" if runtime_write.get("ok") else "runtime_write_unavailable",
            recoverability="" if runtime_write.get("ok") else "recoverable_permission_block",
            recommended_action="" if runtime_write.get("ok") else "enable_full_access_or_fix_runtime_directory",
            user_message="" if runtime_write.get("ok") else "当前运行目录不可写；自动模式需要 Codex 具备完全访问权限，或需要换到可写目录后再继续。",
            details=runtime_write,
        ),
        build_preflight_layer(
            "browser_inventory",
            (normalized_backend != "isolated_browser") or bool(installed_browsers),
            required=normalized_backend == "isolated_browser",
            blocked_reason="" if ((normalized_backend != "isolated_browser") or installed_browsers) else "no_supported_browser_found",
            recoverability="" if ((normalized_backend != "isolated_browser") or installed_browsers) else "recoverable_environment_block",
            recommended_action="" if ((normalized_backend != "isolated_browser") or installed_browsers) else "install_supported_browser",
            user_message="" if ((normalized_backend != "isolated_browser") or installed_browsers) else "当前没有检测到受支持的 Chromium 浏览器；建议先安装 Edge。",
            details={
                "backend": normalized_backend,
                "supported_browser_names": [browser["name"] for browser in installed_browsers],
                "installed_browsers": installed_browsers,
            },
        ),
        build_preflight_layer(
            "optional_tooling",
            rg_ok,
            required=False,
            blocked_reason="" if rg_ok else "rg_execution_blocked",
            recoverability="" if rg_ok else "recoverable_tooling_block",
            recommended_action="" if rg_ok else "use_powershell_fallback_or_fix_rg_path",
            user_message="" if rg_ok else "文件搜索工具 rg 被系统拦截；首测应改用 PowerShell 或内置读取兜底，不影响 Midjourney 自动生图链路。",
            details={"rg": rg_probe},
        ),
    ]
    return layers


def summarize_preflight_layers(layers):
    required_blocks = [layer for layer in layers if layer.get("required") and not layer.get("ok")]
    nonfatal_warnings = [layer for layer in layers if not layer.get("required") and not layer.get("ok")]
    return {
        "preflight_layers": layers,
        "required_preflight_blocks": required_blocks,
        "nonfatal_preflight_warnings": nonfatal_warnings,
        "first_required_preflight_block": required_blocks[0] if required_blocks else {},
        "can_run_minimal_first_test": not required_blocks,
    }


DEPENDENCY_REPAIR_CATALOG = {
    "powershell_runtime_missing": {
        "display_name": "PowerShell 7",
        "packages": {
            "winget": ["install", "--id", "Microsoft.PowerShell", "--exact", "--silent", "--accept-package-agreements", "--accept-source-agreements"],
            "choco": ["install", "powershell-core", "-y"],
            "scoop": ["install", "pwsh"],
        },
    },
    "node_runtime_missing": {
        "display_name": "Node.js LTS",
        "packages": {
            "winget": ["install", "--id", "OpenJS.NodeJS.LTS", "--exact", "--silent", "--accept-package-agreements", "--accept-source-agreements"],
            "choco": ["install", "nodejs-lts", "-y"],
            "scoop": ["install", "nodejs-lts"],
        },
    },
    "no_supported_browser_found": {
        "display_name": "Microsoft Edge",
        "packages": {
            "winget": ["install", "--id", "Microsoft.Edge", "--exact", "--silent", "--accept-package-agreements", "--accept-source-agreements"],
            "choco": ["install", "microsoft-edge", "-y"],
        },
    },
}


def detect_dependency_repair_managers():
    managers = []
    for manager_name in ["winget", "choco", "scoop"]:
        manager_path = shutil.which(manager_name) or ""
        if manager_path:
            managers.append({"name": manager_name, "path": manager_path})
    return managers


def build_dependency_repair_plan(environment_check: dict, available_managers=None):
    managers = list(available_managers) if available_managers is not None else detect_dependency_repair_managers()
    manager_names = [str(manager.get("name") or "").strip() for manager in managers]
    actions = []
    for layer in environment_check.get("required_preflight_blocks") or []:
        blocked_reason = str(layer.get("blocked_reason") or "").strip()
        catalog_item = DEPENDENCY_REPAIR_CATALOG.get(blocked_reason)
        action = {
            "layer": str(layer.get("name") or "").strip(),
            "blocked_reason": blocked_reason,
            "display_name": "",
            "repairable": False,
            "selected_manager": "",
            "command": [],
            "needs_user_confirmation": True,
            "no_repair_reason": "",
        }
        if not catalog_item:
            action["no_repair_reason"] = "not_a_supported_dependency_repair"
            actions.append(action)
            continue
        action["display_name"] = str(catalog_item.get("display_name") or "").strip()
        package_commands = catalog_item.get("packages") or {}
        for manager_name in manager_names:
            if manager_name in package_commands:
                action["repairable"] = True
                action["selected_manager"] = manager_name
                action["command"] = [manager_name] + [str(item) for item in package_commands[manager_name]]
                break
        if not action["repairable"]:
            action["no_repair_reason"] = "no_supported_package_manager_available"
        actions.append(action)
    repairable_actions = [action for action in actions if action.get("repairable")]
    return {
        "available_managers": managers,
        "actions": actions,
        "repairable_actions": repairable_actions,
        "unrepairable_actions": [action for action in actions if not action.get("repairable")],
        "can_attempt_repair": bool(repairable_actions),
        "requires_explicit_user_authorization": True,
    }


def execute_dependency_repair_plan(plan: dict, *, dry_run: bool = False, timeout_sec: int = 900):
    outcomes = []
    for action in plan.get("actions") or []:
        command = [str(item) for item in (action.get("command") or [])]
        outcome = {
            "blocked_reason": str(action.get("blocked_reason") or "").strip(),
            "display_name": str(action.get("display_name") or "").strip(),
            "selected_manager": str(action.get("selected_manager") or "").strip(),
            "command": command,
            "attempted": False,
            "ok": False,
            "skipped": False,
            "dry_run": bool(dry_run),
            "returncode": None,
            "stdout_preview": "",
            "stderr_preview": "",
            "error": "",
        }
        if not action.get("repairable"):
            outcome["skipped"] = True
            outcome["error"] = str(action.get("no_repair_reason") or "not_repairable")
            outcomes.append(outcome)
            continue
        if dry_run:
            outcome["skipped"] = True
            outcome["ok"] = True
            outcomes.append(outcome)
            continue
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
            )
        except PermissionError as exc:
            outcome["attempted"] = True
            outcome["error"] = f"permission_denied: {exc}"
            outcomes.append(outcome)
            continue
        except subprocess.TimeoutExpired as exc:
            outcome["attempted"] = True
            outcome["error"] = f"timeout: {exc}"
            outcomes.append(outcome)
            continue
        except OSError as exc:
            outcome["attempted"] = True
            outcome["error"] = f"os_error: {exc}"
            outcomes.append(outcome)
            continue
        outcome["attempted"] = True
        outcome["returncode"] = completed.returncode
        outcome["ok"] = completed.returncode == 0
        outcome["stdout_preview"] = str(completed.stdout or "").strip()[:500]
        outcome["stderr_preview"] = str(completed.stderr or "").strip()[:500]
        if completed.returncode != 0:
            outcome["error"] = outcome["stderr_preview"] or outcome["stdout_preview"] or f"returncode={completed.returncode}"
        outcomes.append(outcome)
    attempted_outcomes = [outcome for outcome in outcomes if outcome.get("attempted")]
    return {
        "requested": True,
        "dry_run": bool(dry_run),
        "attempted": bool(attempted_outcomes),
        "outcomes": outcomes,
        "ok": all(outcome.get("ok") for outcome in outcomes if not outcome.get("skipped")) if outcomes else True,
    }


def detect_runtime_environment(automatic_backend: str = "isolated_browser"):
    powershell_command = get_powershell_command()
    node_command = get_node_command()
    installed_browsers = detect_supported_browser_installations()
    preflight_layers = build_runtime_preflight_layers(
        automatic_backend=automatic_backend,
        powershell_command=powershell_command,
        node_command=node_command,
        installed_browsers=installed_browsers,
    )
    preflight_summary = summarize_preflight_layers(preflight_layers)
    return {
        "platform": sys.platform,
        "os_supported": sys.platform.startswith("win"),
        "powershell_available": bool(powershell_command),
        "powershell_command": powershell_command,
        "node_available": bool(node_command),
        "node_command": node_command,
        "supported_browser_found": bool(installed_browsers),
        "installed_browsers": installed_browsers,
        "supported_browser_names": [browser["name"] for browser in installed_browsers],
        **preflight_summary,
    }


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def managed_runtime_paths(prefix: str):
    safe_prefix = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(prefix or "runtime").strip()).strip("-") or "runtime"
    runtime_root = None
    try:
        RUNTIME_WORK_ROOT.mkdir(parents=True, exist_ok=True)
        probe_path = RUNTIME_WORK_ROOT / f"{safe_prefix}-{uuid4().hex[:8]}.probe"
        probe_path.write_text("", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
        runtime_root = RUNTIME_WORK_ROOT
    except OSError:
        runtime_root = Path(tempfile.gettempdir())
    token = f"{safe_prefix}-{uuid4().hex[:12]}"
    created_paths = []

    def build_path(name: str) -> Path:
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(name or "runtime.json").strip()).strip("-") or "runtime.json"
        path = runtime_root / f"{token}-{safe_name}"
        created_paths.append(path)
        return path

    try:
        yield build_path
    finally:
        for path in reversed(created_paths):
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, content: str) -> None:
    ensure_parent(path)
    path.write_text(content, encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jsonl_records(path: Path):
    content = read_text(path, default="")
    records = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = read_json_input(line)
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def read_json_file(path: Path, default=None):
    content = read_text(path, default="")
    if not content.strip():
        return default
    parsed = read_json_input(content)
    return parsed if parsed is not None else default


def write_json_file(path: Path, payload) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_json_input(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def load_prompt_terminology(path: Path = PROMPT_TERMINOLOGY_PATH):
    global _PROMPT_TERMINOLOGY_CACHE
    if _PROMPT_TERMINOLOGY_CACHE is not None and path == PROMPT_TERMINOLOGY_PATH:
        return _PROMPT_TERMINOLOGY_CACHE

    payload = read_json_file(path, default={})
    if not isinstance(payload, dict):
        payload = {}
    phrases = payload.get("phrases")
    if not isinstance(phrases, dict):
        phrases = {}
    terminology = {
        "version": str(payload.get("version") or "").strip(),
        "phrases": {
            str(source).strip(): str(target).strip()
            for source, target in phrases.items()
            if str(source).strip() and str(target).strip()
        },
    }
    if path == PROMPT_TERMINOLOGY_PATH:
        _PROMPT_TERMINOLOGY_CACHE = terminology
    return terminology


def unique_preserve_order(items):
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def normalize_string_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return unique_preserve_order(
            [str(item).strip() for item in value if str(item).strip()]
        )
    if isinstance(value, str):
        parts = re.split(r"[\n,，;；]+", value)
        return unique_preserve_order([part.strip() for part in parts if part.strip()])
    return []


def append_unique_list(values, value):
    items = normalize_string_list(values)
    normalized = str(value or "").strip()
    if normalized and normalized not in items:
        items.append(normalized)
    return items


def empty_subject_contract():
    return {
        "subject_type": "",
        "gender": "",
        "count": "",
        "age_band": "",
        "role_labels": [],
        "view": "",
        "framing": "",
        "pose": "",
        "identity_terms": [],
        "negative_constraints": [],
    }


def normalize_subject_contract(value):
    contract = empty_subject_contract()
    if isinstance(value, dict):
        contract.update(value)
    contract["subject_type"] = str(contract.get("subject_type") or "").strip().lower()
    contract["gender"] = str(contract.get("gender") or "").strip().lower()
    contract["count"] = str(contract.get("count") or "").strip().lower()
    contract["age_band"] = str(contract.get("age_band") or "").strip().lower()
    contract["view"] = str(contract.get("view") or "").strip().lower()
    contract["framing"] = str(contract.get("framing") or "").strip().lower()
    contract["pose"] = str(contract.get("pose") or "").strip().lower()
    contract["role_labels"] = normalize_string_list(contract.get("role_labels"))
    contract["identity_terms"] = normalize_string_list(contract.get("identity_terms"))
    contract["negative_constraints"] = normalize_string_list(contract.get("negative_constraints"))
    return contract


def merge_subject_contract(base_contract, override_contract):
    merged = normalize_subject_contract(base_contract)
    override = normalize_subject_contract(override_contract)
    for field in ["subject_type", "gender", "count", "age_band", "view", "framing", "pose"]:
        if override.get(field):
            merged[field] = override[field]
    for field in ["role_labels", "identity_terms", "negative_constraints"]:
        merged[field] = unique_preserve_order(
            normalize_string_list(merged.get(field)) + normalize_string_list(override.get(field))
        )
    return merged


def _text_contains_any(text: str, keywords) -> bool:
    lowered = str(text or "").lower()
    for keyword in keywords:
        token = str(keyword or "").strip().lower()
        if not token:
            continue
        if re.search(r"[\u4e00-\u9fff]", token):
            if token in lowered:
                return True
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered):
            return True
    return False


def infer_subject_contract(raw_request: str = "", brief=None, existing_contract=None):
    base_contract = normalize_subject_contract(existing_contract)
    brief_payload = brief if isinstance(brief, dict) else {}
    parts = [
        raw_request,
        brief_payload.get("goal"),
        " ".join(normalize_string_list(brief_payload.get("must_have"))),
        " ".join(normalize_string_list(brief_payload.get("must_not_have"))),
        " ".join(normalize_string_list(brief_payload.get("style_bias"))),
    ]
    source_text = " ".join(str(part or "").strip() for part in parts if str(part or "").strip())
    lowered = source_text.lower()
    inferred = empty_subject_contract()

    if _text_contains_any(lowered, CHARACTER_SUBJECT_KEYWORDS):
        inferred["subject_type"] = "character"
    elif _text_contains_any(lowered, PRODUCT_SUBJECT_KEYWORDS):
        inferred["subject_type"] = "product"
    elif _text_contains_any(lowered, SCENE_SUBJECT_KEYWORDS):
        inferred["subject_type"] = "scene"

    if _text_contains_any(lowered, GAME_CHARACTER_ROLE_KEYWORDS):
        inferred["role_labels"] = append_unique_list(inferred.get("role_labels"), "game character")
    if _text_contains_any(lowered, MODERN_IDENTITY_KEYWORDS):
        inferred["identity_terms"] = append_unique_list(inferred.get("identity_terms"), "modern")

    no_women = _text_contains_any(lowered, NO_WOMEN_CONSTRAINT_KEYWORDS)
    no_men = _text_contains_any(lowered, NO_MEN_CONSTRAINT_KEYWORDS)
    no_group = _text_contains_any(lowered, NO_GROUP_CONSTRAINT_KEYWORDS)

    has_male = _text_contains_any(lowered, MALE_SUBJECT_KEYWORDS)
    has_female = _text_contains_any(lowered, FEMALE_SUBJECT_KEYWORDS)
    if has_male and not has_female:
        inferred["gender"] = "male"
    elif has_female and not no_women and not has_male:
        inferred["gender"] = "female"

    if _text_contains_any(lowered, SINGLE_SUBJECT_KEYWORDS):
        inferred["count"] = "single"
    elif _text_contains_any(lowered, GROUP_SUBJECT_KEYWORDS):
        inferred["count"] = "group"

    if _text_contains_any(lowered, YOUTH_SUBJECT_KEYWORDS):
        inferred["age_band"] = "youth"
    elif _text_contains_any(lowered, ADULT_SUBJECT_KEYWORDS):
        inferred["age_band"] = "adult"
    if _text_contains_any(lowered, FRONT_VIEW_KEYWORDS):
        inferred["view"] = "front"
    if _text_contains_any(lowered, FULL_BODY_KEYWORDS):
        inferred["framing"] = "full_body"
    elif _text_contains_any(lowered, HALF_BODY_KEYWORDS):
        inferred["framing"] = "half_body"
    if _text_contains_any(lowered, STANDING_POSE_KEYWORDS):
        inferred["pose"] = "standing"

    if no_women or inferred.get("gender") == "male":
        inferred["negative_constraints"] = append_unique_list(inferred.get("negative_constraints"), "no women")
    if no_men or inferred.get("gender") == "female":
        inferred["negative_constraints"] = append_unique_list(inferred.get("negative_constraints"), "no men")
    if no_group or inferred.get("count") == "single":
        inferred["negative_constraints"] = append_unique_list(inferred.get("negative_constraints"), "no group")

    return merge_subject_contract(base_contract, inferred)


def subject_contract_to_brief_constraints(contract):
    normalized = normalize_subject_contract(contract)
    must_have = []
    must_not_have = []
    if "game character" in [item.lower() for item in normalized.get("role_labels")]:
        must_have = append_unique_list(must_have, "game character")
    if normalized.get("gender") == "male":
        must_have = append_unique_list(must_have, "male character")
    elif normalized.get("gender") == "female":
        must_have = append_unique_list(must_have, "female character")
    if normalized.get("count") == "single":
        must_have = append_unique_list(must_have, "single character")
    elif normalized.get("count") == "group":
        must_have = append_unique_list(must_have, "group characters")
    if normalized.get("view") == "front" and normalized.get("framing") == "full_body" and normalized.get("pose") == "standing":
        must_have = append_unique_list(must_have, "front-facing full-body standing pose")
    elif normalized.get("view") == "front":
        must_have = append_unique_list(must_have, "front view")

    for constraint in normalized.get("negative_constraints"):
        lowered = constraint.lower()
        if lowered == "no women":
            must_not_have = append_unique_list(must_not_have, "women")
        elif lowered == "no men":
            must_not_have = append_unique_list(must_not_have, "men")
        elif lowered == "no group":
            must_not_have = append_unique_list(must_not_have, "group")
    return {
        "must_have": must_have,
        "must_not_have": must_not_have,
    }


def build_subject_prompt_segments(contract):
    normalized = normalize_subject_contract(contract)
    if not any(normalized.values()):
        return []

    segments = []
    role_labels = [item.lower() for item in normalized.get("role_labels")]
    base_noun_map = {
        "character": "character",
        "product": "product",
        "scene": "scene concept",
    }
    base_noun = "game character" if "game character" in role_labels else base_noun_map.get(
        normalized.get("subject_type"),
        "",
    )
    descriptors = []
    if "modern" in [item.lower() for item in normalized.get("identity_terms")]:
        descriptors.append("modern")
    if normalized.get("count") == "single":
        descriptors.append("single")
    elif normalized.get("count") == "group":
        descriptors.append("group")
    if normalized.get("age_band") == "adult":
        descriptors.append("adult")
    elif normalized.get("age_band") == "youth":
        descriptors.append("young")
    if normalized.get("gender") in {"male", "female"}:
        descriptors.append(normalized["gender"])
    if base_noun:
        segments.append(" ".join(descriptors + [base_noun]).strip())
    elif descriptors:
        segments.append(" ".join(descriptors).strip())

    if (
        normalized.get("gender") == "male"
        and normalized.get("count") == "single"
        and normalized.get("age_band") == "adult"
    ):
        segments.append("one adult man only")
    elif (
        normalized.get("gender") == "female"
        and normalized.get("count") == "single"
        and normalized.get("age_band") == "adult"
    ):
        segments.append("one adult woman only")
    elif normalized.get("count") == "single":
        segments.append("one clear subject only")

    view_parts = []
    if normalized.get("view") == "front":
        view_parts.append("front-facing")
    if normalized.get("framing") == "full_body":
        view_parts.append("full-body")
    elif normalized.get("framing") == "half_body":
        view_parts.append("half-body")
    if normalized.get("pose") == "standing":
        view_parts.append("standing pose")
    if view_parts:
        segments.append(" ".join(view_parts).strip())

    for constraint in normalized.get("negative_constraints"):
        lowered = constraint.lower()
        if lowered == "no women":
            segments.append("no women")
        elif lowered == "no men":
            segments.append("no men")
        elif lowered == "no group":
            segments.append("no group")
    return unique_preserve_order([segment for segment in segments if str(segment or "").strip()])


def extract_keywords(values):
    joined = " ".join(str(value) for value in values if value)
    raw = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]{3,}", joined)
    return unique_preserve_order([token.lower() for token in raw])


def score_text(text: str, keywords):
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword in lowered)


def empty_profile():
    return {
        "industry": "",
        "work_types": [],
        "style_preferences": [],
        "content_preferences": [],
        "taboos": [],
        "quality_tendency": "",
        "updated_at": "",
    }


def load_profile(path: Path = PROFILE_PATH):
    content = read_text(path, default="")
    structured = empty_profile()
    notes = []
    if not content.strip():
        return structured, notes

    match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.S)
    if match:
        parsed = read_json_input(match.group(1))
        if isinstance(parsed, dict):
            merged = empty_profile()
            merged.update(parsed)
            merged["work_types"] = normalize_string_list(merged.get("work_types"))
            merged["style_preferences"] = normalize_string_list(
                merged.get("style_preferences")
            )
            merged["content_preferences"] = normalize_string_list(
                merged.get("content_preferences")
            )
            merged["taboos"] = normalize_string_list(merged.get("taboos"))
            structured = merged

    notes_section = False
    for line in content.splitlines():
        if line.strip() == "## 非结构化备注":
            notes_section = True
            continue
        if not notes_section:
            continue
        if line.startswith("- "):
            note = line[2:].strip()
            if note:
                notes.append(note)
    return structured, notes


def render_profile(structured: dict, notes) -> str:
    normalized = empty_profile()
    normalized.update(structured)
    normalized["work_types"] = normalize_string_list(normalized.get("work_types"))
    normalized["style_preferences"] = normalize_string_list(
        normalized.get("style_preferences")
    )
    normalized["content_preferences"] = normalize_string_list(
        normalized.get("content_preferences")
    )
    normalized["taboos"] = normalize_string_list(normalized.get("taboos"))
    normalized["updated_at"] = normalized.get("updated_at") or now_iso()
    lines = [
        "# 用户画像",
        "",
        "## 结构化画像",
        "",
        "```json",
        json.dumps(normalized, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 非结构化备注",
        "",
    ]
    for note in unique_preserve_order([str(item).strip() for item in notes if str(item).strip()]):
        lines.append(f"- {note}")
    if lines[-1] == "":
        lines.append("- ")
    return "\n".join(lines) + "\n"


def project_memory_path(project_id: str) -> Path:
    return MEMORY_ROOT / "projects" / f"{project_id}.md"


def normalize_mode_label(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    collapsed = re.sub(r"\s+", " ", raw)
    if collapsed in {
        "auto",
        "auto mode",
        "automatic",
        "automatic mode",
        "\u81ea\u52a8",
        "\u81ea\u52a8\u6a21\u5f0f",
    }:
        return "automatic"
    if collapsed in {
        "manual",
        "manual mode",
        "\u624b\u52a8",
        "\u624b\u52a8\u6a21\u5f0f",
    }:
        return "manual"
    raw = collapsed
    if raw in {"auto", "automatic", "自动", "自动模式"}:
        return "automatic"
    if raw in {"manual", "手动", "手动模式"}:
        return "manual"
    return raw


def normalize_automatic_backend(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    collapsed = re.sub(r"\s+", " ", raw)
    if collapsed in {
        "isolated_browser",
        "background",
        "background_mode",
        "background mode",
        "\u540e\u53f0",
        "\u540e\u53f0\u6a21\u5f0f",
        "\u540e\u53f0\u81ea\u52a8",
        "\u540e\u53f0\u81ea\u52a8\u6a21\u5f0f",
    }:
        return "isolated_browser"
    if collapsed in {
        "window_uia",
        "foreground",
        "foreground_mode",
        "foreground mode",
        "\u524d\u53f0",
        "\u524d\u53f0\u6a21\u5f0f",
        "\u524d\u53f0\u81ea\u52a8",
        "\u524d\u53f0\u81ea\u52a8\u6a21\u5f0f",
    }:
        return "window_uia"
    raw = collapsed
    if raw in {
        "isolated_browser",
        "background",
        "background_mode",
        "后台",
        "后台模式",
        "后台自动",
        "后台自动模式",
    }:
        return "isolated_browser"
    if raw in {
        "window_uia",
        "foreground",
        "foreground_mode",
        "前台",
        "前台模式",
        "前台自动",
        "前台自动模式",
    }:
        return "window_uia"
    return raw


def slugify_project_id(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    return text


def new_task_id(prefix: str = "mj-task") -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{uuid4().hex[:6]}"


def normalize_prompt_policy(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {
        "",
        "english_only",
        "english",
        "en",
        "英文",
        "英文prompt",
        "英文提示词",
        "只允许英文",
        "只允许英文prompt",
        "不要中文prompt",
    }:
        return PROMPT_POLICY_ENGLISH_ONLY
    return raw


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def is_english_prompt_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if has_cjk(value):
        return False
    return bool(re.search(r"[A-Za-z]", value))


def normalize_prompt_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("\u3000", " ")
    value = value.replace("，", ", ")
    value = value.replace("。", ". ")
    value = value.replace("；", "; ")
    value = value.replace("：", ": ")
    value = value.replace("、", ", ")
    value = value.replace("（", " ")
    value = value.replace("）", " ")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*([,;.])\s*", r"\1 ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,;:.")


def validate_execution_prompt(text: str):
    normalized = normalize_prompt_text(text)
    issues = []

    if not normalized:
        issues.append("prompt 为空")
    if has_cjk(normalized):
        issues.append("prompt 含中文")
    if normalized and not re.search(r"[A-Za-z]", normalized):
        issues.append("prompt 不包含有效英文描述")

    lowered = normalized.lower()
    for marker in EXECUTION_PROMPT_META_MARKERS:
        if marker in lowered:
            issues.append(f"prompt 含内部控制语：{marker}")
    for marker in EXECUTION_PROMPT_SELECTION_MARKERS:
        if marker in lowered:
            issues.append(f"prompt 含内部交付目标：{marker}")
    for pattern, message in EXECUTION_PROMPT_REQUEST_PATTERNS:
        if pattern.search(normalized):
            issues.append(message)

    return {
        "ok": not issues,
        "issues": unique_preserve_order(issues),
        "normalized_prompt": normalized,
    }


def diagnosis_blocks_success(payload: dict) -> bool:
    diagnosis = payload.get("diagnosis_report") if isinstance(payload.get("diagnosis_report"), dict) else {}
    observed_issues = normalize_string_list(diagnosis.get("observed_issues"))
    if not observed_issues:
        return False
    return any(issue in HARD_DIAGNOSIS_ISSUES for issue in observed_issues)


def infer_run_verdict(payload: dict) -> str:
    existing = str(payload.get("run_verdict") or "").strip()
    if existing in ALLOWED_VERDICTS:
        return existing
    if payload.get("blocked_by_ui"):
        return "blocked_by_ui"
    if payload.get("blocked_by_context"):
        return "blocked_by_context"
    if payload.get("stopped_by_user"):
        return "stopped_by_user"
    if payload.get("stopped_by_budget"):
        return "stopped_by_budget"
    if payload.get("result_available") and diagnosis_blocks_success(payload):
        return "usable_but_iterate"
    if payload.get("result_available") and payload.get("should_continue"):
        return "usable_but_iterate"
    if payload.get("result_available"):
        return "success"
    return "blocked_by_context"


def build_backend_health_snapshot(task: dict):
    backend = normalize_automatic_backend(task.get("automatic_execution_backend")) or "isolated_browser"
    snapshot = {
        "backend": backend,
        "checked_at": now_iso(),
    }
    if backend == "isolated_browser":
        state_payload = read_json_file(ISOLATED_BROWSER_STATE_PATH, default={})
        if not isinstance(state_payload, dict):
            state_payload = {}
        profile_dir_value = str(state_payload.get("profile_dir") or "").strip()
        profile_dir_path = Path(profile_dir_value) if profile_dir_value else ISOLATED_BROWSER_PROFILE_DIR
        snapshot.update(
            {
                "profile_dir": str(profile_dir_path),
                "profile_dir_exists": profile_dir_path.exists(),
                "runtime_state_path": str(ISOLATED_BROWSER_STATE_PATH),
                "runtime_state_exists": ISOLATED_BROWSER_STATE_PATH.exists(),
                "last_seen_at": str(state_payload.get("last_seen_at") or "").strip(),
                "browser_key": str(state_payload.get("browser_key") or "").strip(),
                "browser_name": str(state_payload.get("browser_name") or "").strip(),
                "browser_path": str(state_payload.get("browser_path") or "").strip(),
                "web_socket_url_present": bool(str(state_payload.get("web_socket_debugger_url") or "").strip()),
                "page_url": str(state_payload.get("page_url") or "").strip(),
            }
        )
        return snapshot

    ui_state = task.get("ui_state") if isinstance(task.get("ui_state"), dict) else {}
    snapshot.update(
        {
            "window_handle": str(ui_state.get("window_handle") or "").strip(),
            "window_handle_known": bool(str(ui_state.get("window_handle") or "").strip()),
        }
    )
    return snapshot


def classify_execution_governance(auto_result: dict, backend: str):
    normalized_backend = normalize_automatic_backend(backend) or "isolated_browser"
    blocked_reason = str(auto_result.get("blocked_reason") or "").strip()

    if auto_result.get("ok") and auto_result.get("result_available") and auto_result.get("completed"):
        return {
            "backend": normalized_backend,
            "status": "completed",
            "recoverability": "none",
            "verdict_hint": "success",
            "recommended_action": "finish_task",
            "message": "本轮执行器返回已完成结果。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason == "english_prompt_required":
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "unrecoverable_context_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "fix_prompt_policy",
            "message": "当前 prompt 不符合英文唯一出口规则，已阻断执行。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason == "no_supported_browser_found":
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_environment_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "install_supported_browser",
            "message": "当前机器没有可用的后台浏览器，建议先安装 Edge 再继续后台首次测试或后台自动生成。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason == "unsupported_platform":
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_environment_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "use_windows_desktop",
            "message": "当前自动模式只支持 Windows 桌面环境，请改在 Windows 电脑上使用自动模式，或改走手动模式。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason == "node_runtime_missing":
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_environment_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "install_node_runtime",
            "message": "当前机器缺少 Node.js，后台自动模式无法启动，请先安装 Node.js 再继续。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason == "powershell_runtime_missing":
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_environment_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "install_powershell_runtime",
            "message": "当前机器缺少可用的 PowerShell，自动模式无法启动，请先安装 PowerShell 再继续。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason == "automatic_backend_runtime_error":
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_environment_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "inspect_environment_runtime",
            "message": "自动执行环境异常，当前机器需要先补齐本地运行环境后再继续。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason == "automatic_parent_timeout":
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_executor_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "stop_after_budget",
            "message": "本轮自动执行达到外层时间上限，已停止继续等待。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason == "runtime_write_unavailable":
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_permission_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "enable_full_access_or_fix_runtime_directory",
            "message": "当前运行目录不可写，自动模式需要先启用完全访问权限或修复运行目录权限。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason == "rg_execution_blocked":
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_tooling_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "use_powershell_fallback_or_fix_rg_path",
            "message": "辅助搜索工具被系统拦截，可改用 PowerShell 或内置读取兜底；这不应阻断 Midjourney 自动生图链路。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason in {"needs_isolated_browser_login", "isolated_browser_challenge_page"}:
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_session_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "restore_backend_session",
            "message": "执行器会话不可用，需要恢复独立浏览器登录态后再继续。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason in {
        "isolated_browser_input_not_ready",
        "midjourney_window_not_found",
        "window_gate_blocked",
        "window_not_visible",
        "window_minimized",
        "user_manual_restore",
        "prompt_region_not_found",
        "prompt_region_unconfirmed",
    }:
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_ui_block",
            "verdict_hint": "blocked_by_ui",
            "recommended_action": "resolve_ui_block",
            "message": "执行器被界面状态阻断，需要先恢复页面或结果区域可识别状态。",
            "blocked_reason": blocked_reason,
        }

    if blocked_reason:
        return {
            "backend": normalized_backend,
            "status": "blocked",
            "recoverability": "recoverable_executor_block",
            "verdict_hint": "blocked_by_context",
            "recommended_action": "retry_backend_execution",
            "message": "执行器返回了未归档的阻断原因，需要按执行器健康状态继续排查。",
            "blocked_reason": blocked_reason,
        }

    return {
        "backend": normalized_backend,
        "status": "in_progress" if auto_result.get("generation_observed") else "unknown",
        "recoverability": "none",
        "verdict_hint": "",
        "recommended_action": "observe_generation" if auto_result.get("generation_observed") else "inspect_backend_state",
        "message": "执行器未返回明确阻断原因，保留当前状态继续观察。",
        "blocked_reason": "",
    }
