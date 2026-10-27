"""Swinging door compression, as PI and PHD actually store data.

The algorithm keeps a point only when a straight line from the last stored
point can no longer represent everything in between to within a deadband. What
comes out is not a regular grid: timestamps are irregular, values are held
between stored points, and resampling produces staircases.

**Why this matters more than it looks.** The deadband is per tag, so every tag
ends up with a *different* set of timestamps. That single fact is what makes
the dataset genuinely hard to work with -- there is no shared time axis, so any
analysis has to resample explicitly and decide how. Almost nobody simulates
this, and it is one of the fastest tells that data was generated rather than
recorded. It also shapes anything built on the data, because the tools have to
handle it.
"""

from __future__ import annotations

import numpy as np

__all__ = ["swinging_door", "compress", "reconstruct"]


def _swinging_door_loop(t, v, dev):
    """Core algorithm. Inherently sequential -- the anchor depends on the whole
    history, so there is nothing to vectorize."""
    n = len(t)
    keep = np.empty(n, dtype=np.int64)
    keep[0] = 0
    count = 1

    anchor = 0
    slope_max = -np.inf
    slope_min = np.inf

    for i in range(1, n):
        dti = t[i] - t[anchor]
        if dti <= 0.0:
            continue
        s_up = (v[i] + dev - v[anchor]) / dti
        s_lo = (v[i] - dev - v[anchor]) / dti

        if s_lo > slope_min or s_up < slope_max:
            # The cone has closed: the previous point is the last one a single
            # line could cover, so it becomes the new anchor.
            if keep[count - 1] != i - 1:
                keep[count] = i - 1
                count += 1
            anchor = i - 1
            slope_max = -np.inf
            slope_min = np.inf
            dti = t[i] - t[anchor]
            if dti <= 0.0:
                continue
            s_up = (v[i] + dev - v[anchor]) / dti
            s_lo = (v[i] - dev - v[anchor]) / dti

        if s_lo > slope_max:
            slope_max = s_lo
        if s_up < slope_min:
            slope_min = s_up

    if keep[count - 1] != n - 1:
        keep[count] = n - 1
        count += 1
    return keep[:count]


# Compiled if numba is present. This runs over every sample of every tag --
# tens of millions of iterations for a full campaign -- and it is the one hot
# loop in the export path that cannot be expressed in numpy.
try:  # pragma: no cover - depends on the environment
    from numba import njit

    _swinging_door_fast = njit(cache=True, fastmath=False)(_swinging_door_loop)
except Exception:  # pragma: no cover
    _swinging_door_fast = _swinging_door_loop


def swinging_door(t: np.ndarray, v: np.ndarray, dev: float) -> np.ndarray:
    """Indices to retain so a linear hold reproduces ``v`` within ``dev``.

    Parameters
    ----------
    dev:
        Half-width of the deadband, in engineering units.

    The first and last samples are always kept, which is what makes the stored
    series reconstructible over its full span.
    """
    n = len(t)
    if n <= 2 or dev <= 0:
        return np.arange(n, dtype=np.int64)
    return _swinging_door_fast(
        np.ascontiguousarray(t, dtype=np.float64),
        np.ascontiguousarray(v, dtype=np.float64),
        float(dev),
    )


def compress(
    t: np.ndarray,
    v: np.ndarray,
    quality: np.ndarray,
    deadband: float,
    span: tuple[float, float],
) -> np.ndarray:
    """Indices retained, with quality transitions always kept.

    A change in quality is an event in its own right: a historian stores the
    first bad sample and the first good one after it regardless of value, or
    the boundaries of an outage would be lost.
    """
    width = abs(span[1] - span[0]) or 1.0
    dev = deadband * width
    keep = set(swinging_door(t, v, dev).tolist())

    transitions = np.flatnonzero(np.diff(quality.astype(np.int16)) != 0)
    for idx in transitions:
        keep.add(int(idx))
        keep.add(int(idx) + 1)

    return np.array(sorted(keep), dtype=np.int64)


def reconstruct(
    kept_t: np.ndarray, kept_v: np.ndarray, target_t: np.ndarray
) -> np.ndarray:
    """Interpolate a compressed series back onto a grid.

    Linear rather than step, matching how PI reconstructs an interpolated
    value between stored points. Stepped reconstruction is what a raw
    ``ffill`` gives and it is measurably worse -- worth knowing, since the
    difference is a real source of error in analyses built on historian data.
    """
    return np.interp(target_t, kept_t, kept_v)
