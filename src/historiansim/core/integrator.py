"""Fixed-step integration.

RK4 rather than Euler. The stirred tank is not stiff, but the steam side added
in phase 2 has a time constant of tens of seconds against a 1 s step, and Euler
at that ratio accumulates enough amplitude error to shift a mass balance --
which is one of the things the validation battery checks.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

__all__ = ["rk4_step", "integrate_scan"]

Derivatives = Callable[[float, np.ndarray], np.ndarray]


def rk4_step(f: Derivatives, t: float, x: np.ndarray, dt: float) -> np.ndarray:
    """One classical Runge-Kutta 4 step of ``dx/dt = f(t, x)``."""
    k1 = f(t, x)
    k2 = f(t + 0.5 * dt, x + 0.5 * dt * k1)
    k3 = f(t + 0.5 * dt, x + 0.5 * dt * k2)
    k4 = f(t + dt, x + dt * k3)
    return x + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def integrate_scan(
    f: Derivatives, t: float, x: np.ndarray, dt_sim: float, n_sub: int
) -> np.ndarray:
    """Advance one controller scan, holding the manipulated variables constant.

    The zero-order hold is the point. Controllers execute on a scan and their
    output is frozen in between; integrating with a continuously varying MV
    would smooth away the sawtooth that real manipulated variables show.
    """
    for i in range(n_sub):
        x = rk4_step(f, t + i * dt_sim, x, dt_sim)
    return x
