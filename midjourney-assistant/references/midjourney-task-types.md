# Midjourney 任务类型

## 目录

- 作用
- 第一层：`task_type`
- 第二层：`task_stage`
- 第三层：`revision_mode`
- 第四层：`lock_state`
- 核心业务规则
  - 1. `换配色` 不是 `继续重画角色`
  - 2. 没有基底锁定，不做真配色
  - 3. `colorway_only` 必须是单变量
- 任务建模输出要求


## 作用

这个文档负责先把“用户到底想改什么”说清楚，再决定 prompt 怎么写。

从现在开始，任务判断不再只有两层：

1. `task_type`：这是什么交付物
2. `task_stage`：现在是探索、收敛还是定稿

还必须再加两层：

3. `revision_mode`：这一轮允许改什么
4. `lock_state`：当前设计锁到了什么程度

如果没有这两层，系统就会把“换配色”误当成“继续重画一轮角色”。

## 第一层：`task_type`

`task_type` 决定你在做什么图。

常见类型：

1. `character_design`
   - 角色方向探索、角色提案、角色概念
2. `character_sheet`
   - 正面全身、角色设定图、清晰展示服装结构
3. `proposal_visual`
   - 多方向筛选图、方向板
4. `poster`
   - 海报、封面、宣传图
5. `scene_concept`
   - 场景概念、环境概念
6. `product_visual`
   - 产品图、商业产品表现
7. `fashion_material`
   - 服装语言、面料和工艺探索
8. `brand_visual_direction`
   - 品牌或项目的整体视觉方向
9. `continuity_batch`
   - 延续上一轮同一主体
10. `reference_driven`
   - 以现有参考图为主锚点
11. `image_edit`
   - 局部编辑、扩图、局部换材质
12. `video_generation`
   - 静帧转短视频
13. `style_system_build`
   - 风格码沉淀、风格系统整理

## 第二层：`task_stage`

`task_stage` 决定当前轮次在项目中的位置。

1. `explore`
   - 先找方向，允许差异拉开
2. `converge`
   - 保留已对的东西，只修关键缺口
3. `finalize`
   - 只做交付级收尾，不再重新发散

## 第三层：`revision_mode`

`revision_mode` 决定这一轮到底允许改什么。

这是当前 skill 最关键的状态层。

1. `new_direction`
   - 允许换方向、换人、换版型、换整体设计语言
   - 适用于“重做几版”“看看新方向”“可以换人”
2. `structure_refine`
   - 主体方向保留，只改结构、剪裁、服装语言、材质分区
   - 适用于“版型不对”“剪裁过时”“更像游戏设计一点”
3. `colorway_only`
   - 只改颜色分配，不允许重画新人
   - 适用于“换几个配色”“配色难看”“看别的颜色”
4. `finish_only`
   - 只改画面完成度、背景干净度、交付感
   - 适用于“更干净一点”“更高级一点”“收尾”
5. `local_edit`
   - 只改指定局部
   - 适用于编辑器链，不走整轮重生图

## 第四层：`lock_state`

`lock_state` 决定当前设计到底锁到了什么程度。

1. `unlocked`
   - 还没有可靠基底，允许继续换方向
2. `soft_locked`
   - 有“尽量保持”的对象，但还没有可靠基底图或强锚点
3. `hard_locked`
   - 已有明确基底图或当前结果已被接受为锚点
   - 进入 `colorway_only` 时，理想状态必须是这个级别

## 核心业务规则

### 1. `换配色` 不是 `继续重画角色`

当用户说“换配色”时，默认语义是：

1. 同一个人
2. 同一套版型
3. 同一套服装分区
4. 同一套材质关系
5. 只改颜色

如果这一轮允许换脸、换发型、换轮廓、换服装结构，那就不是 `colorway_only`，而是 `new_direction` 或 `structure_refine`。

### 2. 没有基底锁定，不做真配色

如果任务是 `colorway_only`，但当前没有 `hard_locked` 基底：

1. 不要假装自己在做配色
2. 先回到锁基底的步骤
3. 或者明确告诉用户当前其实是在看不同方向，不是在看 colorway

### 3. `colorway_only` 必须是单变量

`colorway_only` 每轮只能动一个轴：

1. 顶部服装颜色
2. 下装颜色
3. 金属件 / 设备颜色
4. 点缀色

不允许同一轮同时把人物、版型、材质和配色一起重做。

## 任务建模输出要求

`task_model` 至少要包含：

1. `task_type`
2. `task_stage`
3. `revision_mode`
4. `change_axis`
5. `lock_state`
6. `locked_elements`
7. `deliverable_type`
8. `must_have`
9. `must_not_have`
10. `risk_flags`

如果用户需求跨了多层目标，主输出原则是：

1. 先定 `task_type`
2. 再定 `revision_mode`
3. 最后再写 prompt
