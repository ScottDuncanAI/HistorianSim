"""Generate the process description that ships with a dataset.

The plant supplies its own sections -- service, equipment, design basis,
physics, control strategy, utilities -- computed from its model so the design
figures cannot drift from the parameters actually integrated. This module adds
the sections that are the same for every plant: the tag list, the calculated
tags, instrument and historian behaviour, neighbouring equipment and the data
files.

The document describes the plant and its data, and nothing else. It must give
an analyst everything needed to reason from first principles while saying
nothing about which abnormal events occur, when, or why. In particular it never
lists failure modes: a catalogue of "things that can go wrong here" is a
candidate list, and a candidate list is half an answer.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from historiansim.config.schema import ScenarioConfig
from historiansim.measurement.instrument import INSTRUMENT_CLASSES
from historiansim.plants import GENERIC_SECTIONS, Plant, PlantDescription, Section, get_plant
from historiansim.tags import BALLAST_UNIT_NAMES, BALLAST_UNITS

__all__ = ["build_process_description", "write_process_description"]


def _load_config(dataset_dir: Path | None) -> ScenarioConfig | None:
    if dataset_dir is None:
        return None
    from historiansim.pipeline import manifest_path

    path = manifest_path(dataset_dir)
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return ScenarioConfig.model_validate(manifest["config"])


def _default_config(plant_name: str | None) -> ScenarioConfig:
    """The plant's first shipped scenario, for describing it without a dataset."""
    from historiansim.scenarios import SCENARIOS, build_scenario

    for name, spec in SCENARIOS.items():
        if plant_name is None or spec["unit"] == plant_name:
            return build_scenario(name)
    raise KeyError(f"no scenario ships for plant {plant_name!r}")


def _crosses_dst(cfg: ScenarioConfig) -> bool:
    tz = ZoneInfo(cfg.time.timezone)
    start = cfg.time.start.replace(tzinfo=tz)
    end = start + timedelta(days=cfg.time.days)
    return start.utcoffset() != end.utcoffset() or any(
        (start + timedelta(days=d)).utcoffset() != start.utcoffset()
        for d in range(int(cfg.time.days) + 1)
    )


# ---------------------------------------------------------------------------
# generic sections
# ---------------------------------------------------------------------------

def _tags_section(plant: Plant, desc: PlantDescription) -> list[str]:
    out: list[str] = []
    w = out.append
    w(f"Every {plant.equipment} tag in the historian. Ranges are the transmitter calibrated")
    w("ranges; readings are clamped to them. The *transport delay* is the pure")
    w("time delay between the vessel and the measurement point.")
    w("")
    w("| Tag | Description | Units | Range | Instrument class | Transport delay | Notes |")
    w("|---|---|---|---|---|---|---|")
    for spec in plant.tags():
        if spec.instrument == "calculated":
            continue
        lag = f"{spec.transport_lag_s / 60:.0f} min" if spec.transport_lag_s else "-"
        w(f"| `{spec.name}` | {spec.description} | {spec.units} | {spec.lo:g} - {spec.hi:g} "
          f"| {spec.instrument} | {lag} | {desc.tag_notes.get(spec.name, '')} |")
    w("")
    w("Valve positions and controller outputs are in percent of travel or")
    w("output. Mode tags are integers. Setpoint tags are written by the DCS.")
    return out


def _calcs_section(desc: PlantDescription) -> list[str]:
    out: list[str] = []
    w = out.append
    w("The DCS computes these every scan from the *measured* values of the tags")
    w("above. It has no other knowledge of the process, so a calculated tag")
    w("inherits any error in its inputs. They are historised and compressed")
    w("like any other tag.")
    w("")
    w("| Tag | Units | Definition |")
    w("|---|---|---|")
    for tag, units, definition in desc.calc_definitions:
        w(f"| `{tag}` | {units} | {definition} |")
    if desc.calc_notes:
        w("")
        w("Interpretation notes:")
        w("")
        out.extend(desc.calc_notes)
    return out


def _instruments_section(plant: Plant, cfg: ScenarioConfig, desc: PlantDescription) -> list[str]:
    out: list[str] = []
    w = out.append
    specs = plant.tags()
    classes = sorted({s.instrument for s in specs})
    w("### 8.1 Measurement characteristics by instrument class")
    w("")
    w("Every transmitter adds the lag and noise of its class. The noise wanders")
    w("smoothly over the correlation time shown, as real transmitter noise does,")
    w("and readings are rounded to the transmitter's digital resolution. Figures")
    w("are fractions of the tag's span.")
    w("")
    w("| Class | Sensor lag | Noise (1 sigma) | Noise correlation time | Resolution | Typical calibration drift | Update | Historian deadband |")
    w("|---|---|---|---|---|---|---|---|")
    for name in classes:
        c = INSTRUMENT_CLASSES[name]
        if name == "status":
            w("| status (SP, MODE) | - | - | - | - | - | on change | on change |")
            continue
        if name == "calculated":
            w(f"| calculated | - | inherited | inherited | - | inherited | every scan | {c.deadband * 100:.2f} % |")
            continue
        upd = f"{c.sample_s / 60:.0f} min" if c.sample_s else "every scan"
        drift = f"{c.drift_per_day * 100:.4f} %/day" if c.drift_per_day else "-"
        w(f"| {name} | {c.tau_s:g} s | {c.noise_sigma * 100:.2f} % | {c.noise_tau_s:g} s "
          f"| {c.lsb * 100:.3f} % | {drift} | {upd} | {c.deadband * 100:.2f} % |")
    w("")
    if "flow" in classes:
        w("- **Flow** readings are noisy and fast: the meters see real turbulence.")
    if "temperature" in classes or "temperature_slow" in classes:
        w("- **Temperature** readings are smooth and slow because the thermowell")
        w("  filters the process. `temperature_slow` is the heavy bulk-vessel")
        w("  thermowell.")
    if "level" in classes:
        w("- **Level** readings wander slowly, and each level transmitter's")
        w("  calibration drifts slowly and independently.")
    out.extend(desc.instrument_notes)
    w("- **Valve positions and controller outputs** are clean, with a")
    w("  resolution of about 0.1 % of travel.")
    w("- Each transmitter has a small, slowly varying calibration offset of its")
    w("  own. Two instruments measuring the same thing therefore agree closely")
    w("  but not exactly, and the small gap between them can wander by a few")
    w("  tenths of a percent of span over months.")
    w("")
    w("### 8.2 Data quality")
    w("")
    w("- The `quality` field is **0 = good, 1 = uncertain, 2 = bad**.")
    w("- Each tag is served by one of several DCS I/O nodes (column `dcs_node` in")
    w("  `tags.csv`). Communication outages of a few minutes up to about")
    w("  1.5 hours occur occasionally; every tag on the affected node is marked")
    w("  bad for the same interval. In the long-format file the value recorded")
    w("  against a bad sample is not meaningful. In the regular grid bad samples")
    w("  are `NaN`.")
    w("- Isolated single-sample spikes occur occasionally on transmitters.")
    w("- A transmitter can occasionally stop updating and repeat its last")
    w("  reading for minutes to hours while still reporting good quality. A")
    w("  stuck reading stores no new values in the compressed record, so on a")
    w("  tag that normally moves it shows as a gap in `historian_10s.parquet` and as a")
    w("  straight line in the 60 s grid, which interpolates between stored points.")
    w("- These data-quality artifacts are a normal property of historian data")
    w("  and are not, in themselves, process events.")
    w("")
    w("### 8.3 Historian compression")
    w("")
    w("Analog tags are stored with swinging-door compression, each with its own")
    w("deadband (column `compression_deadband_pct` in `tags.csv`, percent of")
    w("span). A value is stored only when the signal departs from the line")
    w("through the last stored points by more than the deadband. As a result")
    w("**every tag has its own irregular timestamps** and there is no shared time")
    w("axis. Status tags (modes, operator setpoints) are stored only when they")
    slaves = [f"`{lp.name}.SP`" for lp in cfg.loops if lp.mode == "CAS"]
    if len(slaves) == 1:
        w(f"change. The cascade setpoint {slaves[0]}, which changes every scan, is")
        w("compressed as an analog tag.")
    elif slaves:
        w(f"change. The cascade setpoints {', '.join(slaves)}, which change every")
        w("scan, are compressed as analog tags.")
    else:
        w("change.")
    return out


def _neighbours_section(plant: Plant, cfg: ScenarioConfig) -> list[str]:
    out: list[str] = []
    w = out.append
    w("The historian extract also contains tags from other equipment on the same")
    w(f"historian ({cfg.ballast_tags} tags in total, identified by the `unit` column of `tags.csv`):")
    w("")
    for prefix, description, n_loops in BALLAST_UNITS:
        w(f"- `{prefix}-*`: {description} ({BALLAST_UNIT_NAMES[prefix]}), {n_loops} control loops")
    w("")
    w(f"These units are not connected to {plant.equipment} by any process stream or")
    w("utility other than sharing the same weather. Deciding which tags bear on a")
    w("given question is part of the analysis.")
    return out


def _files_section(cfg: ScenarioConfig, desc: PlantDescription) -> list[str]:
    out: list[str] = []
    w = out.append
    t = cfg.time
    w("| File | Content |")
    w("|---|---|")
    w("| `historian_10s.parquet` | The full record at the 10 s DCS scan, stored the way a plant historian stores it: one row per stored value, with columns `tag`, `timestamp` (UTC), `value` and `quality`. Each tag keeps a value only when it changes by more than its deadband, so every tag has its own timestamps. |")
    w("| `historian_60s.parquet` | The same data on a regular 1-minute grid: a `timestamp` column and one column per tag, filled in by straight-line interpolation between the stored values. Bad-quality samples are blank (`NaN`). Easiest file to open in Excel-style tools or pandas. |")
    w("| `tags.csv` | Tag dictionary: description, units, range, instrument class, role (PV/SP/OP/MODE/IND/CALC), loop, DCS node, transport delay, compression deadband, sensor lag, update period, owning unit. |")
    w("| `PROCESS_DESCRIPTION.md` | This document. |")
    w("| `FAULT_ANSWER_KEY.md` | The abnormal events in the record, their timing and their root causes. |")
    w("")
    w(f"- The record starts at {t.start:%Y-%m-%d %H:%M} plant local time ({t.timezone}) and runs for {t.days:.0f} days.")
    label = desc.timezone_label or t.timezone
    dst = "the period includes the spring daylight-saving change" if _crosses_dst(cfg) else (
        "there is no daylight-saving change in the period"
    )
    w(f"- **All timestamps are UTC.** Plant local time is {label}")
    w(f"  ({t.timezone}); {dst}. Daily")
    w(f"  cycles in {desc.diurnal_sources} follow local time.")
    w(f"- The DCS scans every {t.dt_scan:.0f} s.")
    w(f"- The first {cfg.episodes.baseline_days:.0f} days of the record are normal, steady operation and can be")
    w("  used as a reference for normal behaviour.")
    return out


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

def build_process_description(
    dataset_dir: Path | None = None, plant_name: str | None = None
) -> str:
    cfg = _load_config(dataset_dir) or _default_config(plant_name)
    plant = get_plant(cfg.unit)
    desc = plant.describe(cfg)

    lines: list[str] = []
    w = lines.append
    w(f"# {desc.title}")
    w("")
    w(f"This document describes the {plant.equipment} unit, its control system and its")
    w("instrumentation, and explains how to read the historian data supplied")
    w("with it. It contains what an engineer needs to interpret the data from")
    w("first principles: equipment, physical relationships, control strategy,")
    w("how every tag and calculated value is defined, and how the instruments")
    w("and historian behave normally.")
    w("")
    if desc.intro:
        lines.extend(desc.intro)
        w("")
    w(f"The record covers {cfg.time.days:.0f} days of continuous operation and includes")
    w("several abnormal events. This document describes only the plant and how")
    w("to read its data. It does not say what goes wrong, so it can be given to")
    w("someone working the data blind. The events and their root causes are")
    w("listed in `FAULT_ANSWER_KEY.md`.")
    w("")

    items = [
        (GENERIC_SECTIONS[s], s) if isinstance(s, str) else (s.title, s)
        for s in desc.sections
    ]
    w("## Contents")
    w("")
    for i, (title, _) in enumerate(items, 1):
        w(f"{i}. {title}")
    w("")

    for i, (title, item) in enumerate(items, 1):
        w(f"## {i}. {title}")
        w("")
        if isinstance(item, Section):
            body = item.lines
        elif item == "tags":
            body = _tags_section(plant, desc)
        elif item == "calcs":
            body = _calcs_section(desc)
        elif item == "instruments":
            # Subsection numbers follow the section's actual position.
            body = [
                ln.replace("### 8.", f"### {i}.", 1) if ln.startswith("### 8.") else ln
                for ln in _instruments_section(plant, cfg, desc)
            ]
        elif item == "neighbours":
            body = _neighbours_section(plant, cfg)
        else:
            body = _files_section(cfg, desc)
        lines.extend(body)
        w("")
    return "\n".join(lines)


def write_process_description(dataset_dir: Path) -> Path:
    dataset_dir = Path(dataset_dir)
    out = dataset_dir / "PROCESS_DESCRIPTION.md"
    out.write_text(build_process_description(dataset_dir), encoding="utf-8")
    return out
