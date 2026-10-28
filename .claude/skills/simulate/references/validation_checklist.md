# Before calling a dataset done

## Automated (all must pass)

- [ ] `historiansim check-plant <name>`, stages 1–5.
- [ ] `historiansim generate ...` ends with every check passing. That includes
      `recipe` (unique causes, mechanisms and components; no overlap; a
      clean 14-day baseline), `baseline_settled`, `solvable`,
      `not_trivially_detectable`, `no_range_clamping`, `dataset_layout` and
      `no_answer_leak`.
- [ ] Transmitter ranges are sized to the duty: the operating value sits at
      roughly 20-60 % of span, with headroom for the worst fault plus the
      seasonal swing. Oversized ranges inflate noise and drift; undersized
      ones clamp the evidence.
- [ ] `python -m pytest tests -q` passes, including the catalog sweep for the
      new plant.

## Read the difficulty table (`historiansim report <dataset>`)

- [ ] Every fault has a *first observable* time. `never` means the episode
      is invisible: fix the severity or duration.
- [ ] No subtle, masked fault is caught by the naive 3-sigma column at the
      same moment it becomes observable.

## Physics and realism review

For each episode, run
`historiansim plot <dataset> --episode EP-00n --out <dataset>-validation/plots/EP-00n.png`
and check:

- [ ] The confirming evidence moves the way the answer key says.
- [ ] The tags that rule out competitors are actually flat.
- [ ] The controlled variable is masked where the cause says
      `masked_by_control`.
- [ ] The magnitudes are plausible for the plant: valves are not saturated
      unless that is the point, and temperatures and flows are in range.

For the whole record:

- [ ] Baseline balances nearly close: a small offset, never exactly zero.
- [ ] Noise is coloured per instrument class (`noise_is_colored` reports
      correlation times).
- [ ] Lagged tags peak at their declared delay (`transport_lag`).
- [ ] Some stuck transmitters, spikes and node dropouts exist, away from the
      episodes.

## Blind diagnosis

1. Run `historiansim make-challenge <dataset> --out <scratch>/<dataset>-challenge`,
   with `<scratch>` a temporary directory outside `output/` and the repo. It writes
   the historian files, tag list, process description, `CHALLENGE.md` and
   a submission template, and no answer key.
2. Spawn a fresh subagent with only that folder. Prompt it with the task in
   `CHALLENGE.md` and ask for a submission CSV in the template's format,
   with its reasoning in `notes`. Do not give it the cause catalog, the
   design doc or this repo.
3. Run `historiansim score <dataset> <submission.csv>`. Then add a
   `cause_correct` column (Y/N), judging each matched claim against
   `FAULT_ANSWER_KEY.md`: right item *and* right mechanism. Score again.
   Copy the scored submission to `<dataset>-validation/blind-submission.csv`
   and delete the challenge folder.
4. For every miss or wrong cause, decide whose fault it is:
   - **The data's.** The evidence was not in the data, was ambiguous, or
     the process description lacked a relationship needed to reason it
     out. Fix and regenerate.
   - **The agent's.** The evidence is there and a careful engineer would
     find it. Leave it: that is what makes the dataset hard.
5. False positives on operator actions or artifacts are the agent's problem,
   unless the process description failed to explain the behaviour.

## Check the PFD

- Every balloon tag exists in `tags.csv`, and every loop in `loops.py`
  (cascades and ratio stations included) is drawn with the same pairing.
- The drawing passes the PFD skill's render checklist.
- `PFD.svg` and `PFD.png` were copied into the dataset folder from
  `plants/<name>/pfd/`, and `historiansim audit <dataset>` passes.

## Write it down

Write `<dataset>-validation/VALIDATION.md`, beside the dataset folder and
never inside it (see `docs/validation/cstr-rca-s7.md` for an example). The
validation folder holds only `VALIDATION.md`, `plots/` and
`blind-submission.csv`. Include the
check results, the difficulty table, the blind score, each miss with its
classification, and every fix made.
