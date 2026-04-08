r"""
ads_build_lpf_demo.py
=====================
# Created by: net-to-ads agent
# Run: 2026-04-06  (Run 2)
# Purpose: Build lpf_demo schematic in existing spdt_switch_pdk_wrk workspace
# Inputs: lpf_demo_ads_buildplan.yaml (pre-computed coordinates)
# Outputs: lpf_demo:schematic in spdt_switch_pdk_lib, lpf_demo_ads_generated.net
# Replaces: Manual schematic entry for passives-only LPF circuit

Build ideal 3rd-order Butterworth LPF schematic into existing ADS workspace.
Target: spdt_switch_pdk_lib:lpf_demo:schematic in spdt_switch_pdk_wrk

Component layout (signal path y=0, left-to-right):
  Term1 @ (0,0) -- L1 @ (1.5,0) -- [C1 shunt @ (3.0,0)] -- L2 @ (4.0,0) -- Term2 @ (6,0)

Run with ADS Python:
  "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" ads_build_lpf_demo.py
"""

import sys, os, warnings
from pathlib import Path

ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

import keysight.ads.de as de
from keysight.ads.de import db_uu as db

WRK_DIR  = Path(r"C:\Users\jarvis\ads_projects\spdt_switch_pdk_wrk")
LIB_NAME = "spdt_switch_pdk_lib"
LIB_DIR  = WRK_DIR / LIB_NAME
PDK_DIR  = Path(r"C:\Users\jarvis\ads_projects\design_kits\WIN_PP1029_DESIGN_KIT")
CELL_NAME = "lpf_demo"
NET_OUT  = WRK_DIR / "lpf_demo_ads_generated.net"

print("=" * 62)
print("LPF Demo Build -- Passives-Only Schematic (Stage 3, Run 2)")
print("=" * 62)
print(f"Target: {LIB_NAME}:{CELL_NAME}:schematic in {WRK_DIR}")

# ── Step 1: Open existing workspace (do NOT recreate) ─────────────────────────
if de.workspace_is_open():
    de.close_workspace()

print(f"\n[1] Opening existing workspace: {WRK_DIR}")
if not WRK_DIR.exists():
    print(f"[ERROR] Workspace not found: {WRK_DIR}")
    print("        Please create the workspace first (it should already exist from Run 1).")
    sys.exit(1)

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    workspace = de.open_workspace(str(WRK_DIR))

# Ensure our lib is registered
existing_libs = [lib.name for lib in workspace.libraries]
if LIB_NAME not in existing_libs:
    if not LIB_DIR.exists():
        de.create_new_library(LIB_NAME, str(LIB_DIR))
    workspace.add_library(LIB_NAME, str(LIB_DIR), de.LibraryMode.SHARED)
    print(f"[1] Library '{LIB_NAME}' registered.")
else:
    print(f"[1] Library '{LIB_NAME}' already registered.")

# Delete any existing lpf_demo cell to allow clean rebuild
cell_dir = LIB_DIR / CELL_NAME
if cell_dir.exists():
    import shutil
    shutil.rmtree(str(cell_dir), ignore_errors=True)
    print(f"[1] Removed existing cell dir: {cell_dir}")

print(f"[1] Workspace ready.")

# ── Step 2: Build schematic ───────────────────────────────────────────────────
print(f"\n[2] Building schematic: {LIB_NAME}:{CELL_NAME}:schematic")
sch = db.create_schematic(f"{LIB_NAME}:{CELL_NAME}:schematic")
tx  = de.db.Transaction(sch, f"build_{CELL_NAME}")

# ── Component factory helpers ─────────────────────────────────────────────────
def mkL(name, x, y, val, angle=0.0):
    i = sch.add_instance(de.LCVName("ads_rflib", "L", "symbol"),
                         (x, y), name=name, angle=angle)
    i.parameters["L"].value = val
    return i

def mkC(name, x, y, val, angle=-90.0):
    i = sch.add_instance(de.LCVName("ads_rflib", "C", "symbol"),
                         (x, y), name=name, angle=angle)
    i.parameters["C"].value = val
    return i

def mkGnd(name, x, y):
    return sch.add_instance(de.LCVName("ads_rflib", "GROUND", "symbol"),
                             (x, y), name=name, angle=-90.0)

def mkTerm(name, x, y, num):
    i = sch.add_instance(de.LCVName("ads_simulation", "Term", "symbol"),
                         (x, y), name=name, angle=-90.0)
    i.parameters["Num"].value = str(num)
    i.parameters["Z"].value   = "50 Ohm"
    return i

# ── Layout: signal path at y=0, left-to-right ───────────────────────────────
# Topology: Term1 -- L1 -- (C1 shunt to GND) -- L2 -- Term2
#
# x=0.0  : Term1   RF pin at (0,0)
# x=1.5  : L1      P1=(1.5,0)  P2=(2.5,0)
# x=3.0  : C1      P1=(3.0,0) [mid tap]  P2=(3.0,-1) [GND]
# x=4.0  : L2      P1=(4.0,0)  P2=(5.0,0)
# x=6.0  : Term2   RF pin at (6,0)
#
# GND symbols: below C1, below Term1, below Term2

Y = 0.0

mkTerm("Term1", 0.0, Y, 1)
mkGnd("GND_T1", 0.0, Y - 1.0)

mkL("L1", 1.5, Y, "7.958 nH")

mkC("C1", 3.0, Y, "6.366 pF")     # angle=-90 by default: P1=(3,0), P2=(3,-1)
mkGnd("GND_C1", 3.0, Y - 1.0)

mkL("L2", 4.0, Y, "7.958 nH")

mkTerm("Term2", 6.0, Y, 2)
mkGnd("GND_T2", 6.0, Y - 1.0)

# S_Param controller (below circuit)
sp = sch.add_instance(de.LCVName("ads_simulation", "S_Param", "symbol"),
                       (1.5, Y - 3.0), name="SP1", angle=0.0)
sp.parameters["Start"].value = "100 MHz"
sp.parameters["Stop"].value  = "5 GHz"
sp.parameters["Step"].value  = "100 MHz"

# ── Wires ─────────────────────────────────────────────────────────────────────
sch.add_wire([(0.0, Y), (1.5, Y)])    # Term1 -> L1.P1
sch.add_wire([(2.5, Y), (3.0, Y)])    # L1.P2 -> C1.P1 (mid node)
sch.add_wire([(3.0, Y), (4.0, Y)])    # C1.P1 (mid) -> L2.P1
sch.add_wire([(5.0, Y), (6.0, Y)])    # L2.P2 -> Term2

tx.commit()
sch.save_design()
print("[2] Schematic built and saved.")

# ── Step 3: Verify connectivity ───────────────────────────────────────────────
print("\n[3] Connectivity check:")
for inst in sch.instances:
    it_list = list(inst.get_inst_term_iter())
    nets = []
    for it in it_list:
        try:
            nets.append(f"{it.term_name}={it.net.name if it.net else 'OPEN'}")
        except Exception:
            nets.append(f"#{it.term_number}={it.net.name if it.net else 'OPEN'}")
    print(f"  {inst.name:10s}  {' | '.join(nets)}")

# ── Step 4: Generate netlist ──────────────────────────────────────────────────
print("\n[4] Generating ADS netlist from schematic...")
netlist_text = sch.generate_netlist()
NET_OUT.write_text(netlist_text, encoding="utf-8")
lines = netlist_text.splitlines()
print(f"[4] Written: {NET_OUT.name}  ({len(lines)} lines)")
print("\n--- ADS Generated Netlist ---")
for ln in lines[:60]:
    print(f"  {ln}")
if len(lines) > 60:
    print(f"  ... [{len(lines)-60} more lines]")
print("--- End Netlist ---")

print(f"\nWorkspace : {WRK_DIR}")
print(f"Schematic : {LIB_NAME}:{CELL_NAME}:schematic")
print(f"Netlist   : {NET_OUT.name}")
print("Done. Run check_netlist.py on lpf_demo_ads_generated.net to verify.")
