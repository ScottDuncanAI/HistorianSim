"""Turn a finished dataset into a blind root cause challenge.

A dataset as written contains its own answer key, because the person who
simulated it is usually the person who will use it. ``historiansim
make-challenge`` copies the data, tag list and process description into a new
folder with ``CHALLENGE.md`` and ``submission_template.csv``, so it can be
handed to someone else. ``historiansim score`` grades their answers against the
original dataset's metadata.

Nothing in the challenge folder names a cause, a cause class or a count of
events.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

__all__ = ["make_challenge", "build_scoring_key", "load_scoring_key"]


def _origin(cfg: dict) -> pd.Timestamp:
    tz = cfg["time"]["timezone"]
    return (
        pd.Timestamp(cfg["time"]["start"])
        .tz_localize(tz, nonexistent="shift_forward", ambiguous=True)
        .tz_convert("UTC")
    )


def _iso(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_scoring_key(truth: dict, cfg: dict) -> pd.DataFrame:
    """One row per labelled episode, faults and benign operator actions."""
    origin = _origin(cfg)
    rows = []
    for e in sorted(truth["episodes"], key=lambda x: x["true_onset_s"]):
        fault = e["class"] == "fault"
        rows.append({
            "event_id": e["episode_id"],
            "kind": "fault" if fault else "operator_action",
            "start_utc": _iso(origin + pd.Timedelta(seconds=e["true_onset_s"])),
            "end_utc": _iso(origin + pd.Timedelta(seconds=e["true_end_s"])),
            "cause_id": e["true_root_cause"] if fault else "",
            "cause": e.get("true_root_cause_label", "") if fault else e.get("note", ""),
            "failed_component": e.get("failed_component", "") if fault else "",
            "mechanism": e.get("mechanism", "") if fault else "",
        })
    return pd.DataFrame(rows)


def _neighbour_prefixes() -> str:
    from historiansim.tags import BALLAST_UNITS

    return ", ".join(f"`{prefix}-*`" for prefix, _, _ in BALLAST_UNITS)


def _challenge(plant, cfg: dict) -> str:
    eq = plant.equipment
    days = cfg["time"]["days"]
    baseline = cfg["episodes"]["baseline_days"]
    unique = cfg["episodes"]["n_concurrent"] == 0
    lines = [
        f"# {eq} Root Cause Challenge",
        "",
        f"{days:.0f} days of historian data from {eq}. Over that period, things go wrong. "
        "Your job is to find each abnormal event, say when it happened, and identify its "
        "root cause.",
        "",
        "The data is simulated, but the simulator models the process physics, the control "
        "system and the instruments' behaviour, so the record looks like a real plant "
        "historian: noisy, compressed, with gaps, stuck readings and weather effects. Every "
        "event has a single, known root cause, and every root cause can be determined from "
        "the files in this folder alone.",
        "",
        "There is no list of possible causes. You diagnose each event from first principles "
        "and state its root cause in your own words, as you would in a real investigation.",
        "",
        "## The task",
        "",
        "Find every **fault event** in the record. For each one, report:",
        "",
        "1. **Start time**: when the cause began acting on the unit (UTC).",
        "2. **End time**: when the cause was removed (UTC).",
        "3. **Root cause**: one root cause, stated in your own words (see *What counts as a "
        "correct root cause*).",
        "4. **Evidence**: the tags that support your diagnosis. Not scored, but required.",
        "",
        "### What counts as an event",
        "",
        f"A **fault event** is a period during which a fault (a failure or abnormal condition "
        f"in the equipment, instruments, control system, utilities or upstream supply) is "
        f"acting on {eq}.",
        "",
        "These are **not** fault events, and reporting them as faults costs points:",
        "",
        "- Deliberate operator actions to which the unit responds normally: a setpoint "
        "change or a rate change, made with every loop in its normal mode.",
        "- Instrument and historian artifacts: stuck readings, single-sample spikes, DCS "
        "communication outages. The process description describes these.",
        f"- Weather and seasonal effects, slow transmitter calibration drift, and anything on "
        f"the neighbouring units ({_neighbour_prefixes()}).",
        "",
        "Two boundary cases, so that the line is drawn the same way by everyone:",
        "",
        "- A control loop left out of its normal mode (for example in MAN) so that it no "
        "longer regulates what it controls **is** a fault, in the control system, even "
        "though a person put it there.",
        "- Calibration drift at the typical rates given in the process description is "
        "background. An instrument error that develops many times faster than that, or "
        "arrives as a step, **is** a fault.",
        "",
        "### What you are told, and what you are not",
        "",
        f"- The first {baseline:.0f} days of the record are normal operation and can be used "
        "as a reference.",
    ]
    if unique:
        lines.append("- Each fault event has exactly one root cause, and fault events do not overlap.")
    lines += [
        "- Nothing is stated about how many events there are or which kinds of cause occur.",
        "- Some faults develop gradually, so a fault can be acting for a while before its "
        "effects are visible. Scoring does not depend on precise timing.",
        "",
        "### What counts as a correct root cause",
        "",
        "A root cause is judged correct when it names the same physical cause as the answer "
        "key. It must say **what** failed or changed (the specific equipment item, "
        "instrument, valve, controller, utility or upstream system, by tag where it has one) "
        "and **how** (the failure mode or mechanism). Where more than one item could be "
        "responsible, name the one. A description of the symptom is not a root cause: "
        "\"the valve is opening\" describes what you saw, not why. Each fault row gives "
        "**one** root cause; a row that offers alternatives is judged incorrect.",
        "",
        "## Submission",
        "",
        "One CSV file in the format of `submission_template.csv`, one row per event:",
        "",
        "| Column | Format |",
        "|---|---|",
        "| `start_utc` | ISO 8601, UTC, e.g. `2024-03-10T14:00:00Z` |",
        "| `end_utc` | ISO 8601, UTC |",
        "| `kind` | `fault`, `operator_action` or `artifact` |",
        "| `root_cause` | Free text, one root cause. Required for `fault` rows. |",
        "| `evidence_tags` | Tags separated by semicolons |",
        "| `notes` | Free text, optional |",
        "",
        "Rows are discarded if they have a missing or malformed time, `end_utc` before "
        "`start_utc`, an unknown `kind`, no `evidence_tags`, or (for `fault` rows) an empty "
        "`root_cause`.",
        "",
        "## Scoring",
        "",
        "Only rows with `kind` = `fault` are scored. A claim **overlaps** a true fault event if "
        "its interval overlaps the event's true interval extended by 6 hours after its end. "
        "Claims and events are matched one-to-one, longest overlap first.",
        "",
        "| Outcome | Points |",
        "|---|---|",
        "| Fault event detected (matched by a claim) | +1 |",
        "| Matched claim has the correct root cause | +2 more |",
        "| False positive (unmatched claim) | -1 |",
        "| Missed event | 0 |",
        "",
        "Ties are broken by fewer false positives, then by smaller median start-time error "
        "over correctly diagnosed events.",
        "",
        "## Rules",
        "",
        "- Use only the files in this folder. Attempting to obtain the answer key or the "
        "generating configuration defeats the purpose.",
        "- Any method is allowed: manual analysis, statistics, machine learning, LLM agents.",
        "- Every claim must list its evidence tags.",
        "",
        "## Answer key",
        "",
        "The answer key is kept separately so the dataset stays usable as a blind test. For "
        "every event it gives the true times and cause, and the tags that confirm the cause "
        "and rule out the alternatives.",
    ]
    return "\n".join(lines) + "\n"


def load_scoring_key(dataset_dir: Path) -> pd.DataFrame:
    """The scoring table for a dataset, built from its metadata."""
    from historiansim.layout import ground_truth_path, manifest_path

    dataset_dir = Path(dataset_dir)
    truth = json.loads(ground_truth_path(dataset_dir).read_text(encoding="utf-8"))
    cfg = json.loads(manifest_path(dataset_dir).read_text(encoding="utf-8"))["config"]
    return build_scoring_key(truth, cfg)


def make_challenge(dataset_dir: Path, out_dir: Path) -> Path:
    """Copy a dataset into a blind-test folder: the data, without the answers.

    The new folder holds the two historian files, the tag dictionary, the
    process description, ``CHALLENGE.md`` and ``submission_template.csv``.
    The answer key and metadata stay behind in the original dataset, which is
    what ``historiansim score`` grades against.
    """
    import shutil

    from historiansim import layout
    from historiansim.plants import get_plant

    dataset_dir, out_dir = Path(dataset_dir), Path(out_dir)
    if out_dir.resolve() == dataset_dir.resolve():
        raise ValueError("write the challenge to a different folder from the dataset")
    truth = json.loads(layout.ground_truth_path(dataset_dir).read_text(encoding="utf-8"))
    cfg = json.loads(layout.manifest_path(dataset_dir).read_text(encoding="utf-8"))["config"]
    plant = get_plant(truth["unit"])

    out_dir.mkdir(parents=True, exist_ok=True)
    for name in (layout.HISTORIAN_FULL, layout.HISTORIAN_GRID, layout.TAGS):
        shutil.copy2(dataset_dir / name, out_dir / name)
    # The description points at the answer key, which the challenge leaves out.
    text = (dataset_dir / layout.PROCESS_DESCRIPTION).read_text(encoding="utf-8")
    text = text.replace(
        " The events and their root causes are\nlisted in `FAULT_ANSWER_KEY.md`.", ""
    )
    text = "\n".join(
        line for line in text.splitlines() if not line.startswith(f"| `{layout.ANSWER_KEY}`")
    ) + "\n"
    (out_dir / layout.PROCESS_DESCRIPTION).write_text(text, encoding="utf-8")
    (out_dir / "CHALLENGE.md").write_text(_challenge(plant, cfg), encoding="utf-8")

    origin = _origin(cfg)
    example_start = origin + pd.Timedelta(days=cfg["episodes"]["baseline_days"] + 1)
    template = pd.DataFrame([{
        "start_utc": _iso(example_start),
        "end_utc": _iso(example_start + pd.Timedelta(hours=42)),
        "kind": "fault",
        "root_cause": "<what failed, by tag where it has one, and how>",
        "evidence_tags": "<TAG-1>;<TAG-2>",
        "notes": "Example row only. Delete it before submitting.",
    }])
    template.to_csv(out_dir / "submission_template.csv", index=False)
    return out_dir
