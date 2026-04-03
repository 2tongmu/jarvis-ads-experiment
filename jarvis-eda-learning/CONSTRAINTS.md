# CONSTRAINTS.md

## Purpose
These are hard runtime boundaries that apply regardless of task, circuit type, or orchestrator instruction. They cannot be overridden by the PLAYBOOK or by the orchestrator without human approval.

---

## Token Limits

| Threshold | Action |
|---|---|
| Soft limit: 50,000 tokens | Log warning to MEMORY.md, continue |
| Hard limit: 100,000 tokens | Pause immediately, save state to MEMORY.md, report to orchestrator |

On hard limit pause, save to MEMORY.md:
- Current stage (1 / 2 / 3)
- Last completed step within stage
- Input files consumed
- Output files produced so far
- Token count at pause
- Suggested resume instruction

---

## Time Limits

| Threshold | Action |
|---|---|
| Soft limit: 10 minutes | Log warning to MEMORY.md, continue |
| Hard limit: 20 minutes | Pause immediately, save state to MEMORY.md, report to orchestrator |

On hard limit pause, save to MEMORY.md:
- Current stage and step
- Wall time elapsed
- Last successful artifact produced
- Reason for slowdown if known
- Suggested resume instruction

---

## Cost Limits (per run)

| Threshold | Action |
|---|---|
| Soft limit: $0.10 USD | Log warning to MEMORY.md, continue |
| Hard limit: $0.25 USD | Pause, report to orchestrator, await instruction |

---

## Irreversible Action Rules
These actions require explicit confirmation before execution — never assume permission:

- Overwriting an existing ADS schematic in the target project
- Deleting or replacing any `.net` or `.yaml` artifact that already exists
- Modifying the PDK mapping table

If any of the above are required, stop and ask before proceeding.

---

## On Any Unhandled Exception
Regardless of stage or step:
1. Catch the error
2. Log full error message and stack trace to MEMORY.md
3. Save current stage, step, and last known good state to MEMORY.md
4. Send Telegram notification to human operator
5. Halt — do not retry automatically unless orchestrator instructs

---

## Pause State — Minimum Required Fields
Every pause entry written to MEMORY.md must include:

```yaml
pause_reason: ""           # token_limit | time_limit | cost_limit | exception | escalation
stage: ""                  # 1 | 2 | 3
last_completed_step: ""
input_file: ""
outputs_produced: []
resume_instruction: ""
timestamp: ""
```

---

## What Cannot Be Overridden
- Hard token, time, and cost limits
- Irreversible action confirmation requirement
- Mandatory MEMORY.md update on pause
- Telegram notification on unhandled exception
