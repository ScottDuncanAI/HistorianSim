"""Turning measured series into the files a historian export actually produces.

Three artifacts, serving different needs:

* ``historian.parquet`` -- long format, one row per stored value, irregular
  timestamps per tag. This is the primary artifact and it matches a PI or PHD
  export closely enough to drop into DuckDB unchanged.
* ``historian_<period>.parquet`` -- a regular wide grid, resampled. A
  convenience for matrix methods like PCA, documented as derived rather than
  recorded, because deriving it involves resampling choices someone should be
  aware they are inheriting.
* ``tags.csv`` -- the tag master, without which the long format is unusable.

Shipping both the irregular and the regular form is deliberate. Diagnostic work
should face the real thing; matrix methods need a matrix. Hiding the
irregularity entirely would remove one of the more instructive properties of
plant data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from historiansim.historian.swinging_door import compress, reconstruct
from historiansim.measurement.apply import MeasuredData
from historiansim.measurement.instrument import INSTRUMENT_CLASSES
from historiansim.tags import BALLAST_UNIT_NAMES

__all__ = ["build_long_format", "build_regular_grid", "build_tag_master"]

#: Deadband for a setpoint that is written continuously -- a cascade slave's
#: SP, which is its master's output. A historian stores it as an analog tag,
#: with compression. Storing it on every change would ship a noise-free,
#: uncompressed copy of the master's output: a trend no real plant keeps.
_CASCADE_SP_DEADBAND = 0.002


def _analog_deadband(spec, values: np.ndarray) -> float | None:
    """Compression deadband for a tag, or None if it is stored on change only."""
    if spec.instrument != "status":
        return INSTRUMENT_CLASSES[spec.instrument].deadband
    if spec.role == "SP" and len(values) > 1:
        if np.count_nonzero(np.diff(values)) > 0.01 * len(values):
            return _CASCADE_SP_DEADBAND
    return None


def build_long_format(
    data: MeasuredData,
    index: pd.DatetimeIndex,
    compressed: bool = True,
) -> pd.DataFrame:
    """Long-format export: tag, timestamp, value, quality.

    Each tag is compressed with its own deadband, so each ends up with its own
    timestamps. The result is sorted by time then tag, the way an export
    ordered by a time-range query comes out.
    """
    seconds = np.arange(data.n, dtype=float) * data.dt
    frames = []

    for name, values in data.values.items():
        spec = data.specs[name]
        quality = data.quality[name]

        deadband = _analog_deadband(spec, values)
        if compressed and deadband is not None:
            keep = compress(seconds, values, quality, deadband, spec.span)
        elif spec.instrument == "status" or spec.role in ("MODE", "SP"):
            # Discrete and setpoint tags are stored on change only, which is
            # why a mode tag is a handful of rows across a whole campaign.
            changed = np.flatnonzero(np.diff(values) != 0)
            keep = np.unique(
                np.concatenate([[0], changed, changed + 1, [data.n - 1]])
            ).astype(np.int64)
            keep = keep[(keep >= 0) & (keep < data.n)]
        else:
            keep = np.arange(data.n, dtype=np.int64)

        frames.append(
            pd.DataFrame(
                {
                    "tag": pd.Categorical([name] * len(keep)),
                    "timestamp": index[keep],
                    "value": values[keep].astype(np.float32),
                    "quality": quality[keep].astype(np.int8),
                }
            )
        )

    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["timestamp", "tag"], kind="stable").reset_index(drop=True)


def build_regular_grid(
    data: MeasuredData,
    index: pd.DatetimeIndex,
    period_s: float = 60.0,
    from_compressed: bool = True,
) -> pd.DataFrame:
    """Wide, regular-grid resampling of the compressed data.

    Built from the *compressed* series by default rather than the raw one, so
    it carries the reconstruction error a real user would inherit. Rebuilding
    it from the uncompressed data would quietly hand back fidelity the
    historian never stored.

    Bad-quality samples become NaN. Filling them is a modelling decision and
    not one this function should make on anyone's behalf.
    """
    seconds = np.arange(data.n, dtype=float) * data.dt
    stride = max(1, int(round(period_s / data.dt)))
    target_idx = np.arange(0, data.n, stride)
    target_t = seconds[target_idx]

    columns: dict[str, np.ndarray] = {}
    for name, values in data.values.items():
        spec = data.specs[name]
        quality = data.quality[name]

        deadband = _analog_deadband(spec, values)
        if from_compressed and deadband is not None:
            keep = compress(seconds, values, quality, deadband, spec.span)
            resampled = reconstruct(seconds[keep], values[keep], target_t)
        else:
            resampled = values[target_idx]

        bad = quality[target_idx] != 0
        resampled = resampled.astype(np.float32)
        resampled[bad] = np.nan
        columns[name] = resampled

    frame = pd.DataFrame(columns, index=index[target_idx])
    frame.index.name = "timestamp"
    return frame.reset_index()


def build_tag_master(data: MeasuredData, equipment: str = "UNIT") -> pd.DataFrame:
    """The tag dictionary. Without it the long format is a pile of numbers."""
    rows = []
    for name, spec in data.specs.items():
        cls = INSTRUMENT_CLASSES[spec.instrument]
        deadband = _analog_deadband(spec, data.values[name]) or 0.0
        rows.append(
            {
                "tag": name,
                "description": spec.description,
                "units": spec.units,
                "range_lo": spec.lo,
                "range_hi": spec.hi,
                "instrument_class": spec.instrument,
                "role": spec.role,
                "loop": spec.loop or "",
                "dcs_node": spec.node,
                "transport_lag_s": spec.transport_lag_s,
                "compression_deadband_pct": round(deadband * 100.0, 4),
                "sensor_lag_s": cls.tau_s,
                "update_period_s": cls.sample_s or data.dt,
                "unit": (
                    BALLAST_UNIT_NAMES.get(spec.name.split("-", 1)[0], "UNKNOWN")
                    if spec.ballast
                    else equipment
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("tag").reset_index(drop=True)
