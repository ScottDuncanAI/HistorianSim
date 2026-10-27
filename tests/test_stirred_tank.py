"""Tank physics: equilibria, balances, and the nonlinearities that matter."""

import numpy as np
import pytest

from historiansim.core.sim import ConstantDisturbance, simulate
from historiansim.core.steam import t_sat
from historiansim.plants.heated_stirred_tank.model import HeatedStirredTank
from tests.conftest import DESIGN_D, FEED, tank_scenario

TARGETS = {"LI-101": 2.0, "TI-101": 75.0}


def test_unknown_parameter_is_rejected():
    with pytest.raises(KeyError, match="unknown parameter"):
        HeatedStirredTank({"UA_coyl": 1000.0})


def test_steady_inputs_give_zero_derivatives(unit, design_d):
    u = unit.steady_inputs(TARGETS, design_d, unit.params)
    dx = unit.derivatives(0.0, np.array([2.0, 75.0]), u, design_d, unit.params)
    assert np.abs(dx).max() < 1e-12


def test_steady_state_inverts_steady_inputs(unit, design_d):
    u = unit.steady_inputs(TARGETS, design_d, unit.params)
    assert unit.steady_state(u, design_d, unit.params) == pytest.approx([2.0, 75.0], rel=1e-9)


def test_design_point_leaves_valve_headroom(unit, design_d):
    """A degradation fault needs somewhere to go before the loop saturates."""
    u = unit.steady_inputs(TARGETS, design_d, unit.params)
    assert 0.35 < u["TV-101"] < 0.65
    assert 0.35 < u["LV-101"] < 0.65


def test_equal_percentage_gain_rises_with_opening(unit):
    """As fouling drives the valve open, the loop gets more aggressive.

    Emergent from the valve trim, not scheduled anywhere. It is also why a
    heavily fouled coil can start to cycle.
    """
    p = unit.params
    gain = lambda x, eps=1e-6: (
        unit.effective_ua(x + eps, p) - unit.effective_ua(x, p)
    ) / eps
    assert gain(0.8) > gain(0.5) > gain(0.2)


def test_level_loop_gain_varies_with_level(unit):
    """The sqrt outlet characteristic makes 'operating point shift' a real
    competing explanation for a cycling level loop."""
    p = unit.params
    flow = lambda h: unit.outlet_flow(h, 0.5, p)
    assert flow(3.0) / flow(1.0) == pytest.approx(np.sqrt(3.0), rel=1e-9)


def test_fouling_and_flooding_both_reduce_ua(unit):
    """Two mechanisms entering the physics at exactly the same place."""
    clean = unit.effective_ua(0.5, unit.params)
    fouled = unit.effective_ua(0.5, dict(unit.params, fouling_factor=0.8))
    flooded = unit.effective_ua(0.5, dict(unit.params, flooded_fraction=0.2))
    assert fouled == pytest.approx(0.8 * clean)
    assert flooded == pytest.approx(0.8 * clean)
    assert fouled == pytest.approx(flooded), "indistinguishable by design"


def test_coil_cannot_cool_the_tank(unit, design_d):
    """Physical bound: with the header collapsed, duty floors at zero."""
    cold = dict(design_d, steam_header_P=-0.9)
    assert unit.coil_duty(75.0, 0.5, cold, unit.params) == 0.0


def test_steam_temperature_follows_header_pressure(unit, design_d):
    """The coupling that makes header decline a competing cause."""
    assert t_sat(6.0) == pytest.approx(162.7, abs=0.5)
    assert t_sat(4.0) < t_sat(6.0) < t_sat(9.0)


def test_energy_balance_closes_at_steady_state(unit, design_d):
    res = simulate(tank_scenario(days=0.3), ConstantDisturbance(DESIGN_D))
    p = unit.params
    temp = res.signals["TI-101"][-1]
    duty = res.signals["CALC-DUTY"][-1] * 1000.0
    required = (
        p["rho"] * p["cp"] * FEED * (temp - DESIGN_D["feed_temp"])
        + p["UA_loss"] * (temp - DESIGN_D["T_amb"])
    )
    assert duty == pytest.approx(required, rel=1e-6)


def test_mass_balance_closes_at_steady_state():
    res = simulate(tank_scenario(days=0.3), ConstantDisturbance(DESIGN_D))
    assert abs(res.signals["CALC-MBAL"][-1]) < 1e-6


def test_run_starts_at_equilibrium():
    """No startup transient, so the clean baseline is usable from hour zero."""
    res = simulate(tank_scenario(days=0.3), ConstantDisturbance(DESIGN_D))
    assert np.ptp(res.signals["TI-101"]) < 1e-6
    assert np.ptp(res.signals["LI-101"]) < 1e-6


def test_cascade_also_starts_at_equilibrium():
    """A cascade master must open at the setpoint its slave already holds."""
    res = simulate(tank_scenario(days=0.3, cascade=True), ConstantDisturbance(DESIGN_D))
    assert np.ptp(res.setpoints["FIC-201.SP"]) < 1.0
    assert np.ptp(res.outputs["TV-101"]) < 1e-3


def test_controller_returns_temperature_to_new_setpoint():
    step = lambda k, t, loops: setattr(loops["TIC-101"], "sp", 75.0 if t < 3600 else 79.0)
    res = simulate(tank_scenario(days=0.6), ConstantDisturbance(DESIGN_D), on_scan=step)
    assert res.signals["TI-101"][-1] == pytest.approx(79.0, abs=0.05)
    assert res.outputs["TV-101"][-1] > res.outputs["TV-101"][100] + 0.01


def test_level_stays_positive_under_a_hard_outflow_step():
    def drive(k, t, loops):
        if t > 600:
            loops["LIC-101"].set_mode("MAN", output=1.0)

    res = simulate(tank_scenario(days=0.5), ConstantDisturbance(DESIGN_D), on_scan=drive)
    assert res.signals["LI-101"].min() >= 0.0


def test_higher_feed_rate_needs_more_steam(unit, design_d):
    p = unit.params
    low = unit.steady_inputs(TARGETS, design_d, p)
    high = unit.steady_inputs(TARGETS, dict(design_d, feed_flow=FEED * 1.15), p)
    assert high["TV-101"] > low["TV-101"]


def test_colder_feed_needs_more_steam(unit, design_d):
    p = unit.params
    base = unit.steady_inputs(TARGETS, design_d, p)
    cold = unit.steady_inputs(TARGETS, dict(design_d, feed_temp=18.0), p)
    assert cold["TV-101"] > base["TV-101"]


def test_lower_header_pressure_needs_more_valve(unit, design_d):
    p = unit.params
    base = unit.steady_inputs(TARGETS, design_d, p)
    low = unit.steady_inputs(TARGETS, dict(design_d, steam_header_P=4.5), p)
    assert low["TV-101"] > base["TV-101"]
