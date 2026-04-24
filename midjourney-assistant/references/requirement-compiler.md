# 需求编译规则

## 目标

把用户原始自然语言编译成结构化 brief。  
编译后的 brief 是后续记忆检索、prompt 生成和执行的唯一上游输入。

## 必备字段

必须产出这些字段：

1. `goal`
2. `deliverable`
3. `must_have`
4. `must_not_have`
5. `style_bias`
6. `iteration_budget`
7. `stop_rule`

## 字段含义

### `goal`

本轮真正想要生成什么。

### `deliverable`

这轮结果最终要以什么形式交付，例如：

1. 一组可筛选四宫格
2. 一张可继续放大的方向图
3. 一张可直接用于提案的成图

### `must_have`

必须满足的硬约束。

### `must_not_have`

明确不能出现的内容、风格、语义或元素。

### `style_bias`

用户倾向的风格方向，不一定是硬约束，但应优先满足。

### `iteration_budget`

本次任务最多允许用几轮来逼近目标。

### `stop_rule`

什么时候可以结束，不再继续生图。

## 缺失信息处理

如果缺失信息不影响单轮执行，允许补默认值继续。  
如果缺失信息会直接影响结果方向，只做必要澄清。

## 默认值

如果用户没有明确给：

1. `deliverable` 默认是“一组可用于筛选的 Midjourney 结果”
2. `iteration_budget` 默认是 `1`
3. `must_have`、`must_not_have`、`style_bias` 默认是空数组
4. `stop_rule` 默认是“完成当前单轮生成并给出结果判断”
