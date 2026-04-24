import argparse
import json
import sys
from pathlib import Path

from common import configure_stdout, infer_run_verdict, read_json_input


def parse_args():
    parser = argparse.ArgumentParser(description="生成运行摘要")
    parser.add_argument("--input-file", help="输入 JSON 文件")
    parser.add_argument("--output-file", help="输出 JSON 文件")
    parser.add_argument("--markdown-file", help="输出 Markdown 文件")
    return parser.parse_args()


def load_payload(args):
    if args.input_file:
        return json.loads(Path(args.input_file).read_text(encoding="utf-8-sig"))
    raw = sys.stdin.read().strip()
    parsed = read_json_input(raw)
    if not isinstance(parsed, dict):
        raise ValueError("运行摘要输入必须是 JSON 对象")
    return parsed


def build_markdown(summary):
    return "\n".join(
        [
            "# Run Summary",
            "",
            f"- task_id: {summary.get('task_id', '')}",
            f"- run_verdict: {summary.get('run_verdict', '')}",
            f"- result_summary: {summary.get('result_summary', '')}",
            f"- next_action: {summary.get('next_action', '')}",
            "",
        ]
    ) + "\n"


def main():
    configure_stdout()
    args = parse_args()
    payload = load_payload(args)
    summary = {
        "task_id": payload.get("task_id", ""),
        "goal": payload.get("goal", ""),
        "run_verdict": infer_run_verdict(payload),
        "result_summary": str(payload.get("result_summary") or payload.get("last_result_summary") or "").strip(),
        "next_action": str(payload.get("next_action") or "").strip(),
        "should_continue": bool(payload.get("should_continue", False)),
    }
    json_output = json.dumps(summary, ensure_ascii=False, indent=2)
    markdown_output = build_markdown(summary)

    if args.output_file:
        Path(args.output_file).write_text(json_output + "\n", encoding="utf-8")
    if args.markdown_file:
        Path(args.markdown_file).write_text(markdown_output, encoding="utf-8")
    if not args.output_file and not args.markdown_file:
        print(json_output)


if __name__ == "__main__":
    main()
