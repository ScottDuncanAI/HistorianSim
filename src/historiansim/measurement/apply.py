"""Apply the full measurement layer to a finished run.

Pure post-processing. Nothing here may reach back into the physics -- that
separation is what lets the true history stay pristine for the ground truth
manifest while the exported dataset is as messy as a real historian export.

Order of operations follows the signal chain:

1. transport lag (a pure delay on the true value),
2. instrument faults (a drifting or offset transmitter),
3. sensor lag, noise, drift, quantization for the instrument class,
4. spikes and freezes,
5. correlated node dropouts, which stamp quality across whole tag groups.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

from historiansim.core.deadtime import shift_series
from historiansim.core.rng import SeedBank
from historiansim.core.sim import SimResult
from historiansim.measurement.instrument import (
    INSTRUMENT_CLASSES,
    Quality,
    apply_instrument,
    drift_direction,
)
from historiansim.measurement.pathology import (
    apply_freezes,
    apply_spikes,
    node_dropouts,
    stamp_quality,
)
from historiansim.tags import TagSpec

__all__ = ["MeasuredData", "measure"]


@dataclass
class MeasuredData:
    """What the DCS and historian would have on a regular grid, before compression."""

    values: dict[str, np.ndarray]
    quality: dict[str, np.ndarray]
    specs: dict[str, TagSpec]
    frozen: dict[str, np.ndarray]
    dt: float

    @property
    def tags(self) -> list[str]:
        return list(self.values)

    @property
    def n(self) -> int:
        return len(next(iter(self.values.values()))) if self.values else 0


def _scale_for_display(spec: TagSpec, values: np.ndarray) -> np.ndarray:
    """Convert simulator units to the engineering units the tag is stored in.

    Valve positions and controller outputs are 0-1 internally and percent on the
    DCS, which is the only conversion the tank needs.
    """
    if spec.units == "%" and spec.instrument in ("valve",):
        return values * 100.0
    if spec.role == "OP" and spec.units == "%":
        return values * 100.0
    return values


def _release_protected(
    unfrozen: np.ndarray, measured: np.ndarray, frozen: np.ndarray, protected: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Undo every whole freeze run that overlaps a protected window."""
    measured = measured.copy()
    frozen = frozen.copy()
    edges = np.flatnonzero(np.diff(np.concatenate([[0], frozen.astype(np.int8), [0]])))
    for start, stop in zip(edges[::2], edges[1::2]):
        if protected[start:stop].any():
            measured[start:stop] = unfrozen[start:stop]
            frozen[start:stop] = False
    return measured, frozen


def measure(
    result: SimResult,
    specs: Sequence[TagSpec],
    seeds: SeedBank,
    extra_series: dict[str, np.ndarray] | None = None,
    instrument_faults: Sequence[object] = (),
    withheld: Sequence[str] = (),
    unit_params: dict | None = None,
    protected_windows_s: Sequence[tuple[float, float]] = (),
    calcs: Callable[[dict, dict | None], None] | None = None,
) -> MeasuredData:
    """Turn a true history into per-tag measured series with quality codes.

    ``protected_windows_s`` are time ranges in which no unit tag may be left
    frozen. A stuck transmitter is realistic background, but one landing on
    the evidence for a labelled episode would make that episode's root cause
    undeterminable for reasons unrelated to the fault -- so any freeze that
    touches a protected window is undone. The random draws are unchanged, so
    the twin and every other tag are unaffected.

    ``calcs`` is the plant's DCS calculation routine; it rebuilds the CALC-*
    tags in place from the measured values.
    """
    dt = result.dt_scan
    extra_series = extra_series or {}
    withheld_set = set(withheld)

    values: dict[str, np.ndarray] = {}
    quality: dict[str, np.ndarray] = {}
    frozen_masks: dict[str, np.ndarray] = {}
    kept: dict[str, TagSpec] = {}

    faults_by_tag: dict[str, list] = {}
    for fault in instrument_faults:
        faults_by_tag.setdefault(fault.tag, []).append(fault)

    t_grid = np.arange(result.n) * dt
    protected = np.zeros(result.n, dtype=bool)
    for lo_s, hi_s in protected_windows_s:
        protected[max(int(lo_s / dt), 0):max(int(hi_s / dt), 0)] = True

    for spec in specs:
        if spec.name in withheld_set:
            continue

        # -- source ------------------------------------------------------
        if spec.name in extra_series:
            true = np.asarray(extra_series[spec.name], dtype=float)
        else:
            source = spec.source or spec.name
            try:
                true = np.asarray(result.series(source), dtype=float)
            except KeyError:
                continue

        # -- transport lag ------------------------------------------------
        if spec.transport_lag_s > 0:
            true = shift_series(true, spec.transport_lag_s, dt)

        true = _scale_for_display(spec, true)

        # -- instrument faults, keyed on the *tag*, not the process -------
        # An orifice plate reading high changes this series and nothing else,
        # which is why a balance built from it stops closing while every real
        # quantity is untouched.
        for fault in faults_by_tag.get(spec.name, ()):
            severity = np.array([fault.severity_at(float(t)) for t in t_grid])
            if fault.mode == "scale":
                true = true * (1.0 + severity * fault.magnitude)
            else:
                true = true + severity * fault.magnitude

        # -- instrument class ---------------------------------------------
        cls = INSTRUMENT_CLASSES[spec.instrument]
        rng = seeds.get(f"instrument/{spec.name}")

        if spec.role == "MODE" or spec.instrument == "status":
            # Discrete and setpoint tags are written by the DCS, not measured.
            measured = true.copy()
            frozen = np.zeros(len(true), dtype=bool)
        else:
            measured = apply_instrument(
                true, cls, spec.span, dt, rng,
                direction=drift_direction(seeds, spec.name),
            )
            measured = apply_spikes(measured, spec.span, cls.spike_per_day, dt, rng)
            unfrozen = measured
            measured, frozen = apply_freezes(measured, cls.freeze_per_month, dt, rng)
            if not spec.ballast and frozen.any() and protected.any():
                measured, frozen = _release_protected(unfrozen, measured, frozen, protected)

        # Physical bounds still apply to the *reading*: a transmitter clamps at
        # its range limits rather than reporting impossible values.
        measured = np.clip(measured, spec.lo, spec.hi)

        values[spec.name] = measured
        frozen_masks[spec.name] = frozen
        quality[spec.name] = np.full(len(measured), Quality.GOOD, dtype=np.int8)
        kept[spec.name] = spec

    # -- DCS calculations ---------------------------------------------------
    # Rebuilt from the measured tags, after instrument faults have corrupted
    # them, so a drifting transmitter opens the balance it feeds.
    if calcs is not None:
        calcs(values, unit_params)
    for name, spec in kept.items():
        if spec.instrument == "calculated" and name in values:
            values[name] = np.clip(values[name], spec.lo, spec.hi)

    # -- correlated dropouts ------------------------------------------------
    # One node event marks every tag on that node bad over the same range.
    nodes = sorted({spec.node for spec in kept.values()})
    for node in nodes:
        ranges = node_dropouts(result.n, dt, seeds.get(f"node/{node}"))
        if not ranges:
            continue
        for name, spec in kept.items():
            if spec.node == node:
                quality[name] = stamp_quality(quality[name], ranges, Quality.BAD)

    return MeasuredData(
        values=values, quality=quality, specs=kept, frozen=frozen_masks, dt=dt
    )
