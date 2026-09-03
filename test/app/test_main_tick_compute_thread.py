import threading

from app import main as app_main


class DummyEngine:
    """틱 연산 루프 호출 여부를 확인하는 테스트용 엔진."""

    def __init__(self, stop_event: threading.Event) -> None:
        self.calls = 0
        self._stop_event = stop_event

    def process_tick_compute_queue(self, shard_id: int = 0) -> None:
        self.calls += 1
        self._stop_event.set()


def test_tick_compute_thread_calls_engine():
    stop_event = threading.Event()
    engine = DummyEngine(stop_event)
    thread = threading.Thread(
        target=app_main._start_tick_compute,
        args=(engine, stop_event, 0.001, 0),
        daemon=True,
    )

    thread.start()

    assert stop_event.wait(1.0)
    assert engine.calls >= 1
