import argparse
import json
import re
import sys
from pathlib import Path

from common import (
    ASSET_ROOT,
    PROMPT_POLICY_ENGLISH_ONLY,
    configure_stdout,
    is_english_prompt_text,
    normalize_prompt_policy,
    normalize_prompt_text,
    normalize_string_list,
    now_iso,
    read_json_file,
    read_json_input,
    validate_execution_prompt,
)
from manual_mode_prepare import (
    build_brief_summary,
    build_memory_guidance,
    dedupe_preserve_order,
    extract_feedback_points,
    has_letters,
    infer_goal_fallback,
    translate_cn_fragment_to_en,
    translate_list,
)
from solution_plan_build import build_solution_plan
from task_classify import classify_task


PARAMETER_PRESETS_PATH = ASSET_ROOT / "parameter-presets.json"
PROMPT_RULES_PATH = ASSET_ROOT / "prompt-composition-rules.json"

QUALITY_CUES = {
    "clean_design_sheet": ["clean character design sheet presentation"],
    "commercial_finish": ["commercial finish", "premium presentation"],
    "final_delivery": ["polished production-ready finish"],
    "colorway_readability": ["clear readable colorway", "controlled palette separation"],
    "direction_selection": ["selection-ready concept options"],
    "usable_direction": ["clear and usable visual direction"],
    "edit_integrity": ["edit-integrity focused result", "preserve the original structure while fixing the targeted changes"],
    "motion_proof": ["coherent five-second motion clip", "stable keyframe-to-motion transition"],
    "reusable_style_system": ["reusable style language", "portable style-code-ready aesthetic system"],
}

REFERENCE_ROLE_CUES = {
    "subject": ["consistent subject identity"],
    "style": ["style-driven visual language"],
    "composition": ["clear composition anchor"],
    "project_direction": ["project-level visual direction"],
}

INTERNAL_PROCESS_TERMS = [
    "我会继续",
    "我先检查",
    "检查脚本",
    "回归",
    "task_model",
    "solution_plan",
    "diagnosis_report",
]

COLOR_TRANSLATIONS = {
    "白": "white",
    "冷白": "cool white",
    "暖白": "warm white",
    "珍珠白": "pearl white",
    "米白": "off-white",
    "灰": "gray",
    "浅灰": "light gray",
    "深灰": "dark gray",
    "石墨": "graphite",
    "石墨灰": "graphite gray",
    "炭灰": "charcoal",
    "黑": "black",
    "酒红": "oxblood",
    "勃艮第": "burgundy",
    "红": "red",
    "海军蓝": "navy",
    "蓝灰": "slate blue",
    "蓝": "blue",
    "卡其": "khaki",
    "沙色": "sand",
    "米色": "beige",
    "棕": "brown",
    "橄榄": "olive",
    "苔藓": "moss",
    "绿": "green",
    "银": "silver",
    "银钢": "silver steel",
    "钢": "steel",
    "枪灰": "gunmetal",
    "金": "gold",
    "冰蓝": "ice blue",
}

PALETTE_SLOT_LABELS = {
    "top": "top",
    "bottom": "bottom",
    "hardware": "hardware",
    "accent": "accent",
}

LOCKED_ELEMENT_PROMPT_MAP = {
    "face": "the same face",
    "hair": "the same hairstyle",
    "silhouette": "the same silhouette",
    "garment_panels": "the same garment panel layout",
    "material_map": "the same material relationships",
}


def parse_args():
    parser = argparse.ArgumentParser(description="生成 Midjourney prompt_package")
    parser.add_argument("--task-file", help="统一任务对象路径")
    parser.add_argument("--input-file", help="输入 JSON 路径")
    parser.add_argument("--regenerate-prompt", action="store_true", help="强制重生 prompt")
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
    raise ValueError("prompt_strategy_select 输入必须是任务对象 JSON")


def load_asset(path: Path):
    payload = read_json_file(path, default={})
    return payload if isinstance(payload, dict) else {}


def current_stage(task: dict) -> str:
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    return str(task_model.get("task_stage") or "").strip() or "explore"


def current_task_type(task: dict) -> str:
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    return str(task_model.get("task_type") or "").strip()


def current_revision_mode(task: dict) -> str:
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    return str(
        task_model.get("revision_mode")
        or task.get("requested_revision_mode")
        or ""
    ).strip()


def build_diagnosis_summary(task: dict):
    diagnosis = task.get("diagnosis_report") if isinstance(task.get("diagnosis_report"), dict) else {}
    return {
        "observed_issues": normalize_string_list(diagnosis.get("observed_issues")),
        "likely_causes": normalize_string_list(diagnosis.get("likely_causes")),
        "keep_list": normalize_string_list(diagnosis.get("keep_list")),
        "change_list": normalize_string_list(diagnosis.get("change_list")),
        "next_round_goal": str(diagnosis.get("next_round_goal") or "").strip(),
        "next_round_strategy": str(diagnosis.get("next_round_strategy") or "").strip(),
        "next_round_prompt_delta": normalize_string_list(diagnosis.get("next_round_prompt_delta")),
    }


def build_diagnosis_prompt_guidance(task: dict):
    summary = build_diagnosis_summary(task)
    prompt_cues = translate_list(summary.get("next_round_prompt_delta"), strict=False, field_label="diagnosis_delta")
    keep_cues = translate_list(summary.get("keep_list"), strict=False, field_label="diagnosis_keep")
    goal_cue = translate_cn_fragment_to_en(
        summary.get("next_round_goal"),
        strict=False,
        field_label="diagnosis_goal",
    )
    if has_letters(goal_cue):
        prompt_cues.append(goal_cue)
    prompt_cues.extend(keep_cues[:2])
    review_focus = normalize_string_list(summary.get("change_list")) or normalize_string_list(summary.get("observed_issues"))
    return {
        "summary": summary,
        "prompt_cues": dedupe_preserve_order(prompt_cues),
        "review_focus": review_focus,
    }


def build_generic_segments(
    goal,
    must_have,
    composition_goal,
    style_goal,
    style_bias,
    preferred_phrases,
    reference_cues,
    memory_guidance,
    consistency_goal,
    feedback_points,
    diagnosis_guidance,
    quality_cues,
    avoid_terms,
):
    segments = [goal]
    segments.extend(must_have[:4])
    segments.extend(composition_goal[:3])
    segments.extend(style_goal[:3])
    segments.extend(style_bias[:3])
    segments.extend(preferred_phrases[:3])
    segments.extend(reference_cues[:2])
    segments.extend(memory_guidance.get("visual_prompt_cues", [])[:3])
    segments.extend(consistency_goal[:2])
    segments.extend(feedback_points[:3])
    segments.extend(diagnosis_guidance.get("prompt_cues", [])[:3])
    segments.extend(quality_cues)
    if avoid_terms:
        segments.append("avoid " + ", ".join(avoid_terms))
    return segments


def get_project_context(task: dict):
    snapshot = task.get("project_context_snapshot")
    if isinstance(snapshot, dict):
        return snapshot
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    project_context = artifacts.get("project_context")
    return project_context if isinstance(project_context, dict) else {}


def get_accepted_base_reference(task: dict, solution_plan: dict):
    readiness = solution_plan.get("readiness") if isinstance(solution_plan.get("readiness"), dict) else {}
    for candidate in [
        readiness.get("accepted_base_reference"),
        task.get("accepted_base_reference"),
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


def get_revision_override(prompt_rules: dict, revision_mode: str):
    overrides = (
        prompt_rules.get("revision_mode_overrides")
        if isinstance(prompt_rules.get("revision_mode_overrides"), dict)
        else {}
    )
    return overrides.get(revision_mode) if isinstance(overrides.get(revision_mode), dict) else {}


def translate_palette_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    detected = []
    remaining = value
    for source, target in sorted(COLOR_TRANSLATIONS.items(), key=lambda item: -len(item[0])):
        if source in remaining and target not in detected:
            detected.append(target)
            remaining = remaining.replace(source, " ")
    if detected:
        return ", ".join(detected)
    translated = translate_cn_fragment_to_en(value, strict=False, field_label="palette")
    if has_letters(translated) and not re.search(r"[\u4e00-\u9fff]", translated):
        return translated
    return ""


def build_colorway_segments(task: dict, solution_plan: dict, prompt_rules: dict):
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    strict_english = normalize_prompt_policy(task.get("prompt_policy")) == PROMPT_POLICY_ENGLISH_ONLY
    goal = translate_cn_fragment_to_en(
        brief.get("goal") or task.get("goal") or "",
        strict=strict_english and bool(str(brief.get("goal") or task.get("goal") or "").strip()),
        field_label="goal",
    )
    if not has_letters(goal):
        goal = infer_goal_fallback(task)

    palette_request = task.get("palette_request") if isinstance(task.get("palette_request"), dict) else {}
    revision_override = get_revision_override(prompt_rules, current_revision_mode(task))
    preferred_phrases = normalize_string_list(revision_override.get("preferred_phrases"))
    quality_target = str(solution_plan.get("quality_target") or "").strip()
    quality_cues = QUALITY_CUES.get(quality_target, [])
    locked_elements = normalize_string_list((task.get("task_model") or {}).get("locked_elements"))
    locked_reference = get_accepted_base_reference(task, solution_plan)
    if not locked_reference:
        raise ValueError("当前是配色任务，但还没有锁定基底图。")

    segments = [
        goal,
        "same face and hairstyle",
        "same body proportions",
        "same silhouette and garment panel layout",
        "same material map and accessory placement",
        "front-facing full-body standing pose",
        "single character",
        "clean character design sheet presentation",
    ]

    slot_order = normalize_string_list(revision_override.get("palette_slots")) or ["top", "bottom", "hardware", "accent"]
    for slot in slot_order:
        values = normalize_string_list(palette_request.get(slot))
        if not values:
            continue
        translated = ", ".join(filter(None, [translate_palette_text(value) for value in values]))
        if translated:
            segments.append(f"{PALETTE_SLOT_LABELS.get(slot, slot)} in {translated}")

    summary = translate_palette_text(str(palette_request.get("summary") or "").strip())
    if summary:
        segments.append(f"palette direction: {summary}")
    else:
        segments.append("single readable modern colorway with clear top-bottom separation")

    locked_element_phrases = [
        LOCKED_ELEMENT_PROMPT_MAP.get(item)
        for item in locked_elements[:5]
        if LOCKED_ELEMENT_PROMPT_MAP.get(item)
    ]
    if locked_element_phrases:
        segments.append("preserve " + ", ".join(locked_element_phrases))
    segments.extend(preferred_phrases[:3])
    segments.extend(quality_cues[:2])

    max_negative_constraints = int(revision_override.get("max_negative_constraints") or 2)
    translated_must_not_have = translate_list(brief.get("must_not_have"), strict=False, field_label="must_not_have")
    must_not_have = [value for value in translated_must_not_have if has_letters(value)][:max_negative_constraints]
    if must_not_have:
        segments.append("avoid " + ", ".join(must_not_have))
    return dedupe_preserve_order([segment for segment in segments if str(segment).strip()])


def build_image_edit_segments(
    goal,
    must_have,
    style_goal,
    style_bias,
    preferred_phrases,
    diagnosis_guidance,
    quality_cues,
    recommended_capabilities,
):
    segments = []
    if must_have:
        segments.extend(must_have[:4])
    elif has_letters(goal):
        segments.append(goal)
    if "retexture" in recommended_capabilities:
        segments.extend(style_goal[:2])
        segments.extend(style_bias[:2])
    segments.extend(preferred_phrases[:2])
    segments.extend(diagnosis_guidance.get("prompt_cues", [])[:2])
    if len(quality_cues) > 1:
        segments.extend(quality_cues[1:2])
    else:
        segments.extend(quality_cues[:1])
    return segments


def build_video_generation_segments(goal, must_have, preferred_phrases, diagnosis_guidance, quality_cues):
    segments = []
    segments.extend(must_have[:2])
    cleaned_goal = strip_request_lead(goal)
    if not segments and has_letters(cleaned_goal):
        segments.append(cleaned_goal)
    segments.extend(preferred_phrases[:1])
    segments.extend(diagnosis_guidance.get("prompt_cues", [])[:2])
    segments.extend(quality_cues[:2])
    return segments


def build_style_system_segments(goal, style_goal, style_bias, preferred_phrases, diagnosis_guidance, quality_cues):
    style_segments = dedupe_preserve_order(style_bias[:3] + style_goal[:3])
    segments = style_segments[:]
    if not segments and has_letters(goal):
        segments.append(goal)
    segments.extend(preferred_phrases[:2])
    segments.extend(diagnosis_guidance.get("prompt_cues", [])[:2])
    segments.extend(quality_cues[:2])
    return segments


def strip_request_lead(text: str) -> str:
    normalized = normalize_prompt_text(text)
    normalized = re.sub(r"^\s*(create|make|generate)\b\s*", "", normalized, flags=re.I)
    normalized = re.sub(r"^\s*(turn|convert)\b.+?\binto\b\s*", "", normalized, flags=re.I)
    return normalize_prompt_text(normalized)


def build_text_segments(task: dict, solution_plan: dict, prompt_rules: dict):
    if current_revision_mode(task) == "colorway_only":
        segments = build_colorway_segments(task, solution_plan, prompt_rules)
        memory_guidance = build_memory_guidance(task)
        diagnosis_guidance = build_diagnosis_prompt_guidance(task)
        return segments, memory_guidance, diagnosis_guidance

    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    strict_english = normalize_prompt_policy(task.get("prompt_policy")) == PROMPT_POLICY_ENGLISH_ONLY
    memory_guidance = build_memory_guidance(task)
    diagnosis_guidance = build_diagnosis_prompt_guidance(task)

    goal = translate_cn_fragment_to_en(
        brief.get("goal") or task.get("goal") or "",
        strict=strict_english and bool(str(brief.get("goal") or task.get("goal") or "").strip()),
        field_label="goal",
    )
    if not has_letters(goal):
        goal = infer_goal_fallback(task)

    must_have = translate_list(brief.get("must_have"), strict=strict_english, field_label="must_have")
    style_bias = translate_list(brief.get("style_bias"), strict=strict_english, field_label="style_bias")
    must_not_have = translate_list(brief.get("must_not_have"), strict=strict_english, field_label="must_not_have")
    style_goal = translate_list(task_model.get("style_goal"), strict=False, field_label="style_goal")
    composition_goal = translate_list(task_model.get("composition_goal"), strict=False, field_label="composition_goal")
    consistency_goal = translate_list(task_model.get("consistency_goal"), strict=False, field_label="consistency_goal")
    feedback_points = translate_list(extract_feedback_points(task), strict=False, field_label="feedback")

    overrides = prompt_rules.get("task_overrides") if isinstance(prompt_rules.get("task_overrides"), dict) else {}
    task_override = overrides.get(current_task_type(task)) if isinstance(overrides.get(current_task_type(task)), dict) else {}
    preferred_phrases = normalize_string_list(task_override.get("preferred_phrases"))
    segment_policy = str(task_override.get("segment_policy") or "").strip()
    quality_target = str(solution_plan.get("quality_target") or "").strip()
    quality_cues = QUALITY_CUES.get(quality_target, [])
    reference_role = str(task_model.get("reference_role") or "").strip()
    reference_cues = REFERENCE_ROLE_CUES.get(reference_role, [])

    avoid_terms = dedupe_preserve_order(
        must_not_have + list(memory_guidance.get("taboo_terms") or [])
    )
    recommended_capabilities = normalize_string_list(solution_plan.get("recommended_capabilities"))
    if segment_policy == "edit_selected_region":
        segments = build_image_edit_segments(
            goal,
            must_have,
            style_goal,
            style_bias,
            preferred_phrases,
            diagnosis_guidance,
            quality_cues,
            recommended_capabilities,
        )
    elif segment_policy == "video_motion_only":
        segments = build_video_generation_segments(
            goal,
            must_have,
            preferred_phrases,
            diagnosis_guidance,
            quality_cues,
        )
    elif segment_policy == "style_system_distill":
        segments = build_style_system_segments(
            goal,
            style_goal,
            style_bias,
            preferred_phrases,
            diagnosis_guidance,
            quality_cues,
        )
    else:
        segments = build_generic_segments(
            goal,
            must_have,
            composition_goal,
            style_goal,
            style_bias,
            preferred_phrases,
            reference_cues,
            memory_guidance,
            consistency_goal,
            feedback_points,
            diagnosis_guidance,
            quality_cues,
            avoid_terms,
        )

    return (
        dedupe_preserve_order([segment for segment in segments if str(segment).strip()]),
        memory_guidance,
        diagnosis_guidance,
    )


def select_parameter_strategy(task: dict, solution_plan: dict, prompt_rules: dict):
    parameter_payload = load_asset(PARAMETER_PRESETS_PATH)
    plan = solution_plan.get("parameter_strategy") if isinstance(solution_plan.get("parameter_strategy"), dict) else {}
    parameters = normalize_string_list(plan.get("parameters"))
    optional_parameters = normalize_string_list(plan.get("optional_parameters"))

    task_override = (
        prompt_rules.get("task_overrides", {}).get(current_task_type(task), {})
        if isinstance(prompt_rules.get("task_overrides"), dict)
        else {}
    )
    revision_override = get_revision_override(prompt_rules, current_revision_mode(task))
    preferred_parameters = normalize_string_list(task_override.get("preferred_parameters"))
    for parameter in normalize_string_list(revision_override.get("preferred_parameters")):
        if parameter not in preferred_parameters:
            preferred_parameters.append(parameter)
    for parameter in preferred_parameters:
        if parameter not in parameters:
            parameters.append(parameter)

    compatibility_warnings = normalize_string_list(plan.get("compatibility_warnings"))
    compatibility_warnings.extend(normalize_string_list(parameter_payload.get("compatibility_warnings")))

    return {
        "parameters": dedupe_preserve_order(parameters),
        "optional_parameters": dedupe_preserve_order(optional_parameters),
        "avoid_parameters": normalize_string_list(plan.get("avoid_parameters")),
        "compatibility_warnings": dedupe_preserve_order(compatibility_warnings),
    }


def build_reference_bundle(task: dict, solution_plan: dict):
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    revision_mode = current_revision_mode(task)
    accepted_base_reference = get_accepted_base_reference(task, solution_plan)
    bundle = []
    for capability in normalize_string_list(solution_plan.get("recommended_capabilities")):
        if capability not in {"image_prompt", "style_reference", "omni_reference", "moodboard", "personalization"}:
            continue
        role = ""
        if capability == "style_reference":
            role = "style"
        elif capability == "omni_reference":
            role = "subject"
        elif capability == "image_prompt":
            role = "composition"
        elif capability == "moodboard":
            role = "project_direction"
        elif capability == "personalization":
            role = "personal_bias"
        bundle.append(
            {
                "capability": capability,
                "role": role,
                "required": capability in {"style_reference", "omni_reference"} and current_task_type(task)
                in {"continuity_batch", "reference_driven", "poster", "brand_visual_direction"}
                or (revision_mode == "colorway_only" and capability == "omni_reference"),
                "reference_role": str(task_model.get("reference_role") or "").strip(),
                "reference_path": accepted_base_reference if capability == "omni_reference" and accepted_base_reference else "",
            }
        )
    return bundle


def build_capability_notes(task: dict, solution_plan: dict):
    notes = []
    recommended = normalize_string_list(solution_plan.get("recommended_capabilities"))
    if "draft_mode" in recommended and current_stage(task) == "explore":
        notes.append("如果这一轮只是快速试方向，可先用 Draft Mode 或 `--draft`；挑到可行方向后再 Enhance 或正常质量重跑。")
    if "conversational_mode" in recommended:
        notes.append("如果当前创意还很模糊，可先用 Conversational Mode 把想法聊成方向；但正式执行前仍要落回可复核的最终 prompt。")
    if "style_explorer" in recommended:
        notes.append("如果只是先找现成风格码，优先用 Style Explorer 搜和试 `sref`，确认方向后再决定是否进入 Style Creator。")
    if "style_creator" in recommended:
        notes.append("如果目标是沉淀长期风格码，优先用 Style Creator；通常 5–10 轮开始趋稳，超过 15 轮收益会明显变小。")
    if "editor" in recommended:
        notes.append("如果只是局部修正或扩画面，不要整轮重跑，优先切到 Editor 链。")
    if "vary_region" in recommended:
        notes.append("局部重绘时只描述选区里要改的内容，不要把整轮新目标都塞进局部编辑 prompt。")
    if "pan_zoom" in recommended:
        notes.append("需要补边或拉远镜头时，优先 Pan / Zoom Out，而不是直接重写整轮 prompt。")
    if "smart_select" in recommended:
        notes.append("选区边界复杂时优先 Smart Select；先把遮罩应用干净，再提交编辑。")
    if "layers" in recommended:
        notes.append("要叠外部素材时先用 Layers 摆位；图层提交后会压平，不要把它当长期多层工程文件。")
    if "retexture" in recommended:
        notes.append("如果结构已经对了但材质或画风不对，优先 Retexture，而不是把整轮主体重新跑掉。")
    if "text_generation" in recommended:
        notes.append("图中文字请用双引号包住短词或短句；不要把 Midjourney 当成长文排版工具。")
    if "video_generation" in recommended:
        notes.append("视频链只接受 Starting Frame + 可选短文本，参数只用 `--motion`、`--raw`、`--loop`、`--end`、`--bs`。")
        notes.append("视频生成时，原始静态图里的旧参数会被自动移除，不要指望直接继承整套图片链参数。")
    if "repeat_batch" in recommended:
        notes.append("需要并行多组方向时再用 `--repeat`；它只在 Fast / Turbo 生效，而且会很快消耗 GPU。")
    if "seed_lock" in recommended:
        notes.append("如果这一轮是实验对比，可以锁 `Seed` 做 A/B；但不要把它当角色一致性工具，也不要在 Turbo 上承诺稳定复现。")
    return dedupe_preserve_order(notes)


def build_submission_notes(task: dict, solution_plan: dict, parameter_strategy: dict, diagnosis_guidance: dict):
    notes = [
        "先按当前 execution prompt 原样提交，不要同时新增平台侧变量。",
        "如果没有对应参考图，就先不要硬上需要图像输入的参考能力。",
    ]
    revision_mode = current_revision_mode(task)
    if revision_mode == "colorway_only":
        notes.append("当前轮次是配色任务：只允许提交 1 个配色变体，出结果后立即停。")
        notes.append("这一轮不允许顺手改脸、发型、版型、服装分区和材质关系。")
    if parameter_strategy["parameters"]:
        notes.append("当前已纳入执行的参数：" + " ".join(parameter_strategy["parameters"]))
    if parameter_strategy["optional_parameters"]:
        notes.append("可选强化参数：" + " ".join(parameter_strategy["optional_parameters"]))
    for warning in parameter_strategy["compatibility_warnings"][:3]:
        notes.append("参数兼容提醒：" + warning)
    if current_stage(task) == "explore":
        notes.append("这一轮先验证方向，不要过早追求最终成品。")
    elif current_stage(task) == "finalize":
        notes.append("这一轮只做交付级收尾，不要再重新发散方向。")
    else:
        notes.append("这一轮只改关键问题，避免同时推翻主体和风格。")
    strategy = str(solution_plan.get("reference_strategy") or "").strip()
    if strategy:
        notes.append("参考策略：" + strategy)
    open_questions = normalize_string_list(((task.get("task_model") or {}).get("open_questions")))
    if "video_starting_frame_implicit" in open_questions:
        notes.append("当前还缺起始帧锚点；先确认用哪一张图做 Starting Frame，再提交视频链。")
    diagnosis_summary = diagnosis_guidance.get("summary") if isinstance(diagnosis_guidance, dict) else {}
    keep_list = normalize_string_list(diagnosis_summary.get("keep_list"))
    change_list = normalize_string_list(diagnosis_summary.get("change_list"))
    next_round_goal = str(diagnosis_summary.get("next_round_goal") or "").strip()
    next_round_strategy = str(diagnosis_summary.get("next_round_strategy") or "").strip()
    if keep_list:
        notes.append("本轮先保留这些已正确的点：" + "、".join(keep_list))
    if change_list:
        notes.append("本轮只验证这些修改是否落到图上：" + "、".join(change_list))
    if next_round_goal:
        notes.append("本轮目标：" + next_round_goal)
    if next_round_strategy:
        notes.append("本轮策略：" + next_round_strategy)
    notes.extend(build_capability_notes(task, solution_plan))
    return dedupe_preserve_order(notes)


def build_result_focus(task: dict):
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    focus = normalize_string_list(task_model.get("evaluation_focus"))
    diagnosis_guidance = build_diagnosis_prompt_guidance(task)
    diagnosis_focus = normalize_string_list(diagnosis_guidance.get("review_focus"))
    solution_plan = task.get("solution_plan") if isinstance(task.get("solution_plan"), dict) else {}
    recommended = normalize_string_list(solution_plan.get("recommended_capabilities"))
    if "text_generation" in recommended:
        focus.append("text_legibility")
    if "video_generation" in recommended:
        focus.extend(["motion_coherence", "frame_transition"])
    if "retexture" in recommended:
        focus.append("style_retarget_accuracy")
    if "smart_select" in recommended or "vary_region" in recommended:
        focus.append("edit_boundary_coherence")
    if "layers" in recommended:
        focus.append("layer_integration")
    if current_revision_mode(task) == "colorway_only":
        focus.extend(["palette_readability", "structure_retention"])
    if focus or diagnosis_focus:
        return dedupe_preserve_order(focus + diagnosis_focus)
    return ["subject", "style", "composition", "usability"]


def contains_internal_process_terms(prompt_text: str) -> bool:
    lowered = str(prompt_text or "").lower()
    return any(term.lower() in lowered for term in INTERNAL_PROCESS_TERMS)


def assemble_execution_prompt(segments, parameter_bundle):
    text_prompt = normalize_prompt_text(", ".join(segment for segment in segments if segment))
    prompt = text_prompt
    if parameter_bundle:
        prompt = f"{text_prompt} {' '.join(parameter_bundle)}".strip()
    return normalize_prompt_text(prompt)


def build_prompt_package(task: dict, force_regenerate: bool = False):
    if not isinstance(task.get("task_model"), dict):
        task, _ = classify_task(task)
    if not isinstance(task.get("solution_plan"), dict):
        task, _ = build_solution_plan(task)

    existing_prompt = str(task.get("current_prompt") or "").strip()
    prompt_version = max(1, int(task.get("prompt_version") or 1))
    prompt_rules = load_asset(PROMPT_RULES_PATH)
    solution_plan = task.get("solution_plan") if isinstance(task.get("solution_plan"), dict) else {}
    readiness = solution_plan.get("readiness") if isinstance(solution_plan.get("readiness"), dict) else {}
    if not readiness.get("ready", True):
        blocked_reasons = normalize_string_list(readiness.get("blocked_reasons"))
        if "base_lock_missing" in blocked_reasons:
            raise ValueError("当前是配色任务，但还没有锁定基底图。")
    parameter_strategy = select_parameter_strategy(task, solution_plan, prompt_rules)
    parameter_bundle = parameter_strategy["parameters"]

    must_regenerate = force_regenerate or not existing_prompt
    if normalize_prompt_policy(task.get("prompt_policy")) == PROMPT_POLICY_ENGLISH_ONLY and not is_english_prompt_text(
        existing_prompt
    ):
        must_regenerate = True

    if must_regenerate:
        segments, memory_guidance, diagnosis_guidance = build_text_segments(task, solution_plan, prompt_rules)
        prompt_text = assemble_execution_prompt(segments, parameter_bundle)
        if contains_internal_process_terms(prompt_text):
            raise ValueError("execution prompt 含内部过程说明")
        validation = validate_execution_prompt(prompt_text)
        if not validation["ok"]:
            raise ValueError("execution prompt 不合规：" + "；".join(validation["issues"]))
        prompt_text = validation["normalized_prompt"]
        if existing_prompt and prompt_text != existing_prompt:
            prompt_version += 1
    else:
        prompt_text = existing_prompt
        memory_guidance = build_memory_guidance(task)
        diagnosis_guidance = build_diagnosis_prompt_guidance(task)
        validation = validate_execution_prompt(prompt_text)
        if not validation["ok"]:
            raise ValueError("execution prompt 不合规：" + "；".join(validation["issues"]))
        prompt_text = validation["normalized_prompt"]

    diagnosis_summary = diagnosis_guidance.get("summary") if isinstance(diagnosis_guidance, dict) else {}
    accepted_base_reference = get_accepted_base_reference(task, solution_plan)

    prompt_package = {
        "task_id": task.get("task_id", ""),
        "project_id": task.get("project_id", ""),
        "prompt_stage": current_stage(task),
        "prompt_policy": normalize_prompt_policy(task.get("prompt_policy")),
        "brief_summary": build_brief_summary(task),
        "feedback_summary": "、".join(extract_feedback_points(task)),
        "prompt_structure": normalize_string_list(solution_plan.get("prompt_structure")),
        "prompt_text": prompt_text,
        "parameter_bundle": parameter_bundle,
        "parameter_options": parameter_strategy["optional_parameters"],
        "accepted_base_reference": accepted_base_reference,
        "reference_bundle": build_reference_bundle(task, solution_plan),
        "submission_notes": build_submission_notes(task, solution_plan, parameter_strategy, diagnosis_guidance),
        "result_readback_focus": build_result_focus(task),
        "quality_target": str(solution_plan.get("quality_target") or "").strip(),
        "memory_guidance": memory_guidance,
        "diagnosis_summary": diagnosis_summary,
        "review_focus": normalize_string_list(diagnosis_guidance.get("review_focus")),
        "solution_summary": {
            "primary_strategy": str(solution_plan.get("primary_strategy") or "").strip(),
            "recommended_capabilities": normalize_string_list(solution_plan.get("recommended_capabilities")),
        },
    }

    updated_task = dict(task)
    updated_task["prompt_policy"] = normalize_prompt_policy(task.get("prompt_policy"))
    if updated_task["prompt_policy"] == PROMPT_POLICY_ENGLISH_ONLY:
        updated_task["prompt_language"] = "en"
    updated_task["current_prompt"] = prompt_text
    updated_task["prompt_version"] = prompt_version
    updated_task["prompt_stage"] = prompt_package["prompt_stage"]
    updated_task["prompt_package"] = prompt_package
    updated_task["task_phase"] = "prompt_selected"
    updated_task["updated_at"] = now_iso()
    return updated_task, prompt_package


def main():
    configure_stdout()
    args = parse_args()
    task = load_task(args)
    updated_task, prompt_package = build_prompt_package(task, force_regenerate=args.regenerate_prompt)
    result = {
        "ok": True,
        "task": updated_task,
        "prompt_package": prompt_package,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
