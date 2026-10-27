"""Noise colour, the plant clock, and the disturbance drivers."""

import numpy as np
import pytest

from historiansim.core.clock import local_hours, utc_index
from historiansim.core.noise import first_order_filter, ou_noise
from historiansim.core.rng import SeedBank
from historiansim.core.sim import simulate
from tests.conftest import tank_disturbances, tank_scenario


def acorr_time(x: np.ndarray, dt: float) -> float:
    """Lag at which autocorrelation falls to 1/e, in seconds."""
    x = x - x.mean()
    # Via FFT: the same linear autocorrelation as np.correlate(x, x, "full"),
    # in O(n log n) rather than O(n^2) -- minutes rather than an hour at 400k.
    n = len(x)
    spec = np.fft.rfft(x, 2 * n)
    full = np.fft.irfft(spec * np.conj(spec))[:n]
    full /= full[0]
    below = np.argmax(full < np.exp(-1.0))
    return float(below * dt)


# -- noise ------------------------------------------------------------------

def test_ou_noise_has_the_requested_standard_deviation():
    rng = np.random.default_rng(0)
    x = ou_noise(200_000, sigma=2.0, tau=300.0, dt=10.0, rng=rng)
    assert x.std() == pytest.approx(2.0, rel=0.05)
    assert x.mean() == pytest.approx(0.0, abs=0.1)


def test_ou_noise_has_the_requested_correlation_time():
    rng = np.random.default_rng(1)
    x = ou_noise(400_000, sigma=1.0, tau=600.0, dt=10.0, rng=rng)
    assert acorr_time(x, 10.0) == pytest.approx(600.0, rel=0.25)


def test_ou_noise_is_not_white():
    """The check this whole module exists to pass."""
    rng = np.random.default_rng(2)
    colored = ou_noise(50_000, sigma=1.0, tau=600.0, dt=10.0, rng=rng)
    white = rng.normal(size=50_000)
    assert acorr_time(colored, 10.0) > 10 * max(acorr_time(white, 10.0), 10.0)


def test_ou_noise_starts_stationary():
    """No settling ramp at the head of the series."""
    rng = np.random.default_rng(3)
    heads = [ou_noise(50, 1.0, 600.0, 10.0, np.random.default_rng(s))[0]
             for s in range(400)]
    assert np.std(heads) == pytest.approx(1.0, rel=0.2)


def test_longer_correlation_time_is_smoother():
    """Per-instrument signatures: a thermowell must not look like a flow meter."""
    rng = np.random.default_rng(4)
    fast = ou_noise(100_000, 1.0, 30.0, 10.0, rng)
    slow = ou_noise(100_000, 1.0, 3000.0, 10.0, rng)
    assert np.abs(np.diff(slow)).mean() < np.abs(np.diff(fast)).mean()


def test_first_order_filter_attenuates_and_lags():
    t = np.arange(0, 20000, 10.0)
    square = np.where((t // 2000) % 2 == 0, 1.0, -1.0)
    smoothed = first_order_filter(square, tau=600.0, dt=10.0)
    assert np.abs(np.diff(smoothed)).max() < np.abs(np.diff(square)).max()
    assert smoothed.std() < square.std()


def test_ou_noise_is_reproducible_from_the_seed_bank():
    a = ou_noise(1000, 1.0, 100.0, 10.0, SeedBank(7).get("feed"))
    b = ou_noise(1000, 1.0, 100.0, 10.0, SeedBank(7).get("feed"))
    assert np.array_equal(a, b)


# -- clock ------------------------------------------------------------------

def test_utc_index_spans_the_configured_duration():
    cfg = tank_scenario(days=3.0)
    idx = utc_index(cfg.time)
    assert len(idx) == cfg.time.n_steps
    assert str(idx.tz) == "UTC"
    assert (idx[-1] - idx[0]).total_seconds() == pytest.approx(3 * 86400 - 10.0)


def test_local_hours_survive_a_daylight_saving_transition():
    """The default window straddles a DST change on purpose.

    The diurnal cycle is locked to the sun, so local hour must stay continuous
    across the transition even though UTC offset jumps. Anything that assumes a
    fixed offset produces a one-hour discontinuity here.
    """
    cfg = tank_scenario(days=20.0)   # 2024-03-01 + 20 d covers 2024-03-10
    idx = utc_index(cfg.time)
    hours = local_hours(idx, cfg.time.timezone)
    assert hours.min() >= 0.0 and hours.max() < 24.0

    # Every local midnight should be present exactly once per day.
    midnights = np.sum(np.diff(hours) < -20.0)
    assert midnights == 20


# -- disturbance bundle -----------------------------------------------------

@pytest.fixture(scope="module")
def bundle():
    cfg = tank_scenario(days=10.0)
    return cfg, tank_disturbances(cfg, SeedBank(42))


def test_bundle_supplies_every_channel_the_unit_needs(bundle):
    from historiansim.plants.heated_stirred_tank.model import HeatedStirredTank
    _, dist = bundle
    assert set(HeatedStirredTank.disturbance_names) <= set(dist.names)


def test_ambient_has_a_diurnal_cycle(bundle):
    cfg, dist = bundle
    amb = dist.channels["T_amb"]
    per_day = int(86400 / cfg.time.dt_scan)
    profile = amb[: 10 * per_day].reshape(10, per_day).mean(axis=0)
    assert np.ptp(profile) > 5.0, "no daily swing"

    hours = local_hours(utc_index(cfg.time), cfg.time.timezone)[:per_day]
    assert 12.0 < hours[profile.argmax()] < 18.0, "daily peak is not mid-afternoon"


def test_ambient_swing_varies_between_days(bundle):
    """Some days are cloudy. A metronomic sinusoid is a tell."""
    cfg, dist = bundle
    per_day = int(86400 / cfg.time.dt_scan)
    swings = np.ptp(dist.channels["T_amb"][: 10 * per_day].reshape(10, per_day), axis=1)
    assert swings.std() / swings.mean() > 0.1


def test_feed_temperature_shares_ambient_without_being_caused_by_it(bundle):
    _, dist = bundle
    r = np.corrcoef(dist.channels["T_amb"], dist.channels["feed_temp"])[0, 1]
    assert 0.5 < r < 0.99, "coupling should be partial, not a copy"


def test_disturbances_are_bit_identical_for_the_same_seed():
    """The property the no-fault twin rests on."""
    cfg = tank_scenario(days=2.0)
    a = tank_disturbances(cfg, SeedBank(42))
    b = tank_disturbances(cfg, SeedBank(42))
    for name in a.names:
        assert np.array_equal(a.channels[name], b.channels[name])


def test_different_seeds_give_different_weather():
    cfg = tank_scenario(days=2.0)
    a = tank_disturbances(cfg, SeedBank(42))
    b = tank_disturbances(cfg, SeedBank(43))
    assert not np.allclose(a.channels["T_amb"], b.channels["T_amb"])


def test_feed_flow_never_goes_negative(bundle):
    _, dist = bundle
    assert dist.channels["feed_flow"].min() >= 0.0


def test_ambient_reaches_the_plant_without_being_scripted():
    """Nobody wrote a diurnal term into the tank. It arrives through heat loss.

    The consequence is common-cause correlation: feed temperature and steam
    valve position move together while neither drives the other. Mistaking that
    for a process relationship is a real diagnostic error, so it belongs here.
    """
    cfg = tank_scenario(days=8.0)
    dist = tank_disturbances(cfg, SeedBank(42))
    res = simulate(cfg, dist)

    r = abs(np.corrcoef(res.signals["TI-100"], res.outputs["TV-101"])[0, 1])
    assert r > 0.1, "ambient should couple upstream temperature to the valve"
