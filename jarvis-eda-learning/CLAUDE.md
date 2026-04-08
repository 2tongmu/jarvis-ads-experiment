# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

A skills, scripts, and agent definition repository for the `net-to-ads` sub-agent — a system that converts rfscikit-generated RF circuit netlists (`.net` files) into simulation-ready Keysight ADS schematics using a specified PDK.

The full pipeline: `.net → _prep.net → _ads_import.net → _placeplan.yaml → _ads_buildplan.yaml → ADS schematic`

## Running Scripts

ADS Python scripts must use the ADS-bundled Python interpreter, not system Python:

```bash
cd workspace-scripts
"/mnt/c/Program Files/Keysight/ADS2026_Update1/tools/python/python.exe" <script>.py
```

Run the schematic checker from the repo root:

```bash
python skills/ads-schematic-checker/scripts/check_netlist.py workspace-netlists/<circuit>_ads_generated.net
```

Pass criterion: `ALL CHECKS PASSED ✅` — zero errors. Do not report success to an orchestrator until this passes.

## Architecture

### Agent Framework

The `net-to-ads` sub-agent is defined by 7 files at the repo root:

| File | Editable by |
|---|---|
| `IDENTITY.md` | Human only |
| `SKILLS.md` | Human only |
| `PLAYBOOK.md` | Human only |
| `CONSTRAINTS.md` | Human only |
| `IMPROVEMENT.md` | Human only |
| `GRADUATION.md` | Human only |
| `MEMORY.md` | Agent + Human |

**Do not edit the first 6 files autonomously.** If a problem is found with a frozen file, log it to `MEMORY.md` Section 4 with tag `[FRAMEWORK-ISSUE]`.

### Pipeline Scripts (`workspace-scripts/`)

Ordered by pipeline stage:

| Stage | Script | Purpose |
|---|---|---|
| 1 | `net_parse.py` | Parse and validate `.net` files |
| 1 | `net_prepare.py` | Annotate with `@PDK_SWAP` tags → `_prep.net` |
| 1 | `net_graph_utils.py` | Build connectivity graph; identify backbone vs shunt/bias groups |
| 2 | `ads_import_netlist.py` | Translate `_prep.net` → ADS-import-ready `_ads_import.net` |
| 3 | `ads_placeplan_generate.py` | Generate `_placeplan.yaml` from `_ads_import.net` |
| 3 | `ads_placeplan_to_ads.py` | Convert placeplan → deterministic build coordinates → `_ads_buildplan.yaml` |
| 3 | `ads_build_spdt_pdk.py` | Build SPDT switch ADS schematic with WIN_PP1029 PDK FETs |

Utility scripts (run once to avoid multi-turn exploration):

| Script | Purpose |
|---|---|
| `ads_create_pdk_workspace.py` | Create ADS workspace with PDK loaded via lib.defs INCLUDE |
| `ads_query_pdk_cells.py` | List all cells in a PDK library (true API names, views, params) |
| `ads_probe_fet_pins.py` | Probe PDK component pin snap_point offsets at any angle |

### PDK Configs (`pdk-configs/`)
One YAML file per PDK. Loaded by the agent at runtime — not hardcoded into scripts.

| File | Purpose |
|---|---|
| `WIN_PP1029_core.yaml` | Loaded every run — component map, pin offsets, placement recipes, workspace setup |
| `WIN_PP1029_reference.yaml` | Loaded on demand only — full 43-cell enumeration for cell lookup |

When adding a new PDK, create `<PDK_NAME>_core.yaml` and `<PDK_NAME>_reference.yaml` following the same structure.

### Skills (`skills/`)

- `ads-netlist-translator/` — Full pipeline reference: netlist format, ADS Python API patterns, PDK swap pipeline
- `ads-schematic-checker/` — Post-build connectivity verification (`check_netlist.py`)
- `ads-schematic-placement/` — Placement planning concepts and rules

Each skill has a `SKILL.md` (read this before working on its domain) and a `references/` subdirectory with detailed documentation.

### Netlists (`workspace-netlists/`)

Artifact naming convention for circuit `<name>`:

| File | Stage |
|---|---|
| `<name>.net` | Raw rfscikit netlist |
| `<name>_prep.net` | After Stage 1: `@PDK_SWAP` annotated |
| `<name>_ads_import.net` | After Stage 2: ADS-import ready |
| `<name>_placeplan.yaml` | After Stage 3a: placement plan |
| `<name>_ads_buildplan.yaml` | After Stage 3b: build coordinates |
| `<name>_ads_generated.net` | ADS-exported netlist for checker |

## Critical ADS Python API Facts

These were discovered through failure — violating them silently breaks the schematic.

**ADS Python interpreter:** Scripts must use the ADS-bundled Python, not system Python:
`C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe`
Verify this path exists on the target machine before running any script.

**Cell name mismatch:** The ADS Python API cell name for WIN_PP1029_DESIGN_KIT is `WIN_PP1029_CPW` — not `PP1029_CPW_PDK` (which is only the TransistorModel parameter / netlist export identifier). Using the wrong name causes `RuntimeError: Could not find cell`.

**Pin probing API:** `InstTerm.position` does not exist in ADS 2026 Update 1. Use:
```python
list(inst.get_inst_term_iter())[n].inst_pins[0].snap_point
```

**WIN_PP1029_CPW verified pin offsets (relative to instance origin):**

| Angle | Pin 1 (gate) | Pin 2 (drain) | Pin 3 (source) |
|---|---|---|---|
| 0° | (0.0, 0.0) | (+0.5, +0.5) | (+0.5, -0.5) |
| 90° | (0.0, 0.0) | (-0.5, +0.5) | (+0.5, +0.5) |

**Series FET** (angle=90): place at `(drain_x+0.5, y-0.5)` → drain=(drain_x, y), source=(drain_x+1, y)

**Shunt FET** (angle=0): place at `(rf_x-0.5, y-0.5)` → drain=(rf_x, y), source=(rf_x, y-1)

**WIN_PP1029_MS** has source pre-grounded — do NOT use for switch FETs.

**Wire endpoints must EXACTLY match pin snap_points** — ADS places components silently even if wires miss pins.

**lib.defs INCLUDE path must NOT be quoted:** `INCLUDE C:\path\lib.defs`

**PDK schematics simulate from ADS GUI only** — `PP1029_CPW_PDK` models do not resolve via standalone `hpeesofsim`.

**Workspace recreate pattern:** Delete cell directory on disk (`shutil.rmtree`) before recreating; check `workspace.libraries` before `add_library` to avoid duplicates.

## Improvement Rules

When improving workspace scripts autonomously (the only editable execution-layer artifacts):

1. Add inline comment: `# IMPROVED [date]: <one line reason>`
2. Do not delete existing logic — comment out first, confirm replacement works, then remove
3. After creating a new script, add it to `SKILLS.md` and log it to `MEMORY.md` Section 1 as `[SCRIPT-ADDED]`
4. New scripts go in `workspace-scripts/` with a standard header comment block (see `IMPROVEMENT.md`)

Any `[IMPROVEMENT-CANDIDATE]` identified for a frozen file: log only to `MEMORY.md` Section 4, do not edit the file.

## Development Phase

Current phase: **Phase 1 — Schematic Generation** (active). Phase 1 stop criterion has been met for `spdt_switch`. Awaiting human sign-off in `GRADUATION.md` to advance to Phase 2 (simulation).

Phase advancement is controlled exclusively by a human editing `GRADUATION.md`.
