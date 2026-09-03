import time

from infrastructure.kiwoom.outbound_dispatcher import OutboundDispatcher


class SpyLimiter:
    """호출 횟수만 기록하는 레이트리미터 스파이."""

    def __init__(self) -> None:
        self.acquire_count = 0

    def acquire(self) -> None:
        self.acquire_count += 1

    def get_wait_ms_last_sec(self, window_sec: float = 1.0) -> float:
        return 0.0


def test_dispatcher_prioritizes_order_channel():
    tr_limiter = SpyLimiter()
    order_limiter = SpyLimiter()
    global_limiter = SpyLimiter()
    dispatcher = OutboundDispatcher(
        tr_limiter=tr_limiter,
        order_limiter=order_limiter,
        global_limiter=global_limiter,
    )
    completed = []

    try:
        dispatcher.submit_async("tr", lambda: completed.append("tr1"))
        dispatcher.submit_async("tr", lambda: completed.append("tr2"))
        dispatcher.submit_async("order", lambda: completed.append("order1"))

        deadline = time.time() + 1.0
        while len(completed) < 3 and time.time() < deadline:
            time.sleep(0.01)

        assert len(completed) == 3
        assert completed[0] == "order1"
        assert tr_limiter.acquire_count == 2
        assert order_limiter.acquire_count == 1
        assert global_limiter.acquire_count == 3
    finally:
        dispatcher.close()
