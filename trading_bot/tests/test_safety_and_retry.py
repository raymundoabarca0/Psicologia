import pytest

from bot.safety.kill_switch import HaltFile, KillSwitch
from bot.utils.retry import retry_call
from bot.utils.timeframes import timeframe_to_ms


def test_kill_switch(tmp_path):
    k = KillSwitch(tmp_path / "KILL")
    assert not k.is_triggered()
    (tmp_path / "KILL").touch()
    assert k.is_triggered()


def test_halt_file_keeps_original_reason(tmp_path):
    h = HaltFile(tmp_path / "HALTED")
    h.halt("drawdown 10%")
    h.halt("otro motivo")
    assert h.is_halted()
    assert h.reason().splitlines()[0].endswith("drawdown 10%")


def test_retry_backoff_then_success():
    delays, calls = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("boom")
        return "ok"

    assert retry_call(flaky, retries=4, base_delay=2, jitter=False,
                      retry_on=(ConnectionError,), sleep=delays.append) == "ok"
    assert delays == [2, 4]


def test_retry_gives_up():
    delays = []
    with pytest.raises(ConnectionError):
        retry_call(lambda: (_ for _ in ()).throw(ConnectionError()), retries=3,
                   base_delay=1, jitter=False, retry_on=(ConnectionError,), sleep=delays.append)
    assert delays == [1, 2, 4]


def test_non_retryable_errors_propagate_immediately():
    delays = []
    with pytest.raises(ValueError):
        retry_call(lambda: (_ for _ in ()).throw(ValueError("fondos insuficientes")),
                   retry_on=(ConnectionError,), sleep=delays.append)
    assert delays == []


def test_timeframes():
    assert timeframe_to_ms("4h") == 4 * 3600 * 1000
    with pytest.raises(ValueError):
        timeframe_to_ms("4x")
    with pytest.raises(ValueError):
        timeframe_to_ms("0h")
