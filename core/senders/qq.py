import asyncio
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from telethon.tl.types import Message

from astrbot.api import AstrBotConfig, logger, star
from astrbot.api.event import MessageChain
from astrbot.api.message_components import (
    File,
    Image,
    Node,
    Nodes,
    Plain,
    Record,
    Video,
)

try:
    from astrbot.core.utils.path_util import path_Mapping
except ImportError:
    path_Mapping = None

from ...common.text_tools import (
    clean_telegram_text,
    is_numeric_channel_id,
    to_telethon_entity,
)
from ..downloader import MediaDownloader


@dataclass(frozen=True)
class QQSendSummary:
    acked_batch_indexes: tuple[int, ...] = ()
    failed_batch_indexes: tuple[int, ...] = ()
    deferred_batch_indexes: tuple[int, ...] = ()
    error_types: dict[int, str] = field(default_factory=dict)


class QQSender:
    """
    负责将消息转发到 QQ 群
    """

    def __init__(
        self, context: star.Context, config: AstrBotConfig, downloader: MediaDownloader
    ):
        self.context = context
        self.config = config
        self.downloader = downloader
        self._group_locks = {}  # 群锁，防止并发发送
        self.platform_id = None  # 动态捕获的平台 ID
        self.bot = None  # 动态捕获的 bot 实例
        self.node_name = None  # 合并转发消息时显示的 bot 昵称
        self._target_circuit: dict[str, dict[str, float | int]] = {}

    async def _ensure_node_name(self, bot, cache_fallback: bool = False):
        """获取 bot 昵称"""
        if self.node_name and self.node_name != "AstrBot":
            return self.node_name

        try:
            # 优先从登录信息获取
            info = await bot.get_login_info()
            if info and (nickname := info.get("nickname")):
                self.node_name = str(nickname)
                logger.debug(f"[QQSender] 获取到 bot 昵称: {self.node_name}")
            else:
                logger.debug("[QQSender] 未能从登录信息获取到昵称")
        except Exception as e:
            logger.debug(f"[QQSender] 获取 bot 昵称异常: {e}")

        if cache_fallback and not self.node_name:
            self.node_name = "AstrBot"
        return self.node_name

    def _get_lock(self, group_id):
        if group_id not in self._group_locks:
            self._group_locks[group_id] = asyncio.Lock()
        return self._group_locks[group_id]

    def _map_path(self, fpath: str) -> str:
        """映射文件路径（用于跨 Docker 容器文件访问）"""
        try:
            if path_Mapping is None:
                return fpath
            core_config = getattr(self.context, "_config", None)
            if core_config:
                mappings = core_config.get("platform_settings", {}).get(
                    "path_mapping", []
                )
                if mappings:
                    return path_Mapping(mappings, fpath)
        except Exception:
            pass
        return fpath

    def _dispatch_media_file(self, fpath: str, audio_mode: str = "record"):
        ext = os.path.splitext(fpath)[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
            return [Image.fromFileSystem(fpath)]
        if ext in (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"):
            if audio_mode == "file_only":
                mapped = self._map_path(fpath)
                return [
                    File(
                        file=mapped,
                        url="",
                        name=os.path.basename(fpath),
                    )
                ]
            record = Record.fromFileSystem(fpath)
            if getattr(record, "path", None) is None:
                setattr(record, "path", fpath)
            return [record]
        if ext in (".mp4", ".mkv", ".mov", ".webm", ".avi"):
            mapped = self._map_path(fpath)
            if mapped != fpath:
                return [Video(file=f"file:///{mapped}")]
            return [Video.fromFileSystem(fpath)]
        mapped = self._map_path(fpath)
        return [
            File(
                file=mapped,
                url="",
                name=os.path.basename(fpath),
            )
        ]

    @staticmethod
    def _get_sender_display_name(msg: Message) -> str:
        post_author = getattr(msg, "post_author", None)
        if post_author:
            return str(post_author)
        sender = getattr(msg, "sender", None)
        if not sender:
            return ""
        for attr in ("first_name", "title", "username"):
            value = getattr(sender, attr, None)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _reply_media_label(msg: Message) -> str:
        if getattr(msg, "photo", None):
            return "[图片]"
        if getattr(msg, "video", None):
            return "[视频]"
        if getattr(msg, "audio", None) or getattr(msg, "voice", None):
            return "[音频]"
        if getattr(msg, "file", None) or getattr(msg, "document", None):
            return "[文件]"
        return "[消息]"

    def _build_reply_preview(
        self, reply_msg: Message, strip_links: bool = False
    ) -> str:
        sender_name = self._get_sender_display_name(reply_msg)
        if getattr(reply_msg, "text", None):
            preview = clean_telegram_text(reply_msg.text, strip_links=strip_links)
            preview = " ".join(part for part in preview.splitlines() if part).strip()
            if len(preview) > 100:
                preview = preview[:100].rstrip() + "..."
        else:
            preview = self._reply_media_label(reply_msg)
        if not preview:
            preview = self._reply_media_label(reply_msg)
        if sender_name:
            return f"↩ 回复 {sender_name}:\n{preview}"
        return f"↩ 回复:\n{preview}"

    async def _prefetch_reply_previews(
        self, msgs: list[Message], src_channel: str, strip_links: bool = False
    ) -> dict[int, str]:
        existing_ids = {getattr(msg, "id", None) for msg in msgs}
        reply_ids = []
        for msg in msgs:
            reply_header = getattr(msg, "reply_to", None)
            reply_id = getattr(reply_header, "reply_to_msg_id", None)
            if not reply_id or reply_id in existing_ids or reply_id in reply_ids:
                continue
            reply_ids.append(reply_id)
        if not reply_ids:
            return {}

        client = getattr(self.downloader, "client", None)
        if client is None:
            return {}

        try:
            reply_msgs = await client.get_messages(
                to_telethon_entity(src_channel), ids=reply_ids
            )
        except Exception as e:
            logger.warning(f"[QQSender] 获取 reply 预览失败: {e}")
            return {}

        preview_cache: dict[int, str] = {}
        if not reply_msgs:
            return preview_cache

        if not isinstance(reply_msgs, list):
            reply_msgs = [reply_msgs]

        for reply_msg in reply_msgs:
            if not reply_msg or getattr(reply_msg, "id", None) is None:
                continue
            preview_cache[reply_msg.id] = self._build_reply_preview(
                reply_msg, strip_links=strip_links
            )
        return preview_cache

    @staticmethod
    def _batch_contains_audio(nodes_data: list[list[object]]) -> bool:
        return any(
            isinstance(component, Record) for node in nodes_data for component in node
        )

    @staticmethod
    def _should_merge_batch_nodes(batch_data: dict) -> bool:
        special_types = (Record, File, Video)
        has_special_media = any(
            isinstance(component, special_types)
            for node in batch_data.get("nodes_data", [])
            for component in node
        )
        return (
            len(batch_data.get("nodes_data", [])) > 1
            and not batch_data.get("contains_audio", False)
            and not has_special_media
        )

    async def _send_processed_batch(
        self,
        batch_data: dict,
        unified_msg_origin: str,
        self_id: int,
        node_name: str,
        target_session: str,
    ) -> None:
        def normalize_file_payload(component: File) -> File:
            if getattr(component, "file", None):
                return component
            compat_file = getattr(component, "file_", None)
            if compat_file:
                normalized = File(
                    file=compat_file, name=getattr(component, "name", None)
                )
                if getattr(component, "file_", None) is not None:
                    setattr(normalized, "file_", component.file_)
                return normalized
            return component

        def log_file_payload(component: File) -> None:
            logger.info(
                f"[QQSender] File payload -> {target_session}: "
                f"file={getattr(component, 'file', None)!r}, "
                f"file_={getattr(component, 'file_', None)!r}, "
                f"url={getattr(component, 'url', None)!r}, "
                f"name={getattr(component, 'name', None)!r}"
            )

        all_nodes_data = batch_data["nodes_data"]
        if self._should_merge_batch_nodes(batch_data):
            message_chain = MessageChain()
            nodes_list = [
                Node(uin=self_id, name=node_name, content=nc) for nc in all_nodes_data
            ]
            message_chain.chain.append(Nodes(nodes_list))
            await self.context.send_message(unified_msg_origin, message_chain)
            logger.info(
                f"[QQSender] {node_name} -> {target_session}: 相册合并 ({len(all_nodes_data)} 节点)"
            )
            return

        if batch_data.get("contains_audio"):
            for node_components in all_nodes_data:
                common_components = []
                for component in node_components:
                    if isinstance(component, Record):
                        chain = MessageChain([component])
                        await self.context.send_message(unified_msg_origin, chain)
                        path = getattr(component, "path", None)
                        if path:
                            mapped = self._map_path(path)
                            file_component = File(
                                file=mapped,
                                url="",
                                name=os.path.basename(path),
                            )
                            log_file_payload(file_component)
                            file_chain = MessageChain([file_component])
                            await self.context.send_message(
                                unified_msg_origin, file_chain
                            )
                    else:
                        if isinstance(component, File):
                            component = normalize_file_payload(component)
                        common_components.append(component)
                if common_components:
                    chain = MessageChain()
                    chain.chain.extend(common_components)
                    await self.context.send_message(unified_msg_origin, chain)
            logger.info(
                f"[QQSender] {node_name} -> {target_session}: 单条消息 (音频已拆分补文件)"
            )
            return

        special_types = (Record, File, Video)
        batch_has_special = False
        for node_components in all_nodes_data:
            component_types = [
                type(component).__name__ for component in node_components
            ]
            logger.debug(
                f"[QQSender] target={target_session} node_types={component_types}"
            )
            has_special = any(isinstance(c, special_types) for c in node_components)
            if has_special:
                batch_has_special = True
                for c in node_components:
                    if isinstance(c, special_types):
                        if isinstance(c, File):
                            c = normalize_file_payload(c)
                            log_file_payload(c)
                        chain = MessageChain([c])
                        await self.context.send_message(unified_msg_origin, chain)
                common_components = [
                    c for c in node_components if not isinstance(c, special_types)
                ]
                if common_components:
                    chain = MessageChain()
                    chain.chain.extend(common_components)
                    await self.context.send_message(unified_msg_origin, chain)
                continue

            message_chain = MessageChain()
            message_chain.chain.extend(node_components)
            await self.context.send_message(unified_msg_origin, message_chain)

        if batch_has_special:
            logger.info(
                f"[QQSender] {node_name} -> {target_session}: 单条消息 (已拆分特殊媒体)"
            )
            return

        logger.info(f"[QQSender] {node_name} -> {target_session}: 单条普通消息")

    async def initialize_runtime(self):
        """Best-effort bootstrap for platform_id/bot before first forward."""
        await self._bootstrap_qq_runtime()
        if not self.platform_id:
            logger.warning(
                "[QQSender] 初始化阶段未捕获到 QQ 平台实例，后续若使用纯数字目标将无法自动拼接会话名。"
            )

    def _get_platform_instances(self) -> list:
        pm = getattr(self.context, "platform_manager", None)
        if not pm:
            return []
        if hasattr(pm, "platform_insts"):
            insts = getattr(pm, "platform_insts") or []
            return list(insts)
        if hasattr(pm, "get_insts"):
            try:
                insts = pm.get_insts()
                return list(insts or [])
            except Exception:
                return []
        return []

    @staticmethod
    def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
        seen = set()
        result: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    @staticmethod
    def _split_qq_targets(targets: list) -> tuple[list[str], list[str]]:
        """Split config targets into full sessions and numeric group IDs."""
        session_targets: list[str] = []
        group_ids: list[str] = []
        for raw in targets:
            if raw is None:
                continue
            if isinstance(raw, str):
                val = raw.strip()
            else:
                val = str(raw).strip()
            if not val:
                continue
            if ":" in val:
                session_targets.append(val)
            elif val.isdigit():
                group_ids.append(val)
            else:
                logger.warning(f"[QQSender] Ignore invalid QQ target: {val}")
        return session_targets, group_ids

    @staticmethod
    def _session_platform_ids(session_targets: list[str]) -> list[str]:
        platform_ids: list[str] = []
        for session in session_targets:
            if ":" not in session:
                continue
            platform_ids.append(session.split(":", 1)[0])
        return QQSender._dedupe_keep_order(platform_ids)

    @staticmethod
    def _classify_send_error(error: Exception) -> str:
        message = str(error)
        if "WebSocket API call timeout" in message:
            return "timeout"
        if "retcode=1200" in message:
            return "retcode_1200"
        if "wrong session ID" in message:
            return "wrong_session_id"
        return "send_failed"

    def _target_is_open(self, target_session: str, now_ts: float) -> bool:
        circuit = self._target_circuit.get(target_session)
        if not circuit:
            return False
        open_until = float(circuit.get("open_until", 0.0))
        if open_until <= 0:
            return False
        if open_until <= now_ts:
            self._target_circuit.pop(target_session, None)
            return False
        return True

    def _record_target_failure(
        self,
        target_session: str,
        *,
        threshold: int,
        cooldown_sec: int,
        now_ts: float,
    ) -> None:
        circuit = self._target_circuit.get(target_session) or {
            "consecutive_failures": 0,
            "open_until": 0.0,
        }
        consecutive_failures = int(circuit.get("consecutive_failures", 0)) + 1
        open_until = 0.0
        if consecutive_failures >= threshold:
            open_until = now_ts + float(cooldown_sec)
        self._target_circuit[target_session] = {
            "consecutive_failures": consecutive_failures,
            "open_until": open_until,
        }

    def _record_target_success(self, target_session: str) -> None:
        self._target_circuit.pop(target_session, None)

    async def _bootstrap_qq_runtime(
        self, preferred_platform_ids: list[str] | None = None
    ):
        """Try to fetch platform_id and bot from context.platform_manager."""
        if self.platform_id and self.bot:
            return

        platforms = self._get_platform_instances()
        if not platforms:
            return

        candidates = []
        for platform in platforms:
            try:
                meta = platform.meta()
                pid = getattr(meta, "id", None)
                pname_raw = str(getattr(meta, "name", ""))
                pname = pname_raw.lower()
                if pid:
                    candidates.append((platform, str(pid), pname, pname_raw))
            except Exception:
                continue

        if not candidates:
            return

        selected = None
        preferred = set(preferred_platform_ids or [])
        if preferred:
            for item in candidates:
                if item[1] in preferred:
                    selected = item
                    break
        if selected is None and self.platform_id:
            for item in candidates:
                if item[1] == self.platform_id:
                    selected = item
                    break
        if selected is None:
            for item in candidates:
                if item[2] == "aiocqhttp":
                    selected = item
                    break
        if selected is None:
            for item in candidates:
                if "qq" in item[2] or "onebot" in item[2]:
                    selected = item
                    break
        if selected is None:
            selected = candidates[0]

        platform, pid, _, pname_raw = selected
        self.platform_id = pid
        logger.debug(
            f"[QQSender] 捕获到 QQ 平台: platform_id={pid}, platform_name={pname_raw or 'unknown'}"
        )

        try:
            if hasattr(platform, "get_client"):
                self.bot = platform.get_client()
            elif hasattr(platform, "bot"):
                self.bot = platform.bot
        except Exception as e:
            logger.debug(f"[QQSender] Bootstrap bot from platform failed: {e}")

        if self.bot:
            await self._ensure_node_name(self.bot, cache_fallback=False)

    async def send(
        self,
        batches: list[list[Message]],
        src_channel: str,
        display_name: str | None = None,
        effective_cfg: dict[str, object] | None = None,
        involved_channels: list[str]
        | None = None,  # 新增：混合模式时传入实际涉及的频道列表
    ):
        """
        转发消息到 QQ 群
        """
        if effective_cfg is None:
            effective_cfg = {}

        if involved_channels and len(involved_channels) > 1:
            global_cfg = self.config.get("forward_config", {})
            strip_links = global_cfg.get("strip_markdown_links", False)
            exclude_text_on_media = global_cfg.get("exclude_text_on_media", False)
        else:
            exclude_text_on_media = effective_cfg.get("exclude_text_on_media", False)
            strip_links = effective_cfg.get("strip_markdown_links", False)

        channel_specific_targets = effective_cfg.get("effective_target_qq_sessions", [])
        if channel_specific_targets:  # 非空列表 → 使用频道专属配置
            effective_qq_targets = channel_specific_targets
        else:
            effective_qq_targets = self.config.get("target_qq_session", [])

        qq_targets = effective_qq_targets

        if not qq_targets or not batches:
            return QQSendSummary()

        if isinstance(qq_targets, int):
            qq_targets = [qq_targets]
        elif not isinstance(qq_targets, list):
            return QQSendSummary()

        session_targets_cfg, numeric_group_ids = self._split_qq_targets(qq_targets)
        preferred_platform_ids = self._session_platform_ids(session_targets_cfg)
        if numeric_group_ids or session_targets_cfg:
            await self._bootstrap_qq_runtime(
                preferred_platform_ids=preferred_platform_ids
            )

        context_target_sessions = list(session_targets_cfg)
        qq_platform_id = self.platform_id
        if numeric_group_ids:
            if qq_platform_id:
                context_target_sessions.extend(
                    [
                        f"{qq_platform_id}:GroupMessage:{gid}"
                        for gid in numeric_group_ids
                    ]
                )
            else:
                logger.warning(
                    "[QQSender] Localhost mode cannot resolve platform_id for numeric QQ target. "
                    "Use full session name (platform:MessageType:target_id) or ensure platform is loaded."
                )
        context_target_sessions = self._dedupe_keep_order(context_target_sessions)

        if not context_target_sessions:
            return QQSendSummary()

        forward_cfg = self.config.get("forward_config", {})
        qq_merge_threshold = forward_cfg.get("qq_merge_threshold", 0)
        fail_fast_limit = forward_cfg.get("qq_target_fail_fast_consecutive_failures", 3)
        try:
            fail_fast_limit = int(fail_fast_limit)
        except (TypeError, ValueError):
            fail_fast_limit = 3
        if fail_fast_limit < 1:
            fail_fast_limit = 1

        target_circuit_fail_threshold = forward_cfg.get(
            "target_circuit_fail_threshold", 3
        )
        try:
            target_circuit_fail_threshold = int(target_circuit_fail_threshold)
        except (TypeError, ValueError):
            target_circuit_fail_threshold = 3
        if target_circuit_fail_threshold < 1:
            target_circuit_fail_threshold = 1

        target_circuit_cooldown_sec = forward_cfg.get(
            "target_circuit_cooldown_sec", 300
        )
        try:
            target_circuit_cooldown_sec = int(target_circuit_cooldown_sec)
        except (TypeError, ValueError):
            target_circuit_cooldown_sec = 300
        if target_circuit_cooldown_sec < 1:
            target_circuit_cooldown_sec = 1

        # 兼容大合并调用时多包一层的情况
        real_batches = []
        for item in batches:
            if (
                isinstance(item, list)
                and item
                and all(isinstance(sub, list) for sub in item)
            ):
                real_batches.extend(item)
            else:
                real_batches.append(item)

        if not real_batches:
            logger.debug("[QQSender] 展平后无有效批次，跳过发送")
            return QQSendSummary()

        logger.debug(
            f"[QQSender] 接收到 {len(batches)} 批次，展平后 {len(real_batches)} 个逻辑批次"
        )

        if context_target_sessions:
            bot = self.bot
            if not bot and qq_platform_id:
                try:
                    platform = self.context.get_platform_inst(qq_platform_id)
                    if platform:
                        if hasattr(platform, "get_client"):
                            bot = platform.get_client()
                        elif hasattr(platform, "bot"):
                            bot = platform.bot
                except Exception as e:
                    logger.error(f"[QQSender] Failed to get bot instance: {e}")
            if bot and not self.bot:
                self.bot = bot

            self_id = 0
            node_name = (
                await self._ensure_node_name(bot, cache_fallback=True)
                if bot
                else "AstrBot"
            )
            if bot:
                try:
                    info = await bot.get_login_info()
                    self_id = info.get("user_id", 0)
                except Exception as e:
                    logger.error(f"[QQSender] 获取 bot 详细信息失败: {e}")

            # ─── 判断是否为混合频道大合并模式 ───
            is_mixed_big_merge = bool(involved_channels and len(involved_channels) > 1)

            if is_mixed_big_merge:
                # 构造清晰的多频道 From
                formatted = [
                    ch if is_numeric_channel_id(ch) else f"@{ch.lstrip('@')}"
                    for ch in sorted(involved_channels)
                ]
                if len(formatted) <= 4:
                    channels_str = " ".join(formatted)
                else:
                    channels_str = (
                        " ".join(formatted[:4]) + f" 等{len(formatted) - 4}个频道"
                    )
                header = f"From {channels_str}:"
                logger.debug(f"[QQSender] 混合大合并 From: {header}")
            else:
                # 普通情况（单频道或独立频道模式）
                header_name = display_name or src_channel
                if not header_name.startswith("@") and not is_numeric_channel_id(
                    header_name.lstrip("@")
                ):
                    header_name = f"@{header_name}"
                header = f"From {header_name}:"

            # 预处理所有批次
            processed_batches = []
            target_successes = {
                batch_index: set() for batch_index in range(len(real_batches))
            }
            target_failures: dict[int, str] = {}
            deferred_batch_indexes: set[int] = set()
            header_added = False  # 用于混合模式：只在全局第一个节点加 header

            for batch_index, msgs in enumerate(real_batches):
                all_local_files = []
                all_nodes_data = []
                try:
                    reply_preview_cache = await self._prefetch_reply_previews(
                        msgs, src_channel, strip_links=strip_links
                    )
                    for i, msg in enumerate(msgs):
                        current_node_components = []
                        text_parts = []
                        if msg.text:
                            cleaned = clean_telegram_text(
                                msg.text, strip_links=strip_links
                            )
                            if cleaned:
                                text_parts.append(cleaned)

                        media_components = []
                        has_any_attachment = False
                        msg_max_size = getattr(msg, "_max_file_size", 0)
                        files = await self.downloader.download_media(
                            msg, max_size_mb=msg_max_size
                        )
                        for fpath in files:
                            all_local_files.append(fpath)
                            has_any_attachment = True
                            media_components.extend(self._dispatch_media_file(fpath))

                        should_exclude_text = (
                            exclude_text_on_media and has_any_attachment
                        )

                        reply_header = getattr(msg, "reply_to", None)
                        reply_id = getattr(reply_header, "reply_to_msg_id", None)
                        reply_preview = reply_preview_cache.get(reply_id)
                        if reply_preview and not should_exclude_text:
                            text_parts.insert(0, reply_preview)

                        # ─── 决定是否添加 From 头部 ───
                        add_header_this_time = False
                        # 媒体消息仅发送媒体模式下，不添加 From 头部
                        if not should_exclude_text:
                            if is_mixed_big_merge:
                                # 混合大合并：**只在整个合并的第一个消息**加 From
                                if not header_added and i == 0:
                                    add_header_this_time = True
                                    header_added = True
                            else:
                                # 普通/独立模式：每个小相册/单条的第一个消息加 From
                                if i == 0:
                                    add_header_this_time = True

                        if add_header_this_time:
                            if text_parts:
                                text_parts[0] = f"{header}\n\u200b{text_parts[0]}"
                            else:
                                current_node_components.append(
                                    Plain(f"{header}\n\u200b")
                                )

                        if not should_exclude_text:
                            for t in text_parts:
                                current_node_components.append(Plain(t + "\n"))

                        # 文字 + 特殊媒体(Video/Record/File)时拆分为独立 Node，
                        # 与单条消息路径的 special_types 拆分逻辑对齐 (issue#16)
                        # 注意：Image 不拆分（原设计：From header 在外层显示，内层只渲染图片）
                        _node_special_media = [
                            c
                            for c in media_components
                            if isinstance(c, (Video, Record, File))
                        ]
                        if (
                            not should_exclude_text
                            and text_parts
                            and _node_special_media
                        ):
                            if current_node_components:
                                all_nodes_data.append(current_node_components)
                            current_node_components = []

                        current_node_components.extend(media_components)

                        if current_node_components:
                            # 避免生成只有 header 的空节点
                            is_only_header = (
                                len(current_node_components) == 1
                                and isinstance(current_node_components[0], Plain)
                                and current_node_components[0].text.strip("\u200b\n")
                                in [header, ""]
                            )
                            if not is_only_header:
                                all_nodes_data.append(current_node_components)

                    if all_nodes_data:
                        processed_batches.append(
                            {
                                "batch_index": batch_index,
                                "nodes_data": all_nodes_data,
                                "local_files": all_local_files,
                                "contains_audio": self._batch_contains_audio(
                                    all_nodes_data
                                ),
                            }
                        )
                    else:
                        target_failures.setdefault(batch_index, "preprocess_empty")
                except Exception as e:
                    logger.error(f"[QQSender] 预处理消息批次异常: {e}")
                    target_failures.setdefault(
                        batch_index, self._classify_send_error(e)
                    )
                    self._cleanup_files(all_local_files)

            use_big_merge = (qq_merge_threshold > 1) and (
                len(processed_batches) >= qq_merge_threshold
            )
            if use_big_merge and not is_mixed_big_merge:
                logger.info(
                    f"[QQSender] 本次 {len(processed_batches)} 个逻辑单元 >= 阈值 {qq_merge_threshold}，转为整组合并转发"
                )

            # 发送到各个目标群组
            for target_session in context_target_sessions:
                if not target_session:
                    continue
                lock = self._get_lock(target_session)
                async with lock:
                    now_ts = time.time()
                    if self._target_is_open(target_session, now_ts):
                        logger.warning(
                            f"[QQSender] 目标 {target_session} 熔断冷却中，跳过本轮发送"
                        )
                        deferred_batch_indexes.update(range(len(real_batches)))
                        continue

                    unified_msg_origin = target_session

                    if use_big_merge or is_mixed_big_merge:
                        # ─── 大合并（包括混合模式） ───
                        # 按批次边界拆块，避免同一组图片/album 被拆到不同块
                        chunk_size = forward_cfg.get("qq_merge_chunk_size", 5)
                        chunk_delay = forward_cfg.get("qq_merge_chunk_delay", 3)

                        batch_chunks: list[list[dict]] = []
                        current_chunk_batches: list[dict] = []
                        current_chunk_nodes = 0
                        for batch_data in processed_batches:
                            batch_node_count = len(batch_data["nodes_data"])
                            if (
                                current_chunk_nodes + batch_node_count > chunk_size
                                and current_chunk_batches
                            ):
                                batch_chunks.append(current_chunk_batches)
                                current_chunk_batches = []
                                current_chunk_nodes = 0
                            current_chunk_batches.append(batch_data)
                            current_chunk_nodes += batch_node_count
                        if current_chunk_batches:
                            batch_chunks.append(current_chunk_batches)

                        total_chunks = len(batch_chunks)
                        consecutive_failures = 0
                        for chunk_idx, chunk_batches in enumerate(batch_chunks, 1):
                            chunk_nodes = []
                            chunk_batch_indexes = [
                                bd["batch_index"] for bd in chunk_batches
                            ]
                            for bd in chunk_batches:
                                chunk_nodes.extend(bd["nodes_data"])
                            try:
                                if len(chunk_nodes) > 1:
                                    nodes_list = [
                                        Node(uin=self_id, name=node_name, content=nc)
                                        for nc in chunk_nodes
                                    ]
                                    message_chain = MessageChain()
                                    message_chain.chain.append(Nodes(nodes_list))
                                    await self.context.send_message(
                                        unified_msg_origin, message_chain
                                    )
                                else:
                                    components = chunk_nodes[0]
                                    message_chain = MessageChain()
                                    message_chain.chain.extend(components)
                                    await self.context.send_message(
                                        unified_msg_origin, message_chain
                                    )
                                for batch_index in chunk_batch_indexes:
                                    target_successes[batch_index].add(target_session)
                                self._record_target_success(target_session)
                                consecutive_failures = 0
                                logger.info(
                                    f"[QQSender] {node_name} -> {target_session}: "
                                    f"{'混合' if is_mixed_big_merge else ''}大合并转发 "
                                    f"({chunk_idx}/{total_chunks}, 本块 {len(chunk_nodes)} 节点 / {len(chunk_batches)} 批次)"
                                )
                                if chunk_idx < total_chunks:
                                    await asyncio.sleep(chunk_delay)
                            except Exception as e:
                                logger.warning(
                                    f"[QQSender] 大合并转发到 {target_session} 失败 "
                                    f"(块 {chunk_idx}): {e}，降级为按批次保守发送"
                                )
                                chunk_failed = False
                                for batch_data in chunk_batches:
                                    batch_index = batch_data["batch_index"]
                                    try:
                                        await self._send_processed_batch(
                                            batch_data=batch_data,
                                            unified_msg_origin=unified_msg_origin,
                                            self_id=self_id,
                                            node_name=node_name,
                                            target_session=target_session,
                                        )
                                        target_successes[batch_index].add(
                                            target_session
                                        )
                                        self._record_target_success(target_session)
                                        await asyncio.sleep(1)
                                    except Exception as e2:
                                        chunk_failed = True
                                        target_failures.setdefault(
                                            batch_index,
                                            self._classify_send_error(e2),
                                        )
                                        self._record_target_failure(
                                            target_session,
                                            threshold=target_circuit_fail_threshold,
                                            cooldown_sec=target_circuit_cooldown_sec,
                                            now_ts=time.time(),
                                        )
                                        logger.error(
                                            f"[QQSender] 降级批次发送失败: {e2}"
                                        )
                                if chunk_failed:
                                    consecutive_failures += 1
                                else:
                                    consecutive_failures = 0
                                if (
                                    chunk_failed
                                    and consecutive_failures >= fail_fast_limit
                                ):
                                    remaining = sum(
                                        len(batch_data["nodes_data"])
                                        for chunk in batch_chunks[chunk_idx:]
                                        for batch_data in chunk
                                    )
                                    logger.warning(
                                        f"[QQSender] 连续 {consecutive_failures} 块失败，"
                                        f"停止本目标剩余 {remaining} 个节点"
                                    )
                                    break
                                await asyncio.sleep(5)
                    else:
                        # 普通发送（逐个小相册 / 单条）
                        consecutive_failures = 0
                        for batch_data in processed_batches:
                            batch_index = batch_data["batch_index"]
                            try:
                                await self._send_processed_batch(
                                    batch_data=batch_data,
                                    unified_msg_origin=unified_msg_origin,
                                    self_id=self_id,
                                    node_name=node_name,
                                    target_session=target_session,
                                )
                                target_successes[batch_index].add(target_session)
                                self._record_target_success(target_session)
                                consecutive_failures = 0
                                await asyncio.sleep(1)
                            except Exception as e:
                                consecutive_failures += 1
                                target_failures.setdefault(
                                    batch_index,
                                    self._classify_send_error(e),
                                )
                                self._record_target_failure(
                                    target_session,
                                    threshold=target_circuit_fail_threshold,
                                    cooldown_sec=target_circuit_cooldown_sec,
                                    now_ts=time.time(),
                                )
                                logger.error(
                                    f"[QQSender] 转发到 {target_session} 异常: {e}"
                                )
                                if consecutive_failures >= fail_fast_limit:
                                    logger.warning(
                                        f"[QQSender] 目标 {target_session} 连续失败 {consecutive_failures} 次，停止本目标后续批次"
                                    )
                                    break

            # 清理文件
            for batch_data in processed_batches:
                self._cleanup_files(batch_data["local_files"])

        target_count = len(context_target_sessions)
        acked = tuple(
            batch_index
            for batch_index, success_sessions in target_successes.items()
            if len(success_sessions) == target_count
        )
        deferred = tuple(sorted(deferred_batch_indexes))
        failed = tuple(
            batch_index
            for batch_index, success_sessions in target_successes.items()
            if len(success_sessions) != target_count
            and batch_index not in deferred_batch_indexes
        )
        return QQSendSummary(
            acked_batch_indexes=acked,
            failed_batch_indexes=failed,
            deferred_batch_indexes=deferred,
            error_types=target_failures,
        )

    def _is_plugin_data_file(self, path: str) -> bool:
        plugin_data_dir = getattr(self, "plugin_data_dir", None) or getattr(
            self.downloader, "plugin_data_dir", None
        )
        if not plugin_data_dir:
            return False
        plugin_entry_dir = os.path.abspath(plugin_data_dir)
        plugin_real_dir = os.path.realpath(plugin_data_dir)
        entry_path = os.path.abspath(path)
        real_path = os.path.realpath(path)
        try:
            return (
                os.path.commonpath([plugin_entry_dir, entry_path]) == plugin_entry_dir
                and os.path.commonpath([plugin_real_dir, real_path]) == plugin_real_dir
                and os.path.isfile(entry_path)
            )
        except ValueError:
            return False

    def _cleanup_files(self, files: list[str]):
        """清理临时下载的文件"""
        for f in files:
            if self._is_plugin_data_file(f):
                try:
                    os.remove(f)
                except OSError as e:
                    logger.warning(f"[QQSender] 清理临时文件失败: {f} ({e})")
