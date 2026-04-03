# MEMORY.md

## Purpose
This file serves two roles depending on agent lifecycle phase:
- **Training phase:** raw learning log — record mistakes, discoveries, and refined rules
- **Shipped phase:** distilled field manual — curated wisdom and handoff state for the receiving orchestrator

---

## Section 1 — Graduated Rules
*(Promoted from training log after validation. Stable. Do not modify without review.)*

> Empty at initialization. Rules are promoted here after recurring patterns are confirmed across multiple runs.

---

## Section 2 — Known Failure Modes
*(Confirmed failure patterns and their mitigations.)*

> Empty at initialization.

Example format when populated:
```
- Failure: rfscikit generates floating ground nodes for shunt components labeled GND_SYM
  Mitigation: net_graph_utils.py normalize_ground() resolves this before Stage 2
  Confirmed: [date] on spdt_switch.net
```

---

## Section 3 — Known Limitations
*(What this agent reliably cannot handle yet.)*

> Empty at initialization.

Example format when populated:
```
- Cannot handle multi-port S-param blocks with >4 ports — pin mapping is undefined in current PDK pipeline
- Differential pair topologies not yet supported by ads_placeplan_generate.py
```

---

## Section 4 — Training Log
*(Raw per-run entries during development. Messy is acceptable here.)*

> Empty at initialization.

Entry format:
```
### Run [N] — [date]
Circuit: 
PDK:
Outcome: success | partial | failed
Stage reached: 1 | 2 | 3
Issues encountered:
Decisions made:
What to improve:
```

---

## Section 5 — Pause State
*(Written by agent on any pause. Cleared on successful resume and completion.)*

> No active pause.

Format (written automatically per CONSTRAINTS.md):
```yaml
pause_reason: ""
stage: ""
last_completed_step: ""
input_file: ""
outputs_produced: []
resume_instruction: ""
timestamp: ""
```

---

## Section 6 — Handoff Brief
*(Curated by human operator before shipping to project orchestrator. Replaces training log for production use.)*

> Not yet compiled. Complete training phase and promote learnings before shipping.

Suggested content when compiled:
- Summary of validated circuit types this agent has handled
- PDK(s) tested and confirmed working
- Recommended pre-checks before invoking this agent
- Edge cases the orchestrator should be aware of
- Current limitation boundaries
