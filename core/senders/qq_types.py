"""QQ sender shared type definitions."""

from typing import Literal, Protocol

from astrbot.api.event import MessageChain

SendKind = Literal[
    "big_merge",
    "album_merge",
    "plain",
    "audio_record",
    "audio_file",
    "special_media",
    "fallback_link",
    "fallback_zip",
]


class SendMessageFn(Protocol):
    """Unified QQ send wrapper callable."""

    async def __call__(
        self,
        unified_msg_origin: str,
        message_chain: MessageChain,
        *,
        send_kind: SendKind,
    ) -> None: ...
