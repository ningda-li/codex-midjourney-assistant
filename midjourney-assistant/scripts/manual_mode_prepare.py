import argparse
import json
import re
import sys
from pathlib import Path

from common import (
    PROMPT_POLICY_ENGLISH_ONLY,
    build_subject_prompt_segments,
    configure_stdout,
    is_english_prompt_text,
    load_prompt_terminology,
    normalize_prompt_policy,
    normalize_prompt_text,
    normalize_string_list,
    now_iso,
    read_json_file,
    read_json_input,
    validate_execution_prompt,
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

REQUEST_NOISE_PATTERNS = [
    re.compile(r"^\s*请?帮我", re.I),
    re.compile(r"^\s*我(?:想要|要)", re.I),
    re.compile(r"^\s*请", re.I),
    re.compile(r"\b帮我\b", re.I),
    re.compile(r"\b我想要\b", re.I),
    re.compile(r"\b我要\b", re.I),
    re.compile(r"\b生成(?:一个|一张|一套)?", re.I),
    re.compile(r"\b做(?:一个|一张|一套)?", re.I),
    re.compile(r"\b来(?:一个|一张|一套)?", re.I),
    re.compile(r"\b给我(?:一个|一张|一套)?", re.I),
    re.compile(r"(?:需要|要求|希望|带有|包含|具备)", re.I),
]

RELAXED_STRICT_FIELDS = {"goal", "feedback"}

SOFT_TRANSLATION_PATTERNS = [
    (re.compile(r"具体内容[^，。；;]*?(?:你自己去想|自由发挥|随意发挥|自行设计|你来设计|你看着办)"), "original details"),
    (re.compile(r"(?:你自己去想|自由发挥|随意发挥|自行设计|你来设计|你看着办)"), "original details"),
    (re.compile(r"现代男性游戏角色"), "modern male game character"),
    (re.compile(r"现代女性游戏角色"), "modern female game character"),
    (re.compile(r"现代男性角色"), "modern male character"),
    (re.compile(r"现代女性角色"), "modern female character"),
    (re.compile(r"游戏角色"), "game character"),
    (re.compile(r"服装(?:要|得|需)?(?:足够|比较|更)?时尚潮流"), "fashion-forward outfit"),
    (re.compile(r"时尚潮流(?:的)?服装"), "fashion-forward outfit"),
    (re.compile(r"潮流服装"), "fashion-forward outfit"),
    (re.compile(r"时尚潮流"), "fashion-forward"),
    (re.compile(r"现代"), "modern"),
]

SOFT_REMOVE_PATTERNS = [
    re.compile(r"具体内容"),
    re.compile(r"足够"),
    re.compile(r"比较"),
    re.compile(r"更"),
]


def parse_args():
    parser = argparse.ArgumentParser(description="生成 Midjourney 手动模式交付包")
    parser.add_argument("--task-file", help="统一任务对象文件路径")
    parser.add_argument("--input-file", help="输入 JSON 文件路径")
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
    raw = sys.stdin.read().strip()
    payload = read_json_input(raw)
    if isinstance(payload, dict):
        return payload
    raise ValueError("手动模式交付输入必须是任务对象 JSON")


def infer_stage(task: dict) -> str:
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    existing_package = task.get("prompt_package") if isinstance(task.get("prompt_package"), dict) else {}
    for candidate in [
        str(task_model.get("task_stage") or "").strip(),
        str(task.get("prompt_stage") or "").strip(),
        str(existing_package.get("prompt_stage") or "").strip(),
    ]:
        if candidate in {"explore", "converge", "finalize"}:
            return candidate
    round_index = max(1, int(task.get("round_index") or 1))
    round_budget = max(1, int(task.get("round_budget") or 1))
    if round_budget == 1 or round_index >= round_budget:
        return "finalize"
    if round_index == 1:
        return "explore"
    return "converge"


def extract_feedback_points(task: dict):
    latest_feedback = task.get("latest_feedback") or {}
    return normalize_string_list(latest_feedback.get("points"))


def build_diagnosis_summary(task: dict):
    existing_package = task.get("prompt_package") if isinstance(task.get("prompt_package"), dict) else {}
    diagnosis = (
        existing_package.get("diagnosis_summary")
        if isinstance(existing_package.get("diagnosis_summary"), dict)
        else task.get("diagnosis_report")
        if isinstance(task.get("diagnosis_report"), dict)
        else {}
    )
    return {
        "observed_issues": normalize_string_list(diagnosis.get("observed_issues")),
        "likely_causes": normalize_string_list(diagnosis.get("likely_causes")),
        "keep_list": normalize_string_list(diagnosis.get("keep_list")),
        "change_list": normalize_string_list(diagnosis.get("change_list")),
        "next_round_goal": str(diagnosis.get("next_round_goal") or "").strip(),
        "next_round_strategy": str(diagnosis.get("next_round_strategy") or "").strip(),
        "next_round_prompt_delta": normalize_string_list(diagnosis.get("next_round_prompt_delta")),
    }


def build_feedback_summary(task: dict, diagnosis_summary: dict) -> str:
    feedback_points = extract_feedback_points(task)
    if feedback_points:
        return "、".join(feedback_points)
    return "、".join(normalize_string_list(diagnosis_summary.get("change_list")))


def build_iteration_advice(stage: str, diagnosis_summary: dict):
    advice = []
    keep_list = normalize_string_list(diagnosis_summary.get("keep_list"))
    change_list = normalize_string_list(diagnosis_summary.get("change_list"))
    next_round_goal = str(diagnosis_summary.get("next_round_goal") or "").strip()
    next_round_strategy = str(diagnosis_summary.get("next_round_strategy") or "").strip()
    next_round_prompt_delta = normalize_string_list(diagnosis_summary.get("next_round_prompt_delta"))

    if keep_list:
        advice.append("保留：" + "、".join(keep_list))
    if change_list:
        advice.append("改动：" + "、".join(change_list))
    if next_round_goal:
        advice.append("本轮目标：" + next_round_goal)
    if next_round_strategy:
        advice.append("执行策略：" + next_round_strategy)
    if next_round_prompt_delta:
        advice.append("Prompt 调整重点：" + "、".join(next_round_prompt_delta))

    if not advice:
        if stage == "explore":
            advice.append("这轮先确认主体、风格和构图方向，再决定是否继续收敛。")
        elif stage == "converge":
            advice.append("这轮只围绕上一轮反馈继续收敛，不再同时改新的方向。")
        else:
            advice.append("这轮只做交付级收尾，优先判断是否已经足够定稿。")
    return advice


def build_consultant_summary(stage: str, diagnosis_summary: dict) -> str:
    change_list = normalize_string_list(diagnosis_summary.get("change_list"))
    next_round_goal = str(diagnosis_summary.get("next_round_goal") or "").strip()
    if change_list and next_round_goal:
        return f"我先按这轮反馈收敛，重点是：{next_round_goal}；你提交后优先看 {'、'.join(change_list)} 是否真正落地。"
    if change_list:
        return "我会把这轮修改收敛成可执行 prompt；你提交后优先看 " + "、".join(change_list) + " 是否落地。"
    if stage == "explore":
        return "我先把需求整理成可执行 prompt，首轮优先确认主体、风格和构图方向。"
    if stage == "converge":
        return "我会沿着上一轮结果继续收敛，避免同时改太多方向。"
    return "我会把这轮需求压到交付级修改，只保留最后一段必要收尾。"


def build_brief_summary(task: dict) -> str:
    brief = task.get("brief") or {}
    segments = []
    goal = str(brief.get("goal") or task.get("goal") or "").strip()
    if goal:
        segments.append(f"目标：{goal}")
    if brief.get("must_have"):
        segments.append("必须包含：" + "、".join(normalize_string_list(brief.get("must_have"))))
    if brief.get("style_bias"):
        segments.append("风格倾向：" + "、".join(normalize_string_list(brief.get("style_bias"))))
    if brief.get("must_not_have"):
        segments.append("避免：" + "、".join(normalize_string_list(brief.get("must_not_have"))))
    deliverable = str(brief.get("deliverable") or "").strip()
    if deliverable:
        segments.append(f"交付目标：{deliverable}")
    feedback_points = extract_feedback_points(task)
    if feedback_points:
        segments.append("本轮修改：" + "、".join(feedback_points))
    return "；".join(segments)


def normalize_english_fragment(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = value.replace("，", ", ").replace("。", ". ").replace("；", "; ").replace("：", ": ")
    value = value.replace("（", " ").replace("）", " ").replace("、", ", ")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*([,;:.])\s*", r"\1 ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,;:.")


def strip_request_noise(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    cleaned = value
    for pattern in REQUEST_NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"^[,，。；：:、\-\s]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def has_letters(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", str(text or "")))


def has_cjk_characters(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def dedupe_preserve_order(items):
    results = []
    seen = set()
    for item in items:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
    return results


def iter_terminology_pairs():
    terminology = load_prompt_terminology()
    phrases = terminology.get("phrases") if isinstance(terminology, dict) else {}
    if not isinstance(phrases, dict):
        return []
    return sorted(phrases.items(), key=lambda item: len(item[0]), reverse=True)


def apply_soft_cn_translation_fallbacks(text: str) -> str:
    translated = str(text or "")
    for pattern, target in SOFT_TRANSLATION_PATTERNS:
        translated = pattern.sub(f" {target} ", translated)
    for pattern in SOFT_REMOVE_PATTERNS:
        translated = pattern.sub(" ", translated)
    return translated


def cleanup_translated_fragment(text: str) -> str:
    translated = re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", " ", str(text or ""))
    translated = normalize_prompt_text(translated)
    translated = re.sub(r"\bcreate create\b", "create", translated, flags=re.I)
    translated = re.sub(r"\band and\b", "and", translated, flags=re.I)
    translated = re.sub(r"\boriginal details\b", "", translated, flags=re.I)
    translated = normalize_prompt_text(translated)
    return translated


def translate_cn_fragment_to_en(text: str, strict: bool = False, field_label: str = "约束") -> str:
    value = strip_request_noise(text)
    if not value:
        return ""
    if is_english_prompt_text(value):
        return normalize_prompt_text(value)

    for source, target in iter_terminology_pairs():
        value = re.sub(re.escape(source), f" {target} ", value)
    translated = apply_soft_cn_translation_fallbacks(value)

    if strict and has_cjk_characters(translated):
        relaxed_translated = cleanup_translated_fragment(translated)
        if field_label in RELAXED_STRICT_FIELDS and has_letters(relaxed_translated):
            translated = relaxed_translated
        else:
            raise ValueError(f"{field_label}存在未收录中文术语：{value}")
    else:
        translated = cleanup_translated_fragment(translated)

    if strict and (not has_letters(translated) or "?" in translated):
        raise ValueError(f"{field_label}翻译不完整：{value}")
    return translated


def infer_goal_fallback(task: dict) -> str:
    source = " ".join(
        [
            str(task.get("raw_request") or ""),
            str((task.get("brief") or {}).get("goal") or ""),
            str(task.get("goal") or ""),
        ]
    )
    if any(token in source for token in ["海报", "poster"]):
        return "poster concept"
    if any(token in source for token in ["猫咪", "猫", "cat"]):
        return "cat concept art"
    if any(token in source for token in ["角色", "人物", "立绘", "character"]):
        return "original character design"
    return "original visual concept"


def translate_list(values, strict: bool = False, field_label: str = "约束"):
    translated = []
    for value in normalize_string_list(values):
        english = translate_cn_fragment_to_en(value, strict=strict, field_label=field_label)
        if english and english not in translated:
            translated.append(english)
    return translated


def collect_memory_snapshot(task: dict):
    snapshot = task.get("memory_consumption_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def sanitize_memory_line(value: str) -> str:
    line = normalize_prompt_text(str(value or ""))
    if not line:
        return ""
    lowered = line.lower()
    if line.startswith("#") or line.startswith("```"):
        return ""
    if re.match(r'^"?[a-z_]+"?\s*:', line, flags=re.I):
        return ""
    if line.startswith("{") or line.startswith("}") or line.startswith("[") or line.startswith("]"):
        return ""
    if any(token in lowered for token in ["task_id", "brief_summary", "result_summary", "prompt_excerpt", "updated_at"]):
        return ""
    return line


def translate_memory_lines(values, field_label: str):
    translated = []
    warnings = []
    for value in normalize_string_list(values):
        if not value:
            continue
        english = translate_cn_fragment_to_en(value, strict=False, field_label=field_label)
        if english and has_letters(english):
            translated.append(english)
        elif has_cjk_characters(value):
            warnings.append(f"{field_label}含未收录术语，已跳过：{value}")
    return dedupe_preserve_order(translated), warnings


def translate_memory_lines_for_prompt(values, field_label: str):
    translated = []
    warnings = []
    for value in normalize_string_list(values):
        sanitized = sanitize_memory_line(value)
        if not sanitized:
            continue
        english = translate_cn_fragment_to_en(sanitized, strict=False, field_label=field_label)
        if english and has_letters(english):
            translated.append(english)
        elif has_cjk_characters(sanitized):
            warnings.append(f"{field_label} 含未收录术语，已跳过：{sanitized}")
    return dedupe_preserve_order(translated), warnings


def build_memory_guidance(task: dict):
    snapshot = collect_memory_snapshot(task)
    preferred_work_types, work_type_warnings = translate_memory_lines_for_prompt(
        snapshot.get("profile_work_types"), "用户画像工作类型"
    )
    preferred_style, style_warnings = translate_memory_lines_for_prompt(
        snapshot.get("profile_style_preferences"), "用户画像风格偏好"
    )
    preferred_content, content_warnings = translate_memory_lines_for_prompt(
        snapshot.get("profile_content_preferences"), "用户画像内容偏好"
    )
    taboo_terms, taboo_warnings = translate_memory_lines_for_prompt(
        snapshot.get("profile_taboos"), "用户画像禁忌"
    )
    project_hints, project_warnings = translate_memory_lines_for_prompt(
        snapshot.get("project_memory_lines"), "项目连续性记忆"
    )
    distilled_hints, distilled_warnings = translate_memory_lines_for_prompt(
        snapshot.get("distilled_pattern_lines"), "蒸馏经验"
    )
    site_notes, site_warnings = translate_memory_lines_for_prompt(
        snapshot.get("site_change_lines"), "站点变化记忆"
    )
    quality_tendency = translate_cn_fragment_to_en(
        snapshot.get("profile_quality_tendency"),
        strict=False,
        field_label="用户画像质量倾向",
    )

    submission_notes = []
    if site_notes:
        submission_notes.append("站点变化注意：" + "；".join(site_notes))
    if quality_tendency and has_letters(quality_tendency):
        submission_notes.append("质量倾向参考：" + quality_tendency)

    warnings = (
        work_type_warnings
        + style_warnings
        + content_warnings
        + taboo_warnings
        + project_warnings
        + distilled_warnings
        + site_warnings
    )

    return {
        "preferred_work_types": preferred_work_types,
        "preferred_style": preferred_style,
        "preferred_content": preferred_content,
        "taboo_terms": taboo_terms,
        "quality_tendency": quality_tendency if has_letters(quality_tendency) else "",
        "project_hints": project_hints,
        "distilled_hints": distilled_hints,
        "site_notes": site_notes,
        "visual_prompt_cues": dedupe_preserve_order(
            preferred_style + preferred_content + project_hints
        ),
        "submission_notes": dedupe_preserve_order(submission_notes),
        "warnings": dedupe_preserve_order(warnings),
    }


def build_prompt_text(task: dict, stage: str):
    brief = task.get("brief") or {}
    strict_english = normalize_prompt_policy(task.get("prompt_policy")) == PROMPT_POLICY_ENGLISH_ONLY
    memory_guidance = build_memory_guidance(task)
    diagnosis_summary = build_diagnosis_summary(task)
    subject_segments = build_subject_prompt_segments(task.get("subject_contract"))

    goal = translate_cn_fragment_to_en(
        brief.get("goal") or task.get("goal") or "",
        strict=strict_english and bool(str(brief.get("goal") or task.get("goal") or "").strip()),
        field_label="goal",
    )
    must_have = translate_list(brief.get("must_have"), strict=strict_english, field_label="must_have")
    style_bias = translate_list(brief.get("style_bias"), strict=strict_english, field_label="style_bias")
    must_not_have = translate_list(brief.get("must_not_have"), strict=strict_english, field_label="must_not_have")
    feedback_points = translate_list(extract_feedback_points(task), strict=strict_english, field_label="feedback")
    if not has_letters(goal):
        goal = infer_goal_fallback(task)

    segments = []
    segments.extend(subject_segments)
    if goal:
        segments.append(goal)
    segments.extend(dedupe_preserve_order(must_have))
    segments.extend(dedupe_preserve_order(style_bias))
    segments.extend(memory_guidance["visual_prompt_cues"])
    segments.extend(dedupe_preserve_order(feedback_points))
    segments.extend(translate_list(diagnosis_summary.get("next_round_prompt_delta"), strict=False, field_label="diagnosis_delta")[:3])

    avoid_terms = dedupe_preserve_order(must_not_have + memory_guidance["taboo_terms"])
    if avoid_terms:
        segments.append("avoid " + ", ".join(avoid_terms))

    prompt_text = normalize_prompt_text(", ".join(segment for segment in segments if segment))
    validation = validate_execution_prompt(prompt_text)
    if not validation["ok"]:
        raise ValueError("execution prompt 不合规：" + "；".join(validation["issues"]))
    return validation["normalized_prompt"], memory_guidance


def build_parameter_suggestions(task: dict, stage: str, diagnosis_summary: dict):
    goal = str((task.get("brief") or {}).get("goal") or task.get("goal") or "").strip()
    feedback_points = extract_feedback_points(task)
    existing_package = task.get("prompt_package") if isinstance(task.get("prompt_package"), dict) else {}
    parameter_bundle = normalize_string_list(existing_package.get("parameter_bundle"))
    parameter_options = normalize_string_list(existing_package.get("parameter_options"))
    suggestions = []
    if parameter_bundle:
        suggestions.append("当前已纳入执行的参数：" + " ".join(parameter_bundle))
    if parameter_options:
        suggestions.append("可选强化参数：" + " ".join(parameter_options))
    if stage == "explore":
        suggestions.extend(
            [
                "首轮先不要叠太多额外参数，优先确认主体、风格和构图方向。",
                "如果你已经明确要横版或竖版，再单独补充画幅要求。",
            ]
        )
    elif stage == "converge":
        suggestions.extend(
            [
                "本轮尽量只围绕这次修改继续收敛，不要同时再改新的方向。",
                "如果上一轮已经接近可用，只改一两个核心点。",
            ]
        )
    else:
        suggestions.extend(
            [
                "成品确认轮尽量冻结主体和风格描述，只做小修。",
                "如果已经接近最终稿，避免重写 prompt 前半段。",
            ]
        )

    if "海报" in goal:
        suggestions.append("如果目标是海报成品，提交时补上明确版式或横竖构图要求。")
    if "横版" in goal or "banner" in goal.lower():
        suggestions.append("如果目标是横版成图，记得补上明确横向画幅要求。")
    if feedback_points:
        suggestions.append("这一轮先验证这些修改有没有落到图上：" + "、".join(feedback_points))
    elif normalize_string_list(diagnosis_summary.get("change_list")):
        suggestions.append("这一轮先验证这些修改有没有落到图上：" + "、".join(diagnosis_summary.get("change_list")))
    next_round_strategy = str(diagnosis_summary.get("next_round_strategy") or "").strip()
    if next_round_strategy:
        suggestions.append("参数和提交节奏都要服务于这条策略：" + next_round_strategy)
    return suggestions


def build_submission_notes(stage: str, memory_guidance: dict, diagnosis_summary: dict):
    notes = [
        "先原样提交本轮英文 prompt，不要同时再改平台设置。",
        "如果平台已有个性化设置，先保持不变，避免这一轮同时引入多个变量。",
    ]
    if stage == "explore":
        notes.append("探索轮先看方向，不要一开始就追求最终成品。")
    elif stage == "converge":
        notes.append("收敛轮重点观察主体稳定性和构图是否已经可用。")
    else:
        notes.append("成品确认轮提交后，优先判断是否已经足够交付。")
    keep_list = normalize_string_list(diagnosis_summary.get("keep_list"))
    change_list = normalize_string_list(diagnosis_summary.get("change_list"))
    next_round_goal = str(diagnosis_summary.get("next_round_goal") or "").strip()
    next_round_strategy = str(diagnosis_summary.get("next_round_strategy") or "").strip()
    if keep_list:
        notes.append("先观察这些保留项有没有被破坏：" + "、".join(keep_list))
    if change_list:
        notes.append("再观察这些修改项有没有落地：" + "、".join(change_list))
    if next_round_goal:
        notes.append("本轮目标：" + next_round_goal)
    if next_round_strategy:
        notes.append("执行策略：" + next_round_strategy)
    notes.extend(memory_guidance.get("submission_notes") or [])
    return dedupe_preserve_order(notes)


def build_feedback_requirements(diagnosis_summary: dict):
    requirements = [
        "回传本轮生成结果截图。",
        "用一句话说明你最满意的点和最不满意的点。",
        "如果提交失败或页面报错，直接回传错误提示或错误截图。",
    ]
    keep_list = normalize_string_list(diagnosis_summary.get("keep_list"))
    change_list = normalize_string_list(diagnosis_summary.get("change_list"))
    if keep_list:
        requirements.append("回传时顺手说明这些保留项有没有被破坏：" + "、".join(keep_list))
    if change_list:
        requirements.append("回传时优先说明这些修改项有没有落地：" + "、".join(change_list))
    return dedupe_preserve_order(requirements)


def prepare_task_prompt(task: dict, force_regenerate: bool = False):
    stage = infer_stage(task)
    prompt_policy = normalize_prompt_policy(task.get("prompt_policy"))
    existing_prompt = str(task.get("current_prompt") or "").strip()
    existing_package = task.get("prompt_package") if isinstance(task.get("prompt_package"), dict) else {}
    prompt_version = max(1, int(task.get("prompt_version") or 1))
    prompt_text = existing_prompt
    diagnosis_summary = build_diagnosis_summary(task)
    memory_guidance = (
        existing_package.get("memory_guidance")
        if isinstance(existing_package.get("memory_guidance"), dict)
        else build_memory_guidance(task)
    )
    existing_validation = validate_execution_prompt(existing_prompt) if existing_prompt else {"ok": False}

    must_regenerate = force_regenerate or not existing_prompt
    if prompt_policy == PROMPT_POLICY_ENGLISH_ONLY and not is_english_prompt_text(existing_prompt):
        must_regenerate = True
    if existing_prompt and not existing_validation.get("ok"):
        must_regenerate = True

    if not must_regenerate and existing_package and str(existing_package.get("prompt_text") or "").strip():
        prompt_text = str(existing_package.get("prompt_text") or "").strip()
        validation = validate_execution_prompt(prompt_text)
        if not validation["ok"]:
            raise ValueError("execution prompt 不合规：" + "；".join(validation["issues"]))
        prompt_text = validation["normalized_prompt"]
    elif must_regenerate:
        prompt_text, memory_guidance = build_prompt_text(task, stage)
        if existing_prompt and prompt_text != existing_prompt:
            prompt_version += 1

    validation = validate_execution_prompt(prompt_text)
    if prompt_policy == PROMPT_POLICY_ENGLISH_ONLY and (
        not is_english_prompt_text(prompt_text) or not validation["ok"]
    ):
        raise ValueError("execution prompt 不合规：" + "；".join(validation["issues"]))
    prompt_text = validation["normalized_prompt"]

    package = dict(existing_package)
    package.update(
        {
            "task_id": task.get("task_id", ""),
            "project_id": task.get("project_id", ""),
            "prompt_stage": str(existing_package.get("prompt_stage") or stage).strip() or stage,
            "prompt_policy": prompt_policy,
            "subject_contract": task.get("subject_contract") or {},
            "accepted_base_reference": str(
                existing_package.get("accepted_base_reference") or task.get("accepted_base_reference") or ""
            ).strip(),
            "brief_summary": build_brief_summary(task),
            "feedback_summary": build_feedback_summary(task, diagnosis_summary),
            "consultant_summary": build_consultant_summary(stage, diagnosis_summary),
            "diagnosis_summary": diagnosis_summary,
            "iteration_advice": build_iteration_advice(stage, diagnosis_summary),
            "prompt_text": prompt_text,
            "memory_guidance": memory_guidance,
            "parameter_suggestions": build_parameter_suggestions(task, stage, diagnosis_summary),
            "submission_notes": dedupe_preserve_order(
                normalize_string_list(existing_package.get("submission_notes"))
                + build_submission_notes(stage, memory_guidance, diagnosis_summary)
            ),
            "feedback_requirements": build_feedback_requirements(diagnosis_summary),
        }
    )

    updated_task = dict(task)
    updated_task["prompt_policy"] = prompt_policy
    updated_task["prompt_language"] = "en" if prompt_policy == PROMPT_POLICY_ENGLISH_ONLY else str(
        task.get("prompt_language") or ""
    ).strip()
    updated_task["current_prompt"] = prompt_text
    updated_task["prompt_version"] = prompt_version
    updated_task["prompt_stage"] = package.get("prompt_stage", stage)
    updated_task["prompt_package"] = package
    updated_task["updated_at"] = now_iso()
    return updated_task, package


def main():
    configure_stdout()
    args = parse_args()
    task = load_task(args)
    updated_task, package = prepare_task_prompt(task, force_regenerate=args.regenerate_prompt)
    updated_task["mode"] = "manual"
    updated_task["task_phase"] = "manual_handoff"
    updated_task["next_action"] = "await_user_feedback"
    updated_task["should_continue"] = False
    artifacts = dict(updated_task.get("artifacts") or {})
    artifacts["manual_handoff"] = package
    updated_task["artifacts"] = artifacts
    result = {
        "ok": True,
        "orchestration_status": "manual_handoff_ready",
        "task": updated_task,
        "prompt_package": package,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
