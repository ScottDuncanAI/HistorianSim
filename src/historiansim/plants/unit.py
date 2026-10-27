"""The interface a process unit must provide.

Only two things vary between units: the derivatives function and the
configuration. Control, disturbances, faults, measurement, historian and
validation are identical everywhere, which is why they live outside this class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

__all__ = ["UnitModel"]


class UnitModel(ABC):
    """Base class for a lumped-parameter continuous process unit.

    Subclasses declare their states, the manipulated variables they consume,
    and the disturbances they respond to, then implement :meth:`derivatives`
    and :meth:`signals`.
    """

    #: Registry key, e.g. ``heated_stirred_tank``; matches the plant name.
    name: str = "unnamed"

    #: Ordered state variable names; the ordering defines the state vector.
    state_names: tuple[str, ...] = ()

    #: Manipulated variables this unit expects in ``u``, e.g. valve positions.
    mv_names: tuple[str, ...] = ()

    #: Disturbance channels this unit expects in ``d``.
    disturbance_names: tuple[str, ...] = ()

    def __init__(self, params: dict[str, float] | None = None):
        merged = dict(self.default_params())
        for key, value in (params or {}).items():
            if key not in merged:
                raise KeyError(
                    f"{self.name}: unknown parameter {key!r}. "
                    f"Known: {sorted(merged)}"
                )
            merged[key] = float(value)
        self.params = merged
        self.validate_params(self.params)

    # -- to implement -----------------------------------------------------

    @staticmethod
    @abstractmethod
    def default_params() -> dict[str, float]:
        """Physical parameters and their design-case values."""

    @abstractmethod
    def derivatives(
        self,
        t: float,
        x: np.ndarray,
        u: dict[str, float],
        d: dict[str, float],
        p: dict[str, float],
    ) -> np.ndarray:
        """State derivatives ``dx/dt``.

        ``p`` is the *effective* parameter set for this instant: the base
        parameters after degradation and any active process faults have
        modified them. Faults reach the process only through this argument --
        nothing is ever added to a finished signal.
        """

    @abstractmethod
    def signals(
        self,
        t: float,
        x: np.ndarray,
        u: dict[str, float],
        d: dict[str, float],
        p: dict[str, float],
    ) -> dict[str, float]:
        """Every true process value an instrument could be attached to.

        Includes the states themselves plus derived quantities a plant would
        actually compute and trend -- duty, calculated UA, approach
        temperature, balance residuals.
        """

    # -- optional overrides ----------------------------------------------

    def validate_params(self, p: dict[str, float]) -> None:
        """Raise if a parameter combination is physically nonsensical."""

    def steady_inputs(
        self, targets: dict[str, float], d: dict[str, float], p: dict[str, float]
    ) -> dict[str, float]:
        """Manipulated variables that hold ``targets`` at steady state.

        Used to start a run already at equilibrium. Without it the first hours
        of every dataset are a startup transient, which wastes the clean
        baseline the training window depends on.
        """
        raise NotImplementedError(f"{self.name} does not provide steady_inputs")

    def steady_state(
        self, u: dict[str, float], d: dict[str, float], p: dict[str, float]
    ) -> np.ndarray:
        """State vector at equilibrium for the given inputs."""
        raise NotImplementedError(f"{self.name} does not provide steady_state")

    # -- helpers ----------------------------------------------------------

    def state_index(self, name: str) -> int:
        return self.state_names.index(name)

    def state_dict(self, x: np.ndarray) -> dict[str, float]:
        return dict(zip(self.state_names, (float(v) for v in x)))

    def __repr__(self) -> str:
        return f"{type(self).__name__}(states={list(self.state_names)})"
