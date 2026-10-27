"""Transport lag.

Change a feed rate and the downstream analyzer moves eight minutes later.
Synthetic data almost always correlates instantaneously, and a cross-correlation
that peaks at zero lag is one of the fastest ways to spot fabricated data.

Two places this gets applied, and the distinction matters:

* **Inside the loop**, when a controller reads a delayed measurement. The delay
  is then part of the feedback dynamics and changes stability, so it cannot be
  applied afterwards.
* **After the loop**, as a pure array shift, when nothing controls on the
  delayed signal. A pure delay commutes with everything downstream of it, so
  shifting the finished array is exactly equivalent and much cheaper.

Use :class:`DeadTime` for the first case and :func:`shift_series` for the second.
"""

from __future__ import annotations

from collections import deque

import numpy as np

__all__ = ["DeadTime", "shift_series"]


class DeadTime:
    """Fixed transport delay on a scalar signal, for in-loop use."""

    def __init__(self, delay_s: float, dt_scan: float, init: float = 0.0):
        n = max(1, int(round(delay_s / dt_scan)))
        self.n = n
        self.delay_s = n * dt_scan
        self.buf: deque[float] = deque([float(init)] * n, maxlen=n)

    def __call__(self, value: float) -> float:
        oldest = self.buf[0]
        self.buf.append(float(value))
        return oldest

    def __repr__(self) -> str:
        return f"DeadTime({self.delay_s:g}s, n={self.n})"


def shift_series(values: np.ndarray, delay_s: float, dt: float) -> np.ndarray:
    """Delay a finished series by ``delay_s``, holding the first value.

    Equivalent to running the signal through :class:`DeadTime`, valid whenever
    no controller acts on the delayed signal.
    """
    n = int(round(delay_s / dt))
    if n <= 0:
        return values.copy()
    out = np.empty_like(values)
    out[:n] = values[0]
    out[n:] = values[:-n]
    return out
