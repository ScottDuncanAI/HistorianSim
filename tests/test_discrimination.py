"""The reason this simulator exists.

Six root causes produce the same headline symptom -- the steam valve slowly
opening while tank temperature sits perfectly on setpoint. A dataset where that
symptom maps to one cause teaches an agent nothing. These tests assert that all
six are genuinely present, genuinely confusable, and genuinely separable by
querying the right *other* tag.

If a change to the physics collapses two of these signatures together, or lets
tank temperature give the fault away, this file should fail.
"""

import numpy as np
import pytest

from historiansim.core.sim import ConstantDisturbance, simulate
from tests.conftest import (
    DESIGN_D,
    FEED,
    RampDisturbance,
    RampParam,
    tank_scenario,
)

DAYS = 0.6
ONSET = DAYS * 86400 / 3.0
BASELINE_IDX = int(ONSET / 10.0) - 30   # a little before onset


def run_case(fault=None, disturbance=None):
    cfg = tank_scenario(days=DAYS)
    dist = disturbance or ConstantDisturbance(DESIGN_D)
    res = simulate(cfg, dist, faults=[fault] if fault else [])
    return res


def delta(res, tag: str) -> float:
    """Change in a tag from just before onset to the end of the run."""
    values = res.series(tag)
    return float(values[-1] - values[BASELINE_IDX])


# -- the six candidate causes, each at a severity that opens the valve ------

@pytest.fixture(scope="module")
def cases():
    from historiansim.plants.heated_stirred_tank.model import HeatedStirredTank
    p = HeatedStirredTank().params
    return {
        "A1_fouling": run_case(
            fault=RampParam("fouling_factor", p["fouling_factor"], 0.75, ONSET)),
        "A2_feed_creep": run_case(
            disturbance=RampDisturbance("feed_flow", FEED * 1.18, ONSET)),
        "A3_header_pressure": run_case(
            disturbance=RampDisturbance("steam_header_P", 4.2, ONSET)),
        "A4_feed_temp": run_case(
            disturbance=RampDisturbance("feed_temp", 16.0, ONSET)),
        "A5_condensate_backup": run_case(
            fault=RampParam("flooded_fraction", 0.0, 0.22, ONSET)),
        "A6_trap_blowthrough": run_case(
            fault=RampParam("blowthrough", 0.0, 0.30, ONSET)),
    }


def test_temperature_masks_every_cause(cases):
    """The single most important property of the dataset.

    An agent that watches only the controlled variable must learn nothing. If
    this fails, the whole premise -- 'look at the manipulated variable' -- is
    gone, and every downstream result is easier than it should be.
    """
    for name, res in cases.items():
        assert abs(delta(res, "TI-101")) < 0.05, (
            f"{name} moved tank temperature by {delta(res, 'TI-101'):.4f} K; "
            "the controller should have absorbed it"
        )


@pytest.mark.parametrize(
    "name", ["A1_fouling", "A2_feed_creep", "A3_header_pressure",
             "A4_feed_temp", "A5_condensate_backup"],
)
def test_valve_opens_for_every_heat_transfer_cause(cases, name):
    """All five share the headline symptom, so none is identifiable from it."""
    assert delta(cases[name], "TV-101") > 0.02


def test_fouling_moves_nothing_but_the_valve(cases):
    """Fouling is a diagnosis of exclusion, which is what makes it hard.

    With a steam-flow cascade the inner loop absorbs the lost heat transfer
    completely: flow returns to setpoint, duty is unchanged, temperature never
    moves. The valve position is the only evidence in the entire dataset.
    """
    res = cases["A1_fouling"]
    assert delta(res, "TV-101") > 0.05
    for tag in ("FI-101", "TI-100", "PI-201", "TI-202", "CALC-DUTY", "TIC-101.OP"):
        assert abs(delta(res, tag)) < 0.05, f"{tag} moved under pure fouling"


def test_condensate_backup_is_fouling_plus_one_tag(cases):
    """A1 and A5 are the crux: identical everywhere except condensate temperature.

    Both lose coil area, both open the valve, both leave every flow and
    pressure untouched. Only TI-202 separates them, and it moves *down* because
    stagnant condensate subcools.
    """
    fouling, backup = cases["A1_fouling"], cases["A5_condensate_backup"]

    for tag in ("FI-101", "TI-100", "PI-201", "CALC-DUTY"):
        assert abs(delta(fouling, tag)) < 0.05
        assert abs(delta(backup, tag)) < 0.05

    assert abs(delta(fouling, "TI-202")) < 0.05, "fouling should not touch condensate temp"
    assert delta(backup, "TI-202") < -3.0, "backup must subcool the condensate"


def test_feed_creep_is_identified_by_feed_flow(cases):
    res = cases["A2_feed_creep"]
    assert delta(res, "FI-101") > 1.0
    assert delta(res, "FI-201") > 50.0        # more load, more steam
    assert abs(delta(res, "TI-100")) < 0.05   # but the feed is not colder


def test_feed_temperature_decline_is_identified_by_feed_temp(cases):
    res = cases["A4_feed_temp"]
    assert delta(res, "TI-100") < -3.0
    assert delta(res, "FI-201") > 50.0
    assert abs(delta(res, "FI-101")) < 0.05   # and the feed rate is unchanged


def test_feed_creep_and_feed_temp_are_confusable_on_energy_alone(cases):
    """Two causes with the same energy signature, separable only upstream.

    Both raise steam demand by the same amount. An agent reasoning purely on
    the heat balance cannot tell them apart; it has to ask which upstream
    variable actually moved.
    """
    creep, cold = cases["A2_feed_creep"], cases["A4_feed_temp"]
    assert delta(creep, "FI-201") == pytest.approx(delta(cold, "FI-201"), rel=0.05)
    assert delta(creep, "CALC-DUTY") == pytest.approx(delta(cold, "CALC-DUTY"), rel=0.05)


def test_header_pressure_decline_is_identified_by_pressure(cases):
    res = cases["A3_header_pressure"]
    assert delta(res, "PI-201") < -1.0
    # Lower header pressure means lower saturation temperature, which drags the
    # condensate return down with it -- so TI-202 alone does not isolate the
    # condensate-backup case. Two tags are needed, which is the point.
    assert delta(res, "TI-202") < -5.0
    assert abs(delta(res, "FI-101")) < 0.05


def test_blowthrough_wastes_steam_without_delivering_heat(cases):
    """A failed-open trap is the one cause that does not open the valve.

    Live steam escapes to the condensate system, so indicated flow jumps while
    duty is flat and the condensate return climbs toward saturation. Opposite
    direction on TI-202 from condensate backup.
    """
    res = cases["A6_trap_blowthrough"]
    assert delta(res, "FI-201") > 200.0
    assert abs(delta(res, "CALC-DUTY")) < 1.0
    assert delta(res, "TI-202") > 0.5
    assert delta(res, "TI-202") * -1 < 0     # rises, unlike backup


def test_every_cause_has_a_distinct_evidence_fingerprint(cases):
    """No two causes may share a signature across the discriminating tags.

    This is the guard against a physics change quietly collapsing two competing
    explanations into one, which would make the dataset unsolvable rather than
    merely hard.
    """
    tags = ["TV-101", "FI-201", "PI-201", "FI-101", "TI-100", "TI-202", "CALC-DUTY"]

    def fingerprint(res):
        # Sign pattern with a deadband, which is how a diagnostician reads a trend.
        out = []
        for tag in tags:
            scale = max(abs(res.series(tag)[BASELINE_IDX]), 1.0)
            rel = delta(res, tag) / scale
            out.append(0 if abs(rel) < 2e-3 else int(np.sign(rel)))
        return tuple(out)

    prints = {name: fingerprint(res) for name, res in cases.items()}
    for a in prints:
        for b in prints:
            if a < b:
                assert prints[a] != prints[b], (
                    f"{a} and {b} are indistinguishable: {prints[a]}"
                )
