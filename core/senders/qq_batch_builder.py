"""Batch preprocessing helpers for QQ sender dispatch."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypedDict

from astrbot.api import logger
from astrbot.api.message_components import File, Plain, Record, Video

from ...common.text_tools import clean_telegram_text, is_numeric_channel_id

if TYPE_CHECKING:
    from .qq import QQSender


class ProcessedBatchData(TypedDict):
    """Dispatch-ready processed batch data."""

    batch_index: int
    nodes_data: list[list[object]]
    local_files: list[str]
    contains_audio: bool


@dataclass(frozen=True)
class ProcessedBatch:
    """A Telegram message batch converted into QQ message component nodes."""

    batch_index: int
    nodes_data: list[list[object]]
    local_files: list[str]
    contains_audio: bool

    def as_batch_data(self) -> ProcessedBatchData:
        """Return the dict shape used by the existing QQSender dispatch code."""
        return {
            "batch_index": self.batch_index,
            "nodes_data": self.nodes_data,
            "local_files": self.local_files,
            "contains_audio": self.contains_audio,
        }


@dataclass(frozen=True)
class BuildBatchesResult:
    """Result of preparing Telegram batches for QQ dispatch."""

    processed_batches: list[ProcessedBatchData]
    target_failures: dict[int, str] = field(default_factory=dict)


async def build_processed_batches(
    *,
    sender: "QQSender",
    real_batches: list[list[object]],
    src_channel: str,
    display_name: str | None,
    involved_channels: list[str] | None,
    strip_links: bool,
    exclude_text_on_media: bool,
) -> BuildBatchesResult:
    """Prepare Telegram message batches into QQ dispatch-ready batch data."""
    if involved_channels and len(involved_channels) > 1:
        formatted = [
            ch if is_numeric_channel_id(ch) else f"@{ch.lstrip('@')}"
            for ch in sorted(involved_channels)
        ]
        if len(formatted) <= 4:
            channels_str = " ".join(formatted)
        else:
            channels_str = " ".join(formatted[:4]) + f" 等{len(formatted) - 4}个频道"
        header = f"From {channels_str}:"
        logger.debug(f"[QQSender] 混合大合并 From: {header}")
    else:
        header_name = display_name or src_channel
        if not header_name.startswith("@") and not is_numeric_channel_id(
            header_name.lstrip("@")
        ):
            header_name = f"@{header_name}"
        header = f"From {header_name}:"

    processed_batches = []
    target_failures: dict[int, str] = {}
    header_added = False

    for batch_index, msgs in enumerate(real_batches):
        all_local_files = []
        all_nodes_data = []
        try:
            reply_preview_cache = await sender._prefetch_reply_previews(
                msgs, src_channel, strip_links=strip_links
            )
            for i, msg in enumerate(msgs):
                current_node_components = []
                text_parts = []
                if msg.text:
                    cleaned = clean_telegram_text(msg.text, strip_links=strip_links)
                    if cleaned:
                        text_parts.append(cleaned)

                media_components = []
                has_any_attachment = False
                msg_max_size = getattr(msg, "_max_file_size", 0)
                files = await sender.downloader.download_media(
                    msg, max_size_mb=msg_max_size
                )
                for fpath in files:
                    all_local_files.append(fpath)
                    has_any_attachment = True
                    media_components.extend(sender._dispatch_media_file(fpath))

                should_exclude_text = exclude_text_on_media and has_any_attachment

                reply_header = getattr(msg, "reply_to", None)
                reply_id = getattr(reply_header, "reply_to_msg_id", None)
                reply_preview = reply_preview_cache.get(reply_id)
                if reply_preview and not should_exclude_text:
                    text_parts.insert(0, reply_preview)

                add_header_this_time = False
                if not should_exclude_text:
                    if involved_channels and len(involved_channels) > 1:
                        if not header_added and i == 0:
                            add_header_this_time = True
                            header_added = True
                    else:
                        if i == 0:
                            add_header_this_time = True

                if add_header_this_time:
                    if text_parts:
                        text_parts[0] = f"{header}\n​{text_parts[0]}"
                    else:
                        current_node_components.append(Plain(f"{header}\n​"))

                if not should_exclude_text:
                    for t in text_parts:
                        current_node_components.append(Plain(t + "\n"))

                _node_special_media = [
                    c for c in media_components if isinstance(c, (Video, Record, File))
                ]
                if not should_exclude_text and text_parts and _node_special_media:
                    if current_node_components:
                        all_nodes_data.append(current_node_components)
                    current_node_components = []

                current_node_components.extend(media_components)

                if current_node_components:
                    is_only_header = (
                        len(current_node_components) == 1
                        and isinstance(current_node_components[0], Plain)
                        and current_node_components[0].text.strip("​\n") in [header, ""]
                    )
                    if not is_only_header:
                        all_nodes_data.append(current_node_components)

            if all_nodes_data:
                processed_batches.append(
                    ProcessedBatch(
                        batch_index=batch_index,
                        nodes_data=all_nodes_data,
                        local_files=all_local_files,
                        contains_audio=sender._batch_contains_audio(all_nodes_data),
                    ).as_batch_data()
                )
            else:
                target_failures.setdefault(batch_index, "preprocess_empty")
        except Exception as e:
            logger.error(f"[QQSender] 预处理消息批次异常: {e}")
            target_failures.setdefault(batch_index, sender._classify_send_error(e))
            sender._cleanup_files(all_local_files)

    return BuildBatchesResult(
        processed_batches=processed_batches,
        target_failures=target_failures,
    )
