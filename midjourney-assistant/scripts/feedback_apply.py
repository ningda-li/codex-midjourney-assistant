import argparse
import json
import re
import sys
from pathlib import Path

from common import (
    PROMPT_POLICY_ENGLISH_ONLY,
    configure_stdout,
    infer_subject_contract,
    merge_subject_contract,
    normalize_string_list,
    normalize_subject_contract,
    now_iso,
    read_json_file,
    read_json_input,
    subject_contract_to_brief_constraints,
)


REVISION_MARKERS = [
    "改成",
    "换成",
    "调整",
    "保留",
    "继续",
    "再来",
    "优化",
    "修一下",
    " refine ",
    " tweak ",
]

COLORWAY_HINTS = [
    "配色",
    "颜色",
    "色板",
    "色系",
    "换几个配色",
    "换配色",
    "看看别的颜色",
    "配色难看",
    "colorway",
    "palette",
    "recolor",
]

NEW_DIRECTION_HINTS = [
    "重做",
    "重新设计",
    "重新来",
    "换个人",
    "换一个人",
    "新方向",
    "多看几个新方向",
    "重画",
    "new direction",
]

STRUCTURE_REFINE_HINTS = [
    "版型",
    "剪裁",
    "结构",
    "材质",
    "比例",
    "轮廓",
    "改成",
    "换成",
    "调整",
    "鏃跺皻",
    "娼祦",
    "鐢婚",
    "refine",
    "fix",
]

FINISH_ONLY_HINTS = [
    "定稿",
    "最终稿",
    "成品",
    "可交付",
    "精修",
    "高精",
    "production-ready",
    "final polish",
]

LOCK_HINTS = [
    "就按这个",
    "按这个换配色",
    "按这张来",
    "基于这张",
    "用这张做基底",
    "锁定基底",
    "固定这个",
    "固定这张",
    "保持这套设计",
    "保持这个设计",
    "别换人",
    "不要换人",
    "同一个角色",
    "same face",
    "same silhouette",
    "same outfit",
]

DEFAULT_COLORWAY_LOCKS = ["face", "hair", "silhouette", "garment_panels", "material_map"]
DEFAULT_STRUCTURE_LOCKS = ["face", "hair", "silhouette", "garment_panels"]

COLOR_SLOT_HINTS = {
    "top": ["上衣", "上装", "top", "shirt", "vest"],
    "bottom": ["下装", "裤", "裤子", "bottom", "trousers", "pants"],
    "hardware": ["五金", "金属", "硬件", "hardware", "metal"],
    "accent": ["点缀", "accent", "secondary", "highlight"],
}

COLOR_WORD_HINTS = [
    "白",
    "灰",
    "黑",
    "红",
    "蓝",
    "绿",
    "黄",
    "紫",
    "棕",
    "卡其",
    "米白",
    "冷白",
    "暖白",
    "石墨",
    "炭灰",
    "酒红",
    "海军蓝",
    "银",
    "金",
    "white",
    "gray",
    "grey",
    "black",
    "red",
    "blue",
    "green",
    "yellow",
    "purple",
    "brown",
    "khaki",
    "graphite",
    "charcoal",
    "oxblood",
    "navy",
    "silver",
    "gold",
]

PROJECT_SCOPE_HINTS = [
    "这个项目",
    "项目后面",
    "后面都",
    "以后都",
    "之后都",
    "统一",
    "默认保持",
]

GLOBAL_SCOPE_HINTS = [
    "所有任务",
    "以后默认",
    "全局",
    "以后都用",
    "一直只用",
]

ENGLISH_PROMPT_HINTS = [
    "英文prompt",
    "英文 prompt",
    "english prompt",
    "只允许英文",
    "只用英文",
    "only english",
]

FULL_BODY_HINTS = ["全身", "full-body", "full body"]
HALF_BODY_HINTS = ["半身", "half-body", "half body", "close-up", "close up"]
FRONT_HINTS = ["正面", "front-facing", "front facing", "front view"]
STANDING_HINTS = ["站姿", "站立", "standing pose", "standing"]
GAME_STYLE_HINTS = ["游戏设计风格", "游戏角色设计", "hero shooter", "game design style", "game character design"]
CLEAN_HINTS = ["干净", "clean", "cleaner"]
NEW_TASK_HINTS = [
    "新任务",
    "新需求",
    "另外做一张",
    "另外来一张",
    "重新开始一个新任务",
    "重新开始",
    "重开",
    "换个任务",
    "另一个任务",
    "换个项目",
    "另一个项目",
    "重新做一张新的",
    "重新生成一个新的",
]

NEW_TASK_REQUEST_PREFIXES = [
    "做一个",
    "做一张",
    "来一张",
    "画一个",
    "画一张",
    "生成一个",
    "生成一张",
    "create ",
    "make ",
    "generate ",
]

EXPLANATION_REQUEST_HINTS = [
    "为什么",
    "原因",
    "解释",
    "说清楚",
    "怎么回事",
    "what happened",
    "what went wrong",
    "why",
    "explain",
    "reason",
]

SPLIT_RE = re.compile(r"[，,。；;、\n]+")


def parse_args():
    parser = argparse.ArgumentParser(description="把 Midjourney 反馈归并成结构化任务补丁")
    parser.add_argument("--task-file", help="任务对象文件路径")
    parser.add_argument("--input-file", help="输入 JSON 文件路径")
    parser.add_argument("--message", help="反馈文本")
    parser.add_argument("--increment-round", action="store_true", help="是否在应用反馈后推进轮次")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def load_payload(args):
    payload = {}
    if args.task_file:
        task = read_json_file(Path(args.task_file), default={})
        if isinstance(task, dict):
            payload["task"] = task
    if args.input_file:
        direct = read_json_file(Path(args.input_file), default={})
        if isinstance(direct, dict):
            if "task" in direct and isinstance(direct.get("task"), dict):
                payload["task"] = direct.get("task")
            else:
                payload["task"] = direct
            if str(direct.get("message") or "").strip():
                payload["message"] = str(direct.get("message") or "").strip()
            if bool(direct.get("increment_round")):
                payload["increment_round"] = True
    elif not payload:
        raw = sys.stdin.read().strip()
        direct = read_json_input(raw)
        if isinstance(direct, dict):
            if "task" in direct and isinstance(direct.get("task"), dict):
                payload["task"] = direct.get("task")
            else:
                payload["task"] = direct
            if str(direct.get("message") or "").strip():
                payload["message"] = str(direct.get("message") or "").strip()
            if bool(direct.get("increment_round")):
                payload["increment_round"] = True
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    message = str(args.message or payload.get("message") or "").strip()
    increment_round = bool(args.increment_round or payload.get("increment_round"))
    if not task:
        raise ValueError("feedback_apply 输入里缺少任务对象")
    return task, message, increment_round


def normalize_text(text: str) -> str:
    return str(text or "").strip()


def lower_text(text: str) -> str:
    return normalize_text(text).lower()


def contains_any(text: str, keywords) -> bool:
    lowered = lower_text(text)
    return any(str(keyword).lower() in lowered for keyword in keywords if str(keyword).strip())


def split_message(message: str):
    return [segment.strip() for segment in SPLIT_RE.split(normalize_text(message)) if segment.strip()]


def dedupe_preserve_order(items):
    results = []
    seen = set()
    for item in items:
        value = normalize_text(item)
        if not value or value in seen:
            continue
        seen.add(value)
        results.append(value)
    return results


def append_unique(items, value):
    values = normalize_string_list(items)
    normalized = normalize_text(value)
    if normalized and normalized not in values:
        values.append(normalized)
    return values


def remove_matching(items, keywords):
    lowered_keywords = [str(keyword).lower() for keyword in keywords if str(keyword).strip()]
    results = []
    for item in normalize_string_list(items):
        lowered = item.lower()
        if any(keyword in lowered for keyword in lowered_keywords):
            continue
        results.append(item)
    return results


def get_project_context(task: dict):
    if isinstance(task.get("project_context_snapshot"), dict):
        return task.get("project_context_snapshot")
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    project_context = artifacts.get("project_context")
    return project_context if isinstance(project_context, dict) else {}


def get_latest_capture(task: dict) -> str:
    project_context = get_project_context(task)
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    for candidate in [
        task.get("accepted_base_reference"),
        project_context.get("accepted_base_reference"),
        artifacts.get("accepted_base_reference"),
    ]:
        value = normalize_text(candidate)
        if value:
            return value
    return ""


def get_latest_result_capture(task: dict) -> str:
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    for candidate in [
        artifacts.get("final_capture"),
        (artifacts.get("last_auto_result") or {}).get("final_capture") if isinstance(artifacts.get("last_auto_result"), dict) else "",
    ]:
        value = normalize_text(candidate)
        if value:
            return value
    return ""


def contains_explicit_revision_marker(message: str) -> bool:
    return contains_any(message, REVISION_MARKERS + COLORWAY_HINTS)


def has_explicit_base_acceptance(message: str) -> bool:
    return contains_any(message, LOCK_HINTS)


def build_source_text(task: dict, message: str = "") -> str:
    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    parts = [
        task.get("goal"),
        task.get("raw_request"),
        brief.get("goal"),
        " ".join(normalize_string_list(brief.get("must_have"))),
        " ".join(normalize_string_list(brief.get("style_bias"))),
        " ".join(normalize_string_list(brief.get("must_not_have"))),
        latest_feedback.get("raw_text"),
        message,
    ]
    return " ".join(normalize_text(part) for part in parts if normalize_text(part))


def starts_like_new_task_request(message: str) -> bool:
    lowered = lower_text(message)
    return any(lowered.startswith(token) for token in NEW_TASK_REQUEST_PREFIXES)


def looks_like_new_task_request(task: dict, message: str) -> bool:
    if not normalize_text(message):
        return False
    if contains_any(message, NEW_TASK_HINTS):
        return True
    if max(1, int(task.get("round_index") or 1)) > 1 and starts_like_new_task_request(message):
        return True
    if classify_feedback_intent(task, message):
        return False
    return False


def looks_like_explanation_request(message: str) -> bool:
    normalized = normalize_text(message)
    lowered = lower_text(message)
    if not normalized:
        return False
    if not contains_any(normalized, EXPLANATION_REQUEST_HINTS) and "?" not in normalized and "？" not in normalized:
        return False
    if contains_explicit_revision_marker(message):
        return False
    if re.search(r"\b(can you|could you|please)\b", lowered):
        return False
    return True


def classify_feedback_intent(task: dict, message: str) -> bool:
    if not normalize_text(message):
        return False
    if looks_like_explanation_request(message):
        return False
    text = build_source_text(task, message)
    if contains_any(text, COLORWAY_HINTS + STRUCTURE_REFINE_HINTS + FINISH_ONLY_HINTS):
        return True
    if contains_explicit_revision_marker(message):
        return True
    if contains_any(message, PROJECT_SCOPE_HINTS + GLOBAL_SCOPE_HINTS + GAME_STYLE_HINTS + CLEAN_HINTS + ENGLISH_PROMPT_HINTS):
        return True
    if max(1, int(task.get("round_index") or 1)) > 1:
        if contains_any(message, NEW_TASK_HINTS):
            return False
        if starts_like_new_task_request(message):
            return False
        return True
    return False


def detect_revision_mode_from_message(task: dict, message: str) -> str:
    project_context = get_project_context(task)
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    existing_mode = normalize_text(
        revision_patch.get("revision_mode")
        or task.get("requested_revision_mode")
        or task_model.get("revision_mode")
        or project_context.get("latest_revision_mode")
    )
    if contains_any(message, COLORWAY_HINTS):
        return "colorway_only"
    if contains_any(message, FINISH_ONLY_HINTS):
        return "finish_only"
    if contains_any(message, NEW_DIRECTION_HINTS):
        return "new_direction"
    if contains_any(message, STRUCTURE_REFINE_HINTS):
        return "structure_refine"
    if existing_mode:
        return existing_mode
    return "structure_refine"


def detect_change_axis(revision_mode: str) -> str:
    mapping = {
        "new_direction": "direction",
        "structure_refine": "structure",
        "colorway_only": "palette",
        "finish_only": "finish",
        "local_edit": "local",
    }
    return mapping.get(normalize_text(revision_mode), "structure")


def clean_segment_prefix(text: str) -> str:
    value = normalize_text(text)
    for prefix in [
        "这个项目后面都",
        "项目后面都",
        "后面都",
        "以后都",
        "之后都",
        "请",
        "麻烦",
        "帮我",
        "我想要",
        "我需要",
        "保持",
        "保留",
        "就按这个",
        "按这个",
    ]:
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
    return value


def extract_color_slot_values(message: str, keywords):
    values = []
    keyword_list = [str(keyword).lower() for keyword in keywords if str(keyword).strip()]
    for segment in split_message(message):
        lowered = segment.lower()
        if not any(keyword in lowered for keyword in keyword_list):
            continue
        cleaned = segment
        for keyword in sorted(keywords, key=len, reverse=True):
            if str(keyword).strip():
                cleaned = re.sub(re.escape(str(keyword)), " ", cleaned, flags=re.I)
        cleaned = re.sub(r"[：:\- ]+", " ", cleaned).strip()
        if cleaned:
            values.append(cleaned)
    return dedupe_preserve_order(values)


def build_palette_request(message: str):
    if not contains_any(message, COLORWAY_HINTS + COLOR_WORD_HINTS):
        return {}
    palette_request = {}
    for slot, keywords in COLOR_SLOT_HINTS.items():
        values = extract_color_slot_values(message, keywords)
        if values:
            palette_request[slot] = values
    summary_parts = []
    for segment in split_message(message):
        cleaned = clean_segment_prefix(segment)
        if contains_any(cleaned, COLORWAY_HINTS + COLOR_WORD_HINTS):
            summary_parts.append(cleaned)
    summary = "，".join(dedupe_preserve_order(summary_parts))[:120].strip("，")
    if summary:
        palette_request["summary"] = summary
    elif palette_request:
        palette_request["summary"] = "只改配色分配"
    return palette_request


def infer_scope(message: str) -> str:
    if contains_any(message, GLOBAL_SCOPE_HINTS):
        return "global"
    if contains_any(message, PROJECT_SCOPE_HINTS):
        return "project"
    return "round"


def build_feedback_points(message: str):
    points = []
    for segment in split_message(message):
        cleaned = clean_segment_prefix(segment)
        if not cleaned:
            continue
        if contains_any(cleaned, FULL_BODY_HINTS):
            points.append("改成全身")
            continue
        if contains_any(cleaned, HALF_BODY_HINTS):
            points.append("改成半身")
            continue
        if contains_any(cleaned, FRONT_HINTS) and contains_any(cleaned, STANDING_HINTS):
            points.append("改成正面站姿")
            continue
        if contains_any(cleaned, FRONT_HINTS):
            points.append("改成正面")
            continue
        if contains_any(cleaned, GAME_STYLE_HINTS):
            points.append("保留游戏设计风格")
            continue
        if contains_any(cleaned, ENGLISH_PROMPT_HINTS):
            points.append("只允许英文prompt")
            continue
        if contains_any(cleaned, CLEAN_HINTS):
            points.append("画面更干净")
            continue
        if contains_any(cleaned, COLORWAY_HINTS):
            points.append(cleaned)
            continue
        points.append(cleaned)
    return dedupe_preserve_order(points)


def build_global_policy_patch(message: str):
    if contains_any(message, ENGLISH_PROMPT_HINTS):
        return {"prompt_policy": PROMPT_POLICY_ENGLISH_ONLY}
    return {}


def build_project_strategy_patch(message: str):
    patch = {
        "persistent_must_have": [],
        "persistent_style_bias": [],
        "persistent_must_not_have": [],
        "consistency_rules": [],
    }
    if contains_any(message, FULL_BODY_HINTS):
        patch["persistent_must_have"] = append_unique(patch["persistent_must_have"], "全身角色展示")
    if contains_any(message, GAME_STYLE_HINTS):
        patch["persistent_style_bias"] = append_unique(patch["persistent_style_bias"], "游戏设计风格")
    if contains_any(message, LOCK_HINTS):
        patch["consistency_rules"] = append_unique(patch["consistency_rules"], "保持同一角色与服装结构")
    return {key: value for key, value in patch.items() if value}


def derive_subject_contract(task: dict, message: str, brief: dict):
    project_context = get_project_context(task)
    subject_contract = merge_subject_contract(
        project_context.get("subject_contract"),
        task.get("subject_contract"),
    )
    subject_contract = merge_subject_contract(
        subject_contract,
        infer_subject_contract(
            str(task.get("raw_request") or task.get("goal") or ""),
            task.get("brief"),
            subject_contract,
        ),
    )
    subject_contract = merge_subject_contract(
        subject_contract,
        infer_subject_contract(message, brief, subject_contract),
    )
    return normalize_subject_contract(subject_contract)


def apply_brief_edits(task: dict, message: str):
    brief = dict(task.get("brief") or {})
    must_have = normalize_string_list(brief.get("must_have"))
    style_bias = normalize_string_list(brief.get("style_bias"))
    must_not_have = normalize_string_list(brief.get("must_not_have"))
    edit_operations = []

    if contains_any(message, FULL_BODY_HINTS):
        must_have = remove_matching(must_have, HALF_BODY_HINTS + ["近景"])
        must_have = append_unique(must_have, "全身角色展示")
        edit_operations.append({"field": "must_have", "action": "replace", "value": "全身角色展示"})

    if contains_any(message, HALF_BODY_HINTS):
        must_have = remove_matching(must_have, FULL_BODY_HINTS + ["远景"])
        must_have = append_unique(must_have, "半身构图")
        edit_operations.append({"field": "must_have", "action": "replace", "value": "半身构图"})

    if contains_any(message, FRONT_HINTS):
        must_have = remove_matching(must_have, ["侧面", "背面", "side", "back"])
        if contains_any(message, FULL_BODY_HINTS) and contains_any(message, STANDING_HINTS):
            must_have = append_unique(must_have, "正面全身站立")
            edit_operations.append({"field": "must_have", "action": "append", "value": "正面全身站立"})
        else:
            must_have = append_unique(must_have, "正面视角")
            edit_operations.append({"field": "must_have", "action": "append", "value": "正面视角"})

    if contains_any(message, GAME_STYLE_HINTS):
        style_bias = append_unique(style_bias, "游戏设计风格")
        edit_operations.append({"field": "style_bias", "action": "append", "value": "游戏设计风格"})

    subject_contract = derive_subject_contract(task, message, brief)
    subject_constraints = subject_contract_to_brief_constraints(subject_contract)
    for value in normalize_string_list(subject_constraints.get("must_have")):
        must_have = append_unique(must_have, value)
    for value in normalize_string_list(subject_constraints.get("must_not_have")):
        must_not_have = append_unique(must_not_have, value)

    brief["must_have"] = must_have
    brief["style_bias"] = style_bias
    brief["must_not_have"] = must_not_have
    return brief, edit_operations, subject_contract


def build_revision_patch(task: dict, message: str, feedback_points):
    revision_mode = detect_revision_mode_from_message(task, message)
    accepted_capture = get_latest_capture(task)
    latest_result_capture = get_latest_result_capture(task)
    explicit_base_acceptance = has_explicit_base_acceptance(message)
    change_axis = detect_change_axis(revision_mode)
    palette_request = build_palette_request(message)
    subject_contract = normalize_subject_contract(task.get("subject_contract"))
    has_subject_anchor = bool(
        subject_contract.get("subject_type")
        or subject_contract.get("gender")
        or subject_contract.get("count")
        or normalize_string_list(subject_contract.get("role_labels"))
    )
    patch = {
        "revision_mode": revision_mode,
        "change_axis": change_axis,
        "locked_elements": [],
        "allow_subject_redraw": revision_mode == "new_direction",
        "keep_list": [],
        "change_list": dedupe_preserve_order(feedback_points),
    }

    if revision_mode == "colorway_only":
        patch["locked_elements"] = list(DEFAULT_COLORWAY_LOCKS)
        patch["allow_subject_redraw"] = False
        patch["keep_list"] = list(DEFAULT_COLORWAY_LOCKS)
        patch["palette_request"] = palette_request
        if accepted_capture:
            patch["accepted_base_reference"] = accepted_capture
            patch["design_lock_state"] = "hard_locked"
        elif explicit_base_acceptance and latest_result_capture:
            patch["accepted_base_reference"] = latest_result_capture
            patch["design_lock_state"] = "hard_locked"
        else:
            patch["design_lock_state"] = "soft_locked"
    elif revision_mode in {"structure_refine", "finish_only"}:
        if explicit_base_acceptance or accepted_capture or has_subject_anchor:
            patch["locked_elements"] = list(DEFAULT_STRUCTURE_LOCKS)
            patch["keep_list"] = list(DEFAULT_STRUCTURE_LOCKS)
            patch["allow_subject_redraw"] = False
        if accepted_capture:
            patch["accepted_base_reference"] = accepted_capture
            patch["design_lock_state"] = "hard_locked"
        elif explicit_base_acceptance and latest_result_capture:
            patch["accepted_base_reference"] = latest_result_capture
            patch["design_lock_state"] = "hard_locked"
        elif patch["locked_elements"]:
            patch["design_lock_state"] = "soft_locked"
    else:
        patch["design_lock_state"] = "unlocked"

    return patch


def apply_feedback_to_task(task: dict, message: str, increment_round: bool = False):
    normalized_message = normalize_text(message)
    feedback_points = build_feedback_points(normalized_message)
    scope = infer_scope(normalized_message)
    brief, edit_operations, subject_contract = apply_brief_edits(task, normalized_message)
    revision_seed_task = dict(task)
    revision_seed_task["brief"] = brief
    revision_seed_task["subject_contract"] = subject_contract
    revision_patch = build_revision_patch(revision_seed_task, normalized_message, feedback_points)
    project_strategy_patch = build_project_strategy_patch(normalized_message)
    global_policy_patch = build_global_policy_patch(normalized_message)
    palette_request = revision_patch.get("palette_request") if isinstance(revision_patch.get("palette_request"), dict) else {}

    feedback_entry = {
        "scope": scope,
        "raw_text": normalized_message,
        "message": normalized_message,
        "points": feedback_points,
        "edit_operations": edit_operations,
        "revision_mode": revision_patch.get("revision_mode"),
        "change_axis": revision_patch.get("change_axis"),
        "keep_list": normalize_string_list(revision_patch.get("keep_list")),
        "change_list": normalize_string_list(revision_patch.get("change_list")),
        "palette_request": palette_request,
        "recorded_at": now_iso(),
    }

    updated_task = dict(task)
    updated_task["brief"] = brief
    updated_task["subject_contract"] = subject_contract
    updated_task["latest_feedback"] = feedback_entry
    updated_task["revision_patch"] = revision_patch
    updated_task["requested_revision_mode"] = normalize_text(revision_patch.get("revision_mode"))
    updated_task["change_axis"] = normalize_text(revision_patch.get("change_axis"))
    updated_task["locked_elements"] = normalize_string_list(revision_patch.get("locked_elements"))
    updated_task["allow_subject_redraw"] = bool(revision_patch.get("allow_subject_redraw"))
    updated_task["keep_list"] = normalize_string_list(revision_patch.get("keep_list"))
    updated_task["change_list"] = normalize_string_list(revision_patch.get("change_list"))
    if palette_request:
        updated_task["palette_request"] = palette_request
    if normalize_text(revision_patch.get("design_lock_state")):
        updated_task["design_lock_state"] = normalize_text(revision_patch.get("design_lock_state"))
    if normalize_text(revision_patch.get("accepted_base_reference")):
        updated_task["accepted_base_reference"] = normalize_text(revision_patch.get("accepted_base_reference"))

    artifacts = dict(updated_task.get("artifacts") or {})
    if normalize_text(revision_patch.get("accepted_base_reference")):
        artifacts["accepted_base_reference"] = normalize_text(revision_patch.get("accepted_base_reference"))
    artifacts["subject_contract"] = subject_contract
    updated_task["artifacts"] = artifacts

    if project_strategy_patch:
        existing_project_patch = dict(updated_task.get("project_strategy_patch") or {})
        for key, values in project_strategy_patch.items():
            merged = normalize_string_list(existing_project_patch.get(key))
            for value in normalize_string_list(values):
                merged = append_unique(merged, value)
            existing_project_patch[key] = merged
        updated_task["project_strategy_patch"] = existing_project_patch

    if global_policy_patch:
        existing_policy_patch = dict(updated_task.get("global_policy_patch") or {})
        existing_policy_patch.update(global_policy_patch)
        updated_task["global_policy_patch"] = existing_policy_patch
        updated_task["prompt_policy"] = PROMPT_POLICY_ENGLISH_ONLY
        updated_task["prompt_language"] = "en"

    if increment_round:
        updated_task["round_index"] = max(1, int(updated_task.get("round_index") or 1)) + 1
        updated_task["prompt_version"] = max(1, int(updated_task.get("prompt_version") or 1)) + 1

    updated_task["task_phase"] = "feedback_applied"
    updated_task["updated_at"] = now_iso()

    return {
        "ok": True,
        "task": updated_task,
        "feedback_summary": "、".join(feedback_points),
        "latest_feedback": feedback_entry,
        "revision_patch": revision_patch,
    }


def main():
    configure_stdout()
    args = parse_args()
    task, message, increment_round = load_payload(args)
    result = apply_feedback_to_task(task, message, increment_round=increment_round)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
