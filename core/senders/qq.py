"""QQ sender facade that coordinates runtime, batch building, and dispatch."""

import asyncio
import os
from collections.abc import Iterable
from dataclasses import dataclass, field

from telethon.tl.types import Message

from astrbot.api import AstrBotConfig, logger, star
from astrbot.api.message_components import Plain

try:
    from astrbot.core.utils.path_util import path_Mapping
except ImportError:
    path_Mapping = None

from ..downloader import MediaDownloader
from .qq_batch_builder import (
    ProcessedBatch,
    ProcessedBatchData,
    build_processed_batches,
)
from .qq_circuit import record_target_failure, record_target_success, target_is_open
from .qq_dispatcher import dispatch_processed_batches_to_targets, send_processed_batch
from .qq_media import (
    File,
    Image,
    Record,
    Video,
    batch_contains_audio,
    dispatch_media_file,
    map_path_with_config,
    should_merge_batch_nodes,
)
from .qq_reply_preview import (
    build_reply_preview,
    get_sender_display_name,
    prefetch_reply_previews,
    reply_media_label,
)
from .qq_runtime import get_platform_bot, get_platform_instances, select_qq_platform
from .qq_send_prep import (
    flatten_batches,
    normalize_qq_targets,
    positive_int,
    resolve_qq_targets,
    resolve_send_limits,
    resolve_text_processing_options,
)
from .qq_send_summary import (
    build_send_summary,
    collect_processed_batch_local_files,
)
from .qq_targets import (
    classify_send_error,
    dedupe_keep_order,
    session_platform_ids,
    split_qq_targets,
)

_ = Plain, ProcessedBatch, File, Image, Record, Video


@dataclass(frozen=True)
class QQSendSummary:
    """Batch-level QQ forwarding outcome exposed to forwarder callers."""

    acked_batch_indexes: tuple[int, ...] = ()
    failed_batch_indexes: tuple[int, ...] = ()
    deferred_batch_indexes: tuple[int, ...] = ()
    error_types: dict[int, str] = field(default_factory=dict)


class QQSender:
    """Facade sender that preserves public QQ sending behavior."""

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
        return map_path_with_config(
            fpath=fpath,
            context=self.context,
            path_mapping=path_Mapping,
        )

    def _dispatch_media_file(self, fpath: str, audio_mode: str = "record"):
        return dispatch_media_file(
            fpath,
            map_path=self._map_path,
            audio_mode=audio_mode,
        )

    @staticmethod
    def _get_sender_display_name(msg: Message) -> str:
        return get_sender_display_name(msg)

    @staticmethod
    def _reply_media_label(msg: Message) -> str:
        return reply_media_label(msg)

    def _build_reply_preview(
        self, reply_msg: Message, strip_links: bool = False
    ) -> str:
        return build_reply_preview(reply_msg, strip_links=strip_links)

    async def _prefetch_reply_previews(
        self, msgs: list[Message], src_channel: str, strip_links: bool = False
    ) -> dict[int, str]:
        return await prefetch_reply_previews(
            msgs=msgs,
            src_channel=src_channel,
            client=getattr(self.downloader, "client", None),
            strip_links=strip_links,
        )

    @staticmethod
    def _batch_contains_audio(nodes_data: list[list[object]]) -> bool:
        return batch_contains_audio(nodes_data)

    @staticmethod
    def _should_merge_batch_nodes(batch_data: ProcessedBatchData) -> bool:
        return should_merge_batch_nodes(batch_data)

    async def _send_processed_batch(
        self,
        batch_data: ProcessedBatchData,
        unified_msg_origin: str,
        self_id: int,
        node_name: str,
        target_session: str,
    ) -> None:
        await send_processed_batch(
            batch_data=batch_data,
            unified_msg_origin=unified_msg_origin,
            self_id=self_id,
            node_name=node_name,
            target_session=target_session,
            context=self.context,
            map_path=self._map_path,
            should_merge=self._should_merge_batch_nodes,
        )

    async def initialize_runtime(self):
        """Best-effort bootstrap for platform_id/bot before first forward."""
        await self._bootstrap_qq_runtime()
        if not self.platform_id:
            logger.warning(
                "[QQSender] 初始化阶段未捕获到 QQ 平台实例，后续若使用纯数字目标将无法自动拼接会话名。"
            )

    def _get_platform_instances(self) -> list:
        return get_platform_instances(self.context)

    @staticmethod
    def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
        return dedupe_keep_order(items)

    @staticmethod
    def _split_qq_targets(targets: list) -> tuple[list[str], list[str]]:
        """Split config targets into full sessions and numeric group IDs."""
        return split_qq_targets(targets)

    @staticmethod
    def _session_platform_ids(session_targets: list[str]) -> list[str]:
        return session_platform_ids(session_targets)

    @staticmethod
    def _classify_send_error(error: Exception) -> str:
        return classify_send_error(error)

    def _target_is_open(self, target_session: str, now_ts: float) -> bool:
        return target_is_open(self._target_circuit, target_session, now_ts)

    def _record_target_failure(
        self,
        target_session: str,
        *,
        threshold: int,
        cooldown_sec: int,
        now_ts: float,
    ) -> None:
        record_target_failure(
            self._target_circuit,
            target_session,
            threshold=threshold,
            cooldown_sec=cooldown_sec,
            now_ts=now_ts,
        )

    def _record_target_success(self, target_session: str) -> None:
        record_target_success(self._target_circuit, target_session)

    async def _bootstrap_qq_runtime(
        self, preferred_platform_ids: list[str] | None = None
    ):
        """Try to fetch platform_id and bot from context.platform_manager."""
        if self.platform_id and self.bot:
            return

        platforms = self._get_platform_instances()
        if not platforms:
            return

        selected = select_qq_platform(
            platforms,
            preferred_platform_ids,
            self.platform_id,
        )
        if not selected:
            return

        platform, pid, pname_raw = selected
        self.platform_id = pid
        logger.debug(
            f"[QQSender] 捕获到 QQ 平台: platform_id={pid}, platform_name={pname_raw or 'unknown'}"
        )

        try:
            self.bot = get_platform_bot(platform)
        except Exception as e:
            logger.debug(f"[QQSender] Bootstrap bot from platform failed: {e}")

        if self.bot:
            await self._ensure_node_name(self.bot, cache_fallback=False)

    def _resolve_text_processing_options(
        self,
        effective_cfg: dict[str, object],
        involved_channels: list[str] | None,
    ) -> tuple[bool, bool]:
        return resolve_text_processing_options(
            self.config,
            effective_cfg,
            involved_channels,
        )

    def _resolve_qq_targets(self, effective_cfg: dict[str, object]) -> object:
        return resolve_qq_targets(self.config, effective_cfg)

    @staticmethod
    def _normalize_qq_targets(qq_targets: object) -> list | None:
        return normalize_qq_targets(qq_targets)

    def _resolve_context_target_sessions(self, qq_targets: list) -> list[str]:
        session_targets_cfg, numeric_group_ids = self._split_qq_targets(qq_targets)
        context_target_sessions = list(session_targets_cfg)
        if numeric_group_ids:
            if self.platform_id:
                context_target_sessions.extend(
                    [
                        f"{self.platform_id}:GroupMessage:{gid}"
                        for gid in numeric_group_ids
                    ]
                )
            else:
                logger.warning(
                    "[QQSender] Localhost mode cannot resolve platform_id for numeric QQ target. "
                    "Use full session name (platform:MessageType:target_id) or ensure platform is loaded."
                )
        return self._dedupe_keep_order(context_target_sessions)

    @staticmethod
    def _positive_int(value: object, default: int) -> int:
        return positive_int(value, default)

    def _resolve_send_limits(
        self, forward_cfg: dict[str, object]
    ) -> tuple[int, int, int]:
        return resolve_send_limits(forward_cfg)

    @staticmethod
    def _flatten_batches(batches: list[list[Message]]) -> list[list[Message]]:
        return flatten_batches(batches)

    async def _resolve_bot_send_identity(self) -> tuple[int, str]:
        bot = self.bot
        if not bot and self.platform_id:
            try:
                platform = self.context.get_platform_inst(self.platform_id)
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
            await self._ensure_node_name(bot, cache_fallback=True) if bot else "AstrBot"
        )
        if bot:
            try:
                info = await bot.get_login_info()
                self_id = info.get("user_id", 0)
            except Exception as e:
                logger.error(f"[QQSender] 获取 bot 详细信息失败: {e}")
        return self_id, node_name

    def _build_send_summary(
        self,
        *,
        context_target_sessions: list[str],
        target_successes: dict[int, set[str]],
        target_failures: dict[int, str],
        deferred_batch_indexes: set[int],
    ) -> QQSendSummary:
        return build_send_summary(
            QQSendSummary,
            context_target_sessions=context_target_sessions,
            target_successes=target_successes,
            target_failures=target_failures,
            deferred_batch_indexes=deferred_batch_indexes,
        )

    def _cleanup_processed_batches(
        self, processed_batches: list[ProcessedBatchData]
    ) -> None:
        local_files = collect_processed_batch_local_files(processed_batches)
        self._cleanup_files(local_files)

    async def send(
        self,
        batches: list[list[Message]],
        src_channel: str,
        display_name: str | None = None,
        effective_cfg: dict[str, object] | None = None,
        involved_channels: list[str] | None = None,
    ):
        """
        转发消息到 QQ 群
        """
        if effective_cfg is None:
            effective_cfg = {}

        strip_links, exclude_text_on_media = self._resolve_text_processing_options(
            effective_cfg, involved_channels
        )
        qq_targets = self._resolve_qq_targets(effective_cfg)

        if not qq_targets or not batches:
            return QQSendSummary()

        qq_targets = self._normalize_qq_targets(qq_targets)
        if qq_targets is None:
            return QQSendSummary()

        session_targets_cfg, numeric_group_ids = self._split_qq_targets(qq_targets)
        preferred_platform_ids = self._session_platform_ids(session_targets_cfg)
        if numeric_group_ids or session_targets_cfg:
            await self._bootstrap_qq_runtime(
                preferred_platform_ids=preferred_platform_ids
            )

        context_target_sessions = self._resolve_context_target_sessions(qq_targets)

        if not context_target_sessions:
            return QQSendSummary()

        forward_cfg = self.config.get("forward_config", {})
        qq_merge_threshold = forward_cfg.get("qq_merge_threshold", 0)
        (
            fail_fast_limit,
            target_circuit_fail_threshold,
            target_circuit_cooldown_sec,
        ) = self._resolve_send_limits(forward_cfg)

        real_batches = self._flatten_batches(batches)

        if not real_batches:
            logger.debug("[QQSender] 展平后无有效批次，跳过发送")
            return QQSendSummary()

        logger.debug(
            f"[QQSender] 接收到 {len(batches)} 批次，展平后 {len(real_batches)} 个逻辑批次"
        )

        self_id, node_name = await self._resolve_bot_send_identity()

        is_mixed_big_merge = bool(involved_channels and len(involved_channels) > 1)

        build_result = await build_processed_batches(
            sender=self,
            real_batches=real_batches,
            src_channel=src_channel,
            display_name=display_name,
            involved_channels=involved_channels,
            strip_links=strip_links,
            exclude_text_on_media=exclude_text_on_media,
        )
        processed_batches = build_result.processed_batches
        target_failures = build_result.target_failures
        target_successes = {
            batch_index: set() for batch_index in range(len(real_batches))
        }
        deferred_batch_indexes: set[int] = set()

        use_big_merge = (qq_merge_threshold > 1) and (
            len(processed_batches) >= qq_merge_threshold
        )
        if use_big_merge and not is_mixed_big_merge:
            logger.info(
                f"[QQSender] 本次 {len(processed_batches)} 个逻辑单元 >= 阈值 {qq_merge_threshold}，转为整组合并转发"
            )

        dispatch_result = await dispatch_processed_batches_to_targets(
            context_target_sessions=context_target_sessions,
            real_batches=real_batches,
            processed_batches=processed_batches,
            target_successes=target_successes,
            target_failures=target_failures,
            deferred_batch_indexes=deferred_batch_indexes,
            use_big_merge=use_big_merge,
            is_mixed_big_merge=is_mixed_big_merge,
            forward_cfg=forward_cfg,
            self_id=self_id,
            node_name=node_name,
            get_lock=self._get_lock,
            target_is_open=self._target_is_open,
            record_target_success=self._record_target_success,
            record_target_failure=self._record_target_failure,
            classify_send_error=self._classify_send_error,
            send_processed_batch_fn=self._send_processed_batch,
            send_message_fn=self.context.send_message,
            fail_fast_limit=fail_fast_limit,
            target_circuit_fail_threshold=target_circuit_fail_threshold,
            target_circuit_cooldown_sec=target_circuit_cooldown_sec,
        )
        target_successes = dispatch_result.target_successes
        target_failures = dispatch_result.target_failures
        deferred_batch_indexes = dispatch_result.deferred_batch_indexes

        self._cleanup_processed_batches(processed_batches)

        return self._build_send_summary(
            context_target_sessions=context_target_sessions,
            target_successes=target_successes,
            target_failures=target_failures,
            deferred_batch_indexes=deferred_batch_indexes,
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
