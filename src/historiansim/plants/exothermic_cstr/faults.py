"""The fault catalog for R-201, organised by symptom.

Four symptom classes, fifteen root causes, five injection layers:

======  ======================================================  ======
Class   First observable                                        Causes
======  ======================================================  ======
S1      cooling valve opens, reactor temperature on setpoint    5
S2      cooling or feed side oscillating                        3
S3      reactor temperature off setpoint                        2
S4      composition or balance drifting, loops on setpoint      5
======  ======================================================  ======

The cascade is what makes S1 hard. The jacket loop absorbs every change in
how much heat has to come out, or how hard it is to get out, so reactor
temperature stays on setpoint and the information lives in the cooling valve,
the jacket temperature and the cooling-water tags. Unlike a steam coil, the
jacket approach ``T - Tj`` is free to move, so the back-calculated UA really
does separate a heat-transfer loss (fouling, agitation) from a heat-load or
utility change -- but only once the cooling-water side is checked.
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

SYMPTOMS = {
    "S1": SymptomClass(
        id="S1",
        label="cooling valve slowly opening, reactor temperature on setpoint",
        first_observable="TV-202.POS",
        description=(
            "Reactor temperature looks perfect. The jacket loop is working "
            "harder: the cooling valve opens over days and the jacket "
            "temperature setpoint written by TIC-201 moves. Either more heat "
            "has to come out, or it has become harder to get out, or the "
            "cooling water itself has changed. The cooling-water tags and the "
            "back-calculated UA decide which."
        ),
    ),
    "S2": SymptomClass(
        id="S2",
        label="cooling or feed side oscillating",
        first_observable="TIC-202.OP",
        tempo="cycling",
        description=(
            "Something on the cooling or feed side has started to cycle. "
            "The reactor's thermal mass filters most of it out of the bulk "
            "temperature. The question is where the oscillation enters: a "
            "valve, a utility header or a feed."
        ),
    ),
    "S3": SymptomClass(
        id="S3",
        label="reactor temperature off setpoint",
        first_observable="TIC-201.PV",
        tempo="acute",
        description=(
            "Temperature control has stopped holding the reactor. Either the "
            "cooling has run out of capacity or the control system is not "
            "acting."
        ),
    ),
    "S4": SymptomClass(
        id="S4",
        label="composition or balance drifting while every loop holds setpoint",
        first_observable="AI-201",
        description=(
            "Every controlled variable is on setpoint, but the residual PO "
            "reading, the second temperature element or the liquid balance "
            "has moved. Some of these are real changes in the reaction; some "
            "are an instrument telling a story the process is not living."
        ),
    ),
}


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def _jacket_fouling(onset, severity):
    mag, tau = {"subtle": (0.12, 9 * DAY), "moderate": (0.25, 5 * DAY),
                "obvious": (0.40, 2 * DAY)}[severity]
    return ProcessFault(
        id="RC-A1", param="fouling_factor", magnitude=mag, onset_s=onset,
        profile=Exponential(tau_s=tau), mode="scale", label="jacket-side fouling",
    )


def _cw_supply_hot(onset, severity):
    mag = {"subtle": 2.5, "moderate": 4.5, "obvious": 6.0}[severity]
    return DisturbanceFault(
        id="RC-A2", channel="T_cw", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=2 * DAY), mode="offset",
        label="cooling water supply temperature rise",
    )


def _impeller(onset, severity):
    mag = {"subtle": 0.15, "moderate": 0.30, "obvious": 0.45}[severity]
    return ProcessFault(
        id="RC-A3", param="agit_factor", magnitude=mag, onset_s=onset,
        profile=Exponential(tau_s=3 * DAY), mode="scale", label="agitator impeller damage",
    )


def _overdose(onset, severity):
    mag = {"subtle": -0.25, "moderate": -0.50, "obvious": -0.80}[severity]
    return ProcessFault(
        id="RC-A4", param="cat_factor", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=1 * DAY), mode="scale", label="acid catalyst over-dosing",
    )


def _cw_dp_decline(onset, severity):
    mag = {"subtle": -0.5, "moderate": -0.9, "obvious": -1.3}[severity]
    return DisturbanceFault(
        id="RC-A5", channel="dP_cw", magnitude=mag, onset_s=onset,
        profile=Exponential(tau_s=3 * DAY), mode="offset",
        label="cooling water header pressure decline",
    )


def _tv_stiction(onset, severity):
    mag = {"subtle": 0.012, "moderate": 0.025, "obvious": 0.05}[severity]
    return ProcessFault(
        id="RC-B1", param="tv_stiction", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=2 * DAY), mode="offset", label="TV-202 stiction",
    )


def _cw_surging(onset, severity):
    mag = {"subtle": -0.15, "moderate": -0.30, "obvious": -0.45}[severity]
    return DisturbanceFault(
        id="RC-B2", channel="dP_cw", magnitude=mag, onset_s=onset,
        profile=Erratic(tau_s=HOUR, period_s=900.0, depth=0.9), mode="scale",
        label="cooling water header pressure surging",
    )


def _po_pump_surging(onset, severity):
    mag = {"subtle": -0.15, "moderate": -0.30, "obvious": -0.45}[severity]
    return DisturbanceFault(
        id="RC-B3", channel="dP_po", magnitude=mag, onset_s=onset,
        profile=Erratic(tau_s=HOUR, period_s=600.0, depth=0.9), mode="scale",
        label="PO feed pump P-201 surging",
    )


def _left_in_manual(onset, severity):
    hours = {"subtle": 4.0, "moderate": 10.0, "obvious": 20.0}[severity]
    return ControlFault(
        id="RC-C1", loop="TIC-201", action="manual", onset_s=onset,
        end_s=onset + hours * HOUR, value=0.0,
        label="reactor temperature controller left in manual",
    )


def _cw_loss(onset, severity):
    mag = {"subtle": -0.97, "moderate": -0.985, "obvious": -0.995}[severity]
    return DisturbanceFault(
        id="RC-C2", channel="dP_cw", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=30 * 60.0), mode="scale", label="cooling water supply loss",
    )


def _deactivation(onset, severity):
    mag = {"subtle": 0.15, "moderate": 0.30, "obvious": 0.45}[severity]
    return ProcessFault(
        id="RC-D1", param="cat_factor", magnitude=mag, onset_s=onset,
        profile=Exponential(tau_s=3 * DAY), mode="scale", label="catalyst deactivation",
    )


def _analyzer_drift(onset, severity):
    mag = {"subtle": 0.25, "moderate": 0.50, "obvious": 0.90}[severity]
    return InstrumentFault(
        id="RC-D2", tag="AI-201", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=5 * DAY), mode="offset", label="AI-201 calibration drift",
    )


def _element_drift(onset, severity):
    mag = {"subtle": -0.8, "moderate": -1.4, "obvious": -2.2}[severity]
    return InstrumentFault(
        id="RC-D3", tag="TIC-201.PV", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=5 * DAY), mode="offset",
        label="reactor temperature element TE-201 drifting low",
    )


def _water_meter_high(onset, severity):
    mag = {"subtle": 0.20, "moderate": 0.40, "obvious": 0.70}[severity]
    return InstrumentFault(
        id="RC-D4", tag="FFC-202.PV", magnitude=mag, onset_s=onset,
        profile=Linear(ramp_s=6 * DAY), mode="offset",
        label="process water flow transmitter FT-202 reading high",
    )


def _product_meter_zero(onset, severity):
    mag = {"subtle": -0.25, "moderate": -0.50, "obvious": -0.90}[severity]
    return InstrumentFault(
        id="RC-D5", tag="FI-203", magnitude=mag, onset_s=onset,
        profile=Step(), mode="offset", label="product flow transmitter FT-203 zero shift",
    )


# ---------------------------------------------------------------------------
# the catalog
# ---------------------------------------------------------------------------

CATALOG = FaultCatalog(
    SYMPTOMS,
    [
        # -- S1 ------------------------------------------------------------
        RootCause(
            id="RC-A1", name="jacket_fouling", label="Jacket heat-transfer fouling",
            symptom="S1", layer=6, component="R-201 jacket wall",
            mechanism=(
                "Deposit builds on the jacket's heat-transfer wall (scale from the cooling "
                "water) and adds a resistance to heat transfer. The heat load is unchanged, so to push the same duty through "
                "less UA the jacket must run colder: the master lowers the jacket setpoint "
                "and the cooling valve opens."
            ),
            build=_jacket_fouling, grade="Medium",
            evidence=(
                Evidence("CALC-UA", "falls", "the jacket transfers less heat per kelvin of approach",
                         rules_in=("RC-A1", "RC-A3"), rules_out=("RC-A2", "RC-A4", "RC-A5")),
                Evidence("JI-201", "flat", "agitator power is normal, so mixing is not the cause",
                         rules_out=("RC-A3",)),
                Evidence("TIC-202.PV", "falls", "the jacket runs colder to keep the duty up"),
                Evidence("TV-202.POS", "rises", "more cooling water to hold the colder jacket"),
                Evidence("TI-301", "flat", "cooling water arrives at its normal temperature",
                         rules_out=("RC-A2",)),
                Evidence("PI-301", "flat", "header pressure is normal", rules_out=("RC-A5",)),
                Evidence("AI-201", "flat", "reaction rate unchanged", rules_out=("RC-A4",)),
            ),
            walkthrough=(
                "Reactor temperature never leaves setpoint. Over days the cooling valve "
                "`TV-202.POS` opens and the jacket outlet `TIC-202.PV` (and its setpoint from "
                "TIC-201) drifts lower. The duty `CALC-QJ` is unchanged, so the heat load has "
                "not changed; the back-calculated `CALC-UA` falls, so the same heat now needs a "
                "bigger reactor-to-jacket approach. That is a heat-transfer loss. Agitator power "
                "`JI-201` is normal, which clears the impeller, and cooling-water supply "
                "temperature `TI-301` and header pressure `PI-301` are normal, which clear the "
                "utility. The jacket itself has fouled."
            ),
            competitors=("agitator impeller damage", "warmer cooling water",
                         "low cooling-water header pressure", "higher reaction rate"),
        ),
        RootCause(
            id="RC-A2", name="cw_supply_hot", label="Cooling water supply temperature rise",
            symptom="S1", layer=4, component="cooling tower",
            mechanism=(
                "The cooling tower delivers warmer water (for example a fan out of service). "
                "Each cubic metre removes less heat, so more water is needed for the same duty."
            ),
            build=_cw_supply_hot, grade="Medium",
            evidence=(
                Evidence("TI-301", "rises", "cooling water arrives warmer than the weather explains",
                         rules_in=("RC-A2",), rules_out=("RC-A1", "RC-A3", "RC-A4", "RC-A5")),
                Evidence("FI-301", "rises", "more water for the same duty"),
                Evidence("CALC-UA", "flat", "the jacket transfers heat normally",
                         rules_out=("RC-A1", "RC-A3")),
                Evidence("TV-202.POS", "rises", "the valve opens to pass the extra water"),
            ),
            walkthrough=(
                "Reactor temperature holds and the cooling valve `TV-202.POS` and cooling water "
                "flow `FI-301` climb over a couple of days. The jacket temperature and the duty "
                "`CALC-QJ` are unchanged, and `CALC-UA` is unchanged, so the heat load and the "
                "jacket's ability to transfer it are both normal: each cubic metre of water is "
                "simply removing less heat. Supply temperature `TI-301` says why. It always "
                "follows the weather, but it now sits several degrees above where the ambient "
                "temperature `TI-901` would put it, and stays there through the night. The "
                "header pressure is normal. The cooling tower is delivering warmer water."
            ),
            competitors=("jacket fouling", "agitator impeller damage", "low header pressure",
                         "higher reaction rate"),
        ),
        RootCause(
            id="RC-A3", name="impeller_damage", label="Agitator impeller damage",
            symptom="S1", layer=6, component="M-201 agitator",
            mechanism=(
                "A damaged or eroded impeller moves less liquid past the jacket wall. The "
                "process-side film coefficient falls, so UA falls, and the motor draws less "
                "power because the impeller is doing less work."
            ),
            build=_impeller, grade="Medium",
            evidence=(
                Evidence("JI-201", "falls", "the motor draws less power: the impeller is doing less work",
                         rules_in=("RC-A3",), rules_out=("RC-A1", "RC-A2", "RC-A4", "RC-A5")),
                Evidence("CALC-UA", "falls", "heat transfer has degraded",
                         rules_in=("RC-A3", "RC-A1"), rules_out=("RC-A2", "RC-A4", "RC-A5")),
                Evidence("TIC-202.PV", "falls", "the jacket runs colder to keep the duty up"),
                Evidence("TV-202.POS", "rises", "more cooling water"),
                Evidence("TI-301", "flat", "cooling water normal", rules_out=("RC-A2",)),
                Evidence("PI-301", "flat", "header normal", rules_out=("RC-A5",)),
            ),
            walkthrough=(
                "As with fouling, the reactor holds setpoint while the cooling valve "
                "`TV-202.POS` opens, the jacket runs colder (`TIC-202.PV` falls) and the "
                "back-calculated `CALC-UA` drops at an unchanged duty `CALC-QJ`: heat "
                "transfer has degraded. What separates this from fouling is the agitator: motor "
                "power `JI-201` falls by a few kW at the same time. Less power at the same speed "
                "means the impeller is moving less liquid, which also explains the lost "
                "process-side heat transfer. Cooling-water temperature and pressure are normal."
            ),
            competitors=("jacket fouling", "warmer cooling water", "low cooling-water pressure"),
        ),
        RootCause(
            id="RC-A4", name="acid_overdose", label="Acid catalyst over-dosing",
            symptom="S1", layer=4, component="acid dosing",
            mechanism=(
                "Stronger acid in the process water raises the rate constant. Conversion "
                "rises, more heat is released, and the jacket has to remove it."
            ),
            build=_overdose,
            evidence=(
                Evidence("AI-201", "falls", "less PO survives: the reaction has sped up",
                         rules_in=("RC-A4",), rules_out=("RC-A1", "RC-A2", "RC-A3", "RC-A5")),
                Evidence("CALC-QJ", "rises", "more heat really is being removed"),
                Evidence("CALC-UA", "flat", "the jacket itself is healthy",
                         rules_out=("RC-A1", "RC-A3")),
                Evidence("TI-301", "flat", "cooling water normal", rules_out=("RC-A2",)),
            ),
        ),
        RootCause(
            id="RC-A5", name="cw_dp_decline", label="Cooling water header pressure decline",
            symptom="S1", layer=4, component="cooling water header",
            mechanism=(
                "Less differential pressure across the jacket circuit means less flow at any "
                "valve position, so the valve opens to restore it."
            ),
            build=_cw_dp_decline,
            evidence=(
                Evidence("PI-301", "falls", "header differential pressure is sagging",
                         rules_in=("RC-A5",), rules_out=("RC-A1", "RC-A2", "RC-A3", "RC-A4")),
                Evidence("FI-301", "flat", "flow is restored by opening the valve"),
                Evidence("CALC-UA", "flat", "jacket healthy", rules_out=("RC-A1", "RC-A3")),
                Evidence("TV-202.POS", "rises", "the valve opens by what the lower dP requires"),
            ),
        ),
        # -- S2 ------------------------------------------------------------
        RootCause(
            id="RC-B1", name="cw_valve_stiction", label="TV-202 stiction",
            symptom="S2", layer=6, component="TV-202", masked_by_control=False,
            mechanism=(
                "Static friction in the cooling-water valve stem. The jacket loop winds up "
                "against the deadband, the stem breaks free and overshoots, and the jacket "
                "loop limit-cycles. The reactor's thermal mass filters the cycle almost out "
                "of the bulk temperature."
            ),
            build=_tv_stiction, grade="Hard",
            evidence=(
                Evidence("TV-202.POS", "erratic",
                         "the stem sticks while its demand moves and then jumps; plotted against "
                         "TIC-202.OP it traces stick-slip loops rather than a line",
                         rules_in=("RC-B1",), rules_out=("RC-B2", "RC-B3")),
                Evidence("TIC-202.OP", "erratic", "the jacket controller saws back and forth"),
                Evidence("PI-301", "flat", "the header is steady", rules_out=("RC-B2",)),
                Evidence("FIC-201.PV", "flat", "the PO feed is steady", rules_out=("RC-B3",)),
            ),
            walkthrough=(
                "Reactor temperature is essentially unaffected and nothing trends. The change "
                "is in how the cooling-water valve moves: `TV-202.POS` stops following its "
                "demand `TIC-202.OP`, standing still while the demand ramps and then jumping, "
                "so the gap between the two widens from about the readback resolution to a few "
                "percent and the jacket temperature `TIC-202.PV` cycles with it. The "
                "oscillation does not come from outside: header pressure `PI-301` and the PO "
                "feed `FIC-201.PV` are steady. A healthy positioner tracks its demand; this one "
                "does not, so the valve is sticking."
            ),
            competitors=("cooling water header pressure surging", "PO feed pump surging"),
        ),
        RootCause(
            id="RC-B2", name="cw_header_surging", label="Cooling water header pressure surging",
            symptom="S2", layer=4, component="cooling water header", masked_by_control=False,
            mechanism="Another user on the cooling water header is cycling; the jacket loop passes it on.",
            build=_cw_surging,
            evidence=(
                Evidence("PI-301", "erratic", "header pressure oscillates first",
                         rules_in=("RC-B2",), rules_out=("RC-B1", "RC-B3")),
                Evidence("TV-202.POS", "erratic", "the valve moves, but it follows its demand one for one",
                         rules_out=("RC-B1",)),
                Evidence("FIC-201.PV", "flat", "PO feed steady", rules_out=("RC-B3",)),
            ),
        ),
        RootCause(
            id="RC-B3", name="po_pump_surging", label="PO feed pump P-201 surging",
            symptom="S2", layer=4, component="P-201", masked_by_control=False,
            mechanism=(
                "The PO feed pump's discharge pressure surges. FIC-201 fights it by moving "
                "FV-201, the flow wobbles around setpoint, and the water feed follows through "
                "the ratio, so the reactor's heat load wobbles too."
            ),
            build=_po_pump_surging, grade="Easy",
            evidence=(
                Evidence("FV-201.POS", "erratic",
                         "the PO valve hunts continuously to hold flow against a surging supply",
                         rules_in=("RC-B3",), rules_out=("RC-B1", "RC-B2")),
                Evidence("FIC-201.PV", "erratic", "the PO flow itself wobbles around setpoint"),
                Evidence("FFC-202.SP", "erratic", "the water setpoint follows the PO flow through the ratio"),
                Evidence("PI-301", "flat", "cooling water header steady", rules_out=("RC-B2",)),
                Evidence("TV-202.POS", "erratic", "and the cooling valve follows its demand, so it is healthy",
                         rules_out=("RC-B1",)),
            ),
            walkthrough=(
                "The PO feed valve `FV-201.POS` starts hunting continuously, swinging tens of "
                "percent of travel on a cycle of minutes while the PO flow `FIC-201.PV` "
                "wobbles around its unchanged setpoint. The flow loop is fighting a supply "
                "pressure that surges. Because water is ratioed to the measured PO flow, "
                "`FFC-202.SP` and the water flow wobble in step, and the reactor's heat load "
                "with them, so the jacket loop works harder too. The setpoint never moves, so "
                "this is not an operator change, and the cooling-water header `PI-301` is "
                "steady. The disturbance enters on the PO supply: the feed pump is surging."
            ),
            competitors=("cooling-water valve stiction", "cooling water header surging"),
        ),
        # -- S3 ------------------------------------------------------------
        RootCause(
            id="RC-C1", name="master_left_in_manual", label="TIC-201 left in manual",
            symptom="S3", layer=3, component="TIC-201", masked_by_control=False,
            mechanism=(
                "Nothing is wrong with the plant. The reactor temperature controller was put "
                "in manual and left there, so the jacket setpoint is frozen and reactor "
                "temperature is no longer regulated."
            ),
            build=_left_in_manual, grade="Easy",
            evidence=(
                Evidence("TIC-201.MODE", "steps", "the mode tag reads 0 (MAN)",
                         rules_in=("RC-C1",), rules_out=("RC-C2",)),
                Evidence("TIC-202.SP", "frozen",
                         "the jacket setpoint written by the master stops moving while the "
                         "plant around it keeps changing",
                         rules_in=("RC-C1",)),
                Evidence("TIC-201.PV", "erratic",
                         "reactor temperature wanders off setpoint with the feed temperatures "
                         "and catalyst activity, because nothing is correcting it"),
                Evidence("PI-301", "flat", "cooling water supply is fine", rules_out=("RC-C2",)),
            ),
            walkthrough=(
                "`TIC-201.MODE` changes from 1 (AUTO) to 0 (MAN). The master's output "
                "`TIC-201.OP`, and with it the jacket setpoint `TIC-202.SP`, stops moving, so "
                "the jacket loop holds a fixed jacket temperature and nobody holds the reactor. "
                "Reactor temperature drifts off setpoint with feed temperatures and catalyst "
                "activity for the hours the loop is in manual, then returns once it is back in "
                "AUTO. Cooling water supply is normal. This is not a planned setpoint change, "
                "because `TIC-201.SP` never moves."
            ),
            competitors=("cooling water supply loss",),
        ),
        RootCause(
            id="RC-C2", name="cw_supply_loss", label="Cooling water supply loss",
            symptom="S3", layer=4, component="cooling water header", masked_by_control=False,
            mechanism="The header collapses; there is not enough cooling water at any valve position.",
            build=_cw_loss,
            evidence=(
                Evidence("PI-301", "falls", "header differential pressure collapsed",
                         rules_in=("RC-C2",), rules_out=("RC-C1",)),
                Evidence("TV-202.POS", "rises", "the cooling valve runs to its stop"),
                Evidence("TIC-201.PV", "rises", "reactor temperature climbs"),
                Evidence("TIC-201.MODE", "flat", "the controller is in AUTO", rules_out=("RC-C1",)),
            ),
        ),
        # -- S4 ------------------------------------------------------------
        RootCause(
            id="RC-D1", name="catalyst_deactivation", label="Catalyst deactivation",
            symptom="S4", layer=6, component="acid catalyst",
            mechanism=(
                "Alkaline contamination in the process water neutralises part of the acid "
                "catalyst. The rate constant falls, more PO leaves unreacted, and less heat is "
                "released, so the jacket has less to remove."
            ),
            build=_deactivation, grade="Medium",
            evidence=(
                Evidence("AI-201", "rises", "more PO survives the reactor",
                         rules_in=("RC-D1", "RC-D2"), rules_out=("RC-D3",)),
                Evidence("CALC-QJ", "falls",
                         "less heat comes out of the jacket: the reaction really has slowed",
                         rules_in=("RC-D1",), rules_out=("RC-D2", "RC-D3")),
                Evidence("TV-202.POS", "falls", "the cooling valve closes as the heat load drops"),
                Evidence("TI-204", "flat", "the second temperature element agrees with the first",
                         rules_out=("RC-D3",)),
                Evidence("CALC-MBAL", "flat", "the liquid balance closes", rules_out=("RC-D4", "RC-D5")),
            ),
            walkthrough=(
                "Every loop holds setpoint. The residual PO analyzer `AI-201` climbs over a "
                "few days, so conversion `CALC-CONV` falls. The question is whether the "
                "reaction really slowed or the analyzer is lying. Heat says it is real: the "
                "jacket duty `CALC-QJ` falls and the cooling valve `TV-202.POS` closes, because "
                "less PO reacting means less heat released. The two reactor temperature "
                "elements agree, so the reactor is at the temperature it reports, and the "
                "liquid balance closes, so the feeds are what they read. Slower reaction at the "
                "same temperature and feed means less catalyst activity."
            ),
            competitors=("analyzer calibration drift", "temperature element drift",
                         "feed flowmeter error"),
        ),
        RootCause(
            id="RC-D2", name="analyzer_drift", label="AI-201 calibration drift",
            symptom="S4", layer=7, component="AI-201",
            mechanism="The analyzer reads high. The reaction is unchanged, so no heat signature follows.",
            build=_analyzer_drift,
            evidence=(
                Evidence("AI-201", "rises", "residual PO reading climbs",
                         rules_in=("RC-D1", "RC-D2"), rules_out=("RC-D3",)),
                Evidence("CALC-QJ", "flat", "jacket duty unchanged: the reaction has not slowed",
                         rules_in=("RC-D2",), rules_out=("RC-D1",)),
                Evidence("TI-204", "flat", "temperature elements agree", rules_out=("RC-D3",)),
                Evidence("CALC-MBAL", "flat", "balance closes", rules_out=("RC-D4", "RC-D5")),
            ),
        ),
        RootCause(
            id="RC-D3", name="element_drift", label="Reactor temperature element TE-201 drifting low",
            symptom="S4", layer=7, component="TE-201",
            mechanism=(
                "The control element reads low. TIC-201 faithfully holds the false reading at "
                "setpoint, so the real reactor runs hotter: the reaction speeds up, conversion "
                "rises and more heat must be removed."
            ),
            build=_element_drift, grade="Hard",
            evidence=(
                Evidence("TI-204", "rises",
                         "the independent element reads higher and higher than TIC-201.PV",
                         rules_in=("RC-D3",), rules_out=("RC-D1", "RC-D2", "RC-D4", "RC-D5")),
                Evidence("TIC-201.PV", "flat", "the controlled reading sits on setpoint"),
                Evidence("AI-201", "falls", "less PO survives a hotter reactor",
                         rules_out=("RC-D1", "RC-D2")),
                Evidence("TI-203", "rises", "the product line confirms the reactor is hotter"),
                Evidence("CALC-MBAL", "flat", "balance closes", rules_out=("RC-D4", "RC-D5")),
            ),
            walkthrough=(
                "`TIC-201.PV` sits on setpoint throughout, but the independent element "
                "`TI-204` creeps upward over several days, and the product line temperature "
                "`TI-203` follows `TI-204`, not `TIC-201.PV`. Two of three temperature "
                "readings agree that the reactor is getting hotter. The process confirms it: "
                "residual PO `AI-201` falls (a hotter reactor converts more) and the jacket "
                "removes more heat. The control element is reading low, so the controller is "
                "holding a false temperature."
            ),
            competitors=("catalyst activity change", "analyzer drift", "feed flowmeter error"),
        ),
        RootCause(
            id="RC-D4", name="water_meter_high", label="Process water flowmeter FT-202 reading high",
            symptom="S4", layer=7, component="FT-202",
            mechanism=(
                "The water flow transmitter reads high. FFC-202 holds the false reading on its "
                "ratio setpoint, so the real water flow falls. Less liquid enters than the "
                "meters say, so the liquid balance opens up, and the outlet valve closes to "
                "hold level against the lower true inflow."
            ),
            build=_water_meter_high, grade="Medium",
            evidence=(
                Evidence("CALC-MBAL", "rises", "the feeds read more than the product: the balance opens",
                         rules_in=("RC-D4", "RC-D5"), rules_out=("RC-D1", "RC-D2", "RC-D3")),
                Evidence("LV-201.POS", "falls",
                         "the outlet valve closes to hold level: less liquid is really arriving",
                         rules_in=("RC-D4",), rules_out=("RC-D5",)),
                Evidence("FI-203", "falls", "product flow really is lower"),
                Evidence("CALC-RATIO", "flat", "the measured ratio is still on target"),
                Evidence("TI-204", "flat", "temperature elements agree", rules_out=("RC-D3",)),
            ),
            walkthrough=(
                "Every loop holds setpoint, including the water-to-PO ratio `CALC-RATIO`. The "
                "liquid balance `CALC-MBAL` (feeds minus product) climbs steadily over days. "
                "Either a feed meter reads high or the product meter reads low. The outlet "
                "valve `LV-201.POS` closes over the same days while level holds, so the true "
                "outflow really is falling, by the product relation in the process "
                "description, and `FI-203` is reading correctly. Less liquid is really "
                "arriving than the meters say. The PO flow loop and its valve are steady, and "
                "the water valve `FV-202.POS` has closed a little to hold its flow reading: the "
                "water meter is reading high."
            ),
            competitors=("product flowmeter offset", "catalyst or analyzer change"),
        ),
        RootCause(
            id="RC-D5", name="product_meter_zero", label="Product flowmeter FT-203 zero shift",
            symptom="S4", layer=7, component="FT-203",
            mechanism="A step offset on the product flow reading, typically after maintenance.",
            build=_product_meter_zero,
            evidence=(
                Evidence("CALC-MBAL", "steps", "the residual steps rather than ramping",
                         rules_in=("RC-D5", "RC-D4"), rules_out=("RC-D1", "RC-D2", "RC-D3")),
                Evidence("LV-201.POS", "flat", "outlet valve unmoved: the true outflow is unchanged",
                         rules_in=("RC-D5",), rules_out=("RC-D4",)),
                Evidence("AI-201", "flat", "reaction unchanged", rules_out=("RC-D1", "RC-D2")),
            ),
        ),
    ],
)
