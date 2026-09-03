import datetime

from use_cases.cooldown import CooldownTracker


class FixedClock:
    """고정 시간을 제공하는 테스트용 시계."""

    def __init__(self, now: datetime.datetime):
        self._now = now

    def now(self) -> datetime.datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now = self._now + datetime.timedelta(seconds=seconds)


def test_cooldown_blocks_until_elapsed():
    """쿨다운 시간 동안 재진입을 막는다."""
    clock = FixedClock(datetime.datetime(2026, 2, 9, 0, 0, 0))
    cooldown = CooldownTracker(seconds=5, clock=clock)

    assert cooldown.allow("000001") is True
    cooldown.mark("000001")
    assert cooldown.allow("000001") is False

    clock.advance(5)
    assert cooldown.allow("000001") is True
