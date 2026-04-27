# Personalization 与风格系统桥接

## 目录

- 当前基线
- 这四类东西不是一回事
  - 1. Personalization
  - 2. Moodboards
  - 3. Style Reference
  - 4. Style Creator
- Personalization 当前官方要点
- Style Creator 当前官方技巧
- Style Explorer 与风格系统
- 实际判断顺序
- 当前输出要求


## 当前基线

按 Midjourney 官方文档和官方更新，截至 `2026-04-24`，这块能力要按下面理解：

1. `Personalization` 本体兼容 `V6` 和 `V7`
2. `V7` 的 Personalization profiles 可兼容 `V8.1 Alpha`
3. `Moodboards` 兼容 `V6` 和 `V7`
4. `Style Creator` 是 `midjourney.com` 上的 `V7` 风格码生成工具
5. 当前 Web 端的 Personalization 已经改成“滚动选图”的新界面，不再按旧的 pair ranking 口径理解

## 这四类东西不是一回事

### 1. Personalization

作用：

1. 注入用户长期偏好
2. 让模型更懂“这个用户平时喜欢什么”

适合：

1. 长期个人使用
2. 用户有稳定偏好
3. 任务允许继承个人审美

不适合：

1. 严格客户 brief
2. 单轮一次性项目
3. 需要非常窄的项目风格约束

### 2. Moodboards

作用：

1. 用一组图建立更宽范围的项目级视觉调性
2. 比单张 `Style Reference` 更适合定整套方向

适合：

1. 品牌视觉方向
2. 系列任务统一气质
3. 用户给了一组灵感图

不适合：

1. 单张图的小修小改
2. 已经有一张非常明确的风格参考图

兼容提醒：

1. `Moodboards` 不能和 `--sv`、`--sw` 一起规划
2. 它更像宽范围风格边界，不是精确复制某种具体笔触

### 3. Style Reference

作用：

1. 借单张或少量参考锁“这张图的味道”
2. 解决颜色、材质、光照、笔触和氛围统一

适合：

1. 单轮风格锁定
2. 多张图要统一成同一视觉味道
3. 用户给的是明确风格样张

### 4. Style Creator

作用：

1. 生成可复用的 `--sref` 风格码
2. 把“我喜欢这种风格”沉淀成长期资产

适合：

1. 用户想沉淀长期可复用风格码
2. 需要把风格探索成果固化成内部资产
3. 项目之后还会长期反复使用同一种风格语言

不适合：

1. 当前只是赶一轮出图
2. 风格方向还没定
3. 用户只是想借一张图的现成风格

## Personalization 当前官方要点

1. 每个模型版本都有自己的 `Global Profile`
2. 想创建更多 profile，先解锁对应版本的全局档
3. 在 Explore 页给别人图片点 `Like`，会影响对应版本的 `Global Profile`
4. 额外 profile 会跟随你当前默认版本创建
5. `--p pID` 提交后会自动转成具体 code
6. 旧 code 仍然能继续用，但 profile 会随着继续选图而进化

## Style Creator 当前官方技巧

1. 预览图使用 GPU 时间
2. 进入时最好先用简单 prompt，看清风格本身在做什么
3. 如果只是想更快做风格预览，可以加 `--draft`
4. 大多数风格在 `5–10` 轮开始趋稳
5. `10–15` 轮还会继续变细
6. 超过 `15` 轮后变化通常已经很小
7. 如果你带着旧的 style code 进入 Style Creator，新旧 code 会叠加生效，不会自动合并

## Style Explorer 与风格系统

当前风格系统不只剩 `Style Creator`：

1. `Style Explorer` 适合先搜和试现成 `sref` 码
2. `Try Style` 适合快速套到当前 prompt 上看方向
3. 给 style code 点 `Like` 只会收藏 style，不会反向训练 `Personalization`
4. 如果找到接近的 style code，再决定要不要进一步进入 `Style Creator` 沉淀自己的风格码

## 实际判断顺序

真实任务里先按这个顺序判断：

1. 用户要的是长期个人偏好，还是当前项目风格
2. 如果是长期个人偏好，优先看 `Personalization`
3. 如果是整套项目方向，优先看 `Moodboards`
4. 如果是单张或短批次风格统一，优先看 `Style Reference`
5. 如果用户先想试现成风格码，优先看 `Style Explorer`
6. 如果用户明确要沉淀成可复用风格码，再进入 `Style Creator`

## 当前输出要求

如果本轮涉及风格系统，至少要写清楚：

1. `personalization_plan`
2. `style_system_plan`
3. 本轮到底是：
   - 不桥接
   - 只桥接 Personalization
   - 只桥接 Moodboards
   - 只桥接 Style Reference
   - 先走 Style Explorer
   - 进入 Style Creator 沉淀风格码

不能只说“上个风格能力试试”，必须明确是哪一种。
