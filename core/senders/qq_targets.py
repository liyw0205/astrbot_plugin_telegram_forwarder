"""Pure helper functions for QQ target parsing and send error classification."""

from collections.abc import Iterable

from astrbot.api import logger


def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    """Return unique strings while preserving first-seen order."""
    seen = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def split_qq_targets(targets: list) -> tuple[list[str], list[str]]:
    """Split targets into session targets and numeric group IDs."""
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


def session_platform_ids(session_targets: list[str]) -> list[str]:
    """Extract unique platform IDs from session target strings."""
    platform_ids: list[str] = []
    for session in session_targets:
        if ":" not in session:
            continue
        platform_ids.append(session.split(":", 1)[0])
    return dedupe_keep_order(platform_ids)


def classify_send_error(error: Exception) -> str:
    """Classify known send failures into stable error tags."""
    message = str(error)
    if "WebSocket API call timeout" in message:
        return "timeout"
    if "retcode=1200" in message:
        return "retcode_1200"
    if "wrong session ID" in message:
        return "wrong_session_id"
    return "send_failed"
