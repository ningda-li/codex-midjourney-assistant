import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from common import (
    MEMORY_ROOT,
    append_jsonl,
    configure_stdout,
    infer_run_verdict,
    now_iso,
    read_json_input,
)


def parse_args():
    parser = argparse.ArgumentParser(description="追加运行日志")
    parser.add_argument("--input-file", help="输入 JSON 文件")
    parser.add_argument("--output-file", help="输出 JSONL 文件路径")
    return parser.parse_args()


def load_record(args):
    if args.input_file:
        return json.loads(Path(args.input_file).read_text(encoding="utf-8-sig"))
    raw = sys.stdin.read().strip()
    parsed = read_json_input(raw)
    if not isinstance(parsed, dict):
        raise ValueError("运行日志输入必须是 JSON 对象")
    return parsed


def main():
    configure_stdout()
    args = parse_args()
    record = load_record(args)
    record.setdefault("logged_at", now_iso())
    record["run_verdict"] = infer_run_verdict(record)
    timestamp = datetime.now().astimezone()
    target = (
        Path(args.output_file)
        if args.output_file
        else MEMORY_ROOT / "runs" / f"{timestamp:%Y-%m}.jsonl"
    )
    append_jsonl(target, record)
    print(
        json.dumps(
            {
                "ok": True,
                "path": str(target),
                "task_id": record.get("task_id", ""),
                "run_verdict": record["run_verdict"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
