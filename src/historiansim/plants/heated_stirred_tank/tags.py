"""Historian tags of the heated stirred tank, and its DCS calculations."""

from __future__ import annotations

import numpy as np

from historiansim.tags import TagSpec

__all__ = ["tank_tags", "recompute_dcs_calculations"]


def tank_tags() -> list[TagSpec]:
    """The 28 real tags of the tank unit."""
    return [
        # -- temperature loop (master of the steam flow cascade) -----------
        TagSpec("TIC-101.PV", "Tank temperature", "degC", 0, 120, "temperature_slow",
                "PV", source="TI-101", loop="TIC-101", node="NODE-A"),
        TagSpec("TIC-101.SP", "Tank temperature setpoint", "degC", 0, 120, "status",
                "SP", source="TIC-101.SP", loop="TIC-101", node="NODE-A"),
        TagSpec("TIC-101.OP", "Tank temperature controller output", "%", 0, 100, "valve",
                "OP", source="TIC-101.OP", loop="TIC-101", node="NODE-A"),
        TagSpec("TIC-101.MODE", "Tank temperature controller mode", "-", 0, 2, "status",
                "MODE", source="TIC-101.MODE", loop="TIC-101", node="NODE-A"),

        # -- steam flow loop (cascade slave) -------------------------------
        TagSpec("FIC-201.PV", "Steam flow to coil", "kg/h", 0, 3000, "flow",
                "PV", source="FI-201", loop="FIC-201", node="NODE-A"),
        TagSpec("FIC-201.SP", "Steam flow setpoint", "kg/h", 0, 3000, "status",
                "SP", source="FIC-201.SP", loop="FIC-201", node="NODE-A"),
        TagSpec("FIC-201.OP", "Steam valve demand", "%", 0, 100, "valve",
                "OP", source="FIC-201.OP", loop="FIC-201", node="NODE-A"),
        TagSpec("FIC-201.MODE", "Steam flow controller mode", "-", 0, 2, "status",
                "MODE", source="FIC-201.MODE", loop="FIC-201", node="NODE-A"),

        # -- level loop ----------------------------------------------------
        TagSpec("LIC-101.PV", "Tank level", "m", 0, 4, "level",
                "PV", source="LI-101", loop="LIC-101", node="NODE-B"),
        TagSpec("LIC-101.SP", "Tank level setpoint", "m", 0, 4, "status",
                "SP", source="LIC-101.SP", loop="LIC-101", node="NODE-B"),
        TagSpec("LIC-101.OP", "Outlet valve demand", "%", 0, 100, "valve",
                "OP", source="LIC-101.OP", loop="LIC-101", node="NODE-B"),
        TagSpec("LIC-101.MODE", "Level controller mode", "-", 0, 2, "status",
                "MODE", source="LIC-101.MODE", loop="LIC-101", node="NODE-B"),

        # -- valve position feedback ---------------------------------------
        TagSpec("TV-101.POS", "Steam valve position feedback", "%", 0, 100, "valve",
                "IND", source="TV-101", node="NODE-A"),
        TagSpec("LV-101.POS", "Outlet valve position feedback", "%", 0, 100, "valve",
                "IND", source="LV-101", node="NODE-B"),

        # -- indicators ----------------------------------------------------
        TagSpec("FI-101", "Feed flow from upstream storage", "m3/h", 0, 30, "flow",
                "IND", source="FI-101", node="NODE-B"),
        TagSpec("TI-100", "Feed temperature", "degC", 0, 60, "temperature",
                "IND", source="TI-100", node="NODE-B"),
        TagSpec("FI-102", "Product flow", "m3/h", 0, 30, "flow",
                "IND", source="FI-102", node="NODE-B", transport_lag_s=120.0),
        TagSpec("TI-102", "Product line temperature", "degC", 0, 120, "temperature",
                "IND", source="TI-102", node="NODE-B", transport_lag_s=180.0),
        TagSpec("LI-102", "Tank level, redundant transmitter", "m", 0, 4, "level",
                "IND", source="LI-101", node="NODE-C"),
        TagSpec("PI-201", "Steam header pressure", "barg", 0, 12, "pressure",
                "IND", source="PI-201", node="NODE-A"),
        TagSpec("TI-201", "Steam saturation temperature", "degC", 0, 220, "temperature",
                "IND", source="TI-201", node="NODE-A"),
        TagSpec("TI-202", "Condensate return temperature", "degC", 0, 220, "temperature",
                "IND", source="TI-202", node="NODE-A", transport_lag_s=240.0),
        TagSpec("TI-901", "Ambient temperature", "degC", -30, 50, "temperature",
                "IND", source="TI-901", node="NODE-C"),
        TagSpec("AI-101", "Product purity analyzer (desired product in dissolved organics)", "%", 90, 100, "analyzer",
                "IND", source="CALC-PURITY", node="NODE-C", transport_lag_s=480.0),

        # -- DCS calculations ------------------------------------------------
        # Recomputed in the measurement layer from the *measured* tags above,
        # never from the true process values. This is the whole reason an
        # instrument fault is detectable: a drifting transmitter opens up a
        # balance built on its reading while every real quantity is unchanged.
        # Deriving these from truth would make transmitter faults invisible to
        # exactly the tags meant to reveal them.
        TagSpec("CALC-DUTY", "Coil duty, steam side", "kW", 0, 2000, "calculated",
                "CALC", source="CALC-DUTY", node="NODE-A"),
        TagSpec("CALC-DUTY-PROC", "Coil duty, process side", "kW", 0, 2000,
                "calculated", "CALC", source="CALC-DUTY", node="NODE-B"),
        TagSpec("CALC-EBAL", "Energy balance gap, steam minus process", "kW",
                -500, 500, "calculated", "CALC", source="CALC-DUTY", node="NODE-A"),
        TagSpec("CALC-UA", "Back-calculated coil UA", "W/K", 0, 30000, "calculated",
                "CALC", source="CALC-UA", node="NODE-A"),
        TagSpec("CALC-APPROACH", "Steam to bulk approach", "K", 0, 200, "calculated",
                "CALC", source="CALC-APPROACH", node="NODE-A"),
        TagSpec("CALC-MBAL", "Mass balance residual", "m3/h", -10, 10, "calculated",
                "CALC", source="CALC-MBAL", node="NODE-B"),
    ]


def recompute_dcs_calculations(values: dict, params: dict | None = None) -> None:
    """Rebuild the CALC-* tags from measured tags, in place.

    What a DCS actually does: it has no access to the true state, only to the
    transmitter readings, so every derived value inherits their errors. That
    inheritance is the entire diagnostic content of the S4 symptom class.
    """
    from historiansim.core.steam import h_fg

    p = params or {"rho": 1000.0, "cp": 4180.0}

    steam = values.get("FIC-201.PV")
    t_sat_meas = values.get("TI-201")
    t_tank = values.get("TIC-101.PV")
    feed = values.get("FI-101")
    t_feed = values.get("TI-100")
    product = values.get("FI-102")

    if steam is not None and t_sat_meas is not None:
        duty_steam = steam / 3600.0 * h_fg(t_sat_meas) / 1000.0
        values["CALC-DUTY"] = duty_steam
        if t_tank is not None:
            approach = np.maximum(t_sat_meas - t_tank, 1e-6)
            values["CALC-APPROACH"] = approach
            values["CALC-UA"] = duty_steam * 1000.0 / approach

    if feed is not None and t_tank is not None and t_feed is not None:
        duty_proc = feed / 3600.0 * p["rho"] * p["cp"] * (t_tank - t_feed) / 1000.0
        values["CALC-DUTY-PROC"] = duty_proc
        if "CALC-DUTY" in values:
            values["CALC-EBAL"] = values["CALC-DUTY"] - duty_proc

    if feed is not None and product is not None:
        values["CALC-MBAL"] = feed - product
