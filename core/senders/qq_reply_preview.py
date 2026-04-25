"""QQ 转发场景下的回复预览辅助函数。

用于把 Telegram 的回复上下文压缩成适合 QQ 展示的简短预览文本，
避免在发送主流程中混入过多“回复引用”相关的细节处理。
"""

from telethon.tl.types import Message

from astrbot.api import logger

from ...common.text_tools import clean_telegram_text, to_telethon_entity


def get_sender_display_name(msg: Message) -> str:
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


def reply_media_label(msg: Message) -> str:
    if getattr(msg, "photo", None):
        return "[图片]"
    if getattr(msg, "video", None):
        return "[视频]"
    if getattr(msg, "audio", None) or getattr(msg, "voice", None):
        return "[音频]"
    if getattr(msg, "file", None) or getattr(msg, "document", None):
        return "[文件]"
    return "[消息]"


def build_reply_preview(reply_msg: Message, strip_links: bool = False) -> str:
    sender_name = get_sender_display_name(reply_msg)
    if getattr(reply_msg, "text", None):
        preview = clean_telegram_text(reply_msg.text, strip_links=strip_links)
        preview = " ".join(part for part in preview.splitlines() if part).strip()
        if len(preview) > 100:
            preview = preview[:100].rstrip() + "..."
    else:
        preview = reply_media_label(reply_msg)
    if not preview:
        preview = reply_media_label(reply_msg)
    if sender_name:
        return f"↩ 回复 {sender_name}:\n{preview}"
    return f"↩ 回复:\n{preview}"


async def prefetch_reply_previews(
    *,
    msgs: list[Message],
    src_channel: str,
    client,
    strip_links: bool = False,
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
        preview_cache[reply_msg.id] = build_reply_preview(
            reply_msg, strip_links=strip_links
        )
    return preview_cache
