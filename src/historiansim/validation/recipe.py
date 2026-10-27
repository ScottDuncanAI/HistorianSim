"""Checks that a dataset honours its recipe, and that a written folder leaks nothing.

The battery in :mod:`historiansim.validation.battery` asks whether the data looks
like plant data. These ask whether the *benchmark* is sound: a clean baseline
long enough to train on, causes that are genuinely distinct, episodes that
never share a window, and a dataset root that does not hand over the answer.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from historiansim.validation.battery import Check

__all__ = ["check_recipe", "check_baseline_settled", "audit_dataset_dir"]

_DAY = 86400.0


def check_recipe(dataset) -> Check:
    """Shape of an ``rca-benchmark``: baseline, uniqueness, separation.

    Run on any dataset; only one built from a recipe is held to it. A
    shortened profile (``quick``) is reported but cannot fail the battery,
    since it squeezes the shape on purpose.
    """
    from historiansim.plants import get_plant
    from historiansim.scenarios import RECIPES

    cfg = dataset.cfg
    if not cfg.recipe:
        return Check("recipe", True, "no recipe declared; nothing to enforce", severity="warn")
    recipe = RECIPES[cfg.recipe]
    catalog = get_plant(cfg.unit).catalog
    ep = cfg.episodes
    problems: list[str] = []

    faults = [e for e in dataset.plan.episodes if e.kind == "fault"]
    ordered = sorted(dataset.plan.episodes, key=lambda e: e.onset_s)
    baseline_end = ep.baseline_days * _DAY

    if ep.baseline_days < recipe["baseline_days"]:
        problems.append(f"baseline {ep.baseline_days:g} d < {recipe['baseline_days']:g} d")
    if ordered and ordered[0].onset_s < baseline_end:
        problems.append(f"{ordered[0].id} starts inside the clean baseline")
    if len(faults) != recipe["n_faults"]:
        problems.append(f"{len(faults)} fault episodes, recipe wants {recipe['n_faults']}")

    causes = [catalog.get(e.cause_id) for e in faults]
    for field, label in (("id", "root cause"), ("name", "mechanism"), ("component", "failed component")):
        values = [getattr(c, field) for c in causes]
        dupes = sorted({v for v in values if values.count(v) > 1})
        if dupes:
            problems.append(f"repeated {label}: {dupes}")
        if field == "component" and any(not v for v in values):
            problems.append("a cause declares no failed component")

    gap = ep.min_gap_days * _DAY
    for a, b in zip(ordered, ordered[1:]):
        if a.end_s is None or b.onset_s < a.end_s + gap - 1e-6:
            problems.append(f"{a.id} and {b.id} are closer than {ep.min_gap_days:g} d")
    if ordered and ordered[-1].end_s is not None:
        tail = cfg.time.duration_s - ordered[-1].end_s
        if tail < min(gap, 0.5 * _DAY):
            problems.append(f"only {tail / 3600:.0f} h of normal operation after the last episode")
    if any(e.concurrent_with for e in dataset.plan.episodes):
        problems.append("concurrent episodes present")
    if dataset.plan.background:
        problems.append("background degradation present")

    shortened = cfg.time.days < 90.0 or cfg.time.dt_scan != 10.0
    detail = (
        f"{cfg.recipe}: {len(faults)} unique faults, {len(ordered) - len(faults)} benign, "
        f"baseline {ep.baseline_days:g} d, gaps >= {ep.min_gap_days:g} d"
        if not problems else "; ".join(problems)
    )
    return Check(
        name="recipe",
        passed=not problems,
        detail=detail + (" (shortened profile, not enforced)" if shortened and problems else ""),
        rationale=(
            "One window, one label: a benchmark scored on root cause cannot repeat a "
            "cause, a mechanism or a failed component, or let two explanations share data."
        ),
        severity="warn" if shortened else "error",
        data={"problems": problems},
    )


def check_baseline_settled(dataset, k: float = 3.0, head_h: float = 6.0) -> Check:
    """The run must open at steady state, not with a startup transient.

    The first days are the training window for every normal-behaviour model
    built on the dataset. A controlled variable still settling at the start of
    it teaches those models that the transient is normal.
    """
    dt = dataset.cfg.time.dt_scan
    base = int(dataset.cfg.episodes.baseline_days * _DAY / dt)
    head = int(head_h * 3600.0 / dt)
    if base <= 2 * head:
        return Check("baseline_settled", True, "baseline too short to assess", severity="warn")
    offenders = []
    for loop in dataset.cfg.loops:
        values = dataset.measured.values.get(f"{loop.name}.PV")
        if values is None:
            continue
        early, rest = values[:head], values[head:base]
        sd = float(np.std(rest)) or 1e-9
        shift = abs(float(np.mean(early)) - float(np.mean(rest)))
        if shift > k * sd:
            offenders.append((loop.name, round(shift / sd, 1)))
    return Check(
        name="baseline_settled",
        passed=not offenders,
        detail=("every loop PV opens at its steady value" if not offenders
                else f"startup transient on {offenders} (shift in baseline sigmas)"),
        rationale="A transient at the head of the training window is learned as normal.",
        data={"offenders": offenders},
    )


#: Files that describe the plant without naming any fault. They are what
#: someone working the data blind is given, alongside the historian files, so
#: they must never name a cause. The answer key and metadata/ are the only
#: places allowed to.
_BLIND_TEXT = ("PROCESS_DESCRIPTION.md", "tags.csv", "CHALLENGE.md", "submission_template.csv")


def audit_dataset_dir(dataset_dir: Path) -> list[Check]:
    """Check a written dataset folder: the documented files, and no answers outside the key."""
    import json

    from historiansim import layout as files
    from historiansim.plants import get_plant

    dataset_dir = Path(dataset_dir)
    truth = json.loads(files.ground_truth_path(dataset_dir).read_text(encoding="utf-8"))
    catalog = get_plant(truth["unit"]).catalog

    present = {p.name for p in dataset_dir.iterdir() if p.is_file()}
    expected = set(files.DATASET_FILES)
    extra = sorted(present - expected)
    missing = sorted(expected - present)
    if not (dataset_dir / files.METADATA).is_dir():
        missing.append(files.METADATA + "/")
    layout = Check(
        name="dataset_layout",
        passed=not extra and not missing,
        detail=("folder holds exactly the documented files" if not (extra or missing)
                else f"unexpected {extra}, missing {missing}"),
        rationale="The dataset is the historian files, tag list, process description and answer key.",
    )

    # Cause ids, cause names and cause labels must not appear in anything a
    # blind reader is given. Labels are matched as whole phrases; one-word
    # labels would match ordinary description text, so only multi-word ones
    # are searched.
    needles: dict[str, str] = {}
    for cause in catalog.causes.values():
        needles[cause.id] = cause.id
        needles[cause.name] = cause.id
        if len(cause.label.split()) >= 2:
            needles[cause.label.lower()] = cause.id
    for e in truth["episodes"]:
        needles[e["episode_id"]] = e["episode_id"]
    hits = []
    for name in _BLIND_TEXT:
        path = dataset_dir / name
        if not path.exists():
            continue
        lower = path.read_text(encoding="utf-8").lower()
        for needle, cid in needles.items():
            pattern = re.escape(needle.lower())
            if re.search(rf"(?<![\w-]){pattern}(?![\w-])", lower):
                hits.append((name, needle, cid))
    leak = Check(
        name="no_answer_leak",
        passed=not hits,
        detail=("process description and tag list name no cause or event" if not hits
                else f"found: {hits[:8]}"),
        rationale=(
            "A list of things that can go wrong is half an answer. The process "
            "description and tag list describe the plant, never what goes wrong."
        ),
        data={"hits": hits},
    )
    return [layout, leak]
