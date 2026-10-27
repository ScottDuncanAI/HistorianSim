"""Fault primitives: severity profiles, composition, and cleaning resets."""

import numpy as np
import pytest

from historiansim.faults.base import (
    Erratic,
    Exponential,
    InstrumentFault,
    Linear,
    ProcessFault,
    Step,
)

DAY = 86400.0


def make(**kw) -> ProcessFault:
    base = dict(id="F-001", param="fouling_factor", magnitude=0.25,
                onset_s=2 * DAY, profile=Exponential(tau_s=4 * DAY), mode="scale")
    base.update(kw)
    return ProcessFault(**base)


# -- profiles ---------------------------------------------------------------

def test_step_profile_is_immediate():
    assert Step()(0.0) == 1.0


def test_linear_profile_ramps_then_holds():
    ramp = Linear(ramp_s=1000.0)
    assert ramp(0.0) == 0.0
    assert ramp(500.0) == pytest.approx(0.5)
    assert ramp(5000.0) == 1.0


def test_exponential_profile_reaches_63_percent_at_one_tau():
    exp = Exponential(tau_s=1000.0)
    assert exp(1000.0) == pytest.approx(0.632, abs=0.001)
    assert exp(5000.0) == pytest.approx(1.0, abs=0.01)


def test_exponential_start_is_slow_enough_to_hide_in_the_noise():
    """Why fouling is hard to catch early: the first day barely moves anything."""
    exp = Exponential(tau_s=6 * DAY)
    assert exp(0.25 * DAY) < 0.05


def test_erratic_profile_oscillates_around_its_envelope():
    """Condensate backup slugs; fouling does not. That difference is visible."""
    erratic = Erratic(tau_s=2 * DAY, period_s=5400.0, depth=0.35)
    smooth = Exponential(tau_s=2 * DAY)
    t = np.arange(0, 4 * DAY, 300.0)
    e = np.array([erratic(v) for v in t])
    s = np.array([smooth(v) for v in t])
    assert np.abs(np.diff(e)).std() > 5 * np.abs(np.diff(s)).std()
    assert e.min() >= 0.0 and e.max() <= 1.0


def test_erratic_is_a_pure_function_of_time():
    """Evaluated inside the integration loop, so it must not consume randomness."""
    erratic = Erratic(tau_s=DAY)
    assert erratic(12345.0) == erratic(12345.0)


# -- severity and timing ----------------------------------------------------

def test_no_effect_before_onset():
    fault = make()
    p = {"fouling_factor": 1.0}
    fault.apply(p, t=DAY)
    assert p["fouling_factor"] == 1.0


def test_scale_mode_reduces_a_surviving_fraction():
    fault = make(profile=Step())
    p = {"fouling_factor": 1.0}
    fault.apply(p, t=3 * DAY)
    assert p["fouling_factor"] == pytest.approx(0.75)


def test_offset_mode_adds_to_a_quantity_that_starts_at_zero():
    fault = make(param="flooded_fraction", magnitude=0.22, mode="offset",
                 profile=Step())
    p = {"flooded_fraction": 0.0}
    fault.apply(p, t=3 * DAY)
    assert p["flooded_fraction"] == pytest.approx(0.22)


def test_faults_on_the_same_parameter_compose():
    """Background degradation must run underneath an injected fault.

    Neither knows about the other; scale composition makes that work out.
    """
    background = make(id="D-001", magnitude=0.10, profile=Step(), onset_s=0.0)
    injected = make(id="F-002", magnitude=0.20, profile=Step(), onset_s=0.0)
    p = {"fouling_factor": 1.0}
    background.apply(p, t=DAY)
    injected.apply(p, t=DAY)
    assert p["fouling_factor"] == pytest.approx(0.9 * 0.8)


def test_fault_clears_at_end_time():
    fault = make(profile=Step(), end_s=5 * DAY)
    p = {"fouling_factor": 1.0}
    fault.apply(p, t=6 * DAY)
    assert p["fouling_factor"] == 1.0


def test_cleaning_resets_the_severity_clock():
    """Real fouling data is a sawtooth across turnarounds, not a monotone curve."""
    fault = make(onset_s=0.0, profile=Exponential(tau_s=2 * DAY), resets=(10 * DAY,))
    assert fault.severity_at(9.9 * DAY) > 0.9
    assert fault.severity_at(10.01 * DAY) < 0.05
    assert fault.severity_at(13 * DAY) > 0.5      # and it starts fouling again


def test_reset_before_onset_is_ignored():
    fault = make(onset_s=5 * DAY, profile=Exponential(tau_s=DAY), resets=(2 * DAY,))
    assert fault.severity_at(7 * DAY) > 0.8


def test_touched_params_drives_logging():
    assert make().touched_params() == ("fouling_factor",)


# -- layer assignment -------------------------------------------------------

def test_process_fault_is_layer_six():
    assert make().layer == 6


def test_instrument_fault_is_layer_seven_and_touches_no_parameter():
    """The distinction that keeps a transmitter fault out of the physics."""
    fault = InstrumentFault(id="F-010", tag="FI-201", magnitude=120.0,
                            onset_s=DAY, profile=Linear(2 * DAY))
    assert fault.layer == 7
    assert fault.touched_params() == ()
    assert not hasattr(fault, "apply"), (
        "an instrument fault must not be applicable to the parameter dict"
    )


def test_instrument_fault_severity_ramps():
    fault = InstrumentFault(id="F-010", tag="FI-201", magnitude=120.0,
                            onset_s=DAY, profile=Linear(2 * DAY))
    assert fault.severity_at(0.5 * DAY) == 0.0
    assert fault.severity_at(2 * DAY) == pytest.approx(0.5)
    assert fault.severity_at(10 * DAY) == 1.0
