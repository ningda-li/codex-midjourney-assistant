import argparse
import json
import sys
from pathlib import Path

from common import (
    PROFILE_PATH,
    configure_stdout,
    load_profile,
    normalize_string_list,
    read_json_input,
    render_profile,
    write_text,
)


LIST_FIELDS = {"work_types", "style_preferences", "content_preferences", "taboos"}
SCALAR_FIELDS = {"industry", "quality_tendency", "updated_at"}


def parse_args():
    parser = argparse.ArgumentParser(description="纠正当前用户画像")
    parser.add_argument("--input-file", help="输入 JSON patch 文件")
    parser.add_argument("--profile-file", help="profile.md 路径")
    parser.add_argument("--output-file", help="输出 JSON 文件")
    return parser.parse_args()


def load_patch(args):
    if args.input_file:
        return json.loads(Path(args.input_file).read_text(encoding="utf-8-sig"))
    raw = sys.stdin.read().strip()
    payload = read_json_input(raw)
    if not isinstance(payload, dict):
        raise ValueError("画像纠正输入必须是 JSON 对象")
    return payload


def main():
    configure_stdout()
    args = parse_args()
    payload = load_patch(args)
    target = Path(args.profile_file) if args.profile_file else PROFILE_PATH
    structured, notes = load_profile(target)

    structured_patch = payload.get("structured_patch") if isinstance(payload.get("structured_patch"), dict) else {}
    for field, value in structured_patch.items():
        if field in LIST_FIELDS:
            structured[field] = normalize_string_list(value)
        elif field in SCALAR_FIELDS:
            structured[field] = str(value or "").strip()
        else:
            raise ValueError(f"不支持纠正字段：{field}")

    if "replace_notes" in payload:
        notes = normalize_string_list(payload.get("replace_notes"))
    if "append_notes" in payload:
        notes = normalize_string_list(notes + normalize_string_list(payload.get("append_notes")))
    if "remove_notes" in payload:
        remove_set = set(normalize_string_list(payload.get("remove_notes")))
        notes = [item for item in notes if item not in remove_set]

    write_text(target, render_profile(structured, notes))
    result = {
        "ok": True,
        "path": str(target),
        "structured": structured,
        "notes": notes,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
