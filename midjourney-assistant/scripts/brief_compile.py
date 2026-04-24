import argparse
import json
import re
import sys

from common import configure_stdout, normalize_string_list, read_json_input


STYLE_HINTS = [
    "赛博东方",
    "二次元概念设定",
    "二次元",
    "概念设定",
    "赛博朋克",
    "东方",
    "国风",
    "绘本",
    "电影感",
    "插画",
    "写实",
]


def clean_phrase(text: str) -> str:
    return re.sub(r"^[是为要]\s*", "", text.strip(" ，。；;、"))


def clean_subject_phrase(text: str) -> str:
    value = clean_phrase(text)
    value = re.sub(r"^(?:一组|一张|一套|一个)", "", value)
    value = re.sub(r"^(?:[^，。；;]{1,20}?风(?:格)?的)+", "", value)
    return value.strip(" 的")


def infer_deliverable(text: str) -> str:
    if "提案" in text or "筛选" in text:
        return "一组可用于提案筛选的 Midjourney 结果"
    if "情绪板" in text:
        return "一组可用于情绪板筛选的 Midjourney 结果"
    if "终稿" in text or "成图" in text or "定稿" in text:
        return "一张可直接使用的 Midjourney 成图"
    return "一组可用于筛选的 Midjourney 结果"


def infer_mode(text: str) -> str:
    return "iterative" if any(token in text for token in ["多轮", "迭代", "连续", "多次"]) else "single_run"


def extract_must_have(text: str):
    results = []
    patterns = [
        (r"主体(?:要是|为|是|要)?([^，。；;]+)", "主体为{value}"),
        (r"主角(?:要是|为|是|要)?([^，。；;]+)", "主角为{value}"),
        (r"要有([^，。；;]+)", "包含{value}"),
        (r"包含([^，。；;]+)", "包含{value}"),
        (
            r"(?:做|生成|来|帮我做|帮我生成|需要|想要)(?:一组|一张|一套|一个)?([^，。；;]+?)(?:提案图|角色图|设定图|成图|海报|插画|概念图|概念设定图)",
            "主体为{value}",
        ),
    ]
    for pattern, template in patterns:
        for match in re.finditer(pattern, text):
            if "主体为{value}" == template:
                value = clean_subject_phrase(match.group(1))
            else:
                value = clean_phrase(match.group(1))
            if value:
                results.append(template.format(value=value))
    return normalize_string_list(results)


def extract_must_not_have(text: str):
    results = []
    for pattern in [r"不要([^，。；;]+)", r"不能([^，。；;]+)", r"避免([^，。；;]+)", r"禁用([^，。；;]+)"]:
        for match in re.finditer(pattern, text):
            value = clean_phrase(match.group(1))
            if value:
                results.append(value)
    return normalize_string_list(results)


def extract_style_bias(text: str):
    results = []
    for pattern in [r"风格(?:偏|为|是)([^，。；;]+)", r"画风(?:偏|为|是)([^，。；;]+)"]:
        for match in re.finditer(pattern, text):
            value = clean_phrase(match.group(1))
            if value:
                results.append(value)
    for hint in STYLE_HINTS:
        if hint in text:
            results.append(hint)
    return normalize_string_list(results)


def parse_args():
    parser = argparse.ArgumentParser(description="规范化 Midjourney brief")
    parser.add_argument("--text", help="原始需求文本")
    parser.add_argument("--input-file", help="输入文件路径")
    parser.add_argument("--output-file", help="输出文件路径")
    return parser.parse_args()


def load_input(args):
    if args.text:
        return args.text.strip()
    if args.input_file:
        with open(args.input_file, "r", encoding="utf-8-sig") as handle:
            return handle.read().strip().lstrip("\ufeff")
    return sys.stdin.read().strip()


def build_defaults(goal: str):
    return {
        "goal": goal,
        "deliverable": infer_deliverable(goal),
        "must_have": [],
        "must_not_have": [],
        "style_bias": [],
        "iteration_budget": 3 if infer_mode(goal) == "iterative" else 1,
        "stop_rule": "完成当前单轮生成并给出结果判断",
        "mode": infer_mode(goal),
        "project_id": "",
    }


def normalize(raw_input: str):
    parsed = read_json_input(raw_input)
    if isinstance(parsed, dict):
        goal = str(parsed.get("goal", "")).strip()
        if not goal:
            raise ValueError("brief 缺少 goal")
        brief = build_defaults(goal)
        brief["deliverable"] = str(parsed.get("deliverable") or brief["deliverable"]).strip()
        brief["must_have"] = normalize_string_list(parsed.get("must_have"))
        brief["must_not_have"] = normalize_string_list(parsed.get("must_not_have"))
        brief["style_bias"] = normalize_string_list(parsed.get("style_bias"))
        brief["iteration_budget"] = max(1, int(parsed.get("iteration_budget") or 1))
        brief["stop_rule"] = str(parsed.get("stop_rule") or brief["stop_rule"]).strip()
        brief["mode"] = str(parsed.get("mode") or brief["mode"]).strip() or "single_run"
        brief["project_id"] = str(parsed.get("project_id") or "").strip()
        return brief

    goal = raw_input.strip().lstrip("\ufeff")
    if not goal:
        raise ValueError("原始需求为空")
    brief = build_defaults(goal)
    brief["must_have"] = extract_must_have(goal)
    brief["must_not_have"] = extract_must_not_have(goal)
    brief["style_bias"] = extract_style_bias(goal)
    if brief["mode"] == "iterative":
        brief["stop_rule"] = "达到目标、达到迭代预算上限或用户中止"
    return brief


def main():
    configure_stdout()
    args = parse_args()
    brief = normalize(load_input(args))
    output = json.dumps(brief, ensure_ascii=False, indent=2)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as handle:
            handle.write(output + "\n")
    else:
        print(output)


if __name__ == "__main__":
    main()
