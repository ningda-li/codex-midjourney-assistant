import argparse
import json
import re
import sys
from pathlib import Path

from common import SKILL_ROOT, configure_stdout, normalize_string_list, now_iso, read_json_file, read_json_input
from solution_plan_build import KNOWLEDGE_RULES_PATH, build_solution_plan, build_structured_knowledge, load_asset


REFERENCE_ROOT = SKILL_ROOT / "references"
MAX_DOCUMENTS = 8
MAX_SECTION_CHARS = 700
MAX_TOTAL_CHARS = 3600
MIN_TRUNCATED_SECTION_CHARS = 80


def parse_args():
    parser = argparse.ArgumentParser(description="按任务检索 Midjourney reference 知识")
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
    raise ValueError("reference_knowledge_retrieve 输入必须是任务对象 JSON")


def unique_documents(documents):
    merged = []
    seen = set()
    for document in documents or []:
        if not isinstance(document, dict):
            continue
        path = str(document.get("path") or "").strip()
        sections = normalize_string_list(document.get("sections"))
        if not path:
            continue
        key = (path, tuple(sections))
        if key in seen:
            continue
        merged.append({"path": path, "sections": sections})
        seen.add(key)
    return merged


def clean_section_text(text: str, limit: int = MAX_SECTION_CHARS):
    lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        line = re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
        if line:
            lines.append(line)
    compact = " ".join(lines)
    compact = re.sub(r"\s+", " ", compact).strip()
    return compact[:limit].rstrip()


def split_markdown_sections(text: str):
    sections = {}
    current_heading = ""
    current_lines = []

    def flush():
        if current_heading:
            sections[current_heading] = "\n".join(current_lines).strip()

    for line in str(text or "").splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            flush()
            current_heading = match.group(1).strip()
            current_lines = []
            continue
        if current_heading:
            current_lines.append(line)
    flush()
    return sections


def extract_document_sections(path: Path, requested_sections):
    text = path.read_text(encoding="utf-8-sig")
    sections = split_markdown_sections(text)
    extracted = []
    for heading in normalize_string_list(requested_sections):
        content = sections.get(heading)
        if content is None:
            continue
        excerpt = clean_section_text(content)
        if excerpt:
            extracted.append({"heading": heading, "excerpt": excerpt})
    if not extracted:
        fallback = clean_section_text(text, limit=MAX_SECTION_CHARS)
        if fallback:
            extracted.append({"heading": "document_overview", "excerpt": fallback})
    return extracted


def collect_reference_documents(task: dict, structured_knowledge: dict):
    solution_plan = task.get("solution_plan") if isinstance(task.get("solution_plan"), dict) else {}
    documents = []
    documents.extend(solution_plan.get("reference_documents") or [])
    documents.extend((solution_plan.get("structured_knowledge") or {}).get("reference_documents") or [])
    documents.extend(structured_knowledge.get("reference_documents") or [])
    return unique_documents(documents)[:MAX_DOCUMENTS]


def build_reference_snapshot(task: dict):
    if not isinstance(task.get("solution_plan"), dict):
        task, _ = build_solution_plan(task)
    solution_plan = task.get("solution_plan") if isinstance(task.get("solution_plan"), dict) else {}
    task_model = task.get("task_model") if isinstance(task.get("task_model"), dict) else {}
    knowledge_payload = load_asset(KNOWLEDGE_RULES_PATH)
    structured_knowledge = solution_plan.get("structured_knowledge")
    if not isinstance(structured_knowledge, dict):
        structured_knowledge = build_structured_knowledge(
            knowledge_payload,
            task_model,
            solution_plan.get("recommended_capabilities"),
        )

    documents = collect_reference_documents(task, structured_knowledge)
    total_chars = 0
    resolved_documents = []
    missing_documents = []

    for document in documents:
        relative_path = str(document.get("path") or "").strip()
        path = (REFERENCE_ROOT / relative_path).resolve()
        try:
            path.relative_to(REFERENCE_ROOT.resolve())
        except ValueError:
            missing_documents.append(relative_path)
            continue
        if not path.exists() or not path.is_file():
            missing_documents.append(relative_path)
            continue
        sections = extract_document_sections(path, document.get("sections"))
        kept_sections = []
        for section in sections:
            excerpt = str(section.get("excerpt") or "")
            if not excerpt:
                continue
            if total_chars >= MAX_TOTAL_CHARS:
                break
            remaining = MAX_TOTAL_CHARS - total_chars
            if len(excerpt) > remaining and remaining < MIN_TRUNCATED_SECTION_CHARS:
                break
            kept_excerpt = excerpt[:remaining].rstrip()
            if len(excerpt) > len(kept_excerpt) and len(kept_excerpt) < MIN_TRUNCATED_SECTION_CHARS:
                break
            kept_sections.append({"heading": section.get("heading", ""), "excerpt": kept_excerpt})
            total_chars += len(kept_excerpt)
        if kept_sections:
            resolved_documents.append(
                {
                    "path": relative_path,
                    "sections_requested": normalize_string_list(document.get("sections")),
                    "sections": kept_sections,
                }
            )
        if total_chars >= MAX_TOTAL_CHARS:
            break

    guidance = {
        "prompt_cues": normalize_string_list(structured_knowledge.get("prompt_cues")),
        "prompt_negative_cues": normalize_string_list(structured_knowledge.get("prompt_negative_cues")),
        "avoid_prompt_cues": normalize_string_list(structured_knowledge.get("avoid_prompt_cues")),
        "submission_notes": normalize_string_list(structured_knowledge.get("submission_notes")),
        "parameter_preferences": normalize_string_list(structured_knowledge.get("parameter_preferences")),
        "optional_parameters": normalize_string_list(structured_knowledge.get("optional_parameters")),
        "avoid_parameters": normalize_string_list(structured_knowledge.get("avoid_parameters")),
        "applied_rule_ids": normalize_string_list(structured_knowledge.get("applied_rule_ids")),
    }
    return task, {
        "applied": bool(resolved_documents or guidance["applied_rule_ids"]),
        "generated_at": now_iso(),
        "source_asset": "assets/knowledge-rules.json",
        "documents": resolved_documents,
        "missing_documents": missing_documents,
        "guidance": guidance,
    }


def attach_reference_snapshot(task: dict, snapshot: dict):
    updated_task = dict(task)
    updated_task["reference_knowledge_snapshot"] = snapshot
    updated_task["knowledge_guidance"] = snapshot.get("guidance") if isinstance(snapshot.get("guidance"), dict) else {}
    artifacts = dict(updated_task.get("artifacts") or {})
    artifacts["reference_knowledge"] = snapshot
    updated_task["artifacts"] = artifacts
    updated_task["updated_at"] = now_iso()
    return updated_task


def main():
    configure_stdout()
    args = parse_args()
    task = load_task(args)
    task, snapshot = build_reference_snapshot(task)
    updated_task = attach_reference_snapshot(task, snapshot)
    result = {
        "ok": True,
        "task": updated_task,
        "reference_knowledge_snapshot": snapshot,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
