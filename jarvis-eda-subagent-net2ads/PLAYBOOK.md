# net2ads Playbook

Full translation workflow from research netlist to ADS schematic cell.

---

## Overview

```
[RESEARCH NETLIST]
    │  .SUBCKT + components + ports
    ▼
┌──────────────────────┐
│  Stage 1: PARSE      │  translator/parser.py + ir_builder.py
│  Topology → IR       │
└──────────────────────┘
    │  <name>_ir.yaml
    ▼
┌──────────────────────┐
│  Stage 2: MAP        │  translator/ads_mapper.py
│  IR → ADS build plan │
└──────────────────────┘
    │  <name>_buildplan.yaml
    ▼
┌──────────────────────┐
│  Stage 3: PLACE+BUILD│  translator/placement_engine.py → ADS Python API
│  Build plan → ADS    │
└──────────────────────┘
    │  ADS schematic cell + symbol
    │  <name>_placement.yaml
    │  <name>_ads_generated.net
    ▼
┌──────────────────────┐
│  POST-BUILD CHECK    │  ads-schematic-checker
│  Connectivity verify │
└──────────────────────┘
    │  Status block (stdout)
    ▼
[DONE — reusable ADS subcell ready for instantiation]
```

---

## Stage 1 — Topology Parsing + Normalization

**Script:** `translator/parser.py` → `translator/ir_builder.py`
**Input:** `<name>_research.net`
**Output:** `<name>_ir.yaml`

### 1a. Parse research netlist

`parser.py` reads the research netlist dialect:

```
; comment
.SUBCKT <cell_name> <port1> <port2> ... 0
PORT:<name>  <node>
<Type>:<InstanceName>  <node1>  <node2>  <param>=<value> ...
.ENDS <cell_name>
```

Rules:
- Skip lines starting with `;` (comment) or blank
- `.SUBCKT` / `.ENDS` set the cell name and port list
- `PORT:` lines register external ports (mapped to ADS `add_term()`)
- Component lines: split on whitespace, first token is `<Type>:<Name>`
- Parameters: `key=value` pairs anywhere after the node list
- Ground node `0` is implicit — any node named `0` connects to GND
- Emit warning for unsupported types (TLIN in Phase 1, SW in Phase 1/2)

### 1b. Build IR

`ir_builder.py` normalizes parsed data into the IR schema (`schemas/ir.yaml`):

```
classify each component:
  series   → both nodes are signal nodes (not ground)
  shunt    → one node is ground (node == "0")
  tline    → type == TLIN
  switch   → type == SW

build connectivity graph:
  nodes: all unique node names (excluding "0")
  edges: each component is an edge between its two nodes

identify backbone:
  longest chain of series components between port nodes
  (left-to-right signal flow path)

identify branches:
  shunt components (one end at ground)
  switch arms (SW elements)
```

IR is written to `<name>_ir.yaml` before Stage 2 begins (CONSTRAINT C5).

---

## Stage 2 — ADS Mapping (PDK-aware when needed)

**Script:** `translator/ads_mapper.py`
**Input:** `<name>_ir.yaml` + `schemas/ads_mapping.yaml`
**Output:** `<name>_buildplan.yaml`

### Phase 1 mapping (R, L, C)

| Research element | ADS library | ADS cell | View | Parameter mapping |
|---|---|---|---|---|
| `R` | `ads_rflib` | `R` | `symbol` | `R` → `R` |
| `L` | `ads_rflib` | `L` | `symbol` | `L` → `L` |
| `C` | `ads_rflib` | `C` | `symbol` | `C` → `C` |
| `GND` (implicit) | `ads_rflib` | `GROUND` | `symbol` | none |

### Phase 2 mapping (TLIN)

| Research element | ADS library | ADS cell | View | Parameter mapping |
|---|---|---|---|---|
| `TLIN` | `ads_rflib` | `TLIN` | `symbol` | `Z0`→`Z`, `ELength`→`E`, `Fref`→`F` |

PDK override (configurable in `ads_mapping.yaml`):
```yaml
TLIN:
  ads_lib: ads_rflib
  ads_cell: TLIN
  param_map:
    Z0: Z
    ELength: E
    Fref: F
  pdk_override:        # set to override with PDK component
    enabled: false
    ads_lib: ~
    ads_cell: ~
```

### Phase 3 mapping (SW)

| Research element | ADS mapping | Notes |
|---|---|---|
| `SW` (State=ON) | `ads_rflib:R` with R=0.1 Ohm | Series resistive ON-state model |
| `SW` (State=OFF) | `ads_rflib:C` with C=30 fF | Shunt capacitive OFF-state model |

Switch mapping is intentionally simple for Phase 3. Full FET substitution (WIN_PP1029_CPW)
is a future extension triggered by a PDK override in `ads_mapping.yaml`.

### Build plan structure

`<name>_buildplan.yaml` contains one entry per component:

```yaml
instances:
  - id: R1_SER
    ads_lib: ads_rflib
    ads_cell: R
    ads_view: symbol
    params:
      R: "50 Ohm"
    role: series
    nodes: [P1, N_OUT]
  - id: C1_SH
    ads_lib: ads_rflib
    ads_cell: C
    ads_view: symbol
    params:
      C: "2.0 pF"
    role: shunt
    nodes: [N_OUT, "0"]

ports:
  - name: P1
    number: 1
    node: P1
  - name: P2
    number: 2
    node: P2
```

---

## Stage 3 — Schematic Placement + ADS Build

**Scripts:** `translator/placement_engine.py` → ADS Python API
**Input:** `<name>_buildplan.yaml`
**Outputs:** `<name>_placement.yaml`, ADS schematic cell + symbol

### 3a. Placement engine

`placement_engine.py` computes `(x, y, angle)` for every component using the
placement rules from `schemas/placement.yaml`.

**Coordinate system:**
- Signal path runs left to right at y = 0.0
- Shunt components hang downward from signal path (y < 0)
- GND symbols at y = −1.0
- Port pins at left (port 1) and right (port 2) of signal path
- Series component spacing: 2.0 units
- Shunt component x-position: at the node where the shunt branch taps the signal path

**Component angle conventions (confirmed from `ads_build_spdt_pdk.py`):**

| Component role | angle |
|---|---|
| Series R (horizontal) | 0.0 |
| Series L (horizontal) | 0.0 |
| Series C (horizontal) | 0.0 |
| Shunt C (vertical, pin1 at signal node) | −90.0 |
| Shunt R (vertical) | −90.0 |
| GND symbol | −90.0 |
| TLIN (horizontal) | 0.0 |

**Port pin x-positions (from `net_to_ads_cell.py` confirmed coords):**
- Port 1 (left): x = 1.375
- Port 2 (right): x = (last series component right edge) + 1.0

**Series component x positions:**
- First series: x = 2.875 (if preceded by shunt branch) or 4.25 (if not)
- Spacing: 2.0 units between consecutive series components

**Critical wiring rules (confirmed 2026-04-15 from probe of manually-fixed cells):**

1. **Endpoint-only connection**: ADS connects a component pin to a wire only if a wire ENDPOINT coincides with the pin position. A wire passing THROUGH a pin without ending there leaves that pin floating.
2. **No single polyline through components**: A wire `[(p1_x, 0), (comp_x, 0), (p2_x, 0)]` will float any pin at `comp_x` that is a midpoint. Use separate segments with endpoints at each pin.
3. **No explicit shunt wire**: Never draw a wire from shunt.P1 to shunt.P2 — that shorts the component. `place_ground()` draws the wire from shunt.P2 down to the GND symbol; the shunt.P1 connection is made by the signal-path wire endpoint.
4. **Co-located pins auto-connect**: If a series component's P2 and a port pin are at the same x-coordinate, no wire is needed — ADS connects them implicitly.
5. **Component body span skipped**: Never draw a wire segment that spans from series.P1 to series.P2 — that shorts the component body.

Placement plan is written to `<name>_placement.yaml` before ADS API calls.

### 3b. ADS schematic build (confirmed API patterns)

All API calls sourced from `../jarvis-eda-learning/workspace-scripts/ADS_API_REFERENCE.md`.

```python
# Imports (✅ CONFIRMED)
import keysight.ads.de as de
from keysight.ads.de import db_uu as db
from keysight.ads.de._pde.db import TermType, DesignMode

# Open workspace (✅ CONFIRMED)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    ws = de.open_workspace(workspace_path)

# Get/create cell (✅ CONFIRMED)
lib = de.get_open_library(lib_name)
if lib.cell_exists(cell_name):
    cell = lib.cell(cell_name)
else:
    cell = de.Cell.create(lib, cell_name)

# Recreate schematic view (✅ CONFIRMED)
if cell.view_exists('schematic'):
    cell.delete_view('schematic')
sch_view = de.View.create(cell, 'schematic', 'schematic')
design = sch_view.get_design(DesignMode.WRITE)  # CRITICAL: must be WRITE

# Create port terms + visible pin markers (✅ CONFIRMED)
net  = design.find_or_add_net("port_name")
term = design.add_term(net, "port_name", TermType.INPUT_OUTPUT)
dot  = design.add_dot_for_pin((x, y))                      # ✅ CONFIRMED 2026-04-14
design.add_pin(term, dot, angle=angle, add_annot=True)     # ✅ CONFIRMED 2026-04-14
# angle=180.0 for left-side port (P1), angle=0.0 for right-side port (P2)

# Place instance (✅ CONFIRMED)
inst = design.add_instance(
    de.LCVName(ads_lib, ads_cell, 'symbol'),
    (x, y), name=instance_name, angle=angle
)
inst.parameters["R"].value = "50 Ohm"   # ✅ CONFIRMED

# Wire — one call = one segment (✅ CONFIRMED)
# Use separate calls per segment; never span across component pin positions.
# See wiring rules in Stage 3a above.
design.add_wire([(x1, y1), (x2, y2)])

# Design variables (✅ CONFIRMED)
design.cell.write_design_variables([("Rs", "1000 Ohm"), ("Cp", "1 pF")])

# Save (✅ CONFIRMED — must call; changes are not auto-saved)
design.save_design()
```

### 3c. Symbol generation (confirmed pattern)

Preferred for two-port RF cells: **dual symbol** with left/right pin split.
Use `ads_api/symbol_ops.py::create_dual_symbol(session, lib, lib_name, cell, cell_name, design, port_angles)`.

Key pattern (all confirmed 2026-04-14):
```python
# Symbol-side terms required — schematic terms cannot be used with sym_design.add_pin
sym_net  = sym_design.find_or_add_net(term_name)
sym_term = sym_design.add_term(sym_net, term_name, TermType.INPUT_OUTPUT)
dot      = sym_design.add_dot_for_pin((x, y))
sym_design.add_pin(sym_term, dot, angle=angle, add_annot=True)
# Left pins: x=0.0, angle=180; Right pins: x=symbol_width(2.0), angle=0

# Body rectangle on layer 231
from keysight.ads.de.db_uu import LayerId
sym_design.add_rectangle(LayerId(231), (bx0, -half_h), (bx1, half_h))

sym_design.save_design()   # ✅ CONFIRMED
```

Basic single-column symbol (legacy, all pins on left):
```python
db.create_symbol((lib_name, cell_name, 'symbol'))
sym_view  = cell.view('symbol')
sym_write = sym_view.get_design(DesignMode.WRITE)
for idx, term in enumerate(list(design.terms)):
    y_pos = y_start - (idx * 2.0)
    sym_write.add_pin_fig_for_term_type(term.term_type, (0.0, y_pos))  # ✅ CONFIRMED
sym_write.save_design()
```

---

## Post-Build Check

**Script:** `../jarvis-eda-learning/skills/ads-schematic-checker/scripts/check_netlist.py`
**Input:** `<name>_ads_generated.net`
**Pass criterion:** `ALL CHECKS PASSED ✅`

Do not report success to any orchestrator until the checker passes.

---

## Development Phases

### Phase 1 — Passive Topology → ADS Schematic ✅ active

**Target netlists:**
- `rc_series_shunt_research.net`
- `t_network_lcl_research.net`

**Supported elements:** R, L, C
**PDK required:** No — uses `ads_rflib` only
**Success criteria:**
- Generated schematic matches topology visually in ADS GUI
- Port terms correctly created (v_ctrl / sw_gate style naming)
- Checker passes for both netlists
- Symbol view generated with correct pin count

### Phase 2 — PDK-Aware Mapping ⏳ planned

**Target netlist:** `two_quarter_wave_lines_research.net`

**Additions:**
- `TLIN` element support in parser and IR
- PDK mapping layer in `ads_mapper.py`
- `ads_mapping.yaml` TLIN mapping block with configurable PDK override
- `ads_rflib:TLIN` as default; WIN_PP1029 CPW TLine as optional override

**Success criteria:**
- TLIN mapped to correct ADS component per `ads_mapping.yaml`
- Mapping is configurable without code changes
- Checker passes

### Phase 3 — SPDT Switch Structure ⏳ planned

**Target netlist:** `spdt_switch_research.net`

**Additions:**
- `SW` element support in parser and IR
- Switch state (`State=ON`/`State=OFF`) preserved in IR
- ON-state: resistive model (R=0.1 Ohm)
- OFF-state: capacitive model (C=30 fF) or shunt termination
- 3-port cell support in placement engine

**Success criteria:**
- 3-port schematic created with correct connectivity
- Switch structure preserved topologically
- Ready for nonlinear / PDK FET substitution in a future phase

---

## Artifact Naming Convention

All artifacts for circuit `<name>` (stem of input netlist):

| Artifact | Path |
|---|---|
| Research netlist | `examples/<name>/<name>_research.net` |
| Intermediate representation | `examples/<name>/<name>_ir.yaml` |
| ADS build plan | `examples/<name>/<name>_buildplan.yaml` |
| Placement plan | `examples/<name>/<name>_placement.yaml` |
| ADS-exported netlist | `examples/<name>/<name>_ads_generated.net` |

---

## Status Block Format

Every run ends with a structured status block on stdout:

```
================================================================
status: success | partial | failed
stage_completed: 1 | 2 | 3
outputs:
  - <artifact path>
next_action: <human-readable instruction>
errors: none | <description>
================================================================
```
