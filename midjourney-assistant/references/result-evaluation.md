# 结果评估

## 目标

单轮执行完成后，必须做一次最小评估，而不是只说“提交成功”。

最终评估建立在两个前提上：

1. 本轮任务已经被正式流程判断为 `completed`
2. 已经拿到最终单次截图做审图

## 基础评估维度

1. 主体是否匹配
2. 风格是否接近
3. 构图是否可用
4. 是否适合当前用途
5. 是否存在明显偏离

## `run_verdict`

v0.1 允许这些值：

1. `success`
2. `usable_but_iterate`
3. `blocked_by_ui`
4. `blocked_by_context`
5. `stopped_by_user`
6. `stopped_by_budget`

## 判断规则

### `success`

结果已经满足本轮目标，或已经足够交付。

### `usable_but_iterate`

结果可用，但还不够最终使用。

### `blocked_by_ui`

页面、焦点、窗口状态、状态探针或截图链路阻断了任务。

### `blocked_by_context`

需求信息不足，或外部上下文不足以继续。

### `stopped_by_user`

用户明确中止。

### `stopped_by_budget`

达到当前轮次或预算上限，不再继续。
