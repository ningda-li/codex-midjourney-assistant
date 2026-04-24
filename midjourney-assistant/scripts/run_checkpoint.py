import argparse
import json
import sys
from pathlib import Path

from common import MEMORY_ROOT, configure_stdout, ensure_parent, now_iso, read_json_input


def parse_args():
    parser = argparse.ArgumentParser(description="写入任务检查点")
    parser.add_argument("--input-file", help="输入 JSON 文件")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def load_payload(args):
    if args.input_file:
        return json.loads(Path(args.input_file).read_text(encoding="utf-8-sig"))
    raw = sys.stdin.read().strip()
    payload = read_json_input(raw)
    if not isinstance(payload, dict):
        raise ValueError("检查点输入必须是 JSON 对象")
    return payload


def main():
    configure_stdout()
    args = parse_args()
    payload = load_payload(args)
    task_id = str(payload.get("task_id") or "unnamed-task").strip()
    payload["checkpointed_at"] = now_iso()
    target = (
        Path(args.output_file)
        if args.output_file
        else MEMORY_ROOT / "runs" / "checkpoints" / f"{task_id}.json"
    )
    ensure_parent(target)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"ok": True, "path": str(target), "task_id": task_id},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
