"""Human-readable validation and difficulty reporting."""

from __future__ import annotations

from typing import Sequence

from historiansim.validation.battery import Check

__all__ = ["format_report", "format_difficulty"]

_MARK = {True: "PASS", False: "FAIL"}


def format_report(checks: Sequence[Check], verbose: bool = False) -> str:
    lines = ["", "Validation battery", "=" * 72]
    errors = 0
    for check in checks:
        mark = _MARK[check.passed]
        if not check.passed and check.severity == "warn":
            mark = "WARN"
        elif not check.passed:
            errors += 1
        lines.append(f"  [{mark}] {check.name}")
        lines.append(f"         {check.detail}")
        if verbose and check.rationale:
            lines.append(f"         why: {check.rationale}")
    lines.append("=" * 72)
    lines.append(
        f"  {sum(c.passed for c in checks)}/{len(checks)} passed"
        + (f", {errors} failing" if errors else "")
    )
    return "\n".join(lines)


def format_difficulty(manifest: dict) -> str:
    """The honest headline: how much lead a real diagnosis has over a threshold."""
    lines = ["", "Episode difficulty", "=" * 88]
    lines.append(
        f"  {'episode':<9}{'cause':<9}{'severity':<10}{'onset':>8}"
        f"{'observable':>12}{'3-sigma':>10}  first tag"
    )
    lines.append("-" * 88)

    def fmt(value):
        if value is None:
            return "never"
        return f"{value / 3600:.1f}h"

    for ep in manifest.get("episodes", []):
        if ep["class"] != "fault":
            continue
        lines.append(
            f"  {ep['episode_id']:<9}{ep['true_root_cause']:<9}"
            f"{ep.get('severity', ''):<10}"
            f"{ep['true_onset_s'] / 86400:>7.1f}d"
            f"{fmt(ep.get('detection_lead_s')):>12}"
            f"{fmt(ep.get('difficulty', {}).get('sigma_detector_lead_s')):>10}"
            f"  {ep.get('first_observable_tag') or '-'}"
        )
    lines.append("=" * 88)
    lines.append(
        "  observable = first divergence from the no-fault twin in any real tag"
    )
    lines.append(
        "  3-sigma    = when a naive threshold on the clean baseline would fire"
    )
    return "\n".join(lines)
