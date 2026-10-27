"""Cascade ordering, valve characteristics, stiction and transport lag."""

import numpy as np
import pytest
from pydantic import ValidationError

from historiansim.config.schema import LoopConfig, ScenarioConfig
from historiansim.core.deadtime import DeadTime, shift_series
from historiansim.core.sim import ConstantDisturbance, simulate
from historiansim.core.valve import (
    Stiction,
    equal_percentage,
    inverse_equal_percentage,
    linear,
)
from tests.conftest import DESIGN_D, tank_scenario


# -- cascade ----------------------------------------------------------------

def test_cascade_slave_must_declare_setpoint_limits():
    with pytest.raises(ValidationError, match="sp_limits"):
        ScenarioConfig(
            name="x", unit="heated_stirred_tank",
            loops=[
                LoopConfig(name="M", pv_source="TI-101", mv_tag="a", kc=1, sp=75,
                           cascade_to="S"),
                LoopConfig(name="S", pv_source="FI-201", mv_tag="TV-101", kc=1,
                           sp=1500, mode="CAS"),
            ],
        )


def test_cascade_slave_must_be_in_cas_mode():
    with pytest.raises(ValidationError, match="must be CAS"):
        ScenarioConfig(
            name="x", unit="heated_stirred_tank",
            loops=[
                LoopConfig(name="M", pv_source="TI-101", mv_tag="a", kc=1, sp=75,
                           cascade_to="S"),
                LoopConfig(name="S", pv_source="FI-201", mv_tag="TV-101", kc=1,
                           sp=1500, sp_limits=(0, 3000)),
            ],
        )


def test_cascade_to_unknown_loop_is_rejected():
    with pytest.raises(ValidationError, match="unknown loop"):
        ScenarioConfig(
            name="x", unit="heated_stirred_tank",
            loops=[LoopConfig(name="M", pv_source="TI-101", mv_tag="a", kc=1,
                              sp=75, cascade_to="nope")],
        )


def test_master_writes_the_slave_setpoint():
    """The master's output is a flow in engineering units, not a valve position."""
    step = lambda k, t, loops: setattr(loops["TIC-101"], "sp", 75.0 if t < 1800 else 79.0)
    res = simulate(tank_scenario(days=0.5), ConstantDisturbance(DESIGN_D), on_scan=step)
    sp = res.setpoints["FIC-201.SP"]
    assert sp[-1] > sp[100] + 50.0, "hotter target should demand more steam"
    # And the slave actually delivers it.
    assert res.signals["FI-201"][-1] == pytest.approx(sp[-1], rel=0.02)


def test_master_executes_before_its_slave():
    from historiansim.core.pid import PID
    from historiansim.core.sim import _order_by_cascade

    master = PID(LoopConfig(name="M", pv_source="TI-101", mv_tag="a", kc=1,
                            sp=75, cascade_to="S"), pv0=75.0)
    slave = PID(LoopConfig(name="S", pv_source="FI-201", mv_tag="TV-101", kc=1,
                           sp=1500, mode="CAS", sp_limits=(0, 3000)), pv0=1500.0)
    for order in ([master, slave], [slave, master]):
        assert [c.name for c in _order_by_cascade(order)] == ["M", "S"]


# -- valve characteristics --------------------------------------------------

def test_linear_characteristic_is_travel():
    assert linear(0.37) == pytest.approx(0.37)


def test_equal_percentage_gain_is_proportional_to_flow():
    """Equal travel gives equal percentage change -- the defining property."""
    r = equal_percentage(0.6) / equal_percentage(0.5)
    assert equal_percentage(0.9) / equal_percentage(0.8) == pytest.approx(r)


def test_equal_percentage_endpoints():
    assert equal_percentage(1.0) == pytest.approx(1.0)
    assert equal_percentage(0.0) == pytest.approx(1 / 50.0)


def test_inverse_equal_percentage_round_trips():
    for x in (0.05, 0.3, 0.5014, 0.9):
        assert inverse_equal_percentage(equal_percentage(x)) == pytest.approx(x)


# -- stiction ---------------------------------------------------------------

def test_stiction_ignores_small_moves():
    valve = Stiction(deadband=0.05, jump=0.02, position=0.5)
    assert valve(0.52) == pytest.approx(0.5), "inside the deadband the stem should not move"


def test_stiction_breaks_free_and_jumps():
    valve = Stiction(deadband=0.05, jump=0.03, position=0.5)
    moved = valve(0.58)
    assert moved > 0.5


def test_stiction_sustains_a_limit_cycle_under_integral_action():
    """The signature that separates a sticking valve from an aggressive loop.

    A pure integrator ramping into a sticking valve produces stepped, square-ish
    stem movement rather than smooth tracking. On a PV/OP plot this traces a
    parallelogram, which is how the two are told apart in practice.
    """
    valve = Stiction(deadband=0.06, jump=0.03, position=0.5)
    demand = 0.5
    positions = []
    for i in range(200):
        demand += 0.002 if i < 100 else -0.002
        positions.append(valve(demand))

    steps = np.diff(positions)
    moving = np.abs(steps) > 1e-9
    assert moving.sum() < len(steps) * 0.9, "stem moved every scan; no stiction"
    assert np.abs(steps[moving]).max() > 0.02, "no discrete jump on breakaway"


def test_stiction_rejects_negative_parameters():
    with pytest.raises(ValueError):
        Stiction(deadband=-0.1, jump=0.02)


# -- transport lag ----------------------------------------------------------

def test_deadtime_delays_by_the_requested_time():
    lag = DeadTime(delay_s=30.0, dt_scan=10.0, init=0.0)
    outputs = [lag(1.0) for _ in range(5)]
    assert outputs == [0.0, 0.0, 0.0, 1.0, 1.0]


def test_shift_series_matches_deadtime():
    """The post-processing shortcut must equal the in-loop object exactly."""
    rng = np.random.default_rng(0)
    values = rng.normal(size=200)
    lag = DeadTime(delay_s=50.0, dt_scan=10.0, init=values[0])
    streamed = np.array([lag(v) for v in values])
    assert np.allclose(streamed, shift_series(values, 50.0, 10.0))


def test_shift_series_puts_correlation_peak_at_the_declared_lag():
    """A cross-correlation peaking at zero is the fastest tell of fake data."""
    rng = np.random.default_rng(1)
    source = np.cumsum(rng.normal(size=4000))
    delayed = shift_series(source, delay_s=480.0, dt=10.0)  # 8 minutes

    a = source - source.mean()
    b = delayed - delayed.mean()
    corr = np.correlate(b, a, mode="full")
    peak = corr.argmax() - (len(a) - 1)
    assert peak == 48
