"""Score a root cause challenge submission against a dataset's answer key.

Implements the rules in ``CHALLENGE.md``: only rows with kind = fault are
claims; a claim overlaps an event if it overlaps [true start, true end + 6 h];
claims and events are matched one-to-one, longest overlap first; +1 per
detection, +2 more for a correct root cause, -1 per false positive.

Root causes are free text, so correctness is judged by a person (or a careful
reviewer) against the dataset's ``FAULT_ANSWER_KEY.md``. Score once to list the
matched claims, add a ``cause_correct`` column (Y/N) to the submission for
those rows, then score again. Until every matched claim is judged, the score
counts only judged ones and lists the rest under ``unjudged_rows``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

__all__ = ["score_submission", "GRACE"]

GRACE = pd.Timedelta(hours=6)
KINDS = {"fault", "operator_action", "artifact"}


def _load_claims(path: Path) -> tuple[pd.DataFrame, int]:
    sub = pd.read_csv(path, dtype=str).fillna("")
    for col in ("start_utc", "end_utc", "kind", "root_cause", "evidence_tags"):
        if col not in sub:
            raise ValueError(f"submission is missing column {col!r}")
    if "cause_correct" not in sub:
        sub["cause_correct"] = ""
    sub["row"] = sub.index + 2                     # CSV line number, header is 1
    sub["start"] = pd.to_datetime(sub["start_utc"], utc=True, errors="coerce")
    sub["end"] = pd.to_datetime(sub["end_utc"], utc=True, errors="coerce")
    sub["kind"] = sub["kind"].str.strip().str.lower()
    is_fault = sub["kind"] == "fault"
    valid = (
        sub["start"].notna()
        & sub["end"].notna()
        & (sub["end"] >= sub["start"])
        & sub["kind"].isin(KINDS)
        & (sub["evidence_tags"].str.strip() != "")
        & ~(is_fault & (sub["root_cause"].str.strip() == ""))
    )
    claims = sub[valid & is_fault].reset_index(drop=True)
    return claims, int((~valid).sum())


def score_submission(key: Path | pd.DataFrame, submission_path: Path) -> dict:
    key = key.copy() if isinstance(key, pd.DataFrame) else pd.read_csv(key)
    key["start"] = pd.to_datetime(key["start_utc"], utc=True)
    key["end"] = pd.to_datetime(key["end_utc"], utc=True)
    events = key[key["kind"] == "fault"].reset_index(drop=True)
    claims, discarded = _load_claims(Path(submission_path))

    pairs = []
    for ci, c in claims.iterrows():
        for ei, e in events.iterrows():
            lo = max(c["start"], e["start"])
            hi = min(c["end"], e["end"] + GRACE)
            if hi > lo:
                pairs.append(((hi - lo).total_seconds(), ci, ei))
    pairs.sort(reverse=True)

    matched_c, matched_e, matches = set(), set(), []
    for _, ci, ei in pairs:
        if ci in matched_c or ei in matched_e:
            continue
        matched_c.add(ci)
        matched_e.add(ei)
        matches.append((ci, ei))

    rows = []
    for ci, ei in matches:
        c, e = claims.loc[ci], events.loc[ei]
        judged = c["cause_correct"].strip().upper()[:1]
        rows.append({
            "row": c["row"], "event": e["event_id"],
            "true_cause": f'{e["cause_id"]} {e["cause"]}',
            "claimed_cause": c["root_cause"],
            "correct": {"Y": True, "N": False}.get(judged),
            "start_error_h": abs((c["start"] - e["start"]).total_seconds()) / 3600,
        })
    detail = pd.DataFrame(rows)

    detected = len(matches)
    is_correct = detail["correct"].eq(True) if detected else pd.Series(dtype=bool)
    correct = int(is_correct.sum())
    unjudged = detail.loc[detail["correct"].isna(), "row"].tolist() if detected else []
    false_pos = len(claims) - detected
    errs = detail.loc[is_correct, "start_error_h"] if detected else pd.Series(dtype=float)
    found = {events.loc[e, "event_id"] for e in matched_e}
    return {
        "points": detected + 2 * correct - false_pos,
        "max_points": 3 * len(events),
        "detected": detected,
        "correct_cause": correct,
        "unjudged_rows": unjudged,
        "false_positives": false_pos,
        "missed": len(events) - detected,
        "discarded_rows": discarded,
        "median_start_error_h": float(errs.median()) if len(errs) else None,
        "missed_events": sorted(set(events["event_id"]) - found),
        "detail": detail,
    }
