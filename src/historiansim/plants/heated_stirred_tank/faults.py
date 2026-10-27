"""The fault catalog for the heated stirred tank.

Organised the way a diagnosis actually proceeds: by **symptom**, not by cause.
Each symptom class is a set of root causes that produce the same first
observable, so identifying the symptom narrows nothing. The work is
discrimination, and the discrimination matrix records exactly which other tag
settles each question.

Four symptom classes, nineteen root causes, spanning four injection layers:

======  ==================================================  =====
Class   First observable                                    Causes
======  ==================================================  =====
S1      steam valve opens, temperature stays on setpoint    6
S2      level loop cycles                                   4
S3      temperature leaves setpoint, valve saturated        4
S4      balances stop closing, loops look normal            5
======  ==================================================  =====

Note on S1: five of its six causes drive the valve *open*. ``RC-A6`` (steam
valve stiction) shares the class because it shares the first observable --
the information is in the manipulated variable while the temperature stays
clean -- but its signature is in the variance of the valve position rather
than its level. Discriminating it from ``RC-A5``, which also hunts, is the
hardest pair in the catalog.

The severity levels are a difficulty dial. ``subtle`` is sized so the first
days of the fault move the valve by less than the ambient swing does, which is
what makes early detection a real problem rather than a threshold check.
"""

from __future__ import annotations

from historiansim.faults.base import (
    ControlFault,
    DisturbanceFault,
    Erratic,
    Exponential,
    InstrumentFault,
    Linear,
    ProcessFault,
    Step,
)
from historiansim.faults.catalog import Evidence, FaultCatalog, RootCause, SymptomClass

__all__ = ["CATALOG", "SYMPTOMS"]

DAY = 86400.0
HOUR = 3600.0


SYMPTOMS: dict[str, SymptomClass] = {
    "S1": SymptomClass(
        id="S1",
        label="steam valve slowly opening, temperature on setpoint",
        first_observable="TV-101.POS",
        description=(
            "The controlled variable looks perfect for the entire episode. All "
            "of the information is in the manipulated variable. With the steam "
            "flow cascade in service the inner loop absorbs the change too, so "
            "for several causes the valve position is the only tag that moves "
            "at all.\n\n"
            "Note what is *not* diagnostic here. CALC-UA looks like the obvious "
            "tag for a heat-transfer problem and is useless for it: it is "
            "computed as duty over approach, and while the temperature loop is "
            "holding, duty is pinned by the process load and approach is pinned "
            "by the header pressure and the setpoint. The ratio is therefore "
            "near-constant whatever the coil is doing, and it stays flat through "
            "fouling, backup and stiction alike. The discrimination lives in the "
            "valve position (its level, its scatter, and its agreement with "
            "the demand), plus the condensate temperature."
        ),
    ),
    "S2": SymptomClass(
        id="S2",
        label="outlet valve and level loop misbehaving",
        first_observable="LIC-101.OP",
        tempo="cycling",
        description=(
            "Something is wrong on the level loop. Note that a sustained "
            "oscillation in the level itself is only one of the ways this "
            "presents, and on this unit it is the rarer one: LIC-101 is a "
            "surge-damping inventory loop tuned deliberately loose, so it "
            "filters a sticking outlet valve almost out of the level "
            "altogether. For a genuine disturbance or a badly-placed setpoint "
            "the level does cycle; for a valve or transmitter fault the level "
            "can look untouched while the outlet valve tells the whole story. "
            "Read the demand against the stem position before concluding "
            "anything from the PV."
        ),
    ),
    "S3": SymptomClass(
        id="S3",
        label="temperature off setpoint with the valve saturated",
        first_observable="TIC-101.PV",
        tempo="acute",
        description=(
            "Control has run out of range. The question is never whether "
            "something is wrong. The question is whether the cause is supply, load, or "
            "the control system itself."
        ),
    ),
    "S4": SymptomClass(
        id="S4",
        label="balances stop closing while every loop looks normal",
        first_observable="CALC-MBAL",
        description=(
            "Every controlled variable is on setpoint and every valve is in a "
            "normal range, but the mass or energy balance has drifted. Usually "
            "an instrument, occasionally a genuine loss of containment, and "
            "the two demand opposite responses."
        ),
    ),
}


# ---------------------------------------------------------------------------
# S1: steam valve opening, temperature masked
# ---------------------------------------------------------------------------

_S1_TUNING = {
    # severity: (magnitude, tau)
    "subtle": (0.12, 9 * DAY),
    "moderate": (0.25, 5 * DAY),
    "obvious": (0.45, 2 * DAY),
}


def _fouling(onset: float, severity: str):
    mag, tau = _S1_TUNING[severity]
    return ProcessFault(
        id="RC-A1", param="fouling_factor", magnitude=mag, onset_s=onset,
        profile=Exponential(tau_s=tau), mode="scale", label="coil fouling",
    )


def _backup(onset: float, severity: str):
    mag, tau = _S1_TUNING[severity]
    return ProcessFault(
        id="RC-A5", param="flooded_fraction", magnitude=mag * 0.9, onset_s=onset,
        profile=Erratic(tau_s=tau * 0.5, period_s=5400.0, depth=0.35),
        mode="offset", label="condensate backup",
    )


def _feed_creep(onset: float, severity: str):
    mag = {"subtle": 0.08, "moderate": 0.18, "obvious": 0.30}[severity]
    return DisturbanceFault(
        id="RC-A2", channel="feed_flow", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=4 * DAY), mode="scale", label="upstream feed rate creep",
    )


def _header_decline(onset: float, severity: str):
    mag = {"subtle": -0.9, "moderate": -1.8, "obvious": -2.8}[severity]
    return DisturbanceFault(
        id="RC-A3", channel="steam_header_P", magnitude=mag, onset_s=onset,
        profile=Exponential(tau_s=3 * DAY), mode="offset",
        label="steam header pressure decline",
    )


def _feed_cold(onset: float, severity: str):
    mag = {"subtle": -4.0, "moderate": -9.0, "obvious": -14.0}[severity]
    return DisturbanceFault(
        id="RC-A4", channel="feed_temp", magnitude=mag, onset_s=onset,
        profile=Exponential(tau_s=3 * DAY), mode="offset",
        label="cold feed from upstream",
    )


# ---------------------------------------------------------------------------
# S2: level cycling
# ---------------------------------------------------------------------------

def _stiction(onset: float, severity: str):
    mag = {"subtle": 0.02, "moderate": 0.05, "obvious": 0.09}[severity]
    return ProcessFault(
        id="RC-B1", param="lv_stiction", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=2 * DAY), mode="offset", label="LV-101 stiction",
    )


def _tv_stiction(onset: float, severity: str):
    # Same friction model as LV-101, pointed at the steam valve. Sized a little
    # tighter because the steam flow loop is fast and its integral action winds
    # up against the deadband quickly; the level loop is slower and tolerates a
    # wider band before it cycles.
    mag = {"subtle": 0.015, "moderate": 0.035, "obvious": 0.065}[severity]
    return ProcessFault(
        id="RC-A6", param="tv_stiction", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=2 * DAY), mode="offset", label="TV-101 stiction",
    )


def _level_sp_move(onset: float, severity: str):
    value = {"subtle": 1.6, "moderate": 1.2, "obvious": 0.9}[severity]
    return ControlFault(
        id="RC-B2", loop="LIC-101", action="setpoint", onset_s=onset,
        value=value, label="level setpoint lowered into a higher-gain region",
    )


def _feed_surging(onset: float, severity: str):
    mag = {"subtle": 0.05, "moderate": 0.11, "obvious": 0.20}[severity]
    return DisturbanceFault(
        id="RC-B3", channel="feed_flow", magnitude=mag, onset_s=onset,
        profile=Erratic(tau_s=HOUR, period_s=1800.0, depth=0.9), mode="scale",
        label="upstream pump surging",
    )


def _dp_cell_plugging(onset: float, severity: str):
    mag = {"subtle": 0.03, "moderate": 0.07, "obvious": 0.14}[severity]
    return InstrumentFault(
        id="RC-B4", tag="LIC-101.PV", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=3 * DAY), mode="offset",
        label="level DP cell impulse line plugging",
    )


# ---------------------------------------------------------------------------
# S3: temperature off setpoint, valve saturated
# ---------------------------------------------------------------------------

def _steam_loss(onset: float, severity: str):
    mag = {"subtle": -2.0, "moderate": -3.2, "obvious": -4.4}[severity]
    return DisturbanceFault(
        id="RC-C1", channel="steam_header_P", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=30 * 60.0), mode="offset", end_s=None,
        label="steam supply loss",
    )


def _feed_step(onset: float, severity: str):
    mag = {"subtle": 0.25, "moderate": 0.45, "obvious": 0.70}[severity]
    return DisturbanceFault(
        id="RC-C2", channel="feed_flow", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=20 * 60.0), mode="scale",
        label="feed flow step beyond design",
    )


def _left_in_manual(onset: float, severity: str):
    hours = {"subtle": 4.0, "moderate": 10.0, "obvious": 20.0}[severity]
    return ControlFault(
        id="RC-C3", loop="TIC-101", action="manual", onset_s=onset,
        end_s=onset + hours * HOUR, value=0.0,
        label="temperature controller left in manual after an operator action",
    )


def _severe_fouling(onset: float, severity: str):
    """The moment the compensation margin runs out -- not the deposition.

    S3 episodes are acute by construction: the scheduler gives them 6-20 hours
    on the grounds that somebody responds to a temperature excursion. A fouling
    time constant measured in days therefore never develops inside the window
    it is given, and the episode lands in the data as nothing at all. What this
    models is the last of the valve travel disappearing, so it arrives fast.

    The magnitudes are set from the steady-state valve equation rather than by
    eye. Holding setpoint needs ``UA_coil * ff * R**(x-1) * (Tsat - Tsp)`` to
    equal the required duty; with the design numbers the valve reaches its stop
    once ``ff`` falls to about 0.13. ``moderate`` therefore takes the surviving
    fraction to roughly 0.10 -- saturated, with the temperature falling several
    degrees below setpoint -- and the other two bracket it.
    """
    mag = {"subtle": 0.84, "moderate": 0.90, "obvious": 0.93}[severity]
    return ProcessFault(
        id="RC-C4", param="fouling_factor", magnitude=mag, onset_s=onset,
        profile=Exponential(tau_s=2 * HOUR), mode="scale",
        label="fouling past the compensation range",
    )


# ---------------------------------------------------------------------------
# S4: balances drift, loops normal
# ---------------------------------------------------------------------------

def _steam_fm_drift(onset: float, severity: str):
    mag = {"subtle": 90.0, "moderate": 190.0, "obvious": 320.0}[severity]
    return InstrumentFault(
        id="RC-D1", tag="FIC-201.PV", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=6 * DAY), mode="offset",
        label="steam orifice plate fouling, flow reads high",
    )


def _blowthrough(onset: float, severity: str):
    mag = {"subtle": 0.12, "moderate": 0.28, "obvious": 0.45}[severity]
    return ProcessFault(
        id="RC-D2", param="blowthrough", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=2 * DAY), mode="offset",
        label="steam trap failed open, blowing live steam",
    )


def _feed_fm_drift(onset: float, severity: str):
    mag = {"subtle": 0.35, "moderate": 0.75, "obvious": 1.3}[severity]
    return InstrumentFault(
        id="RC-D3", tag="FI-101", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=7 * DAY), mode="offset",
        label="feed flow transmitter calibration drift",
    )


def _product_fm_zero(onset: float, severity: str):
    mag = {"subtle": -0.40, "moderate": -0.85, "obvious": -1.5}[severity]
    return InstrumentFault(
        id="RC-D4", tag="FI-102", magnitude=mag, onset_s=onset,
        profile=Step(), mode="offset", label="product flow transmitter zero shift",
    )


def _vessel_leak(onset: float, severity: str):
    mag = {"subtle": 0.00018, "moderate": 0.00040, "obvious": 0.00075}[severity]
    return ProcessFault(
        id="RC-D5", param="leak_coeff", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=3 * DAY), mode="offset", label="vessel leak",
    )


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------

#: The failed component behind each cause. Two causes on the same component
#: are not distinct episodes in a benchmark even when the mechanism differs --
#: the RCA recipe refuses to schedule both.
_COMPONENTS = {
    "RC-A1": "E-101 coil surface",
    "RC-A2": "upstream feed supply",
    "RC-A3": "steam header",
    "RC-A4": "upstream feed temperature",
    "RC-A5": "E-101 steam trap",
    "RC-A6": "TV-101",
    "RC-B1": "LV-101",
    "RC-B2": "LIC-101 setpoint",
    "RC-B3": "P-100",
    "RC-B4": "LI-101",
    "RC-C1": "steam header",
    "RC-C2": "upstream feed supply",
    "RC-C3": "TIC-101",
    "RC-C4": "E-101 coil surface",
    "RC-D1": "FI-201",
    "RC-D2": "E-101 steam trap",
    "RC-D3": "FI-101",
    "RC-D4": "FI-102",
    "RC-D5": "TK-101 vessel",
}


def _cause(**kw) -> RootCause:
    return RootCause(component=_COMPONENTS[kw["id"]], **kw)


CATALOG = FaultCatalog(
    SYMPTOMS,
    [
        # -- S1 ------------------------------------------------------------
        _cause(
            id="RC-A1", name="coil_fouling", label="Coil fouling", symptom="S1", layer=6,
            mechanism="Deposit on the coil reduces UA; the controller opens the valve to hold duty.",
            build=_fouling,
            evidence=(
                Evidence("FI-101", "flat", "feed rate unchanged", rules_out=("RC-A2",)),
                Evidence("TI-100", "flat", "feed temperature unchanged", rules_out=("RC-A4",)),
                Evidence("PI-201", "flat", "header healthy", rules_out=("RC-A3",)),
                Evidence("TI-202", "flat", "condensate returning normally", rules_out=("RC-A5",)),
                Evidence("TV-101.POS", "rises", "smooth, monotonic, first-order, with no "
                                                "hunting, no jumps",
                         rules_in=("RC-A1",), rules_out=("RC-A6",)),
            ),
        ),
        _cause(
            id="RC-A2", name="feed_rate_creep", label="Upstream feed rate creep", symptom="S1", layer=4,
            mechanism="More throughput means more sensible load, so more steam is demanded.",
            build=_feed_creep,
            evidence=(
                Evidence("FI-101", "rises", "feed rate is climbing", rules_in=("RC-A2",),
                         rules_out=("RC-A1", "RC-A3", "RC-A4", "RC-A5", "RC-A6")),
                Evidence("FIC-201.PV", "rises", "steam demand tracks the load"),
                Evidence("TI-100", "flat", "the feed is not colder", rules_out=("RC-A4",)),
            ),
        ),
        _cause(
            id="RC-A3", name="header_pressure_decline", label="Steam header pressure decline",
            symptom="S1", layer=4,
            mechanism="Lower header pressure lowers saturation temperature, cutting the driving force.",
            build=_header_decline,
            evidence=(
                Evidence("PI-201", "falls", "header pressure is sagging", rules_in=("RC-A3",),
                         rules_out=("RC-A1", "RC-A2", "RC-A5", "RC-A6")),
                Evidence("TI-201", "falls", "saturation temperature follows pressure"),
                Evidence("TI-202", "falls", "condensate follows saturation down too, so this "
                                            "tag alone does not separate it from backup; the "
                                            "TI-201 minus TI-202 subcooling stays normal"),
                Evidence("TV-101.POS", "rises", "the valve opens by exactly what the lower driving "
                                                "force requires: valve position is still consistent "
                                                "with the coil relation at the measured T_sat, so "
                                                "the coil itself is healthy"),
            ),
        ),
        _cause(
            id="RC-A4", name="feed_preheat_loss", label="Cold feed from upstream", symptom="S1", layer=4,
            mechanism="Colder feed raises the sensible heat duty at unchanged throughput.",
            build=_feed_cold,
            evidence=(
                Evidence("TI-100", "falls", "the feed is arriving colder", rules_in=("RC-A4",),
                         rules_out=("RC-A1", "RC-A2", "RC-A3", "RC-A5", "RC-A6")),
                Evidence("FI-101", "flat", "throughput unchanged", rules_out=("RC-A2",)),
                Evidence("FIC-201.PV", "rises", "same energy signature as feed creep"),
            ),
        ),
        _cause(
            id="RC-A5", name="condensate_backup", label="Condensate backup in the coil",
            symptom="S1", layer=6,
            mechanism=(
                "A failing trap lets condensate flood part of the coil, removing "
                "heat transfer area. Enters the physics at exactly the same place "
                "as fouling and is indistinguishable from it on the steam valve."
            ),
            build=_backup,
            evidence=(
                Evidence("TI-202", "falls", "stagnant condensate subcools. This is the one tag that "
                                            "separates this from fouling",
                         rules_in=("RC-A5",), rules_out=("RC-A1", "RC-A6")),
                Evidence("PI-201", "flat", "and the header is healthy, which rules out the "
                                           "other reason TI-202 could fall",
                         rules_out=("RC-A3",)),
                Evidence("TV-101.POS", "rises", "the valve opens further than the coil should need "
                                                "for the duty it is delivering (section 4.3 of the "
                                                "process description), and hunts as slugs clear",
                         rules_in=("RC-A5", "RC-A1")),
                Evidence("FIC-201.OP", "rises", "the stem follows its demand one for one: the "
                                                "positioner is healthy, so this is not stiction",
                         rules_out=("RC-A6",)),
                Evidence("FI-101", "flat", "throughput unchanged", rules_out=("RC-A2",)),
            ),
        ),
        _cause(
            id="RC-A6", name="steam_valve_stiction", label="TV-101 stiction",
            symptom="S1", layer=6,
            mechanism=(
                "Static friction in the steam valve stem. The flow controller "
                "winds up against the deadband, breaks free, and overshoots, so "
                "the valve limit-cycles instead of settling. The tank's thermal "
                "mass filters the cycle out of the temperature, so the "
                "controlled variable stays clean and only the valve misbehaves. "
                "The same first observable as fouling and condensate backup, but "
                "the mean position barely moves. The signature is in the "
                "variance, not the level. Condensate backup hunts too; the "
                "condensate temperature is what separates the two."
            ),
            build=_tv_stiction,
            evidence=(
                Evidence("TV-101.POS", "erratic",
                         "square-ish position against a smooth demand; the OP/POS plot "
                         "traces a parallelogram, which neither fouling nor slugging does",
                         rules_in=("RC-A6",), rules_out=("RC-A1",)),
                Evidence("TI-202", "flat",
                         "condensate returns normally; nothing is subcooling in the coil",
                         rules_out=("RC-A5",)),
                Evidence("FI-101", "flat", "throughput unchanged", rules_out=("RC-A2",)),
                Evidence("PI-201", "flat", "header healthy", rules_out=("RC-A3",)),
            ),
        ),
        # -- S2 ------------------------------------------------------------
        _cause(
            id="RC-B1", name="valve_stiction", label="LV-101 stiction", symptom="S2", layer=6,
            mechanism=(
                "Static friction makes the stem move in jumps rather than "
                "following its demand. On a tightly-tuned loop that sustains a "
                "limit cycle; on this one it does not. LIC-101 is a loose "
                "surge-damping loop, so the tank absorbs the jumps and the "
                "level barely registers them. The evidence is the "
                "disagreement between what the controller asks for and where "
                "the stem actually goes, not an oscillation in the PV."
            ),
            build=_stiction, masked_by_control=False,
            evidence=(
                Evidence("LV-101.POS", "erratic",
                         "the stem stands still through small changes in demand and then "
                         "jumps; plotted against LIC-101.OP it traces a parallelogram "
                         "instead of a line. The stem covers materially less travel than "
                         "the demand does, which is the positive test for stiction",
                         rules_in=("RC-B1",), rules_out=("RC-B2", "RC-B3", "RC-B4")),
                Evidence("LIC-101.OP", "erratic", "the controller works harder to chase a "
                                                  "stem that will not follow it",
                         rules_in=("RC-B1",)),
                Evidence("LI-102", "erratic", "the redundant transmitter tracks the primary "
                                              "step for step. Both level readings still "
                                              "agree, so the measurement is sound and it is "
                                              "the valve that is at fault",
                         rules_out=("RC-B4",)),
                Evidence("FI-101", "flat", "nothing upstream is cycling", rules_out=("RC-B3",)),
                Evidence("LIC-101.SP", "flat", "and nobody moved the setpoint", rules_out=("RC-B2",)),
            ),
        ),
        _cause(
            id="RC-B2", name="operating_point_shift", label="Level setpoint moved into a higher-gain region",
            symptom="S2", layer=3,
            mechanism=(
                "Outflow goes as sqrt(level), so loop gain rises as level falls. "
                "A loop tuned at 2 m cycles at 1.2 m without anything being wrong."
            ),
            build=_level_sp_move, masked_by_control=False,
            evidence=(
                Evidence("LIC-101.SP", "steps", "the setpoint was moved, and the cycling starts after",
                         rules_in=("RC-B2",), rules_out=("RC-B1", "RC-B3")),
                Evidence("LIC-101.PV", "erratic", "cycle amplitude grows as level falls"),
            ),
        ),
        _cause(
            id="RC-B3", name="upstream_surging", label="Upstream pump surging", symptom="S2", layer=4,
            mechanism="The disturbance arrives already cycling; the level loop is only passing it on.",
            build=_feed_surging, masked_by_control=False,
            evidence=(
                Evidence("FI-101", "erratic", "the feed arrives already cycling, with surges of "
                                              "tens of minutes, and its mean rate is raised. The "
                                              "disturbance originates upstream",
                         rules_in=("RC-B3",), rules_out=("RC-B1", "RC-B2", "RC-B4")),
                Evidence("LIC-101.OP", "erratic", "the level loop passes the cycle through to the "
                                                  "outlet, so the outlet valve and product flow "
                                                  "cycle after the feed does"),
                Evidence("LV-101.POS", "erratic", "and the stem tracks that demand one for one, so "
                                                  "the outlet valve is healthy",
                         rules_out=("RC-B1",)),
                Evidence("LIC-101.SP", "flat", "nobody moved the setpoint", rules_out=("RC-B2",)),
                Evidence("LI-102", "erratic", "both level transmitters agree", rules_out=("RC-B4",)),
            ),
        ),
        _cause(
            id="RC-B4", name="dp_cell_plugging", label="Level DP cell impulse line plugging",
            symptom="S2", layer=7,
            mechanism="The transmitter reads a drifting offset; the loop faithfully controls a lie.",
            build=_dp_cell_plugging, masked_by_control=False,
            evidence=(
                Evidence("LI-102", "falls", "the redundant transmitter disagrees, and it is the "
                                            "one telling the truth",
                         rules_in=("RC-B4",), rules_out=("RC-B1", "RC-B2", "RC-B3")),
                Evidence("LIC-101.OP", "rises", "the loop trims the outlet to chase an offset "
                                                "that is not there"),
                Evidence("LV-101.POS", "rises", "and the stem tracks that demand one for one, "
                                                "with no deadband and no jumps. The valve is "
                                                "healthy, which is what separates this from "
                                                "stiction on the same loop",
                         rules_out=("RC-B1",)),
                Evidence("FI-101", "flat", "nothing upstream changed", rules_out=("RC-B3",)),
            ),
        ),
        # -- S3 ------------------------------------------------------------
        _cause(
            id="RC-C1", name="steam_supply_loss", label="Steam supply loss", symptom="S3", layer=4,
            mechanism="The header collapses; there is not enough driving force at any valve position.",
            build=_steam_loss, masked_by_control=False,
            evidence=(
                Evidence("PI-201", "falls", "header pressure collapsed", rules_in=("RC-C1",),
                         rules_out=("RC-C2", "RC-C3", "RC-C4")),
                Evidence("TV-101.POS", "rises", "valve pinned at its stop"),
            ),
        ),
        _cause(
            id="RC-C2", name="feed_step", label="Feed flow step beyond design", symptom="S3", layer=4,
            mechanism="Load exceeds the coil's capacity at full valve.",
            build=_feed_step, masked_by_control=False,
            evidence=(
                Evidence("FI-101", "steps", "a step change in throughput", rules_in=("RC-C2",),
                         rules_out=("RC-C1", "RC-C3", "RC-C4")),
                Evidence("PI-201", "flat", "supply is fine", rules_out=("RC-C1",)),
            ),
        ),
        _cause(
            id="RC-C3", name="left_in_manual", label="Controller left in manual", symptom="S3", layer=3,
            mechanism="Nothing is wrong with the plant. The loop simply is not controlling.",
            build=_left_in_manual, masked_by_control=False,
            evidence=(
                Evidence("TIC-101.MODE", "steps", "the mode tag says MAN", rules_in=("RC-C3",),
                         rules_out=("RC-C1", "RC-C2", "RC-C4")),
                Evidence("TIC-101.OP", "frozen", "the master's output is frozen while its PV "
                                               "drifts away. Note it is TIC-101.OP that "
                                               "freezes, not the valve: with the cascade in "
                                               "service the master writes a steam flow "
                                               "setpoint, and the inner flow loop keeps "
                                               "working the valve to hold it",
                         rules_in=("RC-C3",)),
                Evidence("TIC-101.PV", "erratic", "bulk temperature wanders off setpoint with the "
                                                  "load and the weather because nothing is "
                                                  "correcting it"),
                Evidence("PI-201", "flat", "supply is fine", rules_out=("RC-C1",)),
                Evidence("FI-101", "flat", "load is unchanged", rules_out=("RC-C2",)),
            ),
        ),
        _cause(
            id="RC-C4", name="fouling_exhausted", label="Fouling past the compensation range",
            symptom="S3", layer=6,
            mechanism="The end state of an S1 episode nobody acted on; the valve runs out of travel.",
            build=_severe_fouling, masked_by_control=False,
            evidence=(
                Evidence("TV-101.POS", "rises", "a long, slow precursor is visible in history",
                         rules_in=("RC-C4",), rules_out=("RC-C1", "RC-C2", "RC-C3")),
                Evidence("PI-201", "flat", "supply is fine", rules_out=("RC-C1",)),
                Evidence("FI-101", "flat", "load is unchanged", rules_out=("RC-C2",)),
            ),
        ),
        # -- S4 ------------------------------------------------------------
        _cause(
            id="RC-D1", name="steam_fm_drift", label="Steam flow transmitter drift", symptom="S4", layer=7,
            mechanism=(
                "A fouling orifice plate reads high. The process is untouched, so "
                "the energy balance built from this tag stops closing while every "
                "real quantity is unchanged."
            ),
            build=_steam_fm_drift,
            evidence=(
                Evidence("CALC-EBAL", "rises", "steam-side duty pulls away from process-side; "
                                               "the energy balance opens up",
                         rules_in=("RC-D1",), rules_out=("RC-D4",)),
                Evidence("FIC-201.PV", "rises", "indicated steam climbs"),
                Evidence("TI-202", "flat", "but the condensate return is normal, so no real "
                                           "steam is being wasted", rules_out=("RC-D2",)),
                Evidence("CALC-MBAL", "flat", "and the mass balance is untouched",
                         rules_out=("RC-D3", "RC-D5")),
            ),
        ),
        _cause(
            id="RC-D2", name="trap_blowthrough", label="Steam trap failed open", symptom="S4", layer=6,
            mechanism=(
                "Live steam escapes to the condensate system. Real steam is "
                "genuinely consumed without delivering heat, which looks like a "
                "transmitter drift until the condensate temperature is checked."
            ),
            build=_blowthrough,
            evidence=(
                Evidence("TI-202", "rises", "condensate return climbs toward saturation. This is the "
                                            "one tag separating this from a drifting transmitter",
                         rules_in=("RC-D2",), rules_out=("RC-D1",)),
                Evidence("CALC-EBAL", "rises", "real steam consumed without reaching the process"),
                Evidence("FIC-201.PV", "rises", "steam consumption genuinely rises"),
            ),
        ),
        _cause(
            id="RC-D3", name="feed_fm_drift", label="Feed flow transmitter drift", symptom="S4", layer=7,
            mechanism="The feed reading drifts; the mass balance opens up linearly.",
            build=_feed_fm_drift,
            evidence=(
                Evidence("CALC-MBAL", "rises", "residual grows steadily rather than stepping",
                         rules_in=("RC-D3",), rules_out=("RC-D4",)),
                Evidence("CALC-EBAL", "falls", "process-side duty reads high on the same bad "
                                               "flow, pulling the balance the other way. This is the "
                                               "tag that separates this from a product-side error",
                         rules_out=("RC-D1", "RC-D2", "RC-D4")),
                Evidence("LIC-101.PV", "flat", "level is steady, so nothing is actually being lost",
                         rules_out=("RC-D5",)),
            ),
        ),
        _cause(
            id="RC-D4", name="product_fm_zero", label="Product flow transmitter zero shift",
            symptom="S4", layer=7,
            mechanism="A step offset on the outlet reading, typically after a maintenance touch.",
            build=_product_fm_zero,
            evidence=(
                Evidence("CALC-MBAL", "steps", "the residual steps rather than ramping",
                         rules_in=("RC-D4",), rules_out=("RC-D3", "RC-D5")),
                Evidence("CALC-EBAL", "flat", "the energy balance is untouched, so the error is "
                                              "on the product side only",
                         rules_out=("RC-D1", "RC-D2", "RC-D3")),
                Evidence("LIC-101.PV", "flat", "level does not corroborate the imbalance"),
                Evidence("LV-101.POS", "flat", "the outlet valve has not moved, so with level "
                                               "unchanged the true outflow (section 4.1 of the "
                                               "process description) is unchanged too. Only "
                                               "the reading moved",
                         rules_out=("RC-D5",)),
            ),
        ),
        _cause(
            id="RC-D5", name="vessel_leak", label="Vessel leak", symptom="S4", layer=2,
            mechanism=(
                "Genuine loss of containment: liquid leaves the vessel other than through "
                "the outlet line. Unlike a flowmeter error, material is actually lost."
            ),
            build=_vessel_leak,
            evidence=(
                Evidence("LV-101.POS", "falls", "the level loop closes the outlet valve to hold "
                                                "level against liquid leaving another way. The "
                                                "measured product flow agrees with the valve "
                                                "position and level, so FI-102 is reading "
                                                "correctly and the missing liquid is real",
                         rules_in=("RC-D5",), rules_out=("RC-D1", "RC-D3", "RC-D4")),
                Evidence("LIC-101.OP", "falls", "the demand behind that valve movement"),
                Evidence("CALC-MBAL", "rises", "the balance opens up and keeps growing as the "
                                               "leak develops, rather than stepping"),
                Evidence("FI-102", "falls", "less product reaches the outlet line"),
                Evidence("LIC-101.PV", "flat", "level is held, so the loss shows in the outlet "
                                               "valve, not in the level"),
                Evidence("CALC-EBAL", "flat", "the feed meter is not involved",
                         rules_out=("RC-D3",)),
            ),
        ),
    ],
)
