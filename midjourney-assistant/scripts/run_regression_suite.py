import argparse
import contextlib
import importlib
import io
import json
import py_compile
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
ASSET_ROOT = SKILL_ROOT / "assets"
DEFAULT_CASES_PATH = ASSET_ROOT / "regression-cases.json"

PHASE5_ACCEPTANCE_AREAS = [
    {
        "key": "knowledge_chain_complete",
        "label": "知识主链完整",
        "regression_cases": [
            "logic::english_only",
            "logic::mode_consistency",
            "logic::specialized_task_routes",
            "logic::automatic_mode_minimal_integration",
        ],
    },
    {
        "key": "mode_consistency_established",
        "label": "模式一致性成立",
        "regression_cases": [
            "logic::mode_routing",
            "logic::mode_consistency",
            "logic::automatic_mode_minimal_integration",
        ],
    },
    {
        "key": "feedback_diagnosis_effective",
        "label": "反馈诊断有效",
        "regression_cases": [
            "logic::feedback_edit_model",
            "logic::manual_diagnosis_handoff",
            "logic::automatic_mode_minimal_integration",
        ],
    },
    {
        "key": "automatic_execution_keeps_knowledge",
        "label": "自动执行不破坏知识判断",
        "regression_cases": [
            "logic::mode_consistency",
            "logic::automatic_mode_minimal_integration",
            "logic::prompt_region_governance",
        ],
    },
]

PHASE5_LIVE_ACCEPTANCE_ITEMS = [
    {
        "key": "background_mode_real_submission",
        "label": "后台模式真实网页提交、轮询和完成判定",
        "why": "这部分依赖真实 Midjourney 页面、登录态和网络时序，内部回归只能验证编排与任务文件。",
    },
    {
        "key": "foreground_mode_real_reuse",
        "label": "前台模式对当前 Midjourney 页面的真实复用",
        "why": "这部分依赖真实窗口焦点、输入区位置和当前标签页状态，必须在桌面现场验收。",
    },
    {
        "key": "prompt_region_result_binding",
        "label": "prompt 对应区域与结果图区的现场绑定",
        "why": "这部分必须确认读取的是当前任务卡和真实截图，而不是脚本状态或历史页面内容。",
    },
    {
        "key": "isolated_browser_auth_recovery",
        "label": "独立浏览器登录态、挑战页与恢复路径",
        "why": "这部分取决于真实账号环境和站点挑战页，内部回归无法伪造完整登录链路。",
    },
    {
        "key": "final_capture_matches_page",
        "label": "最终截图与页面真实结果一致",
        "why": "这部分必须在真实页面上核对最终截图、任务卡和 prompt 的对应关系。",
    },
]

if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import common  # noqa: E402
import experience_distill  # noqa: E402
import feedback_apply  # noqa: E402
import manual_mode_prepare  # noqa: E402
import mode_route  # noqa: E402
import next_action_decide  # noqa: E402
import prompt_diagnose  # noqa: E402
import prompt_strategy_select  # noqa: E402
import project_context_merge  # noqa: E402
import solution_plan_build  # noqa: E402
import startup_route  # noqa: E402
import task_classify  # noqa: E402
import task_orchestrate  # noqa: E402
import template_candidate_upsert  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="运行 midjourney-assistant 阶段5内部回归；仅用于开发修改或明确验收，不用于正式生图运行"
    )
    parser.add_argument("--cases-file", help="回归样例矩阵路径")
    parser.add_argument("--output-file", help="回归结果输出路径")
    return parser.parse_args()


def load_cases(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("回归样例矩阵必须是 JSON 对象")
    return payload


def assert_true(condition, message: str):
    if not condition:
        raise AssertionError(message)


USER_MESSAGE_FORBIDDEN_MARKERS = [
    "checkpoint",
    "runtime_receipts",
    "runtime receipts",
    "profile_signal",
    "profile signal",
    "experience_distill",
    "experience distill",
    "template_candidate",
    "template candidate",
    "run_regression_suite",
    "内部回归",
    "检查任务",
    "检查编排",
    "检查脚本",
    "检查术语",
    "执行后端",
]


def assert_user_message_clean(payload: dict, expected: str):
    message = str(payload.get("message") or "")
    assert_true(message == expected, f"用户可见消息不符合预期：{message}")
    for marker in USER_MESSAGE_FORBIDDEN_MARKERS:
        assert_true(marker not in message, f"用户可见消息泄漏内部实现词：{marker}")


def run_command(command, *, input_text: str = ""):
    result = subprocess.run(
        command,
        input=input_text if input_text else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(SKILL_ROOT),
    )
    return result


def run_json_command(command, *, input_text: str = ""):
    result = run_command(command, input_text=input_text)
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip() or "命令执行失败")
    payload = json.loads((result.stdout or "").strip())
    if not isinstance(payload, dict):
        raise AssertionError("命令输出不是 JSON 对象")
    return payload


def build_python_script_command(script_name: str, arguments=None):
    return [sys.executable, str(SCRIPT_ROOT / script_name)] + list(arguments or [])


def build_node_check_command(relative_path: str):
    return ["node", "--check", str(SKILL_ROOT / relative_path)]


def build_powershell_parse_command(relative_path: str):
    script_path = str(SKILL_ROOT / relative_path)
    shell_command = common.get_powershell_command() or "powershell"
    ps = (
        "$tokens=$null; $errors=$null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$errors); "
        "if($errors -and $errors.Count -gt 0){ "
        "$errors | ForEach-Object { $_.Message }; exit 1 }"
    )
    return [shell_command, "-NoProfile", "-Command", ps]


def record_case(results, name: str, callback):
    try:
        detail = callback()
        results.append({"name": name, "status": "passed", "detail": detail})
    except Exception as exc:  # noqa: BLE001
        results.append(
            {
                "name": name,
                "status": "failed",
                "detail": {
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            }
        )


@contextlib.contextmanager
def patch_attrs(*patches):
    originals = []
    try:
        for module, name, value in patches:
            originals.append((module, name, getattr(module, name)))
            setattr(module, name, value)
        yield
    finally:
        for module, name, value in reversed(originals):
            setattr(module, name, value)


def syntax_smoke_cases(cases):
    results = []
    syntax = cases.get("syntax") or {}
    for relative_path in syntax.get("python") or []:
        path = SKILL_ROOT / relative_path

        def run_python_compile(path=path, relative_path=relative_path):
            py_compile.compile(str(path), doraise=True)
            return {"path": str(path), "kind": "python"}

        record_case(results, f"syntax_python::{relative_path}", run_python_compile)

    for relative_path in syntax.get("node") or []:
        path = SKILL_ROOT / relative_path

        def run_node_check(path=path, relative_path=relative_path):
            result = run_command(build_node_check_command(relative_path))
            if result.returncode != 0:
                raise AssertionError(result.stderr.strip() or result.stdout.strip() or "node --check 失败")
            return {"path": str(path), "kind": "node"}

        record_case(results, f"syntax_node::{relative_path}", run_node_check)

    for relative_path in syntax.get("powershell") or []:
        path = SKILL_ROOT / relative_path

        def run_powershell_parse(path=path, relative_path=relative_path):
            result = run_command(build_powershell_parse_command(relative_path))
            if result.returncode != 0:
                raise AssertionError(result.stderr.strip() or result.stdout.strip() or "PowerShell 语法解析失败")
            return {"path": str(path), "kind": "powershell"}

        record_case(results, f"syntax_powershell::{relative_path}", run_powershell_parse)

    return results


def case_startup_and_onboarding(case_payload):
    with tempfile.TemporaryDirectory(prefix="mj-regression-startup-") as temp_dir:
        temp_root = Path(temp_dir)
        state_path = temp_root / "bootstrap-state.json"
        environment_path = temp_root / "environment-notes.md"

        initial = run_json_command(
            build_python_script_command(
                "first_run_check.py",
                [
                    "--state-file",
                    str(state_path),
                    "--environment-file",
                    str(environment_path),
                ],
            )
        )
        assert_true(initial.get("needs_onboarding") is True, "首次检查应进入首次引导")
        assert_true(
            "自动模式默认走后台模式" in " ".join(initial.get("recommended_steps") or []),
            "首次引导默认说明必须强调后台模式",
        )
        assert_true(
            "不需要你先打开当前主浏览器页面" in " ".join(initial.get("recommended_steps") or []),
            "后台默认说明必须明确不需要先打开当前主浏览器页面",
        )
        assert_true(
            "先安装 Edge" in " ".join(initial.get("recommended_steps") or []),
            "首次引导必须说明无可用后台浏览器时建议先安装 Edge",
        )
        assert_true(
            "Windows 桌面环境" in " ".join(initial.get("recommended_steps") or []),
            "首次引导必须说明自动模式的本地运行环境前提",
        )
        environment_check = initial.get("environment_check") or {}
        assert_true(isinstance(environment_check, dict), "首次引导必须返回环境检查结果")
        for key in ["os_supported", "powershell_available", "node_available", "supported_browser_found"]:
            assert_true(key in environment_check, f"环境检查缺少字段：{key}")

        completed = run_json_command(
            build_python_script_command(
                "first_run_check.py",
                [
                    "--state-file",
                    str(state_path),
                    "--environment-file",
                    str(environment_path),
                    "--mark-complete",
                    "--host",
                    str(case_payload.get("complete_host") or "www.midjourney.com"),
                    "--browser",
                    str(case_payload.get("complete_browser") or "Edge"),
                    "--environment-summary",
                    str(case_payload.get("complete_environment_summary") or "回归测试环境就绪"),
                ],
            )
        )
        assert_true(completed.get("needs_onboarding") is False, "首次引导完成后不应继续 onboarding")
        assert_true(environment_path.exists(), "环境记录文件应被写入")
        return {
            "initial": initial,
            "completed": completed,
            "state_file": str(state_path),
            "environment_file": str(environment_path),
        }


def case_mode_routing(case_payloads):
    outputs = []
    for item in case_payloads:
        message = str(item.get("message") or "")
        startup = run_json_command(
            build_python_script_command("startup_route.py", ["--message", message])
        )
        routed = run_json_command(
            build_python_script_command("mode_route.py", ["--message", message])
        )
        expected_mode = str(item.get("selected_mode") or "")
        expected_backend = str(item.get("selected_backend") or "")
        assert_true(startup.get("has_task") is True, f"{message} 应被识别为带任务启动")
        assert_true(routed.get("selected_mode", "") == expected_mode, f"{message} 模式路由错误")
        assert_true(
            str(routed.get("selected_backend") or "") == expected_backend,
            f"{message} 执行后端路由错误",
        )
        outputs.append({"message": message, "startup": startup, "mode_route": routed})
    return {"cases": outputs}


def case_english_only(case_payload):
    valid_task = json.loads(json.dumps(case_payload.get("valid_task") or {}))
    invalid_task = json.loads(json.dumps(case_payload.get("invalid_task") or {}))

    updated_task, package = manual_mode_prepare.prepare_task_prompt(valid_task, force_regenerate=True)
    assert_true(common.is_english_prompt_text(package.get("prompt_text")), "英文唯一出口生成的 prompt 必须是英文")
    assert_true(updated_task.get("prompt_language") == "en", "英文唯一出口应写回 prompt_language=en")
    validation = common.validate_execution_prompt(package.get("prompt_text"))
    assert_true(validation.get("ok"), "最终 prompt 必须通过执行级质量闸门")
    lowered_prompt = str(package.get("prompt_text") or "").lower()
    for marker in [
        "target output",
        "preferred deliverable cues",
        "prioritize validating",
        "lock the subject and style",
        "createmale",
    ]:
        assert_true(marker not in lowered_prompt, f"最终 prompt 不应包含 {marker}")

    blocked_message = ""
    try:
        manual_mode_prepare.prepare_task_prompt(invalid_task, force_regenerate=True)
    except ValueError as exc:  # noqa: BLE001
        blocked_message = str(exc)
    assert_true(bool(blocked_message), "未收录中文术语必须阻断")

    valorant_task = json.loads(json.dumps(case_payload.get("valorant_style_task") or {}))
    valorant_updated, valorant_package = manual_mode_prepare.prepare_task_prompt(
        valorant_task, force_regenerate=True
    )
    valorant_prompt = str(valorant_package.get("prompt_text") or "")
    assert_true(common.is_english_prompt_text(valorant_prompt), "无畏契约风格样例必须生成英文 prompt")
    assert_true(
        "Valorant-inspired tactical hero-shooter design language" in valorant_prompt,
        "无畏契约风格必须直接转换成稳定英文描述",
    )
    assert_true("fashion-forward" in valorant_prompt, "现代时尚风格服装必须转成稳定英文描述")
    assert_true(
        valorant_updated.get("prompt_language") == "en",
        "无畏契约风格样例必须写回 prompt_language=en",
    )
    return {
        "valid_prompt": package.get("prompt_text", ""),
        "valorant_style_prompt": valorant_prompt,
        "invalid_block_reason": blocked_message,
    }


def case_feedback_edit(case_payload):
    task = {
        "task_id": "regression-feedback-task",
        "project_id": "regression-feedback-project",
        "mode": "automatic",
        "prompt_policy": "english_only",
        "round_index": 2,
        "prompt_version": 3,
        "brief": {
            "goal": "做一个角色设计",
            "must_have": ["半身构图"],
            "style_bias": ["写实"],
            "must_not_have": [],
        },
    }
    result = feedback_apply.apply_feedback_to_task(task, str(case_payload.get("message") or ""), increment_round=True)
    updated_task = result["task"]
    latest_feedback = updated_task.get("latest_feedback") or {}
    assert_true(latest_feedback.get("scope") == "project", "这条反馈应识别为项目级")
    assert_true("全身角色展示" in (updated_task.get("brief") or {}).get("must_have", []), "反馈应替换成全身角色展示")
    assert_true("半身构图" not in (updated_task.get("brief") or {}).get("must_have", []), "互斥约束未被替换干净")
    assert_true(
        (updated_task.get("global_policy_patch") or {}).get("prompt_policy") == "english_only",
        "全局策略应锁到 english_only",
    )
    assert_true(
        "游戏设计风格" in (updated_task.get("project_strategy_patch") or {}).get("persistent_style_bias", []),
        "项目策略补丁应写入持久风格",
    )
    return {
        "feedback_summary": result.get("feedback_summary", ""),
        "latest_feedback": latest_feedback,
        "project_strategy_patch": updated_task.get("project_strategy_patch") or {},
        "global_policy_patch": updated_task.get("global_policy_patch") or {},
    }


def case_manual_diagnosis(case_payload):
    task = json.loads(json.dumps(case_payload.get("base_task") or {}))
    feedback_message = str(case_payload.get("feedback_message") or "")
    feedback_result = feedback_apply.apply_feedback_to_task(task, feedback_message, increment_round=True)
    diagnosed_task, diagnosis_report = prompt_diagnose.build_diagnosis_report(feedback_result["task"])
    prompt_task, prompt_package = prompt_strategy_select.build_prompt_package(diagnosed_task, force_regenerate=True)
    manual_task, handoff_package = manual_mode_prepare.prepare_task_prompt(prompt_task, force_regenerate=False)

    diagnosis_summary = handoff_package.get("diagnosis_summary") if isinstance(handoff_package.get("diagnosis_summary"), dict) else {}
    iteration_advice = handoff_package.get("iteration_advice") or []
    submission_notes = handoff_package.get("submission_notes") or []
    feedback_requirements = handoff_package.get("feedback_requirements") or []
    prompt_text = str(handoff_package.get("prompt_text") or "")

    assert_true(bool(diagnosis_summary.get("change_list")), "手动模式交付必须保留 diagnosis_summary.change_list")
    assert_true(bool(iteration_advice), "手动模式交付必须给出 iteration_advice")
    assert_true(any("执行策略：" in item for item in iteration_advice), "iteration_advice 应包含执行策略")
    assert_true(any("本轮目标：" in item for item in iteration_advice), "iteration_advice 应包含本轮目标")
    assert_true(any("执行策略：" in item for item in submission_notes), "submission_notes 应消费 diagnosis_report")
    assert_true(any("修改项" in item for item in feedback_requirements), "反馈要求应提示用户验证修改项")
    assert_true(common.is_english_prompt_text(prompt_text), "手动模式最终 prompt 仍必须保持英文唯一出口")
    assert_true(
        any(delta in prompt_text for delta in common.normalize_string_list(diagnosis_summary.get("next_round_prompt_delta"))),
        "手动模式 prompt 应直接吸收 diagnosis_report 的 prompt delta",
    )
    feedback_summary = str(handoff_package.get("feedback_summary") or "")
    assert_true("改成全身" in feedback_summary, "手动模式 feedback_summary 应包含全身修改")
    assert_true("改成正面" in feedback_summary, "手动模式 feedback_summary 应包含正面修改")
    assert_true("游戏设计风格" in feedback_summary, "手动模式 feedback_summary 应保留风格修改重点")
    assert_true(manual_task.get("prompt_package") == handoff_package, "手动模式任务对象应回写增强后的 prompt_package")

    return {
        "diagnosis_report": diagnosis_report,
        "prompt_text": prompt_text,
        "iteration_advice": iteration_advice,
        "submission_notes": submission_notes,
        "feedback_requirements": feedback_requirements,
    }


def case_mode_consistency(case_payload):
    base_task = json.loads(json.dumps(case_payload.get("base_task") or {}))
    automatic_task = dict(base_task)
    automatic_task["mode"] = "automatic"
    automatic_task["task_phase"] = automatic_task.get("task_phase") or "received"
    automatic_task, automatic_package, knowledge_snapshot = task_orchestrate.run_knowledge_pipeline(
        automatic_task,
        force_regenerate=False,
    )
    assert_true(bool(knowledge_snapshot.get("task_model")), "模式一致性回归必须先产出 task_model")
    assert_true(bool(knowledge_snapshot.get("solution_plan")), "模式一致性回归必须先产出 solution_plan")
    assert_true(
        common.is_english_prompt_text(automatic_package.get("prompt_text")),
        "共享 prompt_package 必须保持英文唯一出口",
    )

    manual_seed = json.loads(json.dumps(automatic_task))
    manual_seed["mode"] = "manual"
    manual_task, manual_package = manual_mode_prepare.prepare_task_prompt(manual_seed, force_regenerate=False)

    assert_true(
        manual_task.get("task_model") == automatic_task.get("task_model"),
        "手动模式不应改写知识主链给出的 task_model",
    )
    assert_true(
        manual_task.get("solution_plan") == automatic_task.get("solution_plan"),
        "手动模式不应改写知识主链给出的 solution_plan",
    )
    assert_true(
        str(manual_package.get("prompt_text") or "").strip() == str(automatic_package.get("prompt_text") or "").strip(),
        "手动模式与自动模式必须共享同一条最终 prompt_text",
    )
    assert_true(
        str(manual_package.get("brief_summary") or "").strip() == str(automatic_package.get("brief_summary") or "").strip(),
        "手动模式与自动模式必须共享同一份 brief_summary",
    )
    return {
        "task_model": automatic_task.get("task_model") or {},
        "solution_plan": automatic_task.get("solution_plan") or {},
        "shared_prompt_text": automatic_package.get("prompt_text", ""),
        "manual_consultant_summary": manual_package.get("consultant_summary", ""),
    }


def case_project_workflow(case_payload):
    task = json.loads(json.dumps(case_payload.get("task") or {}))
    with tempfile.TemporaryDirectory(prefix="mj-regression-project-") as temp_dir:
        project_path = Path(temp_dir) / "project.md"
        with patch_attrs(
            (project_context_merge, "project_memory_path", lambda project_id: project_path),
        ):
            existing = project_context_merge.empty_context(task["project_id"])
            context = project_context_merge.build_context_from_task(task, existing)
            project_path.write_text(project_context_merge.render_project_context(context), encoding="utf-8")
            reloaded = project_context_merge.load_project_context(project_path, task["project_id"])
        assert_true(bool(reloaded.get("project_stage")), "项目阶段不能为空")
        assert_true(bool(reloaded.get("workflow_status")), "项目 workflow_status 不能为空")
        assert_true(bool(reloaded.get("active_batch_label")), "项目批次标签不能为空")
        assert_true(bool(reloaded.get("open_items")), "项目 open_items 应有内容")
        assert_true(bool(reloaded.get("template_candidate_keys")), "项目应保留模板候选键")
        return {"project_file": str(project_path), "project_context": reloaded}


def case_template_candidate(case_payload):
    record = json.loads(json.dumps(case_payload.get("record") or {}))
    threshold = int(case_payload.get("threshold") or 2)
    with tempfile.TemporaryDirectory(prefix="mj-regression-template-") as temp_dir:
        temp_root = Path(temp_dir)
        patterns_file = temp_root / "task-patterns.md"
        review_queue_file = temp_root / "review-queue.jsonl"
        candidate_dir = temp_root / "task-templates"

        first = template_candidate_upsert.upsert_template_candidate(
            record,
            threshold=threshold,
            patterns_file=patterns_file,
            review_queue_file=review_queue_file,
            candidate_dir=candidate_dir,
        )
        second = template_candidate_upsert.upsert_template_candidate(
            record,
            threshold=threshold,
            patterns_file=patterns_file,
            review_queue_file=review_queue_file,
            candidate_dir=candidate_dir,
        )
        assert_true(first.get("candidate_generated") is False, "首次写入不应立刻生成模板候选")
        assert_true(second.get("candidate_generated") is True, "达到阈值后应生成模板候选")
        assert_true(Path(second.get("candidate_file") or "").exists(), "模板候选文件应存在")
        queue_lines = review_queue_file.read_text(encoding="utf-8-sig").splitlines()
        assert_true(any("template_candidate" in line for line in queue_lines), "review queue 应追加模板候选记录")
        patterns_text = patterns_file.read_text(encoding="utf-8-sig")
        assert_true('"count": 2' in patterns_text or '"count": 3' in patterns_text, "任务模式统计应累计")
        return {
            "first": first,
            "second": second,
            "review_queue_file": str(review_queue_file),
            "patterns_file": str(patterns_file),
        }


def case_profile_signal(case_payload):
    record = json.loads(json.dumps(case_payload.get("record") or {}))
    with tempfile.TemporaryDirectory(prefix="mj-regression-profile-") as temp_dir:
        temp_root = Path(temp_dir)
        profile_path = temp_root / "profile.md"
        preference_signals = temp_root / "preference-signals.jsonl"
        taboo_signals = temp_root / "taboo-signals.jsonl"
        distilled_file = temp_root / "distilled-patterns.md"
        failure_file = temp_root / "failure-patterns.md"
        site_file = temp_root / "site-changelog.md"
        record_path = temp_root / "record.json"
        candidate_path = temp_root / "candidate.json"
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        extracted = run_json_command(
            build_python_script_command("profile_signal_extract.py", ["--input-file", str(record_path)])
        )
        assert_true(extracted.get("skipped") is False, "成功 run_record 应产出画像候选")
        candidate = extracted.get("candidate") or {}
        candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        first_merge = run_json_command(
            build_python_script_command(
                "profile_merge.py",
                [
                    "--input-file",
                    str(candidate_path),
                    "--output-file",
                    str(profile_path),
                    "--preference-signals-file",
                    str(preference_signals),
                    "--taboo-signals-file",
                    str(taboo_signals),
                ],
            )
        )
        second_merge = run_json_command(
            build_python_script_command(
                "profile_merge.py",
                [
                    "--input-file",
                    str(candidate_path),
                    "--output-file",
                    str(profile_path),
                    "--preference-signals-file",
                    str(preference_signals),
                    "--taboo-signals-file",
                    str(taboo_signals),
                ],
            )
        )
        assert_true(bool(second_merge.get("promoted_values")), "累计两次 signal 后应自动提升进稳定画像")

        distilled = run_json_command(
            build_python_script_command(
                "experience_distill.py",
                [
                    "--input-file",
                    str(record_path),
                    "--distilled-file",
                    str(distilled_file),
                    "--failure-file",
                    str(failure_file),
                    "--site-file",
                    str(site_file),
                ],
            )
        )
        assert_true(
            (distilled.get("receipts") or {}).get("distilled_patterns", {}).get("updated") is True,
            "成功 run_record 应写入蒸馏经验",
        )
        return {
            "extracted": extracted,
            "first_merge": first_merge,
            "second_merge": second_merge,
            "distilled": distilled,
            "profile_path": str(profile_path),
        }


def run_task_orchestrate_with_patches(task_payload, message: str, execute_automatic: bool):
    temp_dir = tempfile.TemporaryDirectory(prefix="mj-regression-orchestrate-")
    temp_root = Path(temp_dir.name)
    task_file = temp_root / "task.json"
    task_file.write_text(json.dumps(task_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def fake_merge_project_context(task, writeback=False):
        updated = dict(task)
        snapshot = {
            "project_id": updated.get("project_id", ""),
            "project_stage": updated.get("project_stage", "refine"),
            "workflow_status": "active",
            "active_batch_label": "regression-batch",
            "template_candidate_keys": list(updated.get("template_candidate_keys") or []),
            "updated_at": common.now_iso(),
        }
        updated["project_context_snapshot"] = snapshot
        return updated, {"ok": True, "writeback": writeback, "project_context_snapshot": snapshot}

    def fake_save_task_outputs(task, task_file="", checkpoint_file=""):
        if task_file:
            Path(task_file).write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "path": checkpoint_file or "checkpoint.json"}

    def fake_ensure_memory_snapshot(task):
        updated = dict(task)
        updated["memory_snapshot"] = {"user_profile": {"structured": {"style_preferences": ["游戏设计风格"]}}}
        return updated, updated["memory_snapshot"]

    def fake_attach_memory_consumption_snapshot(task, memory_snapshot):
        updated = dict(task)
        snapshot = {"sources_applied": ["user_profile"], "profile_style_preferences": ["游戏设计风格"]}
        updated["memory_snapshot"] = memory_snapshot
        updated["memory_consumption_snapshot"] = snapshot
        return updated, snapshot

    def fake_prepare_task_prompt(task, force_regenerate=False):
        updated = dict(task)
        updated["current_prompt"] = "full body game character concept art, game design style"
        updated["prompt_version"] = int(updated.get("prompt_version") or 1) + (1 if force_regenerate else 0)
        updated["prompt_policy"] = "english_only"
        updated["prompt_language"] = "en"
        package = {
            "brief_summary": "目标：角色设计；必须包含：全身角色展示；风格倾向：游戏设计风格",
            "prompt_text": updated["current_prompt"],
            "parameter_suggestions": ["先确认主体和风格方向"],
            "submission_notes": ["保持设置不变"],
            "feedback_requirements": ["回传截图"],
            "prompt_stage": "refine",
        }
        updated["prompt_package"] = package
        return updated, package

    def fake_backend_health(task):
        return {"backend": task.get("automatic_execution_backend", ""), "checked_at": common.now_iso()}

    def fake_node_script(script_name, arguments):
        task_path = Path(arguments[arguments.index("--task-file") + 1])
        task_payload = json.loads(task_path.read_text(encoding="utf-8-sig"))
        assert_true(bool(((task_payload.get("prompt_package") or {}).get("prompt_text") or "").strip()), "自动模式必须把 prompt_package 写入执行任务文件")
        return {
            "ok": True,
            "completed": True,
            "result_available": True,
            "generation_observed": True,
            "automatic_execution_backend": "isolated_browser",
            "prompt_source": "prompt_package",
            "result_summary": "style is unstable and not full body",
            "should_continue": True,
            "final_capture": "isolated-final.png",
            "window_state": {},
        }

    def fake_powershell_script(script_name, arguments):
        if script_name == "midjourney_isolated_browser_setup.ps1":
            return {
                "ok": True,
                "launched": False,
                "process_id": 12345,
                "port": 9230,
                "profile_dir": "isolated-profile",
                "page_url": "https://www.midjourney.com/imagine",
                "state_path": "runtime-state.json",
                "browser_key": "edge",
                "browser_name": "Edge",
                "browser_path": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
                "browser_process_name": "msedge.exe",
                "browser_detection_source": "state_reuse",
            }
        task_path = Path(arguments[arguments.index("-TaskFile") + 1])
        task_payload = json.loads(task_path.read_text(encoding="utf-8-sig"))
        assert_true(bool(((task_payload.get("prompt_package") or {}).get("prompt_text") or "").strip()), "前台自动模式必须把 prompt_package 写入执行任务文件")
        return {
            "ok": True,
            "completed": True,
            "result_available": True,
            "generation_observed": True,
            "automatic_execution_backend": "window_uia",
            "prompt_source": "prompt_package",
            "result_summary": "style is unstable and not full body",
            "should_continue": True,
            "final_capture": "foreground-final.png",
            "window_state": {"window_handle": "0x123"},
        }

    def fake_append_run_record(record):
        return {"ok": True, "recorded": True, "task_id": record.get("task_id", "")}

    def fake_run_summary(record):
        return {"ok": True, "run_verdict": record.get("run_verdict", "success"), "summary": "回归摘要"}

    def fake_profile_signal(record):
        return {"ok": True, "candidate": {"style_preferences": ["游戏设计风格"]}}

    def fake_profile_merge(candidate):
        return {"ok": True, "profile_updated": True, "promoted_values": {"style_preferences": ["游戏设计风格"]}}

    def fake_experience_distill(record):
        return {"ok": True, "receipts": {"distilled_patterns": {"updated": True}}}

    def fake_template_candidate(record):
        return {
            "ok": True,
            "candidate_key": "automatic|isolated_browser|english_only|角色设计|游戏设计风格",
            "candidate_generated": True,
            "review_queue_updated": True,
        }

    argv = [
        "task_orchestrate.py",
        "--task-file",
        str(task_file),
        "--message",
        message,
    ]
    if execute_automatic:
        argv.append("--execute-automatic")

    buffer = io.StringIO()
    with patch_attrs(
        (task_orchestrate, "merge_project_context", fake_merge_project_context),
        (task_orchestrate, "save_task_outputs", fake_save_task_outputs),
        (task_orchestrate, "ensure_memory_snapshot", fake_ensure_memory_snapshot),
        (task_orchestrate, "attach_memory_consumption_snapshot", fake_attach_memory_consumption_snapshot),
        (task_orchestrate, "prepare_task_prompt", fake_prepare_task_prompt),
        (task_orchestrate, "build_backend_health_snapshot", fake_backend_health),
        (task_orchestrate, "run_node_script", fake_node_script),
        (task_orchestrate, "run_powershell_script", fake_powershell_script),
        (task_orchestrate, "append_run_record", fake_append_run_record),
        (task_orchestrate, "build_run_summary", fake_run_summary),
        (task_orchestrate, "extract_profile_signal", fake_profile_signal),
        (task_orchestrate, "merge_profile_candidate", fake_profile_merge),
        (task_orchestrate, "distill_experience", fake_experience_distill),
        (task_orchestrate, "upsert_template_candidate", fake_template_candidate),
    ):
        with contextlib.redirect_stdout(buffer):
            old_argv = sys.argv[:]
            try:
                sys.argv = argv
                task_orchestrate.main()
            finally:
                sys.argv = old_argv
    temp_dir.cleanup()
    return json.loads(buffer.getvalue().strip())


def case_automatic_integration():
    base_task = {
        "task_id": "regression-auto-task",
        "project_id": "regression-auto-project",
        "startup_phase": "ready",
        "task_phase": "received",
        "mode": "automatic",
        "prompt_policy": "english_only",
        "prompt_language": "en",
        "round_index": 1,
        "prompt_version": 1,
        "goal": "做一个角色设计",
        "raw_request": "生成一个任意角色设计",
        "brief": {
            "goal": "做一个角色设计",
            "must_have": ["全身角色展示"],
            "style_bias": ["游戏设计风格"],
            "must_not_have": [],
        },
    }
    isolated_task = dict(base_task)
    isolated_task["automatic_execution_backend"] = "isolated_browser"
    isolated = run_task_orchestrate_with_patches(isolated_task, "继续", execute_automatic=True)
    assert_true(isolated.get("orchestration_status") == "automatic_round_executed", "后台自动模式应完成最小集成执行")
    assert_user_message_clean(isolated, "已按修改完成生成。")
    assert_true(((isolated.get("auto_result") or {}).get("prompt_source") == "prompt_package"), "后台自动模式应显式消费共享 prompt_package")
    assert_true(
        "style_drift" in common.normalize_string_list((isolated.get("diagnosis_report") or {}).get("observed_issues")),
        "后台自动模式结果回读后应重跑 diagnosis_report",
    )
    receipts = isolated.get("runtime_receipts") or {}
    for key in ["checkpoint", "run_log", "run_summary", "profile_signal", "profile_merge", "experience_distill", "template_candidate"]:
        assert_true(key in receipts, f"后台自动模式缺少 {key} receipt")

    ready_task = dict(base_task)
    ready_task["automatic_execution_backend"] = "isolated_browser"
    ready = run_task_orchestrate_with_patches(ready_task, "自动模式", execute_automatic=False)
    assert_true(ready.get("orchestration_status") == "automatic_ready_to_submit", "自动模式待执行编排应保持短消息")
    assert_user_message_clean(ready, "已接住需求，正在后台生成。")

    ready_feedback_task = dict(base_task)
    ready_feedback_task["automatic_execution_backend"] = "isolated_browser"
    ready_feedback = run_task_orchestrate_with_patches(ready_feedback_task, "继续", execute_automatic=False)
    assert_true(ready_feedback.get("orchestration_status") == "automatic_ready_to_submit", "反馈续跑待执行编排应保持短消息")
    assert_user_message_clean(ready_feedback, "已接住修改，正在后台生成。")

    foreground_task = dict(base_task)
    foreground_task["automatic_execution_backend"] = "window_uia"
    foreground = run_task_orchestrate_with_patches(foreground_task, "继续", execute_automatic=True)
    assert_true(foreground.get("orchestration_status") == "automatic_round_executed", "前台自动模式应完成最小集成执行")
    assert_user_message_clean(foreground, "已按修改完成生成。")
    assert_true(((foreground.get("auto_result") or {}).get("prompt_source") == "prompt_package"), "前台自动模式应显式消费共享 prompt_package")
    assert_true(
        "style_drift" in common.normalize_string_list((foreground.get("diagnosis_report") or {}).get("observed_issues")),
        "前台自动模式结果回读后应重跑 diagnosis_report",
    )
    assert_true(
        (((foreground.get("task") or {}).get("artifacts") or {}).get("automatic_execution_backend") == "window_uia"),
        "前台自动模式应保留 window_uia 执行后端",
    )
    return {
        "isolated_browser": isolated,
        "automatic_ready": ready,
        "automatic_ready_feedback": ready_feedback,
        "window_uia": foreground,
    }


def case_governance(case_payload):
    results = []
    for blocked_reason in case_payload.get("blocked_reasons") or []:
        governance = common.classify_execution_governance(
            {"blocked_reason": blocked_reason, "ok": False, "completed": False, "result_available": False},
            "isolated_browser",
        )
        assert_true(governance.get("recoverability") == "recoverable_ui_block", f"{blocked_reason} 应归为可恢复 UI 阻塞")
        assert_true(governance.get("recommended_action") == "resolve_ui_block", f"{blocked_reason} 推荐动作错误")
        results.append(governance)
    return {"governance_results": results}


def case_block_messages():
    browser_missing_message = task_orchestrate.build_user_facing_block_message(
        {"blocked_reason": "no_supported_browser_found", "ok": False, "completed": False, "result_available": False}
    )
    assert_true(
        browser_missing_message == "这台电脑没有检测到可用的后台浏览器。建议先安装 Edge，再继续首次测试或后台自动生成。",
        f"无浏览器阻塞提示错误：{browser_missing_message}",
    )
    governance = common.classify_execution_governance(
        {"blocked_reason": "no_supported_browser_found", "ok": False, "completed": False, "result_available": False},
        "isolated_browser",
    )
    assert_true(governance.get("recommended_action") == "install_supported_browser", "无浏览器阻塞应建议安装可用浏览器")
    assert_true(governance.get("verdict_hint") == "blocked_by_context", "无浏览器阻塞应归为上下文阻塞")
    assert_true(
        task_orchestrate.build_user_facing_block_message({"blocked_reason": "unsupported_platform"}) == "当前自动模式只支持 Windows 桌面环境；这台电脑请改用手动模式，或换到 Windows 电脑再继续。",
        "平台阻塞提示错误",
    )
    assert_true(
        task_orchestrate.build_user_facing_block_message({"blocked_reason": "powershell_runtime_missing"}) == "这台电脑缺少可用的 PowerShell，自动模式暂时不可用。",
        "PowerShell 阻塞提示错误",
    )
    assert_true(
        task_orchestrate.build_user_facing_block_message({"blocked_reason": "node_runtime_missing"}) == "这台电脑缺少 Node.js，后台自动模式暂时不可用。",
        "Node 阻塞提示错误",
    )
    return {
        "message": browser_missing_message,
        "governance": governance,
    }


def case_desktop_browser_coverage():
    browser_preflight_path = SKILL_ROOT / "scripts" / "browser_preflight.ps1"
    content = browser_preflight_path.read_text(encoding="utf-8-sig")
    for process_name in ['"msedge"', '"chrome"', '"brave"', '"vivaldi"', '"arc"']:
        assert_true(process_name in content, f"前台浏览器预检缺少：{process_name}")
    return {
        "browser_preflight_path": str(browser_preflight_path),
        "covered_processes": ["msedge", "chrome", "brave", "vivaldi", "arc"],
    }


def run_specialized_prompt_chain(task_payload):
    task = json.loads(json.dumps(task_payload or {}))
    task, task_model = task_classify.classify_task(task)
    task, solution_plan = solution_plan_build.build_solution_plan(task)
    task, prompt_package = prompt_strategy_select.build_prompt_package(task, force_regenerate=True)
    return task, task_model, solution_plan, prompt_package


def case_specialized_task_routes(case_payload):
    outputs = {}
    for case_name, item in (case_payload or {}).items():
        task, task_model, solution_plan = None, None, None
        prompt_package = {}
        prompt_error = ""
        try:
            task, task_model, solution_plan, prompt_package = run_specialized_prompt_chain(item.get("task") or {})
        except ValueError as exc:  # noqa: BLE001
            prompt_error = str(exc)
            base_task = json.loads(json.dumps(item.get("task") or {}))
            task, task_model = task_classify.classify_task(base_task)
            task, solution_plan = solution_plan_build.build_solution_plan(task)

        assert_true(
            task_model.get("task_type") == item.get("expected_task_type"),
            f"{case_name} task_type 错误：{task_model.get('task_type')}",
        )
        if str(item.get("expected_revision_mode") or "").strip():
            assert_true(
                str(task_model.get("revision_mode") or "").strip() == str(item.get("expected_revision_mode") or "").strip(),
                f"{case_name} revision_mode 错误：{task_model.get('revision_mode')}",
            )
        assert_true(
            solution_plan.get("primary_strategy") == item.get("expected_strategy"),
            f"{case_name} primary_strategy 错误：{solution_plan.get('primary_strategy')}",
        )
        assert_true(
            str((solution_plan.get("parameter_strategy") or {}).get("preset_key") or "") == str(item.get("expected_preset") or ""),
            f"{case_name} preset_key 错误：{(solution_plan.get('parameter_strategy') or {}).get('preset_key')}",
        )
        if str(item.get("expected_prompt_error_contains") or "").strip():
            assert_true(
                str(item.get("expected_prompt_error_contains") or "").strip() in prompt_error,
                f"{case_name} prompt 错误信息不符合预期：{prompt_error}",
            )
        else:
            prompt_text = str(prompt_package.get("prompt_text") or "")
            for term in item.get("required_prompt_terms") or []:
                assert_true(term in prompt_text, f"{case_name} prompt 缺少：{term}")
            for term in item.get("forbidden_prompt_terms") or []:
                assert_true(term not in prompt_text, f"{case_name} prompt 不应包含：{term}")
        for question in item.get("required_open_questions") or []:
            assert_true(
                question in common.normalize_string_list(task_model.get("open_questions")),
                f"{case_name} open_questions 缺少：{question}",
            )
        if prompt_package:
            for snippet in item.get("required_submission_notes") or []:
                assert_true(
                    any(snippet in note for note in prompt_package.get("submission_notes") or []),
                    f"{case_name} submission_notes 缺少：{snippet}",
                )
        outputs[case_name] = {
            "task_model": task_model,
            "solution_plan": solution_plan,
            "prompt_package": prompt_package,
            "prompt_error": prompt_error,
        }
    return outputs


def case_colorway_next_action(case_payload):
    payload = json.loads(json.dumps((case_payload or {}).get("payload") or {}))
    decision = next_action_decide.decide_next_action(payload)
    assert_true(decision.get("run_verdict") == "success", "配色任务出结果后应收敛为 success")
    assert_true(decision.get("next_action") == "await_user_feedback", "配色任务出结果后应立即等待用户反馈")
    assert_true(decision.get("should_continue") is False, "配色任务默认不应自动继续下一轮")
    return {"decision": decision}


def build_summary(results):
    total = len(results)
    passed = sum(1 for item in results if item.get("status") == "passed")
    failed = total - passed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
    }


def build_phase5_acceptance_report(results):
    status_map = {str(item.get("name") or ""): str(item.get("status") or "") for item in results}
    areas = []
    for area in PHASE5_ACCEPTANCE_AREAS:
        covered_cases = []
        for case_name in area["regression_cases"]:
            covered_cases.append(
                {
                    "case": case_name,
                    "status": status_map.get(case_name, "missing"),
                }
            )
        areas.append(
            {
                "key": area["key"],
                "label": area["label"],
                "passed": all(item["status"] == "passed" for item in covered_cases),
                "covered_cases": covered_cases,
            }
        )
    return {
        "ready_for_live_acceptance": all(area["passed"] for area in areas),
        "regression_entrypoints": [
            "assets/regression-cases.json",
            "scripts/run_regression_suite.py",
            "references/regression-matrix.md",
            "references/live-acceptance-runbook.md",
        ],
        "areas": areas,
        "live_acceptance_required": PHASE5_LIVE_ACCEPTANCE_ITEMS,
    }


def main():
    args = parse_args()
    cases_path = Path(args.cases_file) if args.cases_file else DEFAULT_CASES_PATH
    cases = load_cases(cases_path)

    results = []
    results.extend(syntax_smoke_cases(cases))

    logic_cases = cases.get("logic_cases") or {}
    record_case(results, "logic::startup_and_onboarding", lambda: case_startup_and_onboarding(logic_cases.get("startup") or {}))
    record_case(results, "logic::mode_routing", lambda: case_mode_routing(logic_cases.get("mode_routing") or []))
    record_case(results, "logic::english_only", lambda: case_english_only(logic_cases.get("english_only") or {}))
    record_case(results, "logic::feedback_edit_model", lambda: case_feedback_edit(logic_cases.get("feedback") or {}))
    record_case(results, "logic::manual_diagnosis_handoff", lambda: case_manual_diagnosis(logic_cases.get("manual_diagnosis") or {}))
    record_case(results, "logic::mode_consistency", lambda: case_mode_consistency(logic_cases.get("mode_consistency") or {}))
    record_case(results, "logic::colorway_next_action", lambda: case_colorway_next_action(logic_cases.get("colorway_next_action") or {}))
    record_case(results, "logic::specialized_task_routes", lambda: case_specialized_task_routes(logic_cases.get("specialized_task_routes") or {}))
    record_case(results, "logic::project_workflow", lambda: case_project_workflow(logic_cases.get("project_workflow") or {}))
    record_case(results, "logic::template_candidate", lambda: case_template_candidate(logic_cases.get("template_candidate") or {}))
    record_case(results, "logic::profile_signal_chain", lambda: case_profile_signal(logic_cases.get("profile_signal") or {}))
    record_case(results, "logic::automatic_mode_minimal_integration", case_automatic_integration)
    record_case(results, "logic::prompt_region_governance", lambda: case_governance(logic_cases.get("governance") or {}))
    record_case(results, "logic::block_messages", case_block_messages)
    record_case(results, "logic::desktop_browser_coverage", case_desktop_browser_coverage)

    summary = build_summary(results)
    output = {
        "ok": summary["failed"] == 0,
        "summary": summary,
        "phase5_acceptance": build_phase5_acceptance_report(results),
        "cases_file": str(cases_path),
        "results": results,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    if summary["failed"] != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
