# SKILLS.md

## Purpose
This file lists all tools, scripts, and skills the `net-to-ads` agent is authorized to use.
Additions require human approval (per IMPROVEMENT.md — this file is frozen).

---

## Stage Scripts (PLAYBOOK.md workflow)

| Script | Stage | Purpose |
|---|---|---|
| `net_parse.py` | Stage 1 | Parse and validate input `.net` files |
| `net_prepare.py` | Stage 1 | Annotate netlist with `@PDK_SWAP` tags → `_prep.net` |
| `net_graph_utils.py` | Stage 1 | Build connectivity graph; identify backbone vs shunt/bias groups |
| `ads_import_netlist.py` | Stage 2 | Translate `_prep.net` → ADS-import-ready `_ads_import.net` |
| `ads_placeplan_generate.py` | Stage 3 | Generate schematic placement plan → `_placeplan.yaml` |
| `ads_placeplan_to_ads.py` | Stage 3 | Convert placeplan → deterministic build coordinates → `_ads_buildplan.yaml` |
| `ads_build_spdt_pdk.py` | Stage 3 | Build SPDT switch ADS schematic with WIN_PP1029 PDK FETs |

---

## Utility Scripts (ADS Setup & Discovery)

These were created during Run 1 (2026-04-06) via the Post-Run Lesson Learned Protocol.
Each replaces multi-turn manual reasoning that would otherwise repeat on every run.

| Script | Purpose | Replaces |
|---|---|---|
| `ads_create_pdk_workspace.py` | Create + open ADS workspace with PDK via lib.defs INCLUDE | ~5 turns: workspace create sequence, lib.defs INCLUDE format, open timing |
| `ads_query_pdk_cells.py` | List all cells in a PDK library (true API names, views, params) | ~6 turns: directory decoding, AEL inspection, cell enumeration to find correct cell name |
| `ads_probe_fet_pins.py` | Probe PDK component pin snap_point offsets at any angle | ~4 turns: InstTerm.position failure, dir() inspection, snap_point discovery |

---

## Skill Modules (from `skills/` directory)

| Skill | Location | Purpose |
|---|---|---|
| `ads-netlist-translator` | `skills/ads-netlist-translator/` | Translate Python RF circuits → ADS netlists (pipeline reference) |
| `ads-schematic-checker` | `skills/ads-schematic-checker/` | Verify ADS schematic connectivity post-build (check_netlist.py) |
| `ads-schematic-placement` | `skills/ads-schematic-placement/` | Placement planning concepts and rules |

### Schematic Checker
Run from the `jarvis-eda-learning/` directory:
```
python3 skills/ads-schematic-checker/scripts/check_netlist.py \
    workspace-netlists/<circuit>_ads_generated.net
```
Pass criteria: `ALL CHECKS PASSED ✅` with zero errors.

---

## ADS Python Executable

```
/mnt/c/Program Files/Keysight/ADS2026_Update1/tools/python/python.exe
```

Run scripts from workspace-scripts/:
```
cd workspace-scripts
"/mnt/c/Program Files/Keysight/ADS2026_Update1/tools/python/python.exe" <script>.py
```

---

## PDK Config Files

PDK-specific knowledge (cell names, pin offsets, component mappings, workspace setup rules)
lives in `pdk-configs/`, NOT in agent memory or hardcoded in scripts.

| Config File | PDK | Status |
|---|---|---|
| `pdk-configs/WIN_PP1029.yaml` | WIN Semi PP1029 GaAs pHEMT | ✅ validated Run 1 (2026-04-06) |

**At invocation, the orchestrator must provide the PDK config file path.**
The agent loads this file at Stage 1 and reads all cell names, pin offsets, and
placement recipes from it through Stages 1–3.

To add a new PDK: create a new `.yaml` in `pdk-configs/` following the WIN_PP1029.yaml
schema. Do not put PDK knowledge in MEMORY.md, SKILLS.md, or builder scripts.
