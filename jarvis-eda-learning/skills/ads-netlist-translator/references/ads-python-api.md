# ADS Python API Reference

ADS 2026 bundled Python: `C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe`
Packages path: `...\tools\python\packages` — add to `sys.path` before importing.

## Table of Contents
1. [Setup](#setup)
2. [Workspace & Library](#workspace--library)
3. [Creating Schematics](#creating-schematics)
4. [Adding Instances](#adding-instances)
5. [Setting Parameters](#setting-parameters)
6. [Wiring](#wiring)
7. [Pins & Ports](#pins--ports)
8. [Symbol Generation](#symbol-generation)
9. [Netlisting & Simulation](#netlisting--simulation)
10. [Reading Results](#reading-results)
11. [Common Pitfalls](#common-pitfalls)

---

## Setup

```python
import sys, os
from pathlib import Path

ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

import keysight.ads.de as de
from keysight.ads.de import db_uu as db
```

The vtb.defs / SystemVue warning printed on every workspace open is benign — suppress with:
```python
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    workspace = de.open_workspace(str(WRK_DIR))
```

---

## Workspace & Library

```python
import shutil

# Create (delete existing first)
WRK_DIR = Path(r"C:\Users\jarvis\ads_projects\my_wrk")
shutil.rmtree(str(WRK_DIR), ignore_errors=True)

if de.workspace_is_open():
    de.close_workspace()

workspace = de.create_workspace(str(WRK_DIR))
workspace.open()

# Create and register library
LIB_NAME = "my_lib"
LIB_DIR  = WRK_DIR / LIB_NAME
de.create_new_library(LIB_NAME, str(LIB_DIR))
workspace.add_library(LIB_NAME, str(LIB_DIR), de.LibraryMode.SHARED)

# Open existing workspace
workspace = de.open_workspace(str(WRK_DIR))

# Close
workspace.close()
```

---

## Creating Schematics

```python
# Create new schematic (cell must not already exist)
sch = db.create_schematic(f"{LIB_NAME}:CellName:schematic")

# Open existing schematic (read-only unless created in same session)
sch = db.open_design(f"{LIB_NAME}:CellName:schematic")

# ALL edits must be inside a Transaction
tx = de.db.Transaction(sch, "description")
# ... make edits ...
tx.commit()
sch.save_design()
```

**Important:** `db.open_design()` returns a read-only view if the design was saved in a previous session. To edit an existing design, delete and recreate the workspace, or use `clear_design()` inside a new transaction on a freshly created schematic.

---

## Adding Instances

```python
# Syntax: add_instance(LCVName or CellviewRef, (x, y), name="...", angle=0.0)

# Standard ADS library components
R_inst = sch.add_instance(de.LCVName("ads_rflib", "R",      "symbol"), (x, y), name="R1")
L_inst = sch.add_instance(de.LCVName("ads_rflib", "L",      "symbol"), (x, y), name="L1")
C_inst = sch.add_instance(de.LCVName("ads_rflib", "C",      "symbol"), (x, y), name="C1")
gnd    = sch.add_instance(de.LCVName("ads_rflib", "GROUND", "symbol"), (x, y), name="GND1", angle=-90.0)

# Simulation components
term   = sch.add_instance(de.LCVName("ads_simulation", "Term",    "symbol"), (x, y), name="Term1", angle=-90.0)
sp     = sch.add_instance(de.LCVName("ads_simulation", "S_Param", "symbol"), (x, y), name="SP1")
ac     = sch.add_instance(de.LCVName("ads_simulation", "AC",      "symbol"), (x, y), name="AC1")

# Subcircuit from own library
sub = sch.add_instance(de.LCVName(LIB_NAME, "MyCell", "symbol"), (x, y), name="X1")
# or via CellviewRef
cvr = de.CellviewRef(LIB_NAME, "MyCell", "symbol")
sub = sch.add_instance(cvr, (x, y), name="X1")

# Angle conventions
# 0.0   = default orientation
# -90.0 = rotated 90° clockwise (standard for GROUND, Term)
# 90.0  = rotated 90° counter-clockwise
```

---

## Setting Parameters

```python
# After add_instance, set params via .parameters dict
inst.parameters["R"].value = "50 Ohm"
inst.parameters["L"].value = "7.958 nH"
inst.parameters["C"].value = "6.366 pF"

# Term parameters
term.parameters["Num"].value = "1"
term.parameters["Z"].value   = "50 Ohm"

# S_Param parameters
sp.parameters["Start"].value = "2 GHz"
sp.parameters["Stop"].value  = "18 GHz"
sp.parameters["Step"].value  = "100 MHz"

# VAR instance (equation block)
var = sch.add_var_instance(de.LCVName("ads_datacmps","VAR","symbol"), (x,y), name="VAR1")
var.vars["Fc"] = "1 GHz"
var.vars["Z0"] = "50"
```

---

## Wiring

```python
# add_wire takes a list of (x, y) waypoints
# Wire snaps to the nearest component pin at each endpoint

sch.add_wire([(0.0, 0.0), (1.0, 0.0)])          # horizontal segment
sch.add_wire([(1.0, 0.0), (1.0, -1.0)])          # vertical segment
sch.add_wire([(0.0, 0.0), (1.0, 0.0), (1.0, -1.0)])  # L-shaped wire
```

**Pin coordinate rule:** Wire endpoints must land exactly on a component pin snap_point.
Use `pin.snap_point` to read positions programmatically.

**Confirmed pin positions** (verified against ADS 2026):

| Component | Orientation | P1 snap_point | P2 snap_point |
|---|---|---|---|
| `ads_rflib:L` | angle=0 (R0) | (0, 0) left | (1, 0) right |
| `ads_rflib:C` | angle=-90 (R270) | (0, 0) top | (0, -1) bottom/GND |
| `ads_rflib:R` | angle=0 (R0) | (0, 0) left | (1, 0) right |
| `ads_simulation:Term` | angle=-90 (R270) | (0, 0) RF pin | (0, -1) GND pin |
| `ads_rflib:GROUND` | angle=-90 (R270) | (0, 0) | -- |

**Verified flat LPF layout** (all on y=0):
```
Term1@(0,0) --wire(0->1.5)--> L1@(1.5,0) --wire(2.5->3.0)--> C1@(3.0,0) --wire(3.0->4.0)--> L2@(4.0,0) --wire(5.0->6.0)--> Term2@(6.0,0)
                                                                   |
                                                              GND@(3.0,-1.0)
```
Nets: N1=Term1<->L1.P1, N5=L1.P2<->C1.P1<->L2.P1, N8=L2.P2<->Term2  -- S-params match Python exactly.

- Auto-generated symbols via `SymbolGenerator` -- check `sym.bbox`; pins at x=0 and x=bbox.width

---

## Pins & Ports

```python
# Add a terminal/pin to a schematic (for subcircuits)
layer = db.LayerId(231)  # ads_device:drawing layer

net  = sch.find_or_add_net("P1")
term = sch.add_term(net, "P1", db.TermType.INPUT)
dot  = sch.add_dot(layer, (0.0, 0.0))
pin  = sch.add_pin(term, dot, angle=180.0)  # angle = direction signal enters

# TermType options: INPUT, OUTPUT, INPUT_OUTPUT
```

---

## Symbol Generation

Auto-generate a symbol from a schematic (required to instantiate as subcircuit):

```python
from keysight.ads.de.experimental import generate_symbol as gs

sym = db.create_symbol(f"{LIB_NAME}:MyCell:symbol")
gen = gs.SymbolGenerator(sym, sch_source, 0.25, 0.25)
gen.should_replace = True
gen.generate_symbol()
sym.save_design()

# Check symbol bbox to determine pin positions
print(sym.bbox)  # e.g. BoxF (0, -0.25), (1, 0.25)
# P1 pin at x=0, P2 pin at x=1 (for a 2-port subcircuit placed at origin)
```

---

## Netlisting & Simulation

```python
# Generate ADS netlist text from schematic
netlist_text = sch.generate_netlist()

# Run via CircuitSimulator (preferred)
from keysight.edatoolbox import ads as edatoolbox_ads
OUTPUT_DIR = WRK_DIR / "sim_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

simulator = edatoolbox_ads.CircuitSimulator()
simulator.run_netlist(netlist_text, output_dir=str(OUTPUT_DIR))

# Fallback: run hpeesofsim.exe directly with ADS-generated netlist
import subprocess
net_file = OUTPUT_DIR / "design.net"
net_file.write_text(netlist_text, encoding="utf-8")

HPEESIM = ADS_DIR / "bin" / "hpeesofsim.exe"
env = dict(os.environ)
env["PATH"] = str(ADS_DIR / "bin") + os.pathsep + env.get("PATH", "")
env["HPEESOF_DIR"] = str(ADS_DIR)

res = subprocess.run([str(HPEESIM), str(net_file)],
                     capture_output=True, text=True,
                     env=env, cwd=str(OUTPUT_DIR), timeout=120)
```

**Critical:** hpeesofsim crashes on WSL paths (`\\wsl.localhost\...`).
Always save netlist to a Windows-native path (under `C:\Users\...`).

---

## Reading Results

```python
import numpy as np
import keysight.ads.dataset as dataset

ds_files = sorted(OUTPUT_DIR.glob("*.ds"))
ds = dataset.open(ds_files[0])

# List available measurements
print(list(ds.keys()))   # e.g. ['SP1.SP']

# Get S-parameter dataframe
# Index = frequency in Hz; columns = S[1,1], S[2,1], S[1,2], S[2,2], PortZ[1], ...
df = ds["SP1.SP"].to_dataframe()
freq_hz = df.index.values
freqs_GHz = freq_hz / 1e9

S21 = df["S[2,1]"].values          # complex
S11 = df["S[1,1]"].values          # complex

IL_dB  = -20 * np.log10(np.abs(S21))
RL_dB  =  20 * np.log10(np.abs(S11))  # note: RL is positive when reported as magnitude
```

---

## Common Pitfalls

| Issue | Cause | Fix |
|---|---|---|
| `RuntimeError: Attempt to save a read-only design` | `open_design()` returns read-only | Delete + recreate workspace; use `create_schematic()` |
| `S[2,1] = 0+0j` everywhere | Wire endpoint misses pin by even 0.001 units | Check symbol bbox; match wire coords exactly to pin positions |
| hpeesofsim exit 3221225781 (0xC0000005) | Given a WSL `\\wsl.localhost\...` path | Copy netlist to `C:\Users\...\Temp\` before running |
| vtb.defs warning on open | SystemVue not installed | Benign — suppress with `warnings.catch_warnings()` |
| `palette.ael` warning on open | WIN PDK palette issue | Benign — does not affect simulation |
| `create_netlist` AttributeError | Not available in this API version | Use `create_schematic()` + `generate_netlist()` instead |
| Duplicate lib in lib.defs | `add_library` called twice | Delete workspace and recreate from scratch |
