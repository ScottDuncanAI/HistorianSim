"""Laying episodes out across a campaign.

The scheduler decides *when* things happen. Its job is to produce a timeline
that is realistic rather than convenient:

* a clean baseline at the front, long enough to train on;
* episodes separated by normal operation, so recovery is observable and each
  episode has its own local reference period;
* a mix of severities, because a dataset where every fault is obvious measures
  nothing;
* a couple of genuinely overlapping episodes, because plants have those and
  they break the assumption that one window has one label;
* benign anomalies, so that "a trend moved" is not synonymous with "a fault";
* slow background fouling underneath all of it, reset at a cleaning, so the
  degradation state is not the same at every episode.

Every draw comes from a named RNG substream, so the schedule is reproducible
and independent of anything else that consumes randomness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

import numpy as np

from historiansim.config.schema import ScenarioConfig
from historiansim.core.rng import SeedBank
from historiansim.faults.catalog import SEVERITIES

__all__ = ["Episode", "EpisodePlan", "build_episode_plan"]

DAY = 86400.0
HOUR = 3600.0

#: How the difficulty dial reshapes an episode.
_DIFFICULTY = {
    #             severity bias      duration scale   instrumented?
    "easy":     ({"subtle": 0.1, "moderate": 0.3, "obvious": 0.6}, 0.8, True),
    "standard": ({"subtle": 0.4, "moderate": 0.4, "obvious": 0.2}, 1.0, True),
    "hard":     ({"subtle": 0.7, "moderate": 0.25, "obvious": 0.05}, 1.3, False),
}

@dataclass
class Episode:
    """One labelled interval of the campaign."""

    id: str
    kind: Literal["fault", "benign"]
    cause_id: str
    symptom: str
    severity: str
    onset_s: float
    end_s: float | None
    fault: Any = field(repr=False, default=None)
    concurrent_with: tuple[str, ...] = ()
    note: str = ""
    cause_label: str = ""
    #: For a benign episode, which of the plant's benign events it is.
    benign_kind: str | None = None

    @property
    def label(self) -> str:
        return self.cause_label or self.note


@dataclass
class EpisodePlan:
    """The full timeline, plus the background degradation running under it."""

    episodes: list[Episode]
    background: list[Any] = field(default_factory=list)
    cleanings: tuple[float, ...] = ()
    withheld_tags: tuple[str, ...] = ()
    difficulty: str = "standard"

    @property
    def all_faults(self) -> list[Any]:
        """Everything that has to be handed to the simulator."""
        return [e.fault for e in self.episodes if e.fault is not None] + list(
            self.background
        )

    def faults_of_layer(self, layer: int) -> list[Any]:
        return [f for f in self.all_faults if getattr(f, "layer", None) == layer]

    def summary(self) -> str:
        lines = [f"{len(self.episodes)} episodes, difficulty={self.difficulty}"]
        for ep in sorted(self.episodes, key=lambda e: e.onset_s):
            end = "open" if ep.end_s is None else f"{ep.end_s / DAY:.1f}d"
            lines.append(
                f"  {ep.id}  d{ep.onset_s / DAY:6.2f} -> {end:>6}  "
                f"{ep.kind:<6} {ep.cause_id:<7} {ep.severity:<8} {ep.label}"
            )
        return "\n".join(lines)


#: Benign events are placed preferentially after the shortest episodes.
_TEMPO_ORDER = {"acute": 0, "cycling": 1}


def _assert_no_overlap(episodes: Sequence["Episode"], gap_s: float) -> None:
    """Every labelled interval stands alone, with normal operation either side.

    One window, one label: a benchmark scored on root cause cannot have two
    causes, or a cause and a benign event, sharing a stretch of data.
    """
    ordered = sorted(episodes, key=lambda e: e.onset_s)
    for a, b in zip(ordered, ordered[1:]):
        if a.end_s is None or b.onset_s < a.end_s + gap_s - 1e-6:
            raise ValueError(
                f"{a.id} and {b.id} are not separated by {gap_s / DAY:g} d of "
                f"normal operation"
            )


def _weighted_choice(rng, options: Sequence[str], weights: dict[str, float]) -> str:
    w = np.array([max(weights.get(o, 0.0), 0.0) for o in options], dtype=float)
    if w.sum() <= 0:
        w = np.ones(len(options))
    return str(rng.choice(list(options), p=w / w.sum()))


def _episode_duration(
    tempo: str, severity: str, rng, scale: float, slot_s: float, gap_s: float
) -> float:
    """How long an episode runs before it is repaired.

    Two competing requirements. Physically, a slow degradation should run for
    a week or more -- that is what makes it a campaign rather than an event.
    Structurally, episodes have to fit their slot with normal operation between
    them, or the dataset ends up with no clean intervals and a fault prevalence
    near 100 %, which destroys both the reference periods and the class balance.

    So the natural duration is capped by the space available. The cap binds on
    long degradations in a short campaign and is inactive in a long one.
    """
    if tempo == "acute":                            # someone responds
        base = rng.uniform(6.0, 20.0) * HOUR
    elif tempo == "cycling":                        # cycling gets noticed
        base = rng.uniform(1.5, 4.0) * DAY
    else:                                           # slow degradation
        base = rng.uniform(5.0, 11.0) * DAY

    room = max(slot_s - gap_s, 0.5 * DAY)
    return min(base * scale, room)


def build_episode_plan(cfg: ScenarioConfig, seeds: SeedBank) -> EpisodePlan:
    """Lay out the whole campaign."""
    from historiansim.plants import get_plant

    plant = get_plant(cfg.unit)
    catalog = plant.catalog
    ecfg = cfg.episodes
    total = cfg.time.duration_s
    rng = seeds.get("episode_schedule")

    sev_weights, duration_scale, instrumented = _DIFFICULTY[ecfg.difficulty]
    sev_weights = {**sev_weights, **{}} if ecfg.difficulty != "standard" else ecfg.severity_weights

    baseline_end = ecfg.baseline_days * DAY
    if baseline_end >= total:
        raise ValueError(
            f"baseline of {ecfg.baseline_days} d leaves no room in a "
            f"{total / DAY:.1f} d campaign"
        )

    # -- background degradation ------------------------------------------
    background: list[Any] = []
    cleanings: tuple[float, ...] = ()
    if ecfg.background_fouling and plant.background_degradation is not None:
        background, cleanings = plant.background_degradation(baseline_end, total)
        background = list(background)

    # -- fault episodes ---------------------------------------------------
    episodes: list[Episode] = []
    window_start = baseline_end
    # Leave a tail of normal operation so the last episode's recovery is in
    # the data. Proportional, so a 7 day quick profile is not asked to give up
    # three days of it.
    usable_end = total - min(3 * DAY, total * 0.06)
    n = ecfg.n_faults
    pinned = ecfg.cause_ids
    if pinned is not None:
        # n_faults is routinely lowered after the config is built (short test
        # campaigns, --faults, the no-fault twin), so a longer pin is not an
        # error -- take the leading slice and keep the sequence deterministic.
        # A pin too short to cover n_faults is a genuine under-specification.
        if len(pinned) < n:
            raise ValueError(
                f"cause_ids has only {len(pinned)} entries but n_faults is {n}; "
                f"pin every episode or leave cause_ids unset to sample"
            )
        pinned = list(pinned[:n])
    pinned_sev = ecfg.severities
    if pinned is not None and pinned_sev is not None:
        if len(pinned_sev) < n:
            raise ValueError(
                f"severities has only {len(pinned_sev)} entries but n_faults is {n}"
            )
        pinned_sev = list(pinned_sev[:n])
    else:
        pinned_sev = None

    benign_kinds = list(ecfg.benign_kinds or plant.default_benign_kinds)
    unknown = [k for k in benign_kinds if k not in plant.benign_events]
    if unknown:
        raise ValueError(
            f"{plant.name} has no benign events {unknown}; have {sorted(plant.benign_events)}"
        )
    if ecfg.n_benign > 0 and not benign_kinds:
        raise ValueError(f"{plant.name} declares no benign events to schedule")
    n_benign = ecfg.n_benign
    gap_s = ecfg.min_gap_days * DAY
    benign_slots: dict[int, float] = {}       # fault index -> benign duration after it

    if n > 0:
        # Spread onsets over the usable window, then jitter within each slot so
        # they are not suspiciously regular. All onsets are drawn first so each
        # episode's duration can be capped against the *next* onset: capping
        # against the nominal slot alone lets a late onset run into the next
        # episode, which silently creates overlaps nobody asked for.
        slot = (usable_end - window_start) / n
        if slot < ecfg.min_gap_days * DAY:
            raise ValueError(
                f"cannot fit {n} episodes with a {ecfg.min_gap_days} d gap into "
                f"{(usable_end - window_start) / DAY:.1f} d"
            )
        onsets = [
            window_start + i * slot + rng.uniform(0.05, 0.20) * slot for i in range(n)
        ]
        causes, severities = [], []
        for i in range(n):
            if pinned is not None:
                # Draw nothing: the cause sequence is part of the benchmark
                # definition, not of the seed.
                cause = catalog.get(pinned[i])
            else:
                symptom = _weighted_choice(
                    rng, list(ecfg.symptom_weights), ecfg.symptom_weights
                )
                candidates = catalog.causes_for(symptom)
                cause = candidates[rng.integers(len(candidates))]
            causes.append(cause)
            if pinned_sev is not None:
                severities.append(pinned_sev[i])
            else:
                severities.append(_weighted_choice(rng, SEVERITIES, sev_weights))

        # Benign anomalies, when they must not overlap anything, need a gap of
        # their own. Reserve it after the episodes that are naturally shortest
        # (acute S3, then S2) so the slow degradations keep their full length.
        if ecfg.n_concurrent == 0 and n_benign > 0:
            order = sorted(
                range(n - 1),
                key=lambda i: (
                    _TEMPO_ORDER.get(catalog.symptoms[causes[i].symptom].tempo, 2), i
                ),
            )
            for k, i in enumerate(sorted(order[:n_benign])):
                kind = benign_kinds[k % len(benign_kinds)]
                lo, hi = plant.benign_events[kind].duration_days
                benign_slots[i] = rng.uniform(lo, hi) * DAY

        for i in range(n):
            cause, severity, onset = causes[i], severities[i], onsets[i]
            next_onset = onsets[i + 1] if i + 1 < n else usable_end + gap_s
            room = next_onset - onset - gap_s
            if i in benign_slots:
                room -= benign_slots[i] + gap_s
            duration = _episode_duration(
                catalog.symptoms[cause.symptom].tempo, severity, rng,
                duration_scale, room + gap_s, gap_s,
            )
            end = min(onset + duration, total)
            fault = cause.make(onset, severity)
            if getattr(fault, "end_s", None) is None:
                fault.end_s = end
            else:
                end = fault.end_s
            if ecfg.n_concurrent == 0 and end > onset + room + 1e-6:
                raise ValueError(
                    f"{cause.id} needs {(end - onset) / DAY:.2f} d but only "
                    f"{room / DAY:.2f} d fit before the next episode"
                )

            episodes.append(
                Episode(
                    id=f"EP-{i + 1:03d}", kind="fault", cause_id=cause.id,
                    symptom=cause.symptom, severity=severity, onset_s=float(onset),
                    end_s=float(end), fault=fault, cause_label=cause.label,
                )
            )

    # -- deliberate overlaps ---------------------------------------------
    # Nudge a couple of episodes to start while an earlier one is still open.
    ordered = sorted(episodes, key=lambda e: e.onset_s)
    overlapped = 0
    for earlier, later in zip(ordered, ordered[1:]):
        if overlapped >= ecfg.n_concurrent:
            break
        if earlier.end_s is None or earlier.cause_id == later.cause_id:
            continue
        span = earlier.end_s - earlier.onset_s
        if span < 2 * DAY:
            continue
        new_onset = earlier.onset_s + span * 0.55
        if new_onset >= later.onset_s:
            continue
        shift = later.onset_s - new_onset
        later.onset_s = new_onset
        later.fault.onset_s = new_onset
        if later.end_s is not None:
            later.end_s -= shift
            later.fault.end_s = later.end_s
        later.concurrent_with = (earlier.id,)
        earlier.concurrent_with = earlier.concurrent_with + (later.id,)
        overlapped += 1

    # -- benign anomalies -------------------------------------------------
    faults_sorted = sorted(episodes, key=lambda e: e.onset_s)
    reserved = sorted(benign_slots.items())
    for i in range(n_benign):
        kind = benign_kinds[i % len(benign_kinds)]
        if reserved:
            # Placed inside its reserved gap, clear of both neighbours.
            idx, duration = reserved[i]
            before = faults_sorted[idx]
            after = faults_sorted[idx + 1]
            lo = before.end_s + gap_s
            hi = after.onset_s - gap_s - duration
            if hi < lo:
                raise ValueError(f"no room for a benign event after {before.id}")
            onset = rng.uniform(lo, hi)
        else:
            onset = rng.uniform(baseline_end + DAY, usable_end)
            lo_d, hi_d = plant.benign_events[kind].duration_days
            duration = rng.uniform(lo_d, hi_d) * DAY
        bid = f"BEN-{i + 1:03d}"
        event = plant.benign_events[kind]
        fault = event.build(bid, onset, onset + duration)
        note = event.note

        episodes.append(
            Episode(
                id=bid, kind="benign", cause_id="BENIGN",
                symptom="none", severity="none", onset_s=float(onset),
                end_s=float(fault.end_s), fault=fault, note=note,
                benign_kind=kind,
            )
        )

    if ecfg.n_concurrent == 0:
        _assert_no_overlap(episodes, gap_s)

    return EpisodePlan(
        episodes=sorted(episodes, key=lambda e: e.onset_s),
        background=background,
        cleanings=cleanings,
        withheld_tags=() if instrumented else tuple(plant.hard_mode_withheld),
        difficulty=ecfg.difficulty,
    )
