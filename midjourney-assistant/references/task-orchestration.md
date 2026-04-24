# v0.2 任务编排

## 目标

`v0.2` 的主线不再只是单轮网页提交，而是统一承接：

1. 首次启动但已携带真实需求
2. 非首次启动直接带需求
3. 自动模式
4. 手动模式
5. 同一 `project_id` 下的连续多轮任务

## 统一入口

任何正式任务开始前，优先按这个顺序执行：

1. `scripts/startup_route.py`
2. 如有需求，立即执行 `scripts/task_state_init.py`
3. `scripts/mode_route.py`
4. `scripts/project_context_merge.py`
5. `scripts/memory_retrieve.py`
6. `scripts/task_orchestrate.py`

## 正式运行输出边界

正式生图任务只走运行时编排，不走开发验收链。运行时可以静默做 prompt 质量闸门、执行器健康检查、结果区域归因和必要写回，但不要把这些内部动作当作进度告诉用户。

正式自动模式的用户可见消息只保留三类：

1. 开始：`已接住需求，正在后台生成。`
2. 完成：`生成完成。`
3. 阻塞：只说明真实阻塞原因和用户需要做的最小动作

正式运行时禁止播报这些内容：

1. 检查任务对象、检查编排器、检查脚本、检查术语映射
2. 跑内部回归、回归用例、脚本级 smoke
3. checkpoint、runtime receipts、profile signal、experience distill、template candidate
4. 本地文件路径、脚本名、内部 JSON、内部补丁或调试命令

只有用户明确要求验收、回归、检查实现、调试或开发修改时，才进入阶段4回归矩阵。

## 统一任务对象

编排器使用统一任务对象承接状态，至少包含：

1. `task_id`
2. `project_id`
3. `mode`
4. `startup_phase`
5. `task_phase`
6. `round_index`
7. `round_budget`
8. `brief`
9. `current_prompt`
10. `last_run_verdict`
11. `last_result_summary`
12. `next_action`
13. `memory_snapshot`
14. `project_context_snapshot`

## 首次启动规则

首次启动仍然必须先做测试，但如果用户已经带了真实需求：

1. 先缓存任务，不丢原始需求
2. 先返回 `onboarding_pending`
3. 完成首次测试后，继续同一个 `task_id`
4. 不要求用户把需求再说一遍

## 模式规则

自动模式和手动模式共享同一个任务对象。

两者唯一差异是网页操作执行者不同：

1. 自动模式：assistant 负责网页预检、输入、提交、状态确认和结果回读
2. 手动模式：assistant 负责需求拆解、prompt 交付、参数建议、结果判断和下一轮建议；用户自己去网页生成

自动模式内部再细分为两条正式后端：

1. 后台模式：`isolated_browser`，默认路线
2. 前台模式：`window_uia`，保留兼容路线

## 项目上下文

只要存在 `project_id`，编排器就要：

1. 先从 `memories/midjourney-assistant/projects/<project_id>.md` 读入最近项目状态
2. 把最近 prompt、最近 verdict、最近结果摘要并回当前任务对象
3. 在任务推进后再把当前状态写回同一个项目文件

项目上下文至少保留：

1. 最新目标
2. brief 摘要
3. 最新 prompt
4. 最新模式
5. 最新任务阶段
6. 最新 verdict
7. 最新结果摘要
8. 下一步动作
9. 最近若干轮次记录

## 自动模式

自动模式的网页执行仍然复用：

1. `scripts/midjourney_generate_once.ps1`

从现在开始，自动模式允许挂两条执行器：

1. `window_uia`
   继续使用当前前台窗口、点击、输入、状态探针和最终截图的旧链路。
2. `isolated_browser`
使用独立 `Chromium 浏览器 profile + remote debugging port` 的后台浏览器链路，不碰用户当前正在使用的主浏览器窗口；后台链会优先复用上次成功的浏览器，其次自动探测本机可用的 Edge、Chrome、Brave、Vivaldi、Arc。

但从 `v0.2` 起，必须由统一任务对象驱动，不再允许散参数主导。

默认自动执行后端改为 `isolated_browser`。如果用户显式说“前台模式”，再切到 `window_uia`。这条默认后端要求：

1. 独立浏览器使用单独的 profile 目录
2. 首次使用时可能需要用户在这套独立 profile 里登录一次 Midjourney
3. 后续自动执行通过 CDP 直接驱动页面，不再依赖窗口激活和 SendKeys
4. 如果独立浏览器未登录或被挑战页拦截，要返回明确的阻塞原因，而不是降级去抢用户当前浏览器前台

自动模式执行完一轮后，编排器还要继续做：

1. `scripts/next_action_decide.py`
2. `scripts/run_checkpoint.py`
3. `scripts/memory_append.py`
4. `scripts/run_summary.py`
5. `scripts/project_context_merge.py --writeback`

## 手动模式

手动模式至少交付：

1. brief 摘要
2. 当前 prompt
3. 参数建议
4. 提交注意事项
5. 用户回传要求

手动模式交付后也要：

1. 写 checkpoint
2. 写项目上下文

但不强制追加运行日志。

## 下一步决策

自动模式或手动模式拿到结果后，优先由 `scripts/next_action_decide.py` 给出：

1. `next_action`
2. `next_phase`
3. `should_continue`
4. `next_round_index`

## 默认写回

`v0.2` 当前版本的默认写回规则如下：

1. 进入正式编排就写 checkpoint
2. 有 `project_id` 就写项目上下文
3. 自动模式实际执行完一轮后，再写运行日志和运行摘要

## 当前边界

`v0.2` 已经完成：

1. 启动路由
2. 模式路由
3. 统一任务对象
4. 项目上下文合并与写回
5. 手动模式交付包
6. 自动模式待提交编排
7. 自动模式执行后决策与统一写回

`v0.2` 还没有新增额外浏览器工具链，也没有引入模板自动生成或子 skill 派生。

## v0.3 阶段3补充

阶段3开始后，项目上下文不再只是“上一轮状态快照”，而要继续沉淀项目级工作流字段：

1. `project_stage`
2. `workflow_status`
3. `active_batch_label`
4. `completed_rounds`
5. `persistent_must_have`
6. `persistent_style_bias`
7. `persistent_must_not_have`
8. `consistency_rules`
9. `open_items`
10. `template_candidate_keys`

只要反馈被识别成续跑修改，就不再停留在自由文本层，而要通过 `scripts/feedback_apply.py` 归并成：

1. `scope = round | project | global`
2. `edit_operations`
3. `project_strategy_patch`
4. `global_policy_patch`

自动模式真实执行完一轮后，阶段3在默认写回链上继续追加：

1. `scripts/profile_signal_extract.py`
2. `scripts/profile_merge.py`
3. `scripts/experience_distill.py`
4. `scripts/template_candidate_upsert.py`

其中 `scripts/template_candidate_upsert.py` 负责三件事：

1. 更新 `memories/midjourney-assistant/task-patterns.md`
2. 在阈值达到后生成 `memories/midjourney-assistant/template-candidates/task-templates/*.md`
3. 追加 `memories/midjourney-assistant/review-queue.jsonl`

项目上下文写回时，要把 `template_candidate_keys` 一起带回项目文件，这样同一项目后续轮次可以知道哪些模板候选已经从该项目里浮出来过。

## v0.3 阶段4回归矩阵

阶段4只属于开发修改、内部验收和用户明确要求回归的场景。正式生图运行时禁止进入本节，也禁止把本节的检查过程播报给用户。

阶段4开始后，先跑内部回归，再交给用户做结果性实机验收。

统一内部回归入口固定为：

1. `assets/regression-cases.json`
2. `scripts/run_regression_suite.py`
3. `references/regression-matrix.md`

### 内部回归覆盖

内部回归当前固定覆盖三层：

1. 语法 smoke
   - Python：`startup_route.py`、`mode_route.py`、`first_run_check.py`、`manual_mode_prepare.py`、`feedback_apply.py`、`project_context_merge.py`、`template_candidate_upsert.py`、`task_orchestrate.py`、`profile_signal_extract.py`、`profile_merge.py`、`experience_distill.py`
   - Node：`midjourney_isolated_browser_once.mjs`
   - PowerShell：`browser_preflight.ps1`、`window_state_probe.ps1`、`window_control_gate.ps1`、`midjourney_generate_once.ps1`、`midjourney_status_probe.ps1`、`midjourney_window_capture.ps1`
2. 逻辑 golden cases
   - 首次启动 / 首次引导
   - 模式路由
   - 英文 prompt 唯一出口
   - 反馈编辑模型
   - 项目工作流写回
   - 模板候选与 `review queue`
   - 画像 signal / 合并 / 蒸馏经验
   - prompt 结果区域阻塞分类
3. 最小集成验证
   - `task_orchestrate.py` 自动模式最小集成
   - `isolated_browser`
   - `window_uia`
   - `runtime_receipts` 主链写回完整性

### 阶段4执行原则

1. 改关键链路前，先跑一次内部回归
2. 改完后，再跑一次内部回归
3. 内部回归不通过时，不直接进入真实 Midjourney 网页测试
4. 用户实机验收只负责验证现场行为，不再替内部逻辑和脚本级回归兜底

### 仍需最终实机验收的能力

这些能力即使内部回归通过，也仍需最终现场验证：

1. 后台模式真实网页提交与轮询
2. 前台模式真实页面复用
3. prompt 对应区域结果归因
4. 独立浏览器登录态与挑战页恢复
5. 页面视觉结果和截图是否与本轮 prompt 真正对应
