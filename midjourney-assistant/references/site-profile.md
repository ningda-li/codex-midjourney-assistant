# 页面与窗口规则

## 浏览器规则

1. v0.1 不自动恢复最小化窗口
2. v0.1 不强制抢前台
3. v0.1 不改变目标窗口形态

## v0.1 红线

以下动作一律禁止：

1. 调用 `ShowWindow`、`SW_RESTORE` 或等价恢复逻辑
2. 把最大化窗口改回普通窗口
3. 为了操作 Midjourney 主动抢前台焦点
4. 临时写额外 Win32 焦点绕过逻辑替代 skill 自带脚本

如果目标窗口不在前台：

1. 先跑 `scripts/window_control_gate.ps1`
2. 如果返回 `can_activate_by_click=true`，只允许一次普通点击
3. 如果窗口已最小化，只允许要求用户手动恢复

## Midjourney 页面规则

当前 v0.1 关注两个站点：

1. `midjourney.com`
2. `alpha.midjourney.com`

正式流程里的判断来源固定分层：

1. 窗口与路由：`browser_preflight.ps1` + `window_state_probe.ps1`
2. 门禁与输入：`window_control_gate.ps1` + `midjourney_visible_window_submit.ps1`
3. 状态判断：`midjourney_status_probe.ps1`
4. 最终审图：`midjourney_window_capture.ps1`

## 提交前检查

每次准备输入前，至少确认：

1. 目标窗口正确
2. 页面可操作
3. 没有明显遮挡弹层
4. 门禁允许直接输入，或允许一次安全激活点击

## 提交后检查

每次提交后，正式流程按这个顺序判断：

1. 先用 UIA 状态探针判断本轮任务是否出现
2. 再判断是否进入 `generating`
3. 再判断是否进入 `completed`
4. 只有在 `completed` 之后才截最终图

不要再默认做连续截图轮询。

## 校准缓存

`midjourney_visible_window_submit.ps1` 的点位策略分两层：

1. 先查已验证校准缓存
2. 未命中时再用参数默认值

缓存 key 由以下字段组成：

1. `process_name`
2. `show_state`
3. `window_width`
4. `window_height`

只有在正式流程确认“本轮任务已经真正开始”后，才允许把当前点位写成已验证缓存。
