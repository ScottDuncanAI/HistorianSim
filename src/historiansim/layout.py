"""File names of a written dataset, in one place.

```
<dataset>/
  historian_10s.parquet    full record at the 10 s DCS scan, compressed like a real historian
  historian_60s.parquet    the same data on a regular 1-minute grid
  tags.csv                 tag dictionary
  PROCESS_DESCRIPTION.md   the plant, written for a process engineer
  FAULT_ANSWER_KEY.md      every abnormal event, its timing and its root cause
  PFD.svg, PFD.png         conceptual process flow diagram (optional, drawn by /simulate)
  metadata/                machine-readable extras: labels, ground truth, config
```
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "HISTORIAN_FULL",
    "HISTORIAN_GRID",
    "TAGS",
    "PROCESS_DESCRIPTION",
    "ANSWER_KEY",
    "METADATA",
    "DATASET_FILES",
    "PFD_FILES",
    "metadata_file",
    "ground_truth_path",
    "manifest_path",
    "labels_path",
]

HISTORIAN_FULL = "historian_10s.parquet"
HISTORIAN_GRID = "historian_60s.parquet"
TAGS = "tags.csv"
PROCESS_DESCRIPTION = "PROCESS_DESCRIPTION.md"
ANSWER_KEY = "FAULT_ANSWER_KEY.md"
METADATA = "metadata"

#: Every file in the dataset folder itself.
DATASET_FILES = (HISTORIAN_FULL, HISTORIAN_GRID, TAGS, PROCESS_DESCRIPTION, ANSWER_KEY)

#: The process flow diagram, added after generation. Optional; it shows the
#: plant only, so it also goes into a challenge folder.
PFD_FILES = ("PFD.svg", "PFD.png")


def metadata_file(dataset_dir: Path, name: str) -> Path:
    return Path(dataset_dir) / METADATA / name


def ground_truth_path(dataset_dir: Path) -> Path:
    return metadata_file(dataset_dir, "ground_truth.json")


def manifest_path(dataset_dir: Path) -> Path:
    return metadata_file(dataset_dir, "manifest.json")


def labels_path(dataset_dir: Path) -> Path:
    return metadata_file(dataset_dir, "labels_60s.parquet")
