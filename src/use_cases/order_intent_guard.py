from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, Optional, Tuple


class OrderIntentGuard:
    """종목/방향별 미체결 주문 의도를 중복 전송하지 않도록 보호한다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Dict[Tuple[str, str], datetime] = {}

    @staticmethod
    def _key(code: str, side: str) -> Tuple[str, str]:
        return str(code or "").strip(), str(side or "").upper().strip()

    def claim(self, code: str, side: str, now: datetime) -> bool:
        key = self._key(code, side)
        if not key[0] or key[1] not in ("BUY", "SELL"):
            return False
        with self._lock:
            if key in self._pending:
                return False
            self._pending[key] = now
            return True

    def release(self, code: str, side: str) -> None:
        with self._lock:
            self._pending.pop(self._key(code, side), None)

    def is_pending(self, code: str, side: str) -> bool:
        with self._lock:
            return self._key(code, side) in self._pending

    def pending_at(self, code: str, side: str) -> Optional[datetime]:
        with self._lock:
            return self._pending.get(self._key(code, side))

    def clear_code(self, code: str) -> None:
        code = str(code or "").strip()
        if not code:
            return
        with self._lock:
            for key in [key for key in self._pending if key[0] == code]:
                self._pending.pop(key, None)
