"""Small-multiple trends from a dataset's 60 s grid.

For eyeballing a dataset, checking an episode's evidence, and making the figure
that goes in a write-up. One panel per tag, sharing a time axis; a loop's
setpoint is overlaid on its PV when both are present. Episode windows from the
answer key are shaded when it is available -- never use that figure for a
blind test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

__all__ = ["plot_dataset"]

SURFACE, INK, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#8a5cd1", "#d1a32a", "#d1497a"]
SHADE = "#f2e6d9"


def _episode_window(dataset_dir: Path, episode: str):
    from historiansim.layout import ground_truth_path

    truth = json.loads(ground_truth_path(dataset_dir).read_text(encoding="utf-8"))
    for ep in truth["episodes"]:
        if ep["episode_id"] == episode:
            return ep
    raise KeyError(f"no episode {episode!r} in the answer key")


def plot_dataset(
    dataset_dir: Path,
    tags: list[str] | None = None,
    episode: str | None = None,
    window_days: tuple[float, float] | None = None,
    out: Path | None = None,
    shade_episodes: bool | None = None,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dataset_dir = Path(dataset_dir)
    from historiansim.layout import HISTORIAN_GRID

    grid_path = dataset_dir / HISTORIAN_GRID
    grid = pd.read_parquet(grid_path)
    t0 = grid["timestamp"].iloc[0]

    ep = _episode_window(dataset_dir, episode) if episode else None
    if ep is not None and tags is None:
        tags = [e["tag"] for e in ep["discriminating_evidence"] if e["available"]][:6]
    if not tags:
        raise ValueError("give --tags, or --episode with an answer key present")
    missing = [t for t in tags if t not in grid.columns]
    if missing:
        raise KeyError(f"tags not in the dataset: {missing}")

    if ep is not None and window_days is None:
        pad = 2.0
        start = ep["true_onset_s"] / 86400.0 - pad
        end = ep["true_end_s"] / 86400.0 + pad
        window_days = (max(start, 0.0), end)
    elapsed = (grid["timestamp"] - t0).dt.total_seconds() / 86400.0
    if window_days is not None:
        grid = grid[(elapsed >= window_days[0]) & (elapsed <= window_days[1])]

    from historiansim.layout import ground_truth_path

    key = ground_truth_path(dataset_dir)
    if shade_episodes is None:
        shade_episodes = key.exists()
    episodes = json.loads(key.read_text(encoding="utf-8"))["episodes"] if shade_episodes and key.exists() else []

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
    })
    meta = pd.read_csv(dataset_dir / "tags.csv").set_index("tag")
    fig, axes = plt.subplots(len(tags), 1, figsize=(14, 2.4 * len(tags) + 1.2), sharex=True,
                             gridspec_kw={"hspace": 0.38}, squeeze=False)
    for i, (ax, tag) in enumerate(zip(axes[:, 0], tags)):
        color = PALETTE[i % len(PALETTE)]
        for e in episodes:
            lo = t0 + pd.Timedelta(seconds=e["true_onset_s"])
            hi = t0 + pd.Timedelta(seconds=e["true_end_s"])
            ax.axvspan(lo, hi, color=SHADE, lw=0, zorder=0)
        ax.plot(grid["timestamp"], grid[tag], color=color, lw=0.6)
        if tag.endswith(".PV") and tag.replace(".PV", ".SP") in grid.columns:
            ax.plot(grid["timestamp"], grid[tag.replace(".PV", ".SP")], color=MUTED,
                    lw=1.0, ls="--")
        desc = meta.loc[tag, "description"] if tag in meta.index else ""
        units = meta.loc[tag, "units"] if tag in meta.index else ""
        ax.set_title(f"{desc}   —   {tag}", loc="left", fontsize=11.5, color=INK, pad=7)
        ax.set_ylabel(units, fontsize=9.5, color=MUTED)
        ax.grid(True, axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(AXIS)
        ax.tick_params(colors=MUTED, labelsize=9)
        ax.set_xlim(grid["timestamp"].iloc[0], grid["timestamp"].iloc[-1])

    title = f"{dataset_dir.name}" + (f"  ·  {episode}" if episode else "")
    fig.suptitle(title, x=0.06, ha="left", fontsize=14, color=INK)
    fig.subplots_adjust(top=0.92, bottom=0.06, left=0.07, right=0.985)

    if out is None:
        # Beside the dataset, never inside it: a shaded plot is an answer key.
        plots = dataset_dir.parent / f"{dataset_dir.name}-plots"
        plots.mkdir(exist_ok=True)
        stem = episode or "_".join(t.replace(".", "-") for t in tags)[:80]
        out = plots / f"{stem}.png"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120, facecolor=SURFACE)
    plt.close(fig)
    return out
