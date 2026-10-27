"""Heated stirred tank with a steam coil.

The reference unit. In service terms it is a hydrolysis and ageing hold tank on
a dilute aqueous process stream: feed from upstream reaction storage is held at
temperature for around half an hour so a residual intermediate finishes
hydrolysing, then passes to downstream recovery. The fluid is dilute enough that
water dominates its thermal properties. Two controlled variables (level and temperature), a
nonlinear outlet valve, an equal-percentage steam valve, and a coil whose heat
transfer is degraded by three physically distinct mechanisms that a naive look
at the trends cannot tell apart.

Nonlinearity is not decoration here:

* Outflow goes as ``sqrt(h)``, so level-loop gain changes with level. A loop
  tuned at 60 % level cycles at 30 %, which is what makes "operating point
  shift" a real competing explanation for a cycling level loop.
* The steam valve is equal-percentage, so its gain is proportional to its own
  flow. As fouling drives the valve open the temperature loop gets *more*
  aggressive. Nobody schedules that; it falls out of the trim.
* Ambient enters the heat-loss term, so every temperature picks up a diurnal
  component without a diurnal component being written anywhere.

Design point (see :meth:`default_params`): 15 m3/h of 25 degC feed heated to
75 degC in a 6.3 m3 working volume, steam from a 6 barg header. That leaves the
steam valve near 50 % open with a clean coil -- real headroom for degradation
to consume before the loop saturates.

**Why there is no coil-pressure state.** A first cut modelled coil pressure as
a state. Its time constant works out near 1 second against a 10 second scan, so
it is a stiff nuisance that would force a 25x smaller integration step to
resolve dynamics no instrument in the dataset can see. It is treated as
quasi-steady instead: steam temperature follows header pressure directly. This
is the standard singular-perturbation argument, and it costs nothing
diagnostically because every discriminating signature survives it.
"""

from __future__ import annotations

import math

import numpy as np

from historiansim.core.steam import h_fg, t_sat
from historiansim.core.valve import inverse_equal_percentage
from historiansim.plants.unit import UnitModel

__all__ = ["HeatedStirredTank"]

_MIN_LEVEL = 1e-3  # m, keeps sqrt() and division by volume well posed


class HeatedStirredTank(UnitModel):
    name = "heated_stirred_tank"
    state_names = ("h", "T")
    mv_names = ("LV-101", "TV-101")

    #: Manipulated variable -> parameter holding its stiction band. The driver
    #: inserts a sticking stem between controller and process wherever the band
    #: is non-zero, so the position the physics sees differs from the demand.
    stiction_params = {"LV-101": "lv_stiction", "TV-101": "tv_stiction"}
    disturbance_names = ("feed_flow", "feed_temp", "T_amb", "steam_header_P")

    @staticmethod
    def default_params() -> dict[str, float]:
        return {
            # -- geometry
            "area": 3.14,            # m2, cross-section of a 2 m diameter vessel
            "h_max": 4.0,            # m, tank height
            # -- fluid properties (water-like)
            "rho": 1000.0,           # kg/m3
            "cp": 4180.0,            # J/kg/K
            # -- outlet valve: F_out = Cv_out * opening * sqrt(h)
            "Cv_out": 0.0059,        # m3/s per unit opening per sqrt(m)
            # -- steam coil
            "UA_coil": 72000.0,      # W/K, clean coil at full valve flow
            "valve_rangeability": 50.0,   # equal-percentage trim, R
            "w_steam_design": 0.426,      # kg/s at the design point
            # -- condensate handling
            "subcool_base": 5.0,     # K below saturation, healthy trap
            "subcool_flood": 40.0,   # K of extra subcooling at full flooding
            # -- heat loss to surroundings
            "UA_loss": 500.0,        # W/K
            # -- product quality correlation
            "purity_peak_T": 78.0,   # degC at which purity is highest
            "purity_curvature": 0.02,  # % purity lost per K^2 away from the peak
            # -- degradation and fault handles, all layer 5/6 parameters
            "fouling_factor": 1.0,   # surviving fraction of clean UA
            "flooded_fraction": 0.0, # coil area lost to condensate backup
            "blowthrough": 0.0,      # live steam lost through a failed trap,
                                     #   as a fraction of design steam flow
            "leak_coeff": 0.0,       # m3/s per sqrt(m), vessel leak
            "lv_stiction": 0.0,      # fraction of travel, level valve friction band
            "tv_stiction": 0.0,      # fraction of travel, steam valve friction band
        }

    def validate_params(self, p: dict[str, float]) -> None:
        if p["area"] <= 0 or p["h_max"] <= 0:
            raise ValueError("tank geometry must be positive")
        if p["rho"] <= 0 or p["cp"] <= 0:
            raise ValueError("fluid properties must be positive")
        for key in ("fouling_factor", "flooded_fraction"):
            if not 0.0 <= p[key] <= 1.0:
                raise ValueError(f"{key} must be a fraction in [0, 1]")
        if p["valve_rangeability"] <= 1.0:
            raise ValueError("valve rangeability must exceed 1")

    # -- steam side (quasi-steady) ----------------------------------------

    @staticmethod
    def _valve_flow_fraction(opening: float, rangeability: float) -> float:
        """Equal-percentage installed characteristic."""
        x = min(max(opening, 0.0), 1.0)
        return rangeability ** (x - 1.0)

    def effective_ua(self, opening: float, p: dict[str, float]) -> float:
        """Heat transfer coefficient actually available, W/K.

        Three independent degradation paths multiply together, and this is the
        crux of the whole dataset: fouling and condensate backup enter the
        physics at exactly the same place. No amount of staring at the steam
        valve distinguishes them. Only the *other* tags do -- condensate
        temperature, and whether the loss is smooth or erratic.
        """
        surviving = p["fouling_factor"] * (1.0 - p["flooded_fraction"])
        return (
            p["UA_coil"]
            * surviving
            * self._valve_flow_fraction(opening, p["valve_rangeability"])
        )

    def coil_duty(self, temp: float, opening: float, d: dict, p: dict) -> float:
        """Heat delivered to the tank, W. Never negative -- a steam coil cannot
        cool the vessel."""
        driving = t_sat(d["steam_header_P"]) - temp
        if driving <= 0.0:
            return 0.0
        return self.effective_ua(opening, p) * driving

    # -- physics ----------------------------------------------------------

    def derivatives(self, t, x, u, d, p) -> np.ndarray:
        # Called four times per integration sub-step for the whole campaign --
        # tens of millions of times -- so it uses scalar math and local
        # bindings rather than numpy scalar ops, which are ~8x slower.
        h = x[0]
        temp = x[1]
        h_eff = h if h > _MIN_LEVEL else _MIN_LEVEL
        area = p["area"]
        volume = area * h_eff
        root_h = math.sqrt(h_eff)

        f_in = d["feed_flow"]
        f_out = p["Cv_out"] * max(u["LV-101"], 0.0) * root_h
        f_leak = p["leak_coeff"] * root_h

        heat_in = self.coil_duty(temp, u["TV-101"], d, p)
        heat_loss = p["UA_loss"] * (temp - d["T_amb"])

        dh = (f_in - f_out - f_leak) / area
        dT = (
            f_in * (d["feed_temp"] - temp) / volume
            + (heat_in - heat_loss) / (p["rho"] * p["cp"] * volume)
        )
        return np.array((dh, dT))

    @staticmethod
    def outlet_flow(h: float, opening: float, p: dict[str, float]) -> float:
        """Nonlinear outlet valve. The sqrt is where level-loop gain variation
        comes from."""
        return p["Cv_out"] * max(opening, 0.0) * math.sqrt(max(h, _MIN_LEVEL))

    # -- observables ------------------------------------------------------

    def signals(self, t, x, u, d, p) -> dict[str, float]:
        h = float(x[0])
        temp = float(x[1])
        h_eff = max(h, _MIN_LEVEL)

        header_p = d["steam_header_P"]
        temp_steam = t_sat(header_p)
        latent = h_fg(temp_steam)

        f_in = d["feed_flow"]
        f_out = self.outlet_flow(h_eff, u["LV-101"], p)
        duty = self.coil_duty(temp, u["TV-101"], d, p)

        # Steam consumed to deliver the duty, plus whatever a failed trap is
        # blowing straight through to the condensate system. Blow-through costs
        # steam without delivering heat, so it shows up here and in the
        # condensate temperature but *not* in the duty -- which is precisely
        # what breaks the steam-side energy balance and gives it away.
        steam_flow = duty / latent + p["blowthrough"] * p["w_steam_design"]

        # Condensate leaves slightly subcooled when the trap is healthy. Backup
        # leaves it stagnant and much colder; blow-through pins it at
        # saturation. Opposite directions from the same tag.
        subcool = (p["subcool_base"] + p["subcool_flood"] * p["flooded_fraction"]) * (
            1.0 - min(max(p["blowthrough"], 0.0), 1.0)
        )
        temp_condensate = temp_steam - subcool

        # UA back-calculated the way a plant engineer would, from measurable
        # quantities only. Under real degradation this tracks the true loss;
        # under a steam-side instrument fault it diverges from it.
        driving = max(temp_steam - temp, 1e-6)
        ua_calc = duty / driving if u["TV-101"] > 1e-6 else 0.0

        return {
            "LI-101": h,                              # m, level
            "TI-101": temp,                           # degC, tank temperature
            "FI-101": f_in * 3600.0,                  # m3/h, feed
            "FI-102": f_out * 3600.0,                 # m3/h, product
            "TI-100": d["feed_temp"],                 # degC, feed
            "TI-102": temp,                           # degC, product line
            "PI-201": header_p,                       # barg, steam header
            "FI-201": steam_flow * 3600.0,            # kg/h, steam
            "TI-201": temp_steam,                     # degC, saturation
            "TI-202": temp_condensate,                # degC, condensate return
            "TI-901": d["T_amb"],                     # degC, ambient
            "CALC-DUTY": duty / 1000.0,               # kW
            "CALC-UA": ua_calc,                       # W/K
            "CALC-APPROACH": driving,                 # K, steam to bulk
            "CALC-PURITY": self.product_purity(temp, p),  # %, on-spec fraction
            "CALC-MBAL": (f_in - f_out) * 3600.0,     # m3/h, accumulation
            "VOLUME": p["area"] * h_eff,              # m3
        }

    @staticmethod
    def product_purity(temp: float, p: dict[str, float]) -> float:
        """Product quality as a function of tank temperature, %.

        The service is a hydrolysis hold: a dilute aqueous stream, held hot long
        enough for a residual intermediate to finish reacting. Two mechanisms
        compete, so the specification is a window rather than a floor. Below
        about 70 degC the hydrolysis does not finish in the available residence
        time and unconverted intermediate carries through; above about 80 degC
        the product degrades to coloured byproducts. Purity therefore peaks near
        ``purity_peak_T`` and falls away either side.

        The unit is run at 75 degC, deliberately on the cool side of the peak:
        drifting hot degrades product irreversibly, while drifting cool leaves
        material downstream recovery can still deal with.

        This is a correlation, not a species balance -- see the "what is not
        modelled" note in the generated process description. Its role in the
        dataset is to give the analyzer something real to track through its eight
        minute deadtime, so quality is a lagging, weakly-informative view of a
        fault rather than a second copy of the temperature trend.
        """
        offset = temp - p["purity_peak_T"]
        return 99.4 - p["purity_curvature"] * offset * offset

    # -- equilibrium ------------------------------------------------------

    def _required_duty(self, t_sp: float, d: dict, p: dict) -> float:
        return (
            p["rho"] * p["cp"] * d["feed_flow"] * (t_sp - d["feed_temp"])
            + p["UA_loss"] * (t_sp - d["T_amb"])
        )

    def steady_inputs(self, targets, d, p) -> dict[str, float]:
        """Valve positions that hold the target level and temperature.

        ``targets`` is keyed by *signal* name, matching what a loop declares as
        its ``pv_source``. Starting a run at equilibrium keeps the first days of
        the dataset a usable clean baseline instead of a startup transient.
        """
        h_sp = targets["LI-101"]
        t_sp = targets["TI-101"]

        lv = d["feed_flow"] / (p["Cv_out"] * math.sqrt(max(h_sp, _MIN_LEVEL)))

        driving = t_sat(d["steam_header_P"]) - t_sp
        if driving <= 0:
            raise ValueError(
                "steam saturation temperature is at or below the target temperature"
            )
        surviving = p["UA_coil"] * p["fouling_factor"] * (1.0 - p["flooded_fraction"])
        flow_fraction = self._required_duty(t_sp, d, p) / (surviving * driving)
        tv = inverse_equal_percentage(flow_fraction, p["valve_rangeability"])

        return {"LV-101": float(lv), "TV-101": float(tv)}

    def steady_state(self, u, d, p) -> np.ndarray:
        """Equilibrium states for fixed valve positions."""
        f_in = d["feed_flow"]
        opening = max(u["LV-101"], 1e-9)
        h = (f_in / (p["Cv_out"] * opening)) ** 2

        # Energy balance is linear in T once the coil opening is fixed.
        ua_coil = self.effective_ua(u["TV-101"], p)
        mcp = p["rho"] * p["cp"] * f_in
        temp_steam = t_sat(d["steam_header_P"])
        numer = mcp * d["feed_temp"] + ua_coil * temp_steam + p["UA_loss"] * d["T_amb"]
        denom = mcp + ua_coil + p["UA_loss"]
        return np.array([h, numer / denom])
