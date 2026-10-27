"""Ballast tag generation: neighbouring units running normally.

These need no coupled physics. What they need is to be *plausibly boring* --
loops sitting on setpoint with their own noise, outputs slowly compensating for
the weather, the occasional setpoint move and spell in manual. They cost almost
nothing to generate and they turn tag selection from a non-problem into a real
one.

They share the ambient driver with the real unit, so they carry a common-cause
correlation with it. That is the point: a correlation search across the tag list
will surface them, and something has to rule them out on structural grounds
rather than statistical ones.
"""

from __future__ import annotations

import numpy as np

from historiansim.core.noise import ou_noise
from historiansim.core.rng import SeedBank
from historiansim.tags import TagSpec

__all__ = ["generate_ballast"]

_MODE_AUTO = 1
_MODE_MAN = 0


def generate_ballast(
    specs: list[TagSpec],
    ambient: np.ndarray,
    dt: float,
    seeds: SeedBank,
) -> dict[str, np.ndarray]:
    """Produce a true-value series for every ballast tag.

    Each loop draws from its own named substream keyed on the loop name, so
    adding or removing ballast never disturbs the real unit's randomness.
    """
    n = len(ambient)
    anomaly = ambient - ambient.mean()
    scale = np.std(anomaly) or 1.0
    out: dict[str, np.ndarray] = {}

    by_loop: dict[str, list[TagSpec]] = {}
    for spec in specs:
        by_loop.setdefault(spec.loop or spec.name, []).append(spec)

    for loop, tags in by_loop.items():
        rng = seeds.get(f"ballast/{loop}")
        pv_spec = next((t for t in tags if t.role == "PV"), None)
        if pv_spec is None:
            continue

        width = pv_spec.hi - pv_spec.lo
        sp_value = pv_spec.lo + width * (0.35 + 0.3 * rng.random())

        # A setpoint that is stepped once or twice over the campaign, held flat
        # in between. Real loops are not moved every day.
        setpoint = np.full(n, sp_value)
        for _ in range(int(rng.integers(0, 3))):
            at = int(rng.integers(n // 10, n))
            setpoint[at:] = setpoint[at] * float(rng.uniform(0.92, 1.08))

        # Ambient coupling is weak but nonzero -- enough to be found by a
        # correlation sweep, not enough to mean anything.
        coupling = float(rng.uniform(-0.35, 0.35)) * width * 0.02
        pv = (
            setpoint
            + coupling * anomaly / scale
            + ou_noise(n, width * float(rng.uniform(0.002, 0.010)),
                       float(rng.uniform(60.0, 900.0)), dt, rng)
        )

        # The output carries the low-frequency compensation, as it should.
        op = (
            45.0
            + 12.0 * coupling / (width * 0.02 + 1e-12) * anomaly / scale
            + ou_noise(n, float(rng.uniform(0.4, 1.8)),
                       float(rng.uniform(600.0, 3600.0)), dt, rng)
        )
        # Held as a 0-1 fraction like every other controller output; the
        # measurement layer converts OP tags to percent for display. Emitting
        # percent here got scaled twice and pinned every ballast OP at 100 %.
        op = np.clip(op, 0.0, 100.0) / 100.0

        mode = np.full(n, _MODE_AUTO, dtype=np.int8)
        if rng.random() < 0.25:                     # some loops sit in manual
            start = int(rng.integers(0, max(n - 10, 1)))
            length = int(rng.uniform(0.5, 6.0) * 86400.0 / dt)
            mode[start:start + length] = _MODE_MAN

        for spec in tags:
            if spec.role == "PV":
                out[spec.name] = pv
            elif spec.role == "SP":
                out[spec.name] = setpoint
            elif spec.role == "OP":
                out[spec.name] = op
            elif spec.role == "MODE":
                out[spec.name] = mode.astype(float)

    return out
