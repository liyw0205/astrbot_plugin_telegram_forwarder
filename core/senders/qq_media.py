"""Media and path helpers for QQ sender dispatch."""

import os
from collections.abc import Callable
from typing import Any

from astrbot.api.message_components import File, Image, Plain, Record, Video

from .qq_batch_builder import ProcessedBatchData

_ = Plain


def map_path_with_config(
    *, fpath: str, context: Any, path_mapping: Callable | None
) -> str:
    """Map a local file path through AstrBot path mapping config when available."""
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
    """Convert a local media path into AstrBot QQ message components."""
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
    """Return whether any node contains a Record component."""
    return any(
        isinstance(component, Record) for node in nodes_data for component in node
    )


def should_merge_batch_nodes(batch_data: ProcessedBatchData) -> bool:
    """Return whether a batch can be sent as merged forward nodes."""
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
