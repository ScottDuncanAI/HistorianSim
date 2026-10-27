"""Sensor pathology: spikes, freezes, dropouts, drift, and correlated failures.

The realism that most synthetic data omits. In particular:

**Frozen values.** A stuck transmitter repeats its last reading for hours and
reports good quality the whole time. These are everywhere in real historians
and almost never in synthetic data. Nothing here flags them, because flagging
them would hand over the exact judgement an analyst has to make: is this tag
genuinely steady, or has it stopped updating?

**Correlated missingness.** Instruments do not fail independently. A DCS node
drops and forty tags go bad at the same instant, then come back together. An
analysis that assumes independent missingness gets the covariance wrong, and a
dataset with independent dropouts never exposes that.
"""

from __future__ import annotations

import numpy as np

from historiansim.measurement.instrument import Quality

__all__ = ["apply_spikes", "apply_freezes", "apply_drift", "node_dropouts"]


def apply_spikes(
    values: np.ndarray,
    span: tuple[float, float],
    per_day: float,
    dt: float,
    rng: np.random.Generator,
    magnitude: float = 0.15,
) -> np.ndarray:
    """Single-sample excursions from electrical noise or a loose connection.

    One sample wide, so any median filter removes them -- which is the point.
    They are there to punish pipelines that do no conditioning at all.
    """
    if per_day <= 0 or len(values) == 0:
        return values
    width = abs(span[1] - span[0]) or 1.0
    expected = per_day * len(values) * dt / 86400.0
    count = rng.poisson(expected)
    if count == 0:
        return values

    out = values.copy()
    idx = rng.integers(0, len(values), size=count)
    signs = rng.choice([-1.0, 1.0], size=count)
    sizes = magnitude * width * (0.4 + rng.random(count))
    out[idx] = out[idx] + signs * sizes
    return out


def apply_freezes(
    values: np.ndarray,
    per_month: float,
    dt: float,
    rng: np.random.Generator,
    min_hours: float = 0.5,
    max_hours: float = 14.0,
) -> tuple[np.ndarray, np.ndarray]:
    """A stuck transmitter repeating its last reading.

    Returns the values and a boolean mask of frozen samples. The mask is for
    the validation battery's use only -- it is deliberately *not* exported as
    a quality code, because a frozen transmitter reports good quality and
    finding it is part of the exercise.
    """
    n = len(values)
    frozen = np.zeros(n, dtype=bool)
    if per_month <= 0 or n == 0:
        return values, frozen

    months = n * dt / (30.0 * 86400.0)
    count = rng.poisson(per_month * months)
    if count == 0:
        return values, frozen

    out = values.copy()
    for _ in range(count):
        length = int(rng.uniform(min_hours, max_hours) * 3600.0 / dt)
        if length < 2 or length >= n:
            continue
        start = int(rng.integers(0, n - length))
        out[start:start + length] = out[start]
        frozen[start:start + length] = True
    return out, frozen


def apply_drift(
    values: np.ndarray,
    span: tuple[float, float],
    per_day: float,
    dt: float,
    onset_frac: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """A calibration offset that starts partway through and grows linearly."""
    if per_day == 0:
        return values
    width = abs(span[1] - span[0]) or 1.0
    n = len(values)
    start = int(onset_frac * n)
    days = np.zeros(n)
    days[start:] = np.arange(n - start) * dt / 86400.0
    return values + per_day * width * days


def node_dropouts(
    n: int,
    dt: float,
    rng: np.random.Generator,
    per_month: float = 1.5,
    min_minutes: float = 2.0,
    max_minutes: float = 90.0,
) -> list[tuple[int, int]]:
    """Index ranges where a DCS node was unavailable.

    Returned as ranges rather than applied, because the same ranges must be
    stamped onto every tag on that node simultaneously. That simultaneity is
    the realistic part; applying dropouts per tag independently would produce a
    missingness structure no plant historian has ever shown.
    """
    if per_month <= 0 or n == 0:
        return []
    months = n * dt / (30.0 * 86400.0)
    count = rng.poisson(per_month * months)
    ranges: list[tuple[int, int]] = []
    for _ in range(count):
        length = max(2, int(rng.uniform(min_minutes, max_minutes) * 60.0 / dt))
        if length >= n:
            continue
        start = int(rng.integers(0, n - length))
        ranges.append((start, start + length))
    return sorted(ranges)


def stamp_quality(
    quality: np.ndarray, ranges: list[tuple[int, int]], code: int = Quality.BAD
) -> np.ndarray:
    """Mark index ranges with a quality code."""
    out = quality.copy()
    for lo, hi in ranges:
        out[lo:hi] = code
    return out
