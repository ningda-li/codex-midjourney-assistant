import argparse
import json
import sys
from pathlib import Path

from common import (
    DISTILLED_PATTERNS_PATH,
    MEMORY_ROOT,
    SITE_CHANGELOG_PATH,
    configure_stdout,
    extract_keywords,
    load_profile,
    project_memory_path,
    read_json_input,
    read_text,
    score_text,
)


def parse_args():
    parser = argparse.ArgumentParser(description="按 brief 检索相关记忆")
    parser.add_argument("--brief-file", help="brief 文件路径")
    parser.add_argument("--brief-json", help="brief JSON 字符串")
    parser.add_argument("--task-file", help="统一任务对象文件路径")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def extract_brief(payload):
    if isinstance(payload, dict) and isinstance(payload.get("brief"), dict):
        return payload["brief"]
    return payload if isinstance(payload, dict) else None


def load_brief(args):
    if args.brief_json:
        parsed = read_json_input(args.brief_json)
        brief = extract_brief(parsed)
        if isinstance(brief, dict):
            return brief
    if args.brief_file:
        content = Path(args.brief_file).read_text(encoding="utf-8-sig")
        parsed = read_json_input(content)
        brief = extract_brief(parsed)
        if isinstance(brief, dict):
            return brief
    if args.task_file:
        content = Path(args.task_file).read_text(encoding="utf-8-sig")
        parsed = read_json_input(content)
        brief = extract_brief(parsed)
        if isinstance(brief, dict):
            return brief
    content = sys.stdin.read().strip()
    parsed = read_json_input(content)
    brief = extract_brief(parsed)
    if isinstance(brief, dict):
        return brief
    raise ValueError("无法读取 brief")


def slice_hits(text, keywords):
    if not text.strip():
        return []
    hits = []
    for line in text.splitlines():
        score = score_text(line, keywords)
        if score > 0:
            hits.append({"line": line.strip(), "score": score})
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits[:8]


def main():
    configure_stdout()
    args = parse_args()
    brief = load_brief(args)
    keywords = extract_keywords(
        [
            brief.get("goal", ""),
            " ".join(brief.get("must_have", [])),
            " ".join(brief.get("must_not_have", [])),
            " ".join(brief.get("style_bias", [])),
            brief.get("project_id", ""),
        ]
    )

    structured_profile, profile_notes = load_profile()
    profile_blob = json.dumps(structured_profile, ensure_ascii=False)
    profile_hits = slice_hits(profile_blob + "\n" + "\n".join(profile_notes), keywords)

    project_id = str(brief.get("project_id") or "").strip()
    project_file = project_memory_path(project_id) if project_id else None
    project_text = read_text(project_file, default="") if project_file else ""
    project_hits = slice_hits(project_text, keywords)

    distilled_hits = slice_hits(read_text(DISTILLED_PATTERNS_PATH, default=""), keywords)
    site_hits = slice_hits(read_text(SITE_CHANGELOG_PATH, default=""), keywords)

    snapshot = {
        "keywords": keywords,
        "sources_read": [
            "user-profile/profile.md",
            "projects/" + f"{project_id}.md" if project_id else "projects/<none>",
            "distilled-patterns.md",
            "site-changelog.md",
        ],
        "hits": {
            "user_profile": profile_hits,
            "project_memory": project_hits,
            "distilled_patterns": distilled_hits,
            "site_changes": site_hits,
        },
    }

    output = {
        "user_profile": {
            "structured": structured_profile,
            "notes": profile_notes,
            "hits": profile_hits,
        },
        "project_memory": {
            "project_id": project_id,
            "hits": project_hits,
        },
        "distilled_patterns": distilled_hits,
        "site_changes": site_hits,
        "memory_policy_snapshot": snapshot,
    }

    content = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(content + "\n", encoding="utf-8")
    else:
        print(content)


if __name__ == "__main__":
    main()
