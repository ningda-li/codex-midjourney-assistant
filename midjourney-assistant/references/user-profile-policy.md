# 用户画像写回规则

## 双层结构

用户画像固定分成两层：
1. 结构化字段
2. 非结构化备注

## 结构化字段

当前稳定画像字段如下：
1. `industry`
2. `work_types`
3. `style_preferences`
4. `content_preferences`
5. `taboos`
6. `quality_tendency`
7. `updated_at`

## signal 与提升

只有用户明确要求记录、复盘或排障，或调用方显式传入 `--allow-memory-writeback` 时，自动模式真实执行完成后才允许提取画像候选并写入 signal：
1. `style_preferences` 写入 `type=style`
2. `content_preferences` 写入 `type=content`
3. `work_types` 写入 `type=work_type`
4. `taboos` 写入 `type=taboo`
5. `industry` 写入 `type=industry`
6. `quality_tendency` 写入 `type=quality_tendency`

提升规则：
1. 单次候选先写 signal，不直接进入稳定画像
2. 同一 signal 累计达到 2 次后，自动提升为稳定画像
3. `promote_to_profile=true`、`confirmed=true` 或高置信候选可直接提升
4. 提升时只提升满足条件的字段，不把整份候选一股脑并进稳定画像

## 写回原则

1. 明确被用户否定的信息必须能被纠正或遗忘
2. 长期用户画像和项目上下文不能混写
3. 用户画像只记录稳定偏好，不记录某一轮临时执行细节
4. 非结构化备注只记录高价值、可复用的信息

## 控制面

用户画像必须支持最小控制面：
1. 查看：`scripts/profile_view.py`
2. 纠正：`scripts/profile_correct.py`
3. 遗忘：`scripts/profile_forget.py`

## 主链接入

显式允许写回时，自动模式真实执行一轮后按下面顺序处理：
1. `scripts/profile_signal_extract.py`
2. `scripts/profile_merge.py`

普通生图、普通手动 prompt 交付、普通自动执行后默认不触发这条链；手动模式当前不自动提取画像 signal。
