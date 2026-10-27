"""Command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from historiansim import __version__

app = typer.Typer(
    add_completion=False,
    help="Generate realistic continuous process datasets for diagnostic and "
         "fault-detection work.",
)


@app.command("list")
def list_scenarios() -> None:
    """List available plants, scenarios, profiles and recipes."""
    from historiansim.plants import all_plants
    from historiansim.scenarios import PROFILES, RECIPES, SCENARIOS

    typer.echo(f"historiansim {__version__}\n")
    typer.echo("Plants:")
    for plant in all_plants():
        typer.echo(f"  {plant.name:<22} {plant.equipment}: {plant.summary}")
        catalog = plant.catalog
        typer.echo(f"  {'':<22} {len(catalog)} root causes across "
                   f"{len(catalog.symptoms)} symptom classes")

    typer.echo("\nScenarios:")
    for name, spec in SCENARIOS.items():
        first = spec["description"].split(".")[0]
        typer.echo(f"  {name:<22} [{spec['unit']}] {first}.")

    typer.echo("\nProfiles:")
    for name, prof in PROFILES.items():
        typer.echo(
            f"  {name:<22} {prof['days']:>5.0f} d at {prof['dt_scan']:>4.0f} s scan, "
            f"{prof['n_faults']:>2} faults, {prof['ballast']:>3} ballast tags"
        )
        typer.echo(f"  {'':<22} {prof['note']}")

    typer.echo("\nRecipes:")
    for name, recipe in RECIPES.items():
        typer.echo(f"  {name:<22} {recipe['note']}")


@app.command()
def describe(scenario: str) -> None:
    """Show a scenario's symptom classes and competing root causes."""
    from historiansim.scenarios import SCENARIOS, describe_scenario

    if scenario not in SCENARIOS:
        typer.echo(f"unknown scenario {scenario!r}. Available: {sorted(SCENARIOS)}")
        raise typer.Exit(1)
    typer.echo(describe_scenario(scenario))


@app.command()
def generate(
    scenario: str = typer.Argument("exchanger-fouling"),
    profile: str = typer.Option("standard", help="quick, standard or campaign."),
    seed: int = typer.Option(42, help="A config plus this seed reproduces the dataset."),
    out: Path = typer.Option(Path("output"), help="Output directory."),
    days: float = typer.Option(None, help="Override the profile duration."),
    scan: float = typer.Option(None, "--scan", help="Override the DCS scan rate, seconds."),
    ballast: int = typer.Option(None, help="Override the ballast tag count."),
    faults: int = typer.Option(None, "--faults", help="Override the episode count."),
    difficulty: str = typer.Option(
        None, help="easy, standard or hard. 'hard' also withholds discriminating tags."
    ),
    resample: float = typer.Option(60.0, help="Period for the regular-grid export, seconds."),
    no_fault: bool = typer.Option(
        False, "--no-fault",
        help="Generate the matched fault-free twin: same seed, same weather, no faults.",
    ),
    validate: bool = typer.Option(True, help="Run the validation battery afterwards."),
) -> None:
    """Generate a dataset."""
    from historiansim.pipeline import generate as run_generate
    from historiansim.pipeline import write_dataset
    from historiansim.scenarios import build_scenario
    from historiansim.validation import format_report, run_battery
    from historiansim.validation.report import format_difficulty

    overrides = {
        "days": days, "dt_scan": scan, "ballast": ballast,
        "n_faults": 0 if no_fault else faults, "difficulty": difficulty,
    }
    overrides = {k: v for k, v in overrides.items() if v is not None}

    try:
        cfg = build_scenario(scenario, profile=profile, seed=seed, **overrides)
    except KeyError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)

    suffix = "-nofault" if no_fault else ""
    target = out / f"{scenario}-{profile}-s{seed}{suffix}"
    typer.echo(f"historiansim {__version__}: {scenario} / {profile} / seed {seed}")
    typer.echo(f"{cfg.time.days:.0f} days at {cfg.time.dt_scan:.0f} s scan "
               f"= {cfg.time.n_steps:,} scans\n")

    dataset = run_generate(cfg, progress=True)
    write_dataset(dataset, target, resample_s=resample)

    typer.echo(f"\nwritten to {target}")
    total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    typer.echo(f"{len(dataset.tags)} tags "
               f"({dataset.ballast_count} ballast), {total / 1e6:.0f} MB")

    if not no_fault:
        typer.echo(format_difficulty(dataset.manifest))
    if validate:
        from historiansim.validation.recipe import audit_dataset_dir

        checks = run_battery(dataset) + audit_dataset_dir(target)
        typer.echo(format_report(checks))
        if any(not c.passed and c.severity == "error" for c in checks):
            raise typer.Exit(1)


@app.command()
def validate(dataset_dir: Path) -> None:
    """Re-run the validation battery by regenerating from a dataset's manifest.

    Regeneration rather than inspection: most checks need the true history and
    the no-fault twin, and neither is shipped with the dataset. The recorded
    config and seed reproduce both exactly, which is the point of storing them.
    """
    from historiansim.config.schema import ScenarioConfig
    from historiansim.pipeline import generate as run_generate
    from historiansim.validation import format_report, run_battery

    from historiansim.pipeline import manifest_path as _manifest_path

    manifest_path = _manifest_path(dataset_dir)
    if not manifest_path.exists():
        typer.echo(f"no manifest.json in {dataset_dir}")
        raise typer.Exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cfg = ScenarioConfig.model_validate(manifest["config"])
    typer.echo(f"regenerating {cfg.name} (seed {cfg.seed}) to validate...")

    checks = run_battery(run_generate(cfg))
    typer.echo(format_report(checks, verbose=True))
    if any(not c.passed and c.severity == "error" for c in checks):
        raise typer.Exit(1)


@app.command()
def report(dataset_dir: Path) -> None:
    """Print the difficulty summary from a dataset's answer key."""
    from historiansim.layout import ground_truth_path
    from historiansim.validation.report import format_difficulty

    path = ground_truth_path(dataset_dir)
    if not path.exists():
        typer.echo(f"no metadata/ground_truth.json in {dataset_dir}")
        raise typer.Exit(1)

    manifest = json.loads(path.read_text(encoding="utf-8"))
    typer.echo(format_difficulty(manifest))

    typer.echo("\nEpisodes and their confusion sets")
    typer.echo("=" * 72)
    for ep in manifest["episodes"]:
        if ep["class"] != "fault":
            continue
        typer.echo(f"\n  {ep['episode_id']}  {ep.get('true_root_cause_label', '')}")
        typer.echo(f"    symptom     {ep.get('symptom_label', '-')}")
        typer.echo(f"    competing   {', '.join(ep.get('candidate_causes', []))}")
        for item in ep.get("discriminating_evidence", []):
            mark = " " if item["available"] else "*"
            typer.echo(f"    {mark} {item['tag']:<16} {item['expected']:<8} {item['note']}")
    typer.echo("\n  * = withheld from this dataset by the difficulty setting")


@app.command()
def summarise(
    dataset_dir: Path,
    out: Path = typer.Option(None, help="Write elsewhere instead of FAULT_ANSWER_KEY.md."),
) -> None:
    """Re-render FAULT_ANSWER_KEY.md from the dataset's metadata."""
    from historiansim.layout import ground_truth_path
    from historiansim.summary import build_summary, write_summary

    if not ground_truth_path(dataset_dir).exists():
        typer.echo(f"no metadata/ground_truth.json in {dataset_dir}")
        raise typer.Exit(1)

    if out is None:
        target = write_summary(dataset_dir)
    else:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(build_summary(dataset_dir), encoding="utf-8")
    typer.echo(f"wrote {target}")


@app.command("describe-process")
def describe_process(
    dataset_dir: Path = typer.Argument(None, help="Dataset to describe. Optional."),
    plant: str = typer.Option(None, help="Plant to describe when no dataset is given."),
    out: Path = typer.Option(None, help="Write to a file instead of stdout."),
) -> None:
    """Print or write the process description for the unit.

    Describes the plant only (equipment, control philosophy, instrumentation)
    and reveals nothing about faults.
    """
    from historiansim.process_doc import build_process_description

    text = build_process_description(dataset_dir, plant_name=plant)
    if out is None:
        typer.echo(text)
    else:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}")


@app.command()
def score(
    dataset_dir: Path,
    submission: Path,
) -> None:
    """Score a challenge submission against the original dataset's answer key.

    Root causes are free text: add a `cause_correct` column (Y/N) to the
    submission for each matched claim, then score again for the final total.
    """
    import pandas as pd

    from historiansim.challenge import load_scoring_key
    from historiansim.layout import ground_truth_path
    from historiansim.scoring import score_submission

    if not ground_truth_path(dataset_dir).exists():
        typer.echo(f"no metadata/ground_truth.json in {dataset_dir}")
        raise typer.Exit(1)
    result = score_submission(load_scoring_key(dataset_dir), submission)
    detail = result.pop("detail")
    for k, v in result.items():
        typer.echo(f"{k:22s} {v}")
    if len(detail):
        typer.echo("")
        with pd.option_context("display.max_colwidth", 70, "display.width", 200):
            typer.echo(detail.to_string(index=False))


@app.command("make-challenge")
def make_challenge_cmd(
    dataset_dir: Path,
    out: Path = typer.Option(None, help="Challenge folder. Defaults to <dataset>-challenge."),
) -> None:
    """Copy a dataset into a blind-test folder, without the answer key.

    Adds CHALLENGE.md (the task and scoring rules) and submission_template.csv.
    Grade submissions with `historiansim score <original dataset> <submission.csv>`.
    """
    from historiansim.challenge import make_challenge

    dataset_dir = Path(dataset_dir)
    target = make_challenge(dataset_dir, out or dataset_dir.parent / f"{dataset_dir.name}-challenge")
    typer.echo(f"wrote {target}")


@app.command()
def audit(dataset_dir: Path) -> None:
    """Check a written dataset folder: documented files only, no answers in the root."""
    from historiansim.validation import format_report
    from historiansim.validation.recipe import audit_dataset_dir

    checks = audit_dataset_dir(dataset_dir)
    typer.echo(format_report(checks))
    if any(not c.passed for c in checks):
        raise typer.Exit(1)


@app.command("check-plant")
def check_plant(
    plant: str,
    stage: int = typer.Option(None, help="Run only this stage (1-5)."),
    seed: int = typer.Option(7),
) -> None:
    """Staged acceptance gates for a plant: physics first, noise last.

    1 steady state closes, 2 setpoint steps settle, 3 each cause alone moves
    its evidence the declared way, 4 candidates are distinguishable and every
    catalog reference resolves, 5 a quick-profile dataset passes the battery.
    """
    from historiansim.validation.plant_checks import run_plant_checks

    ok = run_plant_checks(plant, stages=None if stage is None else [stage], seed=seed,
                          echo=typer.echo)
    if not ok:
        raise typer.Exit(1)


@app.command()
def plot(
    dataset_dir: Path,
    tags: str = typer.Option(None, help="Comma-separated tags to plot."),
    episode: str = typer.Option(None, help="Plot an episode's evidence tags, e.g. EP-003."),
    days: str = typer.Option(None, help="Window as start,end in days from the record start."),
    out: Path = typer.Option(None, help="PNG path. Defaults to <dataset>-plots/ next to the dataset."),
) -> None:
    """Trend tags from a dataset's 60 s grid to a PNG, saved beside the dataset."""
    from historiansim.plotting import plot_dataset

    window = tuple(float(x) for x in days.split(",")) if days else None
    target = plot_dataset(
        dataset_dir,
        tags=[t.strip() for t in tags.split(",")] if tags else None,
        episode=episode, window_days=window, out=out,
    )
    typer.echo(f"wrote {target}")


@app.command("new-plant")
def new_plant(
    name: str,
    equipment: str = typer.Option(..., help="Equipment designation, e.g. R-201."),
) -> None:
    """Scaffold plants/<name>/ from the plant template."""
    from historiansim.scaffold import scaffold_plant

    target = scaffold_plant(name, equipment)
    typer.echo(f"created {target}")
    typer.echo("next: fill in DESIGN.md, then model.py, tags.py, loops.py, faults.py, "
               "description.py; run `historiansim check-plant " + name + "` stage by stage")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
