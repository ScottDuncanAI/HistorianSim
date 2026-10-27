"""Precomputed disturbance channels.

Every channel is generated as a full array before the run starts, rather than
sampled inside the loop. Two reasons, and the second is the important one:

1. Vectorized generation is orders of magnitude faster than drawing per scan.
2. **The no-fault twin depends on it.** Disturbances must be bit-identical
   between a fault run and its twin. Precomputing from a named RNG substream
   guarantees that, whereas drawing inside the loop would couple the draws to
   whatever else consumed randomness that scan.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["DisturbanceBundle"]


@dataclass
class DisturbanceBundle:
    """Disturbance channels on the controller scan grid."""

    channels: dict[str, np.ndarray]

    def __post_init__(self) -> None:
        lengths = {len(v) for v in self.channels.values()}
        if len(lengths) > 1:
            raise ValueError(f"disturbance channels have differing lengths: {lengths}")

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.channels)

    @property
    def n(self) -> int:
        return len(next(iter(self.channels.values()))) if self.channels else 0

    def resolve(self, k: int, t: float) -> dict[str, float]:
        return {name: float(arr[k]) for name, arr in self.channels.items()}

    def with_override(self, name: str, values: np.ndarray) -> "DisturbanceBundle":
        """Return a copy with one channel replaced.

        Used to build a competing-cause counterfactual: identical run, one
        upstream driver behaving differently.
        """
        if name not in self.channels:
            raise KeyError(f"no disturbance channel {name!r}")
        updated = dict(self.channels)
        updated[name] = np.asarray(values, dtype=float)
        return DisturbanceBundle(updated)
