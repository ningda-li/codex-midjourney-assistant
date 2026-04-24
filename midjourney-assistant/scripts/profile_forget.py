import argparse
import json
from pathlib import Path

from common import (
    PROFILE_PATH,
    configure_stdout,
    load_profile,
    normalize_string_list,
    render_profile,
    write_text,
)


LIST_FIELDS = {"work_types", "style_preferences", "content_preferences", "taboos"}
SCALAR_FIELDS = {"industry", "quality_tendency", "updated_at"}


def parse_args():
    parser = argparse.ArgumentParser(description="遗忘用户画像中的某个字段或值")
    parser.add_argument("--profile-file", help="profile.md 路径")
    parser.add_argument("--field", required=True, help="要遗忘的字段")
    parser.add_argument("--value", help="要移除的具体值；列表字段不传则整字段清空")
    parser.add_argument("--output-file", help="输出 JSON 文件")
    return parser.parse_args()


def main():
    configure_stdout()
    args = parse_args()
    target = Path(args.profile_file) if args.profile_file else PROFILE_PATH
    structured, notes = load_profile(target)
    field = str(args.field or "").strip()
    value = str(args.value or "").strip()

    if field in LIST_FIELDS:
        if value:
            remove_set = set(normalize_string_list(value))
            structured[field] = [item for item in normalize_string_list(structured.get(field)) if item not in remove_set]
        else:
            structured[field] = []
    elif field in SCALAR_FIELDS:
        structured[field] = ""
    elif field == "notes":
        if value:
            remove_set = set(normalize_string_list(value))
            notes = [item for item in notes if item not in remove_set]
        else:
            notes = []
    else:
        raise ValueError(f"不支持遗忘字段：{field}")

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
