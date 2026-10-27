"""Can every root cause in a plant's catalog actually be diagnosed from the data?

The battery's ``solvable`` check only inspects causes that happen to appear in
a generated campaign, so a broken cause can sit behind a fully green battery.
On the reference tank four once did:

* two had fault *target* tags naming internal signals (``LI-101``,
  ``FI-201``) rather than historian tags, so the fault was applied to nothing;
* the DCS ``CALC-*`` tags were computed from true values instead of measured
  ones, making instrument faults invisible to the very tags meant to reveal
  them;
* transmitter faults on *controlled* tags were applied only after the loop,
  so the controller never chased the false reading and the fault had no
  physical consequence to find.

The sweep injects each cause on its own against identical weather, measures it
through the full instrument and transport-lag chain, and compares it with a
fault-free twin. The checks below turn the result into pass/fail findings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "Effect",
    "sweep_catalog",
    "undiagnosable",
    "flat_violations",
    "indistinguishable",
    "dangling_tags",
    "direction_mismatches",
    "MIN_SNR",
]

MIN_SNR = 3.0
_DAY = 86400.0


@dataclass(frozen=True)
class Effect:
    """What one injected cause did to one evidence tag."""

    expectation: str
    peak: float          # largest fault-minus-twin difference inside the episode
    snr: float           # peak against the pre-onset difference scatter
    relative: float      # sustained change against the tag's own variability in the window
    #: One sigma of the instrument's own noise, engineering units. A change
    #: smaller than this cannot be seen by anyone reading the data, however
    #: many sigma it is against a noise-free twin. 0 for calculated tags.
    noise_floor: float = 0.0
    #: Peak of the 1-hour rolling mean of the difference: the change a person
    #: reading the trend sees. Single-sample noise on a calculated tag can be
    #: rescaled by a fault's new operating point without anything sustained
    #: happening, so 'flat' and direction are judged on this, not on ``peak``.
    sustained: float = 0.0


def sweep_catalog(
    plant,
    days: float = 14.0,
    onset_s: float = 6 * _DAY,
    severity: str = "moderate",
    dt_scan: float = 20.0,
    seed: int = 99,
    causes: list[str] | None = None,
) -> dict[str, dict[str, Effect]]:
    """Inject each cause alone; return its effect on every evidence tag."""
    from historiansim.core.rng import SeedBank
    from historiansim.core.sim import apply_disturbance_faults, simulate
    from historiansim.disturbances import build_disturbances
    from historiansim.measurement.apply import measure
    from historiansim.pipeline import _build_sensor_fn
    from historiansim.scenarios import SCENARIOS, build_scenario

    scenario = next(n for n, s in SCENARIOS.items() if s["unit"] == plant.name)
    cfg = build_scenario(scenario, profile="standard", seed=seed, days=days)
    # A coarser scan keeps a per-cause simulation cheap; the integration step
    # may double but never exceeds what the plant's own scenario allows twice.
    cfg.time.dt_scan, cfg.time.dt_sim = dt_scan, min(2 * cfg.time.dt_sim, dt_scan / 2)
    cfg.episodes.n_faults = 0
    cfg.episodes.n_benign = 0
    cfg.episodes.background_fouling = False
    cfg.ballast_tags = 0

    from historiansim.measurement.instrument import INSTRUMENT_CLASSES

    specs = plant.tags()
    floors = {
        s.name: INSTRUMENT_CLASSES[s.instrument].noise_sigma * (s.hi - s.lo)
        for s in specs
    }
    dt = cfg.time.dt_scan
    onset_i = int(onset_s / dt)
    t_grid = np.arange(cfg.time.n_steps, dtype=float) * dt
    unit_params = plant.unit(cfg.params).params

    def run(fault=None):
        seeds = SeedBank(cfg.seed)
        dist = build_disturbances(cfg, seeds, plant.unit_cls.disturbance_names)
        faults = [fault] if fault else []
        dist = apply_disturbance_faults(dist, faults, t_grid)
        sensor_fn = _build_sensor_fn(cfg, faults, cfg.time.n_steps, dt, seeds)
        res = simulate(
            cfg, dist,
            faults=[f for f in faults if getattr(f, "layer", 0) in (3, 6)],
            sensor_fn=sensor_fn,
        )
        return measure(
            res, specs, SeedBank(cfg.seed),
            instrument_faults=[f for f in faults if getattr(f, "layer", 0) == 7],
            unit_params=unit_params, calcs=plant.recompute_calcs,
        )

    twin = run()
    out: dict[str, dict[str, Effect]] = {}
    for cid, cause in plant.catalog.causes.items():
        if causes is not None and cid not in causes:
            continue
        fault = cause.make(onset_s, severity)
        measured = run(fault)

        # Measure inside the episode only. Several causes are repaired part way
        # through, and the recovery transient afterwards is large -- counting it
        # would report a tag as moving when the evidence describes what happens
        # while the fault is present.
        end_s = getattr(fault, "end_s", None)
        end_i = measured.n if end_s is None else min(int(end_s / dt), measured.n)

        effects: dict[str, Effect] = {}
        for ev in cause.evidence:
            if ev.tag not in measured.values:
                continue
            after = measured.values[ev.tag][onset_i:end_i] - twin.values[ev.tag][onset_i:end_i]
            before = measured.values[ev.tag][:onset_i] - twin.values[ev.tag][:onset_i]
            scale = (
                float(np.std(before))
                or float(np.std(twin.values[ev.tag])) * 1e-3
                or 1e-9
            )
            peak = float(after[np.argmax(np.abs(after))])
            window = max(1, int(3600.0 / dt))
            if len(after) >= window:
                smooth = np.convolve(after, np.ones(window) / window, mode="valid")
            else:
                smooth = after
            sustained = float(smooth[np.argmax(np.abs(smooth))])
            natural = float(np.std(twin.values[ev.tag][onset_i:end_i])) or 1e-9
            effects[ev.tag] = Effect(
                ev.expectation, peak, abs(peak) / scale, abs(sustained) / natural,
                floors.get(ev.tag, 0.0), sustained,
            )
        out[cid] = effects
    return out


def undiagnosable(sweep: dict[str, dict[str, Effect]]) -> list[str]:
    """Causes none of whose directional evidence moved above MIN_SNR."""
    bad = []
    for cid, effects in sweep.items():
        directional = [e for e in effects.values()
                       if e.expectation in ("rises", "falls", "steps", "erratic", "frozen")]
        if not directional or not any(e.snr > MIN_SNR for e in directional):
            bad.append(cid)
    return bad


def flat_violations(sweep: dict[str, dict[str, Effect]]) -> list[tuple[str, str, float, float]]:
    """Tags documented flat that actually moved.

    A 'flat' expectation is what rules a competitor out; if it moves, the
    elimination it licenses is wrong. The before-onset difference is often
    exactly zero (shared noise), so a single quantization step can score as
    many sigma -- a change that is also small against the tag's own normal
    variability still counts as flat, as does one below the instrument's own
    noise.
    """
    out = []
    for cid, effects in sweep.items():
        for tag, e in effects.items():
            invisible = abs(e.sustained) <= e.noise_floor
            if e.expectation == "flat" and not (
                e.snr < MIN_SNR * 4 or e.relative < 0.25 or invisible
            ):
                out.append((cid, tag, e.peak, e.snr))
    return out


def indistinguishable(plant, sweep: dict[str, dict[str, Effect]]) -> list[tuple[str, str, str]]:
    """Pairs of candidates within a symptom class with identical signatures.

    Two such candidates would make a dataset unsolvable rather than hard:
    there would be no correct reasoning that reaches one over the other.
    """
    collisions = []
    catalog = plant.catalog
    for sid in catalog.symptoms:
        causes = [c.id for c in catalog.causes_for(sid) if c.id in sweep]
        tags = sorted({e.tag for cid in causes for e in catalog.causes[cid].evidence})

        def signature(cid):
            # Per tag: 0 if it did not move, the sign of a sustained shift, or
            # "~" for an oscillation -- a large raw peak whose hourly mean
            # barely moves. A rising valve and a sticking one both push the
            # peak up; only the second does it without a sustained shift.
            sig = []
            for tag in tags:
                effect = sweep[cid].get(tag)
                if effect is None or effect.snr <= MIN_SNR:
                    sig.append(0)
                elif abs(effect.sustained) < 0.5 * abs(effect.peak):
                    sig.append("~")
                else:
                    sig.append(int(np.sign(effect.sustained)))
            return tuple(sig)

        sigs = {cid: signature(cid) for cid in causes}
        collisions += [
            (sid, a, b) for i, a in enumerate(causes) for b in causes[i + 1:]
            if sigs[a] == sigs[b]
        ]
    return collisions


def dangling_tags(plant) -> list[tuple[str, str, str]]:
    """Catalog references to tags the dataset does not have."""
    tags = plant.tag_names()
    dangling = []
    for cause in plant.catalog.causes.values():
        dangling += [(cause.id, "evidence", e.tag) for e in cause.evidence if e.tag not in tags]
        target = getattr(cause.make(1000.0, "moderate"), "tag", None)
        if target is not None and target not in tags:
            dangling.append((cause.id, "target", target))
        for e in cause.evidence:
            for ref in e.rules_in + e.rules_out:
                if ref not in plant.catalog:
                    dangling.append((cause.id, "cause reference", ref))
    return dangling


def direction_mismatches(sweep: dict[str, dict[str, Effect]]) -> list[tuple[str, str, str, float, float]]:
    """Evidence that moved, but the opposite way to what the answer key says.

    A 'rises' that actually falls is worse than no evidence at all: it sends
    correct reasoning to the wrong conclusion. Only clear movements count.
    """
    out = []
    for cid, effects in sweep.items():
        for tag, e in effects.items():
            if e.snr <= MIN_SNR:
                continue
            if ((e.expectation == "rises" and e.sustained < 0)
                    or (e.expectation == "falls" and e.sustained > 0)):
                out.append((cid, tag, e.expectation, e.sustained, e.snr))
    return out
