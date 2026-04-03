# IMPROVEMENT.md

## Purpose
This file defines what the `net-to-ads` agent is allowed to improve autonomously, what requires human approval, and what is permanently frozen. It also defines the process for making and recording improvements safely.

---

## What Is Frozen — Never Modify Without Human Approval

These define the agent's identity, boundaries, and governance. Changing them changes what the agent fundamentally is.

| File | Reason Frozen |
|---|---|
| `IDENTITY.md` | Defines role, scope, and reporting structure |
| `PLAYBOOK.md` | Defines the canonical 3-stage workflow and escalation logic |
| `CONSTRAINTS.md` | Defines hard runtime limits and irreversible action rules |
| `IMPROVEMENT.md` | This file — cannot rewrite its own improvement rules |
| `SKILLS.md` | Adding or removing skills changes capability boundary — requires human decision |

**If the agent identifies a problem with any frozen file, it logs the observation to MEMORY.md Section 4 with tag `[FRAMEWORK-ISSUE]` and waits for human review. It does not edit the file.**

---

## What Is Open for Autonomous Improvement

These are execution-layer artifacts. The agent owns them and may improve them based on observed outcomes.

| Target | What Can Be Improved |
|---|---|
| `workspace-scripts/*.py` | Bug fixes, robustness improvements, better error handling, edge case handling |
| `workspace-netlists/*_prep.net` | Correction of annotation errors discovered during runs |
| `workspace-netlists/*_placeplan.yaml` | Placement refinements that improve schematic readability |
| `workspace-netlists/*_buildplan.yaml` | Coordinate adjustments that reduce wire crossings or improve layout |
| `MEMORY.md` | Always writable — log entries, promote rules, update handoff brief |

---

## Improvement Triggers — When to Improve

The agent should consider an improvement when any of the following occur:

1. **Repeated failure** — same error occurs across 2+ runs on different circuits
2. **Workaround applied** — agent had to deviate from PLAYBOOK.md to complete the task
3. **Assumption logged** — agent made an undocumented assumption to proceed
4. **Edge case encountered** — input pattern not covered by existing script logic
5. **Checker warning** — `ads-schematic-checker` passes but with recurring warning type

A single failure is a log entry. A pattern is an improvement trigger.

---

## Improvement Process — How to Make a Change

### Step 1 — Identify
Log the issue to MEMORY.md Section 4 with:
```
[IMPROVEMENT-CANDIDATE]
Target: <script or artifact name>
Trigger: <what caused this — repeated failure | workaround | assumption | edge case | checker warning>
Observed: <what happened>
Proposed fix: <what should change and why>
Risk: low | medium | high
```

### Step 2 — Assess Risk
Before making any change:

| Risk Level | Criteria | Action |
|---|---|---|
| Low | Change is isolated to one function, no effect on output schema | Proceed autonomously |
| Medium | Change affects multiple functions or output format | Log to MEMORY.md, proceed with caution, note in status report |
| High | Change affects inter-script interfaces, YAML schemas, or ADS API calls | Do not proceed — flag to orchestrator for human review |

### Step 3 — Make the Change
- Edit the target script or artifact directly
- Add an inline comment: `# IMPROVED [date]: <one line reason>`
- Do not remove existing logic without confirming the replacement works first — comment out, don't delete

### Step 4 — Validate
- Re-run the step that originally failed using the same or equivalent input
- Confirm the issue is resolved
- If validation fails, revert the change and re-log as `[IMPROVEMENT-FAILED]`

### Step 5 — Record
Promote the improvement to MEMORY.md:
- If successful → add to Section 1 (Graduated Rules) or Section 2 (Known Failure Modes) as appropriate
- Clear the `[IMPROVEMENT-CANDIDATE]` entry from Section 4
- Note the changed file and date in the run log

---

## What Good Improvement Looks Like

Improvements to scripts should make them:
- **More robust** — handle edge cases that previously caused failures
- **More informative** — better error messages, clearer logging
- **More consistent** — align output format with what downstream steps expect

Improvements should NOT:
- Change the purpose of a script (that's a PLAYBOOK change — frozen)
- Add new external dependencies without human approval
- Change output file naming conventions (breaks orchestrator expectations)
- Remove validation or error-checking logic to make things faster

---

## Improvement Log Summary
*(Maintained here as a high-level index; full entries live in MEMORY.md Section 4)*

| Date | Target | Change | Outcome |
|---|---|---|---|
| — | — | — | — |
