# PDK Pipeline Reference

## Overview

3-stage pipeline to go from an ideal lumped-element netlist to a real ADS schematic with PDK FETs.

```
circuit.net
    │  net_prepare.py
    ▼
circuit_prep.net        (@BLOCK / @PDK_SWAP annotated)
    │  net_parse.py
    ▼
circuit_ads_import.net  (PDK components substituted)
    │  ads_import_netlist.py
    ▼
ADS schematic + workspace
```

Scripts live at: `~/.openclaw/workspace/net_prepare.py`, `net_parse.py`, `ads_import_netlist.py`

---

## Stage 1: net_prepare.py

**Input:** raw ideal netlist (e.g. `spdt_switch.net`)
**Output:** `spdt_switch_prep.net`
**Run:** `python3 net_prepare.py spdt_switch.net`

Wraps each component group in `@BLOCK`/`@END_BLOCK` tags. No values are changed.

### @BLOCK tag format
```
; @BLOCK  name=<id>  type=<TRANSISTOR|PASSIVE_NETWORK|TLINE|PORT|SIM_CTRL>  desc="<text>"
;   @PDK_SWAP  model=WIN_PP1029_CPW  params="NOF=2 UGW=80"
;              port1=<drain_node>  port2=<source_node>  port3=<gate_node>
;              replaces=<comp1,comp2,...>  keep=<comp1,comp2,...>
;   @KEEP  components=<comp1,comp2,...>
<component lines>
; @END_BLOCK name=<id>
```

### Block types
| Type | Meaning |
|------|---------|
| `TRANSISTOR` | FET — gets @PDK_SWAP |
| `PASSIVE_NETWORK` | Bias network, pads — @KEEP |
| `TLINE` | Interconnect pi-model — @KEEP (or optional PDK swap to mlin) |
| `PORT` | S-param ports — passed through |
| `SIM_CTRL` | S_Param sweep controller — passed through |

### Gate bias blocks
Name gate bias blocks with prefix `GBIAS_<FET_name>` (e.g. `GBIAS_Q1a`).
The parser skips all `GBIAS_*` blocks by default — re-enable after FET connection verification.

---

## Stage 2: net_parse.py

**Input:** `spdt_switch_prep.net`
**Output:** `spdt_switch_ads_import.net`
**Run:** `python3 net_parse.py spdt_switch_prep.net`

Reads @BLOCK tags and:
- `TRANSISTOR` + `@PDK_SWAP`: emits PDK component line, keeps any listed in `keep=`
- `PASSIVE_NETWORK` / `TLINE` + `@KEEP`: passes components through unchanged
- `PORT` / `SIM_CTRL`: passes through unchanged
- `GBIAS_*` blocks: skipped (controlled by check in parser)

### PDK netlist syntax (WIN_PP1029_DESIGN_KIT, confirmed from ADS generate_netlist)

```
; 3-port FET (switch use):
"PP1029_CPW_PDK":Q1a  <gate> <drain> <source>  NOF=2  UGW=80 um  Temp=25  NOISE=1  S_Deb=1

; 2-port FET (source pre-grounded -- do NOT use for switch):
"PP1029_MS_PDK":MS_1  <drain> <source>  NOF=2  UGW=75.0 um  Temp=25  LayoutOption=1  NOISE=1

; TFR resistor (50 Ohm/sq, W=50um, L=R um for W=50um):
PP1029_TFR:Rg1  <n1> <n2>  W=50 um  L=300 um  T=25

; MIM capacitor:
PP1029_MIM_CAP_Custom:C1  <n1> <n2>  CornerRadius=0.0 um  PointOfCorner=1  Area=0  Perimeter=0  C=65 fF
```

### Re-enabling GBIAS blocks
In `net_parse.py`, comment out the GBIAS skip block:
```python
# if block_name.startswith('GBIAS_'):
#     ...
#     continue
```

---

## Stage 3: ads_import_netlist.py

**Input:** `spdt_switch_ads_import.net` (must be at Windows-accessible path)
**Run:** `"C:\...\python.exe" ads_import_netlist.py`

### Workspace logic
- If workspace dir exists: open it, delete cell dir on disk, reuse library
- If workspace dir missing: create fresh, inject PDK into lib.defs, copy hpeesofsim.cfg

### PDK lib.defs injection
```python
with open(WRK_DIR / "lib.defs", "a") as f:
    f.write(f'\nINCLUDE {PDK_DIR / "lib.defs"}\n')   # NO quotes around path
```

### Schematic layout rules
- All components on y=0 signal line, x increases left to right
- R/L midpoint at (cx, y): P1=(cx-0.5,y), P2=(cx+0.5,y)
- C shunt at (x,y) angle=-90: P1=(x,y), P2=(x,y-1)
- Term at (x,y) angle=-90: always add companion GROUND at (x,y-1)
- Wire endpoints MUST exactly match pin snap_points (use pin tuples, not computed floats)
- Leave 2-unit gap between blocks for visual clarity

### Series FET placement (angle=90)
```python
# Place at (drain_x+0.5, y-0.5) so Drain=(drain_x,y), Source=(drain_x+1,y), Gate=(drain_x+0.5,y-0.5)
inst = sch.add_instance(de.LCVName("WIN_PP1029_DESIGN_KIT","WIN_PP1029_CPW","symbol"),
                        (drain_x+0.5, y-0.5), name="Q1a", angle=90.0)
```

### Shunt FET placement (angle=0)
```python
# Place at (rf_x-0.5, y-0.5) so Drain=(rf_x,y), Source=(rf_x,y-1), Gate=(rf_x-0.5,y-0.5)
inst = sch.add_instance(de.LCVName("WIN_PP1029_DESIGN_KIT","WIN_PP1029_CPW","symbol"),
                        (rf_x-0.5, y-0.5), name="Q3a", angle=0.0)
```

### Simulating the result
PDK models only resolve inside ADS GUI — not via Python `CircuitSimulator`.
After running `ads_import_netlist.py`:
1. Open workspace in ADS
2. Open the schematic cell
3. Run simulation from ADS GUI directly

---

## WIN_PP1029_DESIGN_KIT Component Summary

| Component | Netlist name | Ports | Key params |
|-----------|-------------|-------|------------|
| pHEMT 3-port | `WIN_PP1029_CPW` → `PP1029_CPW_PDK` | gate, drain, source | NOF, UGW |
| pHEMT 2-port | `WIN_PP1029_MS` → `PP1029_MS_PDK` | drain, source (src grounded) | NOF, UGW |
| TFR resistor | `PP1029_TFR` | n1, n2 | W (um), L (um), T |
| MIM capacitor | `PP1029_MIM_CAP_Custom` | n1, n2 | C (fF) |
| Microstrip line | `PP1029_mlin` | n1, n2 | Layer, W (um), L (um) |

### FET sizing
- `NOF` = number of fingers
- `UGW` = unit gate width in µm
- Total gate periphery = NOF × UGW µm
- Series FETs (switch): NOF=2, UGW=80 → 160µm (adjust for IL/P1dB tradeoff)
- Shunt FETs (switch): NOF=2, UGW=50 → 100µm (Ron+Rterm ≈ 50Ω)

### PDK location
`C:\Users\jarvis\ads_projects\design_kits\WIN_PP1029_DESIGN_KIT`

### hpeesofsim.cfg
Copy from `rf_switch_design_wrk` to new workspace — contains `DESIGN_KIT_MODEL_PATH` and
`DESIGN_KIT_SIM_FILE_PATH` needed to resolve PDK models. Replace workspace path strings when copying.

---

## @PDK_SWAP Tag Examples

### Series FET (4 ideal components → 1 PDK FET)
```
; @BLOCK  name=Q1a  type=TRANSISTOR  desc="Stage 1 series pHEMT Q1a, 160um"
;   @PDK_SWAP  model=WIN_PP1029_CPW  params="NOF=2 UGW=80"
;              port1=n4  port2=n8  port3=ng_Q1a
;              replaces=Ron_Q1a,Ls_Q1a,Rvia_Q1a,Lvia_Q1a
;              keep=none
R:Ron_Q1a   n4   n5   R=2.50 Ohm
L:Ls_Q1a    n5   n6   L=50 pH
R:Rvia_Q1a  n6   n7   R=0.08 Ohm
L:Lvia_Q1a  n7   n8   L=50 pH
; @END_BLOCK name=Q1a
```

### Shunt FET (2 ideal components → 1 PDK FET, keep Rtrm)
```
; @BLOCK  name=Q3a  type=TRANSISTOR  desc="Stage 1 shunt pHEMT Q3a, 100um"
;   @PDK_SWAP  model=WIN_PP1029_CPW  params="NOF=2 UGW=50"
;              port1=n8  port2=ns2_Q3a  port3=ng_Q3a
;              replaces=Coff_Q3a,Lsh_Q3a
;              keep=Rtrm1,Lrt_Q3a
C:Coff_Q3a  n8      ns1      C=30 fF
L:Lsh_Q3a   ns1     ns2_Q3a  L=50 pH
R:Rtrm1     ns2_Q3a ns3      R=47 Ohm
L:Lrt_Q3a   ns3     0        L=25 pH
; @END_BLOCK name=Q3a
```

### Gate bias block (skipped by default, re-enable after FET verification)
```
; @BLOCK  name=GBIAS_Q1a  type=PASSIVE_NETWORK  desc="Gate bias Q1a"
;   @KEEP  components=Rg_Q1a,Cpg_Q1a,Lsg_Q1a
R:Rg_Q1a    ng_Q1a  ng2_Q1a  R=300 Ohm
C:Cpg_Q1a   ng_Q1a  ng2_Q1a  C=12 fF
L:Lsg_Q1a   ng2_Q1a 0        L=150 pH
; @END_BLOCK name=GBIAS_Q1a
```
