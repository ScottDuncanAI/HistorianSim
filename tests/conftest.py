"""Shared fixtures: the reference tank scenario at its design point."""

import numpy as np
import pytest

from historiansim.config.schema import LoopConfig, ScenarioConfig, TimeConfig
from historiansim.plants.heated_stirred_tank.model import HeatedStirredTank
from historiansim.plants.heated_stirred_tank.loops import tank_channels

FEED = 15.0 / 3600.0  # m3/s

#: Design-point disturbance vector.
DESIGN_D = {
    "feed_flow": FEED,
    "feed_temp": 25.0,
    "T_amb": 20.0,
    "steam_header_P": 6.0,
}

def _design_steam_flow() -> float:
    """Steam flow at the design point, kg/h.

    Computed from the physics rather than written down as a round number. The
    cascade slave's setpoint has to match the true equilibrium exactly, or the
    run opens with a small transient and the clean baseline is no longer clean.
    """
    unit = HeatedStirredTank()
    u = unit.steady_inputs({"LI-101": 2.0, "TI-101": 75.0}, DESIGN_D, unit.params)
    sig = unit.signals(0.0, np.array([2.0, 75.0]), u, DESIGN_D, unit.params)
    return sig["FI-201"]


#: Steam flow at the design point, kg/h. Used as the cascade slave's setpoint.
W_STEAM_DESIGN = _design_steam_flow()


@pytest.fixture
def unit() -> HeatedStirredTank:
    return HeatedStirredTank()


@pytest.fixture
def design_d() -> dict[str, float]:
    return dict(DESIGN_D)


def tank_scenario(days: float = 0.5, cascade: bool = True, **time_kw) -> ScenarioConfig:
    """The reference two-loop tank, optionally with the steam-flow cascade.

    With the cascade, temperature control writes a steam *flow* setpoint and an
    inner flow loop moves the valve. That arrangement is standard on a steam
    coil and it changes the diagnosis materially: the inner loop absorbs coil
    degradation entirely, so the only tag that moves is the valve itself.
    """
    time = TimeConfig(**{"days": days, "dt_scan": 10.0, "dt_sim": 5.0, **time_kw})
    level = LoopConfig(
        name="LIC-101", pv_source="LI-101", mv_tag="LV-101",
        kc=2.0, ti=600.0, sp=2.0, action="direct",
    )
    if not cascade:
        cfg = ScenarioConfig(
            name="tank", unit="heated_stirred_tank", time=time,
            loops=[
                LoopConfig(name="TIC-101", pv_source="TI-101", mv_tag="TV-101",
                           kc=0.05, ti=600.0, sp=75.0, action="reverse"),
                level,
            ],
        )
        cfg.disturbances.channels = tank_channels()
        return cfg
    cfg = ScenarioConfig(
        name="tank-cascade", unit="heated_stirred_tank", time=time,
        loops=[
            LoopConfig(name="TIC-101", pv_source="TI-101", mv_tag="TIC-101.OUT",
                       kc=0.045, ti=900.0, sp=75.0, action="reverse",
                       cascade_to="FIC-201"),
            LoopConfig(name="FIC-201", pv_source="FI-201", mv_tag="TV-101",
                       kc=0.00015, ti=60.0, sp=W_STEAM_DESIGN, action="reverse",
                       mode="CAS", sp_limits=(0.0, 3000.0)),
            level,
        ],
    )
    cfg.disturbances.channels = tank_channels()
    return cfg


def tank_disturbances(cfg: ScenarioConfig, seeds):
    """The tank's disturbance bundle, channels in the unit's own order."""
    from historiansim.disturbances import build_disturbances

    return build_disturbances(cfg, seeds, HeatedStirredTank.disturbance_names)


class RampParam:
    """Ramps a single process parameter to a final value after an onset.

    Stands in for the fault framework until phase 4 builds it properly. Note
    what it does *not* do: it never touches a signal, only a parameter, so the
    controller has to discover the change through the physics.
    """

    def __init__(self, param: str, start: float, final: float,
                 onset_s: float, tau_s: float = 6000.0):
        self.param, self.start, self.final = param, start, final
        self.onset_s, self.tau_s = onset_s, tau_s

    def apply(self, p: dict[str, float], t: float) -> None:
        if t < self.onset_s:
            return
        frac = 1.0 - np.exp(-(t - self.onset_s) / self.tau_s)
        p[self.param] = self.start + frac * (self.final - self.start)

    def touched_params(self) -> tuple[str, ...]:
        return (self.param,)


class RampDisturbance:
    """Ramps one disturbance channel; the others stay at the design point."""

    def __init__(self, key: str, final: float, onset_s: float,
                 tau_s: float = 6000.0, base: dict[str, float] | None = None):
        self.base = dict(base or DESIGN_D)
        self.key, self.final = key, final
        self.onset_s, self.tau_s = onset_s, tau_s
        self.start = self.base[key]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.base)

    def resolve(self, k: int, t: float) -> dict[str, float]:
        out = dict(self.base)
        if t >= self.onset_s:
            frac = 1.0 - np.exp(-(t - self.onset_s) / self.tau_s)
            out[self.key] = self.start + frac * (self.final - self.start)
        return out
