# PLAYBOOK.md

## Task
Convert a rfscikit-generated `.net` file into a simulation-ready ADS schematic using a specified PDK.

---

## Workflow — 3 Stages

### Stage 1 — Prepare Netlist for ADS Translation
**Script:** `net_prepare.py`

Steps:
1. Load and validate the input `.net` file using `net_parse.py`
   - Confirm all nodes, component references, and port definitions are present
   - Flag any unrecognized component types — do not proceed if critical components are unrecognized
2. Build connectivity graph using `net_graph_utils.py`
   - Identify backbone (signal path) vs. shunt/bias groups
   - Flag floating nodes or disconnected components
3. Annotate each component with `@PDK_SWAP` tag based on PDK mapping provided
   - Exact match → annotate directly
   - No match found → flag component, log to MEMORY.md, escalate to orchestrator before continuing
4. Output: `<circuit_name>_prep.net`

**Decision Rules:**
- If >20% of components have no PDK match → pause entire stage, report to orchestrator
- If <20% have no PDK match → annotate matched ones, flag unmatched, continue with warning
- If connectivity graph has floating nodes → flag and continue; do not silently ignore

---

### Stage 2 — Generate ADS-Import-Ready Netlist
**Script:** `ads_import_netlist.py`

Steps:
1. Load `<circuit_name>_prep.net`
2. Translate component syntax to ADS netlist format per `ads-netlist-format.md`
   - Replace `@PDK_SWAP` annotated components with PDK cell references
   - Map port numbering to ADS port conventions
   - Validate pin-count consistency for each substituted component
3. Output: `<circuit_name>_ads_import.net`
4. Run a pre-import syntax check — confirm ADS can parse the file before Stage 3

**Decision Rules:**
- Pin-count mismatch after PDK swap → halt stage, log to MEMORY.md, escalate
- Port mapping ambiguity → use default ADS port ordering, log assumption to MEMORY.md
- Syntax check failure → do not proceed to Stage 3

---

### Stage 3 — Generate ADS Schematic via Placement Routine
**Scripts:** `ads_placeplan_generate.py` → `ads_placeplan_to_ads.py`

Steps:
1. Generate placement plan from `<circuit_name>_ads_import.net`
   - Assign spatial coordinates to each component following `placeplan-concepts.md`
   - Group by backbone vs. shunt based on graph from Stage 1
   - Output: `<circuit_name>_placeplan.yaml`
2. Convert placement plan to deterministic build coordinates
   - Output: `<circuit_name>_ads_buildplan.yaml`
3. Execute ADS schematic build using `ads_build_spdt.py` or equivalent builder script
   - Place components at specified coordinates
   - Draw wires per connectivity graph
   - Assign PDK cell properties to each component
4. Run post-build connectivity verification using `ads-schematic-checker` skill
   - Confirm netlist-to-schematic match
   - Flag any missing connections or extra stubs
5. Mark schematic as simulation-ready if checker passes

**Decision Rules:**
- Checker fails → do not mark as simulation-ready, log failures to MEMORY.md, report to orchestrator
- Checker passes with warnings → mark simulation-ready, include warnings in status report
- ADS API error during build → pause, save build step and last successful coordinate to MEMORY.md

---

## Escalation Triggers
| Condition | Action |
|---|---|
| >20% components without PDK match | Pause Stage 1, report to orchestrator |
| Pin-count mismatch after PDK swap | Halt Stage 2, escalate |
| ADS syntax check failure | Do not enter Stage 3, report |
| Post-build checker fails | Report, do not mark simulation-ready |
| Any unhandled exception | Pause, save state to MEMORY.md, notify via Telegram |

## Definition of Done
- `<circuit_name>_ads_buildplan.yaml` exists and is valid
- ADS schematic is built in target project path
- `ads-schematic-checker` passes (zero errors, warnings logged if any)
- Status report delivered to orchestrator
- MEMORY.md updated with outcome summary
