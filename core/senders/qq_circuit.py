"""Stateless target circuit helpers for QQ sending."""

CircuitState = dict[str, dict[str, float | int]]


def target_is_open(
    circuit_state: CircuitState, target_session: str, now_ts: float
) -> bool:
    """Return whether a target circuit is open, pruning expired entries."""
    circuit = circuit_state.get(target_session)
    if not circuit:
        return False

    open_until = float(circuit.get("open_until", 0.0))
    if open_until <= 0:
        return False

    if open_until <= now_ts:
        circuit_state.pop(target_session, None)
        return False

    return True


def record_target_failure(
    circuit_state: CircuitState,
    target_session: str,
    *,
    threshold: int,
    cooldown_sec: int,
    now_ts: float,
) -> None:
    """Record a target failure and open its circuit once threshold is reached."""
    circuit = circuit_state.get(target_session) or {
        "consecutive_failures": 0,
        "open_until": 0.0,
    }
    consecutive_failures = int(circuit.get("consecutive_failures", 0)) + 1
    open_until = 0.0
    if consecutive_failures >= threshold:
        open_until = now_ts + float(cooldown_sec)

    circuit_state[target_session] = {
        "consecutive_failures": consecutive_failures,
        "open_until": open_until,
    }


def record_target_success(circuit_state: CircuitState, target_session: str) -> None:
    """Clear target circuit state after a successful send."""
    circuit_state.pop(target_session, None)
