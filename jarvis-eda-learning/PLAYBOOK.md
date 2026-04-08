# PLAYBOOK.md

## Task
Convert a rfscikit-generated `.net` file into a simulation-ready ADS schematic using a specified PDK.

---

## Workflow — 3 Stages

### Stage 1 — Prepare Netlist for ADS Translation
**Script:** `net_prepare.py`

Steps:
1. Load PDK config (core file) from `pdk-configs/<PDK_NAME>_core.yaml`
   - Read `component_map` entries — these define all valid `@PDK_SWAP` targets
   - Read `ideal_passives` entries — these define `@KEEP` components (no swap)
   - Read `workspace_setup` rules — used in Stage 3
   - If config file is missing or unreadable → halt immediately (see CONSTRAINTS.md)
   - (If a cell lookup is required: load `pdk-configs/<PDK_NAME>_reference.yaml` on demand)
2. Load and validate the input `.net` file using `net_parse.py`
   - Confirm all nodes, component references, and port definitions are present
   - Flag any unrecognized component types — do not proceed if critical components are unrecognized
3. Build connectivity graph using `net_graph_utils.py`
   - Identify backbone (signal path) vs. shunt/bias groups
   - Flag floating nodes or disconnected components
4. Annotate each component with `@PDK_SWAP` or `@KEEP` tag using `component_map` from config
   - Exact match in `component_map` → annotate with `@PDK_SWAP`
   - Match in `ideal_passives` → annotate with `@KEEP`
   - No match found → flag component, log to MEMORY.md, escalate to orchestrator before continuing
5. Output: `<circuit_name>_prep.net`

**Decision Rules:**
- If >20% of components have no PDK match → pause entire stage, report to orchestrator
- If <20% have no PDK match → annotate matched ones, flag unmatched, continue with warning
- If connectivity graph has floating nodes → flag and continue; do not silently ignore

---

### Stage 2 — Generate ADS-Import-Ready Netlist
**Script:** `ads_import_netlist.py`

Steps:
1. Load `<circuit_name>_prep.net` and PDK config (core file) `pdk-configs/<PDK_NAME>_core.yaml`
2. Translate component syntax to ADS netlist format per `ads-netlist-format.md`
   - For each `@PDK_SWAP` component: look up `ads_lib`, `ads_cell`, `pin_names`,
     and `port_mapping` from the PDK config `component_map`
   - For each `@KEEP` component: pass through as-is using `ads_rflib` ideal elements
   - Map port numbering to ADS port conventions using config `port_mapping`
   - Validate pin-count consistency: compare `pin_count` in config vs. component pins
3. Output: `<circuit_name>_ads_import.net`
4. Run a pre-import syntax check — confirm ADS can parse the file before Stage 3

**Decision Rules:**
- Pin-count mismatch after PDK swap → halt stage, log to MEMORY.md, escalate
- Port mapping ambiguity → use default ADS port ordering from config, log assumption to MEMORY.md
- Syntax check failure → do not proceed to Stage 3
- Component type in `@PDK_SWAP` block not found in config `component_map` → halt, escalate

---

### Stage 3 — Generate ADS Schematic via Placement Routine
**Scripts:** `ads_placeplan_generate.py` → `ads_placeplan_to_ads.py`

Steps:
1. Load PDK config (core file) `pdk-configs/<PDK_NAME>_core.yaml`
   - Read `placement_recipes` for FET placement formulas (series / shunt orientation)
   - Read `pin_offsets` for the active FET cell — use these for wire endpoint calculations
   - Read `workspace_setup` rules — apply when creating the ADS workspace
2. Generate placement plan from `<circuit_name>_ads_import.net`
   - Assign spatial coordinates to each component following `placeplan-concepts.md`
   - Apply `placement_recipes` from config for PDK FET components
   - Group by backbone vs. shunt based on graph from Stage 1
   - Output: `<circuit_name>_placeplan.yaml`
3. Convert placement plan to deterministic build coordinates
   - Output: `<circuit_name>_ads_buildplan.yaml`
4. Execute ADS schematic build using the appropriate builder script
   - Create workspace using `ads_create_pdk_workspace.py` with config `workspace_setup` rules
   - Place PDK FET components using `ads_lib` / `ads_cell` from config `component_map`
   - Place ideal passives using `ads_lib` / `ads_cell` from config `ideal_passives`
   - Use `pin_offsets` from config (not hardcoded values) for wire endpoint coordinates
   - Draw wires per connectivity graph
5. Run post-build connectivity verification using `ads-schematic-checker` skill
   - Confirm netlist-to-schematic match
   - Flag any missing connections or extra stubs
6. Mark schematic as simulation-ready if checker passes

**Decision Rules:**
- Checker fails → do not mark as simulation-ready, log failures to MEMORY.md, report to orchestrator
- Checker passes with warnings → mark simulation-ready, include warnings in status report
- ADS API error during build → pause, save build step and last successful coordinate to MEMORY.md
- FET cell name from config not found in ADS library → halt, report (do not guess alternate names)

---

### Stage 4 — Post-Run Debrief (Every Run)
No scripts. Agent reasoning only.

1. Review this run's tool call sequence
2. Identify any step where the agent had to search, try multiple
   approaches, or reason for more than 2 turns before acting
3. For each identified step apply the Post-Run Lesson Learned Protocol
   in IMPROVEMENT.md
4. Update MEMORY.md Section 7 with each discovery
5. Update SKILLS.md if new scripts were created
6. Then yield

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

---

## Yield Format

On task completion OR pause, yield ONLY the following fixed-format block to the orchestrator. Do not yield raw file contents, script output, or full MEMORY.md. Keep each field to one line maximum.

```yaml
status: success | partial | paused | failed
stage_completed: 1 | 2 | 3 | none
outputs:
  - <filename> for each artifact produced (filenames only, no paths)
next_action: <one sentence — what the orchestrator should do next>
errors: none | <single-line brief description>
```

Examples:

```yaml
# Successful full run
status: success
stage_completed: 3
outputs:
  - spdt_switch_prep.net
  - spdt_switch_ads_import.net
  - spdt_switch_placeplan.yaml
  - spdt_switch_ads_buildplan.yaml
next_action: Open ADS project and verify schematic manually per Phase 1 checklist.
errors: none
```

```yaml
# Paused mid-run
status: paused
stage_completed: 2
outputs:
  - spdt_switch_prep.net
  - spdt_switch_ads_import.net
next_action: Resume from Stage 3 — run ads_placeplan_generate.py with existing _ads_import.net.
errors: ADS API timeout during schematic build — see MEMORY.md Section 5 for full state.
```

**Rules:**
- Never include file contents in the yield
- Never include script stdout in the yield
- Never include stack traces in the yield — those go to MEMORY.md only
- If nothing was produced, yield `outputs: []`
l
  - spdt_switch_ads_buildplan.yaml
next_action: Open ADS project and verify schematic manually per Phase 1 checklist.
errors: none
```

```yaml
# Paused mid-run
status: paused
stage_completed: 2
outputs:
  - spdt_switch_prep.net
  - spdt_switch_ads_import.net
next_action: Resume from Stage 3 — run ads_placeplan_generate.py with existing _ads_import.net.
errors: ADS API timeout during schematic build — see MEMORY.md Section 5 for full state.
```

**Rules:**
- Never include file contents in the yield
- Never include script stdout in the yield
- Never include stack traces in the yield — those go to MEMORY.md only
- If nothing was produced, yield `outputs: []`
