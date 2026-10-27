"""Shipped scenarios, duration profiles and dataset recipes.

A scenario is a named starting point, not a fixed dataset. Every field can be
overridden from the command line, and a config plus its seed reproduces the
result exactly. Scenarios live with their plant (``plants/<name>/``); this
module gathers them and turns one into a validated :class:`ScenarioConfig`.

A *recipe* is a dataset shape shared across plants. ``rca-benchmark`` is the
HistorianRCA shape: a clean training baseline, then unique, non-overlapping
fault episodes whose causes are each determinable from the shipped data.
"""

from __future__ import annotations

from datetime import datetime

from historiansim.config.schema import ScenarioConfig, TimeConfig

__all__ = ["PROFILES", "RECIPES", "SCENARIOS", "build_scenario", "describe_scenario"]

#: Duration profiles. The default is 90 days at a 10 s scan: long enough for a
#: 14 day clean baseline, nine episodes, two fouling cycles and 90 diurnal
#: cycles, while still opening in pandas without ceremony.
PROFILES: dict[str, dict] = {
    "quick": {
        "days": 7.0, "dt_scan": 10.0, "dt_sim": 5.0,
        "baseline_days": 2.0, "n_faults": 3, "n_benign": 1,
        "min_gap_days": 0.5, "ballast": 24, "background_fouling": False,
        "note": "regenerates in about a minute; for iterating, not for results",
    },
    "standard": {
        "days": 90.0, "dt_scan": 10.0, "dt_sim": 5.0,
        "baseline_days": 14.0, "n_faults": 9, "n_benign": 3,
        "min_gap_days": 2.0, "ballast": 60, "background_fouling": True,
        "note": "the shipped dataset",
    },
    "campaign": {
        "days": 365.0, "dt_scan": 30.0, "dt_sim": 15.0,
        "baseline_days": 21.0, "n_faults": 26, "n_benign": 8,
        "min_gap_days": 3.0, "ballast": 120, "background_fouling": True,
        "note": "full seasonal swing and several cleaning cycles; coarser scan",
    },
}

#: Dataset recipes. Each key overrides the profile; a scenario overrides both.
RECIPES: dict[str, dict] = {
    "rca-benchmark": {
        # A root cause analysis benchmark. One cause per episode, none sharing
        # a failure mechanism or a failed component, so no label repeats in
        # any form. Episodes never overlap each other or a benign event, and
        # there is no background degradation running underneath, so every
        # labelled window has exactly one explanation. Causes and severities
        # are pinned by the scenario, not drawn from the seed.
        "n_faults": 9,
        "n_benign": 2,
        "n_concurrent": 0,
        "background_fouling": False,
        "min_gap_days": 2.0,
        "baseline_days": 14.0,
        "requires_pinned_causes": True,
        "note": (
            "14 d clean baseline, then 9 unique non-overlapping faults with at "
            "least 2 d of normal operation either side, and 2 benign operator moves"
        ),
    },
}


def _collect_scenarios() -> dict[str, dict]:
    from historiansim.plants import all_plants

    out: dict[str, dict] = {}
    for plant in all_plants():
        for name, spec in plant.scenarios.items():
            if name in out:
                raise ValueError(
                    f"scenario {name!r} is defined by both {out[name]['unit']} and {plant.name}"
                )
            out[name] = {"unit": plant.name, **spec}
    return out


#: Every plant's scenarios, keyed by scenario name; each carries its ``unit``.
SCENARIOS: dict[str, dict] = _collect_scenarios()


def build_scenario(
    name: str,
    profile: str = "standard",
    seed: int = 42,
    **overrides,
) -> ScenarioConfig:
    """Assemble a validated scenario configuration."""
    from historiansim.plants import get_plant

    if name not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}. Available: {sorted(SCENARIOS)}")
    if profile not in PROFILES:
        raise KeyError(f"unknown profile {profile!r}. Available: {sorted(PROFILES)}")

    spec = SCENARIOS[name]
    plant = get_plant(spec["unit"])
    prof = dict(PROFILES[profile])
    recipe_name = spec.get("recipe")
    recipe = dict(RECIPES[recipe_name]) if recipe_name else {}
    # A recipe fixes the dataset's shape; only a shortened profile (quick)
    # may squeeze it, so iteration stays fast.
    if recipe and profile != "quick":
        prof.update({k: v for k, v in recipe.items() if k in prof})
    if recipe.get("requires_pinned_causes") and not spec.get("cause_ids"):
        raise ValueError(f"{name}: recipe {recipe_name} needs pinned cause_ids")

    days = overrides.get("days") or prof["days"]
    dt_scan = overrides.get("dt_scan") or prof["dt_scan"]
    # A plant with fast dynamics may need a finer integration step than the
    # profile default; its scenarios can say so.
    dt_sim = overrides.get("dt_sim") or spec.get("dt_sim") or prof["dt_sim"]
    if dt_sim > dt_scan:
        dt_sim = dt_scan

    cfg = ScenarioConfig(
        name=name,
        unit=spec["unit"],
        recipe=recipe_name,
        description=spec["description"],
        seed=seed,
        time=TimeConfig(
            start=overrides.get("start") or spec.get("start") or datetime(2024, 3, 1),
            timezone=overrides.get("timezone") or spec.get("timezone") or "America/Chicago",
            days=days, dt_scan=dt_scan, dt_sim=dt_sim,
        ),
        params=dict(spec.get("params", {})),
        loops=plant.loops(),
        ballast_tags=overrides.get("ballast", prof["ballast"]),
    )
    cfg.disturbances.channels = plant.channels()

    ep = cfg.episodes
    ep.baseline_days = overrides.get("baseline_days") or prof["baseline_days"]
    ep.n_faults = spec.get("n_faults", prof["n_faults"])
    ep.n_benign = spec.get("n_benign", prof["n_benign"])
    ep.min_gap_days = prof["min_gap_days"]
    ep.background_fouling = spec.get("background_fouling", prof["background_fouling"])
    if "n_concurrent" in spec:
        ep.n_concurrent = spec["n_concurrent"]
    elif "n_concurrent" in recipe:
        ep.n_concurrent = recipe["n_concurrent"]
    if "benign_kinds" in spec:
        ep.benign_kinds = list(spec["benign_kinds"])
    if "symptom_weights" in spec:
        ep.symptom_weights = dict(spec["symptom_weights"])
    else:
        symptoms = list(plant.catalog.symptoms)
        ep.symptom_weights = {s: 1.0 / len(symptoms) for s in symptoms}
    if recipe and profile == "quick":
        # Three non-overlapping faults with gaps already fill a 7 day quick
        # run; a benign event too would not fit.
        ep.n_benign = 0
    if overrides.get("n_faults") is not None:
        ep.n_faults = overrides["n_faults"]
    if overrides.get("difficulty"):
        ep.difficulty = overrides["difficulty"]

    # Applied after the n_faults override so --faults and --no-fault stay
    # usable: a shorter run takes the leading slice of the pinned sequence, and
    # asking for more episodes than the scenario pins falls back to sampling.
    pinned = spec.get("cause_ids")
    if pinned is not None:
        ep.cause_ids = list(pinned[: ep.n_faults]) if ep.n_faults <= len(pinned) else None
        sev = spec.get("severities")
        if sev is not None and ep.cause_ids is not None:
            ep.severities = list(sev[: ep.n_faults])
    return cfg


def describe_scenario(name: str) -> str:
    """Human-readable summary, including the confusion set for each symptom."""
    from historiansim.plants import get_plant

    spec = SCENARIOS[name]
    catalog = get_plant(spec["unit"]).catalog
    lines = [f"{name}", "=" * len(name), "", spec["description"], "",
             f"unit: {spec['unit']}", ""]
    if spec.get("recipe"):
        lines += [f"recipe: {spec['recipe']} -- {RECIPES[spec['recipe']]['note']}", ""]
    pinned = spec.get("cause_ids")
    if pinned:
        lines.append(f"Episodes are pinned, not sampled ({len(pinned)} faults in onset order):")
        for i, cid in enumerate(pinned, 1):
            cause = catalog.get(cid)
            lines.append(f"  {i}. {cid:<7} {cause.symptom}  {cause.label}")
        lines.append("")
    weights = spec.get("symptom_weights") or {s: 1.0 / len(catalog.symptoms)
                                              for s in catalog.symptoms}
    lines.append("Symptom classes and their candidate causes:")
    for sid, weight in sorted(weights.items(), key=lambda kv: -kv[1]):
        symptom = catalog.symptoms[sid]
        lines.append("")
        lines.append(f"  {sid} ({weight:.0%} of episodes): {symptom.label}")
        lines.append(f"      first observable: {symptom.first_observable}")
        for cause in catalog.causes_for(sid):
            evidence = ", ".join(e.tag for e in cause.evidence[:3])
            lines.append(
                f"      {cause.id:<7} layer {cause.layer}  {cause.label}"
            )
            lines.append(f"              discriminated by: {evidence}")
    return "\n".join(lines)
