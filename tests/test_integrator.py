"""Integration accuracy, and the evidence behind the default step size."""

import numpy as np
import pytest

from historiansim.core.integrator import integrate_scan, rk4_step


def test_matches_analytic_exponential_decay():
    tau = 100.0
    f = lambda t, x: -x / tau
    x = np.array([1.0])
    dt = 5.0
    for _ in range(200):                       # 1000 s = 10 time constants
        x = rk4_step(f, 0.0, x, dt)
    # ~5e-7 relative is RK4's own truncation at dt/tau = 0.05 accumulated over
    # 200 steps, not a defect. test_fourth_order_convergence pins the order.
    assert x[0] == pytest.approx(np.exp(-10.0), rel=1e-6)


def test_fourth_order_convergence():
    """Halving the step should cut the error by roughly 16x."""
    f = lambda t, x: -x
    errors = []
    for dt in (0.4, 0.2, 0.1):
        x = np.array([1.0])
        for _ in range(int(2.0 / dt)):
            x = rk4_step(f, 0.0, x, dt)
        errors.append(abs(x[0] - np.exp(-2.0)))
    for coarse, fine in zip(errors, errors[1:]):
        assert 10.0 < coarse / fine < 25.0


def test_integrate_scan_equals_repeated_steps():
    f = lambda t, x: -0.01 * x
    x0 = np.array([5.0])
    scanned = integrate_scan(f, 0.0, x0, dt_sim=5.0, n_sub=2)
    stepped = rk4_step(f, 5.0, rk4_step(f, 0.0, x0, 5.0), 5.0)
    assert scanned == pytest.approx(stepped)


def test_default_step_is_converged_for_this_plant():
    """Justifies TimeConfig.dt_sim = 5.0 rather than asserting it.

    The plant's fastest time constant is tens of seconds. If a unit with faster
    dynamics is added, this test is where the failure should surface.
    """
    from historiansim.core.sim import ConstantDisturbance, simulate
    from tests.conftest import DESIGN_D, tank_scenario

    def run(dt_sim: float):
        cfg = tank_scenario(days=0.2, dt_sim=dt_sim)
        step = lambda k, t, loops: setattr(loops["TIC-101"], "sp", 75.0 if t < 1800 else 79.0)
        res = simulate(cfg, ConstantDisturbance(DESIGN_D), on_scan=step)
        return np.column_stack([res.signals["TI-101"], res.outputs["TV-101"]])

    coarse, fine = run(5.0), run(0.5)
    assert np.abs(coarse - fine).max() < 1e-6
