"""Stateless helpers for QQ send summary construction and cleanup preparation."""

from collections.abc import Iterable
from typing import TypeVar

from .qq_batch_builder import ProcessedBatchData

QQSendSummaryT = TypeVar("QQSendSummaryT")


def build_send_summary(
    summary_cls: type[QQSendSummaryT],
    *,
    context_target_sessions: list[str],
    target_successes: dict[int, set[str]],
    target_failures: dict[int, str],
    deferred_batch_indexes: set[int],
) -> QQSendSummaryT:
    """Build a ``QQSendSummary``-compatible instance from per-batch outcomes.

    Args:
        summary_cls: Summary dataclass type to instantiate.
        context_target_sessions: All target sessions participating in this send.
        target_successes: Successful target sessions keyed by batch index.
        target_failures: Classified failure reason keyed by batch index.
        deferred_batch_indexes: Batch indexes deferred by circuit breaker logic.

    Returns:
        A summary instance containing acked, failed, deferred indexes and error types.
    """

    target_count = len(context_target_sessions)
    acked = tuple(
        batch_index
        for batch_index, success_sessions in target_successes.items()
        if len(success_sessions) == target_count
    )
    deferred = tuple(sorted(deferred_batch_indexes))
    failed = tuple(
        batch_index
        for batch_index, success_sessions in target_successes.items()
        if len(success_sessions) != target_count
        and batch_index not in deferred_batch_indexes
    )
    return summary_cls(
        acked_batch_indexes=acked,
        failed_batch_indexes=failed,
        deferred_batch_indexes=deferred,
        error_types=target_failures,
    )


def collect_processed_batch_local_files(
    processed_batches: Iterable[ProcessedBatchData],
) -> list[str]:
    """Collect all local media file paths from processed batch payloads.

    Args:
        processed_batches: Iterable of processed batch payload dictionaries.

    Returns:
        Flattened file path list in original batch order.
    """

    return [
        local_file
        for batch_data in processed_batches
        for local_file in batch_data["local_files"]
    ]
