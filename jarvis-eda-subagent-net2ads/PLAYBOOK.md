# net2ads Playbook

Full translation workflow from research netlist to ADS schematic cell.
Last updated: 2026-04-28 (Phase 3 complete)

---

## Pipeline Overview

```
[RESEARCH NETLIST]
    │  .SUBCKT + components + ports
    ▼
┌──────────────────────────┐
│  Pre-Stage 1             │  Stale YAML detection
│  Clean stale artifacts   │  net2ads.py _clean_stale_yamls()
└──────────────────────────┘
    ▼
┌──────────────────────────┐
│  Stage 1: PARSE          │  translator/parser.py
│  Netlist → ParsedNetlist │
└──────────────────────────┘
    ▼
┌──────────────────────────┐
│  Stage 2: IR BUILD       │  translator/ir_builder.py
│  ParsedNetlist → IR      │  → <name>_ir.yaml
└──────────────────────────┘
    ▼
┌──────────────────────────┐
│  Stage 3: MAP            │  translator/ads_mapper.py
│  IR → ADS build plan     │  → <name>_buildplan.yaml
└──────────────────────────┘
    ▼
┌──────────────────────────┐
│  Stage 4: PLACEMENT      │  translator/placement_engine.py
│  Build plan → (x,y,angle)│  → <name>_placement.yaml
├──────────────────────────┤
│  Stage 4b: CHECK         │  translator/placement_checker.py
│  Pin connectivity verify │  uses ads_pdk/pin_offsets.yaml
└──────────────────────────┘
    ▼
┌──────────────────────────┐
│  Stage 5: ADS BUILD      │  ads_api/schematic_ops.py
│  Placement → ADS cell    │  ads_api/symbol_ops.py
└──────────────────────────┘
    │  ADS schematic cell + symbol + itemdef.ael
    ▼
[DONE — reusable ADS subcell ready for instantiation]
```

---

## Entry Point

```
python net2ads.py <netlist.net> --workspace <path> [--lib <lib>] [--pdk <pdk>] [--sw-map <yaml>] [--dry-run]
```

| Argument | Default | Notes |
|---|---|---|
| `<netlist.net>` | (required) | Path to research netlist |
| `--workspace` | (required unless --dry-run) | ADS workspace directory |
| `--lib` | `net2ads_lib` | Target ADS library name |
| `--pdk` | None | PDK name for TLIN → microstrip substitution (Phase 2+) |
| `--sw-map` | None | SW annotation YAML from `fet_bias_preprocessor.py` (Phase 3) |
| `--dry-run` | False | Runs Stages 1–4b; writes YAMLs; skips ADS API |

**Must use ADS-bundled Python**, not system Python:
```
C:\Program Files\Keysight\ADS2026_Update1.2\tools\python\python.exe net2ads.py ...
```

---

## Stage 1 — Topology Parsing

**Script:** `translator/parser.py`
**Output:** `ParsedNetlist` (in-memory)

Reads the research netlist dialect:
```
; comment
.SUBCKT <cell_name> <port1> <port2> ... 0
PORT:<name>  <node>
<Type>:<InstanceName>  <node1>  <node2>  <param>=<value> ...
.VAR <name> <value_with_unit>
.ENDS <cell_name>
```

Rules:
- Skip `;` comment lines and blank lines
- `.SUBCKT` / `.ENDS` → cell name and subckt port list
- `PORT:` lines → external schematic ports (mapped to ADS `add_term()`)
- Component lines: `<Type>:<Name>  node1  node2  key=value ...`
- `.VAR` lines → design variables (e.g. `Rs`, `Cp`) for parameterized cells
- Ground node `0` is implicit
- Supported types: R, L, C, TLIN, SW, V (voltage source)

---

## Stage 2 — IR Build

**Script:** `translator/ir_builder.py`
**Output:** `<name>_ir.yaml`

Normalizes parsed data into IR schema (`schemas/ir.yaml`):

- Classify each component: `series` (both nodes signal), `shunt` (one node ground),
  `tline`, `switch`, `vsource`
- Build connectivity graph; identify backbone and shunt branches
- Determine `phase_required` (1=R/L/C, 2=TLIN, 3=SW/FET/V_DC)
- Carry `.VAR` declarations as `design_variables`

---

## Stage 3 — ADS Mapping

**Script:** `translator/ads_mapper.py`
**Config:** `schemas/ads_mapping.yaml`
**Output:** `<name>_buildplan.yaml`

### Component mapping table

| Research type | ADS lib | ADS cell | Phase | Notes |
|---|---|---|---|---|
| R | ads_rflib | R | 1 | param: R |
| L | ads_rflib | L | 1 | param: L |
| C | ads_rflib | C | 1 | param: C |
| GND (shunt companion) | ads_rflib | GROUND | 1 | auto-added for shunt + vsource |
| TLIN (ideal) | ads_rflib | TLIN | 2 | Z0→Z, ELength→E, Fref→F |
| TLIN (PDK) | WIN_PP1029_DESIGN_KIT | PP1029_mlin | 2 | W/L from tline_calc; requires --pdk |
| V (vsource) | ads_sources | V_DC | 3 | param: Vdc; GND companion auto-added |
| SW → series FET | WIN_PP1029_DESIGN_KIT | WIN_PP1029_CPW | 3 | requires --sw-map |
| SW → fetbias subcell | net2ads_lib | fetbias_sw_gate | 3 | 1-port (GATE only); V_DC internal |

### GND companion rule
Shunt and vsource components that connect to node `'0'` automatically receive a
`GND_{id}` companion instance (role=gnd, ads_rflib:GROUND) in the build plan.
The placement engine positions it 1 unit below the companion at `(x, y-1)`.

---

## Stage 4 — Placement

**Script:** `translator/placement_engine.py`
**Output:** `<name>_placement.yaml`

Computes `(x, y, angle)` for every component and generates wire segments.

### Coordinate system

| Element | y position | Notes |
|---|---|---|
| Common section | y = 0.0 | P1 → N_COM |
| Path A (SPDT) | y = +2.0 | N_COM → P2 |
| Path B (SPDT) | y = −2.0 | N_COM → P3 |
| GND companions | y = companion_y − 1.0 | 1 unit below shunt/vsource |
| Port 1 (left) | x = 1.375 | |
| Series start | x = 2.875 | FIRST_SHUNT_X |
| Series spacing | 2.0 units | COMPONENT_SPACING |

### Angle conventions (confirmed from ADS probe)

| Role | angle | Pin layout |
|---|---|---|
| series R/L/C, tline | 0.0 | P1 left, P2 right |
| shunt R/L/C | −90.0 | P1 at origin (signal rail), P2 1 unit below |
| GND symbol | −90.0 | P1 at origin |
| vsource (V_DC) | −90.0 | P+ at origin (signal rail), P− 1 unit below → GND companion |
| series FET (WIN_PP1029_CPW) | 90.0 | gate at origin, drain=(−0.5,+0.5), source=(+0.5,+0.5) |
| shunt FET (WIN_PP1029_CPW) | 0.0 | gate at origin, drain=(+0.5,+0.5), source=(+0.5,−0.5) |
| fetbias_sw_gate | 0.0 | GATE pin at (origin.x+2.0, origin.y) — right-side pin |

### SPDT placement formulas (Phase 3)

```
branch_x = P2 of last common section component (N_COM tap on y=0 rail)

Series FET:   origin = (branch_x + 0.5, path_y − 0.5)
              drain  = (branch_x, path_y)       ← N_COM
              source = (branch_x + 1.0, path_y) ← N_A1 / N_B1

Shunt FET:    origin = (tap_x − 0.5, path_y − 0.5)
              drain  = (tap_x, path_y)           ← signal tap (N_A3 / N_B3)
              source = (tap_x, path_y − 1.0)     ← to RTERM (N_AST / N_BST)

fetbias:      origin = (FET_gate_x − 2.0, gate_y)
              GATE pin at (origin.x + 2.0, origin.y) = FET gate ✓

RTERM:        placed at shunt FET source = (tap_x, path_y − 1.0)
GND_RTERM:    1 unit below RTERM = (tap_x, path_y − 2.0)
```

### Wire generation

Wires are auto-derived from pin position sets per net. One horizontal or vertical
segment per net per y-level spans min_x to max_x. Co-located pins need no wire.

Critical rule: wire ENDPOINTS must coincide with pin positions. A wire passing through
a pin midpoint does not connect it. The checker (Stage 4b) enforces this.

### Port angle conventions

| Port | angle | Side in symbol |
|---|---|---|
| P1 (RF input) | 180.0 | Left |
| P2, P3 (RF outputs) | 0.0 | Right |
| VCTRL_* (bias control) | 180.0 | Left |
| GATE (fetbias subcell output) | 0.0 | Right — connects to FET gate to the right |

GATE must be 0.0 (right-side pin) so that the dual symbol places it at x=symbol_width=2.0.
When the fetbias instance is at (gate_x−2.0, gate_y), GATE is at (gate_x, gate_y) = FET gate.

---

## Stage 4b — Connectivity Check

**Script:** `translator/placement_checker.py`
**Config:** `ads_pdk/pin_offsets.yaml`

Verifies every non-ground pin is reachable from at least one other pin on the same net
via co-location or wire (endpoint or mid-segment tap). Runs automatically after Stage 4.

A pin is connected if:
1. Another pin on the same net sits at the same (x, y) — **co-location**
2. The pin position is a wire endpoint — **wire connection**
3. The pin position lies within a wire segment spanning another net pin — **mid-tap**

Pin positions are computed from `ads_pdk/pin_offsets.yaml`. Components not in the registry
fall back to role-based heuristics and emit `[CHECK-WARN]`.

Output: `[CHECK]` errors appear in the pipeline stdout and in the status block `errors` field.
A `[CHECK]` error does NOT halt the pipeline — Stage 5 still runs — but the status is `partial`.

### Pin offset registry (`ads_pdk/pin_offsets.yaml`)

Stores `(dx, dy)` offsets from placed origin per component and angle:

```yaml
ads_rflib:R:
  offsets_by_angle:
    "0.0":   [[0.0, 0.0], [1.0, 0.0]]   # P1 left, P2 right
    "-90.0": [[0.0, 0.0], [0.0, -1.0]]  # P1 top, P2 bottom

net2ads_lib:fetbias_sw_gate:
  offsets_by_angle:
    "0.0": [[2.0, 0.0]]   # GATE at right side (x = symbol_width = 2.0)
```

To re-probe all offsets against a live ADS installation:
```
python ads_api/probe_pin_offsets.py --workspace <path> [--cells ads_rflib:R ads_sources:V_DC]
```
Entries marked `source: confirmed` are not overwritten by the probe script.

---

## Stage 5 — ADS Build

**Scripts:** `ads_api/schematic_ops.py`, `ads_api/symbol_ops.py`, `ads_api/cell_ops.py`

### Schematic build

All API calls sourced from `../jarvis-eda-learning/workspace-scripts/ADS_API_REFERENCE.md`.

```python
import keysight.ads.de as de
from keysight.ads.de import db_uu as db
from keysight.ads.de._pde.db import TermType, DesignMode

ws     = de.open_workspace(workspace_path)                          # ✅ CONFIRMED
lib    = de.get_open_library(lib_name)                              # ✅ CONFIRMED
cell   = de.Cell.create(lib, cell_name)                             # ✅ CONFIRMED
sch_view = de.View.create(cell, "schematic", "schematic")           # ✅ CONFIRMED
design = sch_view.get_design(DesignMode.WRITE)                      # WRITE required

# Port terms + visible pin markers
net  = design.find_or_add_net("P1")                                 # ✅ CONFIRMED
term = design.add_term(net, "P1", TermType.INPUT_OUTPUT)            # ✅ CONFIRMED
dot  = design.add_dot_for_pin((x, y))                               # ✅ CONFIRMED 2026-04-14
design.add_pin(term, dot, angle=angle, add_annot=True)              # ✅ CONFIRMED 2026-04-14
# angle=180 → left-facing (P1, VCTRL); angle=0 → right-facing (P2, P3, GATE)

# Place instance
inst = design.add_instance(de.LCVName(lib, cell, "symbol"),
                            (x, y), name=id, angle=angle)           # ✅ CONFIRMED
inst.parameters["R"].value = "50 Ohm"                               # ✅ CONFIRMED

# Wire
design.add_wire([(x1, y1), (x2, y2)])                               # ✅ CONFIRMED

# Design variables
design.cell.write_design_variables([("Rs", "1000 Ohm")])            # ✅ CONFIRMED

# CRITICAL: commit transaction before save (finalizes OpenAccess metadata)
transaction.commit()                                                 # ✅ CONFIRMED 2026-04-24
design.save_design()                                                 # ✅ CONFIRMED
```

### Symbol generation

`ads_api/symbol_ops.py::create_dual_symbol()` — splits ports left/right by `port_angles`:

```
Left  pins (angle=180): x=0.0,           body from bx0=0.5 to bx1=1.5
Right pins (angle=0):   x=symbol_width=2.0
Body: layer 231 (outer rect + inner rect + stubs + labels)
```

Design variables are exposed as user parameters via `ads_api/cell_ops.py::write_itemdef_ael()`,
which writes `<workspace>/<lib>/<cell>/itemdef.ael`.

---

## Phase 3 — SPDT Switch with PDK FETs

### Pre-processor

**Script:** `translator/fet_bias_preprocessor.py`

Run this BEFORE net2ads to classify SW elements and generate the fetbias subcell netlist:

```
python translator/fet_bias_preprocessor.py examples/spdt_switch/spdt_switch_research.net
```

Outputs:
- `examples/spdt_switch/spdt_switch_sw_map.yaml` — SW→FET annotation per instance
- `examples/spdt_switch/fetbias_sw_gate/fetbias_sw_gate_research.net` — bias subcell netlist

### fetbias_sw_gate topology

```
                  [RS] ──── GATE (port, right-side)
                  /
         N_VDD ──┤
                  \
                  [CP]  [VGATE/V_DC]
                   |        |
                  GND      GND
```

- V_DC source (`VGATE`) is internal — no external VCTRL port
- Gate voltage is a design variable (`Vgate`, default 0.0 V)
- `Rs` and `Cp` are design variables, overridden per SPDT instance via `inst.parameters[].value`

### Phase 3 run sequence

```
Step 1 — Build fetbias subcell:
  python net2ads.py examples\spdt_switch\fetbias_sw_gate\fetbias_sw_gate_research.net
          --workspace <ws> --lib net2ads_lib

Step 2 — Build SPDT top cell:
  python net2ads.py examples\spdt_switch\spdt_switch_research.net
          --workspace <ws> --lib net2ads_lib
          --sw-map examples\spdt_switch\spdt_switch_sw_map.yaml
          --pdk WIN_PP1029_DESIGN_KIT
```

**fetbias must be built first** — the SPDT step instantiates it from `net2ads_lib`.

### Phase 3 open items

| Item | Status | Notes |
|---|---|---|
| J3-01: subcell parameter override (`inst.parameters["Rs"]`) | ⚠️ Partial | Pipeline sets it; ADS confirms write, but simulation fallback is cell defaults |
| J3-02: V_DC LCV and param name | ✅ Resolved | `ads_sources:V_DC:symbol`, param=`Vdc` |
| J3-03: Replace VCTRL with internal V_DC | ✅ Complete | `fetbias_sw_gate` has internal V_DC |
| J3-04: WIN_PP1029_CPW placement on PDK workspace | ✅ Complete | Probed 2026-04-06, all positions confirmed |

---

## Development Phases

### Phase 1 — Passive Topology → ADS Schematic ✅ Complete

**Supported elements:** R, L, C
**PDK required:** No (ads_rflib only)
**Example:** `examples/rc_series_shunt/`, `examples/t_network_lcl/`

### Phase 2 — PDK-Aware TLIN Mapping ✅ Complete (signed off 2026-04-26)

**Supported elements:** TLIN → PP1029_mlin (W/L from tline_calc)
**PDK required:** `WIN_PP1029_DESIGN_KIT` (use `--pdk WIN_PP1029_DESIGN_KIT`)
**Example:** `examples/two_quarter_wave_lines/`
**Sign-off:** `C:\Github_folders\jarvis-ads-experiment\PHASE2_SIGN_OFF.md`

### Phase 3 — SPDT Switch with PDK FETs + Gate Bias ✅ Complete (signed off 2026-04-28)

**Supported elements:** SW → WIN_PP1029_CPW + fetbias_sw_gate subcell
**PDK required:** `WIN_PP1029_DESIGN_KIT`
**Example:** `examples/spdt_switch/`

**Success criteria — all met:**
- [x] `fetbias_sw_gate`: internal V_DC, Rs/Cp as design variables, GATE right-side pin
- [x] `spdt_switch`: 3-port (P1/P2/P3), PDK FETs, 4× fetbias instances
- [x] Stage 4b connectivity checker: passes clean for both cells
- [x] Visual inspection in ADS GUI: all components connected correctly
- [x] Pin offset registry (`ads_pdk/pin_offsets.yaml`): all pipeline cells registered

---

## Artifact Naming Convention

All artifacts for circuit `<name>` (stem of input netlist):

| Artifact | Path |
|---|---|
| Research netlist | `examples/<name>/<name>_research.net` |
| Intermediate representation | `examples/<name>/<name>_ir.yaml` |
| ADS build plan | `examples/<name>/<name>_buildplan.yaml` |
| Placement plan | `examples/<name>/<name>_placement.yaml` |
| SW annotation | `examples/<name>/<name>_sw_map.yaml` |

---

## Status Block Format

Every run ends with a structured status block on stdout:

```
==================================================================
status: success | partial | failed
stage_completed: 1 | 2 | 3
outputs:
  - <artifact path>
  - <lib>:<cell>:schematic
  - <lib>:<cell>:symbol
next_action: <human-readable instruction>
errors: none | <description>
==================================================================
```

`partial` means all stages ran but non-fatal warnings or `[CHECK]` errors were found.
`failed` means an exception halted the pipeline at the indicated stage.
