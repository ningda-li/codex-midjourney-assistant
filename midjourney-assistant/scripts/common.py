import json
import os
import re
import shutil
import sys
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
PROMPT_TERMINOLOGY_PATH = ASSET_ROOT / "prompt-terminology.json"

ALLOWED_VERDICTS = {
    "success",
    "usable_but_iterate",
    "blocked_by_ui",
    "blocked_by_context",
    "stopped_by_user",
    "stopped_by_budget",
}

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
    return shutil.which("powershell") or shutil.which("pwsh") or ""


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


def detect_runtime_environment():
    powershell_command = get_powershell_command()
    node_command = shutil.which("node") or ""
    installed_browsers = detect_supported_browser_installations()
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
    }


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


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
    if raw in {"auto", "automatic", "自动", "自动模式"}:
        return "automatic"
    if raw in {"manual", "手动", "手动模式"}:
        return "manual"
    return raw


def normalize_automatic_backend(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
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
