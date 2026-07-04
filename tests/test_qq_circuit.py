"""qq_circuit 目标熔断状态机单元测试。

该模块为纯函数状态机，无外部依赖，直接通过 importlib 隔离加载即可。
"""

import importlib.util
from pathlib import Path


def load_circuit_module():
    path = Path(__file__).resolve().parents[1] / "core" / "senders" / "qq_circuit.py"
    spec = importlib.util.spec_from_file_location("test_qq_circuit_module", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestTargetIsOpen:
    def test_unknown_target_not_open(self):
        m = load_circuit_module()
        assert m.target_is_open({}, "g1", now_ts=100.0) is False

    def test_zero_open_until_not_open(self):
        m = load_circuit_module()
        state = {"g1": {"consecutive_failures": 2, "open_until": 0.0}}
        assert m.target_is_open(state, "g1", now_ts=100.0) is False

    def test_open_until_in_future_is_open(self):
        m = load_circuit_module()
        state = {"g1": {"consecutive_failures": 3, "open_until": 200.0}}
        assert m.target_is_open(state, "g1", now_ts=100.0) is True

    def test_open_until_expired_clears_state(self):
        m = load_circuit_module()
        state = {"g1": {"consecutive_failures": 3, "open_until": 50.0}}
        # 过期后判定为未熔断，且顺手清理过期项
        assert m.target_is_open(state, "g1", now_ts=100.0) is False
        assert "g1" not in state


class TestRecordTargetFailure:
    def test_first_failure_below_threshold_no_open(self):
        m = load_circuit_module()
        state = {}
        m.record_target_failure(
            state, "g1", threshold=3, cooldown_sec=300, now_ts=100.0
        )
        assert state["g1"]["consecutive_failures"] == 1
        assert state["g1"]["open_until"] == 0.0

    def test_opens_circuit_when_reaching_threshold(self):
        m = load_circuit_module()
        state = {}
        for ts in (100.0, 110.0, 120.0):
            m.record_target_failure(
                state, "g1", threshold=3, cooldown_sec=300, now_ts=ts
            )
        assert state["g1"]["consecutive_failures"] == 3
        # 第三次失败 now_ts=120.0，达阈值 → 开启熔断 300s
        assert state["g1"]["open_until"] == 120.0 + 300.0

    def test_existing_failures_increment_and_open(self):
        m = load_circuit_module()
        state = {"g1": {"consecutive_failures": 5, "open_until": 0.0}}
        # 已有 5 次失败，再 +1 = 6 ≥ 阈值 3 → 开启熔断
        m.record_target_failure(
            state, "g1", threshold=3, cooldown_sec=300, now_ts=100.0
        )
        assert state["g1"]["consecutive_failures"] == 6
        assert state["g1"]["open_until"] == 100.0 + 300.0

    def test_below_threshold_keeps_open_until_zero(self):
        m = load_circuit_module()
        state = {}
        m.record_target_failure(
            state, "g1", threshold=5, cooldown_sec=300, now_ts=100.0
        )
        # 1 < 5，不开启熔断
        assert state["g1"]["consecutive_failures"] == 1
        assert state["g1"]["open_until"] == 0.0


class TestRecordTargetSuccess:
    def test_success_clears_state(self):
        m = load_circuit_module()
        state = {"g1": {"consecutive_failures": 3, "open_until": 999.0}}
        m.record_target_success(state, "g1")
        assert "g1" not in state

    def test_success_unknown_target_noop(self):
        m = load_circuit_module()
        state = {}
        m.record_target_success(state, "g1")
        assert state == {}


class TestIntegrationFlow:
    def test_fail_threshold_then_cooldown_then_success_resets(self):
        m = load_circuit_module()
        state = {}
        # 连续失败 3 次达到阈值
        for _ in range(3):
            m.record_target_failure(
                state, "g1", threshold=3, cooldown_sec=300, now_ts=100.0
            )
        assert m.target_is_open(state, "g1", now_ts=100.0) is True
        # 成功一次立即清空
        m.record_target_success(state, "g1")
        assert m.target_is_open(state, "g1", now_ts=100.0) is False
        assert "g1" not in state
