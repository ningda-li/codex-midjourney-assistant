# Midjourney 风格分类法

## 作用

用户说的“高级、冷、时尚、游戏设计感、电影感”都不是可直接执行的 prompt。  
本文件负责把抽象中文风格诉求拆成可组合的视觉语言。

## 使用原则

1. 每轮先定一个主风格家族
2. 再补 1 到 3 个视觉锚点，不要堆十几个抽象词
3. 风格词必须服务于交付物，不是单独炫词

## 八个主风格家族

### 1. 写实摄影

适用：

1. 产品图
2. 电商图
3. 时尚拍摄

常用英文锚点：

1. `realistic photography`
2. `studio lighting`
3. `clean background`
4. `high detail`

### 2. 电影感概念

适用：

1. 角色海报
2. 场景概念图
3. 剧情感 KV

常用英文锚点：

1. `cinematic concept art`
2. `dramatic lighting`
3. `atmospheric depth`
4. `production-ready mood`

### 3. 游戏角色设定

适用：

1. 英雄角色
2. 职业设定
3. 阵营化角色

常用英文锚点：

1. `game character concept art`
2. `hero-shooter design language`
3. `front-facing full-body standing pose`
4. `clear costume silhouette`

### 4. 时尚编辑

适用：

1. 时装方向
2. 服装设定
3. 品牌形象图

常用英文锚点：

1. `fashion editorial`
2. `fashion-forward outfit`
3. `tailored silhouette`
4. `luxury styling`

### 5. 产品广告

适用：

1. 商业包装
2. 硬件广告
3. 宣传主视觉

常用英文锚点：

1. `premium product visualization`
2. `advertising shot`
3. `hero product lighting`
4. `commercial finish`

### 6. 平面海报 / 图形设计

适用：

1. 平面海报
2. 图文排版底图
3. 视觉传播图

常用英文锚点：

1. `graphic poster composition`
2. `bold shapes`
3. `high-contrast layout`
4. `clean negative space`

### 7. 动画 / 风格化插画

适用：

1. 二次元
2. 动漫角色
3. 风格化插画项目

常用英文锚点：

1. `stylized illustration`
2. `anime-inspired rendering`
3. `clean linework`
4. `cel-shaded look`

### 8. 材质 / 工艺研究

适用：

1. 面料试样
2. 表面语言探索
3. 结构细节图

常用英文锚点：

1. `material study`
2. `surface detail focus`
3. `fabric texture clarity`
4. `construction detail`

## 风格词的拆法

抽象中文需求要拆成四层：

1. 媒介：摄影、概念艺术、插画、海报、产品广告
2. 调性：冷峻、华丽、克制、未来、复古
3. 细节：面料、笔触、颗粒、灯光、配色
4. 用途：提案、设定、封面、电商、KV

## 常见映射例子

1. “无畏契约风格”优先映射为 `Valorant-inspired tactical hero-shooter design language`
2. “现代时尚风格的服装”优先映射为 `modern fashion-forward outfit`
3. “高端产品广告感”优先映射为 `premium commercial product visualization`
4. “像设定图，不要海报感”优先映射为 `clean character design sheet presentation`

## 禁止做法

1. 不要把十几个同义风格词堆在一起
2. 不要同时混三个主风格家族
3. 不要把平台名直接当风格说明而不解释视觉特征

## 输出约束

`style_goal` 至少要拆成：

1. `style_family`
2. `mood_keywords`
3. `surface_and_material_cues`
4. `delivery_context`
