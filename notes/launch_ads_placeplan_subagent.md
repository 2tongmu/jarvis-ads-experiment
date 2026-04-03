# Launch ADS Placeplan Sub-Agent

## Purpose

This is the canonical launch template for sub-agents building ADS schematics from .net files.
Jarvis-EDA must use this template every time a new sub-agent is spawned for net-to-ADS work.

## Sub-Agent Name

`ads_placeplan_agent`

## Mission

Read all skills, workflows, and context files in this repository first.
Then build the ADS schematic from the input netlist, verify connectivity, and report results.

## Files The Sub-Agent Must Read (in order)

### 1. Memory (context and scope)
- `memory/project_goal.md`
- `memory/current_scope.md`
- `memory/ads_execution_context.md`

### 2. Skills (rules and geometry)
- `skills/understand_net_roles.md`
- `skills/focus_on_ads_schematic_quality.md`
- `skills/ads_python_interface.md`           ← contains confirmed ADS pin coordinates
- `skills/ads_pdk_usage.md`                  ← PDK paths, FET sizing, known constraints
- `skills/ads_component_recognition.md`
- `skills/ads_schematic_build_limitations.md` ← silent failure modes, checker is mandatory

### 3. Workflows
- `workflows/review_example_net_flow.md`
- `workflows/ads_import_to_placeplan.md`

### 4. Schema
- `schemas/placeplan_schema.md`

### 5. Design files
- `input/spdt_switch.net`            ← original circuit intent
- `input/spdt_switch_prep.net`       ← functional grouping
- `input/spdt_switch_ads_import.net` ← PDK logical source (use this for schematic)
- `input/spdt_switch_placeplan.yaml` ← placement plan (use this for layout decisions)

## Required Build Steps

1. Read all files above
2. Write a brand-new `ads_import_netlist.py` based on the skills (do not reuse old scripts)
3. Copy input netlist to `C:\Users\jarvis\AppData\Local\Temp\spdt_switch_ads_import.net`
4. Copy script to `C:\Users\jarvis\AppData\Local\Temp\ads_import_netlist.py`
5. Run via ADS Python: `"C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" C:\Users\jarvis\AppData\Local\Temp\ads_import_netlist.py`
6. Run connectivity checker: `python ~/openclaw/skills/ads-schematic-checker/scripts/check_netlist.py <generated.net>`
7. If any check FAILS: fix the wiring bug, rebuild, re-check. Loop until ALL CHECKS PASSED ✅
8. Save final working script to:
   - `~/.openclaw/workspace/ads_import_netlist.py`
   - `~/.openclaw/workspace/jarvis-ads-experiment/input/ads_import_netlist.py`

## Required Outputs

- ADS schematic in `C:\Users\jarvis\ads_projects\spdt_pdk_wrk` → `spdt_switch_lib:spdt_switch:schematic`
- `input/ads_import_netlist.py` — the working build script
- Connectivity checker output showing ALL CHECKS PASSED ✅

## Constraints

The sub-agent must not:
- read or follow any skills from `~/openclaw/skills/` — use ONLY the skills in this repo's `skills/` folder
- reuse or adapt existing scripts without reading the skills first
- report success if the connectivity checker has failures
- redesign the circuit topology
- change intended connectivity
- simulate directly with CircuitSimulator (PDK models only work in ADS GUI)

## ADS Environment

- ADS Python: `C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe`
- ADS dir: `C:\Program Files\Keysight\ADS2026_Update1`
- Workspace: `C:\Users\jarvis\ads_projects\spdt_pdk_wrk`
- PDK: `C:\Users\jarvis\ads_projects\design_kits\WIN_PP1029_DESIGN_KIT`
- WSL note: always copy scripts/netlists to Windows paths before running
