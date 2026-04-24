import argparse
import json
from pathlib import Path

from common import PROFILE_PATH, configure_stdout, load_profile


def parse_args():
    parser = argparse.ArgumentParser(description="查看当前用户画像")
    parser.add_argument("--profile-file", help="profile.md 路径")
    parser.add_argument("--output-file", help="输出 JSON 文件")
    return parser.parse_args()


def main():
    configure_stdout()
    args = parse_args()
    target = Path(args.profile_file) if args.profile_file else PROFILE_PATH
    structured, notes = load_profile(target)
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
