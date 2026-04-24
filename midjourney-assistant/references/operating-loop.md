# 操作闭环

## v0.1 目标

当前版本要求稳定完成一个单轮闭环：

1. 启动路由
2. 需求理解
3. brief 编译
4. 记忆检索
5. 页面预检
6. prompt 生成
7. Midjourney 提交
8. 状态确认
9. 最终审图
10. 结果评估
11. 给用户结果结论

## 标准顺序

### 1. 需求编译

在真正编译 brief 之前，先运行：

1. `scripts/startup_route.py`
2. 如有任务，再运行 `scripts/task_state_init.py`

这样做的目的只有三个：

1. 首次启动且带需求时，先缓存任务
2. 自动模式和手动模式共享同一个任务对象
3. 用户不需要把需求重说一遍

先把用户原始需求变成结构化 brief。
至少产出：

1. `goal`
2. `deliverable`
3. `must_have`
4. `must_not_have`
5. `style_bias`
6. `iteration_budget`
7. `stop_rule`

### 2. 记忆检索

brief 编译后再读记忆，默认只读和当前 brief 强相关的内容。

### 2A. 模式选择

正式流程启动后，先明确当前进入哪一种模式：

1. 自动模式：assistant 自己执行网页预检、输入、提交、状态确认和结果回读；自动模式默认后台模式，也就是 `isolated_browser`
2. 手动模式：assistant 只负责输出 prompt、参数建议、提交要点、结果评估和下一轮方向；用户自己去网页生成

除“谁执行网页操作”之外，两种模式共享同一套需求理解、brief 编译、记忆检索、prompt 生成、结果评估和迭代逻辑。

`v0.2` 起不要再只靠文案补问模式，而是先运行 `scripts/mode_route.py`：

1. 如果用户已显式给出手动模式，直接采用
2. 如果用户显式说“后台模式”，直接采用自动模式并锁定 `isolated_browser`
3. 如果用户显式说“前台模式”，直接采用自动模式并锁定 `window_uia`
4. 如果需求语义已经明显偏向自动或手动，直接采用
5. 如果只命中自动模式而没有说后台或前台，默认使用 `isolated_browser`
6. 只有判断不出来时，才补问一次模式

### 3. 页面预检（自动模式）

先确认：

1. 浏览器进程存在
2. Midjourney 目标窗口存在
3. 当前站点和路由可识别
4. 目标窗口可见且未最小化
5. 当前页面可提交
6. 当前输入是否被门禁允许

自动模式的页面预检要先看 `automatic_execution_backend`：

1. `isolated_browser`：检查独立浏览器运行状态、登录态、目标页面和输入区是否可用
2. `window_uia`：检查当前已打开窗口、可见性、门禁和输入区是否可用

只要当前后端对应的控制条件不满足，就不要进入真实输入。

### 4. prompt 生成

先确定当前阶段，再生成 prompt。
v0.1 默认首轮用 `explore`。

### 5. 提交与状态闭环（自动模式）

正式提交按 `automatic_execution_backend` 选择执行器：

1. `isolated_browser`：走 `scripts/midjourney_isolated_browser_once.mjs`
2. `window_uia`：走 `scripts/midjourney_generate_once.ps1`

`window_uia` 这条旧链内部固定执行：

1. `browser_preflight`
2. `window_state_probe`
3. `window_control_gate`
4. 提交前基线状态探针
5. `midjourney_visible_window_submit`
6. UIA 轮询确认本轮任务已开始
7. UIA 轮询确认本轮任务已完成
8. 完成后单次窗口截图

`isolated_browser` 这条默认后台链要求：

1. 通过独立 `Chromium 浏览器 profile + remote debugging port` 执行；脚本会优先复用上次成功的浏览器，否则自动探测本机可用的 Edge、Chrome、Brave、Vivaldi、Arc
2. 不碰用户当前正在使用的主浏览器窗口
3. 如果独立浏览器未登录或落到挑战页，直接返回明确阻塞原因

这里有三个关键约束：

1. “是否在生成”和“是否已完成”优先以 UIA 状态探针判断
2. 截图只在确认完成后做一次，用来审图
3. 校准点位只在确认任务已经真正开始后才保存

### 5A. 手动模式交付

手动模式下不做网页输入和提交，assistant 只负责：

1. 输出当前轮可直接复制使用的 prompt
2. 补充必要的参数建议、提交说明和本轮目标
3. 明确告诉用户生成后需要回传什么：截图、结果描述或错误状态
4. 根据用户回传继续做结果评估、问题判断和下一轮 prompt 迭代

两种模式的差异仅在于网页操作由谁执行，不改变其余流程。

`v0.2` 起，手动模式交付优先由 `scripts/manual_mode_prepare.py` 生成，不要每次临场拼接话术。

### 6. 异常与回退

如果主链被阻断，按这个顺序处理：

1. 门禁不允许输入：停止并说明阻塞原因
2. UIA 状态探针读不到窗口：标记 `status_probe_fallback_needed`
3. 状态探针在开始阶段超时：标记 `start_timeout`
4. 状态探针在完成阶段超时：标记 `complete_timeout`

状态探针失败时，允许退回到最终截图人工复核，但不要再把连续截图轮询恢复成默认路径。

### 7. 结果评估

最终评估发生在“已完成 + 已截最终图”之后，而不是提交后立刻给结论。

`v0.2` 起，评估结果还要继续进入 `scripts/next_action_decide.py`，把 verdict 变成下一步动作，而不是只停在一条结论上。

### 8. 收尾

单轮结束后的默认动作只有一个：

1. 给用户结果结论，然后结束

如果当前已经进入 `v0.2` 多轮任务态，则优先交给 `scripts/task_orchestrate.py` 判断：

1. 是否继续下一轮
2. 是否转手动模式
3. 是否因为 budget 或 context 结束

只有在用户明确要求“记录 / 复盘 / 排障”时，才额外写回：

1. 原始运行日志
2. `status_transitions`
3. `status_probe_fallback_needed`
4. `final_capture.output_path`
5. 如有新偏好信号，再写用户画像候选
