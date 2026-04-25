"""Stateless preparation helpers for QQSender send-time config resolution."""

from collections.abc import Mapping, Sequence
from typing import TypeAlias, TypeGuard, cast

Batch: TypeAlias = list[object]
NestedBatches: TypeAlias = list[Batch]
FlattenableBatches: TypeAlias = Sequence[Batch | NestedBatches]


def _as_str_object_mapping(value: object) -> Mapping[str, object]:
    """Return a mapping view when the value is dict-like, else an empty mapping."""
    if isinstance(value, Mapping):
        return value
    return {}


def _is_nested_batches(item: Batch | NestedBatches) -> TypeGuard[NestedBatches]:
    """Detect one-level nested batch groups (e.g. ``[[msg1], [msg2]]``)."""
    return bool(item) and all(isinstance(sub, list) for sub in item)


def resolve_text_processing_options(
    config: Mapping[str, object],
    effective_cfg: Mapping[str, object],
    involved_channels: list[str] | None,
) -> tuple[bool, bool]:
    """Resolve strip-links and media-text options for the current send.

    Args:
        config: Full plugin config containing optional ``forward_config`` defaults.
        effective_cfg: Effective per-send/per-channel config.
        involved_channels: Channels included in the current merge operation.

    Returns:
        A tuple ``(strip_links, exclude_text_on_media)``.
    """
    if involved_channels and len(involved_channels) > 1:
        global_cfg = _as_str_object_mapping(config.get("forward_config"))
        strip_links = global_cfg.get("strip_markdown_links", False)
        exclude_text_on_media = global_cfg.get("exclude_text_on_media", False)
    else:
        exclude_text_on_media = effective_cfg.get("exclude_text_on_media", False)
        strip_links = effective_cfg.get("strip_markdown_links", False)
    return bool(strip_links), bool(exclude_text_on_media)


def resolve_qq_targets(
    config: Mapping[str, object], effective_cfg: Mapping[str, object]
) -> object:
    """Resolve QQ targets, preferring channel-specific targets over global config.

    Args:
        config: Full plugin config.
        effective_cfg: Effective per-send/per-channel config.

    Returns:
        Target definition object from config.
    """
    channel_specific_targets = effective_cfg.get("effective_target_qq_sessions", [])
    if channel_specific_targets:
        return channel_specific_targets
    return config.get("target_qq_session", [])


def normalize_qq_targets(qq_targets: object) -> list | None:
    """Normalize QQ targets into a list or return ``None`` for unsupported types.

    Args:
        qq_targets: Input target configuration.

    Returns:
        A list of targets, or ``None`` if type is unsupported.
    """
    if isinstance(qq_targets, int):
        return [qq_targets]
    if isinstance(qq_targets, list):
        return qq_targets
    return None


def positive_int(value: object, default: int) -> int:
    """Convert value to an integer and clamp to minimum 1.

    Args:
        value: Candidate numeric value.
        default: Fallback value when conversion fails.

    Returns:
        A positive integer (>= 1).
    """
    resolved = default

    if isinstance(value, bool):
        resolved = int(value)
    elif isinstance(value, int):
        resolved = value
    elif isinstance(value, float):
        resolved = int(value)
    elif isinstance(value, str):
        try:
            resolved = int(value.strip())
        except ValueError:
            resolved = default

    if resolved < 1:
        return 1
    return resolved


def resolve_send_limits(forward_cfg: Mapping[str, object]) -> tuple[int, int, int]:
    """Resolve send-loop fail-fast and circuit-breaker numeric limits.

    Args:
        forward_cfg: Effective ``forward_config`` dictionary.

    Returns:
        A tuple ``(fail_fast_limit, circuit_fail_threshold, circuit_cooldown_sec)``.
    """
    fail_fast_limit = positive_int(
        forward_cfg.get("qq_target_fail_fast_consecutive_failures", 3), 3
    )
    target_circuit_fail_threshold = positive_int(
        forward_cfg.get("target_circuit_fail_threshold", 3), 3
    )
    target_circuit_cooldown_sec = positive_int(
        forward_cfg.get("target_circuit_cooldown_sec", 300), 300
    )
    return (
        fail_fast_limit,
        target_circuit_fail_threshold,
        target_circuit_cooldown_sec,
    )


def flatten_batches(batches: FlattenableBatches) -> list[Batch]:
    """Flatten one-level nested batch groups into logical batches.

    Args:
        batches: Input batch list where an item may itself be a list of batches.

    Returns:
        A flattened list of logical batches preserving order.
    """
    real_batches: list[Batch] = []
    for item in batches:
        if _is_nested_batches(item):
            real_batches.extend(item)
        else:
            real_batches.append(cast(Batch, item))
    return real_batches
