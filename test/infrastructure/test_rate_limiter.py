from infrastructure.kiwoom.rate_limiter import AsyncRateLimiter


class FakeMonotonic:
    """단조 증가 시간을 제어하는 테스트 도우미."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_limiter_limits_to_four_calls_per_second():
    fake = FakeMonotonic()
    limiter = AsyncRateLimiter(
        max_calls=4,
        period_sec=1.0,
        clock=fake.clock,
        sleep_fn=fake.sleep,
    )

    for _ in range(5):
        limiter.acquire()

    assert len(fake.sleeps) == 1
    assert fake.sleeps[0] == 1.0


def test_rate_limiter_allows_next_window_without_wait():
    fake = FakeMonotonic()
    limiter = AsyncRateLimiter(
        max_calls=4,
        period_sec=1.0,
        clock=fake.clock,
        sleep_fn=fake.sleep,
    )

    for _ in range(4):
        limiter.acquire()
    fake.now += 1.01
    limiter.acquire()

    assert fake.sleeps == []
