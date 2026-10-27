"""Render a dataset's answer key as FAULT_ANSWER_KEY.md.

Everything quantitative comes from ``metadata/ground_truth.json``. Observed
effect sizes are read, not recomputed: isolating a fault's own contribution
requires differencing against the no-fault twin, which only exists during
generation. Every episode runs in isolation, so every effect is attributable to
exactly one cause.

The per-cause walkthroughs are written for a reader checking their own
reasoning: what the first visible symptom is, which competing explanations it
leaves open, and which tags in the shipped data close each one off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from historiansim.layout import ANSWER_KEY, ground_truth_path, manifest_path

__all__ = ["build_summary", "write_summary"]

_LAYERS = {
    2: "process (loss of containment)",
    3: "control system / operation",
    4: "external disturbance or utility",
    6: "process equipment",
    7: "instrument",
}

def _auto_walkthrough(episode: dict, catalog) -> str:
    """The reasoning path, assembled from the evidence when none is written.

    Plants can supply a hand-written ``RootCause.walkthrough``; without one the
    answer key still states what was seen, what confirms the cause and what
    each observation eliminates, in a fixed form.
    """
    def name(cid):
        return catalog.causes[cid].label.lower() if cid in catalog else cid

    cid = episode["true_root_cause"]
    confirming, eliminating = [], []
    for item in episode["discriminating_evidence"]:
        phrase = f"`{item['tag']}` {item['expected']} ({item['note']})"
        if cid in item["rules_in"]:
            confirming.append(phrase)
        elif item["rules_out"]:
            eliminating.append(
                phrase + ", which rules out " + ", ".join(name(c) for c in item["rules_out"])
            )
    parts = [f"First sign: {episode.get('symptom_label', '-')}."]
    if confirming:
        parts.append("Confirmed by " + "; ".join(confirming) + ".")
    if eliminating:
        parts.append("Other causes with the same first sign are ruled out: " + "; ".join(eliminating) + ".")
    return " ".join(parts)


def _fmt_time(ts) -> str:
    return "-" if ts is None else ts.strftime("%Y-%m-%d %H:%M")


def _fmt_hours(value) -> str:
    return "not reached" if value is None else f"{value / 3600:.1f} h"


def build_summary(dataset_dir: Path) -> str:
    dataset_dir = Path(dataset_dir)
    truth = json.loads(
        ground_truth_path(dataset_dir).read_text(encoding="utf-8")
    )
    manifest = json.loads(manifest_path(dataset_dir).read_text(encoding="utf-8"))
    tz = manifest["config"]["time"]["timezone"]
    tags = pd.read_csv(dataset_dir / "tags.csv").set_index("tag")
    origin = pd.Timestamp(manifest["config"]["time"]["start"]).tz_localize(
        tz, nonexistent="shift_forward", ambiguous=True
    ).tz_convert("UTC")

    def at(seconds):
        return None if seconds is None else origin + pd.Timedelta(seconds=float(seconds))

    from historiansim.plants import get_plant

    plant = get_plant(truth["unit"])
    catalog = plant.catalog
    config = manifest["config"]
    timeline = sorted(truth["episodes"], key=lambda e: e["true_onset_s"])
    gap_s = manifest["config"]["episodes"]["min_gap_days"] * 86400.0
    unique = all(
        b["true_onset_s"] >= a["true_end_s"] + gap_s - 1e-6
        for a, b in zip(timeline, timeline[1:])
    )
    no_background = not truth.get("background_degradation")

    def cause_text(cid):
        cause = catalog.causes.get(cid)
        if cause is None:
            return "-", "", []
        return cause.grade or "-", cause.walkthrough, list(cause.competitors)

    lines: list[str] = []
    w = lines.append
    eps = sorted(truth["episodes"], key=lambda e: e["true_onset_s"])
    faults = [e for e in eps if e["class"] == "fault"]
    benign = [e for e in eps if e["class"] == "benign"]

    w(f"# {plant.equipment}: fault answer key\n")
    w("This file lists every abnormal event in the dataset: when it started and ended, its root "
      "cause, and the tags that show it. The other files (the two historian files, `tags.csv` and "
      "`PROCESS_DESCRIPTION.md`) describe only the plant. To use the dataset as a blind test, "
      "give someone those files without this one.\n")

    w("## Summary\n")
    w(f"- **Record:** {_fmt_time(origin)} to {_fmt_time(at(truth['duration_s']))} UTC, "
      f"{truth['duration_s'] / 86400:.0f} days at a {truth['dt_scan_s']:.0f} s scan.")
    w(f"- **Normal operation first:** the first {truth['baseline_end_s'] / 86400:.0f} days "
      "contain no faults and no operator moves. Use them to learn what normal looks like.")
    distinct = len({e["true_root_cause"] for e in faults}) == len(faults)
    components = [e.get("failed_component") for e in faults]
    if distinct and len(set(components)) == len(components):
        w(f"- **Faults:** {len(faults)}, each with a different root cause. No root cause, failure "
          "mechanism or failed component appears twice.")
    else:
        w(f"- **Faults:** {len(faults)}. Some share a root cause or a failed component.")
    if benign:
        w(f"- **Operator actions:** {len(benign)} deliberate changes (listed below). The unit "
          "responds normally to them. They are not faults.")
    else:
        w("- **Operator actions:** none.")
    gap = config["episodes"]["min_gap_days"]
    if unique and no_background:
        w(f"- **One event at a time:** every event has at least {gap:g} days of normal operation "
          "before and after it. Nothing else changes underneath an event: no slow degradation, "
          "no maintenance, and no stuck transmitters on unit tags within a day of any event.")
    else:
        w("- **Overlap:** some events run at the same time, or slow degradation runs underneath "
          "the record, so not every window has a single explanation.")
    drift = plant.background_notes or "slow transmitter calibration drift"
    w("- **Normal background behaviour, not faults:** weather-driven swings, "
      f"{drift}, DCS node communication outages (flagged bad quality), single-sample spikes, "
      "and occasional stuck readings away from the events. The process description covers "
      "all of these.")
    w("- **Every root cause can be worked out** from the historian data, `tags.csv` and "
      "`PROCESS_DESCRIPTION.md`.\n")

    w("## Events (UTC)\n")
    w("| ID | Start | End | Duration | Root cause | Category | Difficulty |")
    w("|---|---|---|---|---|---|---|")
    for e in eps:
        dur_h = (e["true_end_s"] - e["true_onset_s"]) / 3600
        dur = f"{dur_h:.1f} h" if dur_h < 48 else f"{dur_h / 24:.1f} d"
        if e["class"] == "fault":
            grade = cause_text(e["true_root_cause"])[0]
            w(f"| **{e['episode_id']}** | {_fmt_time(at(e['true_onset_s']))} | "
              f"{_fmt_time(at(e['true_end_s']))} | {dur} | {e['true_root_cause_label']} "
              f"| {_LAYERS.get(e['injection_layer'], '-')} | {grade} |")
        else:
            w(f"| {e['episode_id']} | {_fmt_time(at(e['true_onset_s']))} | "
              f"{_fmt_time(at(e['true_end_s']))} | {dur} | Not a fault: {e['note']} | "
              f"operator action | - |")
    w("")
    w("Start is when the cause began acting on the unit; end is when it was removed. Many "
      "faults develop gradually, so their effects take time to show (see the next table), and "
      "the plant takes a little while to settle after the end.\n")

    w("## When each fault becomes visible\n")
    w("| ID | Root cause | First visible after start | First tag to move | Simple 3-sigma alarm after start |")
    w("|---|---|---|---|---|")
    for e in faults:
        w(f"| {e['episode_id']} | {e['true_root_cause_label']} | {_fmt_hours(e.get('detection_lead_s'))} | "
          f"`{e.get('first_observable_tag') or '-'}` | "
          f"{_fmt_hours(e.get('difficulty', {}).get('sigma_detector_lead_s'))} |")
    w("")
    w(f"*First visible* is the earliest time any {plant.equipment} tag moves away from where it "
      "would have been without the fault, for 30 minutes or more. It is the soonest anyone could "
      "notice. *Simple 3-sigma alarm* is when a per-tag high/low limit set on the first "
      f"{truth['baseline_end_s'] / 86400:.0f} days would first trip, ignoring trips the "
      "fault-free plant would also have had at that moment. A long gap between the two "
      "columns means the control system is hiding the fault.\n")

    w("## Fault details\n")
    for e in faults:
        cid = e["true_root_cause"]
        grade, story, competitors = cause_text(cid)
        story = story or _auto_walkthrough(e, catalog)
        w(f"### {e['episode_id']}: {e['true_root_cause_label']}\n")
        w("| | |")
        w("|---|---|")
        w(f"| **Root cause** | {e['true_root_cause_label']} |")
        if e.get("failed_component"):
            w(f"| **Failed item** | {e['failed_component']} |")
        w(f"| **Category** | {_LAYERS.get(e['injection_layer'], '-')} |")
        w(f"| **Start / end (UTC)** | {_fmt_time(at(e['true_onset_s']))} / {_fmt_time(at(e['true_end_s']))} |")
        w(f"| **Severity / difficulty** | {e['severity']} / {grade} |")
        w(f"| **Controlled variables stay on setpoint** | {'yes' if e['masked_by_control'] else 'no'} |")
        w("")
        w(f"**What happened.** {e['mechanism']}\n")
        w(f"**How to diagnose it from the data.** {story}\n")
        if competitors:
            w("**Other causes with the same first symptom, and ruled out by the data:** "
              + "; ".join(competitors) + ".\n")
        w("**Evidence.** *Change* is the largest difference, during the event, between the "
          "measured tag and the same tag in a fault-free run with identical weather and noise, so "
          "it is the fault's own effect.\n")
        w("| Tag | Description | Expected | Change | What it tells you |")
        w("|---|---|---|---|---|")
        for item in e["discriminating_evidence"]:
            tag = item["tag"]
            desc = tags.loc[tag, "description"] if tag in tags.index else ""
            units = tags.loc[tag, "units"] if tag in tags.index else ""
            eff = item.get("observed_change")
            effect = "-" if eff is None else f"{eff:+.3g} {units}".strip()
            role = []
            if item["rules_in"] and cid in item["rules_in"]:
                role.append("confirms the cause")
            if item["rules_out"]:
                names = [catalog.causes[c].label.lower() if c in catalog else c
                         for c in item["rules_out"]]
                role.append("rules out " + ", ".join(names))
            note = item["note"][0].upper() + item["note"][1:]
            w(f"| `{tag}` | {desc} | {item['expected']} | {effect} | "
              f"{note}{' (' + '; '.join(role) + ')' if role else ''}. |")
        w("")

    if benign:
        w("## Operator actions (not faults)\n")
        for e in benign:
            event = plant.benign_events.get(e.get("benign_kind") or "")
            why = event.why if event is not None else ""
            w(f"### {e['episode_id']}: {e['note']}\n")
            w(f"{_fmt_time(at(e['true_onset_s']))} to {_fmt_time(at(e['true_end_s']))} UTC. "
              f"{why}\n")

    w("## Machine-readable files\n")
    w("The `metadata/` folder holds the same information for code:\n")
    w("- `labels_60s.parquet`: one row per minute, with the event ID, root cause and whether "
      "it is a fault, aligned with `historian_60s.parquet`. Use it to train or score a fault "
      "detection model.")
    w("- `ground_truth.json`: everything in this file, including the evidence for every event.")
    w("- `manifest.json`: the full configuration and random seed. Running HistorianSim with it "
      "reproduces the dataset exactly.\n")
    w(f"Generated by HistorianSim {truth['historiansim_version']}, seed {truth['seed']}.")
    return "\n".join(lines)


def write_summary(dataset_dir: Path) -> Path:
    """Write FAULT_ANSWER_KEY.md into the dataset folder."""
    dataset_dir = Path(dataset_dir)
    out = dataset_dir / ANSWER_KEY
    out.write_text(build_summary(dataset_dir), encoding="utf-8")
    return out
