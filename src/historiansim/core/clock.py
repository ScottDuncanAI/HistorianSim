"""Plant clock: the mapping between simulation seconds and wall-clock time.

Historian timestamps are UTC. Operator logs and lab samples are local. The
default scenario window deliberately straddles a daylight-saving transition, so
anything that assumes local time advances uniformly will produce a visible
one-hour discontinuity -- which is exactly the reconciliation problem real
cross-source analysis runs into.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from historiansim.config.schema import TimeConfig

__all__ = ["utc_index", "local_hours", "day_of_year"]


def utc_index(tcfg: TimeConfig, n: int | None = None) -> pd.DatetimeIndex:
    """UTC timestamps for each controller scan."""
    count = tcfg.n_steps if n is None else n
    start_local = pd.Timestamp(tcfg.start).tz_localize(
        tcfg.timezone, nonexistent="shift_forward", ambiguous=True
    )
    offsets = pd.to_timedelta(np.arange(count) * tcfg.dt_scan, unit="s")
    return pd.DatetimeIndex(start_local.tz_convert("UTC") + offsets)


def local_hours(index: pd.DatetimeIndex, timezone: str) -> np.ndarray:
    """Local hour-of-day as a float, for driving diurnal cycles.

    Converted through the real timezone rather than a fixed offset, so the
    diurnal cycle stays locked to the sun across a DST change instead of
    jumping an hour.
    """
    local = index.tz_convert(timezone)
    return (
        local.hour.to_numpy(dtype=float)
        + local.minute.to_numpy(dtype=float) / 60.0
        + local.second.to_numpy(dtype=float) / 3600.0
    )


def day_of_year(index: pd.DatetimeIndex, timezone: str) -> np.ndarray:
    """Fractional day of year, for seasonal drivers."""
    local = index.tz_convert(timezone)
    return local.dayofyear.to_numpy(dtype=float) + local_hours(index, timezone) / 24.0
