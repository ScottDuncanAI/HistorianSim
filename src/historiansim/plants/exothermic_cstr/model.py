"""R-201: jacketed CSTR hydrolysing propylene oxide to propylene glycol.

Acid-catalysed, with water in large molar excess, so the rate is pseudo-first-
order in propylene oxide (PO). Kinetics and heat of reaction are the published
PO-hydration values (Fogler, *Elements of Chemical Reaction Engineering*),
converted to SI.

What makes it a different diagnostic problem from a heated tank:

* **Heat generation depends on temperature.** The rate rises about 8 % per
  kelvin, so anything that nudges temperature also moves the heat the jacket
  has to remove, and conversion moves with it. The design point is open-loop
  stable -- removal rises about 39 kW/K against 4.4 kW/K for generation -- so
  losing cooling makes temperature climb and settle rather than run away.
* **Cooling, through a jacket with its own dynamics.** The jacket is a state.
  Its outlet temperature is the cascade slave's controlled variable, and the
  approach ``T - Tj`` carries the heat-transfer information that a steam coil's
  pinned saturation temperature hid.
* **Composition is visible**, through an analyzer on residual PO.

Nonlinearity is real, not decoration: Arrhenius kinetics, an equal-percentage
cooling valve whose flow also goes as ``sqrt(dP)``, and outflow as
``sqrt(h)``.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import fsolve

from historiansim.core.valve import inverse_equal_percentage
from historiansim.plants.unit import UnitModel

__all__ = ["ExothermicCSTR"]

_R = 8.314            # J/mol/K
_MIN_LEVEL = 1e-3     # m


class ExothermicCSTR(UnitModel):
    name = "exothermic_cstr"
    state_names = ("h", "C", "T", "Tj")
    mv_names = ("FV-201", "FV-202", "TV-202", "LV-201")
    stiction_params = {"TV-202": "tv_stiction"}
    disturbance_names = (
        "T_amb", "T_cw", "dP_cw", "dP_po", "dP_w", "T_po", "T_w", "cat_activity",
    )

    @staticmethod
    def default_params() -> dict[str, float]:
        return {
            # -- vessel
            "area": 2.0,               # m2
            "h_max": 3.0,              # m
            "Cv_out": 13.4164 / 3600,  # m3/s per unit opening per sqrt(m)
            # -- feeds: F = Cv * x * sqrt(dP)
            "Cv_po": 2.0 / 3600 / (0.5 * math.sqrt(3.0)),   # m3/s per sqrt(bar)
            "Cv_w": 7.0 / 3600 / (0.5 * math.sqrt(3.0)),
            "rho_po": 830.0, "cp_po": 2090.0, "mw_po": 0.05808,
            "rho_w": 1000.0, "cp_w": 4180.0,
            # -- reactor contents (dilute aqueous glycol)
            "rho": 962.0, "cp": 3780.0,
            # -- kinetics: k = k0 exp(-E/RT), 1/s
            "k0": 16.96e12 / 3600.0,
            "E": 75_362.0,             # J/mol
            "dH": -84_666.0,           # J/mol PO
            # -- jacket and cooling water
            "UA_clean": 30_000.0,      # W/K, clean jacket at design agitation
            "V_jacket": 0.6,           # m3
            "F_cw_max": 78.2 / 3600,   # m3/s, valve fully open at design dP
            "dP_cw_design": 2.5,       # bar
            "cw_rangeability": 30.0,
            # -- agitator M-201
            "P_agit": 15_000.0,        # W, motor power at design
            "agit_to_fluid": 0.85,     # share of motor power that heats the batch
            # -- losses
            "UA_loss": 300.0,          # W/K
            # -- fault handles (layer 6)
            "fouling_factor": 1.0,     # surviving fraction of clean jacket UA
            "agit_factor": 1.0,        # impeller pumping capacity, fraction of design
            "cat_factor": 1.0,         # catalyst activity multiplier
            "tv_stiction": 0.0,        # fraction of travel
        }

    def validate_params(self, p):
        for key in ("area", "h_max", "rho", "cp", "V_jacket", "UA_clean"):
            if p[key] <= 0:
                raise ValueError(f"{key} must be positive")
        if p["cw_rangeability"] <= 1.0:
            raise ValueError("valve rangeability must exceed 1")

    # -- building blocks --------------------------------------------------

    def rate_constant(self, temp: float, d: dict, p: dict) -> float:
        """Effective first-order rate constant, 1/s."""
        return (p["k0"] * math.exp(-p["E"] / (_R * (temp + 273.15)))
                * p["cat_factor"] * d["cat_activity"])

    @staticmethod
    def agitation(p: dict) -> float:
        return max(p["agit_factor"], 0.0)

    def jacket_ua(self, p: dict) -> float:
        """Overall jacket UA, W/K.

        Process-side film coefficient goes roughly as agitation^0.6; fouling
        adds a resistance that is represented as a surviving fraction.
        """
        return p["UA_clean"] * p["fouling_factor"] * self.agitation(p) ** 0.6

    def agitator_power(self, p: dict) -> float:
        """Motor power, W. A fixed share is mechanical and electrical loss."""
        return p["P_agit"] * (0.3 + 0.7 * self.agitation(p))

    def cw_flow(self, opening: float, d: dict, p: dict) -> float:
        """Cooling water flow, m3/s: equal-percentage valve on a shared header."""
        x = min(max(opening, 0.0), 1.0)
        dp = max(d["dP_cw"], 0.0)
        return (p["F_cw_max"] * p["cw_rangeability"] ** (x - 1.0)
                * math.sqrt(dp / p["dP_cw_design"]))

    @staticmethod
    def feed_flow(cv: float, opening: float, dp: float) -> float:
        return cv * min(max(opening, 0.0), 1.0) * math.sqrt(max(dp, 0.0))

    def _flows(self, h: float, u: dict, d: dict, p: dict):
        f_po = self.feed_flow(p["Cv_po"], u["FV-201"], d["dP_po"])
        f_w = self.feed_flow(p["Cv_w"], u["FV-202"], d["dP_w"])
        f_out = p["Cv_out"] * max(u["LV-201"], 0.0) * math.sqrt(max(h, _MIN_LEVEL))
        return f_po, f_w, f_out

    # -- physics ----------------------------------------------------------

    def derivatives(self, t, x, u, d, p) -> np.ndarray:
        h, conc, temp, tj = x[0], x[1], x[2], x[3]
        h_eff = h if h > _MIN_LEVEL else _MIN_LEVEL
        volume = p["area"] * h_eff
        f_po, f_w, f_out = self._flows(h_eff, u, d, p)
        f_in = f_po + f_w
        c_feed = p["rho_po"] / p["mw_po"]

        k = self.rate_constant(temp, d, p)
        rate = k * conc                                 # mol/m3/s
        ua = self.jacket_ua(p)
        q_jacket = ua * (temp - tj)
        q_agit = p["agit_to_fluid"] * self.agitator_power(p)

        dh = (f_in - f_out) / p["area"]
        dc = (f_po * c_feed - f_in * conc) / volume - rate
        mcp = p["rho"] * p["cp"] * volume
        dT = (
            p["rho_po"] * p["cp_po"] * f_po * (d["T_po"] - temp)
            + p["rho_w"] * p["cp_w"] * f_w * (d["T_w"] - temp)
            + (-p["dH"]) * rate * volume
            - q_jacket
            - p["UA_loss"] * (temp - d["T_amb"])
            + q_agit
        ) / mcp
        f_cw = self.cw_flow(u["TV-202"], d, p)
        mcp_j = p["rho_w"] * p["cp_w"] * p["V_jacket"]
        dTj = (p["rho_w"] * p["cp_w"] * f_cw * (d["T_cw"] - tj) + q_jacket) / mcp_j
        return np.array((dh, dc, dT, dTj))

    # -- observables ------------------------------------------------------

    def residual_po_wt(self, conc: float, p: dict) -> float:
        """Residual PO in the product, wt %."""
        return 100.0 * conc * p["mw_po"] / p["rho"]

    def signals(self, t, x, u, d, p) -> dict[str, float]:
        h, conc, temp, tj = (float(v) for v in x)
        h_eff = max(h, _MIN_LEVEL)
        f_po, f_w, f_out = self._flows(h_eff, u, d, p)
        f_cw = self.cw_flow(u["TV-202"], d, p)
        q_jacket = self.jacket_ua(p) * (temp - tj)
        po_in_wt = 100.0 * f_po * p["rho_po"] / max(f_po * p["rho_po"] + f_w * p["rho_w"], 1e-12)
        residual = self.residual_po_wt(conc, p)
        approach = max(temp - tj, 1e-6)
        return {
            "LI-201": h,
            "TI-201": temp,
            "TI-202": tj,
            "FI-201": f_po * 3600.0,
            "FI-202": f_w * 3600.0,
            "FI-203": f_out * 3600.0,
            "TI-101": d["T_po"],
            "TI-102": d["T_w"],
            "TI-203": temp,
            "AI-201": residual,
            "TI-301": d["T_cw"],
            "PI-301": d["dP_cw"],
            "FI-301": f_cw * 3600.0,
            "JI-201": self.agitator_power(p) / 1000.0,
            "TI-901": d["T_amb"],
            "CALC-QJ": q_jacket / 1000.0,
            "CALC-UA": q_jacket / 1000.0 / approach,
            "CALC-MBAL": (f_po + f_w - f_out) * 3600.0,
            "CALC-RATIO": f_w / max(f_po, 1e-12),
            "CALC-CONV": 100.0 * (1.0 - residual / max(po_in_wt, 1e-9)),
        }

    # -- equilibrium ------------------------------------------------------

    def _reaction_state(self, temp: float, f_po: float, f_w: float, volume: float,
                        d: dict, p: dict) -> tuple[float, float]:
        """Steady PO concentration and heat release at a given temperature."""
        k = self.rate_constant(temp, d, p)
        f_in = f_po + f_w
        conc = f_po * p["rho_po"] / p["mw_po"] / (f_in + k * volume)
        return conc, (-p["dH"]) * k * conc * volume

    def _required_jacket_duty(self, temp, f_po, f_w, volume, d, p) -> tuple[float, float]:
        conc, q_rx = self._reaction_state(temp, f_po, f_w, volume, d, p)
        q = (
            p["rho_po"] * p["cp_po"] * f_po * (d["T_po"] - temp)
            + p["rho_w"] * p["cp_w"] * f_w * (d["T_w"] - temp)
            + q_rx
            - p["UA_loss"] * (temp - d["T_amb"])
            + p["agit_to_fluid"] * self.agitator_power(p)
        )
        return conc, q

    def steady_inputs(self, targets, d, p) -> dict[str, float]:
        """Valve positions that hold the targets at equilibrium.

        ``targets`` must give ``FI-201``, ``FI-202``, ``LI-201`` and ``TI-201``.
        The jacket temperature is not free: it follows from the duty and UA.
        """
        f_po = targets["FI-201"] / 3600.0
        f_w = targets["FI-202"] / 3600.0
        h = targets["LI-201"]
        temp = targets["TI-201"]
        volume = p["area"] * h

        _, q_jacket = self._required_jacket_duty(temp, f_po, f_w, volume, d, p)
        if q_jacket <= 0:
            raise ValueError("no cooling needed at this design point; the jacket cannot heat")
        tj = temp - q_jacket / self.jacket_ua(p)
        if tj <= d["T_cw"]:
            raise ValueError("cooling water is too warm to remove the heat at this UA")
        f_cw = q_jacket / (p["rho_w"] * p["cp_w"] * (tj - d["T_cw"]))
        frac = f_cw / (p["F_cw_max"] * math.sqrt(max(d["dP_cw"], 1e-9) / p["dP_cw_design"]))
        return {
            "FV-201": f_po / (p["Cv_po"] * math.sqrt(d["dP_po"])),
            "FV-202": f_w / (p["Cv_w"] * math.sqrt(d["dP_w"])),
            "TV-202": float(inverse_equal_percentage(frac, p["cw_rangeability"])),
            "LV-201": (f_po + f_w) / (p["Cv_out"] * math.sqrt(h)),
        }

    def steady_state(self, u, d, p) -> np.ndarray:
        """Equilibrium states for fixed valve positions, solved numerically."""
        f_po = self.feed_flow(p["Cv_po"], u["FV-201"], d["dP_po"])
        f_w = self.feed_flow(p["Cv_w"], u["FV-202"], d["dP_w"])
        f_in = f_po + f_w
        h = (f_in / (p["Cv_out"] * max(u["LV-201"], 1e-9))) ** 2
        volume = p["area"] * h

        def residual(z):
            temp, tj = z
            conc, q_jacket_needed = self._required_jacket_duty(temp, f_po, f_w, volume, d, p)
            ua = self.jacket_ua(p)
            f_cw = self.cw_flow(u["TV-202"], d, p)
            return [
                q_jacket_needed - ua * (temp - tj),
                p["rho_w"] * p["cp_w"] * f_cw * (d["T_cw"] - tj) + ua * (temp - tj),
            ]

        temp, tj = fsolve(residual, [60.0, 49.0], xtol=1e-12)
        conc, _ = self._reaction_state(temp, f_po, f_w, volume, d, p)
        return np.array([h, conc, temp, tj])
