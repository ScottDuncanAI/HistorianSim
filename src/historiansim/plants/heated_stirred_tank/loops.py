"""Control loops and disturbance channels of the heated stirred tank."""

from __future__ import annotations

import numpy as np

from historiansim.config.schema import ChannelConfig, LoopConfig
from historiansim.plants.heated_stirred_tank.model import HeatedStirredTank

__all__ = ["DESIGN_D", "design_steam_flow", "tank_loops", "tank_channels"]

#: Design-point disturbance vector, SI units.
DESIGN_D = {
    "feed_flow": 15 / 3600.0,
    "feed_temp": 25.0,
    "T_amb": 20.0,
    "steam_header_P": 6.0,
}


def design_steam_flow() -> float:
    """Steam flow at the design point, from the physics rather than a round number.

    The cascade slave's setpoint has to match the true equilibrium exactly, or
    the run opens with a transient and the clean baseline is not clean.
    """
    unit = HeatedStirredTank()
    u = unit.steady_inputs({"LI-101": 2.0, "TI-101": 75.0}, DESIGN_D, unit.params)
    return unit.signals(0.0, np.array([2.0, 75.0]), u, DESIGN_D, unit.params)["FI-201"]


def tank_loops() -> list[LoopConfig]:
    """Temperature cascaded onto steam flow, plus level.

    The level loop is deliberately left a little loose and the temperature loop
    a little slow. Every real plant has loops that are not perfectly tuned, and
    a dataset where all of them are is its own kind of tell.
    """
    return [
        LoopConfig(
            name="TIC-101", pv_source="TI-101", mv_tag="TIC-101.OUT",
            kc=0.045, ti=900.0, sp=75.0, action="reverse", cascade_to="FIC-201",
        ),
        LoopConfig(
            name="FIC-201", pv_source="FI-201", mv_tag="TV-101",
            kc=0.00015, ti=60.0, sp=design_steam_flow(), action="reverse",
            mode="CAS", sp_limits=(0.0, 3000.0),
        ),
        LoopConfig(
            name="LIC-101", pv_source="LI-101", mv_tag="LV-101",
            kc=2.0, ti=600.0, sp=2.0, action="direct",
        ),
    ]


def tank_channels() -> dict[str, ChannelConfig]:
    """Feed from upstream storage and the shared steam header."""
    return {
        "feed_flow": ChannelConfig(
            mean=15.0, units="m3/h", description="Feed rate set by the upstream unit",
            sigma=0.30, tau_s=900.0, floor=0.0, si_divisor=3600.0,
        ),
        "feed_temp": ChannelConfig(
            mean=25.0, units="degC", description="Feed temperature",
            # Partly follows ambient through upstream tankage, partly does its
            # own thing. That shared component is common-cause correlation.
            ambient_coupling=0.35, sigma=0.8, tau_s=3600.0,
        ),
        "steam_header_P": ChannelConfig(
            mean=6.0, units="barg", description="Steam header pressure",
            # Shared with units outside this dataset, so it sags when
            # plant-wide demand peaks and wanders with their swings.
            sigma=0.10, tau_s=1800.0, diurnal_amplitude=0.07, diurnal_peak_hour=3.0,
            rng_stream="steam_header",
        ),
    }
