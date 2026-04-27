import argparse
import contextlib
import importlib
import io
import json
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
ASSET_ROOT = SKILL_ROOT / "assets"
DEFAULT_CASES_PATH = ASSET_ROOT / "regression-cases.json"

HEALTH_AREAS = [
    {
        "key": "knowledge_chain_complete",
        "label": "知识主链完整",
        "required_cases": [
            "logic::english_only",
            "logic::mode_consistency",
            "logic::specialized_task_routes",
            "logic::automatic_mode_minimal_integration",
        ],
    },
    {
        "key": "mode_consistency_established",
        "label": "模式一致性成立",
        "required_cases": [
            "logic::mode_routing",
            "logic::mode_consistency",
            "logic::automatic_mode_minimal_integration",
        ],
    },
    {
        "key": "feedback_diagnosis_effective",
        "label": "反馈诊断有效",
        "required_cases": [
            "logic::feedback_edit_model",
            "logic::manual_diagnosis_handoff",
            "logic::automatic_mode_minimal_integration",
        ],
    },
    {
        "key": "automatic_execution_keeps_knowledge",
        "label": "自动执行不破坏知识判断",
        "required_cases": [
            "logic::mode_consistency",
            "logic::reference_knowledge_consumption",
            "logic::automatic_mode_minimal_integration",
            "logic::prompt_region_governance",
        ],
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
import reference_knowledge_retrieve  # noqa: E402
import solution_plan_build  # noqa: E402
import startup_route  # noqa: E402
import task_classify  # noqa: E402
import task_orchestrate  # noqa: E402
import template_candidate_upsert  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="运行 midjourney-assistant 检查套件；仅用于开发修改或明确检查，不用于正式生图运行"
    )
    parser.add_argument("--cases-file", help="检查样例路径")
    parser.add_argument("--output-file", help="检查结果输出路径")
    return parser.parse_args()


def load_cases(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("检查样例必须是 JSON 对象")
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
            compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")
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


def case_skill_entry_and_syntax_contract(cases):
    skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    assert_true(
        "如果 `startup_route.py` 返回 `has_task=true`，立即调用：" in skill_text
        and "scripts/task_orchestrate.py" in skill_text,
        "SKILL.md 必须明确真实任务直接交给 task_orchestrate.py",
    )
    forbidden_patterns = [
        r"startup_route\.py[^\n]{0,160}task_state_init\.py[^\n]{0,160}接住",
        r"task_state_init\.py[^\n]{0,160}接住这条任务",
    ]
    for pattern in forbidden_patterns:
        assert_true(
            re.search(pattern, skill_text, flags=re.DOTALL) is None,
            f"SKILL.md 不能要求外层手工用内部脚本接任务：{pattern}",
        )

    mentioned_scripts = sorted(set(re.findall(r"scripts/[A-Za-z0-9_.-]+", skill_text)))
    syntax = cases.get("syntax") or {}
    syntax_scripts = sorted(set((syntax.get("python") or []) + (syntax.get("node") or []) + (syntax.get("powershell") or [])))
    missing = [script for script in mentioned_scripts if script not in syntax_scripts]
    assert_true(not missing, "SKILL.md 可调用脚本未进入 syntax smoke：" + ", ".join(missing))
    return {
        "mentioned_scripts": mentioned_scripts,
        "syntax_scripts": syntax_scripts,
    }


def case_empty_invocation_startup_contract():
    skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    first_run_text = (SKILL_ROOT / "references" / "first-run.md").read_text(encoding="utf-8-sig")
    assert_true(
        "用户只输入 `$midjourney-assistant` 时，这是启动助手，不是检查 skill 源码。" in skill_text,
        "SKILL.md 必须明确空调用是启动助手，不是源码检查",
    )
    assert_true(
        "不要把首次启动解释成读取 skill 文档" in first_run_text,
        "first-run.md 必须禁止把首次启动解释成读取 skill 文档",
    )

    fixed_section_start = skill_text.index("## 固定启动说明")
    fenced_start = skill_text.index("```text", fixed_section_start) + len("```text")
    fenced_end = skill_text.index("```", fenced_start)
    startup_text = skill_text[fenced_start:fenced_end].strip()

    required_fragments = [
        "我是 Midjourney 使用助手。",
        "**完全访问权限**",
        "自动模式",
        "手动模式",
        "模板、画像、日志、经验",
    ]
    forbidden_fragments = [
        "SKILL.md",
        "Get-Content",
        "读取",
        "UTF-8",
        "GBK",
        "脚本",
        "命令",
        "C:\\Users",
        "runtime",
        "checkpoint",
        "修复依赖",
        "安装系统软件",
    ]
    for fragment in required_fragments:
        assert_true(fragment in startup_text, f"固定启动说明缺少必要内容：{fragment}")
    for fragment in forbidden_fragments:
        assert_true(fragment not in startup_text, f"固定启动说明不应泄漏内部过程：{fragment}")
    return {
        "required_fragments": required_fragments,
        "forbidden_fragments": forbidden_fragments,
    }


def case_memory_writeback_trigger_contract():
    scoped_messages = {
        "继续并记录这次结果": {"log"},
        "记录日志，方便排障": {"log"},
        "记录到画像：我喜欢这种游戏设计风格": {"profile"},
        "复盘一下这轮生成": {"experience"},
        "这张满意，记录为模板": {"template"},
        "这张满意，记录为模版": {"template"},
        "记录全部": {"log", "profile", "experience", "template"},
    }
    blocked_messages = [
        "帮我记录本次方案",
        "写入记忆",
        "保存记忆",
        "帮我沉淀一套风格码",
        "把这个风格系统沉淀成模板方向",
        "继续优化，不要记录",
        "不用记录，继续换配色",
    ]
    for message, expected_scopes in scoped_messages.items():
        actual_scopes = task_orchestrate.message_memory_writeback_scopes(message)
        assert_true(
            actual_scopes == expected_scopes,
            f"记忆写回类别不符合预期：{message} => {actual_scopes}",
        )
    for message in blocked_messages:
        assert_true(
            task_orchestrate.message_requests_memory_writeback(message) is False,
            f"未明确类别的请求不应允许写回：{message}",
        )
    return {
        "scoped_messages": {message: sorted(scopes) for message, scopes in scoped_messages.items()},
        "blocked_messages": blocked_messages,
    }


def case_memory_consumption_relevance_gate():
    structured_profile = {
        "work_types": ["角色设计"],
        "style_preferences": ["现代二次元游戏角色风格"],
        "content_preferences": ["正面全身站立"],
        "taboos": ["厚重装甲"],
        "quality_tendency": "偏好可交付成品",
    }
    no_hit_snapshot = {
        "user_profile": {
            "structured": structured_profile,
            "hits": [],
        }
    }
    no_hit_consumption = task_orchestrate.build_memory_consumption_snapshot(no_hit_snapshot, {})
    for field in ["profile_work_types", "profile_style_preferences", "profile_content_preferences", "profile_taboos"]:
        assert_true(not no_hit_consumption.get(field), f"画像未命中时不应消费 {field}")
    assert_true(not no_hit_consumption.get("profile_quality_tendency"), "画像未命中时不应消费质量偏好")
    assert_true("user_profile" not in no_hit_consumption.get("sources_applied", []), "画像未命中时不应标记为已应用")

    hit_snapshot = {
        "user_profile": {
            "structured": structured_profile,
            "hits": [
                {
                    "field": "style_preferences",
                    "value": "现代二次元游戏角色风格",
                    "line": "style_preferences: 现代二次元游戏角色风格",
                    "score": 1,
                }
            ],
        }
    }
    hit_consumption = task_orchestrate.build_memory_consumption_snapshot(hit_snapshot, {})
    assert_true(
        hit_consumption.get("profile_style_preferences") == ["现代二次元游戏角色风格"],
        "画像命中风格字段时应只消费对应风格偏好",
    )
    assert_true(not hit_consumption.get("profile_content_preferences"), "未命中的画像内容偏好不应被顺手消费")
    assert_true("user_profile" in hit_consumption.get("sources_applied", []), "画像字段命中时应标记为已应用")
    return {
        "no_hit_consumption": no_hit_consumption,
        "hit_consumption": hit_consumption,
    }


def case_startup_and_onboarding(case_payload):
    with common.managed_runtime_paths("mj-regression-startup") as temp_path:
        state_path = temp_path("bootstrap-state.json")
        environment_path = temp_path("environment-notes.md")

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
        assert_true(
            "修复依赖" in " ".join(initial.get("recommended_steps") or []),
            "首次引导必须主动说明可在明确授权后修复依赖",
        )
        environment_check = initial.get("environment_check") or {}
        assert_true(isinstance(environment_check, dict), "首次引导必须返回环境检查结果")
        for key in ["os_supported", "powershell_available", "node_available", "supported_browser_found"]:
            assert_true(key in environment_check, f"环境检查缺少字段：{key}")
        preflight_layers = initial.get("preflight_layers") or []
        assert_true(isinstance(preflight_layers, list) and preflight_layers, "首次引导必须返回分层 preflight")
        layer_names = {str(layer.get("name") or "") for layer in preflight_layers}
        for layer_name in [
            "platform",
            "powershell_runtime",
            "node_runtime",
            "runtime_write",
            "browser_inventory",
            "optional_tooling",
        ]:
            assert_true(layer_name in layer_names, f"首次 preflight 缺少层：{layer_name}")
        for layer in preflight_layers:
            for key in ["name", "ok", "required", "blocked_reason", "recoverability", "recommended_action", "user_message", "details"]:
                assert_true(key in layer, f"preflight 层缺少字段：{key}")
        optional_tooling = next(layer for layer in preflight_layers if layer.get("name") == "optional_tooling")
        assert_true(optional_tooling.get("required") is False, "rg 等辅助工具告警不能阻断 Midjourney 首测")
        required_blocks = initial.get("required_preflight_blocks") or []
        nonfatal_warnings = initial.get("nonfatal_preflight_warnings") or []
        assert_true(isinstance(required_blocks, list), "首次引导必须返回 required_preflight_blocks")
        assert_true(isinstance(nonfatal_warnings, list), "首次引导必须返回 nonfatal_preflight_warnings")
        assert_true(
            initial.get("can_run_minimal_first_test") is (len(required_blocks) == 0),
            "can_run_minimal_first_test 必须和必需层阻塞一致",
        )
        repair_plan = initial.get("dependency_repair_plan") or {}
        dependency_repair = initial.get("dependency_repair") or {}
        assert_true(isinstance(repair_plan.get("actions") or [], list), "首次引导必须返回依赖修复计划")
        assert_true(repair_plan.get("requires_explicit_user_authorization") is True, "依赖修复必须要求用户明确授权")
        assert_true(dependency_repair.get("requested") is False, "默认首测不能自动修复系统依赖")
        first_test_contract = initial.get("minimal_first_test_contract") or []
        contract_layers = {str(item.get("layer") or "") for item in first_test_contract}
        for layer_name in ["preflight", "browser_session", "page_input", "submission", "result_readback"]:
            assert_true(layer_name in contract_layers, f"首测合同缺少层：{layer_name}")

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


def case_reference_knowledge_consumption():
    task = {
        "task_id": "regression-reference-knowledge",
        "project_id": "regression-reference-knowledge",
        "mode": "manual",
        "prompt_policy": "english_only",
        "round_index": 1,
        "round_budget": 2,
        "goal": "create a premium product shot for wireless headphones with material accuracy",
        "brief": {
            "goal": "create a premium product shot for wireless headphones",
            "must_have": [
                "material accuracy",
                "clean commercial background"
            ],
            "style_bias": [],
            "must_not_have": []
        },
    }
    updated_task, prompt_package, knowledge_snapshot = task_orchestrate.run_knowledge_pipeline(
        task,
        force_regenerate=True,
    )
    reference_snapshot = knowledge_snapshot.get("reference_knowledge") or {}
    structured_knowledge = (updated_task.get("solution_plan") or {}).get("structured_knowledge") or {}
    prompt_text = str(prompt_package.get("prompt_text") or "")
    source_documents = prompt_package.get("knowledge_sources") or []

    assert_true(reference_snapshot.get("applied") is True, "正式知识主链应读取 reference 知识快照")
    assert_true(bool(reference_snapshot.get("documents")), "reference 知识快照应包含实际读取的长文档")
    assert_true(
        "task.product_visual" in common.normalize_string_list(structured_knowledge.get("applied_rule_ids")),
        "结构化知识应命中 product_visual 规则",
    )
    assert_true("controlled studio lighting" in prompt_text, "最终 prompt 应消费结构化产品图知识线索")
    assert_true("--raw" in prompt_text, "最终 prompt 应消费结构化产品图参数线索")
    for meta_term in ["overloaded prompt constraints", "premature final polish", "early art-style stacking"]:
        assert_true(meta_term not in prompt_text, f"最终 prompt 不应混入流程类知识提醒：{meta_term}")
    assert_true("shape drift" in prompt_text, "最终 prompt 可保留视觉负面约束")
    assert_true(
        any(path == "midjourney-parameter-system.md" for path in source_documents),
        "prompt_package 应带出本轮读取过的知识来源",
    )
    return {
        "prompt_text": prompt_text,
        "knowledge_sources": source_documents,
        "reference_documents": [item.get("path") for item in reference_snapshot.get("documents") or []],
    }


def case_subject_lock_feedback(case_payload):
    base_task = json.loads(json.dumps(case_payload.get("base_task") or {}))
    feedback_message = str(case_payload.get("feedback_message") or "")
    feedback_result = feedback_apply.apply_feedback_to_task(base_task, feedback_message, increment_round=True)
    updated_task = feedback_result.get("task") or {}
    subject_contract = common.normalize_subject_contract(updated_task.get("subject_contract"))
    assert_true(subject_contract.get("gender") == "male", "主体契约应继续锁定男性")
    assert_true(subject_contract.get("count") == "single", "主体契约应继续锁定单人")
    assert_true("no women" in common.normalize_string_list(subject_contract.get("negative_constraints")), "主体契约应继续保留 no women")
    assert_true("no group" in common.normalize_string_list(subject_contract.get("negative_constraints")), "主体契约应继续保留 no group")

    classified_task, task_model = task_classify.classify_task(updated_task)
    assert_true(task_model.get("revision_mode") == "structure_refine", "只改时尚度时不应掉到 new_direction")
    prompt_task, prompt_package = prompt_strategy_select.build_prompt_package(classified_task, force_regenerate=True)
    manual_task, manual_package = manual_mode_prepare.prepare_task_prompt(prompt_task, force_regenerate=False)
    shared_prompt = str(prompt_package.get("prompt_text") or "")
    manual_prompt = str(manual_package.get("prompt_text") or "")
    for term in ["modern single adult male game character", "one adult man only", "no women", "no group"]:
        assert_true(term in shared_prompt, f"自动模式 prompt 应保留主体锚点：{term}")
        assert_true(term in manual_prompt, f"手动模式 prompt 应保留主体锚点：{term}")
    assert_true(
        common.normalize_subject_contract(manual_task.get("subject_contract")).get("gender") == "male",
        "手动交付不应丢失主体契约",
    )
    return {
        "subject_contract": subject_contract,
        "task_model": task_model,
        "prompt_text": shared_prompt,
    }


def case_subject_contract_chinese_inputs():
    contract = common.infer_subject_contract("现代男性游戏角色，正面全身站立，单人")
    normalized = common.normalize_subject_contract(contract)
    assert_true(normalized.get("subject_type") == "character", "中文主体请求应识别为 character")
    assert_true(normalized.get("gender") == "male", "中文主体请求应识别男性")
    assert_true(normalized.get("count") == "single", "中文主体请求应识别单人")
    assert_true(normalized.get("age_band") == "adult", "中文男性角色默认应保留成人锚点")
    assert_true(normalized.get("view") == "front", "中文主体请求应识别正面")
    assert_true(normalized.get("framing") == "full_body", "中文主体请求应识别全身")
    assert_true(normalized.get("pose") == "standing", "中文主体请求应识别站立")
    assert_true("game character" in common.normalize_string_list(normalized.get("role_labels")), "中文主体请求应识别游戏角色")
    assert_true("modern" in common.normalize_string_list(normalized.get("identity_terms")), "中文主体请求应识别现代风格")
    assert_true("no women" in common.normalize_string_list(normalized.get("negative_constraints")), "中文主体请求应保留 no women")
    assert_true("no group" in common.normalize_string_list(normalized.get("negative_constraints")), "中文主体请求应保留 no group")

    prompt_text = ", ".join(common.build_subject_prompt_segments(normalized))
    for term in [
        "modern single adult male game character",
        "one adult man only",
        "front-facing full-body standing pose",
        "no women",
        "no group",
    ]:
        assert_true(term in prompt_text, f"中文主体请求的 prompt 锚点缺失：{term}")
    return {"subject_contract": normalized, "prompt_text": prompt_text}


def case_feedback_question_not_resume():
    task = {
        "task_id": "regression-feedback-question",
        "mode": "automatic",
        "startup_phase": "ready",
        "round_index": 2,
        "goal": "现代男性游戏角色",
        "raw_request": "现代男性游戏角色",
        "brief": {"goal": "现代男性游戏角色"},
    }
    for message in ["为什么上一轮会生成女的", "为什么会失败", "给我说清楚原因"]:
        assert_true(
            feedback_apply.classify_feedback_intent(task, message) is False,
            f"解释性问题不应被识别为反馈续跑：{message}",
        )
        assert_true(
            task_orchestrate.should_continue_from_feedback(task, message) is False,
            f"解释性问题不应触发活跃任务续跑：{message}",
        )

    for message in ["继续", "服装不够时尚，画风也不够时尚"]:
        assert_true(
            feedback_apply.classify_feedback_intent(task, message),
            f"真实反馈不应被误拦截：{message}",
        )
        assert_true(
            task_orchestrate.should_continue_from_feedback(task, message),
            f"真实反馈应继续沿用当前任务：{message}",
        )
    return {"task": task}


def case_subject_diagnosis_boundaries():
    female_task = {"subject_contract": {"gender": "female"}}
    female_issues = prompt_diagnose.detect_subject_contract_issues(female_task, "single woman fashion character")
    assert_true(female_issues == [], "female + woman 不应因为 man 子串误报 subject_mismatch")

    male_task = {"subject_contract": {"gender": "male"}}
    male_issues = prompt_diagnose.detect_subject_contract_issues(male_task, "single woman fashion character")
    assert_true("subject_mismatch" in male_issues, "male 任务遇到 woman 结果时应命中 subject_mismatch")
    return {"female_issues": female_issues, "male_issues": male_issues}


def case_subject_age_boundaries():
    boy_contract = common.normalize_subject_contract(common.infer_subject_contract("single boy game character"))
    girl_contract = common.normalize_subject_contract(common.infer_subject_contract("single girl game character"))

    assert_true(boy_contract.get("gender") == "male", "boy 应识别为男性")
    assert_true(girl_contract.get("gender") == "female", "girl 应识别为女性")
    assert_true(boy_contract.get("age_band") == "youth", "boy 不应被提升成 adult")
    assert_true(girl_contract.get("age_band") == "youth", "girl 不应被提升成 adult")

    boy_prompt = ", ".join(common.build_subject_prompt_segments(boy_contract))
    girl_prompt = ", ".join(common.build_subject_prompt_segments(girl_contract))
    assert_true("adult" not in boy_prompt and "one adult man only" not in boy_prompt, "boy prompt 不应出现 adult 锚点")
    assert_true("adult" not in girl_prompt and "one adult woman only" not in girl_prompt, "girl prompt 不应出现 adult 锚点")
    assert_true("young male game character" in boy_prompt, "boy prompt 应保留 young male 锚点")
    assert_true("young female game character" in girl_prompt, "girl prompt 应保留 young female 锚点")
    return {"boy_prompt": boy_prompt, "girl_prompt": girl_prompt}


def case_verdict_subject_mismatch(case_payload):
    payload = json.loads(json.dumps((case_payload or {}).get("payload") or {}))
    decision = next_action_decide.decide_next_action(payload)
    assert_true(decision.get("run_verdict") == "usable_but_iterate", "主体错误时不能判 success")
    assert_true(decision.get("next_action") == "prepare_next_round", "主体错误时应继续准备下一轮")
    assert_true(decision.get("should_continue") is True, "主体错误时应允许继续修正")
    return {"decision": decision}


def case_project_workflow(case_payload):
    task = json.loads(json.dumps(case_payload.get("task") or {}))
    with common.managed_runtime_paths("mj-regression-project") as temp_path:
        project_path = temp_path("project.md")
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
    with common.managed_runtime_paths("mj-regression-template") as temp_path:
        patterns_file = temp_path("task-patterns.md")
        review_queue_file = temp_path("review-queue.jsonl")
        candidate_dir = temp_path("task-templates.md").parent

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
    with common.managed_runtime_paths("mj-regression-profile") as temp_path:
        profile_path = temp_path("profile.md")
        preference_signals = temp_path("preference-signals.jsonl")
        taboo_signals = temp_path("taboo-signals.jsonl")
        distilled_file = temp_path("distilled-patterns.md")
        failure_file = temp_path("failure-patterns.md")
        site_file = temp_path("site-changelog.md")
        record_path = temp_path("record.json")
        candidate_path = temp_path("candidate.json")
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


def run_task_orchestrate_with_patches(
    task_payload,
    message: str,
    execute_automatic: bool,
    allow_memory_writeback: bool = False,
):
    with common.managed_runtime_paths("mj-regression-orchestrate") as temp_path:
        task_file = temp_path("task.json")
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

        def fake_save_task_outputs(task, task_file="", checkpoint_file="", persist=False):
            if task_file:
                Path(task_file).write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if not persist:
                return {
                    "ok": True,
                    "skipped": True,
                    "kind": "checkpoint",
                    "reason": task_orchestrate.PERSISTENT_WRITEBACK_SKIPPED_REASON,
                }
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

        def fake_node_script(script_name, arguments, timeout_sec=None):
            task_path = Path(arguments[arguments.index("--task-file") + 1])
            task_payload = json.loads(task_path.read_text(encoding="utf-8-sig"))
            assert_true(
                bool(((task_payload.get("prompt_package") or {}).get("prompt_text") or "").strip()),
                "自动模式必须把 prompt_package 写入执行任务文件",
            )
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

        def fake_powershell_script(script_name, arguments, timeout_sec=None):
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
            assert_true(
                bool(((task_payload.get("prompt_package") or {}).get("prompt_text") or "").strip()),
                "前台自动模式必须把 prompt_package 写入执行任务文件",
            )
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
        if allow_memory_writeback:
            argv.append("--allow-memory-writeback")

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
        return json.loads(buffer.getvalue().strip())


def run_task_orchestrate_from_active_task(active_task_payload, message: str):
    active_task = json.loads(json.dumps(active_task_payload or {}))

    def fake_load_active_task_candidate():
        return json.loads(json.dumps(active_task))

    def fake_initialize_task_from_message(message, mode_override=""):
        raise AssertionError("命中活跃任务恢复时不应重新初始化新任务")

    def fake_merge_mode_route(task, message, mode_override=""):
        updated = dict(task)
        snapshot = {
            "selected_mode": updated.get("mode", "automatic"),
            "selected_backend": updated.get("automatic_execution_backend", "isolated_browser"),
        }
        updated["mode_route_snapshot"] = snapshot
        return updated, snapshot

    def fake_merge_project_context(task, writeback=False):
        updated = dict(task)
        snapshot = {
            "project_id": updated.get("project_id", ""),
            "project_stage": "refine",
            "workflow_status": "active",
            "active_batch_label": "regression-active",
            "subject_contract": updated.get("subject_contract") or {},
            "updated_at": common.now_iso(),
        }
        updated["project_context_snapshot"] = snapshot
        return updated, {"ok": True, "writeback": writeback, "project_context_snapshot": snapshot}

    def fake_save_task_outputs(task, task_file="", checkpoint_file="", persist=False):
        return {"ok": True, "path": checkpoint_file or "checkpoint.json"}

    def fake_ensure_memory_snapshot(task):
        updated = dict(task)
        updated["memory_snapshot"] = {"user_profile": {"structured": {"style_preferences": ["game character design"]}}}
        return updated, updated["memory_snapshot"]

    def fake_attach_memory_consumption_snapshot(task, memory_snapshot):
        updated = dict(task)
        snapshot = {"sources_applied": ["user_profile"], "profile_style_preferences": ["game character design"]}
        updated["memory_snapshot"] = memory_snapshot
        updated["memory_consumption_snapshot"] = snapshot
        return updated, snapshot

    def fake_run_knowledge_pipeline(task, force_regenerate=False):
        updated = dict(task)
        updated["task_model"] = {
            "task_type": "character_design",
            "revision_mode": "structure_refine",
            "subject_contract": updated.get("subject_contract") or {},
        }
        updated["solution_plan"] = {"primary_strategy": "image_prompt"}
        updated["diagnosis_report"] = {
            "observed_issues": [],
            "keep_list": [],
            "change_list": common.normalize_string_list(((updated.get("latest_feedback") or {}).get("points"))),
            "next_round_goal": "",
            "next_round_prompt_delta": [],
        }
        updated["current_prompt"] = "modern single adult male game character, one adult man only, front-facing full-body standing pose, no women, no group"
        prompt_package = {
            "brief_summary": "subject locked",
            "feedback_summary": "fashion-forward outfit",
            "prompt_text": updated["current_prompt"],
            "prompt_stage": "refine",
        }
        updated["prompt_package"] = prompt_package
        return updated, prompt_package, {
            "task_model": updated["task_model"],
            "solution_plan": updated["solution_plan"],
            "diagnosis_report": updated["diagnosis_report"],
        }

    argv = [
        "task_orchestrate.py",
        "--message",
        message,
    ]
    buffer = io.StringIO()
    with patch_attrs(
        (task_orchestrate, "load_active_task_candidate", fake_load_active_task_candidate),
        (task_orchestrate, "initialize_task_from_message", fake_initialize_task_from_message),
        (task_orchestrate, "merge_mode_route", fake_merge_mode_route),
        (task_orchestrate, "merge_project_context", fake_merge_project_context),
        (task_orchestrate, "save_task_outputs", fake_save_task_outputs),
        (task_orchestrate, "ensure_memory_snapshot", fake_ensure_memory_snapshot),
        (task_orchestrate, "attach_memory_consumption_snapshot", fake_attach_memory_consumption_snapshot),
        (task_orchestrate, "run_knowledge_pipeline", fake_run_knowledge_pipeline),
    ):
        with contextlib.redirect_stdout(buffer):
            old_argv = sys.argv[:]
            try:
                sys.argv = argv
                task_orchestrate.main()
            finally:
                sys.argv = old_argv
    return json.loads(buffer.getvalue().strip())


def case_active_task_restore(case_payload):
    active_task = json.loads(json.dumps((case_payload or {}).get("task") or {}))
    feedback_message = str((case_payload or {}).get("feedback_message") or "")
    result = run_task_orchestrate_from_active_task(active_task, feedback_message)
    restored_task = result.get("task") or {}
    feedback_snapshot = result.get("feedback_snapshot") or {}
    assert_true(result.get("orchestration_status") == "automatic_ready_to_submit", "续跑恢复后应继续走自动待执行链路")
    assert_true(restored_task.get("task_id") == active_task.get("task_id"), "无 task-file 续跑应复用原 task_id")
    assert_true(bool(feedback_snapshot), "无 task-file 续跑恢复后应产出 feedback_snapshot")
    assert_true(
        common.normalize_subject_contract(restored_task.get("subject_contract")).get("gender") == "male",
        "续跑恢复后主体契约不应丢失",
    )
    assert_true("one adult man only" in str((result.get("prompt_package") or {}).get("prompt_text") or ""), "恢复后的 prompt 应继续锁定男性单人主体")
    assert_user_message_clean(result, "已接住修改，正在后台生成。")
    return {"result": result}


def case_active_task_restore_requires_pointer():
    checkpoint_task = {
        "task_id": "regression-pointer-task",
        "project_id": "regression-pointer-project",
        "thread_id": "thread-pointer",
        "mode": "automatic",
        "task_phase": "automatic_ready_to_submit",
    }

    with tempfile.TemporaryDirectory(prefix="mj-active-task-") as temp_dir:
        runtime_root = Path(temp_dir)
        active_state_path = runtime_root / "runs" / "active-task.json"
        checkpoints_root = runtime_root / "runs" / "checkpoints"
        checkpoints_root.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoints_root / "recent-task.json"
        checkpoint_path.write_text(json.dumps(checkpoint_task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        with patch_attrs(
            (task_orchestrate, "ACTIVE_TASK_STATE_PATH", active_state_path),
            (task_orchestrate, "MEMORY_ROOT", runtime_root),
            (task_orchestrate, "get_runtime_thread_id", lambda: "thread-pointer"),
        ):
            restored = task_orchestrate.load_active_task_candidate()
            assert_true(restored == {}, "没有 active-task 指针时不应回捞最近 checkpoint")

            active_state_path.parent.mkdir(parents=True, exist_ok=True)
            active_state_path.write_text(
                json.dumps(
                    {
                        "task_id": "other-task",
                        "project_id": checkpoint_task["project_id"],
                        "thread_id": checkpoint_task["thread_id"],
                        "checkpoint_path": str(checkpoint_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            restored = task_orchestrate.load_active_task_candidate()
            assert_true(restored == {}, "active-task 与 checkpoint 的 task_id 不一致时不应恢复")

            active_state_path.write_text(
                json.dumps(
                    {
                        "task_id": checkpoint_task["task_id"],
                        "project_id": checkpoint_task["project_id"],
                        "thread_id": checkpoint_task["thread_id"],
                        "checkpoint_path": str(checkpoint_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            restored = task_orchestrate.load_active_task_candidate()
            assert_true(restored.get("task_id") == checkpoint_task["task_id"], "显式活跃指针应恢复对应 checkpoint")
    return {"checkpoint_task": checkpoint_task}


def case_active_task_restore_requires_thread_scope():
    checkpoint_task = {
        "task_id": "regression-thread-task",
        "project_id": "regression-thread-project",
        "thread_id": "thread-a",
        "mode": "automatic",
        "task_phase": "automatic_ready_to_submit",
    }

    with tempfile.TemporaryDirectory(prefix="mj-active-thread-") as temp_dir:
        runtime_root = Path(temp_dir)
        active_state_path = runtime_root / "runs" / "active-task.json"
        checkpoints_root = runtime_root / "runs" / "checkpoints"
        checkpoints_root.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoints_root / "thread-task.json"
        checkpoint_path.write_text(json.dumps(checkpoint_task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        active_state_path.parent.mkdir(parents=True, exist_ok=True)
        active_state_path.write_text(
            json.dumps(
                {
                    "task_id": checkpoint_task["task_id"],
                    "project_id": checkpoint_task["project_id"],
                    "thread_id": checkpoint_task["thread_id"],
                    "checkpoint_path": str(checkpoint_path),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        with patch_attrs(
            (task_orchestrate, "ACTIVE_TASK_STATE_PATH", active_state_path),
            (task_orchestrate, "get_runtime_thread_id", lambda: "thread-b"),
        ):
            restored = task_orchestrate.load_active_task_candidate()
            assert_true(restored == {}, "褰撳墠绾跨▼涓?active-task 鎸囬拡绾跨▼涓嶄竴鑷存椂涓嶅簲鎭㈠")

        with patch_attrs(
            (task_orchestrate, "ACTIVE_TASK_STATE_PATH", active_state_path),
            (task_orchestrate, "get_runtime_thread_id", lambda: "thread-a"),
        ):
            restored = task_orchestrate.load_active_task_candidate()
            assert_true(restored.get("task_id") == checkpoint_task["task_id"], "鍙湁鍚屼竴绾跨▼鐨?active-task 鎸囬拡鎵嶈兘鎭㈠")

        checkpoint_path.write_text(
            json.dumps({**checkpoint_task, "thread_id": "thread-c"}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with patch_attrs(
            (task_orchestrate, "ACTIVE_TASK_STATE_PATH", active_state_path),
            (task_orchestrate, "get_runtime_thread_id", lambda: "thread-a"),
        ):
            restored = task_orchestrate.load_active_task_candidate()
            assert_true(restored == {}, "checkpoint 鐨?thread_id 涓?active-task 鎸囬拡涓嶄竴鑷存椂涓嶅簲鎭㈠")
    return {"checkpoint_task": checkpoint_task}


def case_finished_task_not_restored():
    finished_task = {
        "task_id": "regression-finished-task",
        "project_id": "regression-finished-project",
        "mode": "automatic",
        "round_index": 2,
        "task_phase": "finished",
        "last_run_verdict": "success",
        "next_action": "finish_task",
    }
    waiting_feedback_task = dict(finished_task)
    waiting_feedback_task["next_action"] = "await_user_feedback"

    assert_true(task_orchestrate.is_terminal_task(finished_task), "finish_task 鐨勭粓鎬佷换鍔″簲琚瘑鍒?terminal")
    assert_true(
        task_orchestrate.should_continue_from_feedback(finished_task, "\u7ee7\u7eed") is False,
        "缁堟€佷换鍔″湪鏀跺埌鈥滅户缁€濇椂涓嶅簲缁х画鎭㈠",
    )
    assert_true(
        task_orchestrate.is_terminal_task(waiting_feedback_task) is False,
        "await_user_feedback 涓嶅簲琚綋鎴愮湡姝ｇ粓鎬佷换鍔?",
    )
    assert_true(
        task_orchestrate.should_continue_from_feedback(waiting_feedback_task, "\u628a\u914d\u8272\u6539\u6df1\u4e00\u70b9"),
        "绛夊緟鐢ㄦ埛鍙嶉鐨勪换鍔″湪鏀跺埌鏄庣‘淇敼鏃朵粛搴旇兘缁х画",
    )
    return {
        "finished_task": finished_task,
        "waiting_feedback_task": waiting_feedback_task,
    }


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

    def assert_receipt_states(payload, written, skipped, label: str):
        receipts = payload.get("runtime_receipts") or {}
        for key in written:
            assert_true(key in receipts, f"{label} 缺少 {key} receipt")
            assert_true((receipts.get(key) or {}).get("skipped") is not True, f"{label} 不应跳过 {key}")
        for key in skipped:
            assert_true(key in receipts, f"{label} 缺少 {key} receipt")
            assert_true((receipts.get(key) or {}).get("skipped") is True, f"{label} 应跳过 {key}")

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
        assert_true((receipts.get(key) or {}).get("skipped") is True, f"默认不应写回本地记忆：{key}")

    scoped_expectations = [
        (
            "记录日志，方便排障",
            ["checkpoint", "run_log", "run_summary"],
            ["profile_signal", "profile_merge", "experience_distill", "template_candidate"],
            "日志单类写回",
        ),
        (
            "记录到画像：我喜欢这种游戏设计风格",
            ["profile_signal", "profile_merge"],
            ["checkpoint", "run_log", "run_summary", "experience_distill", "template_candidate"],
            "画像单类写回",
        ),
        (
            "复盘一下这轮生成",
            ["experience_distill"],
            ["checkpoint", "run_log", "run_summary", "profile_signal", "profile_merge", "template_candidate"],
            "经验单类写回",
        ),
        (
            "这张满意，记录为模板",
            ["template_candidate"],
            ["checkpoint", "run_log", "run_summary", "profile_signal", "profile_merge", "experience_distill"],
            "模板单类写回",
        ),
    ]
    for scoped_message, written, skipped, label in scoped_expectations:
        scoped_task = dict(base_task)
        scoped_task["automatic_execution_backend"] = "isolated_browser"
        scoped_result = run_task_orchestrate_with_patches(scoped_task, scoped_message, execute_automatic=True)
        assert_true(scoped_result.get("orchestration_status") == "automatic_round_executed", f"{label} 应完成最小集成执行")
        assert_receipt_states(scoped_result, written, skipped, label)

    isolated_writeback_task = dict(base_task)
    isolated_writeback_task["automatic_execution_backend"] = "isolated_browser"
    isolated_writeback = run_task_orchestrate_with_patches(
        isolated_writeback_task,
        "继续并记录这次结果",
        execute_automatic=True,
        allow_memory_writeback=True,
    )
    assert_true(
        isolated_writeback.get("orchestration_status") == "automatic_round_executed",
        "显式记录时后台自动模式应完成最小集成执行",
    )
    writeback_receipts = isolated_writeback.get("runtime_receipts") or {}
    for key in ["checkpoint", "run_log", "run_summary", "profile_signal", "profile_merge", "experience_distill", "template_candidate"]:
        assert_true(key in writeback_receipts, f"显式记录时缺少 {key} receipt")
        assert_true((writeback_receipts.get(key) or {}).get("skipped") is not True, f"显式记录时不应跳过 {key}")

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
        "isolated_browser_writeback": isolated_writeback,
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
        browser_missing_message == "这台电脑没有检测到可用的后台浏览器。建议先安装 Edge；你明确要求修复依赖后，我可以尝试安装。",
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
        task_orchestrate.build_user_facing_block_message({"blocked_reason": "powershell_runtime_missing"}) == "这台电脑缺少可用的 PowerShell，自动模式暂时不可用；你明确要求修复依赖后，我可以尝试安装。",
        "PowerShell 阻塞提示错误",
    )
    assert_true(
        task_orchestrate.build_user_facing_block_message({"blocked_reason": "node_runtime_missing"}) == "这台电脑缺少 Node.js，后台自动模式暂时不可用；你明确要求修复依赖后，我可以尝试安装。",
        "Node 阻塞提示错误",
    )
    timeout_message = task_orchestrate.build_user_facing_block_message({"blocked_reason": "automatic_parent_timeout"})
    assert_true(
        timeout_message == "本轮已达到 5 分钟内的自动执行上限，已停止继续尝试。",
        "外层超时阻塞提示错误",
    )
    timeout_governance = common.classify_execution_governance(
        {"blocked_reason": "automatic_parent_timeout", "ok": False, "completed": False, "result_available": False},
        "isolated_browser",
    )
    assert_true(timeout_governance.get("recommended_action") == "stop_after_budget", "外层超时应建议停止预算内等待")
    return {
        "message": browser_missing_message,
        "governance": governance,
        "timeout_message": timeout_message,
        "timeout_governance": timeout_governance,
    }


def case_dependency_repair_planning():
    fake_environment = {
        "required_preflight_blocks": [
            {"name": "powershell_runtime", "blocked_reason": "powershell_runtime_missing"},
            {"name": "node_runtime", "blocked_reason": "node_runtime_missing"},
            {"name": "browser_inventory", "blocked_reason": "no_supported_browser_found"},
            {"name": "runtime_write", "blocked_reason": "runtime_write_unavailable"},
        ]
    }
    plan = common.build_dependency_repair_plan(fake_environment, available_managers=[{"name": "winget", "path": r"C:\winget.exe"}])
    actions_by_reason = {action.get("blocked_reason"): action for action in plan.get("actions") or []}
    assert_true(plan.get("can_attempt_repair") is True, "有 winget 时应能尝试修复支持的系统依赖")
    assert_true(actions_by_reason["powershell_runtime_missing"].get("repairable") is True, "PowerShell 缺失应可规划修复")
    assert_true("Microsoft.PowerShell" in actions_by_reason["powershell_runtime_missing"].get("command", []), "PowerShell 修复应使用官方包 ID")
    assert_true(actions_by_reason["node_runtime_missing"].get("repairable") is True, "Node 缺失应可规划修复")
    assert_true("OpenJS.NodeJS.LTS" in actions_by_reason["node_runtime_missing"].get("command", []), "Node 修复应使用 LTS 包 ID")
    assert_true(actions_by_reason["no_supported_browser_found"].get("repairable") is True, "浏览器缺失应可规划修复")
    assert_true("Microsoft.Edge" in actions_by_reason["no_supported_browser_found"].get("command", []), "浏览器修复应优先安装 Edge")
    assert_true(actions_by_reason["runtime_write_unavailable"].get("repairable") is False, "运行目录权限不能当成依赖安装修复")
    dry_run = common.execute_dependency_repair_plan(plan, dry_run=True)
    assert_true(dry_run.get("dry_run") is True, "依赖修复 dry-run 应标记 dry_run")
    assert_true(dry_run.get("attempted") is False, "dry-run 不能执行安装命令")
    no_manager_plan = common.build_dependency_repair_plan(fake_environment, available_managers=[])
    assert_true(no_manager_plan.get("can_attempt_repair") is False, "没有包管理器时不能声称可自动修复")
    return {
        "repairable_reasons": [
            action.get("blocked_reason")
            for action in plan.get("repairable_actions") or []
        ],
        "dry_run": dry_run,
        "no_manager_plan": no_manager_plan,
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


def case_colorway_base_approval(case_payload):
    unapproved_task = json.loads(json.dumps((case_payload or {}).get("unapproved_task") or {}))
    approved_task = json.loads(json.dumps((case_payload or {}).get("approved_task") or {}))
    unapproved_message = str((case_payload or {}).get("unapproved_message") or "")
    approved_message = str((case_payload or {}).get("approved_message") or "")
    expected_capture = str((case_payload or {}).get("expected_promoted_capture") or "").strip()

    unapproved_result = feedback_apply.apply_feedback_to_task(unapproved_task, unapproved_message)
    approved_result = feedback_apply.apply_feedback_to_task(approved_task, approved_message)

    unapproved_revision_patch = (
        unapproved_result["task"].get("revision_patch")
        if isinstance(unapproved_result["task"].get("revision_patch"), dict)
        else {}
    )
    approved_revision_patch = (
        approved_result["task"].get("revision_patch")
        if isinstance(approved_result["task"].get("revision_patch"), dict)
        else {}
    )

    assert_true(
        not str(unapproved_result["task"].get("accepted_base_reference") or "").strip(),
        "未确认基底时不应自动晋升 accepted_base_reference",
    )
    assert_true(
        str(unapproved_result["task"].get("design_lock_state") or "").strip() != "hard_locked",
        "未确认基底时不应直接进入 hard_locked",
    )
    assert_true(
        str(unapproved_revision_patch.get("accepted_base_reference") or "").strip() == "",
        "未确认基底时 revision_patch 不应写入 accepted_base_reference",
    )
    assert_true(
        str(approved_result["task"].get("accepted_base_reference") or "").strip() == expected_capture,
        "显式确认基底后应晋升当前结果图为 accepted_base_reference",
    )
    assert_true(
        str(approved_result["task"].get("design_lock_state") or "").strip() == "hard_locked",
        "显式确认基底后应进入 hard_locked",
    )
    assert_true(
        str(approved_revision_patch.get("revision_mode") or "").strip() == "colorway_only",
        "换配色确认基底后 revision_mode 仍应保持 colorway_only",
    )
    return {
        "unapproved_result": unapproved_result,
        "approved_result": approved_result,
    }


def case_colorway_blocked_decision(case_payload):
    payload = json.loads(json.dumps((case_payload or {}).get("payload") or {}))
    decision = next_action_decide.decide_next_action(payload)
    assert_true(decision.get("run_verdict") == "blocked_by_ui", "配色阻塞态不应被 success 覆盖")
    assert_true(decision.get("next_action") == "resolve_ui_block", "阻塞态应继续走 resolve_ui_block")
    assert_true(decision.get("should_continue") is False, "阻塞态不应自动继续")
    return {"decision": decision}


def case_manual_colorway_reference(case_payload):
    task = json.loads(json.dumps((case_payload or {}).get("task") or {}))
    expected_reference_path = str((case_payload or {}).get("expected_reference_path") or "").strip()

    task, task_model, solution_plan, prompt_package = run_specialized_prompt_chain(task)
    manual_task, manual_package = manual_mode_prepare.prepare_task_prompt(task, force_regenerate=False)

    assert_true(
        str(prompt_package.get("accepted_base_reference") or "").strip() == expected_reference_path,
        "prompt_package 应回写 accepted_base_reference",
    )
    assert_true(
        str(manual_package.get("accepted_base_reference") or "").strip() == expected_reference_path,
        "手动交付包应回写 accepted_base_reference",
    )
    omni_reference = None
    for item in prompt_package.get("reference_bundle") or []:
        if str(item.get("capability") or "").strip() == "omni_reference":
            omni_reference = item
            break
    assert_true(isinstance(omni_reference, dict), "reference_bundle 缺少 omni_reference")
    assert_true(
        str(omni_reference.get("reference_path") or "").strip() == expected_reference_path,
        "omni_reference 应带出可提交的 reference_path",
    )
    assert_true(
        "garment_panels" not in str(prompt_package.get("prompt_text") or ""),
        "prompt_text 不应泄露内部 locked element 字段名",
    )
    assert_true(
        "material_map" not in str(prompt_package.get("prompt_text") or ""),
        "prompt_text 不应泄露内部 material_map 字段名",
    )
    return {
        "task_model": task_model,
        "solution_plan": solution_plan,
        "prompt_package": prompt_package,
        "manual_package": manual_package,
        "manual_task": manual_task,
    }


def case_new_task_restart_routing(case_payload):
    task = json.loads(json.dumps((case_payload or {}).get("task") or {}))
    reset_message = str((case_payload or {}).get("reset_message") or "")
    fresh_request_message = str((case_payload or {}).get("fresh_request_message") or "")
    restart_hint_message = str((case_payload or {}).get("restart_hint_message") or "")
    feedback_message = str((case_payload or {}).get("feedback_message") or "")

    assert_true(task_orchestrate.is_new_task_reset(reset_message), "显式换任务语句应命中新任务重置")
    assert_true(
        task_orchestrate.should_restart_task_from_message(task, reset_message),
        "显式换任务语句应直接触发重开",
    )
    assert_true(
        task_orchestrate.should_continue_from_feedback(task, reset_message) is False,
        "显式换任务语句不应继续沿用旧任务反馈链",
    )
    assert_true(
        feedback_apply.looks_like_new_task_request(task, fresh_request_message),
        "做一张新的……应被识别为新任务请求",
    )
    assert_true(
        feedback_apply.classify_feedback_intent(task, fresh_request_message) is False,
        "做一张新的……不应被误判成旧任务反馈",
    )
    assert_true(
        task_orchestrate.should_restart_task_from_message(task, fresh_request_message),
        "新生成请求在多轮状态下应触发重开",
    )
    assert_true(
        task_orchestrate.should_continue_from_feedback(task, fresh_request_message) is False,
        "新生成请求不应继续沿用旧任务反馈链",
    )
    assert_true(
        task_orchestrate.should_restart_task_from_message(task, restart_hint_message),
        "重开提示语应触发新任务重开",
    )
    assert_true(
        task_orchestrate.should_continue_from_feedback(task, restart_hint_message) is False,
        "重开提示语不应继续沿用旧任务反馈链",
    )
    assert_true(
        feedback_apply.classify_feedback_intent(task, feedback_message),
        "正常配色反馈仍应保持为反馈意图",
    )
    assert_true(
        task_orchestrate.should_restart_task_from_message(task, feedback_message) is False,
        "正常配色反馈不应触发重开",
    )
    return {
        "reset_message": reset_message,
        "fresh_request_message": fresh_request_message,
        "restart_hint_message": restart_hint_message,
        "feedback_message": feedback_message,
    }


def build_summary(results):
    total = len(results)
    passed = sum(1 for item in results if item.get("status") == "passed")
    failed = total - passed
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
    }


def build_health_report(results):
    status_map = {str(item.get("name") or ""): str(item.get("status") or "") for item in results}
    areas = []
    for area in HEALTH_AREAS:
        covered_cases = []
        for case_name in area["required_cases"]:
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
        "all_required_checks_passed": all(area["passed"] for area in areas),
        "check_entrypoints": [
            "assets/regression-cases.json",
            "scripts/run_regression_suite.py",
        ],
        "areas": areas,
    }


def main():
    args = parse_args()
    cases_path = Path(args.cases_file) if args.cases_file else DEFAULT_CASES_PATH
    cases = load_cases(cases_path)

    results = []
    results.extend(syntax_smoke_cases(cases))
    record_case(results, "logic::skill_entry_and_syntax_contract", lambda: case_skill_entry_and_syntax_contract(cases))
    record_case(results, "logic::empty_invocation_startup_contract", case_empty_invocation_startup_contract)
    record_case(results, "logic::memory_writeback_trigger_contract", case_memory_writeback_trigger_contract)
    record_case(results, "logic::memory_consumption_relevance_gate", case_memory_consumption_relevance_gate)

    logic_cases = cases.get("logic_cases") or {}
    record_case(results, "logic::startup_and_onboarding", lambda: case_startup_and_onboarding(logic_cases.get("startup") or {}))
    record_case(results, "logic::mode_routing", lambda: case_mode_routing(logic_cases.get("mode_routing") or []))
    record_case(results, "logic::english_only", lambda: case_english_only(logic_cases.get("english_only") or {}))
    record_case(results, "logic::feedback_edit_model", lambda: case_feedback_edit(logic_cases.get("feedback") or {}))
    record_case(results, "logic::manual_diagnosis_handoff", lambda: case_manual_diagnosis(logic_cases.get("manual_diagnosis") or {}))
    record_case(results, "logic::mode_consistency", lambda: case_mode_consistency(logic_cases.get("mode_consistency") or {}))
    record_case(results, "logic::reference_knowledge_consumption", case_reference_knowledge_consumption)
    record_case(results, "logic::subject_lock_feedback", lambda: case_subject_lock_feedback(logic_cases.get("subject_lock_feedback") or {}))
    record_case(results, "logic::subject_contract_chinese_inputs", case_subject_contract_chinese_inputs)
    record_case(results, "logic::feedback_question_not_resume", case_feedback_question_not_resume)
    record_case(results, "logic::subject_diagnosis_boundaries", case_subject_diagnosis_boundaries)
    record_case(results, "logic::subject_age_boundaries", case_subject_age_boundaries)
    record_case(results, "logic::verdict_subject_mismatch", lambda: case_verdict_subject_mismatch(logic_cases.get("verdict_subject_mismatch") or {}))
    record_case(results, "logic::active_task_restore", lambda: case_active_task_restore(logic_cases.get("active_task_restore") or {}))
    record_case(results, "logic::active_task_restore_requires_pointer", case_active_task_restore_requires_pointer)
    record_case(results, "logic::active_task_restore_requires_thread_scope", case_active_task_restore_requires_thread_scope)
    record_case(results, "logic::finished_task_not_restored", case_finished_task_not_restored)
    record_case(results, "logic::colorway_next_action", lambda: case_colorway_next_action(logic_cases.get("colorway_next_action") or {}))
    record_case(results, "logic::colorway_base_approval", lambda: case_colorway_base_approval(logic_cases.get("colorway_base_approval") or {}))
    record_case(results, "logic::colorway_blocked_decision", lambda: case_colorway_blocked_decision(logic_cases.get("colorway_blocked_decision") or {}))
    record_case(results, "logic::manual_colorway_reference", lambda: case_manual_colorway_reference(logic_cases.get("manual_colorway_reference") or {}))
    record_case(results, "logic::new_task_restart_routing", lambda: case_new_task_restart_routing(logic_cases.get("new_task_restart_routing") or {}))
    record_case(results, "logic::specialized_task_routes", lambda: case_specialized_task_routes(logic_cases.get("specialized_task_routes") or {}))
    record_case(results, "logic::project_workflow", lambda: case_project_workflow(logic_cases.get("project_workflow") or {}))
    record_case(results, "logic::template_candidate", lambda: case_template_candidate(logic_cases.get("template_candidate") or {}))
    record_case(results, "logic::profile_signal_chain", lambda: case_profile_signal(logic_cases.get("profile_signal") or {}))
    record_case(results, "logic::automatic_mode_minimal_integration", case_automatic_integration)
    record_case(results, "logic::prompt_region_governance", lambda: case_governance(logic_cases.get("governance") or {}))
    record_case(results, "logic::block_messages", case_block_messages)
    record_case(results, "logic::dependency_repair_planning", case_dependency_repair_planning)
    record_case(results, "logic::desktop_browser_coverage", case_desktop_browser_coverage)

    summary = build_summary(results)
    output = {
        "ok": summary["failed"] == 0,
        "summary": summary,
        "health_report": build_health_report(results),
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
