"""Controller behaviour, especially the parts that shape the dataset.

A dataset's correlation structure is decided by the controllers. If the loop
does not mask a fault the way a real one does, nothing downstream is worth
much -- so these are behavioural tests, not algebra checks.
"""

import pytest

from historiansim.config.schema import LoopConfig
from historiansim.core.pid import PID


def make(**kw) -> LoopConfig:
    base = dict(name="TIC-101", pv_source="TI-101", mv_tag="TV-101",
                kc=0.05, ti=600.0, sp=75.0, action="reverse")
    base.update(kw)
    return LoopConfig(**base)


def test_reverse_action_opens_when_pv_falls():
    """A heating loop opens its valve when the process cools."""
    pid = PID(make(), pv0=75.0, out0=0.5)
    assert pid.step(74.0, 10.0) > 0.5


def test_direct_action_opens_when_pv_rises():
    """A level loop draining a vessel opens its valve when level climbs."""
    pid = PID(make(action="direct", kc=2.0, sp=2.0), pv0=2.0, out0=0.5)
    assert pid.step(2.1, 10.0) > 0.5


def test_steady_at_setpoint_holds_output():
    pid = PID(make(), pv0=75.0, out0=0.5155)
    for _ in range(50):
        out = pid.step(75.0, 10.0)
    assert out == pytest.approx(0.5155, abs=1e-9)


def test_setpoint_change_produces_no_derivative_kick():
    """Derivative acts on PV, not error, because real controllers do."""
    pid = PID(make(td=30.0), pv0=75.0, out0=0.5)
    pid.step(75.0, 10.0)
    pid.sp = 80.0
    after = pid.step(75.0, 10.0)
    # Only the proportional term should respond: kc * 5 K = 0.25
    assert after == pytest.approx(0.5 + 0.25, abs=1e-9)


def test_derivative_responds_to_pv_movement():
    pid = PID(make(td=30.0), pv0=75.0, out0=0.5)
    pid.step(75.0, 10.0)
    falling = pid.step(74.0, 10.0)
    pid2 = PID(make(td=0.0), pv0=75.0, out0=0.5)
    pid2.step(75.0, 10.0)
    no_deriv = pid2.step(74.0, 10.0)
    assert falling > no_deriv


def test_output_respects_limits():
    pid = PID(make(kc=5.0), pv0=75.0, out0=0.5)
    assert pid.step(0.0, 10.0) <= 1.0
    pid2 = PID(make(kc=5.0), pv0=75.0, out0=0.5)
    assert pid2.step(200.0, 10.0) >= 0.0


def test_saturated_loop_does_not_wind_up():
    """The signature that matters when a fault pins a valve at its stop.

    A wound-up integrator would hold the valve open long after the process
    recovered, destroying the recovery transient an agent could learn from.
    """
    pid = PID(make(kc=0.5, ti=60.0), pv0=75.0, out0=0.5)
    for _ in range(500):                      # far below setpoint, valve pinned
        pid.step(20.0, 10.0)
    assert pid.out == pytest.approx(1.0)
    assert pid.integral <= 1.0 + 1e-9, "integral ran away while saturated"

    # Recovery should be prompt rather than waiting out a huge integral.
    for _ in range(30):
        pid.step(90.0, 10.0)
    assert pid.out < 1.0


def test_manual_mode_holds_output_regardless_of_pv():
    pid = PID(make(mode="MAN", man_output=0.42), pv0=75.0, out0=0.42)
    for pv in (10.0, 75.0, 200.0):
        assert pid.step(pv, 10.0) == pytest.approx(0.42)


def test_manual_to_auto_is_bumpless():
    pid = PID(make(mode="MAN", man_output=0.62), pv0=75.0, out0=0.62)
    pid.step(70.0, 10.0)
    pid.set_mode("AUTO")
    # At the moment of transfer the output must not jump; only the error term
    # that follows should move it.
    assert pid.integral == pytest.approx(0.62)


def test_rate_limit_caps_movement():
    pid = PID(make(kc=5.0, out_rate_limit=0.001), pv0=75.0, out0=0.5)
    out = pid.step(0.0, 10.0)
    assert out == pytest.approx(0.51, abs=1e-9)  # 0.001/s over a 10 s scan


def test_slower_loop_scan_holds_output():
    """Zero-order hold between a loop's own executions."""
    pid = PID(make(scan_s=60.0), pv0=75.0, out0=0.5)
    first = pid.step(70.0, 10.0)          # executes: 10 s elapsed >= ... no
    held = [pid.step(70.0, 10.0) for _ in range(4)]
    assert all(h == first for h in held), "output moved before the loop scanned"
    moved = pid.step(70.0, 10.0)          # 60 s now elapsed
    assert moved != first


def test_integral_disabled_when_ti_zero():
    pid = PID(make(ti=0.0), pv0=75.0, out0=0.5)
    outs = [pid.step(74.0, 10.0) for _ in range(20)]
    assert outs[0] == pytest.approx(outs[-1]), "P-only loop should not ramp"
