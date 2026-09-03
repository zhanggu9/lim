"""간단한 틱 큐 부하 테스트 스크립트

- 내부 엔진 큐 동작을 모사: put_nowait 시도, Full이면 get_nowait로 자리 비우고 다시 put 시도,
  그래도 안되면 드롭(폐기)로 간주.
- 생산자 속도, 소비자 워커 수/처리시간을 바꿔가며 드롭 수를 관찰할 수 있음.

사용법:
    python tools/tick_queue_load_test.py

중요: 이 스크립트는 실제 엔진을 쓰지 않고 큐 동작만 시뮬레이트합니다.
"""
from __future__ import annotations

import threading
import time
import queue
import random

QUEUE_SIZE = 1000
PRODUCER_RATE_PER_SEC = 5000  # 초당 생성 틱 수 (높게 하면 드롭 발생)
TEST_SECONDS = 10
CONSUMER_WORKERS = 8
CONSUMER_PROCESS_SEC = 0.0005  # 한 틱 처리에 걸리는 평균 시간

_tick_drop_count = 0
_lock = threading.Lock()


def producer(q: queue.Queue):
    global _tick_drop_count
    interval = 1.0 / PRODUCER_RATE_PER_SEC
    end = time.time() + TEST_SECONDS
    while time.time() < end:
        tick = object()
        try:
            q.put_nowait(tick)
        except queue.Full:
            # 시뮬레이트된 엔진 로직: 빈 자리 만들고 재시도
            try:
                q.get_nowait()
            except queue.Empty:
                with _lock:
                    _tick_drop_count += 1
                continue
            try:
                q.put_nowait(tick)
            except queue.Full:
                with _lock:
                    _tick_drop_count += 1
        time.sleep(interval)


def consumer_worker(q: queue.Queue, worker_id: int):
    while True:
        try:
            tick = q.get(timeout=1.0)
        except queue.Empty:
            # 생산이 끝나고 큐가 비면 종료
            return
        # 처리 시간 변동을 주어 현실성 부여
        proc = random.expovariate(1.0 / CONSUMER_PROCESS_SEC)
        time.sleep(proc)
        q.task_done()


def main():
    q: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
    producers = [threading.Thread(target=producer, args=(q,), daemon=True)]
    consumers = [threading.Thread(target=consumer_worker, args=(q, i), daemon=True) for i in range(CONSUMER_WORKERS)]

    for c in consumers:
        c.start()
    for p in producers:
        p.start()

    start = time.time()
    try:
        while time.time() - start < TEST_SECONDS:
            with _lock:
                drops = _tick_drop_count
            print(f"시간={time.time()-start:.1f}s 큐크기={q.qsize()} 드롭={drops}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass

    # 생산자 종료를 기다린 뒤 큐를 비울 때까지 기다림
    for p in producers:
        p.join(timeout=1.0)
    q.join()
    print("테스트 종료. 최종 드롭 수:", _tick_drop_count)


if __name__ == "__main__":
    main()
