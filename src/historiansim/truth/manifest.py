"""The ground truth manifest.

Emitted from inside the generation run, not reconstructed afterwards. Several
things are known here that cannot be recovered from the finished dataset --
most importantly the difference between when a fault *started* and when it
first became *visible*.

That gap is the difficulty of the dataset, and measuring it requires the
no-fault twin: the identical run, same seed, same weather, same ballast, with
the faults removed. Differencing the two isolates the fault's contribution from
everything else that was moving anyway. No amount of staring at the fault run
alone gives that number honestly.

The manifest is written to ``answer_key/`` so it can be withheld while someone
works the dataset, then used to grade not just the final answer but the
reasoning -- which is what the discrimination matrix is for.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from historiansim.config.schema import ScenarioConfig, config_hash
from historiansim.core.sim import SimResult
from historiansim.faults.catalog import FaultCatalog
from historiansim.faults.scheduler import Episode, EpisodePlan

__all__ = ["first_observable", "build_manifest", "sigma_detector_lead"]

_SUSTAIN_S = 1800.0  # a divergence must hold this long to count as observable


def _sustained_first(mask: np.ndarray, need: int) -> int | None:
    """First index where ``mask`` stays True for ``need`` consecutive samples."""
    if need <= 1:
        idx = np.flatnonzero(mask)
        return int(idx[0]) if idx.size else None
    # Rolling sum over a boolean array; the window is short, so this is cheap.
    csum = np.concatenate([[0], np.cumsum(mask.astype(np.int32))])
    runs = csum[need:] - csum[:-need]
    idx = np.flatnonzero(runs == need)
    return int(idx[0]) if idx.size else None


def first_observable(
    fault: SimResult,
    twin: SimResult,
    onset_s: float,
    tags: Sequence[str],
    k: float = 3.0,
    sustain_s: float = _SUSTAIN_S,
    search_end_s: float | None = None,
) -> tuple[str | None, float | None]:
    """Earliest time any tag's fault-minus-twin difference clears the noise.

    Returns the tag that gave it away and the time it did so.

    The subtlety is concurrent episodes. If an earlier fault is still running,
    the fault-minus-twin difference is already large and already trending when
    this episode starts, and a naive threshold on it fires instantly for every
    later episode. So the difference is linearly detrended against the day
    before onset and the residual is what gets tested. That answers the right
    question -- when did this episode change the difference from whatever it
    was already going to be -- rather than "was anything wrong at all".
    """
    dt = fault.dt_scan
    onset_idx = int(onset_s / dt)
    baseline_lo = max(0, onset_idx - int(DAY_S / dt))
    if onset_idx <= baseline_lo + 10 or onset_idx >= fault.n - 10:
        return None, None

    # Bound the search at the next event elsewhere in the campaign. Once
    # another episode starts or stops, the fault-minus-twin difference contains
    # its contribution too, and any hit after that point cannot honestly be
    # attributed to this episode. Better to report "not observed within the
    # clean window" than a number contaminated by a neighbour.
    search_hi = fault.n if search_end_s is None else min(fault.n, int(search_end_s / dt))
    if search_hi <= onset_idx + 2:
        return None, None

    need = max(1, int(sustain_s / dt))
    pre = np.arange(baseline_lo, onset_idx, dtype=float)
    post = np.arange(onset_idx, search_hi, dtype=float)
    best_tag, best_idx = None, None

    for tag in tags:
        try:
            a, b = fault.series(tag), twin.series(tag)
        except KeyError:
            continue
        diff = (a - b).astype(float)

        # Extrapolate whatever the difference was already doing.
        slope, intercept = np.polyfit(pre, diff[baseline_lo:onset_idx], 1)
        residual_pre = diff[baseline_lo:onset_idx] - (slope * pre + intercept)
        residual_post = diff[onset_idx:search_hi] - (slope * post + intercept)

        scale = float(np.std(residual_pre))
        if scale <= 0 or not np.isfinite(scale):
            # A tag that was perfectly quiet, e.g. a setpoint nobody had moved.
            # Any real change is then unambiguous, so use the tag's own scale.
            scale = max(float(np.std(b)) * 1e-3, 1e-9)

        hit = _sustained_first(np.abs(residual_post) > k * scale, need)
        if hit is not None and (best_idx is None or hit < best_idx):
            best_tag, best_idx = tag, hit

    if best_idx is None:
        return None, None
    return best_tag, float(onset_s + best_idx * dt)


DAY_S = 86400.0


def sigma_detector_lead(
    fault: SimResult, onset_s: float, tags: Sequence[str],
    baseline_end_s: float, k: float = 3.0, twin: SimResult | None = None,
) -> float | None:
    """When a naive threshold detector would have fired, for comparison.

    Deliberately the crudest thing anyone would try: standardise each tag
    against the clean baseline period and alarm at k sigma. Publishing the gap
    between this and a real diagnosis is the honest way to report a result --
    "found it 4 hours after first observability, where a variance threshold
    took 19 hours" is a claim; "the agent found the fault" is not.

    With ``twin`` given, an alarm the no-fault twin raises just as early is
    not credited: a seasonal drift or an instrument's slow calibration walk
    crossing its band at the moment of onset is a false alarm that happened to
    coincide, not a detection of this episode.
    """
    dt = fault.dt_scan
    base_hi = int(baseline_end_s / dt)
    onset_idx = int(onset_s / dt)
    if base_hi <= 10 or onset_idx >= fault.n:
        return None

    earliest = None
    need = max(1, int(_SUSTAIN_S / dt))
    quiet_from = max(base_hi, onset_idx - int(3600.0 / dt))

    for tag in tags:
        try:
            values = fault.series(tag)
        except KeyError:
            continue
        mu = float(np.mean(values[:base_hi]))
        sd = float(np.std(values[:base_hi]))
        if sd <= 0 or not np.isfinite(sd):
            continue

        exceeds = np.abs(values - mu) > k * sd

        # A detector that was already firing before onset is not detecting this
        # episode -- it is reacting to seasonal drift or an earlier fault it
        # never recovered from. Crediting it with an instant catch would make
        # the dataset look trivially detectable when the truth is that this
        # particular detector is simply wrong most of the time. Its false
        # positives are the interesting part of the comparison, not a reason to
        # fail the data.
        if quiet_from < onset_idx and exceeds[quiet_from:onset_idx].mean() > 0.25:
            continue

        hit = _sustained_first(exceeds[onset_idx:], need)
        if hit is not None and twin is not None:
            try:
                twin_values = twin.series(tag)
            except KeyError:
                twin_values = None
            if twin_values is not None:
                twin_hit = _sustained_first(
                    np.abs(twin_values - mu)[onset_idx:] > k * sd, need
                )
                if twin_hit is not None and twin_hit <= hit + need:
                    continue
        if hit is not None and (earliest is None or hit < earliest):
            earliest = hit
    return None if earliest is None else float(earliest * dt)


def _propagation(
    fault: SimResult, twin: SimResult, onset_s: float, tags: Sequence[str],
    search_end_s: float | None = None,
) -> list[list[Any]]:
    """Order in which tags start to diverge, relative to the first one.

    This is the causal chain as it actually played out, including transport
    lag, rather than an asserted topology.
    """
    hits = []
    for tag in tags:
        who, when = first_observable(
            fault, twin, onset_s, [tag], search_end_s=search_end_s
        )
        if when is not None:
            hits.append((tag, when))
    if not hits:
        return []
    hits.sort(key=lambda item: item[1])
    t0 = hits[0][1]
    return [[tag, round(when - t0, 1)] for tag, when in hits]


def _observed_change(
    fault: SimResult,
    twin: SimResult,
    tag: str,
    onset_s: float,
    end_s: float | None,
    window_end_s: float | None = None,
) -> float | None:
    """This episode's own contribution to a tag, at peak divergence.

    Fault minus twin, so ambient and every other shared driver cancel exactly.
    Using the raw change in the tag would report the weather instead: feed
    temperature swings six degrees a day on its own, enough to make a tag
    correctly documented as flat look like it moved more than any fault does.

    Returns ``None`` when no clean interval exists -- see
    :func:`_has_clean_interval`. Two earlier attempts tried to correct for a
    concurrent episode instead of declining to measure: subtracting the
    difference at onset left the neighbour's continuing ramp in, and linearly
    detrending against the preceding day extrapolated that ramp past the point
    where the neighbour *ended*, which flipped the sign on the confirming tag.
    With one twin there is no sound correction, only a smaller error, so this
    reports nothing rather than something wrong.
    """
    dt = fault.dt_scan
    lo = int(onset_s / dt)
    hi = fault.n if end_s is None else min(int(end_s / dt), fault.n)
    if window_end_s is not None:
        hi = min(hi, int(window_end_s / dt))
    if hi - lo < 2:
        return None

    try:
        diff = (fault.series(tag) - twin.series(tag)).astype(float)
    except KeyError:
        return None

    # Nothing else is running, so the difference starts at zero and everything
    # after it belongs to this episode.
    residual = diff[lo:hi] - float(np.mean(diff[max(0, lo - 30):lo + 1]))
    if not residual.size:
        return None
    return float(residual[int(np.argmax(np.abs(residual)))])


def _has_clean_interval(
    episode: Episode, plan: EpisodePlan, min_hours: float = 6.0
) -> bool:
    """Whether this episode ever runs with nothing else active.

    If a neighbour is already in progress when this one starts, the
    fault-minus-twin difference carries both and cannot be attributed. Isolating
    it properly would need a counterfactual run per episode, which costs a full
    simulation each; declining to quote a number is the cheap honest option.
    """
    others = [
        e for e in plan.episodes
        if e.id != episode.id
        and e.onset_s <= episode.onset_s
        and (e.end_s is None or e.end_s > episode.onset_s)
    ]
    if others:
        return False
    window_end = _clean_window_end(episode, plan)
    end = episode.end_s if episode.end_s is not None else float("inf")
    if window_end is not None:
        end = min(end, window_end)
    return (end - episode.onset_s) >= min_hours * 3600.0


def _clean_window_end(episode: Episode, plan: EpisodePlan) -> float | None:
    """When another episode next perturbs the picture.

    Everything strictly after this instant is confounded, so first-observability
    is only claimed inside it.
    """
    boundaries: list[float] = []
    for other in plan.episodes:
        if other.id == episode.id:
            continue
        for edge in (other.onset_s, other.end_s):
            if edge is not None and edge > episode.onset_s:
                boundaries.append(edge)
    return min(boundaries) if boundaries else None


def _episode_entry(
    episode: Episode,
    cfg: ScenarioConfig,
    plan: EpisodePlan,
    fault: SimResult,
    twin: SimResult,
    tags: Sequence[str],
    withheld: Sequence[str],
    catalog: FaultCatalog,
) -> dict[str, Any]:
    cause = catalog.causes.get(episode.cause_id)
    onset = episode.onset_s
    window_end = _clean_window_end(episode, plan)
    clean = _has_clean_interval(episode, plan)
    obs_tag, obs_time = first_observable(
        fault, twin, onset, tags, search_end_s=window_end
    )
    naive = sigma_detector_lead(
        fault, onset, tags, cfg.episodes.baseline_days * DAY_S, twin=twin
    )

    entry: dict[str, Any] = {
        "episode_id": episode.id,
        "class": episode.kind,
        "severity": episode.severity,
        "true_onset_s": round(onset, 1),
        "true_end_s": None if episode.end_s is None else round(episode.end_s, 1),
        "concurrent_with": list(episode.concurrent_with),
        "note": episode.note,
    }

    if cause is None:                      # benign anomaly
        entry.update(
            {
                "symptom_class": None,
                "true_root_cause": "BENIGN",
                "benign_kind": episode.benign_kind,
                "candidate_causes": [],
                "injection_layer": 3,
                "masked_by_control": False,
                "discriminating_evidence": [],
                "first_observable_tag": obs_tag,
                "first_observable_s": None if obs_time is None else round(obs_time, 1),
                "detection_lead_s": (
                    None if obs_time is None else round(obs_time - onset, 1)
                ),
            }
        )
        return entry

    candidates = [c.id for c in catalog.causes_for(episode.symptom)]
    evidence = [
        {
            "tag": e.tag,
            "expected": e.expectation,
            "note": e.note,
            "rules_in": list(e.rules_in),
            "rules_out": list(e.rules_out),
            "available": e.tag not in withheld,
            # Recorded here because it needs the twin, which only exists during
            # generation and is never shipped.
            "observed_change": (
                None if e.tag in withheld or not clean
                else _observed_change(
                    fault, twin, e.tag, onset, episode.end_s, window_end
                )
            ),
        }
        for e in cause.evidence
    ]

    entry.update(
        {
            "symptom_class": episode.symptom,
            "symptom_label": catalog.symptoms[episode.symptom].label,
            "true_root_cause": cause.id,
            "true_root_cause_name": cause.name,
            "true_root_cause_label": cause.label,
            "mechanism": cause.mechanism,
            "failed_component": cause.component,
            "candidate_causes": candidates,
            "injection_layer": cause.layer,
            "masked_by_control": cause.masked_by_control,
            "discriminating_evidence": evidence,
            "first_observable_tag": obs_tag,
            "first_observable_s": None if obs_time is None else round(obs_time, 1),
            "detection_lead_s": (
                None if obs_time is None else round(obs_time - onset, 1)
            ),
            "propagation": _propagation(
                fault, twin, onset,
                [e["tag"] for e in evidence if e["available"]], window_end,
            ),
            "uncontaminated_window_s": (
                None if window_end is None else round(window_end - onset, 1)
            ),
            "effects_measurable": clean,
            "difficulty": {
                "sigma_detector_lead_s": None if naive is None else round(naive, 1),
                "withheld_evidence": [e["tag"] for e in evidence if not e["available"]],
            },
        }
    )
    return entry


def build_manifest(
    cfg: ScenarioConfig,
    plan: EpisodePlan,
    fault: SimResult,
    twin: SimResult,
    tags: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Assemble the complete answer key."""
    from historiansim import __version__
    from historiansim.plants import get_plant

    catalog = get_plant(cfg.unit).catalog

    withheld = set(plan.withheld_tags)
    if tags is None:
        tags = [t for t in fault.names() if t not in withheld and not t.startswith("PARAM-")]
    tags = [t for t in tags if t not in withheld]

    episodes = [
        _episode_entry(ep, cfg, plan, fault, twin, tags, plan.withheld_tags, catalog)
        for ep in sorted(plan.episodes, key=lambda e: e.onset_s)
    ]

    return {
        "scenario": cfg.name,
        "unit": cfg.unit,
        "recipe": cfg.recipe,
        "seed": cfg.seed,
        "historiansim_version": __version__,
        "config_hash": config_hash(cfg),
        "difficulty": plan.difficulty,
        "duration_s": cfg.time.duration_s,
        "dt_scan_s": cfg.time.dt_scan,
        "baseline_end_s": cfg.episodes.baseline_days * DAY_S,
        "withheld_tags": list(plan.withheld_tags),
        "cleanings_s": [round(c, 1) for c in plan.cleanings],
        "background_degradation": [
            {"id": f.id, "param": f.param, "label": f.label,
             "onset_s": round(f.onset_s, 1)}
            for f in plan.background
        ],
        "symptom_classes": {
            sid: {
                "label": s.label,
                "first_observable": s.first_observable,
                "description": s.description,
                "candidate_causes": [c.id for c in catalog.causes_for(sid)],
                "discrimination_matrix": catalog.discrimination_matrix(sid),
            }
            for sid, s in catalog.symptoms.items()
        },
        "episodes": episodes,
    }
