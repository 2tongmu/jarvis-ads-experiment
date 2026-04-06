# MEMORY.md

## Purpose
This file serves two roles depending on agent lifecycle phase:
- **Training phase:** raw learning log — record mistakes, discoveries, and refined rules
- **Shipped phase:** distilled field manual — curated wisdom and handoff state for the receiving orchestrator

---

## Section 1 — Graduated Rules
*(Promoted from training log after validation. Stable. Do not modify without review.)*

[SCRIPT-ADDED] ads_create_pdk_workspace.py: Create ADS workspace with PDK loaded via lib.defs INCLUDE — replaces 5-turn exploration of workspace + PDK setup sequence.
[SCRIPT-ADDED] ads_query_pdk_cells.py: List all cells in ADS PDK library with views and params — replaces manual AEL/directory decoding to find correct API cell name.
[SCRIPT-ADDED] ads_probe_fet_pins.py: Probe PDK component pin snap_point offsets at any angle — replaces 4-turn exploration of InstTerm API to find pin coordinate method.

---

## Section 2 — Known Failure Modes
*(Confirmed failure patterns and their mitigations.)*

- Failure: Using `PP1029_CPW_PDK` as the cell name in `de.LCVName("WIN_PP1029_DESIGN_KIT", ...)` causes RuntimeError "Could not find cell".
  Mitigation: The ADS Python API cell name is `WIN_PP1029_CPW`; `PP1029_CPW_PDK` is only the TransistorModel parameter value and the netlist export identifier.
  Confirmed: 2026-04-06 on spdt_switch PDK build.

- Failure: `InstTerm.position` attribute does not exist in ADS 2026 Update 1 Python API.
  Mitigation: Use `list(inst.get_inst_term_iter())[n].inst_pins[0].snap_point` instead.
  For WIN_PP1029_CPW at angle=0: pin1(gate)=(0,0), pin2(drain)=(+0.5,+0.5), pin3(source)=(+0.5,-0.5) relative to origin.
  At angle=90: pin1(gate)=(0,0), pin2(drain)=(-0.5,+0.5), pin3(source)=(+0.5,+0.5).
  Confirmed: 2026-04-06 on spdt_switch PDK build.

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

### Run 1 — 2026-04-06
Circuit: spdt_switch (2-stage SPDT, 2–18 GHz)
PDK: WIN_PP1029_DESIGN_KIT
Outcome: success
Stage reached: 3

Issues encountered:
- Initial FET cell reference `PP1029_CPW_PDK` did not resolve in the ADS Python API.
  The correct cell name in WIN_PP1029_DESIGN_KIT is `WIN_PP1029_CPW` (with `symbol` view).
  The generated netlist uses `PP1029_CPW_PDK` as the model identifier (PDK internal).
- `InstTerm.position` attribute does not exist in this ADS Python version.
  Used `inst_pin.snap_point` via `get_inst_term_iter()` → `inst_pins` to probe pin positions.
  Ultimately used analytically computed pin offsets based on snap_point data.

Decisions made:
- GBIAS networks for all 4 FETs (Q1a, Q3a, Q1b, Q3b) replaced with 10 kΩ gate stubs to GND.
  This is consistent with GBIAS_SKIPPED markers in _ads_import.net.
- Series FETs placed at angle=90 (drain left, source right, gate below).
  Shunt FETs placed at angle=0 (drain top, source below, gate left).
- All FET pin offsets hard-coded after verification via ADS Python snap_point probe.

What to improve:
- Consider adding a helper that auto-probes snap_point positions at build time for robustness
  across PDK versions (currently hard-coded from a known-good probe run).

[PHASE-COMPLETE] — 2026-04-06
Phase: 1 (Schematic Generation)
Checker result: ALL CHECKS PASSED ✅
  - No floating nodes
  - Signal path Term1→Term2 connected (2 hops)
  - All 4 PDK FETs connected
  - GND node in 14 components
Outputs confirmed:
  - spdt_switch_prep.net         ✅
  - spdt_switch_ads_import.net   ✅
  - spdt_switch_placeplan.yaml   ✅
  - spdt_switch_ads_buildplan.yaml ✅
  - spdt_switch_ads_generated.net ✅ (46 lines)
ADS workspace: C:\Users\jarvis\ads_projects\spdt_switch_pdk_wrk
Awaiting human sign-off to advance to Phase 2 (simulation).

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

## Section 7 — ADS Procedure Library
*(Scripts and procedures discovered during runs. Each entry is either a
script that was created or a documented manual procedure.)*

Entry format:
```
---
task: ""
type: script | procedure
script_name: ""
procedure_summary: ""
inputs: ""
outputs: ""
first_discovered: ""
validated_on: []
cost_before: ""
cost_after: ""
```

---
task: "Create ADS workspace with PDK loaded via lib.defs INCLUDE"
type: script
script_name: ads_create_pdk_workspace.py
procedure_summary: >
  Creates + opens an ADS workspace with a PDK library injected.
  Key pattern: create_workspace() first, then append INCLUDE to lib.defs,
  then workspace.open(). PDK is visible only if INCLUDE is written before open().
inputs: "wrk_dir (Windows path), lib_name (str), pdk_dir (Windows path to PDK root)"
outputs: "(workspace, library) tuple; PDK library confirmed visible"
first_discovered: "2026-04-06 Run 1 (spdt_switch PDK build)"
validated_on: ["2026-04-06 spdt_switch Phase 1"]
cost_before: "~5 turns of exploration (create_workspace, lib.defs format, open sequence)"
cost_after: "1 import + 1 function call"

---
task: "Discover correct ADS Python API cell name for PDK components"
type: script
script_name: ads_query_pdk_cells.py
procedure_summary: >
  Lists all cells in a PDK library with their views and optionally parameter names.
  Critical: PDK cell name in ADS Python API (WIN_PP1029_CPW) ≠ TransistorModel
  parameter value (PP1029_CPW_PDK) ≠ directory name (%W%I%N_%P%P1029_%C%P%W).
  Always query via workspace.open_library(pdk_name).cells to get true API names.
inputs: "Open ADS workspace, PDK library name string"
outputs: "List of {name, views} dicts; printed table"
first_discovered: "2026-04-06 Run 1 — PP1029_CPW_PDK RuntimeError triggered cell name search"
validated_on: ["2026-04-06 spdt_switch Phase 1"]
cost_before: "~6 turns (directory decoding, AEL inspection, cell enumeration)"
cost_after: "1 script run → correct cell name immediately"

---
task: "Probe PDK component pin positions (snap_point coordinates)"
type: script
script_name: ads_probe_fet_pins.py
procedure_summary: >
  Probes absolute pin snap_point coordinates for a PDK component at any rotation angle.
  InstTerm.position does NOT exist in ADS 2026 Update 1.
  Correct path: get_inst_term_iter() → it.inst_pins → ip.snap_point (PointF).
  Places scratch instances and rolls back — no design modification.
  Outputs Python dict literal for copy-paste into builder scripts.
inputs: "Open workspace, lib name, cell name, scratch design LCV, angles list"
outputs: "Dict {angle: {pin_number: (x, y)}}; Python dict literal for builder scripts"
first_discovered: "2026-04-06 Run 1 — InstTerm.position AttributeError → snap_point discovery"
validated_on: ["2026-04-06 spdt_switch Phase 1 WIN_PP1029_CPW at angle=0 and angle=90"]
cost_before: "~4 turns (position attr fail, dir() inspection, inst_pins discovery, snap_point confirmation)"
cost_after: "1 script run → all pin offsets for all angles at once"

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
