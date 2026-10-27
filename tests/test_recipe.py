"""The RCA recipe, the challenge files, scoring, and the pieces added for it."""

import json

import numpy as np
import pandas as pd
import pytest

from historiansim.config.schema import LoopConfig
from historiansim.core.rng import SeedBank
from historiansim.faults.scheduler import build_episode_plan
from historiansim.plants import all_plants, get_plant
from historiansim.scenarios import RECIPES, SCENARIOS, build_scenario

RCA_SCENARIOS = [n for n, s in SCENARIOS.items() if s.get("recipe") == "rca-benchmark"]


@pytest.mark.parametrize("name", RCA_SCENARIOS)
def test_rca_scenarios_pin_unique_causes_components_and_mechanisms(name):
    spec = SCENARIOS[name]
    catalog = get_plant(spec["unit"]).catalog
    causes = [catalog.get(c) for c in spec["cause_ids"]]
    assert len(causes) == RECIPES["rca-benchmark"]["n_faults"]
    for field in ("id", "name", "component"):
        values = [getattr(c, field) for c in causes]
        assert all(values) and len(set(values)) == len(values), (field, values)
    assert len(spec["severities"]) == len(causes)
    assert len({c.symptom for c in causes}) >= 3


@pytest.mark.parametrize("name", RCA_SCENARIOS)
def test_rca_plan_has_clean_baseline_and_no_overlap(name):
    for seed in (1, 7, 42, 123):
        cfg = build_scenario(name, seed=seed)
        assert cfg.time.days == 90 and cfg.time.dt_scan == 10
        plan = build_episode_plan(cfg, SeedBank(seed))
        faults = [e for e in plan.episodes if e.kind == "fault"]
        assert len(faults) == 9 and not plan.background
        ordered = sorted(plan.episodes, key=lambda e: e.onset_s)
        assert ordered[0].onset_s >= cfg.episodes.baseline_days * 86400
        for a, b in zip(ordered, ordered[1:]):
            assert b.onset_s >= a.end_s + 2 * 86400 - 1e-6, (seed, a.id, b.id)


@pytest.mark.parametrize("plant", all_plants(), ids=lambda p: p.name)
def test_every_pinned_cause_has_competitors_left_to_rule_out(plant):
    """A pinned cause alone in its class would be identified by its symptom alone."""
    for name, spec in plant.scenarios.items():
        if spec.get("recipe") != "rca-benchmark":
            continue
        for cid in spec["cause_ids"]:
            cause = plant.catalog.get(cid)
            rivals = [c for c in plant.catalog.causes_for(cause.symptom) if c.id != cid]
            assert len(rivals) >= 1, (name, cid)


def test_ratio_loop_needs_cas_and_both_fields():
    with pytest.raises(ValueError):
        LoopConfig(name="F", pv_source="x", mv_tag="v", kc=1, sp=1, ratio_to="y", ratio=2.0)
    with pytest.raises(ValueError):
        LoopConfig(name="F", pv_source="x", mv_tag="v", kc=1, sp=1, mode="CAS", ratio_to="y")


def test_ratio_station_follows_the_wild_flow():
    """A production-rate step on PO must carry the water with it."""
    from historiansim.core.sim import ConstantDisturbance, simulate
    from historiansim.plants.exothermic_cstr.loops import DESIGN_D, RATIO

    cfg = build_scenario("cstr-clean", profile="quick", seed=1, days=0.5)

    def on_scan(k, t, loops):
        if t >= 3600.0:
            loops["FIC-201"].sp = 2.3

    res = simulate(cfg, ConstantDisturbance(dict(DESIGN_D)), on_scan=on_scan)
    tail = slice(-360, None)
    assert np.mean(res.signals["FI-201"][tail]) == pytest.approx(2.3, rel=1e-3)
    assert np.mean(res.signals["FI-202"][tail]) == pytest.approx(2.3 * RATIO, rel=1e-3)


def _write_truth(tmp_path, episodes):
    (tmp_path / "metadata").mkdir(parents=True)
    truth = {"unit": "exothermic_cstr", "episodes": episodes}
    (tmp_path / "metadata" / "ground_truth.json").write_text(json.dumps(truth))
    for name in ("historian_10s.parquet", "historian_60s.parquet", "tags.csv",
                 "FAULT_ANSWER_KEY.md"):
        (tmp_path / name).write_text("ok")
    (tmp_path / "PROCESS_DESCRIPTION.md").write_text("The jacket removes heat.")
    return tmp_path


def test_audit_flags_a_cause_named_in_the_root(tmp_path):
    from historiansim.validation.recipe import audit_dataset_dir

    ds = _write_truth(tmp_path, [{"episode_id": "EP-001"}])
    checks = {c.name: c for c in audit_dataset_dir(ds)}
    assert checks["no_answer_leak"].passed and checks["dataset_layout"].passed

    (ds / "PROCESS_DESCRIPTION.md").write_text("Watch for jacket heat-transfer fouling here.")
    checks = {c.name: c for c in audit_dataset_dir(ds)}
    assert not checks["no_answer_leak"].passed

    (ds / "notes.txt").write_text("stray")
    checks = {c.name: c for c in audit_dataset_dir(ds)}
    assert not checks["dataset_layout"].passed


def test_scoring_matches_one_to_one_and_penalises_false_positives(tmp_path):
    from historiansim.scoring import score_submission

    key = pd.DataFrame([
        {"event_id": "EP-001", "kind": "fault", "start_utc": "2024-03-20T00:00:00Z",
         "end_utc": "2024-03-25T00:00:00Z", "cause_id": "RC-A1", "cause": "Jacket fouling"},
        {"event_id": "EP-002", "kind": "fault", "start_utc": "2024-04-10T00:00:00Z",
         "end_utc": "2024-04-11T00:00:00Z", "cause_id": "RC-C1", "cause": "Manual"},
        {"event_id": "BEN-001", "kind": "operator_action", "start_utc": "2024-04-01T00:00:00Z",
         "end_utc": "2024-04-02T00:00:00Z", "cause_id": "", "cause": "setpoint"},
    ])
    key.to_csv(tmp_path / "key.csv", index=False)
    sub = pd.DataFrame([
        # matches EP-001 with the right cause
        {"start_utc": "2024-03-21T00:00:00Z", "end_utc": "2024-03-24T00:00:00Z", "kind": "fault",
         "root_cause": "jacket fouled", "evidence_tags": "CALC-UA", "cause_correct": "Y"},
        # second claim on EP-001: a false positive
        {"start_utc": "2024-03-24T12:00:00Z", "end_utc": "2024-03-24T18:00:00Z", "kind": "fault",
         "root_cause": "something", "evidence_tags": "TV-202.POS", "cause_correct": ""},
        # claims the benign event as a fault: a false positive
        {"start_utc": "2024-04-01T00:00:00Z", "end_utc": "2024-04-02T00:00:00Z", "kind": "fault",
         "root_cause": "rate change", "evidence_tags": "FIC-201.SP", "cause_correct": ""},
        # malformed: discarded
        {"start_utc": "nonsense", "end_utc": "2024-04-02T00:00:00Z", "kind": "fault",
         "root_cause": "x", "evidence_tags": "A", "cause_correct": ""},
    ])
    sub.to_csv(tmp_path / "sub.csv", index=False)
    result = score_submission(tmp_path / "key.csv", tmp_path / "sub.csv")
    assert result["detected"] == 1 and result["correct_cause"] == 1
    assert result["false_positives"] == 2 and result["discarded_rows"] == 1
    assert result["missed_events"] == ["EP-002"]
    assert result["points"] == 1 + 2 - 2
