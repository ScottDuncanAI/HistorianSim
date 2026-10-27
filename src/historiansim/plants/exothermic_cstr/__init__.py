"""R-201: jacketed CSTR making propylene glycol, under cascade and ratio control.

The second plant, built from ``DESIGN.md`` to prove the engine generalises:
cooled rather than heated, Arrhenius feedback on temperature, a composition
analyzer, and ratioed feeds. Pieces:

* ``model.py`` -- the physics (:class:`ExothermicCSTR`)
* ``tags.py`` -- historian tags and the DCS calculations
* ``loops.py`` -- control loops and disturbance channels
* ``faults.py`` -- the fault catalog, by symptom class
* ``description.py`` -- the plant sections of ``PROCESS_DESCRIPTION.md``
"""

from __future__ import annotations

from historiansim.faults.base import ControlFault
from historiansim.plants.base import BenignEvent, Plant
from historiansim.plants.exothermic_cstr.description import describe
from historiansim.plants.exothermic_cstr.faults import CATALOG
from historiansim.plants.exothermic_cstr.loops import cstr_channels, cstr_loops
from historiansim.plants.exothermic_cstr.model import ExothermicCSTR
from historiansim.plants.exothermic_cstr.tags import cstr_tags, recompute_dcs_calculations

__all__ = ["PLANT", "ExothermicCSTR"]


BENIGN_EVENTS = {
    "temperature_sp": BenignEvent(
        kind="temperature_sp",
        duration_days=(0.75, 1.5),
        build=lambda bid, onset, end: ControlFault(
            id=bid, loop="TIC-201", action="setpoint", onset_s=onset, value=63.0,
            end_s=end, label="planned reactor temperature increase",
        ),
        note="operator raised the reactor temperature setpoint on purpose",
        why=(
            "`TIC-201.SP` was stepped from 60 to 63 degC by an operator and later returned. "
            "The jacket runs colder and the cooling valve opens to remove the extra reaction "
            "heat, and residual PO falls as conversion rises, all as the physics "
            "says it should. Nothing is abnormal."
        ),
    ),
    "rate_change": BenignEvent(
        kind="rate_change",
        duration_days=(1.0, 2.0),
        build=lambda bid, onset, end: ControlFault(
            id=bid, loop="FIC-201", action="setpoint", onset_s=onset, value=2.3,
            end_s=end, label="planned production rate increase",
        ),
        note="operator raised the production rate on purpose",
        why=(
            "`FIC-201.SP` was raised from 2.0 to 2.3 m3/h and later returned; water followed "
            "through the ratio. More heat is released, so the cooling valve opens, and the "
            "shorter residence time lets a little more PO through. A method that flags this "
            "as a fault is reacting to an intended change: the setpoint tag shows it."
        ),
    ),
}


SCENARIOS = {
    "cstr-rca": {
        "recipe": "rca-benchmark",
        # Neutral on purpose: this string is written into the shipped manifest.
        "description": "R-201 propylene glycol reactor, 90 day historian extract.",
        # Nine causes, no failed component or mechanism repeated, all four
        # symptom classes and five injection layers. Each sits beside at least
        # two same-symptom competitors that do not occur, which a diagnosis has
        # to rule out.
        "cause_ids": [
            "RC-A1",   # S1  jacket fouling
            "RC-B1",   # S2  TV-202 stiction
            "RC-D1",   # S4  catalyst deactivation
            "RC-A2",   # S1  cooling tower degraded
            "RC-D3",   # S4  temperature element drifting low
            "RC-C1",   # S3  TIC-201 left in manual
            "RC-A3",   # S1  agitator impeller damage
            "RC-D4",   # S4  water flowmeter reading high
            "RC-B3",   # S2  PO feed pump surging
        ],
        "severities": [
            "moderate", "subtle", "moderate", "moderate", "subtle",
            "obvious", "moderate", "moderate", "obvious",
        ],
        "benign_kinds": ["temperature_sp", "rate_change"],
    },
    "cstr-clean": {
        "description": (
            "R-201 with no injected faults: only weather, utility and feed "
            "variability, and normal operator activity. Measures false positives."
        ),
        "n_faults": 0,
        "n_benign": 3,
        "background_fouling": False,
    },
}


PLANT = Plant(
    name="exothermic_cstr",
    equipment="R-201",
    summary="Jacketed CSTR hydrolysing propylene oxide to propylene glycol, "
            "temperature cascaded onto jacket temperature, ratioed feeds",
    unit_cls=ExothermicCSTR,
    tags=cstr_tags,
    loops=cstr_loops,
    channels=cstr_channels,
    catalog=CATALOG,
    describe=describe,
    scenarios=SCENARIOS,
    recompute_calcs=recompute_dcs_calculations,
    benign_events=BENIGN_EVENTS,
    default_benign_kinds=("temperature_sp", "rate_change"),
    # TI-204 is the only tag that separates a drifting control element from a
    # real change in the reaction; JI-201 the only one that separates the
    # agitator from jacket fouling.
    hard_mode_withheld=("TI-204", "JI-201"),
    mass_balance=(("FI-201", "FI-202"), ("FI-203",)),
    background_notes=(
        "slow transmitter calibration drift (for example the long-run `CALC-MBAL` offset and the "
        "gap between the two reactor temperature elements both wander slightly over the record)"
    ),
)
