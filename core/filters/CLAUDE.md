[根目录](../../CLAUDE.md) > [core](../CLAUDE.md) > **filters**

## 模块职责
`core/filters` 是消息过滤引擎。在 `Forwarder` 抓取到候选消息后、进入合并与发送队列之前，决定哪些消息应当被丢弃。采用**黑名单语义**：命中规则的消息被丢弃，其余原样保留。

## 入口与启动
- 由 `Forwarder.__init__` 实例化 `MessageFilter(config)` 并在抓取流程中调用。
- 不持有独立的调度入口，纯协作式组件。

## 对外接口
- `MessageFilter.filter_messages(messages, logger_func=None) -> list[tuple[str, Message]]`
  - 入参：`(channel_name, Message)` 元组列表 + 可选日志回调。
  - 返回：通过过滤的消息子集（保持原顺序，不修改入参对象）。
  - 短路：若 `forward_config` 中既无 `filter_keywords` 也无 `filter_regex`，直接原样返回，不做任何遍历。
  - 命中日志：丢弃时调用 `logger_func(f"[Filter] Filtered by ...")`（若提供）。

## 关键依赖与配置
- 依赖 `AstrBotConfig`（读取 `forward_config` 子表）与 Telethon 的 `Message` 类型（仅用 `.text` 字段）。
- 配置项（均位于 `forward_config` 下；每频道 `source_channels[]` 可用同名字段覆盖，由 `Forwarder` 合并配置时决定）：
  - `filter_keywords: list[str]`：命中任一即丢弃。匹配方式为大小写不敏感子串（`keyword.lower() in msg.text.lower()`）。
  - `filter_regex: str`：Python 正则，`re.search(filter_regex, msg.text)` 命中即丢弃，**区分大小写**。正则非法时记 `logger.error` 并跳过该规则（不抛出，保证抓取主循环不中断）。

## 数据模型
- 无独立持久化状态，纯内存计算。

## 测试与质量
- `tests/test_message_filter.py`：覆盖空配置短路、关键词命中丢弃、正则命中丢弃、非法正则容错、`logger_func` 回调、大小写不敏感等。
- 另由 `tests/test_forwarder_send_pending.py` 间接覆盖集成路径。

## 相关文件清单
- `__init__.py` — 仅导出 `MessageFilter`
- `message_filter.py` — `MessageFilter` 实现

## 变更记录 (Changelog)
- **2026-07-04 (补扫)**: 修正接口描述（此前误记为 `should_keep` / `include_keywords` / `exclude_keywords`；实际为 `filter_messages` / `filter_keywords` / `filter_regex` 黑名单语义）；补全配置项、匹配语义与测试说明。
- **2026-07-04**: 初始化模块文档。
