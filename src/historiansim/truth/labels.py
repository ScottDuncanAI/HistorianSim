"""Per-sample labels for supervised and semi-supervised work.

Two label columns, not one, because the interesting question is rarely binary.
``is_fault`` marks a real abnormality; ``is_benign`` marks something that moved
for a legitimate reason. A detector scored only on ``is_fault`` gets no credit
for keeping quiet during a deliberate rate change, which is exactly the
behaviour that matters in a control room.

Labels are keyed to *true onset*, not first observability. A model that fires
before the fault was visible in any tag is not early -- it is reading a signal
that is not there, and the gap between the two columns in the manifest is what
lets that be checked.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from historiansim.faults.scheduler import EpisodePlan

__all__ = ["build_labels"]


def build_labels(
    index: pd.DatetimeIndex, plan: EpisodePlan, dt_scan: float
) -> pd.DataFrame:
    """One row per scan: what was happening, and whether it was a fault."""
    n = len(index)
    seconds = np.arange(n) * dt_scan

    is_fault = np.zeros(n, dtype=bool)
    is_benign = np.zeros(n, dtype=bool)
    episode_id = np.full(n, "", dtype=object)
    cause_id = np.full(n, "", dtype=object)
    symptom = np.full(n, "", dtype=object)
    severity = np.full(n, "", dtype=object)
    n_active = np.zeros(n, dtype=np.int8)

    for ep in sorted(plan.episodes, key=lambda e: e.onset_s):
        end = ep.end_s if ep.end_s is not None else seconds[-1] + dt_scan
        active = (seconds >= ep.onset_s) & (seconds < end)
        if not active.any():
            continue

        if ep.kind == "fault":
            is_fault |= active
            n_active[active] += 1
        else:
            is_benign |= active

        # Where episodes overlap, the label lists both rather than silently
        # keeping the last one written.
        for arr, value in (
            (episode_id, ep.id),
            (cause_id, ep.cause_id),
            (symptom, ep.symptom),
            (severity, ep.severity),
        ):
            existing = arr[active]
            arr[active] = np.where(
                existing == "", value, np.char.add(existing.astype(str), f"+{value}")
            )

    return pd.DataFrame(
        {
            "timestamp": index,
            "is_fault": is_fault,
            "is_benign": is_benign,
            "n_active_faults": n_active,
            "episode_id": episode_id.astype(str),
            "cause_id": cause_id.astype(str),
            "symptom_class": symptom.astype(str),
            "severity": severity.astype(str),
        }
    )
