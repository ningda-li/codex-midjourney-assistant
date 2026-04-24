import argparse
import json
import sys
from pathlib import Path

from common import ASSET_ROOT, configure_stdout, normalize_string_list, now_iso, read_json_file, read_json_input
from task_classify import classify_task, keyword_in_text


CAPABILITY_ROUTING_PATH = ASSET_ROOT / "capability-routing.json"
PARAMETER_PRESETS_PATH = ASSET_ROOT / "parameter-presets.json"
PROMPT_RULES_PATH = ASSET_ROOT / "prompt-composition-rules.json"


def parse_args():
    parser = argparse.ArgumentParser(description="生成 Midjourney solution_plan")
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
    raise ValueError("solution_plan_build 输入必须是任务对象 JSON")


def load_asset(path: Path):
    payload = read_json_file(path, default={})
    return payload if isinstance(payload, dict) else {}


def find_routing_rule(routing_payload: dict, task_type: str, task_stage: str):
    for item in routing_payload.get("routing_rules", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("task_type") or "").strip() != task_type:
            continue
        if str(item.get("task_stage") or "").strip() != task_stage:
            continue
        return item
    for item in routing_payload.get("routing_rules", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("task_type") or "").strip() == task_type:
            return item
    return {}


def select_parameter_preset(task_model: dict):
    task_type = str(task_model.get("task_type") or "").strip()
    task_stage = str(task_model.get("task_stage") or "").strip()
    revision_mode = str(task_model.get("revision_mode") or "").strip()
    if revision_mode == "colorway_only":
        return "colorway_locked"
    if task_type == "character_design":
        return "character_explore" if task_stage == "explore" else "character_sheet_clean"
    if task_type == "character_sheet":
        return "character_sheet_clean"
    if task_type == "poster":
        return "poster_converge"
    if task_type == "product_visual":
        return "product_clean"
    if task_type == "reference_driven":
        return "reference_driven_scene"
    if task_type == "image_edit":
        return "image_edit_local_fix"
    if task_type == "video_generation":
        return "video_clip_loop"
    if task_type == "style_system_build":
        return "style_system_distill"
    if task_stage == "finalize":
        return "final_delivery"
    return ""


def build_reference_strategy(task_model: dict, routing_rule: dict):
    task_type = str(task_model.get("task_type") or "").strip()
    reference_role = str(task_model.get("reference_role") or "").strip()
    revision_mode = str(task_model.get("revision_mode") or "").strip()
    if revision_mode == "colorway_only":
        return "treat the locked base design as the primary anchor, preserve face, silhouette, garment panels, and material map, then change only the palette assignment"
    if task_type == "continuity_batch":
        return "use omni_reference as the primary subject anchor and keep style support secondary"
    if task_type == "image_edit":
        return "keep the current image structure, change only the edited area, and avoid reopening the whole concept"
    if task_type == "video_generation":
        return "treat the starting frame as the anchor and avoid carrying image-chain references into the video route"
    if task_type == "style_system_build":
        return "separate style discovery from delivery prompts and distill reusable style codes instead of locking a single subject"
    if task_type == "reference_driven":
        if reference_role == "style":
            return "treat the reference as a style anchor instead of a subject lock"
        if reference_role == "composition":
            return "treat the reference as a composition anchor and keep subject language explicit"
        if reference_role == "subject":
            return "treat the reference as a subject anchor and keep style language controlled"
        return "reference exists but its role is not explicit; avoid mixing subject and style duties"
    strategy = str(routing_rule.get("reference_strategy") or "").strip()
    return strategy or "no primary reference strategy is required for this round"


def build_iteration_strategy(task_model: dict):
    task_stage = str(task_model.get("task_stage") or "").strip()
    revision_mode = str(task_model.get("revision_mode") or "").strip()
    if revision_mode == "colorway_only":
        return "freeze the approved design, test only one colorway variant this round, and stop after one readable palette result"
    if revision_mode == "finish_only":
        return "freeze subject and structure, then change only cleanliness, finish, and delivery polish"
    if task_stage == "explore":
        return "test one main direction axis first and avoid locking too many variables"
    if task_stage == "finalize":
        return "freeze subject and style, then adjust only delivery-level finish"
    return "keep validated elements and change only one or two high-impact deltas"


def build_quality_target(task_model: dict):
    task_type = str(task_model.get("task_type") or "").strip()
    task_stage = str(task_model.get("task_stage") or "").strip()
    revision_mode = str(task_model.get("revision_mode") or "").strip()
    if revision_mode == "colorway_only":
        return "colorway_readability"
    if task_stage == "finalize":
        return "final_delivery"
    if task_type == "image_edit":
        return "edit_integrity"
    if task_type == "video_generation":
        return "motion_proof"
    if task_type == "style_system_build":
        return "reusable_style_system"
    if task_type == "character_sheet":
        return "clean_design_sheet"
    if task_type == "product_visual":
        return "commercial_finish"
    if task_type in {"proposal_visual", "brand_visual_direction"}:
        return "direction_selection"
    return "usable_direction"


def build_prompt_structure(prompt_rules: dict, task_model: dict):
    task_type = str(task_model.get("task_type") or "").strip()
    revision_mode = str(task_model.get("revision_mode") or "").strip()
    revision_overrides = (
        prompt_rules.get("revision_mode_overrides")
        if isinstance(prompt_rules.get("revision_mode_overrides"), dict)
        else {}
    )
    revision_override = revision_overrides.get(revision_mode) if isinstance(revision_overrides.get(revision_mode), dict) else {}
    required_slots = normalize_string_list(revision_override.get("required_slots"))
    if required_slots:
        return required_slots
    overrides = prompt_rules.get("task_overrides") if isinstance(prompt_rules.get("task_overrides"), dict) else {}
    task_override = overrides.get(task_type) if isinstance(overrides.get(task_type), dict) else {}
    required_slots = normalize_string_list(task_override.get("required_slots"))
    if required_slots:
        return required_slots
    return normalize_string_list(prompt_rules.get("core_order"))


def build_source_text(task: dict) -> str:
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    parts = [
        str(task.get("raw_request") or ""),
        str(task.get("goal") or ""),
        str(brief.get("goal") or ""),
        " ".join(normalize_string_list(brief.get("must_have"))),
        " ".join(normalize_string_list(brief.get("style_bias"))),
        " ".join(normalize_string_list(brief.get("must_not_have"))),
        str(latest_feedback.get("raw_text") or ""),
    ]
    return "\n".join(part for part in parts if part).lower()


def append_unique(values, candidate: str):
    normalized = str(candidate or "").strip()
    if normalized and normalized not in values:
        values.append(normalized)


def get_project_context(task: dict):
    snapshot = task.get("project_context_snapshot")
    if isinstance(snapshot, dict):
        return snapshot
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    project_context = artifacts.get("project_context")
    return project_context if isinstance(project_context, dict) else {}


def get_accepted_base_reference(task: dict, task_model: dict) -> str:
    for candidate in [
        task_model.get("accepted_base_reference"),
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


def build_revision_readiness(task: dict, task_model: dict):
    revision_mode = str(task_model.get("revision_mode") or "").strip()
    accepted_base_reference = get_accepted_base_reference(task, task_model)
    lock_state = str(
        task_model.get("lock_state")
        or task.get("design_lock_state")
        or get_project_context(task).get("design_lock_state")
        or ""
    ).strip()
    blocked_reasons = []
    if revision_mode == "colorway_only" and not accepted_base_reference and lock_state != "hard_locked":
        blocked_reasons.append("base_lock_missing")
    return {
        "ready": not blocked_reasons,
        "blocked_reasons": blocked_reasons,
        "accepted_base_reference": accepted_base_reference,
        "lock_state": lock_state,
    }


def apply_capability_hints(task: dict, recommended_capabilities, blocked_capabilities):
    text = build_source_text(task)
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    task_stage = str(task_model.get("task_stage") or "").strip()

    if any(keyword_in_text(text, token) for token in ["文字", "字样", "标题", "招牌", "标语", "text", "logo", "sign"]):
        append_unique(recommended_capabilities, "text_generation")

    if any(keyword_in_text(text, token) for token in ["视频", "动画", "动起来", "loop", "ending frame", "motion", "起始帧", "终帧"]):
        append_unique(recommended_capabilities, "video_generation")
        append_unique(blocked_capabilities, "style_reference")
        append_unique(blocked_capabilities, "omni_reference")
        append_unique(blocked_capabilities, "image_prompt")

    if any(
        keyword_in_text(text, token)
        for token in ["局部", "擦除", "重绘", "修这个区域", "vary region", "erase", "inpaint", "editor", "编辑"]
    ):
        append_unique(recommended_capabilities, "editor")
        append_unique(recommended_capabilities, "vary_region")

    if any(keyword_in_text(text, token) for token in ["扩图", "补边", "拉远", "zoom out", "pan", "往外扩"]):
        append_unique(recommended_capabilities, "editor")
        append_unique(recommended_capabilities, "pan_zoom")

    if any(keyword_in_text(text, token) for token in ["retexture", "整体换风格", "整体换材质", "重贴图", "整体重做风格"]):
        append_unique(recommended_capabilities, "editor")
        append_unique(recommended_capabilities, "retexture")

    if any(keyword_in_text(text, token) for token in ["图层", "layers", "叠图", "摆素材"]):
        append_unique(recommended_capabilities, "editor")
        append_unique(recommended_capabilities, "layers")

    if any(keyword_in_text(text, token) for token in ["smart select", "智能选区", "选背景", "抠背景"]):
        append_unique(recommended_capabilities, "editor")
        append_unique(recommended_capabilities, "smart_select")

    if task_stage == "explore" and any(keyword_in_text(text, token) for token in ["草稿", "draft", "快速探索", "快速试", "先快跑"]):
        append_unique(recommended_capabilities, "draft_mode")

    if any(keyword_in_text(text, token) for token in ["对话式", "语音", "conversation", "conversational", "聊着做"]):
        append_unique(recommended_capabilities, "conversational_mode")

    if any(keyword_in_text(text, token) for token in ["style explorer", "找风格码", "搜风格码", "现成风格码", "style code browse"]):
        append_unique(recommended_capabilities, "style_explorer")

    if any(keyword_in_text(text, token) for token in ["风格码", "style creator", "style code", "sref code", "风格代码"]):
        append_unique(recommended_capabilities, "style_creator")

    if any(keyword_in_text(text, token) for token in ["多跑几组", "重复", "repeat", "多组方案", "多组方向"]):
        append_unique(recommended_capabilities, "repeat_batch")

    if any(keyword_in_text(text, token) for token in ["seed", "固定seed", "seed lock", "种子"]):
        append_unique(recommended_capabilities, "seed_lock")

    return normalize_string_list(recommended_capabilities), normalize_string_list(blocked_capabilities)


def build_solution_plan(task: dict):
    if not isinstance(task.get("task_model"), dict):
        task, _ = classify_task(task)
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    routing_payload = load_asset(CAPABILITY_ROUTING_PATH)
    parameter_payload = load_asset(PARAMETER_PRESETS_PATH)
    prompt_rules = load_asset(PROMPT_RULES_PATH)

    task_type = str(task_model.get("task_type") or "").strip()
    task_stage = str(task_model.get("task_stage") or "").strip()
    revision_mode = str(task_model.get("revision_mode") or "").strip()
    routing_rule = find_routing_rule(routing_payload, task_type, task_stage)
    revision_readiness = build_revision_readiness(task, task_model)

    recommended_capabilities = normalize_string_list(routing_rule.get("recommended_capabilities"))
    primary_strategy = str(routing_rule.get("primary_strategy") or "text_prompt").strip() or "text_prompt"
    if revision_mode == "colorway_only":
        primary_strategy = "omni_reference"
        if "omni_reference" not in recommended_capabilities:
            recommended_capabilities.insert(0, "omni_reference")
        if "text_prompt" not in recommended_capabilities:
            recommended_capabilities.append("text_prompt")
    if primary_strategy not in recommended_capabilities:
        recommended_capabilities.insert(0, primary_strategy)

    if normalize_string_list(task_model.get("consistency_goal")) and "omni_reference" not in recommended_capabilities:
        recommended_capabilities.append("omni_reference")
    if normalize_string_list(task_model.get("style_goal")) and task_type in {
        "poster",
        "fashion_material",
        "brand_visual_direction",
        "character_design",
    }:
        if "style_reference" not in recommended_capabilities:
            recommended_capabilities.append("style_reference")

    blocked_capabilities = normalize_string_list(routing_rule.get("blocked_capabilities"))
    if revision_mode == "colorway_only":
        append_unique(blocked_capabilities, "repeat_batch")
        append_unique(blocked_capabilities, "draft_mode")
        append_unique(blocked_capabilities, "weird_heavy")
    if task_stage != "finalize" and "run_as_hd" not in blocked_capabilities:
        blocked_capabilities.append("run_as_hd")
    recommended_capabilities, blocked_capabilities = apply_capability_hints(
        task,
        recommended_capabilities,
        blocked_capabilities,
    )

    preset_key = select_parameter_preset(task_model)
    preset = parameter_payload.get("preset_bundles", {}).get(preset_key, {}) if preset_key else {}
    parameter_strategy = {
        "preset_key": preset_key,
        "goal": str(preset.get("goal") or "").strip(),
        "parameters": normalize_string_list(preset.get("parameters")),
        "optional_parameters": normalize_string_list(preset.get("optional_parameters")),
        "avoid_parameters": normalize_string_list(preset.get("avoid_parameters")),
        "compatibility_warnings": normalize_string_list(parameter_payload.get("compatibility_warnings")),
    }

    solution_plan = {
        "primary_strategy": primary_strategy,
        "revision_mode": revision_mode,
        "change_axis": str(task_model.get("change_axis") or "").strip(),
        "lock_state": str(task_model.get("lock_state") or revision_readiness.get("lock_state") or "").strip(),
        "locked_elements": normalize_string_list(task_model.get("locked_elements")),
        "recommended_capabilities": normalize_string_list(recommended_capabilities),
        "blocked_capabilities": normalize_string_list(blocked_capabilities),
        "reference_strategy": build_reference_strategy(task_model, routing_rule),
        "parameter_strategy": parameter_strategy,
        "prompt_structure": build_prompt_structure(prompt_rules, task_model),
        "iteration_strategy": build_iteration_strategy(task_model),
        "quality_target": build_quality_target(task_model),
        "diagnosis_focus": normalize_string_list(task_model.get("failure_modes")),
        "readiness": revision_readiness,
        "built_at": now_iso(),
    }

    updated_task = dict(task)
    updated_task["solution_plan"] = solution_plan
    updated_task["task_phase"] = "solution_planned"
    updated_task["updated_at"] = now_iso()
    return updated_task, solution_plan


def main():
    configure_stdout()
    args = parse_args()
    task = load_task(args)
    updated_task, solution_plan = build_solution_plan(task)
    result = {
        "ok": True,
        "task": updated_task,
        "solution_plan": solution_plan,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
