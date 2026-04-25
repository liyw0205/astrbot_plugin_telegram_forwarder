"""QQ 目标解析与发送异常分类辅助函数。

该模块只保留无状态的纯函数，避免把目标解析与异常归类逻辑散落在发送主流程里。
这样做的目的是让 `QQSender` 只负责编排发送步骤，而把可独立测试的细节下沉到这里。
"""

from collections.abc import Iterable

from astrbot.api import logger


def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    """去重并保持元素首次出现顺序。"""
    seen = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def split_qq_targets(targets: list) -> tuple[list[str], list[str]]:
    """把目标拆分为完整会话名和纯数字群号。"""
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
    """从会话目标字符串中提取去重后的平台 ID。"""
    platform_ids: list[str] = []
    for session in session_targets:
        if ":" not in session:
            continue
        platform_ids.append(session.split(":", 1)[0])
    return dedupe_keep_order(platform_ids)


def classify_send_error(error: Exception) -> str:
    """把已知发送异常归类为稳定的错误标签。"""
    message = str(error)
    if "WebSocket API call timeout" in message:
        return "timeout"
    if "retcode=1200" in message:
        return "retcode_1200"
    if "wrong session ID" in message:
        return "wrong_session_id"
    return "send_failed"
