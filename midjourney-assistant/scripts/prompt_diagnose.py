import argparse
import json
import sys
from pathlib import Path

from common import (
    _text_contains_any,
    ASSET_ROOT,
    configure_stdout,
    normalize_string_list,
    normalize_subject_contract,
    now_iso,
    read_json_file,
    read_json_input,
)
from task_classify import classify_task


DIAGNOSIS_RULES_PATH = ASSET_ROOT / "diagnosis-rules.json"

ISSUE_KEYWORDS = {
    "subject_mismatch": ["主体", "角色", "人物", "产品", "subject", "gender", "age"],
    "style_drift": ["风格", "画风", "时尚", "电影感", "无畏契约", "style", "mood"],
    "composition_mismatch": ["全身", "半身", "近景", "远景", "正面", "站立", "构图", "composition", "full-body"],
    "clothing_material_error": ["服装", "材质", "面料", "护甲", "配饰", "outfit", "fabric", "material"],
    "consistency_weak": ["统一", "一致", "继续上一轮", "延续", "consistent", "continuity", "same character"],
    "proposal_variation_weak": ["提案", "方向", "太像", "差异", "proposal", "variation"],
    "commercial_finish_low": ["提案感", "商业", "成品", "干净", "commercial", "finish"],
    "reference_distortion": ["参考图", "按这张", "照这个", "reference", "retain"],
    "feedback_not_applied": ["改成", "换成", "调整", "保留", "去掉", "删掉", "feedback"],
    "palette_not_readable": ["配色", "颜色", "色板", "palette", "colorway"],
    "structure_drift": ["换人", "不像同一个人", "脸变了", "版型变了", "结构变了", "silhouette changed", "same face lost"],
    "base_lock_missing": ["base lock missing", "基底没锁", "没有基底", "先锁基底"],
    "colorway_axis_broken": ["一边换配色一边换人", "不是配色", "重画新人", "change only color failed"],
}


def parse_args():
    parser = argparse.ArgumentParser(description="生成 Midjourney diagnosis_report")
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
    raise ValueError("prompt_diagnose 输入必须是任务对象 JSON")


def load_rules():
    payload = read_json_file(DIAGNOSIS_RULES_PATH, default={})
    return payload if isinstance(payload, dict) else {}


def build_source_text(task: dict) -> str:
    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    parts = [
        str(task.get("raw_request") or ""),
        " ".join(normalize_string_list(latest_feedback.get("points"))),
        str(latest_feedback.get("raw_text") or latest_feedback.get("message") or ""),
        str(task.get("last_result_summary") or ""),
        str(task.get("last_run_verdict") or ""),
    ]
    return " ".join(part for part in parts if part).strip().lower()


def detect_subject_contract_issues(task: dict, text: str):
    subject_contract = normalize_subject_contract(
        task.get("subject_contract")
        or (task.get("task_model") or {}).get("subject_contract")
    )
    if not any(subject_contract.values()):
        return []

    issues = []
    if subject_contract.get("gender") == "male" and _text_contains_any(
        text,
        ["女性", "女的", "女人", "woman", "female", "girl"],
    ):
        issues.append("subject_mismatch")
    if subject_contract.get("gender") == "female" and _text_contains_any(
        text,
        ["男性", "男的", "男人", "man", "male", "boy"],
    ):
        issues.append("subject_mismatch")
    if subject_contract.get("count") == "single" and _text_contains_any(
        text,
        ["多人", "群像", "四个", "4个", "group", "multiple characters"],
    ):
        issues.append("subject_mismatch")
        issues.append("structure_drift")

    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    feedback_text = " ".join(
        [
            str(latest_feedback.get("raw_text") or ""),
            " ".join(normalize_string_list(latest_feedback.get("points"))),
        ]
    ).lower()
    if (
        _text_contains_any(feedback_text, ["不要女性", "不要多人", "no women", "no group"])
        and "subject_mismatch" in issues
        and "feedback_not_applied" not in issues
    ):
        issues.append("feedback_not_applied")
    return normalize_string_list(issues)


def select_issue_types(task: dict, text: str):
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    revision_mode = str(task_model.get("revision_mode") or "").strip()
    solution_plan = task.get("solution_plan") if isinstance(task.get("solution_plan"), dict) else {}
    readiness = solution_plan.get("readiness") if isinstance(solution_plan.get("readiness"), dict) else {}
    contract_issues = detect_subject_contract_issues(task, text)

    if revision_mode == "colorway_only":
        selected = list(contract_issues)
        if "base_lock_missing" in normalize_string_list(readiness.get("blocked_reasons")):
            selected.append("base_lock_missing")
        if any(keyword.lower() in text for keyword in ISSUE_KEYWORDS["structure_drift"]):
            selected.append("structure_drift")
        if any(keyword.lower() in text for keyword in ISSUE_KEYWORDS["palette_not_readable"]):
            selected.append("palette_not_readable")
        if any(keyword.lower() in text for keyword in ISSUE_KEYWORDS["colorway_axis_broken"]):
            selected.append("colorway_axis_broken")
        if selected:
            return normalize_string_list(selected)[:3]

    selected = list(contract_issues)
    for issue_type, keywords in ISSUE_KEYWORDS.items():
        if issue_type in {"palette_not_readable", "structure_drift", "base_lock_missing", "colorway_axis_broken"}:
            continue
        if any(keyword.lower() in text for keyword in keywords):
            selected.append(issue_type)
    if not selected and str(task.get("last_run_verdict") or "").strip() == "usable_but_iterate":
        selected = normalize_string_list(task_model.get("failure_modes"))[:2]
    return normalize_string_list(selected)[:3]


def build_keep_list(task: dict):
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    if str(task_model.get("revision_mode") or "").strip() == "colorway_only":
        return ["face", "hair", "silhouette", "garment_panels", "material_map"]
    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    points = normalize_string_list(latest_feedback.get("points"))
    return [point for point in points if "保留" in point][:3]


def build_change_list(task: dict):
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    if str(task_model.get("revision_mode") or "").strip() == "colorway_only":
        palette_request = task.get("palette_request") if isinstance(task.get("palette_request"), dict) else {}
        summary = str(palette_request.get("summary") or "").strip()
        if summary:
            return [summary]
        return ["只改配色分配"]
    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    return normalize_string_list(latest_feedback.get("points"))[:5]


def build_diagnosis_report(task: dict):
    if not isinstance(task.get("task_model"), dict):
        task, _ = classify_task(task)
    rules = load_rules()
    issue_rules = rules.get("issue_types") if isinstance(rules.get("issue_types"), dict) else {}
    text = build_source_text(task)
    issue_types = select_issue_types(task, text)

    observed_issues = []
    likely_causes = []
    next_round_prompt_delta = []
    next_round_strategy_bits = []

    for issue_type in issue_types:
        rule = issue_rules.get(issue_type) if isinstance(issue_rules.get(issue_type), dict) else {}
        observed_issues.append(issue_type)
        likely_causes.extend(normalize_string_list(rule.get("likely_causes")))
        next_round_prompt_delta.extend(normalize_string_list(rule.get("prompt_delta_patterns")))
        next_round_strategy_bits.extend(normalize_string_list(rule.get("priority_fixes")))

    change_list = build_change_list(task)
    keep_list = build_keep_list(task)
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    revision_mode = str(task_model.get("revision_mode") or "").strip()
    if revision_mode == "colorway_only":
        next_round_goal = change_list[0] if change_list else "change only the palette assignment on the locked base"
    else:
        next_round_goal = change_list[0] if change_list else ("stabilize the current direction" if issue_types else "")

    diagnosis_report = {
        "observed_issues": normalize_string_list(observed_issues),
        "likely_causes": normalize_string_list(likely_causes),
        "keep_list": normalize_string_list(keep_list),
        "change_list": normalize_string_list(change_list),
        "next_round_goal": next_round_goal,
        "next_round_strategy": "；".join(normalize_string_list(next_round_strategy_bits))[:240],
        "next_round_prompt_delta": normalize_string_list(next_round_prompt_delta),
        "diagnosed_at": now_iso(),
    }

    updated_task = dict(task)
    updated_task["diagnosis_report"] = diagnosis_report
    updated_task["updated_at"] = now_iso()
    return updated_task, diagnosis_report


def main():
    configure_stdout()
    args = parse_args()
    task = load_task(args)
    updated_task, diagnosis_report = build_diagnosis_report(task)
    result = {
        "ok": True,
        "task": updated_task,
        "diagnosis_report": diagnosis_report,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
