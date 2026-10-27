"""Colored noise and signal shaping.

**Never white noise.** Real process signals are correlated in time, and the
correlation time is a property of the measurement: a flow transmitter is noisy
and fast, a thermowell is smooth and slow because thermal mass low-passes it, a
level integrates and wanders. One noise model across all tags is the single
fastest way to fail an autocorrelation check.

Ornstein-Uhlenbeck is the workhorse -- exponentially correlated, stationary,
with a correlation time that maps directly onto instrument physics. Everything
here is generated with ``scipy.signal.lfilter`` rather than a Python loop,
because these run over millions of samples per tag.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

__all__ = ["ou_noise", "first_order_filter", "random_walk", "diurnal"]


def ou_noise(
    n: int,
    sigma: float,
    tau: float,
    dt: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Ornstein-Uhlenbeck noise: exponentially correlated, zero mean.

    Parameters
    ----------
    sigma:
        Stationary standard deviation.
    tau:
        Correlation time in seconds. As ``tau`` approaches zero this degenerates
        to white noise, which is why it must be set per instrument class rather
        than globally.

    The recursion ``x[i] = a*x[i-1] + s*e[i]`` is a one-pole IIR filter, so it
    runs in compiled code. The initial condition is chosen to make the very
    first sample stationary; starting at zero would leave a visible settling
    ramp at the head of every tag.
    """
    if n <= 0:
        return np.zeros(0)
    if sigma <= 0:
        return np.zeros(n)
    if tau <= 0:
        return rng.normal(0.0, sigma, n)

    a = np.exp(-dt / tau)
    innovation = sigma * np.sqrt(1.0 - a * a)
    noise = rng.normal(0.0, 1.0, n)

    # zi makes y[0] = innovation*e[0] + a*x_prev with x_prev ~ N(0, sigma),
    # giving var(y[0]) = sigma^2 exactly rather than sigma^2*(1-a^2).
    zi = np.array([a * rng.normal(0.0, sigma)])
    out, _ = lfilter([innovation], [1.0, -a], noise, zi=zi)
    return out


def first_order_filter(
    values: np.ndarray, tau: float, dt: float, init: float | None = None
) -> np.ndarray:
    """Single-pole low-pass. Models sensor lag -- a thermowell, an analyzer cell."""
    if tau <= 0:
        return values.copy()
    alpha = np.exp(-dt / tau)
    start = values[0] if init is None else init
    out, _ = lfilter([1.0 - alpha], [1.0, -alpha], values, zi=np.array([alpha * start]))
    return out


def random_walk(
    n: int, step_sigma: float, dt: float, rng: np.random.Generator
) -> np.ndarray:
    """Non-stationary drift. Levels and calibration offsets do this."""
    if n <= 0:
        return np.zeros(0)
    steps = rng.normal(0.0, step_sigma * np.sqrt(dt), n)
    return np.cumsum(steps)


def diurnal(
    hours: np.ndarray, amplitude: float, peak_hour: float = 15.0
) -> np.ndarray:
    """Daily cycle peaking at ``peak_hour`` local time.

    Ambient temperature peaks mid-afternoon, not at noon, because the ground
    keeps releasing heat after solar maximum. Getting the phase wrong is
    harmless numerically and obvious to anyone who has looked at real plant data.
    """
    return amplitude * np.cos(2.0 * np.pi * (hours - peak_hour) / 24.0)
