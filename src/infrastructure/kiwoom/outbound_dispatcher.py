from __future__ import annotations

import itertools
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(order=True)
class DispatchTask:
    """송신 큐에서 처리할 작업 단위."""

    priority: int
    sequence: int
    channel: str = field(compare=False)
    action: Callable[[], Any] = field(compare=False)
    done: threading.Event = field(compare=False, default_factory=threading.Event)
    result: Any = field(compare=False, default=None)
    error: Optional[BaseException] = field(compare=False, default=None)


class OutboundDispatcher:
    """모든 outbound 호출을 단일 큐에서 순서/제한 정책으로 관리한다."""

    def __init__(self, tr_limiter, order_limiter, global_limiter) -> None:
        """채널별/전체 레이트리미터를 받아 송신 워커를 시작한다."""
        self._tr_limiter = tr_limiter
        self._order_limiter = order_limiter
        self._global_limiter = global_limiter
        self._queue: queue.PriorityQueue[DispatchTask] = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._closed = False
        self._close_lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, channel: str, action: Callable[[], Any]) -> Any:
        """작업을 큐에 넣고 완료까지 대기한 뒤 결과를 반환한다."""
        task = self._build_task(channel, action)
        self._queue.put(task)
        task.done.wait()
        if task.error:
            raise task.error
        return task.result

    def submit_async(self, channel: str, action: Callable[[], Any]) -> None:
        """작업을 큐에 넣고 즉시 반환한다."""
        task = self._build_task(channel, action)
        self._queue.put(task)

    def close(self) -> None:
        """워커 종료 신호를 보내고 큐를 정리한다."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._queue.put(self._build_task("system", lambda: None, priority=99))
        self._worker.join(timeout=1.0)

    def _build_task(self, channel: str, action: Callable[[], Any], priority: Optional[int] = None) -> DispatchTask:
        """채널별 우선순위 정책을 적용해 작업 객체를 만든다."""
        if priority is None:
            priority = self._resolve_priority(channel)
        return DispatchTask(
            priority=priority,
            sequence=next(self._sequence),
            channel=channel,
            action=action,
        )

    @staticmethod
    def _resolve_priority(channel: str) -> int:
        """낮을수록 먼저 처리되는 우선순위를 반환한다."""
        if channel == "order":
            return 0
        if channel == "tr":
            return 1
        return 5

    def _run(self) -> None:
        """큐에서 작업을 꺼내 레이트리밋을 적용한 뒤 실행한다."""
        while True:
            try:
                task = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._closed:
                    return
                continue

            if self._closed and task.channel == "system":
                task.done.set()
                return

            try:
                self._global_limiter.acquire()
                if task.channel == "order":
                    self._order_limiter.acquire()
                elif task.channel == "tr":
                    self._tr_limiter.acquire()
                task.result = task.action()
            except BaseException as exc:  # noqa: BLE001
                task.error = exc
            finally:
                task.done.set()
