[根目录](../CLAUDE.md) > **common**

## 模块职责
`common` 模块提供插件范围内的无状态实用函数和持久层基础组件，独立于核心业务逻辑，可复用度极高。
- **数据持久化**: `storage.py` 处理以 JSON 为基础的数据读写（原子化写入，防止崩溃破损）。
- **文本工具**: `text_tools.py` 处理 Telegram 名字解析转换、文本清洗、多平台内容规范化等操作。

## 入口与启动
- 由 `Main.__init__` 实例化 `Storage(self.plugin_data_dir / "data.json")`。
- `text_tools` 为纯函数模块，按需导入。

## 关键文件与对外接口
- `Storage` (`storage.py`):
  - `save()`: 原子保存方法（`.tmp` + `os.replace`）。
  - `get_channel_data()`: 获取针对某个通道维护的状态（`last_post_id` / `channel_id` / `pending_queue` 等）。
  - `reset_inactive_channels(active_channels)`: 启动时把不在配置内的频道 `last_post_id` 重置，避免遗留状态污染。
- `text_tools.py`:
  - `normalize_telegram_channel_name(raw: str) -> str`
  - `to_telethon_entity(channel_name: str) -> str | int`
  - `is_numeric_channel_id(value) -> bool`

## 关键依赖与配置
- 仅依赖标准库（`json` / `os` / `pathlib`），无外部包。
- 数据目录由上层 `Main._get_plugin_data_dir()` 计算并注入（`data/plugin_data/astrbot_plugin_telegram_forwarder/data.json`）。

## 数据模型
- `data.json` 结构（每频道一份）:
  - `last_post_id`: 已处理到的最新消息 id。
  - `channel_id`: 解析后的 Telethon 实体 id。
  - `pending_queue`: 抓取成功但尚未发送完成的消息队列。

## 测试与质量
- `tests/test_storage_pending_retry.py` 覆盖 pending 队列重试与原子写。

## 常见问题 (FAQ)
- **Q**: 为什么 Storage 更新失败或重载报错？
  **A**: 确保你只向 Storage 中存放 JSON 可序列化的基本类型，并使用框架提供的数据目录（避免存放至插件本身的临时环境目录）。
- **Q**: 插件更新后 data.json 还在吗？
  **A**: 在。`data/plugin_data/` 与插件代码目录 `data/plugins/` 是隔离的，更新代码不会动数据。

## 相关文件清单
- `__init__.py`
- `storage.py` — `Storage` 原子 JSON 存储
- `text_tools.py` — 频道名规范化与 Telethon 实体解析

## 变更记录 (Changelog)
- **2026-07-04**: 补充 `reset_inactive_channels` / `is_numeric_channel_id` 接口；新增数据目录、数据模型与测试章节。
- **2026-06-08**: 初始化模块级自适应文档。
