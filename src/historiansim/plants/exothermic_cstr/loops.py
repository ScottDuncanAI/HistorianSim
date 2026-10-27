"""Control loops and disturbance channels of R-201."""

from __future__ import annotations

from historiansim.config.schema import ChannelConfig, LoopConfig
from historiansim.plants.exothermic_cstr.model import ExothermicCSTR

__all__ = ["DESIGN_D", "DESIGN_TARGETS", "RATIO", "design_point", "cstr_loops", "cstr_channels"]

#: Design-point disturbance vector, SI units (pressures in bar).
DESIGN_D = {
    "T_amb": 20.0,
    "T_cw": 29.0,
    "dP_cw": 2.5,
    "dP_po": 3.0,
    "dP_w": 3.0,
    "T_po": 20.0,
    "T_w": 30.0,
    "cat_activity": 1.0,
}

#: Water-to-PO volumetric feed ratio held by FFC-202.
RATIO = 3.5

DESIGN_TARGETS = {"FI-201": 2.0, "FI-202": 2.0 * RATIO, "LI-201": 1.8, "TI-201": 60.0}


def design_point():
    """Valve positions, states and signals at the design point."""
    unit = ExothermicCSTR()
    p = unit.params
    u = unit.steady_inputs(DESIGN_TARGETS, DESIGN_D, p)
    x = unit.steady_state(u, DESIGN_D, p)
    return unit, u, x, unit.signals(0.0, x, u, DESIGN_D, p)


def cstr_loops() -> list[LoopConfig]:
    """Reactor temperature cascaded onto jacket temperature; ratioed feeds; level.

    The jacket slave's setpoint is the jacket temperature the design point
    actually needs -- computed, not rounded -- so the run opens at rest.
    """
    _, _, x, _ = design_point()
    return [
        LoopConfig(
            name="TIC-201", pv_source="TI-201", mv_tag="TIC-201.OUT",
            kc=0.025, ti=900.0, sp=DESIGN_TARGETS["TI-201"], action="reverse",
            cascade_to="TIC-202",
        ),
        LoopConfig(
            name="TIC-202", pv_source="TI-202", mv_tag="TV-202",
            kc=0.02, ti=120.0, sp=float(x[3]), action="direct",
            mode="CAS", sp_limits=(5.0, 70.0),
        ),
        LoopConfig(
            name="FIC-201", pv_source="FI-201", mv_tag="FV-201",
            kc=0.08, ti=30.0, sp=DESIGN_TARGETS["FI-201"], action="reverse",
        ),
        LoopConfig(
            name="FFC-202", pv_source="FI-202", mv_tag="FV-202",
            kc=0.025, ti=30.0, sp=DESIGN_TARGETS["FI-202"], action="reverse",
            mode="CAS", ratio_to="FI-201", ratio=RATIO,
        ),
        LoopConfig(
            name="LIC-201", pv_source="LI-201", mv_tag="LV-201",
            kc=1.5, ti=600.0, sp=DESIGN_TARGETS["LI-201"], action="direct",
        ),
    ]


def cstr_channels() -> dict[str, ChannelConfig]:
    return {
        "T_cw": ChannelConfig(
            mean=29.0, units="degC", description="Cooling water supply temperature",
            # A cooling tower tracks the wet-bulb temperature, so the supply
            # follows the weather closely: the dominant common-cause driver.
            ambient_coupling=0.55, sigma=0.35, tau_s=2400.0,
        ),
        "dP_cw": ChannelConfig(
            mean=2.5, units="bar", description="Cooling water header differential pressure",
            sigma=0.04, tau_s=1800.0, diurnal_amplitude=0.05, diurnal_peak_hour=4.0,
        ),
        "dP_po": ChannelConfig(
            mean=3.0, units="bar", description="PO supply pressure across FV-201",
            sigma=0.06, tau_s=1200.0,
        ),
        "dP_w": ChannelConfig(
            mean=3.0, units="bar", description="Process water supply pressure across FV-202",
            sigma=0.05, tau_s=1500.0,
        ),
        "T_po": ChannelConfig(
            mean=20.0, units="degC", description="PO feed temperature from storage",
            ambient_coupling=0.30, sigma=0.4, tau_s=7200.0,
        ),
        "T_w": ChannelConfig(
            mean=30.0, units="degC", description="Process water temperature",
            ambient_coupling=0.20, sigma=0.5, tau_s=3600.0,
        ),
        "cat_activity": ChannelConfig(
            mean=1.0, units="-", description="Acid catalyst activity (make-up strength)",
            sigma=0.01, tau_s=6 * 3600.0,
        ),
    }
