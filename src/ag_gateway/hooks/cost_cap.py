from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ag_gateway.obs.logging import get_logger
from ag_gateway.obs.metrics import COST_CAP_REJECTIONS_TOTAL

log = get_logger(__name__)


@dataclass(frozen=True)
class CostCap:
    max_usd: float
    window_seconds: int = 3600


class CostCapExceeded(Exception):
    def __init__(self, prompt: str, used_usd: float, cap_usd: float) -> None:
        super().__init__(f"prompt={prompt} used=${used_usd:.4f} cap=${cap_usd:.4f}")
        self.prompt = prompt
        self.used_usd = used_usd
        self.cap_usd = cap_usd


class CostMeter:
    """In-process cost counters per (prompt, user_sub). Rolling window."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], list[tuple[float, float]]] = {}
        self._lock = threading.RLock()

    def record(self, prompt: str, user_sub: str, usd: float) -> None:
        with self._lock:
            self._entries.setdefault((prompt, user_sub), []).append((time.time(), usd))

    def used(self, prompt: str, user_sub: str, window_seconds: int) -> float:
        now = time.time()
        with self._lock:
            entries = self._entries.get((prompt, user_sub), [])
            entries = [(t, u) for (t, u) in entries if now - t <= window_seconds]
            self._entries[(prompt, user_sub)] = entries
            return sum(u for _, u in entries)

    def check(self, prompt: str, user_sub: str, cap: CostCap) -> None:
        used = self.used(prompt, user_sub, cap.window_seconds)
        if used >= cap.max_usd:
            COST_CAP_REJECTIONS_TOTAL.labels(prompt=prompt).inc()
            raise CostCapExceeded(prompt, used, cap.max_usd)
