"""End-to-end dataset generation: all ten layers, in order.

The sequence is fixed by the architecture and one ordering decision is worth
calling out.

**Ground truth is computed from the measured data, not the true data.** The
first instinct is to difference the two clean runs, but against a noiseless
twin sharing identical weather, every parameter change is visible within one
scan -- the answer is always "immediately", which is useless. What makes a
fault hard to see is instrument noise, compression deadband and transport lag,
so first-observability is only meaningful once those exist. The manifest is
therefore built last, from the series a user would actually query.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from historiansim.config.schema import ScenarioConfig, config_hash
from historiansim.core.clock import utc_index
from historiansim.core.rng import SeedBank
from historiansim.core.sim import SimResult, apply_disturbance_faults, simulate
from historiansim.disturbances import build_disturbances
from historiansim.faults.scheduler import EpisodePlan, build_episode_plan
from historiansim.historian.export import (
    build_long_format,
    build_regular_grid,
    build_tag_master,
)
from historiansim.measurement.apply import MeasuredData, measure
from historiansim.ballast import generate_ballast
from historiansim.plants import get_plant
from historiansim.tags import ballast_tags

__all__ = ["Dataset", "generate", "write_dataset"]


@dataclass
class Dataset:
    """Everything a generation run produces."""

    cfg: ScenarioConfig
    plan: EpisodePlan
    index: pd.DatetimeIndex
    truth: SimResult = field(repr=False)
    twin: SimResult = field(repr=False)
    measured: MeasuredData = field(repr=False)
    measured_twin: MeasuredData = field(repr=False)
    manifest: dict[str, Any] = field(default_factory=dict, repr=False)
    ballast_count: int = 0

    @property
    def tags(self) -> list[str]:
        return self.measured.tags


def _build_sensor_fn(
    cfg: ScenarioConfig, faults, n_steps: int, dt: float, seeds: SeedBank
):
    """Put transmitter faults on *controlled* tags inside the feedback loop.

    A drifting transmitter on an indicator only corrupts a trend. A drifting
    transmitter on a controlled variable is far more serious: the loop
    faithfully controls the false reading and drives the real quantity away
    from where anyone thinks it is. Applying such a fault only in the
    measurement layer produces a corrupted display over an untouched process --
    which is not what a plugged impulse line does, and leaves the fault with no
    consequences to diagnose.

    So the offset is injected here, where the controller reads it, *and* again
    in the measurement layer, where the historian records it. Both are the same
    transmitter reporting the same wrong number.

    Ordinary calibration drift on a loop's own transmitter goes in for the same
    reason, fault or no fault. Otherwise the historised PV walks away from
    setpoint under integral action, which no real loop does: the controller
    holds the reading at setpoint and the drift appears in the true quantity.
    It is keyed on the loop's PV *tag*, not its signal, because an independent
    indicator on the same signal (LI-102) drifts on its own.
    """
    from historiansim.measurement.instrument import (
        INSTRUMENT_CLASSES,
        calibration_drift,
        drift_direction,
    )
    specs = get_plant(cfg.unit).tags()
    signal_for_tag = {t.name: t.source for t in specs if t.source}
    controlled = {loop.pv_source for loop in cfg.loops}

    offsets: dict[str, np.ndarray] = {}
    scales: dict[str, np.ndarray] = {}
    t_grid = np.arange(n_steps, dtype=float) * dt

    loop_names = {loop.name for loop in cfg.loops}
    for spec in specs:
        if spec.role != "PV" or spec.loop not in loop_names:
            continue
        cls = INSTRUMENT_CLASSES[spec.instrument]
        if spec.source not in controlled or cls.drift_per_day == 0.0:
            continue
        offsets[spec.source] = offsets.get(spec.source, np.zeros(n_steps)) + (
            calibration_drift(
                cls, spec.span, n_steps, dt, drift_direction(seeds, spec.name)
            )
        )
    for fault in faults:
        if getattr(fault, "layer", 0) != 7:
            continue
        signal = signal_for_tag.get(fault.tag)
        if signal is None or signal not in controlled:
            continue
        severity = np.array([fault.severity_at(float(t)) for t in t_grid])
        if fault.mode == "scale":
            scales[signal] = scales.get(signal, np.ones(n_steps)) * (
                1.0 + severity * fault.magnitude
            )
        else:
            offsets[signal] = offsets.get(signal, np.zeros(n_steps)) + (
                severity * fault.magnitude
            )

    if not offsets and not scales:
        return None

    def sensor_fn(true_sig: dict[str, float], k: int) -> dict[str, float]:
        seen = dict(true_sig)
        for name, arr in scales.items():
            seen[name] = seen[name] * arr[k]
        for name, arr in offsets.items():
            seen[name] = seen[name] + arr[k]
        return seen

    return sensor_fn


def _run_once(
    cfg: ScenarioConfig,
    seeds: SeedBank,
    plan: EpisodePlan,
    with_faults: bool,
    progress: bool = False,
) -> tuple[SimResult, np.ndarray]:
    """One pass of layers 2-6. ``with_faults=False`` builds the twin.

    The twin keeps the background degradation. Removing that too would compare
    a fouled plant against a clean one and attribute the whole difference to
    the episode, which is not the question being asked.
    """
    plant = get_plant(cfg.unit)
    dist = build_disturbances(cfg, seeds, plant.unit_cls.disturbance_names)
    ambient = dist.channels["T_amb"]
    t_grid = np.arange(cfg.time.n_steps, dtype=float) * cfg.time.dt_scan

    faults = plan.all_faults if with_faults else list(plan.background)
    dist = apply_disturbance_faults(dist, faults, t_grid)
    in_loop = [f for f in faults if getattr(f, "layer", 0) in (3, 6)]

    sensor_fn = _build_sensor_fn(
        cfg, faults, cfg.time.n_steps, cfg.time.dt_scan, seeds
    )
    result = simulate(
        cfg, dist, faults=in_loop, sensor_fn=sensor_fn, progress=progress
    )
    return result, ambient


def generate(cfg: ScenarioConfig, progress: bool = False) -> Dataset:
    """Run every layer and return the finished dataset."""
    seeds = SeedBank(cfg.seed)
    index = utc_index(cfg.time)

    # Layers 4-6 twice: the run, and its no-fault twin. Both draw disturbances
    # from the same named substreams, so the weather is bit-identical.
    plan = build_episode_plan(cfg, seeds)
    if progress:
        print(plan.summary())
        print("\nsimulating fault run...")
    truth, ambient = _run_once(cfg, SeedBank(cfg.seed), plan, True, progress)
    if progress:
        print("simulating no-fault twin...")
    twin, _ = _run_once(cfg, SeedBank(cfg.seed), plan, False, progress)

    # Layer 7. Ballast is generated once and shared, so the twin differs from
    # the fault run only where the faults actually reach.
    plant = get_plant(cfg.unit)
    specs = plant.tags() + ballast_tags(cfg.ballast_tags)
    ballast_series = generate_ballast(
        [s for s in specs if s.ballast], ambient, cfg.time.dt_scan, seeds
    )
    instrument_faults = [f for f in plan.all_faults if getattr(f, "layer", 0) == 7]

    if progress:
        print("applying measurement layer...")
    unit_params = plant.unit(cfg.params).params
    # No unit transmitter may sit frozen across a labelled interval (with a
    # day of margin), or a stuck reading could hide the evidence for it.
    protected = [
        (e.onset_s - 86400.0, (e.end_s if e.end_s is not None else cfg.time.duration_s) + 86400.0)
        for e in plan.episodes
    ]
    measured = measure(
        truth, specs, SeedBank(cfg.seed), extra_series=ballast_series,
        instrument_faults=instrument_faults, withheld=plan.withheld_tags,
        unit_params=unit_params, protected_windows_s=protected,
        calcs=plant.recompute_calcs,
    )
    measured_twin = measure(
        twin, specs, SeedBank(cfg.seed), extra_series=ballast_series,
        instrument_faults=(), withheld=plan.withheld_tags,
        unit_params=unit_params, protected_windows_s=protected,
        calcs=plant.recompute_calcs,
    )

    dataset = Dataset(
        cfg=cfg, plan=plan, index=index, truth=truth, twin=twin,
        measured=measured, measured_twin=measured_twin,
        ballast_count=sum(1 for s in specs if s.ballast),
    )

    if progress:
        print("building ground truth...")
    dataset.manifest = _build_manifest_from_measured(dataset)
    return dataset


def _as_result(data: MeasuredData, dt: float) -> SimResult:
    """Wrap measured series so the truth helpers can consume them.

    They only ever call ``series()`` and read ``dt_scan``/``n``, so a thin
    adapter is enough and avoids duplicating the detrending logic.
    """
    n = data.n
    return SimResult(
        t=np.arange(n, dtype=float) * dt,
        states=np.empty((0, 0)),
        signals=dict(data.values),
        outputs={}, setpoints={}, modes={}, disturbances={},
        params={}, dt_scan=dt,
    )


def _build_manifest_from_measured(dataset: Dataset) -> dict[str, Any]:
    from historiansim.truth.manifest import build_manifest

    dt = dataset.cfg.time.dt_scan
    fault_view = _as_result(dataset.measured, dt)
    twin_view = _as_result(dataset.measured_twin, dt)

    # Only real-unit tags can give a fault away; ballast is unrelated by
    # construction, and letting it into the search would report spurious
    # first-observable tags from pure coincidence.
    tags = [
        name for name, spec in dataset.measured.specs.items() if not spec.ballast
    ]
    manifest = build_manifest(
        dataset.cfg, dataset.plan, fault_view, twin_view, tags=tags
    )
    manifest["tag_count"] = len(dataset.measured.tags)
    manifest["ballast_tag_count"] = dataset.ballast_count
    return manifest


def manifest_path(dataset_dir: Path) -> Path:
    """Where a dataset's generating config lives."""
    from historiansim.layout import manifest_path as _manifest_path

    return _manifest_path(dataset_dir)


def write_dataset(dataset: Dataset, out_dir: Path, resample_s: float = 60.0) -> Path:
    """Write the dataset to disk in the documented layout (see :mod:`historiansim.layout`).

    The data files, the tag dictionary and the process description describe
    the plant and nothing else, so they can be handed to someone working the
    data blind. Everything that identifies the faults is in
    ``FAULT_ANSWER_KEY.md`` and ``metadata/``. No alarm journal, lab record,
    operator log or work order is written: each of those states or strongly
    hints at a conclusion.
    """
    from historiansim import layout
    from historiansim.truth.labels import build_labels

    out_dir = Path(out_dir)
    meta_dir = out_dir / layout.METADATA
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    long = build_long_format(dataset.measured, dataset.index)
    long.to_parquet(out_dir / layout.HISTORIAN_FULL, index=False)

    grid = build_regular_grid(dataset.measured, dataset.index, resample_s)
    grid.to_parquet(out_dir / f"historian_{int(resample_s)}s.parquet", index=False)

    equipment = get_plant(dataset.cfg.unit).equipment
    build_tag_master(dataset.measured, equipment).to_csv(out_dir / layout.TAGS, index=False)

    labels = build_labels(dataset.index, dataset.plan, dataset.cfg.time.dt_scan)
    stride = max(1, int(round(resample_s / dataset.cfg.time.dt_scan)))
    labels.iloc[::stride].reset_index(drop=True).to_parquet(
        meta_dir / f"labels_{int(resample_s)}s.parquet", index=False
    )

    layout.ground_truth_path(out_dir).write_text(
        json.dumps(dataset.manifest, indent=2), encoding="utf-8"
    )

    manifest = {
        "scenario": dataset.cfg.name,
        "unit": dataset.cfg.unit,
        "seed": dataset.cfg.seed,
        "config_hash": config_hash(dataset.cfg),
        "config": dataset.cfg.model_dump(mode="json"),
        "rows_long_format": int(len(long)),
        "tag_count": len(dataset.measured.tags),
        "ballast_tag_count": dataset.ballast_count,
        "compression_ratio": round(
            len(long) / max(dataset.measured.n * len(dataset.measured.tags), 1), 4
        ),
    }
    layout.manifest_path(out_dir).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    from historiansim.process_doc import write_process_description
    from historiansim.summary import write_summary

    write_process_description(out_dir)
    write_summary(out_dir)
    return out_dir
