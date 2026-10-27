"""Instrument classes: per-measurement noise, lag and resolution.

One noise model across every tag is the fastest way to fail an autocorrelation
check, because the differences between instrument types are large and
systematic:

* **Flow** is noisy and fast. A DP cell sees real turbulence, so the signal has
  high variance with a short correlation time.
* **Temperature** is smooth and slow. A thermowell has thermal mass that
  low-passes the process before the transmitter ever sees it, so a temperature
  tag cannot show high-frequency content even if the process has some.
* **Level** wanders. It integrates, so its noise has a long correlation time
  and its calibration drifts.
* **Analyzers** are slow, coarsely quantized, and updated every few minutes
  rather than every scan. Between updates the value is simply held.

Each class also carries a quantization step, because transmitters are digital.
A 12-bit transmitter over a 0-100 span resolves 0.024 units, and the resulting
staircase is visible in any zoomed-in trend of real data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from historiansim.core.noise import first_order_filter, ou_noise

__all__ = [
    "Quality",
    "InstrumentClass",
    "INSTRUMENT_CLASSES",
    "apply_instrument",
    "drift_direction",
    "calibration_drift",
]


class Quality(IntEnum):
    """Historian quality codes.

    Note what is *not* here: a frozen transmitter reports GOOD. That is exactly
    why stuck values are dangerous in a real historian and why they have to be
    modelled without a flag -- anything that marks them is doing the analyst's
    work for them.
    """

    GOOD = 0
    UNCERTAIN = 1
    BAD = 2


@dataclass(frozen=True)
class InstrumentClass:
    """Measurement characteristics for one kind of instrument.

    ``noise_sigma`` and ``lsb`` are fractions of span, so one class definition
    applies to any tag with any range.
    """

    name: str
    tau_s: float
    noise_sigma: float
    noise_tau_s: float
    lsb: float
    drift_per_day: float = 0.0
    sample_s: float = 0.0
    spike_per_day: float = 0.0
    freeze_per_month: float = 0.0
    deadband: float = 0.002

    def describe(self) -> str:
        return (
            f"{self.name}: lag {self.tau_s:g}s, noise {self.noise_sigma * 100:.2f}% "
            f"span with tau {self.noise_tau_s:g}s, resolution {self.lsb * 100:.3f}%"
        )


INSTRUMENT_CLASSES: dict[str, InstrumentClass] = {
    "flow": InstrumentClass(
        name="flow", tau_s=2.0, noise_sigma=0.006, noise_tau_s=25.0,
        lsb=1 / 4096, drift_per_day=0.00004, spike_per_day=0.05,
        freeze_per_month=0.4, deadband=0.004,
    ),
    "temperature": InstrumentClass(
        name="temperature", tau_s=45.0, noise_sigma=0.0012, noise_tau_s=240.0,
        lsb=1 / 4096, drift_per_day=0.00002, spike_per_day=0.01,
        freeze_per_month=0.5, deadband=0.0015,
    ),
    "temperature_slow": InstrumentClass(
        # A heavy thermowell in a large pocket, e.g. bulk vessel temperature.
        name="temperature_slow", tau_s=120.0, noise_sigma=0.0008, noise_tau_s=420.0,
        lsb=1 / 4096, drift_per_day=0.00002, spike_per_day=0.008,
        freeze_per_month=0.5, deadband=0.0015,
    ),
    "level": InstrumentClass(
        name="level", tau_s=8.0, noise_sigma=0.0022, noise_tau_s=90.0,
        lsb=1 / 4096, drift_per_day=0.00012, spike_per_day=0.03,
        freeze_per_month=0.6, deadband=0.003,
    ),
    "pressure": InstrumentClass(
        name="pressure", tau_s=1.5, noise_sigma=0.004, noise_tau_s=18.0,
        lsb=1 / 4096, drift_per_day=0.00003, spike_per_day=0.04,
        freeze_per_month=0.3, deadband=0.004,
    ),
    "analyzer": InstrumentClass(
        name="analyzer", tau_s=90.0, noise_sigma=0.005, noise_tau_s=600.0,
        lsb=1 / 512, drift_per_day=0.0004, sample_s=300.0, spike_per_day=0.02,
        freeze_per_month=1.2, deadband=0.006,
    ),
    "power": InstrumentClass(
        # Motor power or current from the drive or a power transducer: fast,
        # with load ripple from the process riding on it.
        name="power", tau_s=4.0, noise_sigma=0.007, noise_tau_s=45.0,
        lsb=1 / 4096, drift_per_day=0.00002, spike_per_day=0.02,
        freeze_per_month=0.3, deadband=0.004,
    ),
    "valve": InstrumentClass(
        # Valve position feedback is a clean readback of the DCS output.
        name="valve", tau_s=3.0, noise_sigma=0.0006, noise_tau_s=30.0,
        lsb=1 / 1024, spike_per_day=0.0, freeze_per_month=0.15, deadband=0.002,
    ),
    "calculated": InstrumentClass(
        # DCS-computed values inherit their inputs' noise; nothing is added.
        name="calculated", tau_s=0.0, noise_sigma=0.0, noise_tau_s=0.0,
        lsb=0.0, deadband=0.004,
    ),
    "status": InstrumentClass(
        # Discrete. Stored on change only, so the deadband is irrelevant.
        name="status", tau_s=0.0, noise_sigma=0.0, noise_tau_s=0.0,
        lsb=0.0, deadband=0.0,
    ),
}


def drift_direction(seeds, tag: str) -> float:
    """The sign of a tag's calibration drift, set once per transmitter.

    Drawn from its own named substream, reset on every call, so the simulation
    loop (where a controller reads the transmitter) and the measurement layer
    (where the historian records it) agree on the same instrument drifting the
    same way.
    """
    return 1.0 if seeds.fresh(f"drift/{tag}").random() < 0.5 else -1.0


def calibration_drift(
    cls: InstrumentClass,
    span: tuple[float, float],
    n: int,
    dt: float,
    direction: float,
) -> np.ndarray:
    """The calibration offset a transmitter of this class has walked to."""
    width = abs(span[1] - span[0]) or 1.0
    days = np.arange(n) * dt / 86400.0
    return direction * cls.drift_per_day * width * days


def apply_instrument(
    true: np.ndarray,
    cls: InstrumentClass,
    span: tuple[float, float],
    dt: float,
    rng: np.random.Generator,
    direction: float | None = None,
) -> np.ndarray:
    """Turn a true process series into what the transmitter reports.

    Order matters and follows the physical chain: the sensor lags the process,
    the transmitter adds its own noise and drift, the ADC quantizes, and a slow
    analyzer only updates on its own cycle.

    ``direction`` fixes the sign of the calibration drift; see
    :func:`drift_direction`. When omitted it is drawn from ``rng``.
    """
    width = abs(span[1] - span[0]) or 1.0
    values = np.asarray(true, dtype=float)

    if cls.tau_s > 0:
        values = first_order_filter(values, cls.tau_s, dt)

    if cls.noise_sigma > 0:
        values = values + ou_noise(
            len(values), cls.noise_sigma * width, cls.noise_tau_s, dt, rng
        )

    if cls.drift_per_day != 0.0:
        # A calibration offset that walks, with the direction set once per tag
        # rather than redrawn -- instruments drift consistently, not randomly.
        # The draw is always taken so the stream stays aligned for the spikes
        # and freezes that follow.
        drawn = 1.0 if rng.random() < 0.5 else -1.0
        sign = drawn if direction is None else direction
        values = values + calibration_drift(cls, span, len(values), dt, sign)

    if cls.sample_s > dt:
        # Held between analyzer updates: a staircase, not an interpolation.
        stride = max(1, int(round(cls.sample_s / dt)))
        idx = (np.arange(len(values)) // stride) * stride
        values = values[idx]

    if cls.lsb > 0:
        step = cls.lsb * width
        values = np.round(values / step) * step

    return values
