"""Historian tags of R-201, and its DCS calculations."""

from __future__ import annotations

import numpy as np

from historiansim.tags import TagSpec

__all__ = ["cstr_tags", "recompute_dcs_calculations"]


def _loop(name, desc, units, lo, hi, instrument, source, node, op_desc, sp_desc):
    return [
        TagSpec(f"{name}.PV", desc, units, lo, hi, instrument, "PV",
                source=source, loop=name, node=node),
        TagSpec(f"{name}.SP", sp_desc, units, lo, hi, "status", "SP",
                source=f"{name}.SP", loop=name, node=node),
        TagSpec(f"{name}.OP", op_desc, "%", 0, 100, "valve", "OP",
                source=f"{name}.OP", loop=name, node=node),
        TagSpec(f"{name}.MODE", f"{desc} controller mode", "-", 0, 2, "status", "MODE",
                source=f"{name}.MODE", loop=name, node=node),
    ]


def cstr_tags() -> list[TagSpec]:
    """The 39 tags of the reactor unit."""
    return [
        *_loop("TIC-201", "Reactor temperature", "degC", 0, 120, "temperature_slow",
               "TI-201", "NODE-A", "Reactor temperature controller output",
               "Reactor temperature setpoint"),
        *_loop("TIC-202", "Jacket outlet temperature", "degC", 0, 100, "temperature",
               "TI-202", "NODE-A", "Cooling water valve demand",
               "Jacket temperature setpoint"),
        *_loop("FIC-201", "PO feed flow", "m3/h", 0, 4, "flow",
               "FI-201", "NODE-B", "PO feed valve demand", "PO feed flow setpoint"),
        *_loop("FFC-202", "Process water feed flow", "m3/h", 0, 12, "flow",
               "FI-202", "NODE-B", "Process water valve demand",
               "Process water flow setpoint"),
        *_loop("LIC-201", "Reactor level", "m", 0, 3, "level",
               "LI-201", "NODE-C", "Outlet valve demand", "Reactor level setpoint"),

        # -- valve position feedback
        TagSpec("TV-202.POS", "Cooling water valve position feedback", "%", 0, 100, "valve",
                "IND", source="TV-202", node="NODE-A"),
        TagSpec("FV-201.POS", "PO feed valve position feedback", "%", 0, 100, "valve",
                "IND", source="FV-201", node="NODE-B"),
        TagSpec("FV-202.POS", "Process water valve position feedback", "%", 0, 100, "valve",
                "IND", source="FV-202", node="NODE-B"),
        TagSpec("LV-201.POS", "Outlet valve position feedback", "%", 0, 100, "valve",
                "IND", source="LV-201", node="NODE-C"),

        # -- indicators
        TagSpec("TI-204", "Reactor temperature, second element", "degC", 0, 120,
                "temperature_slow", "IND", source="TI-201", node="NODE-C"),
        TagSpec("TI-101", "PO feed temperature", "degC", 0, 60, "temperature",
                "IND", source="TI-101", node="NODE-B"),
        TagSpec("TI-102", "Process water feed temperature", "degC", 0, 80, "temperature",
                "IND", source="TI-102", node="NODE-B"),
        TagSpec("FI-203", "Product flow", "m3/h", 0, 15, "flow",
                "IND", source="FI-203", node="NODE-C", transport_lag_s=60.0),
        TagSpec("TI-203", "Product line temperature", "degC", 0, 120, "temperature",
                "IND", source="TI-203", node="NODE-C", transport_lag_s=120.0),
        TagSpec("AI-201", "Residual PO analyzer on product", "wt%", 0, 5, "analyzer",
                "IND", source="AI-201", node="NODE-C", transport_lag_s=480.0),
        TagSpec("TI-301", "Cooling water supply temperature", "degC", 0, 60, "temperature",
                "IND", source="TI-301", node="NODE-A"),
        TagSpec("PI-301", "Cooling water header differential pressure", "bar", 0, 6,
                "pressure", "IND", source="PI-301", node="NODE-A"),
        TagSpec("FI-301", "Cooling water flow to jacket", "m3/h", 0, 60, "flow",
                "IND", source="FI-301", node="NODE-A"),
        TagSpec("JI-201", "Agitator M-201 motor power", "kW", 0, 25, "power",
                "IND", source="JI-201", node="NODE-C"),
        TagSpec("TI-901", "Ambient temperature", "degC", -30, 50, "temperature",
                "IND", source="TI-901", node="NODE-C"),

        # -- DCS calculations, rebuilt from measured tags (never from truth)
        TagSpec("CALC-QJ", "Jacket duty, cooling water side", "kW", -200, 1200,
                "calculated", "CALC", source="CALC-QJ", node="NODE-A"),
        TagSpec("CALC-UA", "Back-calculated jacket UA", "kW/K", 0, 60,
                "calculated", "CALC", source="CALC-UA", node="NODE-A"),
        TagSpec("CALC-MBAL", "Liquid balance residual, feeds minus product", "m3/h",
                -5, 5, "calculated", "CALC", source="CALC-MBAL", node="NODE-B"),
        TagSpec("CALC-RATIO", "Measured water to PO feed ratio", "-", 0, 10,
                "calculated", "CALC", source="CALC-RATIO", node="NODE-B"),
        TagSpec("CALC-CONV", "PO conversion from analyzer and feed flows", "%", 0, 100,
                "calculated", "CALC", source="CALC-CONV", node="NODE-C"),
    ]


def recompute_dcs_calculations(values: dict, params: dict | None = None) -> None:
    """Rebuild the CALC-* tags from measured tags, in place.

    The DCS only has the transmitter readings, so every derived value inherits
    their errors -- which is the whole diagnostic content of an instrument
    fault.
    """
    p = params or {"rho_w": 1000.0, "cp_w": 4180.0, "rho_po": 830.0}
    cw = values.get("FI-301")
    t_sup = values.get("TI-301")
    t_jac = values.get("TIC-202.PV")
    t_rx = values.get("TIC-201.PV")
    f_po = values.get("FIC-201.PV")
    f_w = values.get("FFC-202.PV")
    f_out = values.get("FI-203")
    ai = values.get("AI-201")

    if cw is not None and t_sup is not None and t_jac is not None:
        qj = cw / 3600.0 * p["rho_w"] * p["cp_w"] * (t_jac - t_sup) / 1000.0
        values["CALC-QJ"] = qj
        if t_rx is not None:
            values["CALC-UA"] = qj / np.maximum(t_rx - t_jac, 1e-3)
    if f_po is not None and f_w is not None:
        if f_out is not None:
            values["CALC-MBAL"] = f_po + f_w - f_out
        values["CALC-RATIO"] = f_w / np.maximum(f_po, 1e-3)
        if ai is not None:
            po_in = 100.0 * f_po * p["rho_po"] / np.maximum(
                f_po * p["rho_po"] + f_w * p["rho_w"], 1e-6
            )
            values["CALC-CONV"] = 100.0 * (1.0 - ai / np.maximum(po_in, 1e-6))
