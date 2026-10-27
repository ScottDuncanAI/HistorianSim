"""The validation battery.

This is the part most simulators omit and the reason to trust anything the rest
of the package produces. Every check corresponds to a way synthetic data
usually gives itself away.

Two checks bound difficulty from opposite sides, and they matter more than the
others:

* :func:`check_not_trivially_detectable` -- if a moving-window threshold finds
  the fault instantly, the dataset is too easy and every result built on it is
  worthless.
* :func:`check_solvable` -- if the declared discriminating evidence does not
  actually separate the true cause from its competitors, the dataset is not
  hard, it is impossible, and any "wrong" answer is the data's fault.

Together they assert that the diagnosis is neither free nor unreachable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from historiansim.measurement.instrument import INSTRUMENT_CLASSES

__all__ = ["Check", "run_battery"]


def _as_view(data, dt: float):
    """Adapt measured series to what the truth helpers consume."""
    from historiansim.pipeline import _as_result

    return _as_result(data, dt)


@dataclass
class Check:
    """One validation result."""

    name: str
    passed: bool
    detail: str
    rationale: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    severity: str = "error"          # 'error' fails the battery, 'warn' does not


def _acorr_time(x: np.ndarray, dt: float, max_lag: int = 4000) -> float:
    """Lag at which autocorrelation first falls below 1/e, in seconds."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 100:
        return float("nan")
    x = x - x.mean()
    if not np.any(x):
        return float("inf")
    n = min(len(x), 60000)
    x = x[:n]
    corr = np.correlate(x, x, mode="full")[n - 1:]
    corr = corr[: min(max_lag, len(corr))]
    if corr[0] <= 0:
        return float("nan")
    corr = corr / corr[0]
    below = np.flatnonzero(corr < np.exp(-1.0))
    return float(below[0] * dt) if below.size else float(len(corr) * dt)


# ---------------------------------------------------------------------------
# difficulty bounds
# ---------------------------------------------------------------------------

def check_not_trivially_detectable(dataset, min_lead_s: float = 3600.0) -> Check:
    """A crude threshold must not beat first-observability on subtle faults.

    Run this one first. Most synthetic fault data is trivially detectable,
    which makes any method built on it look brilliant and tells you nothing.
    """
    offenders = []
    checked = 0
    for ep in dataset.manifest["episodes"]:
        if ep["class"] != "fault" or ep.get("severity") != "subtle":
            continue
        # Only faults the control system is supposed to hide. A sticking valve
        # or a saturated loop announces itself immediately and is *meant* to --
        # its difficulty is telling it apart from the three other causes of the
        # same cycling, not noticing it. Holding those to a masking standard
        # would fail the dataset for being correct.
        if not ep.get("masked_by_control", True):
            continue
        checked += 1
        naive = ep.get("difficulty", {}).get("sigma_detector_lead_s")
        observable = ep.get("detection_lead_s")
        if naive is None:
            continue
        # Trivial means the crude threshold catches the fault about as soon as
        # it is observable at all. A threshold that fires well *before* the
        # fault is observable is not detecting it -- it is a false alarm on the
        # weather -- and says nothing about how hard the fault is.
        if observable is not None and observable - min_lead_s <= naive < observable + min_lead_s:
            offenders.append((ep["episode_id"], naive, observable))

    return Check(
        name="not_trivially_detectable",
        passed=not offenders,
        detail=(
            f"{checked} subtle episodes checked; "
            + ("none beaten by a 3-sigma threshold" if not offenders
               else f"trivially found: {offenders}")
        ),
        rationale=(
            "If a moving-window variance one-liner finds the fault instantly, "
            "the dataset is too easy and every downstream result is worthless."
        ),
        data={"checked": checked, "offenders": offenders},
    )


def check_solvable(dataset, min_effect: float = 3.0) -> Check:
    """The declared discriminating tags must actually move.

    The counterpart to the triviality test. A dataset can fail this by being
    too *hard*: if the evidence the answer key names does not separate the true
    cause from its competitors, then no amount of correct reasoning reaches the
    right answer and the benchmark measures nothing.
    """
    from historiansim.truth.manifest import first_observable

    measured = dataset.measured
    twin = dataset.measured_twin
    dt = dataset.cfg.time.dt_scan
    unsolvable, checked, skipped = [], 0, 0
    min_days = 2.0

    for ep in dataset.manifest["episodes"]:
        if ep["class"] != "fault":
            continue
        evidence = [e for e in ep.get("discriminating_evidence", []) if e["available"]]
        directional = [e for e in evidence if e["expected"] in ("rises", "falls")]
        if not directional:
            continue

        onset = int(ep["true_onset_s"] / dt)
        end = int((ep["true_end_s"] or dataset.measured.n * dt) / dt)
        end = min(end, measured.n)

        # A degradation with a multi-day time constant cannot fairly be asked
        # to have moved a slow tag past three sigma inside a one-day episode.
        # Short campaigns are reported as un-assessed rather than failed --
        # claiming a dataset is unsolvable when the check simply could not see
        # far enough would be the same overclaiming this battery exists to
        # prevent.
        if end - onset < int(min_days * 86400 / dt):
            skipped += 1
            continue
        checked += 1

        # Judged the same way the manifest judges first-observability: against
        # the *residual* of the fault-minus-twin difference, not against the
        # tag's raw standard deviation. Raw sd is inflated by the diurnal swing
        # -- feed temperature moves a couple of degrees every day through
        # ambient coupling alone -- so a real 4 degC upset would be scored as
        # invisible for reasons that have nothing to do with the upset.
        tags = [i["tag"] for i in directional if i["tag"] in measured.values]
        _, when = first_observable(
            _as_view(measured, dt), _as_view(twin, dt),
            ep["true_onset_s"], tags, k=min_effect,
            search_end_s=ep["true_end_s"],
        )
        moved = when is not None
        if not moved:
            unsolvable.append((ep["episode_id"], ep["true_root_cause"]))

    note = f" ({skipped} shorter than {min_days:g} d, not assessable)" if skipped else ""
    return Check(
        name="solvable",
        passed=not unsolvable,
        severity="error" if checked else "warn",
        detail=(
            f"{checked} episodes assessed{note}; "
            + ("all have discriminating evidence that moves" if not unsolvable
               else f"no usable evidence for {unsolvable}")
            if checked
            else f"no episode ran long enough to assess{note}"
        ),
        rationale=(
            "Guarantees the diagnosis is reachable. Without it the dataset can "
            "fail by being impossible rather than hard, and a wrong answer is "
            "the data's fault rather than the method's."
        ),
        data={"checked": checked, "skipped": skipped, "unsolvable": unsolvable},
    )


# ---------------------------------------------------------------------------
# physical consistency
# ---------------------------------------------------------------------------

def check_physical_bounds(dataset) -> Check:
    """Nothing outside its instrument range, no negative flows or levels."""
    violations = []
    for name, values in dataset.measured.values.items():
        spec = dataset.measured.specs[name]
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            violations.append((name, "all non-finite"))
            continue
        if finite.min() < spec.lo - 1e-6 or finite.max() > spec.hi + 1e-6:
            violations.append((name, f"[{finite.min():.3g}, {finite.max():.3g}] "
                                     f"outside [{spec.lo}, {spec.hi}]"))
    return Check(
        name="physical_bounds",
        passed=not violations,
        detail=("all tags inside their declared range" if not violations
                else f"{len(violations)} violations: {violations[:5]}"),
        rationale="A transmitter clamps at its range; values outside it are impossible.",
        data={"violations": violations},
    )


def check_no_range_clamping(dataset, max_fraction: float = 1e-4) -> Check:
    """No plant transmitter may sit pinned at its calibrated range limit.

    A reading clamped at the top of its range hides exactly the excursion an
    analyst needs to see, and a range sized below the plant's own operating
    envelope is a design error, not realism. Valve positions and controller
    outputs are exempt -- running a valve to its stop is legitimate, and is
    the evidence for some causes -- as are DCS-computed and ballast tags.
    """
    offenders = []
    for name, values in dataset.measured.values.items():
        spec = dataset.measured.specs[name]
        if spec.ballast or spec.instrument in ("valve", "status", "calculated"):
            continue
        if spec.role in ("OP", "SP", "MODE"):
            continue
        finite = values[np.isfinite(values)]
        if not finite.size:
            continue
        at_limit = np.mean((finite <= spec.lo + 1e-9) | (finite >= spec.hi - 1e-9))
        if at_limit > max_fraction:
            offenders.append((name, f"{at_limit * 100:.3f} % of samples at a range limit"))
    return Check(
        name="no_range_clamping",
        passed=not offenders,
        detail=("no plant transmitter pinned at its range limit" if not offenders
                else f"{offenders}"),
        rationale="A clamped reading hides the excursion; size the range to the duty.",
        data={"offenders": offenders},
    )


def check_mass_balance(dataset, max_bias_pct: float = 5.0) -> Check:
    """The balance should nearly close, with a small persistent bias.

    Both failure modes are tells. A balance that closes exactly is fake; one
    that does not close at all is broken. Real data misses by instrument error
    plus a small consistent offset.
    """
    from historiansim.plants import get_plant

    balance = get_plant(dataset.cfg.unit).mass_balance
    if balance is None:
        return Check(
            name="mass_balance", passed=True, severity="warn",
            detail="plant declares no liquid balance to check",
        )
    truth = dataset.truth
    inflows, outflows = balance
    feed = sum(np.asarray(truth.series(s), dtype=float) for s in inflows)
    product = sum(np.asarray(truth.series(s), dtype=float) for s in outflows)
    baseline = int(dataset.cfg.episodes.baseline_days * 86400 / truth.dt_scan)
    baseline = min(baseline, len(feed))

    residual = feed[:baseline] - product[:baseline]
    bias_pct = 100.0 * float(np.mean(residual)) / float(np.mean(feed[:baseline]))

    closes = abs(bias_pct) < max_bias_pct
    not_exact = abs(bias_pct) > 1e-9 or float(np.std(residual)) > 1e-9
    return Check(
        name="mass_balance",
        passed=closes and not_exact,
        detail=f"clean-baseline bias {bias_pct:+.3f} % of feed, "
               f"residual sd {float(np.std(residual)):.4f}",
        rationale=(
            "Real balances nearly close but not quite. Exact closure is a tell; "
            "gross non-closure is an error."
        ),
        data={"bias_pct": bias_pct},
    )


def check_control_variance_ratio(
    dataset, min_ratio: float = 2.0, held_pv: float = 0.005
) -> Check:
    """Controlled variables flat, manipulated variables carrying the movement.

    The single property that decides the correlation structure of the whole
    dataset. If the PV wanders and the OP is flat, the loop is not working and
    nothing downstream is meaningful.
    """
    # Measured on the clean baseline only. The claim is about a loop holding a
    # steady setpoint; later in the campaign operators move setpoints and faults
    # saturate valves, and counting that movement as "the PV wandered" would
    # fail the check for behaviour that is entirely correct.
    end = int(dataset.cfg.episodes.baseline_days * 86400 / dataset.cfg.time.dt_scan)
    end = min(end, dataset.measured.n) or dataset.measured.n

    # Every loop holding its own setpoint. A cascade slave is excluded: its
    # setpoint moves every scan by design, so its PV is meant to move too. So
    # is a flow loop: its PV scatter is the meter's own turbulence noise, not
    # a process the loop failed to hold.
    rows = []
    for loop in (lp.name for lp in dataset.cfg.loops
                 if lp.mode == "AUTO" and lp.ti > 0):
        pv_tag, op_tag = f"{loop}.PV", f"{loop}.OP"
        spec = dataset.measured.specs.get(pv_tag)
        if spec is not None and spec.instrument == "flow":
            continue
        pv = dataset.measured.values.get(pv_tag)
        op = dataset.measured.values.get(op_tag)
        if pv is None or op is None:
            continue
        pv, op = pv[:end], op[:end]
        pv_spec = dataset.measured.specs[pv_tag]
        op_spec = dataset.measured.specs[op_tag]
        # Normalise by span so a temperature and a valve position compare.
        pv_cv = float(np.std(pv)) / (pv_spec.hi - pv_spec.lo)
        op_cv = float(np.std(op)) / (op_spec.hi - op_spec.lo)
        rows.append((loop, pv_cv, op_cv, op_cv / pv_cv if pv_cv > 0 else np.inf))

    # A loop with little load to absorb -- a level loop between two
    # flow-controlled feeds -- has a quiet output *and* a quiet PV. That is a
    # loop holding, not one failing; only a PV that wanders indicts it.
    bad = [r for r in rows if r[3] < min_ratio and r[1] > held_pv]
    return Check(
        name="control_variance_ratio",
        passed=not bad,
        detail="; ".join(
            f"{loop}: OP/PV span-normalised sd ratio {ratio:.1f}"
            for loop, _, _, ratio in rows
        ) or "no loops found",
        rationale=(
            "Information lives in the manipulated variable. Fouling shows as a "
            "valve slowly opening while the temperature stays perfect. A loop "
            f"whose PV stays within {held_pv * 100:.1f} % of span is holding "
            "whatever its output does."
        ),
        data={"rows": rows},
    )


# ---------------------------------------------------------------------------
# statistical fingerprints
# ---------------------------------------------------------------------------

def check_noise_is_colored(dataset, min_ratio: float = 3.0) -> Check:
    """Instrument noise must be correlated, and correlated differently by class.

    White noise across every tag is the fastest way to fail an autocorrelation
    check, and a single noise model across classes is nearly as obvious.
    """
    dt = dataset.cfg.time.dt_scan
    by_class: dict[str, list[float]] = {}

    # Measured minus true isolates exactly the instrument's contribution --
    # lag, noise, drift and quantization -- with no process movement left in
    # it. Both series are on hand, so there is no reason to estimate the noise
    # by filtering. Two earlier attempts using differencing and then a
    # high-pass both failed, and in each case the artefact was the filter's:
    # differencing anti-correlates at lag 1, and a short smoothing window
    # erases precisely the slow noise the temperature classes are defined by.
    for name, values in dataset.measured.values.items():
        spec = dataset.measured.specs[name]
        if spec.instrument in ("status", "calculated") or spec.role in ("SP", "MODE"):
            continue
        if spec.transport_lag_s > 0 or spec.units == "%" or spec.ballast:
            continue  # needs realignment or rescaling to compare like with like
        try:
            true = np.asarray(dataset.truth.series(spec.source or name), dtype=float)
        except KeyError:
            continue
        if len(true) != len(values):
            continue
        residual = values - true
        # Remove the calibration drift first: a linear ramp is perfectly
        # correlated at every lag and would saturate the metric, hiding the
        # noise colour it is meant to measure.
        x = np.arange(len(residual), dtype=float)
        slope, intercept = np.polyfit(x, residual, 1)
        tau = _acorr_time(residual - (slope * x + intercept), dt)
        if np.isfinite(tau):
            by_class.setdefault(spec.instrument, []).append(tau)

    medians = {k: float(np.median(v)) for k, v in by_class.items()}
    white = [k for k, v in medians.items() if v <= dt]
    temps = medians.get("temperature_slow", medians.get("temperature", 0.0))
    flows = medians.get("flow", 0.0)
    distinct = temps > flows * 1.2 if (temps and flows) else True

    return Check(
        name="noise_is_colored",
        passed=not white and distinct,
        detail=(
            "median 1/e autocorrelation time by class: "
            + ", ".join(f"{k} {v:.0f}s" for k, v in sorted(medians.items()))
            + ("" if not white else f"; WHITE: {white}")
        ),
        rationale=(
            "A thermowell low-passes the process, a DP cell does not. One noise "
            "model across all tags is a giveaway."
        ),
        data={"medians": medians},
    )


def check_transport_lag(dataset) -> Check:
    """Cross-correlation must peak at the declared lag, not at zero."""
    dt = dataset.cfg.time.dt_scan
    rows = []
    for name, spec in dataset.measured.specs.items():
        if spec.transport_lag_s <= 0 or spec.source is None:
            continue
        try:
            upstream = dataset.truth.series(spec.source)
        except KeyError:
            continue
        downstream = dataset.measured.values[name]
        n = min(len(upstream), len(downstream), 40000)
        a = upstream[:n] - np.mean(upstream[:n])
        b = downstream[:n] - np.mean(downstream[:n])
        if not np.any(a) or not np.any(b):
            continue
        max_lag = int(spec.transport_lag_s * 4 / dt) + 20
        corr = [np.dot(b[lag:], a[: n - lag]) if lag else float(np.dot(b, a))
                for lag in range(max_lag)]
        peak = int(np.argmax(corr)) * dt
        rows.append((name, spec.transport_lag_s, peak))

    bad = [r for r in rows if abs(r[2] - r[1]) > max(2 * dt, 0.5 * r[1])]
    return Check(
        name="transport_lag",
        passed=not bad,
        detail="; ".join(f"{n}: declared {d:.0f}s, measured {m:.0f}s" for n, d, m in rows)
               or "no lagged tags",
        rationale="Synthetic data usually correlates instantaneously; real data does not.",
        data={"rows": rows},
        severity="warn",
    )


def check_pca_dimensionality(dataset, lo: int = 2, hi: int = 25) -> Check:
    """Clean-baseline PCA should need a plausible number of components.

    Too few and every tag is a copy of one driver; too many and the tags are
    independent noise. Real plant data sits in between.
    """
    from numpy.linalg import svd

    baseline_s = dataset.cfg.episodes.baseline_days * 86400
    stride = max(1, int(60.0 / dataset.cfg.time.dt_scan))
    cols = []
    for name, values in dataset.measured.values.items():
        spec = dataset.measured.specs[name]
        # The unit's own tags only: neighbouring-unit ballast is independent by
        # construction, so every ballast loop adds a dimension and the count
        # would measure the ballast tag count rather than the plant.
        if spec.role in ("MODE", "SP") or spec.instrument == "status" or spec.ballast:
            continue
        series = values[: int(baseline_s / dataset.cfg.time.dt_scan) : stride]
        if np.std(series) > 0:
            cols.append((series - series.mean()) / series.std())
    if len(cols) < 3:
        return Check("pca_dimensionality", False, "too few varying tags", severity="warn")

    matrix = np.column_stack(cols)
    sv = svd(matrix, compute_uv=False)
    variance = sv**2 / np.sum(sv**2)
    n_components = int(np.searchsorted(np.cumsum(variance), 0.95) + 1)

    return Check(
        name="pca_dimensionality",
        passed=lo <= n_components <= hi,
        detail=f"{n_components} components explain 95 % of clean-baseline variance "
               f"across {matrix.shape[1]} tags",
        rationale="Effective dimensionality far below or above the tag count is a tell.",
        data={"n_components": n_components, "n_tags": matrix.shape[1]},
    )


# ---------------------------------------------------------------------------
# historian realism
# ---------------------------------------------------------------------------

def check_historian_irregularity(dataset, max_overlap: float = 0.9) -> Check:
    """Every tag must end up with its own timestamps.

    The single fact that makes historian data genuinely awkward: there is no
    shared time axis, so any analysis has to resample explicitly.
    """
    from historiansim.historian.swinging_door import compress

    dt = dataset.cfg.time.dt_scan
    seconds = np.arange(dataset.measured.n, dtype=float) * dt
    kept: dict[str, set[int]] = {}
    for name, values in dataset.measured.values.items():
        spec = dataset.measured.specs[name]
        if spec.instrument in ("status",) or spec.role in ("MODE", "SP"):
            continue
        deadband = INSTRUMENT_CLASSES[spec.instrument].deadband
        idx = compress(seconds, values, dataset.measured.quality[name],
                       deadband, spec.span)
        if len(idx) > 50:
            kept[name] = set(idx.tolist())

    names = list(kept)[:12]
    overlaps = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            shared = len(kept[a] & kept[b]) / min(len(kept[a]), len(kept[b]))
            overlaps.append(shared)
    worst = max(overlaps) if overlaps else 0.0
    total_kept = sum(len(v) for v in kept.values())
    ratio = total_kept / max(len(kept) * dataset.measured.n, 1)

    return Check(
        name="historian_irregularity",
        passed=worst < max_overlap and 0.005 < ratio < 0.6,
        detail=f"overall retention {ratio * 100:.1f} %, worst pairwise timestamp "
               f"overlap {worst * 100:.0f} %",
        rationale=(
            "Per-tag deadbands give every tag a different timestamp set, which "
            "is what forces explicit resampling and reproduces real exports."
        ),
        data={"retention": ratio, "worst_overlap": worst},
    )


def check_frozen_values_present(dataset) -> Check:
    """Stuck transmitters must exist, and must not be flagged.

    Frozen values are everywhere in real historians and almost never in
    synthetic data. Flagging them would hand over the judgement call.
    """
    frozen_tags = {k: int(v.sum()) for k, v in dataset.measured.frozen.items() if v.any()}
    flagged = 0
    for tag, mask in dataset.measured.frozen.items():
        if mask.any():
            flagged += int(np.sum(dataset.measured.quality[tag][mask] != 0))

    # Freezes are Poisson at well under one per tag-month, so a short campaign
    # can legitimately contain none. Only require their presence once enough
    # tag-months have elapsed for absence to be evidence of a defect.
    tag_months = len(dataset.measured.values) * dataset.measured.n * dataset.measured.dt / (
        30.0 * 86400.0
    )
    expect_freezes = tag_months > 20.0

    return Check(
        name="frozen_values",
        passed=(bool(frozen_tags) or not expect_freezes) and flagged == 0,
        detail=f"{len(frozen_tags)} tags contain frozen stretches over "
               f"{tag_months:.0f} tag-months; {flagged} frozen samples carry a "
               f"bad-quality flag (must be 0)",
        rationale=(
            "A stuck transmitter reports good quality. Finding it is part of "
            "the exercise, so nothing may mark it."
        ),
        data={"frozen_tags": len(frozen_tags), "flagged": flagged},
    )


def check_correlated_dropouts(dataset) -> Check:
    """Bad quality must arrive per DCS node, not per tag independently."""
    by_node: dict[str, list[np.ndarray]] = {}
    for name, quality in dataset.measured.quality.items():
        node = dataset.measured.specs[name].node
        by_node.setdefault(node, []).append(quality != 0)

    grouped, independent = 0, 0
    for node, masks in by_node.items():
        if len(masks) < 2 or not any(m.any() for m in masks):
            continue
        stacked = np.vstack(masks)
        any_bad = stacked.any(axis=0)
        all_bad = stacked.all(axis=0)
        if any_bad.sum() == 0:
            continue
        if all_bad.sum() / any_bad.sum() > 0.9:
            grouped += 1
        else:
            independent += 1

    # Dropouts are Poisson per node, so a short record can contain none.
    # Only require them once enough node-months have passed that absence would
    # itself be evidence of a defect (fewer than 1 % of runs would see none).
    from historiansim.measurement.pathology import node_dropouts

    import inspect

    rate = inspect.signature(node_dropouts).parameters["per_month"].default
    node_months = len(by_node) * dataset.measured.n * dataset.measured.dt / (30.0 * 86400.0)
    expect = rate * node_months > 4.6
    return Check(
        name="correlated_dropouts",
        passed=independent == 0 and (grouped > 0 or not expect),
        detail=f"{grouped} nodes fail as a group, {independent} fail tag-by-tag "
               f"({rate * node_months:.1f} outages expected)",
        rationale=(
            "Instruments do not fail independently. A DCS node drops and every "
            "tag on it goes bad at the same instant."
        ),
        data={"grouped": grouped, "independent": independent},
    )


def check_no_fault_twin_matches(dataset) -> Check:
    """The twin must be "the same run minus the fault", exactly.

    Three things have to hold, and none of them is about how *many* tags
    differ -- a campaign with nine episodes should move most real tags:

    1. ballast is bit-identical, since it shares only the weather;
    2. everything is bit-identical before the first onset;
    3. some real tags do differ afterwards, or the faults never took effect.

    A failure of (1) or (2) means an added fault shifted an unrelated RNG
    stream, which silently breaks every comparison the twin exists to support.
    """
    dt = dataset.cfg.time.dt_scan
    onsets = [e.onset_s for e in dataset.plan.episodes] or [dataset.measured.n * dt]
    first_onset = int(min(onsets) / dt)

    ballast_differing, early_differing, real_differing = [], [], []
    for name, values in dataset.measured.values.items():
        twin = dataset.measured_twin.values.get(name)
        if twin is None:
            continue
        spec = dataset.measured.specs[name]
        if not np.allclose(values, twin, equal_nan=True):
            (ballast_differing if spec.ballast else real_differing).append(name)
        if first_onset > 1 and not np.allclose(
            values[:first_onset], twin[:first_onset], equal_nan=True
        ):
            early_differing.append(name)

    ok = not ballast_differing and not early_differing and bool(real_differing)
    return Check(
        name="no_fault_twin",
        passed=ok,
        detail=(
            f"{len(real_differing)} real tags diverge after the first onset; "
            f"ballast differing: {len(ballast_differing)}; "
            f"pre-onset differing: {len(early_differing)}"
        ),
        rationale=(
            "Ballast and the pre-onset period share everything with the twin, "
            "so they must match bit for bit. Anything else means the RNG is "
            "coupled and the twin is not a controlled comparison."
        ),
        data={
            "real": len(real_differing),
            "ballast": ballast_differing,
            "pre_onset": early_differing,
        },
    )


CHECKS: list[Callable] = [
    check_not_trivially_detectable,
    check_solvable,
    check_physical_bounds,
    check_no_range_clamping,
    check_mass_balance,
    check_control_variance_ratio,
    check_noise_is_colored,
    check_transport_lag,
    check_pca_dimensionality,
    check_historian_irregularity,
    check_frozen_values_present,
    check_correlated_dropouts,
    check_no_fault_twin_matches,
]


def run_battery(dataset) -> list[Check]:
    """Run every check. Triviality first, because it gates everything else."""
    from historiansim.validation.recipe import check_baseline_settled, check_recipe

    results = []
    for check in [*CHECKS, check_baseline_settled, check_recipe]:
        try:
            results.append(check(dataset))
        except Exception as exc:  # a broken check must not hide the others
            results.append(
                Check(
                    name=getattr(check, "__name__", str(check)),
                    passed=False,
                    detail=f"check raised {type(exc).__name__}: {exc}",
                    severity="error",
                )
            )
    return results
