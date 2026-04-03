# GRADUATION.md

## Purpose
This file defines the stop criteria for each development phase of the `net-to-ads` agent. The agent halts self-improvement and requests human review when the current phase's stop criterion is met. A human operator advances the phase by editing this file.

This file is **human-controlled**. The agent reads it but never edits it.

---

## Current Phase

```yaml
phase: 1
label: "Schematic Generation"
status: active
```

---

## Phase Definitions

### Phase 1 — Schematic Generation
**Stop criterion:** ADS schematic is successfully created and `ads-schematic-checker` passes with zero errors.

**Agent behavior on stop:**
- Save all output artifacts (`_prep.net`, `_ads_import.net`, `_placeplan.yaml`, `_buildplan.yaml`)
- Write phase completion summary to MEMORY.md Section 4 with tag `[PHASE-COMPLETE]`
- Notify orchestrator and human operator via Telegram
- Halt — do not proceed to simulation or any further action
- Await human sign-off before resuming

**Human check at this phase:**
- Open ADS schematic manually
- Verify component placement and connectivity visually
- Confirm PDK components are correct
- Sign off by advancing `phase` to `2` in this file

---

### Phase 2 — Simulation Execution
**Stop criterion:** Agent successfully runs an S-parameter simulation in ADS and returns valid data (non-empty, physically plausible S-parameter results across the defined frequency range).

**Agent behavior on stop:**
- Save simulation output data file
- Write brief result summary to MEMORY.md (frequency range, key S-param values at a spot frequency)
- Notify orchestrator and human operator via Telegram
- Halt — do not post-process, plot, or interpret results
- Await human sign-off before resuming

**Human check at this phase:**
- Verify simulation completed without ADS errors
- Spot-check S-parameter results against rfscikit baseline
- Sign off by advancing `phase` to `3` in this file

---

### Phase 3 — Result Validation
**Stop criterion:** Agent compares ADS simulation output against the original rfscikit `.net` baseline and confirms delta is within acceptable tolerance (default: ≤ 0.1 dB across full frequency range).

**Agent behavior on stop:**
- Write comparison report to MEMORY.md with delta summary
- Flag any frequency points where delta exceeds tolerance
- Notify orchestrator and human operator via Telegram
- Halt — await human review of comparison report

**Human check at this phase:**
- Review delta report
- Decide if tolerance is acceptable or if PDK mapping needs refinement
- Sign off by advancing `phase` to `4` in this file

---

### Phase 4 — Release Candidate
**Stop criterion:** Agent completes the full pipeline (netlist → schematic → simulation → validation) end-to-end on 2 different circuit types without human intervention, with all checks passing.

**Agent behavior on stop:**
- Write full handoff brief to MEMORY.md Section 6
- Notify human operator: "Ready for release review"
- Halt all self-improvement activity
- Await human release decision

**Human check at this phase:**
- Review MEMORY.md Section 6 handoff brief
- Review IMPROVEMENT.md improvement log for any unresolved medium/high risk items
- Make release decision: approve → update `status` to `released` below, or reject → reset phase and log reason

---

### Phase 5 — Released
**Stop criterion:** N/A — agent is in production. Self-improvement is suspended.

**Agent behavior:**
- Execute tasks per PLAYBOOK.md
- Log issues to MEMORY.md as normal
- Do NOT apply autonomous improvements — flag all `[IMPROVEMENT-CANDIDATE]` items to orchestrator for human-gated update cycles

---

## Release Status

```yaml
released: false
release_date: null
released_by: null
notes: ""
```

---

## Phase Advancement — Human Instructions

To advance the agent to the next phase:
1. Open this file
2. Update the `phase` number under **Current Phase**
3. Optionally add a note under `notes` in Release Status
4. Save — the agent will read the updated phase on next invocation

To roll back a phase (if issues found during human check):
1. Decrement `phase` under **Current Phase**
2. Add a `[PHASE-ROLLBACK]` entry to MEMORY.md Section 4 with reason
3. The agent resumes self-improvement from the rolled-back phase criteria

---

## Stop Criterion History

| Phase Advanced | Date | Signed Off By | Notes |
|---|---|---|---|
| — | — | — | — |
