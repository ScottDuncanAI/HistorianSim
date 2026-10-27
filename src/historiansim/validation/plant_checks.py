"""Staged acceptance gates for a plant, in the order a plant should be built.

Debugging physics through quantization noise and irregular timestamps is
miserable, so the gates go from the inside out:

1. **steady state** -- the design point is a true equilibrium, and the run
   holds it with every loop closed and nothing disturbing it;
2. **setpoint steps** -- each loop settles on a new setpoint without
   sustained oscillation;
3. **each cause alone** -- injected against identical weather and measured
   through the instruments, every cause moves its declared evidence, in the
   declared direction, and leaves its 'flat' tags flat;
4. **catalog integrity** -- candidates in a symptom class are separable and
   every tag and cause the catalog names exists;
5. **quick dataset** -- a quick-profile generation passes the full battery.
"""

from __future__ import annotations

from typing import Callable, Iterable

import numpy as np

__all__ = ["run_plant_checks", "design_disturbances"]

_HOUR = 3600.0


def _first_scenario(plant):
    from historiansim.scenarios import SCENARIOS

    for name, spec in SCENARIOS.items():
        if spec["unit"] == plant.name:
            return name
    raise KeyError(f"plant {plant.name} ships no scenario")


def design_disturbances(cfg, plant) -> dict[str, float]:
    """Every disturbance channel at its configured mean, SI units."""
    d = {}
    for name in plant.unit_cls.disturbance_names:
        if name == "T_amb":
            d[name] = 20.0
        else:
            ch = cfg.disturbances.channels[name]
            d[name] = ch.mean / ch.si_divisor
    return d


def _quiet_config(plant, days: float, seed: int):
    from historiansim.scenarios import build_scenario

    cfg = build_scenario(_first_scenario(plant), profile="quick", seed=seed, days=days)
    cfg.episodes.n_faults = 0
    cfg.episodes.n_benign = 0
    cfg.ballast_tags = 0
    return cfg


def _stage_steady_state(plant, seed: int, echo) -> bool:
    from historiansim.core.sim import ConstantDisturbance, simulate

    cfg = _quiet_config(plant, days=1.0, seed=seed)
    unit = plant.unit(cfg.params)
    d = design_disturbances(cfg, plant)
    targets = {lp.pv_source: lp.sp for lp in cfg.loops}
    ok = True

    u = unit.steady_inputs(targets, d, unit.params)
    x = unit.steady_state(u, d, unit.params)
    dx = unit.derivatives(0.0, x, u, d, unit.params)
    scale = np.maximum(np.abs(x), 1e-6)
    drift_per_hour = np.abs(dx) * _HOUR / scale
    worst = int(np.argmax(drift_per_hour))
    closes = float(drift_per_hour[worst]) < 1e-4
    echo(f"  {'PASS' if closes else 'FAIL'}  design point is an equilibrium: worst state "
         f"{unit.state_names[worst]} moves {drift_per_hour[worst]:.2e} of itself per hour")
    ok &= closes

    for mv, value in u.items():
        inside = 0.05 <= value <= 0.95
        echo(f"  {'PASS' if inside else 'WARN'}  {mv} at design {value * 100:.1f} % "
             f"({'room both ways' if inside else 'near a stop: little room to compensate'})")

    sig = unit.signals(0.0, x, u, d, unit.params)
    for lp in cfg.loops:
        if lp.mode != "CAS":
            continue
        true = sig[lp.pv_source]
        match = abs(lp.sp - true) <= 0.005 * max(abs(true), 1e-9)
        echo(f"  {'PASS' if match else 'FAIL'}  cascade slave {lp.name} SP {lp.sp:.4g} matches "
             f"the equilibrium {lp.pv_source} {true:.4g}")
        ok &= match

    res = simulate(cfg, ConstantDisturbance(d))
    for lp in cfg.loops:
        pv = res.signals[lp.pv_source]
        span = max(abs(lp.sp), 1e-6)
        wander = float(np.max(np.abs(pv - pv[0]))) / span
        holds = wander < 1e-3
        echo(f"  {'PASS' if holds else 'FAIL'}  {lp.name} holds {lp.pv_source} for a day with "
             f"nothing moving: max excursion {wander * 100:.3f} % of setpoint")
        ok &= holds
    return ok


def _stage_setpoint_steps(plant, seed: int, echo) -> bool:
    from historiansim.core.sim import ConstantDisturbance, simulate

    ok = True
    specs = {t.name: t for t in plant.tags()}
    for lp in _quiet_config(plant, days=1.0, seed=seed).loops:
        if lp.mode == "CAS":
            continue                     # a slave's setpoint is its master's output
        cfg = _quiet_config(plant, days=1.5, seed=seed)
        d = design_disturbances(cfg, plant)
        spec = specs.get(f"{lp.name}.PV")
        span = (spec.hi - spec.lo) if spec else max(abs(lp.sp), 1.0)
        step = 0.03 * span
        t_step = 6 * _HOUR

        def on_scan(k, t, loops, name=lp.name, target=lp.sp + step):
            if t >= t_step and loops[name].sp != target:
                loops[name].sp = target

        res = simulate(cfg, ConstantDisturbance(d), on_scan=on_scan)
        pv = res.signals[lp.pv_source]
        dt = cfg.time.dt_scan
        tail = pv[-int(6 * _HOUR / dt):]
        error = abs(float(np.mean(tail)) - (lp.sp + step)) / span
        cycling = float(np.std(tail)) / span
        settled = error < 0.005 and cycling < 0.002
        overshoot = (float(np.max(pv[int(t_step / dt):])) - (lp.sp + step)) / step
        echo(f"  {'PASS' if settled else 'FAIL'}  {lp.name} +{step:.3g} step: final error "
             f"{error * 100:.2f} % span, residual cycling {cycling * 100:.3f} % span, "
             f"overshoot {max(overshoot, 0) * 100:.0f} % of step")
        ok &= settled
    return ok


def _stage_causes(plant, sweep, echo) -> bool:
    from historiansim.validation.catalog import (
        MIN_SNR,
        direction_mismatches,
        flat_violations,
        undiagnosable,
    )

    for cid, effects in sweep.items():
        cause = plant.catalog.causes[cid]
        echo(f"  {cid:<8} {cause.label}")
        for tag, e in effects.items():
            moved = e.snr > MIN_SNR
            echo(f"      {tag:<16} expect {e.expectation:<8} peak {e.peak:+.4g}  "
                 f"{e.snr:7.1f} sigma  {'moved' if moved else 'quiet'}")
    bad = undiagnosable(sweep)
    flats = flat_violations(sweep)
    wrong = direction_mismatches(sweep)
    for cid in bad:
        echo(f"  FAIL  {cid}: no directional evidence moved above {MIN_SNR} sigma")
    for cid, tag, peak, snr in flats:
        echo(f"  FAIL  {cid}: {tag} is documented flat but moved {peak:+.4g} ({snr:.0f} sigma)")
    for cid, tag, exp, peak, snr in wrong:
        echo(f"  FAIL  {cid}: {tag} documented '{exp}' but moved {peak:+.4g} ({snr:.0f} sigma)")
    if not (bad or flats or wrong):
        echo(f"  PASS  all {len(sweep)} causes move their evidence as documented")
    return not (bad or flats or wrong)


def _stage_integrity(plant, sweep, echo) -> bool:
    from historiansim.validation.catalog import dangling_tags, indistinguishable

    collisions = indistinguishable(plant, sweep)
    dangling = dangling_tags(plant)
    for sid, a, b in collisions:
        echo(f"  FAIL  {sid}: {a} and {b} leave identical signatures")
    for cid, kind, ref in dangling:
        echo(f"  FAIL  {cid}: {kind} {ref!r} does not exist")
    components = {}
    for c in plant.catalog.causes.values():
        if not c.component:
            echo(f"  WARN  {c.id}: no failed component declared")
        components.setdefault(c.component, []).append(c.id)
    if not (collisions or dangling):
        echo("  PASS  every symptom class separable; every reference resolves")
    return not (collisions or dangling)


def _stage_quick_dataset(plant, seed: int, echo) -> bool:
    from historiansim.pipeline import generate
    from historiansim.scenarios import build_scenario
    from historiansim.validation import format_report, run_battery

    cfg = build_scenario(_first_scenario(plant), profile="quick", seed=seed)
    checks = run_battery(generate(cfg))
    echo(format_report(checks))
    return not any(not c.passed and c.severity == "error" for c in checks)


def run_plant_checks(
    plant_name: str,
    stages: Iterable[int] | None = None,
    seed: int = 7,
    echo: Callable[[str], None] = print,
) -> bool:
    from historiansim.plants import get_plant
    from historiansim.validation.catalog import sweep_catalog

    plant = get_plant(plant_name)
    stages = sorted(set(stages or [1, 2, 3, 4, 5]))
    titles = {
        1: "steady state", 2: "setpoint steps", 3: "each cause alone",
        4: "catalog integrity", 5: "quick dataset through the battery",
    }
    sweep = None
    ok = True
    for stage in stages:
        echo(f"\nStage {stage}: {titles[stage]}")
        if stage in (3, 4) and sweep is None:
            echo("  (injecting each cause alone against a fault-free twin...)")
            sweep = sweep_catalog(plant)
        if stage == 1:
            passed = _stage_steady_state(plant, seed, echo)
        elif stage == 2:
            passed = _stage_setpoint_steps(plant, seed, echo)
        elif stage == 3:
            passed = _stage_causes(plant, sweep, echo)
        elif stage == 4:
            passed = _stage_integrity(plant, sweep, echo)
        else:
            passed = _stage_quick_dataset(plant, seed, echo)
        ok &= passed
        echo(f"Stage {stage}: {'PASSED' if passed else 'FAILED'}")
        if not passed:
            echo("Fix this stage before moving on: later stages assume it holds.")
            break
    return ok
