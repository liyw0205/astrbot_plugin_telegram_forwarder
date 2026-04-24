"""QQ platform runtime helper utilities for platform and bot discovery."""

from typing import Any


def get_platform_instances(context: Any) -> list:
    """Get platform instances from context platform manager."""
    platform_manager = getattr(context, "platform_manager", None)
    if not platform_manager:
        return []

    if hasattr(platform_manager, "platform_insts"):
        insts = getattr(platform_manager, "platform_insts") or []
        return list(insts)

    if hasattr(platform_manager, "get_insts"):
        try:
            insts = platform_manager.get_insts()
            return list(insts or [])
        except Exception:
            return []

    return []


def select_qq_platform(
    platforms: list,
    preferred_platform_ids: list[str] | None,
    current_platform_id: str | None,
) -> tuple[object, str, str] | None:
    """Select a QQ platform instance using preference and heuristic rules."""
    candidates: list[tuple[object, str, str, str]] = []
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
        return None

    selected = None
    preferred = preferred_platform_ids or []
    if preferred:
        candidates_by_id = {item[1]: item for item in candidates}
        for preferred_id in preferred:
            matched = candidates_by_id.get(preferred_id)
            if matched:
                selected = matched
                break

    if selected is None and current_platform_id:
        for item in candidates:
            if item[1] == current_platform_id:
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
    return platform, pid, pname_raw


def get_platform_bot(platform: object) -> object | None:
    """Get bot/client instance from a platform object."""
    if hasattr(platform, "get_client"):
        return platform.get_client()
    if hasattr(platform, "bot"):
        return platform.bot
    return None
