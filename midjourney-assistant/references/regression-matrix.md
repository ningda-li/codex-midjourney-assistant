# 阶段5回归与实机验收矩阵

## 目标

阶段5的目标不是继续补单点功能，而是把 `midjourney-assistant` 的验收分成两层：

1. 内部回归：先验证知识主链、模式一致性、反馈诊断和自动执行编排没有被改坏
2. 实机验收：再去真实 Midjourney 页面验证后台模式、前台模式和结果归因这些现场能力

统一入口：

1. `assets/regression-cases.json`
2. `scripts/run_regression_suite.py`
3. `references/live-acceptance-runbook.md`

## 使用边界

本矩阵只用于以下场景：

1. skill 开发修改
2. 内部验收
3. 用户明确要求“回归 / 验收 / 检查实现 / 调试”

它不是正式生图任务的前置步骤。正式生图运行时禁止：

1. 每次提交前运行内部回归
2. 向用户播报回归用例、脚本级 smoke 或内部检查过程
3. 把本矩阵里的开发验收动作当作用户可见进度

正式生图运行只保留静默质量闸门和真实阻塞说明；通过时继续执行，完成时只汇报结果。

## 阶段5验收重点

阶段5只盯四件事：

1. 知识主链完整
2. 模式一致性成立
3. 反馈诊断有效
4. 自动执行不破坏知识判断

## 内部回归覆盖

### 1. 语法 smoke

1. Python 脚本语法编译
2. Node `--check`
3. PowerShell 语法解析

### 2. 逻辑 golden cases

1. 首次启动与首次引导
2. 模式路由
3. 英文 prompt 唯一出口
4. 反馈续跑编辑模型
5. 手动模式消费 `diagnosis_report`
6. 自动与手动共享同一知识主链
7. 项目工作流写回
8. 模板候选与 `review queue`
9. 画像 signal / 画像提升 / 蒸馏经验
10. prompt 对应区域阻塞分类

### 3. 最小集成验证

1. `task_orchestrate.py` 自动模式编排
2. `isolated_browser` 后端最小集成
3. `window_uia` 后端最小集成
4. `runtime_receipts` 主链完整性
5. 自动执行后重跑 `diagnosis_report`

## 阶段5重点到回归用例映射

### 1. 知识主链完整

对应回归：

1. `logic::english_only`
2. `logic::mode_consistency`
3. `logic::automatic_mode_minimal_integration`

### 2. 模式一致性成立

对应回归：

1. `logic::mode_routing`
2. `logic::mode_consistency`
3. `logic::automatic_mode_minimal_integration`

### 3. 反馈诊断有效

对应回归：

1. `logic::feedback_edit_model`
2. `logic::manual_diagnosis_handoff`
3. `logic::automatic_mode_minimal_integration`

### 4. 自动执行不破坏知识判断

对应回归：

1. `logic::mode_consistency`
2. `logic::automatic_mode_minimal_integration`
3. `logic::prompt_region_governance`

## 不由内部回归替代的项目

以下能力仍需最终实机验收：

1. 后台模式真实网页提交、轮询和完成判定
2. 前台模式对当前页面的真实复用
3. prompt 对应区域与结果图区的现场绑定
4. 独立浏览器登录态、挑战页与恢复路径
5. 最终截图与页面真实结果是否一致

这些项目的步骤和口径统一收在 `references/live-acceptance-runbook.md`。

## 使用规则

以下规则只适用于本矩阵的开发验收场景，不适用于正式生图运行：

1. 改关键链路前，先跑一次 `python scripts/run_regression_suite.py`
2. 改完后，再跑一次同样的回归
3. 如果内部回归失败，先修内部问题，不要直接把问题转嫁给用户实机测试
4. 只有内部回归通过后，才进入真实 Midjourney 网页验收
5. 实机验收结束后，把结果按 runbook 里的通过 / 阻塞 / 失败口径记录下来
