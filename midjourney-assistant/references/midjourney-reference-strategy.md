# Midjourney 参考体系策略

## 作用

参考图不是“越多越好”，而是要先定义职责。  
本文件用于回答：

1. 什么时间只用文字
2. 什么时间该上参考图
3. 上哪一种参考能力最合适

## 先判断参考图职责

每张参考图只能先承担一个主职责：

1. 主体一致性
2. 风格气质
3. 构图语义
4. 项目级方向

如果一张图同时被要求承担四种职责，基本都会失控。

## 六类参考策略

### 1. 纯文本

适用：

1. 用户需求已经足够清楚
2. 当前目标是先看方向，不是复用某张现成图

优点：

1. 自由度高
2. 便于探索

风险：

1. 一致性弱

### 2. Image Prompt

适用：

1. 用户更在意构图关系或整体语义
2. 场景关系很复杂

优点：

1. 能快速借用画面结构

风险：

1. 容易把不需要的内容也一起带进来
2. 如果只给图片不给文本，不要再规划 `--stylize` 或 `--weird`
3. 最好先把参考图裁到接近最终画幅

补充技巧：

1. 一张图 + 文本，适合“借构图，再补语义”
2. 多张图无文本，适合做视觉混合
3. `--iw` 当前按 `0–3` 控制参考图影响

### 3. Style Reference

适用：

1. 用户要“这个风格，不是这个人”
2. 需要统一系列图的光感、材质、媒介和色调

优点：

1. 风格控制明确

风险：

1. 如果文字里继续堆很多冲突风格词，会互相抵消

补充技巧：

1. `--sw` 默认 `100`
2. `V7` 图片型 `Style Reference` 默认 `--sv 6`
3. `--sref random` 适合探索，不适合直接做稳定交付
4. 多个 style code 可以叠加，但越叠越容易脏

### 4. Omni Reference

适用：

1. 用户要“还是这个角色 / 这个产品 / 这个主体”
2. 多轮延续、一致性任务

优点：

1. 解决主体连续性最直接

风险：

1. 不该让它承担风格统一的全部职责
2. 当前只限 `V7`
3. 结果要进入编辑链时，通常要先去掉 `--oref / --ow`

补充技巧：

1. 只能用一张 Omni 图
2. `--ow` 默认 `100`
3. 非必要不要高于 `400`
4. 它可以与 `Style Reference` 和 `Image Prompt` 叠加，但要明确主次

### 5. Moodboards / Personalization

适用：

1. 项目级风格定调
2. 用户有长期偏好

优点：

1. 比单张 `Style Reference` 更适合大范围气质控制

风险：

1. 不适合精确修某一张图的小问题

### 6. Style Explorer / Style Creator

适用：

1. 用户想先找现成 style code
2. 用户想沉淀自己的可复用风格码

优点：

1. `Style Explorer` 适合搜、试、收藏现成 `sref`
2. `Style Creator` 适合把风格探索沉淀成长期资产

风险：

1. `Style Creator` 预览本身会消耗 GPU
2. 带旧 style code 继续做 `Style Creator` 时会叠码，不会自动合并
3. 这两者都不是“直接替代单轮 prompt 理解”的捷径

## 混用优先级

如果要混用，先按这个顺序判断主次：

1. 主体连续性：`Omni Reference`
2. 风格统一：`Style Reference` 或 `Moodboards`
3. 画面语义：`Image Prompt`
4. 长期偏好：`Personalization`
5. 风格资产化：`Style Explorer / Style Creator`

原则：

1. 一个任务最多一个主主体参考
2. 一个任务最多一个主风格策略
3. 文字 prompt 负责剩余语义补全

## Describe 的位置

`Describe` 不是参考能力本体，而是参考整理工具。

适用：

1. 用户只会说“我喜欢这张”
2. 需要从图里抽出风格词、光照词、构图词

输出要求：

1. 只抽可复用视觉词
2. 去掉和当前任务无关的枝节

## 当前实战提醒

1. `Style Explorer` 的 `Like` 不会影响 `Personalization`
2. `Explore` 页给别人图片点 `Like` 会影响对应版本的 `Global Profile`
3. `Moodboards` 不能和 `--sv / --sw` 一起规划
4. `Omni Reference` 当前不适合与 `Fast Mode / Draft Mode / Conversational Mode / --q 4` 同时规划

## 常见错误

1. 把风格图拿去做主体延续
2. 把主体图拿去要求它承担整套品牌视觉
3. 同时塞太多参考图却不写主职责
4. 参考已经很强，还继续堆长串抽象风格词
5. 用 style code 叠 style code，结果把风格叠脏

## 选择模板

内部 `reference_strategy` 至少要写：

1. `primary_reference_role`
2. `reference_inputs`
3. `why_this_reference`
4. `why_not_other_reference_types`
5. `mixing_rules`
