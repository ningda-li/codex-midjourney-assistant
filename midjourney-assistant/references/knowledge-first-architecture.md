# 知识主链优先改造规格

## 目录

- 1. 目标
- 2. 新定位
  - 2.1 主从关系
  - 2.2 自动模式的角色
  - 2.3 手动模式的角色
- 3. 核心原则
  - 3.1 知识先行
  - 3.2 prompt 不是翻译结果，而是解法表达
  - 3.3 所有任务都必须直接应用知识层
  - 3.4 自动与手动共用同一知识判断
- 4. 运行时强制主链
- 5. 知识层必须覆盖的模块
  - 5.1 能力地图
  - 5.2 参数与控制知识
  - 5.3 任务类型知识
  - 5.4 视觉诊断知识
  - 5.5 参考体系知识
  - 5.6 用户与项目桥接知识
- 6. 推荐文件结构
- 7. 核心数据对象
  - 7.1 `task_model`
  - 7.2 `solution_plan`
  - 7.3 `prompt_package`
  - 7.4 `diagnosis_report`
- 8. 新增脚本职责
  - 8.1 `task_classify.py`
  - 8.2 `solution_plan_build.py`
  - 8.3 `prompt_strategy_select.py`
  - 8.4 `prompt_diagnose.py`
- 9. 输出规范
  - 9.1 默认用户可见输出
  - 9.2 专业解释模式
  - 9.3 强制规则
- 10. 自动与手动模式的统一规则
  - 10.1 自动模式
  - 10.2 手动模式
  - 10.3 严格一致性
- 11. 必须补齐的知识文档
  - 11.1 `midjourney-capability-map.md`
  - 11.2 `midjourney-parameter-system.md`
  - 11.3 `midjourney-task-types.md`
  - 11.4 `midjourney-diagnosis-playbook.md`
  - 11.5 `midjourney-reference-strategy.md`
  - 11.6 `midjourney-style-taxonomy.md`
  - 11.7 `midjourney-iteration-strategy.md`
  - 11.8 `midjourney-failure-patterns.md`
- 12. 当前架构要求
- 13. 非目标
- 14. 最终要求


## 1. 目标

把 `midjourney-assistant` 从“会操作 Midjourney 网页的执行器”改造成“以 Midjourney 专业知识驱动的出图问题解决器”。

自动操作网页不再是主链，只是最后一层执行能力。  
真正的主链变成：

1. 理解用户视觉问题
2. 选择合适的 Midjourney 解法
3. 生成专业 prompt 与迭代策略
4. 再决定由谁执行网页操作

## 2. 新定位

### 2.1 主从关系

以后本 skill 的能力优先级固定为：

1. `需求理解`
2. `Midjourney 解法设计`
3. `prompt 与参数编排`
4. `结果诊断与迭代`
5. `自动或手动执行`

### 2.2 自动模式的角色

自动模式只是 `执行层`，职责是：

1. 复用知识层已经给出的 `prompt_package`
2. 完成网页提交、等待、回读、截图
3. 把结果送回诊断层

自动模式不得绕过知识层直接提交。

### 2.3 手动模式的角色

手动模式与自动模式共享同一套知识主链。  
两者唯一差异是：

1. 自动模式：assistant 执行网页操作
2. 手动模式：用户执行网页操作

除这一点之外，需求理解、解法判断、prompt 生成、参数策略、结果诊断必须完全一致。

## 3. 核心原则

### 3.1 知识先行

任何带任务的对话都必须先判断：

1. 用户在解决什么视觉问题
2. 这个问题在 Midjourney 里该用什么能力
3. 该用什么 prompt 结构
4. 是否需要参考体系
5. 是否需要参数控制
6. 下一轮如何收敛

在这些问题没有内部回答之前，不允许直接产出最终 prompt。

### 3.2 prompt 不是翻译结果，而是解法表达

最终 prompt 必须来自 `solution_plan`，而不是来自逐字翻译。

### 3.3 所有任务都必须直接应用知识层

任何一次带真实需求的对话，都必须至少生成以下三个内部对象：

1. `task_model`
2. `solution_plan`
3. `prompt_package`

如果当前是结果反馈轮，还必须生成：

4. `diagnosis_report`

### 3.4 自动与手动共用同一知识判断

不能存在：

1. 手动模式有完整思考
2. 自动模式只做机械提交

这属于架构错误。

## 4. 运行时强制主链

以后所有正式任务固定走这条链：

1. `startup_route`
2. `task_state_init`
3. `task_classify`
4. `solution_plan_build`
5. `prompt_strategy_select`
6. `manual_mode_prepare`
7. `mode_route`
8. `automatic_execute` 或 `manual_handoff`
9. `result_readback`
10. `prompt_diagnose`
11. `next_action_decide`
12. `memory/project/profile/template writeback`

其中：

1. `task_classify` 到 `prompt_strategy_select` 属于知识主链
2. `automatic_execute` 属于执行层
3. `result_readback` 到 `prompt_diagnose` 属于诊断层

## 5. 知识层必须覆盖的模块

### 5.1 能力地图

定义 Midjourney 原生能力与适用场景，包括：

1. Prompt 本体
2. Style Reference
3. Character Reference
4. Omni Reference
5. Personalization
6. Moodboards
7. Describe
8. Prompt Shortener
9. Run as HD
10. 版本与站点差异

输出目标：

1. 当前任务建议使用哪些能力
2. 当前任务明确不建议使用哪些能力

### 5.2 参数与控制知识

必须系统覆盖：

1. 参数作用
2. 参数风险
3. 参数之间的组合边界
4. 哪类任务该加参数
5. 哪类任务故意不加参数

最低覆盖范围：

1. 画幅与构图类
2. 风格强度类
3. 随机性与探索类
4. 一致性控制类
5. 参考图强度类

### 5.3 任务类型知识

至少建立这些任务类型：

1. 角色设计
2. 角色设定图
3. 提案图
4. 海报
5. 场景概念图
6. 产品图
7. 服装与材质探索
8. 品牌视觉方向图
9. 多轮延续与统一性任务
10. 参考图驱动任务

每类必须定义：

1. 问题定义模板
2. 推荐能力组合
3. 推荐 prompt 结构
4. 参数默认策略
5. 常见失败模式
6. 标准迭代方向

### 5.4 视觉诊断知识

必须覆盖：

1. 主体不对
2. 风格不稳
3. 构图不可用
4. 服装或材质不对
5. 角色一致性不足
6. 提案感不够
7. 商业完成度不足
8. 参考图引用失真

每种问题至少给出：

1. 现象描述
2. 最可能原因
3. 优先修正项
4. 下一轮 prompt 调整方向

### 5.5 参考体系知识

必须明确回答：

1. 什么时候只用文字 prompt
2. 什么时候优先上参考图
3. 什么时候用 Style Reference
4. 什么时候用 Character Reference
5. 什么时候用 Omni Reference
6. 多参考混用时如何排优先级

### 5.6 用户与项目桥接知识

负责把以下内容转成 Midjourney 可执行策略：

1. 用户长期偏好
2. 用户禁忌
3. 当前项目风格规则
4. 当前项目连续性要求
5. 当前任务与历史轮次的关联

## 6. 推荐文件结构

```text
midjourney-assistant/
  references/
    knowledge-first-architecture.md
    midjourney-capability-map.md
    midjourney-parameter-system.md
    midjourney-task-types.md
    midjourney-diagnosis-playbook.md
    midjourney-reference-strategy.md
    midjourney-style-taxonomy.md
    midjourney-iteration-strategy.md
    midjourney-failure-patterns.md
  assets/
    task-type-schema.json
    capability-routing.json
    parameter-presets.json
    diagnosis-rules.json
    prompt-composition-rules.json
  scripts/
    task_classify.py
    solution_plan_build.py
    prompt_strategy_select.py
    prompt_diagnose.py
```

说明：

1. `references/` 放长知识文档
2. `assets/` 放可机读规则
3. `scripts/` 放运行时强约束逻辑

## 7. 核心数据对象

### 7.1 `task_model`

用于定义用户到底在做什么任务。

建议字段：

```json
{
  "task_type": "",
  "task_stage": "",
  "deliverable_type": "",
  "subject_type": "",
  "style_goal": [],
  "composition_goal": [],
  "consistency_goal": [],
  "must_have": [],
  "must_not_have": [],
  "open_questions": [],
  "risk_flags": []
}
```

### 7.2 `solution_plan`

用于定义本轮 Midjourney 解法。

建议字段：

```json
{
  "primary_strategy": "",
  "recommended_capabilities": [],
  "blocked_capabilities": [],
  "reference_strategy": "",
  "parameter_strategy": "",
  "prompt_structure": [],
  "iteration_strategy": "",
  "quality_target": "",
  "diagnosis_focus": []
}
```

### 7.3 `prompt_package`

用于定义可执行提交内容。

建议字段：

```json
{
  "prompt_text": "",
  "parameter_bundle": [],
  "reference_bundle": [],
  "submission_notes": [],
  "result_readback_focus": [],
  "prompt_stage": ""
}
```

### 7.4 `diagnosis_report`

用于反馈轮和结果判断。

建议字段：

```json
{
  "observed_issues": [],
  "likely_causes": [],
  "keep_list": [],
  "change_list": [],
  "next_round_goal": "",
  "next_round_strategy": "",
  "next_round_prompt_delta": []
}
```

## 8. 新增脚本职责

### 8.1 `task_classify.py`

职责：

1. 把需求归类成任务类型
2. 判断当前处于探索、收敛还是成品确认
3. 产出 `task_model`

输入：

1. `task`
2. 用户消息
3. 项目上下文
4. 用户画像

输出：

1. `task_model`
2. 更新后的 `task`

### 8.2 `solution_plan_build.py`

职责：

1. 根据 `task_model` 选择 Midjourney 解法
2. 决定是否启用原生能力桥接
3. 产出 `solution_plan`

### 8.3 `prompt_strategy_select.py`

职责：

1. 根据 `solution_plan` 选择 prompt 结构
2. 决定参数策略
3. 决定参考策略
4. 生成 `prompt_package`

### 8.4 `prompt_diagnose.py`

职责：

1. 接收用户反馈或结果评估输入
2. 判断问题属于哪种失败模式
3. 产出 `diagnosis_report`
4. 为下一轮生成明确修正方向

## 9. 输出规范

### 9.1 默认用户可见输出

默认只给用户结论，不暴露内部对象。

最低输出应包括：

1. 你理解的目标
2. 本轮给出的方案或结果
3. 下一步建议

### 9.2 专业解释模式

当用户问“为什么这样做”时，允许展开解释：

1. 为什么归到这个任务类型
2. 为什么选这套 Midjourney 能力
3. 为什么用这类 prompt 结构
4. 为什么这一轮优先改这些问题

### 9.3 强制规则

无论自动还是手动：

1. 必须先有 `solution_plan`
2. 再有 `prompt_package`
3. 不允许跳过知识判断直接产出 prompt

## 10. 自动与手动模式的统一规则

### 10.1 自动模式

自动模式只负责：

1. 消费 `prompt_package`
2. 提交网页
3. 读取结果
4. 把结果送回 `prompt_diagnose`

### 10.2 手动模式

手动模式只负责：

1. 向用户交付 `prompt_package`
2. 告诉用户怎么提交
3. 等用户回传结果后进入 `prompt_diagnose`

### 10.3 严格一致性

同一需求在自动和手动模式下，必须满足：

1. `task_model` 一致
2. `solution_plan` 一致
3. `prompt_package` 主体一致

## 11. 必须补齐的知识文档

### 11.1 `midjourney-capability-map.md`

写什么：

1. 每种能力是什么
2. 适用场景
3. 不适用场景
4. 与其他能力的组合关系

### 11.2 `midjourney-parameter-system.md`

写什么：

1. 关键参数分组
2. 典型任务的参数策略
3. 高风险参数组合
4. 参数误用案例

### 11.3 `midjourney-task-types.md`

写什么：

1. 任务类型定义
2. 识别规则
3. 每类任务的目标和交付物
4. 每类任务的默认策略

### 11.4 `midjourney-diagnosis-playbook.md`

写什么：

1. 结果偏差分类
2. 常见误判
3. 对应修正动作

### 11.5 `midjourney-reference-strategy.md`

写什么：

1. 参考图使用场景
2. 多参考优先级
3. 参考冲突处理

### 11.6 `midjourney-style-taxonomy.md`

写什么：

1. 常见风格类别
2. 风格词边界
3. 容易混淆的风格概念

### 11.7 `midjourney-iteration-strategy.md`

写什么：

1. 探索轮怎么写
2. 收敛轮怎么写
3. 成品确认轮怎么写

### 11.8 `midjourney-failure-patterns.md`

写什么：

1. 失败模式
2. 失败信号
3. 修复优先级

## 12. 当前架构要求

任意真实需求都应先进入知识主链，再进入手动交付或自动执行。核心要求：

1. 先判断任务类型、参考需求、参数边界和风险点
2. 先生成 `solution_plan`，再生成最终 prompt
3. 最终 prompt 体现明确解法，不做词语堆砌
4. 结果反馈后先做问题诊断，再决定下一轮改法
5. 自动模式和手动模式共用同一套知识判断

## 13. 非目标

这些能力不是知识主链的主导目标：

1. 扩展更多桌面自动化技巧
2. 优先打磨窗口操作细节
3. 补更多截图脚本

这些能力可以保留在执行层，但不能取代需求理解、任务建模、prompt 策略和结果诊断。

## 14. 最终要求

当用户直接发一句需求时，正确行为是：

1. 先看懂他要解决的视觉问题
2. 先判断该怎么用 Midjourney 解决
3. 再生成专业 prompt 和策略
4. 最后才决定由 assistant 操作网页，还是由用户自己操作
