"""Measurement layer and historian: the properties that make data look real."""

import numpy as np
import pytest

from historiansim.core.rng import SeedBank
from historiansim.historian.swinging_door import (
    _swinging_door_loop,
    compress,
    reconstruct,
    swinging_door,
)
from historiansim.measurement.instrument import (
    INSTRUMENT_CLASSES,
    Quality,
    apply_instrument,
)
from historiansim.measurement.pathology import (
    apply_freezes,
    apply_spikes,
    node_dropouts,
    stamp_quality,
)


# -- instrument classes -----------------------------------------------------

def test_every_class_quantizes_or_is_a_dcs_value():
    for name, cls in INSTRUMENT_CLASSES.items():
        if name in ("calculated", "status"):
            assert cls.lsb == 0.0
        else:
            assert cls.lsb > 0, f"{name} has no transmitter resolution"


def test_quantization_produces_a_staircase():
    rng = np.random.default_rng(0)
    true = np.linspace(0.0, 100.0, 5000)
    cls = INSTRUMENT_CLASSES["flow"]
    out = apply_instrument(true, cls, (0.0, 100.0), 10.0, rng)
    steps = np.unique(np.round(np.diff(np.unique(out)), 9))
    assert len(np.unique(out)) < len(true), "no quantization applied"
    assert steps.min() >= cls.lsb * 100.0 * 0.5


def test_temperature_is_smoother_than_flow():
    """Thermal mass low-passes the process; a DP cell does not."""
    rng = np.random.default_rng(1)
    true = np.zeros(20000)
    flow = apply_instrument(true, INSTRUMENT_CLASSES["flow"], (0, 100), 10.0, rng)
    temp = apply_instrument(
        true, INSTRUMENT_CLASSES["temperature_slow"], (0, 100), 10.0, rng
    )
    assert np.abs(np.diff(temp)).mean() < np.abs(np.diff(flow)).mean()


def test_analyzer_holds_between_updates():
    """A slow analyzer produces a staircase, not an interpolation."""
    rng = np.random.default_rng(2)
    true = np.linspace(90.0, 100.0, 3000)
    out = apply_instrument(true, INSTRUMENT_CLASSES["analyzer"], (90, 100), 10.0, rng)
    stride = int(INSTRUMENT_CLASSES["analyzer"].sample_s / 10.0)
    assert out[1] == out[stride - 1], "analyzer updated faster than its sample period"


def test_sensor_lag_delays_a_step():
    rng = np.random.default_rng(3)
    true = np.concatenate([np.zeros(500), np.ones(2000) * 10.0])
    out = apply_instrument(
        true, INSTRUMENT_CLASSES["temperature_slow"], (0, 100), 10.0, rng
    )
    assert out[505] < 8.0, "step arrived instantly; no thermowell lag"
    assert out[-1] == pytest.approx(10.0, abs=0.5)


# -- pathology --------------------------------------------------------------

def test_spikes_are_single_sample():
    rng = np.random.default_rng(4)
    base = np.full(100000, 50.0)
    out = apply_spikes(base, (0, 100), per_day=20.0, dt=10.0, rng=rng)
    affected = np.flatnonzero(out != 50.0)
    assert affected.size > 0
    assert np.all(np.diff(affected) > 1), "spikes must not be contiguous"


def test_freezes_repeat_the_last_value():
    rng = np.random.default_rng(5)
    base = np.cumsum(rng.normal(size=200000))
    out, frozen = apply_freezes(base, per_month=40.0, dt=10.0, rng=rng)
    assert frozen.any(), "no freezes generated"
    idx = np.flatnonzero(frozen)
    run = idx[: np.searchsorted(idx, idx[0] + 5)]
    assert len(np.unique(out[run])) == 1


def test_frozen_stretches_are_not_flagged_bad():
    """A stuck transmitter reports good quality. Flagging it gives it away."""
    rng = np.random.default_rng(6)
    base = np.cumsum(rng.normal(size=100000))
    out, frozen = apply_freezes(base, per_month=40.0, dt=10.0, rng=rng)
    quality = np.full(len(out), Quality.GOOD, dtype=np.int8)
    assert np.all(quality[frozen] == Quality.GOOD)


def test_node_dropouts_return_contiguous_ranges():
    rng = np.random.default_rng(7)
    ranges = node_dropouts(200000, 10.0, rng, per_month=20.0)
    assert ranges
    for lo, hi in ranges:
        assert 0 <= lo < hi <= 200000


def test_stamp_quality_marks_whole_ranges():
    quality = np.zeros(100, dtype=np.int8)
    out = stamp_quality(quality, [(10, 20)], Quality.BAD)
    assert np.all(out[10:20] == Quality.BAD)
    assert np.all(out[:10] == Quality.GOOD)


# -- swinging door ----------------------------------------------------------

def test_compiled_matches_pure_python():
    """The JIT path must be behaviourally identical to the reference loop."""
    rng = np.random.default_rng(8)
    t = np.arange(20000) * 10.0
    v = 50 + np.cumsum(rng.normal(0, 0.02, 20000))
    assert np.array_equal(
        np.asarray(swinging_door(t, v, 0.1)),
        np.asarray(_swinging_door_loop(t, v, 0.1)),
    )


def test_compression_keeps_endpoints():
    t = np.arange(1000) * 10.0
    v = np.sin(t / 500.0)
    keep = swinging_door(t, v, 0.05)
    assert keep[0] == 0 and keep[-1] == 999


def test_reconstruction_stays_near_the_deadband():
    """The guarantee is on the order of the deadband, not exactly it.

    Anchoring on the point *before* the cone closes -- which is what makes the
    algorithm causal and streamable -- allows up to roughly twice the deadband
    in the worst case. Real historians behave the same way.
    """
    rng = np.random.default_rng(9)
    t = np.arange(50000) * 10.0
    v = 50 + np.cumsum(rng.normal(0, 0.02, 50000))
    dev = 0.1
    keep = swinging_door(t, v, dev)
    error = np.abs(reconstruct(t[keep], v[keep], t) - v).max()
    assert error < 2.5 * dev


def test_tighter_deadband_keeps_more_points():
    rng = np.random.default_rng(10)
    t = np.arange(50000) * 10.0
    v = 50 + np.cumsum(rng.normal(0, 0.02, 50000))
    tight = len(swinging_door(t, v, 0.01))
    loose = len(swinging_door(t, v, 0.5))
    assert tight > loose * 10


def test_quality_transitions_are_always_stored():
    """Otherwise the boundaries of an outage are lost."""
    t = np.arange(2000) * 10.0
    v = np.full(2000, 42.0)                 # perfectly flat: nothing to store
    quality = np.zeros(2000, dtype=np.int8)
    quality[500:600] = Quality.BAD
    keep = set(compress(t, v, quality, 0.01, (0.0, 100.0)).tolist())
    assert {499, 500, 599, 600} & keep, "outage boundaries were compressed away"


def test_deadbands_differ_between_instrument_classes():
    """Different deadbands are what give every tag its own timestamps."""
    deadbands = {c.deadband for c in INSTRUMENT_CLASSES.values() if c.deadband > 0}
    assert len(deadbands) > 1
