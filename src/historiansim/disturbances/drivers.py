"""Builders for each disturbance channel.

Every channel draws from its own named RNG substream. Adding a channel later,
or leaving one unused, must not shift the numbers in any other -- that property
is what keeps a no-fault twin comparable to its fault run.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from historiansim.config.schema import ChannelConfig, ScenarioConfig
from historiansim.core.clock import day_of_year, local_hours, utc_index
from historiansim.core.noise import diurnal, ou_noise
from historiansim.core.rng import SeedBank
from historiansim.disturbances.bundle import DisturbanceBundle

__all__ = ["build_ambient", "build_channel", "build_disturbances"]

_HOUR = 3600.0


def build_ambient(
    cfg: ScenarioConfig, seeds: SeedBank, index: pd.DatetimeIndex | None = None
) -> np.ndarray:
    """Ambient temperature, degC.

    Three superimposed components, each with a different timescale:

    * a seasonal sinusoid on day of year,
    * a daily cycle peaking mid-afternoon, whose amplitude itself varies from
      day to day because some days are cloudy,
    * slow correlated excursions standing in for weather fronts.

    The result is nonstationary on purpose. A dataset whose statistics are
    constant over 90 days is not plant data, and any drift-detection method
    trained on one is being flattered.
    """
    acfg = cfg.disturbances.ambient
    tcfg = cfg.time
    index = utc_index(tcfg) if index is None else index
    rng = seeds.get("ambient")

    hours = local_hours(index, tcfg.timezone)
    doy = day_of_year(index, tcfg.timezone)

    # Seasonal: minimum in early January, maximum in early July.
    seasonal = acfg.annual_mean - acfg.annual_amplitude * np.cos(
        2.0 * np.pi * (doy - 15.0) / 365.25
    )

    # Cloud cover modulates the daily swing. One value per day, held, so the
    # modulation does not itself introduce spurious high-frequency content.
    n_days = int(np.ceil(tcfg.duration_s / 86400.0)) + 2
    day_factor = 1.0 + acfg.diurnal_variability * rng.normal(size=n_days)
    day_factor = np.clip(day_factor, 0.15, 1.9)
    day_idx = np.floor(np.arange(len(index)) * tcfg.dt_scan / 86400.0).astype(int)
    swing = acfg.diurnal_amplitude * day_factor[day_idx]

    daily = diurnal(hours, 1.0, acfg.peak_hour) * swing
    fronts = ou_noise(
        len(index), acfg.front_sigma, acfg.front_tau_h * _HOUR, tcfg.dt_scan, rng
    )
    return seasonal + daily + fronts


def build_channel(
    spec: ChannelConfig,
    name: str,
    cfg: ScenarioConfig,
    seeds: SeedBank,
    ambient_anomaly: np.ndarray,
    hours: np.ndarray,
) -> np.ndarray:
    """One disturbance channel, in SI units.

    Terms that a channel does not use are skipped rather than added as zeros,
    so the arithmetic -- and therefore every bit of the result -- depends only
    on the terms the plant actually declared.
    """
    tcfg = cfg.time
    n = len(ambient_anomaly)
    values = spec.mean
    if spec.ambient_coupling:
        values = values + spec.ambient_coupling * ambient_anomaly
    if spec.diurnal_amplitude:
        values = values + diurnal(hours, spec.diurnal_amplitude, peak_hour=spec.diurnal_peak_hour)
    if spec.sigma > 0:
        values = values + ou_noise(
            n, spec.sigma, spec.tau_s, tcfg.dt_scan, seeds.get(spec.rng_stream or name)
        )
    values = np.broadcast_to(np.asarray(values, dtype=float), (n,)).copy()
    if spec.floor is not None:
        values = np.maximum(values, spec.floor)
    if spec.si_divisor != 1.0:
        values = values / spec.si_divisor
    return values


def build_disturbances(
    cfg: ScenarioConfig, seeds: SeedBank, names: Sequence[str] | None = None
) -> DisturbanceBundle:
    """Every disturbance channel the plant responds to, plus ambient as ``T_amb``.

    Channels come from ``cfg.disturbances.channels``. ``names`` fixes the
    order of the returned bundle -- normally the unit's ``disturbance_names``
    -- and every name must be either ``T_amb`` or a configured channel.

    Each channel draws from its own named substream, so the weather and every
    other channel are untouched when a channel is added, removed or retuned.
    """
    tcfg = cfg.time
    index = utc_index(tcfg)

    t_amb = build_ambient(cfg, seeds, index)
    # The shared component of every ambient-coupled channel is common-cause
    # correlation: the channel and the vessel temperature track each other
    # with neither driving the other.
    ambient_anomaly = t_amb - np.mean(t_amb)
    hours = local_hours(index, tcfg.timezone)

    channels = cfg.disturbances.channels
    names = list(names) if names is not None else ["T_amb", *channels]
    missing = [n for n in names if n != "T_amb" and n not in channels]
    if missing:
        raise KeyError(
            f"disturbance channels {missing} are not configured; have {sorted(channels)}"
        )

    out: dict[str, np.ndarray] = {}
    for name in names:
        if name == "T_amb":
            out[name] = t_amb
        else:
            out[name] = build_channel(
                channels[name], name, cfg, seeds, ambient_anomaly, hours
            )
    return DisturbanceBundle(out)
