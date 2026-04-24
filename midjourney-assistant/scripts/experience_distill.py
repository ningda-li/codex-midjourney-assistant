import argparse
import json
import re
import sys
from pathlib import Path

from common import (
    DISTILLED_PATTERNS_PATH,
    FAILURE_PATTERNS_PATH,
    SITE_CHANGELOG_PATH,
    configure_stdout,
    now_iso,
    read_json_input,
    read_text,
    write_text,
)


SITE_CHANGE_REASONS = {
    "isolated_browser_challenge_page",
    "prompt_region_not_found",
    "prompt_region_unconfirmed",
    "isolated_browser_input_not_ready",
}


def parse_args():
    parser = argparse.ArgumentParser(description="把运行日志蒸馏成长期经验与失败模式")
    parser.add_argument("--input-file", help="输入 run_record JSON 文件")
    parser.add_argument("--distilled-file", help="蒸馏经验文件路径")
    parser.add_argument("--failure-file", help="失败模式文件路径")
    parser.add_argument("--site-file", help="页面变化记录文件路径")
    parser.add_argument("--output-file", help="输出 JSON 文件")
    return parser.parse_args()


def load_payload(args):
    if args.input_file:
        return json.loads(Path(args.input_file).read_text(encoding="utf-8-sig"))
    raw = sys.stdin.read().strip()
    payload = read_json_input(raw)
    if not isinstance(payload, dict):
        raise ValueError("蒸馏经验输入必须是 JSON 对象")
    return payload


def load_snapshot(path: Path, key: str):
    content = read_text(path, default="")
    match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.S)
    if match:
        payload = read_json_input(match.group(1))
        if isinstance(payload, dict) and isinstance(payload.get(key), list):
            return payload
    return {"updated_at": "", key: []}


def upsert_entry(entries, key: str, patch: dict):
    normalized_entries = [item for item in entries if isinstance(item, dict)]
    for item in normalized_entries:
        if str(item.get("key") or "").strip() == key:
            item.update(patch)
            item["count"] = int(item.get("count") or 0) + 1
            item["last_seen_at"] = now_iso()
            return normalized_entries, item
    entry = {
        "key": key,
        "count": 1,
        "first_seen_at": now_iso(),
        "last_seen_at": now_iso(),
    }
    entry.update(patch)
    normalized_entries.append(entry)
    return normalized_entries, entry


def render_snapshot(title: str, section_title: str, payload_key: str, payload: dict, summary_lines):
    lines = [
        f"# {title}",
        "",
        f"## {section_title}",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 最近摘要",
        "",
    ]
    if summary_lines:
        lines.extend(f"- {line}" for line in summary_lines)
    else:
        lines.append("- 暂无自动蒸馏记录")
    return "\n".join(lines) + "\n"


def build_success_entry(record: dict):
    brief = record.get("brief") if isinstance(record.get("brief"), dict) else {}
    work_types = brief.get("work_types") if isinstance(brief.get("work_types"), list) else []
    stage = str(record.get("prompt_stage") or "").strip()
    backend = str(record.get("automatic_execution_backend") or "").strip()
    verdict = str(record.get("run_verdict") or "").strip()
    key = "|".join(
        [
            backend or "unknown_backend",
            stage or "unknown_stage",
            ",".join(sorted(str(item).strip() for item in work_types if str(item).strip())) or "unknown_work_type",
            verdict or "unknown_verdict",
        ]
    )
    return key, {
        "backend": backend,
        "prompt_stage": stage,
        "work_types": work_types,
        "run_verdict": verdict,
        "goal": str(record.get("goal") or "").strip(),
        "brief_summary": str(record.get("brief_summary") or "").strip(),
        "result_summary": str(record.get("result_summary") or "").strip(),
        "prompt_excerpt": str(record.get("current_prompt") or "").strip()[:180],
    }


def build_failure_entry(record: dict):
    governance = record.get("execution_governance") if isinstance(record.get("execution_governance"), dict) else {}
    backend = str(record.get("automatic_execution_backend") or "").strip()
    verdict = str(record.get("run_verdict") or "").strip()
    blocked_reason = str(governance.get("blocked_reason") or record.get("blocked_reason") or "").strip()
    key = "|".join(
        [
            backend or "unknown_backend",
            verdict or "unknown_verdict",
            blocked_reason or "unknown_block",
        ]
    )
    return key, {
        "backend": backend,
        "run_verdict": verdict,
        "blocked_reason": blocked_reason,
        "recommended_action": str(governance.get("recommended_action") or "").strip(),
        "message": str(governance.get("message") or record.get("result_summary") or "").strip(),
    }


def build_site_change_entry(record: dict):
    governance = record.get("execution_governance") if isinstance(record.get("execution_governance"), dict) else {}
    blocked_reason = str(governance.get("blocked_reason") or record.get("blocked_reason") or "").strip()
    backend = str(record.get("automatic_execution_backend") or "").strip()
    key = "|".join([backend or "unknown_backend", blocked_reason or "unknown_site_change"])
    return key, {
        "backend": backend,
        "blocked_reason": blocked_reason,
        "message": str(governance.get("message") or record.get("result_summary") or "").strip(),
        "goal": str(record.get("goal") or "").strip(),
    }


def summarize_entries(entries, formatter):
    results = []
    for item in sorted(entries, key=lambda value: int(value.get("count") or 0), reverse=True)[:5]:
        results.append(formatter(item))
    return results


def distill_record(record: dict, distilled_file: Path, failure_file: Path, site_file: Path):
    run_verdict = str(record.get("run_verdict") or "").strip()
    receipts = {
        "distilled_patterns": {"updated": False, "path": str(distilled_file), "entry_key": ""},
        "failure_patterns": {"updated": False, "path": str(failure_file), "entry_key": ""},
        "site_changes": {"updated": False, "path": str(site_file), "entry_key": ""},
    }

    if run_verdict in {"success", "usable_but_iterate"}:
        payload = load_snapshot(distilled_file, "patterns")
        key, patch = build_success_entry(record)
        payload["patterns"], entry = upsert_entry(payload.get("patterns", []), key, patch)
        payload["updated_at"] = now_iso()
        summary_lines = summarize_entries(
            payload["patterns"],
            lambda item: f"{item.get('work_types') or ['未标注类型']} | {item.get('prompt_stage', '')} | {item.get('backend', '')} | {item.get('count', 0)} 次",
        )
        write_text(
            distilled_file,
            render_snapshot("蒸馏经验", "自动蒸馏快照", "patterns", payload, summary_lines),
        )
        receipts["distilled_patterns"] = {
            "updated": True,
            "path": str(distilled_file),
            "entry_key": key,
            "count": entry.get("count", 0),
        }

    if run_verdict in {"blocked_by_ui", "blocked_by_context", "stopped_by_budget", "stopped_by_user"}:
        payload = load_snapshot(failure_file, "patterns")
        key, patch = build_failure_entry(record)
        payload["patterns"], entry = upsert_entry(payload.get("patterns", []), key, patch)
        payload["updated_at"] = now_iso()
        summary_lines = summarize_entries(
            payload["patterns"],
            lambda item: f"{item.get('run_verdict', '')} | {item.get('blocked_reason', '') or '未标注原因'} | {item.get('count', 0)} 次",
        )
        write_text(
            failure_file,
            render_snapshot("失败模式", "自动蒸馏快照", "patterns", payload, summary_lines),
        )
        receipts["failure_patterns"] = {
            "updated": True,
            "path": str(failure_file),
            "entry_key": key,
            "count": entry.get("count", 0),
        }

    governance = record.get("execution_governance") if isinstance(record.get("execution_governance"), dict) else {}
    blocked_reason = str(governance.get("blocked_reason") or record.get("blocked_reason") or "").strip()
    if blocked_reason in SITE_CHANGE_REASONS:
        payload = load_snapshot(site_file, "changes")
        key, patch = build_site_change_entry(record)
        payload["changes"], entry = upsert_entry(payload.get("changes", []), key, patch)
        payload["updated_at"] = now_iso()
        summary_lines = summarize_entries(
            payload["changes"],
            lambda item: f"{item.get('blocked_reason', '')} | {item.get('backend', '')} | {item.get('count', 0)} 次",
        )
        write_text(
            site_file,
            render_snapshot("页面变化记录", "自动蒸馏快照", "changes", payload, summary_lines),
        )
        receipts["site_changes"] = {
            "updated": True,
            "path": str(site_file),
            "entry_key": key,
            "count": entry.get("count", 0),
        }

    return receipts


def main():
    configure_stdout()
    args = parse_args()
    record = load_payload(args)
    receipts = distill_record(
        record,
        Path(args.distilled_file) if args.distilled_file else DISTILLED_PATTERNS_PATH,
        Path(args.failure_file) if args.failure_file else FAILURE_PATTERNS_PATH,
        Path(args.site_file) if args.site_file else SITE_CHANGELOG_PATH,
    )
    result = {"ok": True, "receipts": receipts}
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
