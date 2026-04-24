# 版本与站点分流

## 当前官方基线

按 Midjourney 官方文档与官方更新，截至 `2026-04-24` 先按这套基线理解：

1. 主站 `midjourney.com` 当前默认主模型是 `V7`
2. `V8.1 Alpha` 于 `2026-04-14` 上线，但只在 `alpha.midjourney.com`
3. `V8.1 Alpha` 仍是早期测试环境，能力和成本都可能继续变化
4. 如果现场行为与本基线冲突，以现场结果为准，并把变化写回站点记忆

## 固定路由

### 1. 主站路由

1. `midjourney.com` -> `v7-main-site`
2. `alpha.midjourney.com` -> `v8-1-alpha`
3. 主站明确切 `--niji 7` -> `niji-7`
4. 无法可靠识别 -> `unknown`

### 2. 编辑路由

编辑链要单独看，不要和生图主模型混为一谈：

1. `Editor` 在 `V8.1 Alpha` 上当前仍按 `V6.1` 编辑链工作
2. `Pan / Zoom Out` 在 `V7` 里也仍走 `V6.1`
3. 因此只要任务是 `局部重绘 / 扩图 / Pan / Zoom Out / Editor / Retexture`，都要额外打 `edit_route=editor-v6-1`

## 版本能力重点

### 1. V7 主站

当前按主力正式链理解：

1. 默认正式版本
2. 支持 `Omni Reference`
3. 支持 `Draft Mode`
4. 支持 `Conversational Mode`
5. 支持 `Style Reference / Moodboards / Personalization / Image Prompts`
6. 支持 `--q`、`--no`、`--raw`、`--stylize`、`--chaos`、`--weird`、`--exp`
7. 主站的动漫分支按 `Niji 7` 处理，不要和 `V8.1 Alpha` 混写

### 2. V8.1 Alpha

当前按测试链理解：

1. 只在 `alpha.midjourney.com`
2. 当前不出现在主站 Create/Organize 流里
3. 默认可生成 `2K` HD 图，可切换 `HD / SD`
4. `Run as HD` 是把 `SD` 结果的 seed-locked prompt 重新跑一遍 `HD`
5. 支持 `Raw / Stylize / Chaos / Weird / Image Prompts / Image Weight / Style References / Moodboards / Personalization / Conversational Mode`
6. `V7` 的 Personalization profile 可兼容到 `V8.1 Alpha`
7. `V8.1 Alpha` 当前不支持 `Omni Reference`、`--no`、`--q`、`Multi-Prompts (::)`、`Draft Mode`、`Turbo Mode`
8. `V8.1 Alpha` 当前支持 `Relax / Fast`，但不是 `Turbo`
9. `Seed` 在 `V8.1 Alpha` 当前按“`99%` 相同”理解，不要承诺完全逐像素复现

### 3. Niji 7

当前按主站的动漫专用链理解：

1. `Niji 7` 于 `2026-01-09` 上线
2. 它更字面、更扁平、更强调线条与清晰度
3. 广义的“vibe 型模糊提示词”在 `Niji 7` 上不要照旧习惯写
4. 如果用户明确要动漫、插画、日系角色线稿倾向，再显式切 `Niji 7`

### 4. V6 / V6.1 兼容链

不要把它当当前默认正式链，但要记住它还负责一部分旧能力：

1. `Character Reference` 是 `V6` 时代能力
2. `Multi-Prompts / Weights` 当前按 `V6 / Niji 6` 兼容链理解
3. `Editor / Vary Region / Pan / Zoom Out / Retexture` 的底层兼容口径仍大量落在 `V6.1`
4. `--stop` 当前只按 `V6 及更早` 的 legacy 参数理解

## 当前不要混淆的兼容边界

### 1. 只在 V7 主链使用

1. `Omni Reference`
2. `Omni Reference Weight`
3. `Draft Mode`
4. `Niji 7`

### 2. 不要默认规划到 V8.1 Alpha

在 `v8-1-alpha` 路由下，默认不要把这些能力写进执行策略：

1. `--q`
2. `--no`
3. `Multi-Prompts (::)`
4. `Omni Reference`
5. `Draft Mode`
6. `Turbo Mode`

### 3. 只当旧能力兼容说明

1. `Character Reference`
2. `Character Weight`
3. `--stop`

## 关键现场规则

### 1. 如果是 V8.1 Alpha

优先记住这些：

1. 它不是主站正式默认链
2. 它已经重新支持 `Image Prompts / --iw`
3. 它当前不该照搬 `V7` 的 `Omni / --q / --no / Draft`
4. 如果要编辑图片，转入 `Editor` 时按 `V6.1` 口径判断

### 2. 如果是带 Omni 的任务

1. 默认走 `V7`
2. 后续要进 `Editor / Vary Region / Pan / Zoom Out / Retexture` 时，先去掉 `--oref` / `--ow`

### 3. 如果是文字、视频或编辑任务

要先判断它属于哪条能力链：

1. 文字渲染：主生图链
2. 视频：视频链
3. 局部编辑 / 扩图 / Retexture：编辑链

不要只看站点，不看任务类型。

## 输出字段

运行期至少保留这些字段：

1. `site_route`
2. `version_route`
3. `edit_route`
4. `compatibility_notes`
