"""End-to-end generation, and the invariants the whole dataset rests on.

These run a real (short) generation, so they are the slowest tests here. They
are also the ones that would catch a layer being wired up wrongly, which unit
tests on each layer cannot.
"""

import json

import numpy as np
import pytest

from historiansim.pipeline import generate, write_dataset
from historiansim.scenarios import SCENARIOS, build_scenario
from historiansim.validation import run_battery


@pytest.fixture(scope="module")
def dataset():
    cfg = build_scenario("exchanger-fouling", profile="quick", seed=11)
    return generate(cfg)


def test_generation_produces_every_layer(dataset):
    assert dataset.truth.n > 0
    assert dataset.measured.n == dataset.truth.n
    assert len(dataset.tags) > 40
    assert dataset.manifest["episodes"]


def test_ballast_outnumbers_nothing_important(dataset):
    """Difficulty comes from the ratio of relevant to irrelevant tags."""
    real = [t for t, s in dataset.measured.specs.items() if not s.ballast]
    ballast = [t for t, s in dataset.measured.specs.items() if s.ballast]
    assert len(ballast) >= len(real) * 0.5


def test_answer_key_names_tags_that_exist(dataset):
    """A discrimination matrix pointing at absent tags is unusable.

    This exact defect shipped once: the catalog used internal signal names
    while the export used historian tag names.
    """
    tags = set(dataset.measured.specs)
    for episode in dataset.manifest["episodes"]:
        for item in episode.get("discriminating_evidence", []):
            if item["available"]:
                assert item["tag"] in tags, f"{item['tag']} is not in the dataset"


def test_every_fault_episode_has_competing_candidates(dataset):
    """The premise of the whole dataset: identifying the symptom narrows little."""
    for episode in dataset.manifest["episodes"]:
        if episode["class"] != "fault":
            continue
        assert len(episode["candidate_causes"]) >= 4
        assert episode["true_root_cause"] in episode["candidate_causes"]


def test_evidence_rules_out_other_candidates(dataset):
    """Evidence has to eliminate something, or it is not discriminating."""
    for episode in dataset.manifest["episodes"]:
        if episode["class"] != "fault":
            continue
        ruled_out = {
            cause
            for item in episode["discriminating_evidence"]
            for cause in item["rules_out"]
        }
        others = set(episode["candidate_causes"]) - {episode["true_root_cause"]}
        assert ruled_out & others, f"{episode['episode_id']} eliminates nothing"


def test_validation_battery_passes(dataset):
    failures = [
        c for c in run_battery(dataset) if not c.passed and c.severity == "error"
    ]
    assert not failures, [f"{c.name}: {c.detail}" for c in failures]


@pytest.mark.slow
def test_battery_passes_on_a_campaign_long_enough_to_assess_solvability():
    """The quick profile's one-day episodes are too short to judge solvability.

    This runs a 30 day campaign so the check actually has something to assess,
    rather than passing vacuously.
    """
    cfg = build_scenario("exchanger-fouling", profile="standard", seed=21, days=30.0)
    cfg.episodes.n_faults = 4
    cfg.episodes.baseline_days = 6.0
    cfg.ballast_tags = 24

    checks = {c.name: c for c in run_battery(generate(cfg))}
    assert checks["solvable"].data["checked"] > 0, "nothing was assessable"
    failures = [c for c in checks.values() if not c.passed and c.severity == "error"]
    assert not failures, [f"{c.name}: {c.detail}" for c in failures]


def test_same_seed_reproduces_the_dataset():
    cfg = build_scenario("exchanger-fouling", profile="quick", seed=5)
    a, b = generate(cfg), generate(cfg)
    for tag in a.measured.values:
        assert np.array_equal(a.measured.values[tag], b.measured.values[tag]), tag


def test_different_seed_changes_the_dataset():
    a = generate(build_scenario("exchanger-fouling", profile="quick", seed=5))
    b = generate(build_scenario("exchanger-fouling", profile="quick", seed=6))
    assert not np.allclose(
        a.measured.values["TIC-101.PV"], b.measured.values["TIC-101.PV"]
    )


def test_clean_scenario_has_no_faults():
    """Nothing else measures a false positive rate."""
    cfg = build_scenario("tank-clean", profile="quick", seed=3)
    ds = generate(cfg)
    assert not [e for e in ds.manifest["episodes"] if e["class"] == "fault"]
    assert [e for e in ds.manifest["episodes"] if e["class"] == "benign"]


def test_hard_difficulty_withholds_discriminating_tags():
    """On hard, the tag separating fouling from condensate backup is gone."""
    cfg = build_scenario("exchanger-fouling", profile="quick", seed=3,
                         difficulty="hard")
    ds = generate(cfg)
    assert "TI-202" in ds.plan.withheld_tags
    assert "TI-202" not in ds.measured.specs


def test_write_dataset_emits_the_documented_layout(dataset, tmp_path):
    from historiansim import layout

    out = write_dataset(dataset, tmp_path / "ds")
    assert {p.name for p in out.iterdir() if p.is_file()} == set(layout.DATASET_FILES)
    for name in ("ground_truth.json", "manifest.json", "labels_60s.parquet"):
        assert (out / "metadata" / name).exists(), f"missing metadata/{name}"
    key = (out / layout.ANSWER_KEY).read_text(encoding="utf-8")
    assert "## Events (UTC)" in key and "EP-001" in key


def test_make_challenge_leaves_the_answers_behind(dataset, tmp_path):
    from historiansim.challenge import make_challenge
    from historiansim.validation.recipe import audit_dataset_dir

    out = write_dataset(dataset, tmp_path / "ds2")
    challenge = make_challenge(out, tmp_path / "ch")
    names = {p.name for p in challenge.iterdir()}
    assert names == {"historian_10s.parquet", "historian_60s.parquet", "tags.csv",
                     "PROCESS_DESCRIPTION.md", "CHALLENGE.md", "submission_template.csv"}
    assert "FAULT_ANSWER_KEY" not in (challenge / "PROCESS_DESCRIPTION.md").read_text(encoding="utf-8")
    assert all(c.passed for c in audit_dataset_dir(out))


def test_manifest_round_trips_to_a_config(dataset, tmp_path):
    """The recorded config plus seed must reproduce the dataset exactly."""
    from historiansim.config.schema import ScenarioConfig

    out = write_dataset(dataset, tmp_path / "ds3")
    manifest = json.loads((out / "metadata" / "manifest.json").read_text(encoding="utf-8"))
    restored = ScenarioConfig.model_validate(manifest["config"])
    again = generate(restored)
    assert np.array_equal(
        again.measured.values["TIC-101.PV"], dataset.measured.values["TIC-101.PV"]
    )


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_shipped_scenario_builds(name):
    cfg = build_scenario(name, profile="quick", seed=1)
    assert cfg.loops and cfg.time.n_steps > 0


def test_manual_episode_returns_a_cascade_slave_to_cas():
    """A loop taken to manual must come back in the mode it left, not AUTO."""
    from historiansim.faults.base import ControlFault

    class Loop:
        mode, out, sp = "CAS", 0.5, 1.0

        def set_mode(self, mode, output=None):
            self.mode = mode

    loop = Loop()
    fault = ControlFault(id="X", loop="FIC-201", action="manual", onset_s=0.0, end_s=10.0)
    fault.apply_controls(5.0, {"FIC-201": loop})
    assert loop.mode == "MAN"
    fault.apply_controls(20.0, {"FIC-201": loop})
    assert loop.mode == "CAS"


def test_controllers_read_their_transmitters_calibration_drift():
    """A loop holds its own drifting reading at setpoint, not the true value.

    Otherwise the historised PV walks off setpoint under integral action.
    The independent indicator on the same signal (LI-102) must not leak in.
    """
    from historiansim.core.rng import SeedBank
    from historiansim.measurement.instrument import (
        INSTRUMENT_CLASSES,
        calibration_drift,
        drift_direction,
    )
    from historiansim.pipeline import _build_sensor_fn

    cfg = build_scenario("exchanger-fouling", profile="quick", seed=3)
    n, dt = 2000, cfg.time.dt_scan
    seeds = SeedBank(cfg.seed)
    sensor_fn = _build_sensor_fn(cfg, [], n, dt, seeds)
    assert sensor_fn is not None

    k = n - 1
    true = {"TI-101": 75.0, "FI-201": 1500.0, "LI-101": 2.0}
    seen = sensor_fn(true, k)
    for tag, signal, cls, span in [
        ("TIC-101.PV", "TI-101", "temperature_slow", (0, 120)),
        ("FIC-201.PV", "FI-201", "flow", (0, 3000)),
        ("LIC-101.PV", "LI-101", "level", (0, 4)),
    ]:
        drift = calibration_drift(
            INSTRUMENT_CLASSES[cls], span, n, dt, drift_direction(seeds, tag)
        )[k]
        assert drift != 0.0
        assert seen[signal] - true[signal] == pytest.approx(drift), tag
