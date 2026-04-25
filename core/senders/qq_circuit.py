"""QQ 发送目标熔断状态辅助函数。

这里维护的是“纯状态变换”逻辑：判断目标是否仍处于熔断冷却期、记录失败、记录成功后清除状态。
拆出后可以避免 `QQSender` 和分发器同时关心底层熔断字段细节。
"""

CircuitState = dict[str, dict[str, float | int]]


def target_is_open(
    circuit_state: CircuitState, target_session: str, now_ts: float
) -> bool:
    """判断目标是否仍处于熔断开启状态，并顺手清理已过期项。"""
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
    """记录目标失败次数，并在达到阈值后开启熔断冷却。"""
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
    """目标发送成功后清除其熔断状态。"""
    circuit_state.pop(target_session, None)
