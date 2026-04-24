import argparse
import json
import re
import sys
from pathlib import Path

from common import configure_stdout, normalize_string_list, read_json_input


WORK_TYPE_RULES = [
    ("角色设计", ["角色设计", "角色设定", "角色", "人设", "立绘", "character design", "character concept"]),
    ("海报", ["海报", "poster", "key visual", "banner"]),
    ("场景设定", ["场景", "环境设定", "场景设定", "environment concept", "environment design"]),
    ("情绪板", ["情绪板", "moodboard"]),
    ("产品图", ["产品图", "产品", "product shot", "product render"]),
    ("提案图", ["提案", "pitch", "presentation visual"]),
]
INDUSTRY_RULES = [
    ("游戏", ["游戏", "game", "character design", "concept art"]),
    ("营销", ["海报", "poster", "广告", "campaign", "banner"]),
    ("影视", ["电影", "影视", "cinematic", "film"]),
]


def parse_args():
    parser = argparse.ArgumentParser(description="从任务结果中提取用户画像 signal 候选")
    parser.add_argument("--input-file", help="输入 JSON 文件")
    parser.add_argument("--output-file", help="输出 JSON 文件")
    return parser.parse_args()


def load_payload(args):
    if args.input_file:
        return json.loads(Path(args.input_file).read_text(encoding="utf-8-sig"))
    raw = sys.stdin.read().strip()
    payload = read_json_input(raw)
    if not isinstance(payload, dict):
        raise ValueError("画像 signal 提取输入必须是 JSON 对象")
    return payload


def detect_tokens(text: str, rules):
    lowered = str(text or "").lower()
    matched = []
    for label, tokens in rules:
        if any(token.lower() in lowered for token in tokens):
            matched.append(label)
    return matched


def unique(values):
    results = []
    seen = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
    return results


def compact_text(*values):
    return " ".join(str(value or "").strip() for value in values if str(value or "").strip())


def infer_quality_tendency(payload: dict):
    verdict = str(payload.get("run_verdict") or "").strip()
    round_index = max(1, int(payload.get("round_index") or 1))
    prompt_stage = str(payload.get("prompt_stage") or "").strip()
    should_continue = bool(payload.get("should_continue", False))

    if verdict == "success" and prompt_stage == "finalize":
        return "偏好可交付成品"
    if should_continue or verdict == "usable_but_iterate" or round_index > 1:
        return "偏好多轮迭代收敛"
    return ""


def build_notes(payload: dict):
    notes = []
    goal = str(payload.get("goal") or "").strip()
    if goal:
        notes.append(f"最近任务目标：{goal}")
    result_summary = str(payload.get("result_summary") or "").strip()
    if result_summary:
        notes.append(f"最近结果结论：{result_summary}")
    latest_feedback = payload.get("latest_feedback") or {}
    feedback_points = normalize_string_list(latest_feedback.get("points"))
    if feedback_points:
        notes.append("最近一轮用户反馈：" + "、".join(feedback_points))
    return unique(notes)


def extract_candidate(payload: dict):
    verdict = str(payload.get("run_verdict") or "").strip()
    if verdict not in {"success", "usable_but_iterate"}:
        return {
            "ok": True,
            "candidate": {},
            "skipped": True,
            "reason": "run_verdict_not_profile_eligible",
        }

    brief = payload.get("brief") if isinstance(payload.get("brief"), dict) else {}
    goal = str(payload.get("goal") or brief.get("goal") or "").strip()
    deliverable = str(brief.get("deliverable") or payload.get("brief_summary") or "").strip()
    joined = compact_text(goal, deliverable, payload.get("brief_summary"), payload.get("current_prompt"))

    work_types = unique(
        normalize_string_list(brief.get("work_types"))
        + detect_tokens(joined, WORK_TYPE_RULES)
    )
    style_preferences = normalize_string_list(brief.get("style_bias"))
    content_preferences = normalize_string_list(brief.get("must_have"))
    taboos = normalize_string_list(brief.get("must_not_have"))
    industry_candidates = detect_tokens(joined, INDUSTRY_RULES)
    industry = industry_candidates[0] if industry_candidates else ""

    candidate = {
        "source": "automatic_run_profile_signal",
        "confidence": "candidate",
        "promote_to_profile": False,
        "industry": industry,
        "work_types": work_types,
        "style_preferences": style_preferences,
        "content_preferences": content_preferences,
        "taboos": taboos,
        "quality_tendency": infer_quality_tendency(payload),
        "notes": build_notes(payload),
    }
    return {
        "ok": True,
        "candidate": candidate,
        "skipped": False,
        "reason": "",
    }


def main():
    configure_stdout()
    args = parse_args()
    payload = load_payload(args)
    result = extract_candidate(payload)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
