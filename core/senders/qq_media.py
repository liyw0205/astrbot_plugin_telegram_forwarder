"""QQ 发送所需的媒体与路径辅助函数。

负责两类事情：
1. 按运行环境把本地文件路径映射到 AstrBot / NapCat 实际可访问的路径。
2. 按文件后缀把媒体文件转换成对应的 QQ 消息组件。
"""

import os
from collections.abc import Callable
from typing import Any

from astrbot.api.message_components import File, Image, Plain, Record, Video

from .qq_batch_builder import ProcessedBatchData

_ = Plain


def map_path_with_config(
    *, fpath: str, context: Any, path_mapping: Callable | None
) -> str:
    """按 AstrBot 的路径映射配置转换本地文件路径。

    当 AstrBot 与 QQ 平台运行在不同宿主环境时，下载得到的本地路径未必能被目标平台直接访问。
    这里统一处理宿主机路径到容器路径的映射，避免具体发送逻辑分散关心环境差异。
    """
    try:
        if path_mapping is None:
            return fpath
        core_config = getattr(context, "_config", None)
        if core_config:
            mappings = core_config.get("platform_settings", {}).get("path_mapping", [])
            if mappings:
                return path_mapping(mappings, fpath)
    except Exception:
        pass
    return fpath


def dispatch_media_file(
    fpath: str,
    *,
    map_path: Callable[[str], str],
    audio_mode: str = "record",
) -> list[object]:
    """把本地媒体文件路径转换为 AstrBot QQ 消息组件。

    不同媒体类型在 QQ 端支持能力不同，因此这里按后缀做保守映射：
    图片优先转图片组件，音频按配置决定走语音还是文件，视频和普通文件则尽量保留可访问路径。
    """
    ext = os.path.splitext(fpath)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        return [Image.fromFileSystem(fpath)]
    if ext in (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"):
        if audio_mode == "file_only":
            mapped = map_path(fpath)
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
        mapped = map_path(fpath)
        if mapped != fpath:
            return [Video(file=f"file:///{mapped}")]
        return [Video.fromFileSystem(fpath)]
    mapped = map_path(fpath)
    return [
        File(
            file=mapped,
            url="",
            name=os.path.basename(fpath),
        )
    ]


def batch_contains_audio(nodes_data: list[list[object]]) -> bool:
    """判断批次节点中是否包含语音组件。"""
    return any(
        isinstance(component, Record) for node in nodes_data for component in node
    )


def should_merge_batch_nodes(batch_data: ProcessedBatchData) -> bool:
    """判断一个批次是否适合按合并转发节点发送。

    只有在节点数大于 1，且不包含音频 / 文件 / 视频等兼容性更敏感的媒体时，
    才适合走合并转发，以减少 QQ 侧发送失败或展示异常。
    """
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
