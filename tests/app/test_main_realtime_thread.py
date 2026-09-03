import threading

from app import main as app_main


class DummyEngine:
    """실시간 큐 처리 호출 여부를 확인하는 더미 엔진."""

    def __init__(self, stop_event: threading.Event) -> None:
        self.calls = 0
        self._stop_event = stop_event

    def process_real_data_queue(self) -> None:
        self.calls += 1
        self._stop_event.set()


def test_realtime_thread_calls_engine():
    stop_event = threading.Event()
    engine = DummyEngine(stop_event)
    thread = threading.Thread(
        target=app_main._start_realtime,
        args=(engine, stop_event, 0.001),
        daemon=True,
    )

    thread.start()

    assert stop_event.wait(1.0)
    assert engine.calls >= 1
