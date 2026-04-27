import argparse
import json
import re
import sys
from pathlib import Path

from common import (
    configure_stdout,
    normalize_string_list,
    normalize_subject_contract,
    now_iso,
    project_memory_path,
    read_json_file,
    read_json_input,
    read_text,
    write_text,
)
from manual_mode_prepare import build_brief_summary


def parse_args():
    parser = argparse.ArgumentParser(description="合并或写回 Midjourney 项目上下文")
    parser.add_argument("--task-file", help="统一任务对象文件路径")
    parser.add_argument("--input-file", help="输入 JSON 文件路径")
    parser.add_argument("--writeback", action="store_true", help="把当前任务状态写回项目记忆")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def empty_context(project_id: str):
    return {
        "project_id": project_id,
        "project_stage": "",
        "workflow_status": "",
        "active_batch_label": "",
        "latest_goal": "",
        "brief_summary": "",
        "latest_prompt": "",
        "prompt_version": 0,
        "latest_mode": "",
        "latest_task_phase": "",
        "last_run_verdict": "",
        "last_result_summary": "",
        "next_action": "",
        "round_index": 0,
        "completed_rounds": 0,
        "persistent_must_have": [],
        "persistent_style_bias": [],
        "persistent_must_not_have": [],
        "consistency_rules": [],
        "latest_revision_mode": "",
        "design_lock_state": "",
        "accepted_base_reference": "",
        "locked_elements": [],
        "subject_contract": {},
        "accepted_palette_history": [],
        "open_items": [],
        "template_candidate_keys": [],
        "updated_at": "",
        "recent_rounds": [],
    }


def append_unique(items, value):
    values = normalize_string_list(items)
    normalized = str(value or "").strip()
    if normalized and normalized not in values:
        values.append(normalized)
    return values


def normalize_round_entries(values):
    results = []
    if not isinstance(values, list):
        return results
    for item in values:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "round_index": max(1, int(item.get("round_index") or 1)),
                "prompt_version": max(1, int(item.get("prompt_version") or 1)),
                "mode": str(item.get("mode") or "").strip(),
                "task_phase": str(item.get("task_phase") or "").strip(),
                "run_verdict": str(item.get("run_verdict") or "").strip(),
                "result_summary": str(item.get("result_summary") or "").strip(),
                "next_action": str(item.get("next_action") or "").strip(),
                "updated_at": str(item.get("updated_at") or "").strip(),
            }
        )
    return results


def normalize_context(context: dict, project_id: str):
    normalized = empty_context(project_id)
    normalized.update(context or {})
    normalized["project_id"] = project_id
    normalized["prompt_version"] = max(0, int(normalized.get("prompt_version") or 0))
    normalized["round_index"] = max(0, int(normalized.get("round_index") or 0))
    normalized["completed_rounds"] = max(0, int(normalized.get("completed_rounds") or 0))
    normalized["persistent_must_have"] = normalize_string_list(normalized.get("persistent_must_have"))
    normalized["persistent_style_bias"] = normalize_string_list(normalized.get("persistent_style_bias"))
    normalized["persistent_must_not_have"] = normalize_string_list(normalized.get("persistent_must_not_have"))
    normalized["consistency_rules"] = normalize_string_list(normalized.get("consistency_rules"))
    normalized["latest_revision_mode"] = str(normalized.get("latest_revision_mode") or "").strip()
    normalized["design_lock_state"] = str(normalized.get("design_lock_state") or "").strip()
    normalized["accepted_base_reference"] = str(normalized.get("accepted_base_reference") or "").strip()
    normalized["locked_elements"] = normalize_string_list(normalized.get("locked_elements"))
    normalized["subject_contract"] = normalize_subject_contract(normalized.get("subject_contract"))
    normalized["accepted_palette_history"] = normalize_string_list(normalized.get("accepted_palette_history"))
    normalized["open_items"] = normalize_string_list(normalized.get("open_items"))
    normalized["template_candidate_keys"] = normalize_string_list(normalized.get("template_candidate_keys"))
    normalized["recent_rounds"] = normalize_round_entries(normalized.get("recent_rounds"))
    return normalized


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
    raise ValueError("项目上下文合并输入必须是任务对象 JSON")


def load_project_context(path: Path, project_id: str):
    context = empty_context(project_id)
    content = read_text(path, default="")
    if not content.strip():
        return context
    match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.S)
    if not match:
        return context
    parsed = read_json_input(match.group(1))
    if not isinstance(parsed, dict):
        return context
    return normalize_context(parsed, project_id)


def render_project_context(context: dict) -> str:
    lines = [
        "# 项目上下文",
        "",
        f"- project_id: {context.get('project_id', '')}",
        f"- project_stage: {context.get('project_stage', '')}",
        f"- workflow_status: {context.get('workflow_status', '')}",
        f"- active_batch_label: {context.get('active_batch_label', '')}",
        f"- latest_goal: {context.get('latest_goal', '')}",
        f"- latest_mode: {context.get('latest_mode', '')}",
        f"- latest_task_phase: {context.get('latest_task_phase', '')}",
        f"- last_run_verdict: {context.get('last_run_verdict', '')}",
        f"- next_action: {context.get('next_action', '')}",
        f"- latest_revision_mode: {context.get('latest_revision_mode', '')}",
        f"- design_lock_state: {context.get('design_lock_state', '')}",
        f"- accepted_base_reference: {context.get('accepted_base_reference', '')}",
        f"- updated_at: {context.get('updated_at', '')}",
        "",
        "## 结构化快照",
        "",
        "```json",
        json.dumps(context, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 最近轮次",
        "",
    ]
    rounds = context.get("recent_rounds") or []
    if rounds:
        for item in rounds:
            lines.append(
                "- round {round_index} | prompt_v{prompt_version} | {run_verdict} | {next_action} | {updated_at}".format(
                    round_index=item.get("round_index", ""),
                    prompt_version=item.get("prompt_version", ""),
                    run_verdict=item.get("run_verdict", ""),
                    next_action=item.get("next_action", ""),
                    updated_at=item.get("updated_at", ""),
                )
            )
    else:
        lines.append("- 暂无轮次记录")

    lines.extend(
        [
            "",
            "## 项目级规则",
            "",
        ]
    )
    if context.get("consistency_rules"):
        for item in context.get("consistency_rules") or []:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无项目级规则")
    return "\n".join(lines) + "\n"


def apply_persistent_strategy(brief: dict, context: dict):
    merged = dict(brief)
    merged["must_have"] = normalize_string_list(brief.get("must_have"))
    merged["style_bias"] = normalize_string_list(brief.get("style_bias"))
    merged["must_not_have"] = normalize_string_list(brief.get("must_not_have"))
    for value in normalize_string_list(context.get("persistent_must_have")):
        merged["must_have"] = append_unique(merged.get("must_have"), value)
    for value in normalize_string_list(context.get("persistent_style_bias")):
        merged["style_bias"] = append_unique(merged.get("style_bias"), value)
    for value in normalize_string_list(context.get("persistent_must_not_have")):
        merged["must_not_have"] = append_unique(merged.get("must_not_have"), value)
    return merged


def apply_context_to_task(task: dict, context: dict):
    updated = dict(task)
    snapshot = normalize_context(context, str(task.get("project_id") or "").strip())
    artifacts = dict(updated.get("artifacts") or {})
    artifacts["project_context"] = snapshot
    updated["artifacts"] = artifacts
    updated["project_context_snapshot"] = snapshot

    latest_prompt = str(snapshot.get("latest_prompt") or "").strip()
    if latest_prompt and not str(updated.get("current_prompt") or "").strip():
        updated["current_prompt"] = latest_prompt
        updated["prompt_version"] = max(
            int(updated.get("prompt_version") or 1),
            int(snapshot.get("prompt_version") or 1),
        )

    if not str(updated.get("last_result_summary") or "").strip():
        updated["last_result_summary"] = str(snapshot.get("last_result_summary") or "").strip()
    if not str(updated.get("last_run_verdict") or "").strip():
        updated["last_run_verdict"] = str(snapshot.get("last_run_verdict") or "").strip()
    if not str(updated.get("next_action") or "").strip():
        updated["next_action"] = str(snapshot.get("next_action") or "").strip()

    current_round = max(1, int(updated.get("round_index") or 1))
    snapshot_round = max(0, int(snapshot.get("round_index") or 0))
    if snapshot_round and current_round == 1 and not str(updated.get("last_run_verdict") or "").strip():
        updated["round_index"] = snapshot_round

    updated["brief"] = apply_persistent_strategy(updated.get("brief") or {}, snapshot)
    updated["project_stage"] = str(snapshot.get("project_stage") or updated.get("project_stage") or "").strip()
    updated["workflow_status"] = str(snapshot.get("workflow_status") or updated.get("workflow_status") or "").strip()
    updated["project_consistency_rules"] = normalize_string_list(snapshot.get("consistency_rules"))
    updated["subject_contract"] = normalize_subject_contract(
        updated.get("subject_contract") or snapshot.get("subject_contract")
    )
    updated["accepted_base_reference"] = str(
        updated.get("accepted_base_reference") or snapshot.get("accepted_base_reference") or ""
    ).strip()
    updated["design_lock_state"] = str(
        updated.get("design_lock_state") or snapshot.get("design_lock_state") or ""
    ).strip()
    updated["locked_elements"] = normalize_string_list(
        updated.get("locked_elements") or snapshot.get("locked_elements")
    )
    updated["updated_at"] = now_iso()
    return updated


def build_round_entry(task: dict):
    return {
        "round_index": max(1, int(task.get("round_index") or 1)),
        "prompt_version": max(1, int(task.get("prompt_version") or 1)),
        "mode": str(task.get("mode") or "").strip(),
        "task_phase": str(task.get("task_phase") or "").strip(),
        "run_verdict": str(task.get("last_run_verdict") or task.get("run_verdict") or "").strip(),
        "result_summary": str(task.get("last_result_summary") or task.get("result_summary") or "").strip(),
        "next_action": str(task.get("next_action") or "").strip(),
        "updated_at": str(task.get("updated_at") or now_iso()).strip(),
    }


def merge_round_history(existing_rounds, new_entry: dict):
    normalized = normalize_round_entries(existing_rounds)
    filtered = [
        item
        for item in normalized
        if not (
            item.get("round_index") == new_entry.get("round_index")
            and item.get("prompt_version") == new_entry.get("prompt_version")
        )
    ]
    filtered.append(new_entry)
    filtered.sort(key=lambda item: (int(item.get("round_index") or 0), int(item.get("prompt_version") or 0)))
    return filtered[-12:]


def infer_project_stage(task: dict):
    prompt_stage = str(task.get("prompt_stage") or "").strip()
    next_action = str(task.get("next_action") or "").strip()
    last_verdict = str(task.get("last_run_verdict") or task.get("run_verdict") or "").strip()
    round_index = max(1, int(task.get("round_index") or 1))
    if next_action == "finish_task" or prompt_stage == "finalize":
        return "finalize"
    if last_verdict == "success" and round_index >= 3:
        return "finalize"
    if round_index <= 1:
        return "explore"
    return "refine"


def infer_workflow_status(task: dict):
    last_verdict = str(task.get("last_run_verdict") or task.get("run_verdict") or "").strip()
    next_action = str(task.get("next_action") or "").strip()
    if next_action == "finish_task" and last_verdict == "success":
        return "ready_to_close"
    if last_verdict in {"blocked_by_ui", "blocked_by_context"}:
        return "blocked"
    return "active"


def derive_batch_label(task: dict):
    stage = infer_project_stage(task)
    round_index = max(1, int(task.get("round_index") or 1))
    return f"{stage}-round-{round_index}"


def merge_project_strategy(existing: dict, task: dict):
    strategy = {
        "persistent_must_have": normalize_string_list(existing.get("persistent_must_have")),
        "persistent_style_bias": normalize_string_list(existing.get("persistent_style_bias")),
        "persistent_must_not_have": normalize_string_list(existing.get("persistent_must_not_have")),
        "consistency_rules": normalize_string_list(existing.get("consistency_rules")),
    }
    patch = task.get("project_strategy_patch") if isinstance(task.get("project_strategy_patch"), dict) else {}
    for field in ["persistent_must_have", "persistent_style_bias", "persistent_must_not_have", "consistency_rules"]:
        for value in normalize_string_list(patch.get(field)):
            strategy[field] = append_unique(strategy[field], value)
    return strategy


def collect_template_candidate_keys(task: dict):
    values = []
    direct = normalize_string_list(task.get("template_candidate_keys"))
    values.extend(direct)
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    template_info = artifacts.get("template_candidate") if isinstance(artifacts.get("template_candidate"), dict) else {}
    candidate_key = str(template_info.get("candidate_key") or "").strip()
    if candidate_key:
        values = append_unique(values, candidate_key)
    return values


def build_open_items(task: dict):
    items = []
    next_action = str(task.get("next_action") or "").strip()
    if next_action and next_action not in {"finish_task", "await_user_feedback"}:
        items = append_unique(items, f"下一步动作：{next_action}")
    latest_feedback = task.get("latest_feedback") if isinstance(task.get("latest_feedback"), dict) else {}
    for point in normalize_string_list(latest_feedback.get("points")):
        items = append_unique(items, f"待验证反馈：{point}")
    return items


def build_latest_revision_mode(task: dict):
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    return str(
        revision_patch.get("revision_mode")
        or task_model.get("revision_mode")
        or task.get("requested_revision_mode")
        or ""
    ).strip()


def build_design_lock_state(task: dict, existing: dict):
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    for candidate in [
        revision_patch.get("design_lock_state"),
        task.get("design_lock_state"),
        task_model.get("lock_state"),
        existing.get("design_lock_state"),
    ]:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def build_accepted_base_reference(task: dict, existing: dict):
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    for candidate in [
        revision_patch.get("accepted_base_reference"),
        task.get("accepted_base_reference"),
        task_model.get("accepted_base_reference"),
        existing.get("accepted_base_reference"),
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


def build_locked_elements(task: dict, existing: dict):
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    values = []
    for source in [
        existing.get("locked_elements"),
        revision_patch.get("locked_elements"),
        task.get("locked_elements"),
        task_model.get("locked_elements"),
    ]:
        for value in normalize_string_list(source):
            values = append_unique(values, value)
    return values


def build_palette_history(task: dict, existing: dict):
    history = normalize_string_list(existing.get("accepted_palette_history"))
    palette_request = task.get("palette_request") if isinstance(task.get("palette_request"), dict) else {}
    revision_patch = task.get("revision_patch") if isinstance(task.get("revision_patch"), dict) else {}
    summary = str(
        palette_request.get("summary")
        or revision_patch.get("palette_request", {}).get("summary")
        or ""
    ).strip()
    if summary:
        history = append_unique(history, summary)
    return history


def build_context_from_task(task: dict, existing: dict):
    project_id = str(task.get("project_id") or "").strip()
    context = normalize_context(existing, project_id)
    strategy = merge_project_strategy(context, task)

    context["project_id"] = project_id
    context["project_stage"] = infer_project_stage(task)
    context["workflow_status"] = infer_workflow_status(task)
    context["active_batch_label"] = derive_batch_label(task)
    context["latest_goal"] = str(task.get("goal") or context.get("latest_goal") or "").strip()
    brief_summary = build_brief_summary(task)
    if brief_summary:
        context["brief_summary"] = brief_summary
    context["latest_prompt"] = str(task.get("current_prompt") or context.get("latest_prompt") or "").strip()
    context["prompt_version"] = max(int(context.get("prompt_version") or 0), int(task.get("prompt_version") or 1))
    context["latest_mode"] = str(task.get("mode") or context.get("latest_mode") or "").strip()
    context["latest_task_phase"] = str(task.get("task_phase") or context.get("latest_task_phase") or "").strip()
    context["last_run_verdict"] = str(
        task.get("last_run_verdict") or task.get("run_verdict") or context.get("last_run_verdict") or ""
    ).strip()
    context["last_result_summary"] = str(
        task.get("last_result_summary") or task.get("result_summary") or context.get("last_result_summary") or ""
    ).strip()
    context["next_action"] = str(task.get("next_action") or context.get("next_action") or "").strip()
    context["latest_revision_mode"] = build_latest_revision_mode(task)
    context["design_lock_state"] = build_design_lock_state(task, context)
    context["accepted_base_reference"] = build_accepted_base_reference(task, context)
    context["locked_elements"] = build_locked_elements(task, context)
    context["subject_contract"] = normalize_subject_contract(
        task.get("subject_contract") or context.get("subject_contract")
    )
    context["accepted_palette_history"] = build_palette_history(task, context)
    context["round_index"] = max(int(context.get("round_index") or 0), int(task.get("round_index") or 1))
    context["persistent_must_have"] = strategy["persistent_must_have"]
    context["persistent_style_bias"] = strategy["persistent_style_bias"]
    context["persistent_must_not_have"] = strategy["persistent_must_not_have"]
    context["consistency_rules"] = strategy["consistency_rules"]
    context["open_items"] = build_open_items(task)
    for candidate_key in collect_template_candidate_keys(task):
        context["template_candidate_keys"] = append_unique(context.get("template_candidate_keys"), candidate_key)
    context["updated_at"] = str(task.get("updated_at") or now_iso()).strip()
    context["recent_rounds"] = merge_round_history(context.get("recent_rounds"), build_round_entry(task))
    context["completed_rounds"] = sum(
        1 for item in context["recent_rounds"] if str(item.get("run_verdict") or "").strip() in {"success", "usable_but_iterate"}
    )
    return context


def main():
    configure_stdout()
    args = parse_args()
    task = load_task(args)
    project_id = str(task.get("project_id") or "").strip()

    if not project_id:
        result = {
            "ok": True,
            "applied": False,
            "reason": "no_project_id",
            "task": task,
            "project_context_snapshot": {},
        }
    else:
        target = project_memory_path(project_id)
        existing = load_project_context(target, project_id)
        if args.writeback:
            context = build_context_from_task(task, existing)
            write_text(target, render_project_context(context))
            updated_task = apply_context_to_task(task, context)
            result = {
                "ok": True,
                "applied": True,
                "writeback": True,
                "project_file": str(target),
                "task": updated_task,
                "project_context_snapshot": context,
            }
        else:
            updated_task = apply_context_to_task(task, existing)
            result = {
                "ok": True,
                "applied": bool(existing.get("updated_at") or existing.get("recent_rounds")),
                "writeback": False,
                "project_file": str(target),
                "task": updated_task,
                "project_context_snapshot": existing,
            }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
