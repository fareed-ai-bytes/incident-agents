import pytest

from incident_agent.errors import PermanentToolError, TransientToolError
from incident_agent.raw_loop.retry import RetryPolicy, call_with_retry


class Flaky:
    def __init__(self, failures, error=TransientToolError):
        self.failures, self.error, self.calls = failures, error, 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error(f"fail {self.calls}")
        return "ok"


def test_transient_errors_retried_until_success():
    sleeps = []
    fn = Flaky(2)
    out = call_with_retry(fn, RetryPolicy(3, 0.5, 10), sleep=sleeps.append, jitter=lambda: 0.0)
    assert out.value == "ok" and out.attempts == 3
    assert sleeps == [0.5, 1.0]  # exponential backoff


def test_jitter_adds_up_to_one_backoff():
    sleeps = []
    call_with_retry(Flaky(1), RetryPolicy(3, 0.5, 10), sleep=sleeps.append, jitter=lambda: 0.5)
    assert sleeps == [0.75]


def test_backoff_is_capped():
    assert RetryPolicy(10, 1.0, 2.0).delay(6, 0.0) == 2.0


def test_transient_errors_give_up_after_three_attempts():
    fn = Flaky(99)
    with pytest.raises(TransientToolError):
        call_with_retry(fn, RetryPolicy(max_attempts=3), sleep=lambda s: None)
    assert fn.calls == 3


def test_permanent_error_attempted_exactly_once():
    fn = Flaky(99, PermanentToolError)
    with pytest.raises(PermanentToolError):
        call_with_retry(fn, sleep=lambda s: None)
    assert fn.calls == 1


def test_unexpected_exceptions_are_not_retried():
    fn = Flaky(99, RuntimeError)
    with pytest.raises(RuntimeError):
        call_with_retry(fn, sleep=lambda s: None)
    assert fn.calls == 1
