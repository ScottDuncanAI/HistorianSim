"""TK-101: a steam-heated agitated hold tank under cascade control.

The reference plant, and the one HistorianRCA-style datasets were first built
on. Its pieces:

* ``model.py`` -- the physics (:class:`HeatedStirredTank`)
* ``tags.py`` -- historian tags and the DCS calculations
* ``loops.py`` -- control loops and disturbance channels
* ``faults.py`` -- the fault catalog, by symptom class
* ``description.py`` -- the plant sections of ``PROCESS_DESCRIPTION.md``

and this file, which wires them into a :class:`~historiansim.plants.Plant`.
"""

from __future__ import annotations

from historiansim.faults.base import ControlFault, Exponential, ProcessFault
from historiansim.plants.base import BenignEvent, Plant
from historiansim.plants.heated_stirred_tank.description import describe
from historiansim.plants.heated_stirred_tank.faults import CATALOG
from historiansim.plants.heated_stirred_tank.loops import tank_channels, tank_loops
from historiansim.plants.heated_stirred_tank.model import HeatedStirredTank
from historiansim.plants.heated_stirred_tank.tags import recompute_dcs_calculations, tank_tags

__all__ = ["PLANT", "HeatedStirredTank"]

DAY = 86400.0


def _background_fouling(baseline_end_s: float, total_s: float):
    """Slow coil fouling under the whole campaign, reset at one cleaning.

    Only for campaigns long enough to show a cycle; the degradation state then
    differs from one episode to the next, as it does on a real plant.
    """
    if total_s <= 30 * DAY:
        return [], ()
    clean_at = total_s * 0.72
    fault = ProcessFault(
        id="DEG-001", param="fouling_factor", magnitude=0.16,
        onset_s=baseline_end_s + 6 * DAY,
        profile=Exponential(tau_s=18 * DAY), mode="scale",
        resets=(clean_at,), label="background coil fouling",
    )
    return [fault], (clean_at,)


BENIGN_EVENTS = {
    "temperature_sp": BenignEvent(
        kind="temperature_sp",
        duration_days=(0.75, 1.5),
        build=lambda bid, onset, end: ControlFault(
            id=bid, loop="TIC-101", action="setpoint", onset_s=onset, value=78.0,
            end_s=end, label="planned product temperature change",
        ),
        note="operator raised the temperature setpoint on purpose",
        why=(
            "`TIC-101.SP` was stepped from 75 to 78 degC by an operator and later returned. "
            "Temperature, steam demand and purity all respond as the control strategy says they "
            "should; nothing is abnormal. A method that flags this as a fault is reacting to an "
            "intended change."
        ),
    ),
    "level_sp": BenignEvent(
        kind="level_sp",
        duration_days=(1.0, 2.0),
        build=lambda bid, onset, end: ControlFault(
            id=bid, loop="LIC-101", action="setpoint", onset_s=onset, value=2.3,
            end_s=end, label="planned inventory increase",
        ),
        note="level setpoint raised ahead of a downstream outage",
        why=(
            "`LIC-101.SP` was stepped from 2.0 to 2.3 m by an operator and later returned. Level, "
            "outlet valve and product flow respond as expected and both level transmitters agree."
        ),
    ),
    "flow_manual": BenignEvent(
        kind="flow_manual",
        duration_days=(2.0 / 24.0, 6.0 / 24.0),
        build=lambda bid, onset, end: ControlFault(
            id=bid, loop="FIC-201", action="manual", onset_s=onset, value=0.0,
            end_s=end, label="steam flow loop in manual for instrument calibration",
        ),
        note="technician calibrated the steam flow transmitter",
        why=(
            "FIC-201 was put in manual for a few hours while its transmitter was calibrated, then "
            "returned to cascade. The steam valve holds still and bulk temperature drifts a little "
            "with the load; nothing is wrong with the plant."
        ),
    ),
}


SCENARIOS = {
    "tank-rca": {
        "recipe": "rca-benchmark",
        # Neutral on purpose: this string is written into the shipped manifest.
        "description": "TK-101 heated stirred tank, 90 day historian extract.",
        # Nine causes on nine different components, covering all four
        # symptom classes. Chosen to share no cause with the published
        # HistorianRCA benchmark built on this same unit.
        "cause_ids": [
            "RC-A2",   # S1  upstream feed rate creep
            "RC-B1",   # S2  LV-101 stiction
            "RC-D1",   # S4  steam flow transmitter drift
            "RC-C4",   # S3  fouling past the compensation range
            "RC-A4",   # S1  cold feed from upstream
            "RC-D2",   # S4  steam trap failed open
            "RC-B2",   # S2  level setpoint moved into a higher-gain region
            "RC-C1",   # S3  steam supply loss
            "RC-D3",   # S4  feed flow transmitter drift
        ],
        "severities": [
            "moderate", "moderate", "subtle", "moderate", "moderate",
            "moderate", "obvious", "obvious", "subtle",
        ],
        # Not the level setpoint move: RC-B2 is a level setpoint change too,
        # and two of them would make the benign one a trick question.
        "benign_kinds": ["temperature_sp", "flow_manual"],
    },
    "exchanger-fouling": {
        "description": (
            "Heated stirred tank with a steam coil under cascade control. The "
            "headline problem: six root causes produce an identical first "
            "symptom: the steam valve misbehaving while temperature sits "
            "perfectly on setpoint. Discrimination, not detection."
        ),
        "symptom_weights": {"S1": 0.55, "S2": 0.15, "S3": 0.10, "S4": 0.20},
        # Pinned rather than sampled: nine distinct causes spanning all four
        # symptom classes, so no label can be won by guessing the mode and the
        # mix is identical across seeds. Ordered to interleave the classes and
        # to close on RC-C4, which is the end state of an S1 nobody acted on.
        # RC-A6 and RC-B1 are the same failure -- valve stiction -- on
        # different valves, so localisation is tested and not just mechanism.
        "cause_ids": [
            "RC-A1",   # S1  coil fouling
            "RC-D2",   # S4  steam trap failed open
            "RC-A5",   # S1  condensate backup in the coil
            "RC-B1",   # S2  LV-101 stiction
            "RC-A3",   # S1  steam header pressure decline
            "RC-D4",   # S4  product flow transmitter zero shift
            "RC-A6",   # S1  TV-101 stiction
            "RC-B4",   # S2  level DP cell impulse line plugging
            "RC-C4",   # S3  fouling past the compensation range
        ],
    },
    "tank-mixed-faults": {
        "description": (
            "The same unit with the fault catalog sampled evenly across all "
            "four symptom classes. A broader benchmark than exchanger-fouling, "
            "and the better choice for training a multi-class detector."
        ),
        "symptom_weights": {"S1": 0.3, "S2": 0.25, "S3": 0.2, "S4": 0.25},
    },
    "tank-clean": {
        "description": (
            "No injected faults at all: only weather, degradation and normal "
            "operator activity. Nothing else measures a false positive rate, "
            "and an agent that confidently finds a root cause in clean data is "
            "worse than useless in a control room."
        ),
        "symptom_weights": {"S1": 1.0},
        "n_faults": 0,
        "n_benign": 4,
    },
}


PLANT = Plant(
    name="heated_stirred_tank",
    equipment="TK-101",
    summary="Steam-heated agitated hold tank, temperature cascaded onto steam flow, plus level",
    unit_cls=HeatedStirredTank,
    tags=tank_tags,
    loops=tank_loops,
    channels=tank_channels,
    catalog=CATALOG,
    describe=describe,
    scenarios=SCENARIOS,
    recompute_calcs=recompute_dcs_calculations,
    benign_events=BENIGN_EVENTS,
    default_benign_kinds=("temperature_sp", "level_sp", "flow_manual"),
    background_degradation=_background_fouling,
    # TI-202 is the single tag separating coil fouling from condensate backup,
    # so withholding it is the sharpest available increase in difficulty.
    hard_mode_withheld=("TI-202", "LI-102"),
    mass_balance=(("FI-101",), ("FI-102",)),
    background_notes=(
        "slow transmitter calibration drift (for example the long-run `CALC-MBAL` offset "
        "wanders by a few tenths of a m3/h over the record)"
    ),
)
