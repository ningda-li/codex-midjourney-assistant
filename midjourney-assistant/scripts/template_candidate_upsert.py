import argparse
import json
import re
import sys
from pathlib import Path

from common import (
    REVIEW_QUEUE_PATH,
    TASK_PATTERNS_PATH,
    TASK_TEMPLATE_CANDIDATES_DIR,
    append_jsonl,
    configure_stdout,
    normalize_string_list,
    now_iso,
    read_json_file,
    read_json_input,
    read_text,
    slugify_project_id,
    write_text,
)


DEFAULT_THRESHOLD = 2


def parse_args():
    parser = argparse.ArgumentParser(description="更新任务模式统计并按阈值生成模板候选")
    parser.add_argument("--input-file", help="输入 run_record JSON 文件")
    parser.add_argument("--patterns-file", help="任务模式文件路径")
    parser.add_argument("--review-queue-file", help="review queue 路径")
    parser.add_argument("--candidate-dir", help="模板候选目录")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help="生成模板候选的最小累计次数")
    parser.add_argument("--output-file", help="输出 JSON 文件")
    return parser.parse_args()


def load_record(args):
    if args.input_file:
        return json.loads(Path(args.input_file).read_text(encoding="utf-8-sig"))
    raw = sys.stdin.read().strip()
    payload = read_json_input(raw)
    if not isinstance(payload, dict):
        raise ValueError("模板候选更新输入必须是 run_record JSON 对象")
    return payload


def default_snapshot():
    return {
        "updated_at": "",
        "patterns": [],
    }


def load_snapshot(path: Path):
    content = read_text(path, default="")
    if not content.strip():
        return default_snapshot()
    match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.S)
    if not match:
        return default_snapshot()
    payload = read_json_input(match.group(1))
    if not isinstance(payload, dict):
        return default_snapshot()
    patterns = payload.get("patterns")
    if not isinstance(patterns, list):
        payload["patterns"] = []
    return payload


def derive_work_types(record: dict):
    brief = record.get("brief") if isinstance(record.get("brief"), dict) else {}
    return normalize_string_list(brief.get("work_types"))


def derive_style_bias(record: dict):
    brief = record.get("brief") if isinstance(record.get("brief"), dict) else {}
    return normalize_string_list(brief.get("style_bias"))


def build_candidate_key(record: dict):
    work_types = derive_work_types(record)
    style_bias = derive_style_bias(record)
    backend = str(record.get("automatic_execution_backend") or "").strip() or "unknown_backend"
    prompt_policy = str(record.get("prompt_policy") or "").strip() or "unknown_prompt_policy"
    mode = str(record.get("mode") or "").strip() or "unknown_mode"
    key_parts = [
        mode,
        backend,
        prompt_policy,
        ",".join(work_types) or "unknown_work_type",
        ",".join(style_bias) or "unknown_style",
    ]
    return "|".join(key_parts)


def build_pattern_patch(record: dict, candidate_key: str):
    return {
        "candidate_key": candidate_key,
        "mode": str(record.get("mode") or "").strip(),
        "automatic_execution_backend": str(record.get("automatic_execution_backend") or "").strip(),
        "prompt_policy": str(record.get("prompt_policy") or "").strip(),
        "run_verdict": str(record.get("run_verdict") or "").strip(),
        "work_types": derive_work_types(record),
        "style_bias": derive_style_bias(record),
        "goal_examples": normalize_string_list([str(record.get("goal") or "").strip()]),
        "brief_summaries": normalize_string_list([str(record.get("brief_summary") or "").strip()]),
        "prompt_examples": normalize_string_list([str(record.get("current_prompt") or "").strip()[:240]]),
        "source_task_ids": normalize_string_list([str(record.get("task_id") or "").strip()]),
        "source_project_ids": normalize_string_list([str(record.get("project_id") or "").strip()]),
    }


def merge_pattern_entry(existing: dict, patch: dict):
    merged = dict(existing or {})
    merged.update(
        {
            "candidate_key": patch["candidate_key"],
            "mode": patch["mode"],
            "automatic_execution_backend": patch["automatic_execution_backend"],
            "prompt_policy": patch["prompt_policy"],
            "run_verdict": patch["run_verdict"],
            "updated_at": now_iso(),
        }
    )
    if not str(merged.get("first_seen_at") or "").strip():
        merged["first_seen_at"] = now_iso()
    merged["count"] = int(merged.get("count") or 0) + 1
    merged["work_types"] = normalize_string_list((merged.get("work_types") or []) + patch["work_types"])
    merged["style_bias"] = normalize_string_list((merged.get("style_bias") or []) + patch["style_bias"])
    merged["goal_examples"] = normalize_string_list((merged.get("goal_examples") or []) + patch["goal_examples"])[:5]
    merged["brief_summaries"] = normalize_string_list((merged.get("brief_summaries") or []) + patch["brief_summaries"])[:5]
    merged["prompt_examples"] = normalize_string_list((merged.get("prompt_examples") or []) + patch["prompt_examples"])[:5]
    merged["source_task_ids"] = normalize_string_list((merged.get("source_task_ids") or []) + patch["source_task_ids"])
    merged["source_project_ids"] = normalize_string_list((merged.get("source_project_ids") or []) + patch["source_project_ids"])
    return merged


def upsert_pattern(snapshot: dict, patch: dict):
    patterns = [item for item in snapshot.get("patterns", []) if isinstance(item, dict)]
    target_key = patch["candidate_key"]
    updated_entry = None
    remaining = []
    for item in patterns:
        if str(item.get("candidate_key") or "").strip() == target_key:
            updated_entry = merge_pattern_entry(item, patch)
        else:
            remaining.append(item)
    if updated_entry is None:
        updated_entry = merge_pattern_entry({}, patch)
    remaining.append(updated_entry)
    remaining.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("candidate_key") or "")))
    snapshot["patterns"] = remaining
    snapshot["updated_at"] = now_iso()
    return snapshot, updated_entry


def render_patterns(snapshot: dict):
    lines = [
        "# 任务模式",
        "",
        "## 结构化快照",
        "",
        "```json",
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 高频模式摘要",
        "",
    ]
    patterns = snapshot.get("patterns") or []
    if patterns:
        for item in patterns[:8]:
            work_types = " / ".join(item.get("work_types") or ["未标注类型"])
            style_bias = " / ".join(item.get("style_bias") or ["未标注风格"])
            lines.append(
                f"- {item.get('candidate_key', '')} | {item.get('count', 0)} 次 | {work_types} | {style_bias}"
            )
    else:
        lines.append("- 暂无任务模式")
    return "\n".join(lines) + "\n"


def candidate_file_path(candidate_dir: Path, candidate_key: str):
    return candidate_dir / f"{slugify_project_id(candidate_key)}.md"


def render_candidate(entry: dict, threshold: int):
    payload = {
        "candidate_key": entry.get("candidate_key", ""),
        "status": "pending_review",
        "threshold": threshold,
        "count": int(entry.get("count") or 0),
        "mode": entry.get("mode", ""),
        "automatic_execution_backend": entry.get("automatic_execution_backend", ""),
        "prompt_policy": entry.get("prompt_policy", ""),
        "work_types": entry.get("work_types") or [],
        "style_bias": entry.get("style_bias") or [],
        "source_task_ids": entry.get("source_task_ids") or [],
        "source_project_ids": entry.get("source_project_ids") or [],
        "updated_at": entry.get("updated_at", ""),
    }
    lines = [
        "# 任务模板候选",
        "",
        "## 结构化快照",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 推荐用途",
        "",
        f"- work_types: {' / '.join(entry.get('work_types') or ['未标注'])}",
        f"- style_bias: {' / '.join(entry.get('style_bias') or ['未标注'])}",
        f"- backend: {entry.get('automatic_execution_backend', '')}",
        f"- prompt_policy: {entry.get('prompt_policy', '')}",
        "",
        "## 样例 brief",
        "",
    ]
    brief_summaries = entry.get("brief_summaries") or []
    if brief_summaries:
        for item in brief_summaries[:3]:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无样例")
    lines.extend(
        [
            "",
            "## 样例 prompt",
            "",
        ]
    )
    prompt_examples = entry.get("prompt_examples") or []
    if prompt_examples:
        for item in prompt_examples[:3]:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无样例")
    return "\n".join(lines) + "\n"


def load_review_queue(path: Path):
    lines = read_text(path, default="").splitlines()
    records = []
    for line in lines:
        parsed = read_json_input(line)
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def queue_exists(records, candidate_key: str):
    for item in records:
        if str(item.get("kind") or "").strip() != "template_candidate":
            continue
        if str(item.get("candidate_key") or "").strip() == candidate_key and str(item.get("status") or "").strip() in {
            "pending_review",
            "approved",
        }:
            return True
    return False


def enqueue_candidate(path: Path, entry: dict, candidate_file: Path):
    record = {
        "queued_at": now_iso(),
        "kind": "template_candidate",
        "status": "pending_review",
        "candidate_key": str(entry.get("candidate_key") or "").strip(),
        "candidate_file": str(candidate_file),
        "source_task_id": (entry.get("source_task_ids") or [""])[0],
        "source_project_id": (entry.get("source_project_ids") or [""])[0],
    }
    append_jsonl(path, record)
    return record


def upsert_template_candidate(record: dict, threshold: int, patterns_file: Path, review_queue_file: Path, candidate_dir: Path):
    snapshot = load_snapshot(patterns_file)
    candidate_key = build_candidate_key(record)
    patch = build_pattern_patch(record, candidate_key)
    snapshot, entry = upsert_pattern(snapshot, patch)
    write_text(patterns_file, render_patterns(snapshot))

    candidate_file = candidate_file_path(candidate_dir, candidate_key)
    candidate_generated = False
    queue_record = None
    if int(entry.get("count") or 0) >= max(1, threshold):
        write_text(candidate_file, render_candidate(entry, threshold))
        candidate_generated = True
        existing_queue = load_review_queue(review_queue_file)
        if not queue_exists(existing_queue, candidate_key):
            queue_record = enqueue_candidate(review_queue_file, entry, candidate_file)

    return {
        "ok": True,
        "candidate_key": candidate_key,
        "pattern_count": int(entry.get("count") or 0),
        "patterns_file": str(patterns_file),
        "candidate_generated": candidate_generated,
        "candidate_file": str(candidate_file) if candidate_generated else "",
        "review_queue_updated": bool(queue_record),
        "review_queue_record": queue_record or {},
    }


def main():
    configure_stdout()
    args = parse_args()
    record = load_record(args)
    result = upsert_template_candidate(
        record=record,
        threshold=max(1, int(args.threshold or DEFAULT_THRESHOLD)),
        patterns_file=Path(args.patterns_file) if args.patterns_file else TASK_PATTERNS_PATH,
        review_queue_file=Path(args.review_queue_file) if args.review_queue_file else REVIEW_QUEUE_PATH,
        candidate_dir=Path(args.candidate_dir) if args.candidate_dir else TASK_TEMPLATE_CANDIDATES_DIR,
    )
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
