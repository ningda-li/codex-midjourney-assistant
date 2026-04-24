import argparse
import json
import sys
from pathlib import Path

from common import (
    PREFERENCE_SIGNALS_PATH,
    PROFILE_PATH,
    TABOO_SIGNALS_PATH,
    append_jsonl,
    configure_stdout,
    load_jsonl_records,
    load_profile,
    normalize_string_list,
    now_iso,
    read_json_input,
    render_profile,
    write_text,
)


AUTO_PROMOTE_THRESHOLD = 2
LIST_FIELDS = {
    "work_types",
    "style_preferences",
    "content_preferences",
    "taboos",
}
SIGNAL_FIELD_SPECS = {
    "style_preferences": ("style", PREFERENCE_SIGNALS_PATH),
    "content_preferences": ("content", PREFERENCE_SIGNALS_PATH),
    "work_types": ("work_type", PREFERENCE_SIGNALS_PATH),
    "taboos": ("taboo", TABOO_SIGNALS_PATH),
}
SCALAR_SIGNAL_SPECS = {
    "industry": ("industry", PREFERENCE_SIGNALS_PATH),
    "quality_tendency": ("quality_tendency", PREFERENCE_SIGNALS_PATH),
}


def parse_args():
    parser = argparse.ArgumentParser(description="合并用户画像候选并按 signal 自动提升")
    parser.add_argument("--input-file", help="输入 JSON 文件")
    parser.add_argument("--output-file", help="输出 profile.md 路径")
    parser.add_argument("--preference-signals-file", help="偏好 signal 输出路径")
    parser.add_argument("--taboo-signals-file", help="禁忌 signal 输出路径")
    parser.add_argument("--promote-threshold", type=int, default=AUTO_PROMOTE_THRESHOLD, help="自动提升阈值")
    return parser.parse_args()


def load_candidate(args):
    if args.input_file:
        return json.loads(Path(args.input_file).read_text(encoding="utf-8-sig"))
    raw = sys.stdin.read().strip()
    parsed = read_json_input(raw)
    if not isinstance(parsed, dict):
        raise ValueError("画像候选输入必须是 JSON 对象")
    return parsed


def normalize_signal_value(value: str) -> str:
    return str(value or "").strip().lower()


def count_signal(records, signal_type: str, value: str) -> int:
    expected_type = normalize_signal_value(signal_type)
    expected_value = normalize_signal_value(value)
    total = 0
    for item in records:
        if not isinstance(item, dict):
            continue
        if normalize_signal_value(item.get("type")) != expected_type:
            continue
        if normalize_signal_value(item.get("value")) == expected_value:
            total += 1
    return total


def merge_scalar(existing_value, candidate_value, notes, field_name):
    existing = str(existing_value or "").strip()
    candidate = str(candidate_value or "").strip()
    if not candidate:
        return existing
    if not existing:
        return candidate
    if existing == candidate:
        return existing
    notes.append(f"{field_name} 出现新稳定值：{candidate}")
    return existing


def should_force_promote(candidate):
    if bool(candidate.get("promote_to_profile")):
        return True
    if bool(candidate.get("confirmed")):
        return True
    confidence = str(candidate.get("confidence") or "").strip().lower()
    return confidence in {"confirmed", "stable"}


def build_signal_paths(args):
    preference_signals_path = (
        Path(args.preference_signals_file) if args.preference_signals_file else PREFERENCE_SIGNALS_PATH
    )
    taboo_signals_path = (
        Path(args.taboo_signals_file) if args.taboo_signals_file else TABOO_SIGNALS_PATH
    )
    return {
        "style_preferences": preference_signals_path,
        "content_preferences": preference_signals_path,
        "work_types": preference_signals_path,
        "industry": preference_signals_path,
        "quality_tendency": preference_signals_path,
        "taboos": taboo_signals_path,
    }


def append_candidate_signals(candidate, signal_paths, source: str):
    recorded_at = now_iso()
    signal_records = []

    for field, (signal_type, path_default) in SIGNAL_FIELD_SPECS.items():
        path = signal_paths.get(field, path_default)
        for value in normalize_string_list(candidate.get(field)):
            record = {
                "recorded_at": recorded_at,
                "source": source,
                "type": signal_type,
                "field": field,
                "value": value,
            }
            append_jsonl(path, record)
            signal_records.append(record)

    for field, (signal_type, path_default) in SCALAR_SIGNAL_SPECS.items():
        path = signal_paths.get(field, path_default)
        value = str(candidate.get(field) or "").strip()
        if not value:
            continue
        record = {
            "recorded_at": recorded_at,
            "source": source,
            "type": signal_type,
            "field": field,
            "value": value,
        }
        append_jsonl(path, record)
        signal_records.append(record)

    return signal_records


def collect_signal_counts(candidate, signal_paths):
    counts = {}
    preference_records = load_jsonl_records(signal_paths["style_preferences"])
    taboo_records = load_jsonl_records(signal_paths["taboos"])

    for field, (signal_type, path_default) in SIGNAL_FIELD_SPECS.items():
        records = taboo_records if field == "taboos" else preference_records
        for value in normalize_string_list(candidate.get(field)):
            counts[(field, value)] = count_signal(records, signal_type, value)

    for field, (signal_type, path_default) in SCALAR_SIGNAL_SPECS.items():
        value = str(candidate.get(field) or "").strip()
        if not value:
            continue
        counts[(field, value)] = count_signal(preference_records, signal_type, value)
    return counts


def resolve_promoted_values(candidate, signal_counts, threshold: int, force_promote: bool):
    promoted = {field: [] for field in LIST_FIELDS}
    promoted_scalars = {}
    promoted_reasons = {}

    for field in LIST_FIELDS:
        for value in normalize_string_list(candidate.get(field)):
            count = signal_counts.get((field, value), 0)
            if force_promote or count >= threshold:
                promoted[field].append(value)
                reason = "explicit_confirmation" if force_promote else f"signal_count>={threshold}"
                promoted_reasons[f"{field}:{value}"] = {"count": count, "reason": reason}

    for field in SCALAR_SIGNAL_SPECS:
        value = str(candidate.get(field) or "").strip()
        if not value:
            continue
        count = signal_counts.get((field, value), 0)
        if force_promote or count >= threshold:
            promoted_scalars[field] = value
            reason = "explicit_confirmation" if force_promote else f"signal_count>={threshold}"
            promoted_reasons[field] = {"count": count, "reason": reason}

    return promoted, promoted_scalars, promoted_reasons


def merge_profile(structured, notes, candidate, promoted_lists, promoted_scalars, promoted_reasons):
    updated = False
    newly_promoted_keys = []

    for field, values in promoted_lists.items():
        current_values = normalize_string_list(structured.get(field))
        if not values:
            continue
        merged = normalize_string_list(current_values + values)
        if merged != current_values:
            structured[field] = merged
            updated = True
            for value in values:
                if value not in current_values:
                    newly_promoted_keys.append(f"{field}:{value}")

    if "industry" in promoted_scalars:
        current_value = str(structured.get("industry") or "").strip()
        merged = merge_scalar(current_value, promoted_scalars.get("industry"), notes, "industry")
        if merged != str(structured.get("industry") or "").strip():
            structured["industry"] = merged
            updated = True
            newly_promoted_keys.append("industry")

    if "quality_tendency" in promoted_scalars:
        current_value = str(structured.get("quality_tendency") or "").strip()
        merged = merge_scalar(
            current_value,
            promoted_scalars.get("quality_tendency"),
            notes,
            "quality_tendency",
        )
        if merged != str(structured.get("quality_tendency") or "").strip():
            structured["quality_tendency"] = merged
            updated = True
            newly_promoted_keys.append("quality_tendency")

    if updated:
        structured["updated_at"] = now_iso()
        for note in normalize_string_list(candidate.get("notes")):
            notes.append(note)
        for key in newly_promoted_keys:
            payload = promoted_reasons.get(key) or {}
            reason = payload.get("reason", "")
            count = payload.get("count", 0)
            notes.append(f"自动提升：{key}（{reason}，累计 signal {count} 次）")

    return updated


def main():
    configure_stdout()
    args = parse_args()
    candidate = load_candidate(args)
    target = Path(args.output_file) if args.output_file else PROFILE_PATH
    structured, notes = load_profile(target)
    notes = list(notes)

    source = str(candidate.get("source") or "profile_merge").strip()
    force_promote = should_force_promote(candidate)
    signal_paths = build_signal_paths(args)

    append_candidate_signals(candidate, signal_paths, source)
    signal_counts = collect_signal_counts(candidate, signal_paths)
    promoted_lists, promoted_scalars, promoted_reasons = resolve_promoted_values(
        candidate,
        signal_counts,
        max(1, int(args.promote_threshold or AUTO_PROMOTE_THRESHOLD)),
        force_promote,
    )
    profile_updated = merge_profile(
        structured,
        notes,
        candidate,
        promoted_lists,
        promoted_scalars,
        promoted_reasons,
    )

    if profile_updated:
        markdown = render_profile(structured, notes)
        write_text(target, markdown)

    result = {
        "ok": True,
        "path": str(target),
        "profile_updated": profile_updated,
        "promoted_values": {
            **{field: values for field, values in promoted_lists.items() if values},
            **promoted_scalars,
        },
        "signal_counts": {
            f"{field}:{value}": count for (field, value), count in signal_counts.items()
        },
        "updated_at": structured.get("updated_at", ""),
        "style_preferences": structured.get("style_preferences", []),
        "content_preferences": structured.get("content_preferences", []),
        "work_types": structured.get("work_types", []),
        "taboos": structured.get("taboos", []),
        "quality_tendency": structured.get("quality_tendency", ""),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
