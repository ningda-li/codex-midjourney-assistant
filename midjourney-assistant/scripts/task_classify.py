import argparse
import json
import re
import sys
from pathlib import Path

from common import ASSET_ROOT, configure_stdout, normalize_string_list, now_iso, read_json_file, read_json_input


TASK_SCHEMA_PATH = ASSET_ROOT / "task-type-schema.json"
DEFAULT_LOCKED_ELEMENTS = ["face", "hair", "silhouette", "garment_panels", "material_map"]

TASK_KEYWORDS = {
    "video_generation": [
        "视频",
        "动图",
        "动画",
        "animate",
        "loop",
        "motion",
        "起始帧",
        "终帧",
        "starting frame",
        "end frame",
    ],
    "image_edit": [
        "局部",
        "局部重绘",
        "局部修改",
        "只改",
        "修这个区域",
        "改这个区域",
        "扩图",
        "补边",
        "编辑",
        "editor",
        "vary region",
        "zoom out",
        "pan",
        "retexture",
        "inpaint",
        "local edit",
        "local repaint",
    ],
    "style_system_build": [
        "风格码",
        "style creator",
        "style explorer",
        "style code",
        "sref",
        "风格系统",
        "长期风格",
    ],
    "continuity_batch": [
        "继续上一轮",
        "继续这轮",
        "上一轮",
        "延续",
        "统一一批图",
        "同一个角色",
        "同一个产品",
        "保持一致",
        "same character",
        "continue previous",
    ],
    "reference_driven": [
        "参考图",
        "按这张",
        "照这张",
        "based on this",
        "reference",
    ],
    "brand_visual_direction": [
        "品牌视觉",
        "品牌方向",
        "项目风格",
        "视觉方向",
        "moodboard",
        "品牌调性",
    ],
    "product_visual": [
        "产品图",
        "商品图",
        "包装",
        "产品广告",
        "电商",
        "硬件",
        "product",
        "packaging",
    ],
    "poster": [
        "海报",
        "封面",
        "宣传图",
        "poster",
        "cover art",
    ],
    "scene_concept": [
        "场景",
        "环境概念",
        "世界观",
        "空间",
        "scene",
        "environment",
    ],
    "fashion_material": [
        "服装",
        "材质",
        "面料",
        "工艺",
        "fashion",
        "fabric",
        "material study",
    ],
    "proposal_visual": [
        "提案",
        "方向图",
        "筛选图",
        "探索",
        "proposal",
        "direction board",
    ],
    "character_sheet": [
        "设定图",
        "角色设定图",
        "正面全身",
        "全身站立",
        "设计图",
        "character sheet",
        "full-body",
        "front-facing",
    ],
    "character_design": [
        "角色",
        "人物",
        "角色形象",
        "角色设计",
        "character",
        "hero",
    ],
}

STYLE_KEYWORDS = [
    "无畏契约的设计风格",
    "无畏契约设计风格",
    "游戏设计风格",
    "游戏角色设计",
    "现代时尚风格",
    "电影感",
    "写实",
    "插画",
    "厚涂",
    "二次元",
    "anime",
    "cyberpunk",
    "fashion",
    "cinematic",
]

COMPOSITION_KEYWORDS = [
    "全身",
    "半身",
    "近景",
    "远景",
    "正面",
    "侧面",
    "背面",
    "站立",
    "立绘",
    "front-facing",
    "full-body",
    "close-up",
]

CONSISTENCY_KEYWORDS = [
    "统一",
    "一致",
    "同一个",
    "延续",
    "继续",
    "保留",
    "consistent",
    "continuity",
    "same character",
]

FINALIZE_HINTS = [
    "定稿",
    "最终稿",
    "成品",
    "可交付",
    "精修",
    "高清",
    "production-ready",
]

EXPLORE_HINTS = [
    "探索",
    "提案",
    "方向",
    "筛选",
    "多方案",
    "options",
]

COLORWAY_KEYWORDS = [
    "配色",
    "颜色",
    "色板",
    "色系",
    "换几个配色",
    "换配色",
    "看看别的颜色",
    "colorway",
    "palette",
    "recolor",
]

LOCK_STRONG_KEYWORDS = [
    "固定",
    "锁定",
    "保持这套设计",
    "保持同一个角色",
    "别换人",
    "不要换人",
    "same face",
    "same hairstyle",
    "same silhouette",
    "same outfit silhouette",
]

LOCK_SOFT_KEYWORDS = [
    "保留这个设计",
    "保留这套设计",
    "延续这个角色",
    "同一个角色",
    "同一个人",
    "same character",
    "consistent",
]

NEW_DIRECTION_HINTS = [
    "重做",
    "重新设计",
    "重新来",
    "换个人",
    "换一个人",
    "换版型",
    "新方向",
    "多看几个方向",
    "重画",
    "new direction",
]

STRUCTURE_REFINE_HINTS = [
    "版型",
    "剪裁",
    "结构",
    "轮廓",
    "材质",
    "服装设计",
    "再收一点",
    "精简",
    "更利落",
    "structure",
    "silhouette",
]

FINISH_ONLY_HINTS = [
    "更干净",
    "更高级",
    "更精致",
    "抛光",
    "cleaner",
    "premium finish",
]

FORCED_TASK_PRIORITY = [
    "video_generation",
    "style_system_build",
    "image_edit",
    "continuity_batch",
]

VIDEO_STARTING_FRAME_HINTS = [
    "起始帧",
    "starting frame",
    "首帧",
    "approved image",
    "approved still",
    "this image",
    "current image",
    "当前这张图",
    "上一轮结果",
    "上一张图",
    "定稿图",
]

CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def parse_args():
    parser = argparse.ArgumentParser(description="生成 Midjourney task_model")
    parser.add_argument("--task-file", help="统一任务对象路径")
    parser.add_argument("--input-file", help="输入 JSON 路径")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def load_task(args):
    if args.task_file:
        payload = read_json_file(Path(args.task_file), default={})
        if isinstance(payload, dict):
            return payload
    if args.input_file:
        payload = read_json_file(Path(args.input_file), default={})
        if isinstance(payload, dict):
            return payload
    payload = read_json_input(sys.stdin.read().strip())
    if isinstance(payload, dict):
        return payload
    raise ValueError("task_classify 输入必须是任务对象 JSON")


def load_schema():
    payload = read_json_file(TASK_SCHEMA_PATH, default={})
    return payload if isinstance(payload, dict) else {}


def build_source_text(task: dict) -> str:
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    parts = [
        str(task.get("raw_request") or ""),
        str(task.get("goal") or ""),
        str(brief.get("goal") or ""),
        " ".join(normalize_string_list(brief.get("must_have"))),
        " ".join(normalize_string_list(brief.get("style_bias"))),
        " ".join(normalize_string_list(brief.get("must_not_have"))),
        " ".join(normalize_string_list(latest_feedback.get("points"))),
        str(latest_feedback.get("raw_text") or ""),
        str(task.get("last_result_summary") or ""),
        str(revision_patch.get("summary") or ""),
    ]
    return " ".join(part for part in parts if part).strip().lower()


def keyword_in_text(text: str, keyword: str) -> bool:
    normalized = str(keyword or "").strip().lower()
    if not normalized:
        return False
    if CJK_PATTERN.search(normalized):
        return normalized in text
    escaped = re.escape(normalized)
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text))


def count_keyword_hits(text: str, keywords):
    return sum(1 for keyword in keywords if keyword_in_text(text, keyword))


def has_reference_input(text: str) -> bool:
    return bool(re.search(r"https?://", text)) or any(token in text for token in ["参考图", "reference"])


def has_video_starting_frame_signal(task: dict, text: str) -> bool:
    if has_reference_input(text):
        return True
    if any(keyword_in_text(text, keyword) for keyword in VIDEO_STARTING_FRAME_HINTS):
        return True
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    if str(artifacts.get("final_capture") or "").strip():
        return True
    last_auto_result = artifacts.get("last_auto_result") if isinstance(artifacts.get("last_auto_result"), dict) else {}
    if str(last_auto_result.get("final_capture") or "").strip():
        return True
    return False


def detect_task_type(task: dict, text: str):
    candidates = []
    for task_type, keywords in TASK_KEYWORDS.items():
        score = count_keyword_hits(text, keywords)
        if task_type == "reference_driven" and has_reference_input(text):
            score += 2
        if task_type == "continuity_batch" and int(task.get("round_index") or 1) > 1:
            score += 1
        if score > 0:
            candidates.append({"task_type": task_type, "score": score})

    forced_candidates = [
        item
        for item in candidates
        if item["task_type"] in FORCED_TASK_PRIORITY and item["score"] >= 1
    ]
    if forced_candidates:
        forced_candidates.sort(
            key=lambda item: (
                -item["score"],
                FORCED_TASK_PRIORITY.index(item["task_type"]),
            )
        )
        return forced_candidates[0]["task_type"], candidates

    if any(item["task_type"] == "reference_driven" for item in candidates):
        reference_candidate = next(item for item in candidates if item["task_type"] == "reference_driven")
        if reference_candidate["score"] >= 2:
            return "reference_driven", candidates

    if any(item["task_type"] == "character_sheet" for item in candidates):
        sheet_candidate = next(item for item in candidates if item["task_type"] == "character_sheet")
        if sheet_candidate["score"] >= 1:
            return "character_sheet", candidates

    if not candidates:
        return "character_design", candidates

    candidates.sort(key=lambda item: (-item["score"], item["task_type"]))
    return candidates[0]["task_type"], candidates


def detect_stage(task: dict, text: str, task_type: str) -> str:
    round_index = max(1, int(task.get("round_index") or 1))
    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    if task_type == "style_system_build":
        return "explore"
    if task_type in {"image_edit", "video_generation"}:
        return "converge"
    if any(keyword_in_text(text, hint) for hint in FINALIZE_HINTS):
        return "finalize"
    if round_index > 1 or normalize_string_list(latest_feedback.get("points")):
        return "converge"
    if task_type == "continuity_batch":
        return "converge"
    if any(keyword_in_text(text, hint) for hint in EXPLORE_HINTS):
        return "explore"
    return "explore"


def detect_subject_type(task_type: str, text: str) -> str:
    if task_type in {"character_design", "character_sheet", "continuity_batch"}:
        return "character"
    if task_type == "product_visual":
        return "product"
    if task_type == "scene_concept":
        return "scene"
    if task_type == "brand_visual_direction":
        return "brand_system"
    if task_type == "image_edit":
        return "existing_image"
    if task_type == "video_generation":
        return "motion_clip"
    if task_type == "style_system_build":
        return "style_system"
    if "cat" in text or "猫" in text:
        return "animal"
    return "mixed_visual"


def extract_style_goal(task: dict, text: str):
    values = list(normalize_string_list((task.get("brief") or {}).get("style_bias")))
    for keyword in STYLE_KEYWORDS:
        if keyword_in_text(text, keyword) and keyword not in values:
            values.append(keyword)
    return values


def extract_composition_goal(task: dict, text: str):
    values = []
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    for item in normalize_string_list(brief.get("must_have")):
        if any(keyword in item for keyword in COMPOSITION_KEYWORDS):
            values.append(item)
    for keyword in COMPOSITION_KEYWORDS:
        if keyword_in_text(text, keyword) and keyword not in values:
            values.append(keyword)
    return values


def extract_consistency_goal(task: dict, text: str, task_type: str):
    values = []
    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    if task_type in {"continuity_batch", "reference_driven"}:
        values.append("保持主体一致性")
    for item in normalize_string_list(latest_feedback.get("points")):
        if any(keyword in item for keyword in CONSISTENCY_KEYWORDS):
            values.append(item)
    for keyword in CONSISTENCY_KEYWORDS:
        if keyword_in_text(text, keyword) and keyword not in values:
            values.append(keyword)
    return normalize_string_list(values)


def detect_reference_role(text: str) -> str:
    if any(keyword_in_text(text, token) for token in ["风格", "style"]):
        return "style"
    if any(keyword_in_text(text, token) for token in ["构图", "composition", "场景关系"]):
        return "composition"
    if any(keyword_in_text(text, token) for token in ["角色", "人物", "产品", "主体", "same character"]):
        return "subject"
    if any(keyword_in_text(text, token) for token in ["项目调性", "品牌方向", "moodboard"]):
        return "project_direction"
    return "unspecified"


def schema_defaults(schema: dict, task_type: str):
    for item in schema.get("task_types", []):
        if isinstance(item, dict) and str(item.get("id") or "").strip() == task_type:
            return item
    return {}


def get_project_context(task: dict):
    snapshot = task.get("project_context_snapshot")
    if isinstance(snapshot, dict):
        return snapshot
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    project_context = artifacts.get("project_context")
    return project_context if isinstance(project_context, dict) else {}


def get_accepted_base_reference(task: dict) -> str:
    for candidate in [
        task.get("accepted_base_reference"),
        (task.get("revision_patch") or {}).get("accepted_base_reference"),
        get_project_context(task).get("accepted_base_reference"),
    ]:
        value = str(candidate or "").strip()
        if value:
            return value
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    for candidate in [
        artifacts.get("accepted_base_reference"),
    ]:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def detect_revision_mode(task: dict, text: str, task_type: str, task_stage: str) -> str:
    project_context = get_project_context(task)
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    existing_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    patched_mode = str(revision_patch.get("revision_mode") or "").strip()
    existing_mode = str(existing_model.get("revision_mode") or project_context.get("latest_revision_mode") or "").strip()
    if patched_mode:
        return patched_mode
    if task_type == "image_edit":
        return "local_edit"
    if any(keyword_in_text(text, keyword) for keyword in COLORWAY_KEYWORDS):
        return "colorway_only"
    if task_stage == "finalize" or any(keyword_in_text(text, keyword) for keyword in FINISH_ONLY_HINTS):
        return "finish_only"
    if any(keyword_in_text(text, keyword) for keyword in NEW_DIRECTION_HINTS):
        return "new_direction"
    if any(keyword_in_text(text, keyword) for keyword in STRUCTURE_REFINE_HINTS):
        return "structure_refine"
    if max(1, int(task.get("round_index") or 1)) > 1:
        return existing_mode or "structure_refine"
    if task_type in {"continuity_batch", "reference_driven", "character_sheet"}:
        return "structure_refine"
    return "new_direction"


def detect_change_axis(revision_mode: str) -> str:
    mapping = {
        "new_direction": "direction",
        "structure_refine": "structure",
        "colorway_only": "palette",
        "finish_only": "finish",
        "local_edit": "local",
    }
    return mapping.get(revision_mode, "direction")


def detect_locked_elements(task: dict, text: str, task_type: str, revision_mode: str):
    locked_elements = []
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    project_context = get_project_context(task)

    for value in normalize_string_list(revision_patch.get("locked_elements")):
        if value not in locked_elements:
            locked_elements.append(value)
    for value in normalize_string_list(project_context.get("locked_elements")):
        if value not in locked_elements:
            locked_elements.append(value)

    lock_signal = any(keyword_in_text(text, keyword) for keyword in LOCK_STRONG_KEYWORDS + LOCK_SOFT_KEYWORDS)
    if revision_mode == "colorway_only":
        for value in DEFAULT_LOCKED_ELEMENTS:
            if value not in locked_elements:
                locked_elements.append(value)
    elif revision_mode in {"structure_refine", "finish_only"} and (
        lock_signal or task_type in {"continuity_batch", "reference_driven", "character_sheet"}
    ):
        for value in ["face", "hair", "silhouette", "garment_panels"]:
            if value not in locked_elements:
                locked_elements.append(value)
    return locked_elements


def detect_lock_state(task: dict, text: str, revision_mode: str, locked_elements):
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    project_context = get_project_context(task)
    for candidate in [
        revision_patch.get("design_lock_state"),
        task.get("design_lock_state"),
        project_context.get("design_lock_state"),
    ]:
        value = str(candidate or "").strip()
        if value == "hard_locked":
            return value
    accepted_base_reference = get_accepted_base_reference(task)
    if revision_mode == "colorway_only" and accepted_base_reference:
        return "hard_locked"
    if locked_elements or any(keyword_in_text(text, keyword) for keyword in LOCK_STRONG_KEYWORDS + LOCK_SOFT_KEYWORDS):
        return "soft_locked"
    return "unlocked"


def build_open_questions(task: dict, task_type: str, reference_role: str, defaults: dict, revision_mode: str, lock_state: str):
    questions = []
    if task_type == "reference_driven" and reference_role == "unspecified":
        questions.append("reference_role_unspecified")
    if task_type == "brand_visual_direction" and not normalize_string_list((task.get("brief") or {}).get("style_bias")):
        questions.append("brand_style_anchor_missing")
    if task_type == "video_generation" and not has_video_starting_frame_signal(task, build_source_text(task)):
        questions.append("video_starting_frame_implicit")
    if revision_mode == "colorway_only" and lock_state != "hard_locked":
        questions.append("colorway_base_missing")
    if not str((task.get("brief") or {}).get("deliverable") or "").strip():
        questions.append("deliverable_implicit")
    if not defaults:
        questions.append("task_type_schema_missing")
    return questions


def build_risk_flags(task: dict, candidates, task_type: str, reference_role: str, revision_mode: str, lock_state: str):
    flags = []
    if len(candidates) > 1:
        flags.append("multiple_task_signals")
    if not str(task.get("mode") or "").strip():
        flags.append("mode_unset")
    if task_type == "reference_driven" and reference_role == "unspecified":
        flags.append("reference_role_needs_clarification")
    if task_type == "video_generation" and any(item["task_type"] == "image_edit" for item in candidates):
        flags.append("video_vs_edit_boundary")
    if revision_mode == "colorway_only" and lock_state != "hard_locked":
        flags.append("colorway_without_base_lock")
    if not str((task.get("brief") or {}).get("deliverable") or "").strip():
        flags.append("deliverable_is_implicit")
    return flags


def classify_task(task: dict):
    schema = load_schema()
    text = build_source_text(task)
    task_type, candidates = detect_task_type(task, text)
    defaults = schema_defaults(schema, task_type)
    task_stage = detect_stage(task, text, task_type)
    revision_mode = detect_revision_mode(task, text, task_type, task_stage)
    change_axis = detect_change_axis(revision_mode)
    locked_elements = detect_locked_elements(task, text, task_type, revision_mode)
    lock_state = detect_lock_state(task, text, revision_mode, locked_elements)
    reference_role = detect_reference_role(text) if task_type == "reference_driven" else ""
    accepted_base_reference = get_accepted_base_reference(task)

    task_model = {
        "task_type": task_type,
        "task_stage": task_stage,
        "revision_mode": revision_mode,
        "change_axis": change_axis,
        "lock_state": lock_state,
        "locked_elements": locked_elements,
        "accepted_base_reference": accepted_base_reference,
        "deliverable_type": str(defaults.get("default_deliverable") or "single_direction_frame").strip(),
        "subject_type": detect_subject_type(task_type, text),
        "style_goal": extract_style_goal(task, text),
        "composition_goal": extract_composition_goal(task, text),
        "consistency_goal": extract_consistency_goal(task, text, task_type),
        "must_have": normalize_string_list((task.get("brief") or {}).get("must_have")),
        "must_not_have": normalize_string_list((task.get("brief") or {}).get("must_not_have")),
        "open_questions": build_open_questions(task, task_type, reference_role, defaults, revision_mode, lock_state),
        "risk_flags": build_risk_flags(task, candidates, task_type, reference_role, revision_mode, lock_state),
        "reference_role": reference_role,
        "candidate_task_types": candidates,
        "evaluation_focus": normalize_string_list(defaults.get("evaluation_focus")),
        "failure_modes": normalize_string_list(defaults.get("failure_modes")),
        "classified_at": now_iso(),
    }

    updated_task = dict(task)
    updated_task["task_model"] = task_model
    updated_task["task_phase"] = "task_classified"
    updated_task["updated_at"] = now_iso()
    return updated_task, task_model


def main():
    configure_stdout()
    args = parse_args()
    task = load_task(args)
    updated_task, task_model = classify_task(task)
    result = {
        "ok": True,
        "task": updated_task,
        "task_model": task_model,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
