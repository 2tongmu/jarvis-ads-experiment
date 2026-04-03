# ads_build_spdt.py
# SPDT switch: build ADS schematic from netlist values (LPF-style flow).
#
#   1. Create workspace with WIN_PP1029_DESIGN_KIT loaded via lib.defs INCLUDE
#   2. Build flat schematic: Term1 + all R/L/C inline + Term2 + S_Param
#   3. generate_netlist() from schematic --> simulate via CircuitSimulator
#   4. Validate S21 vs Node.js baseline
#
# Run via ADS Python:
#   "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" ads_build_spdt.py

import sys, os, shutil, warnings
from pathlib import Path

ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

import numpy as np
import keysight.ads.de as de
from keysight.ads.de import db_uu as db
import keysight.ads.dataset as dataset
from keysight.edatoolbox import ads as edatoolbox_ads

WRK_DIR  = Path(r"C:\Users\jarvis\ads_projects\spdt_switch_wrk")
LIB_NAME = "spdt_switch_lib"
LIB_DIR  = WRK_DIR / LIB_NAME
SIM_DIR  = WRK_DIR / "sim_output"
PDK_DIR  = Path(r"C:\Users\jarvis\ads_projects\design_kits\WIN_PP1029_DESIGN_KIT")

print("=" * 60)
print("SPDT Switch -- ADS Build + Simulation")
print("=" * 60)

# ================================================================
# Step 1: Create workspace and inject PDK into lib.defs
# ================================================================
print(f"[1] Creating workspace: {WRK_DIR}")
shutil.rmtree(str(WRK_DIR), ignore_errors=True)
if de.workspace_is_open():
    de.close_workspace()

workspace = de.create_workspace(str(WRK_DIR))

# Write PDK INCLUDE into lib.defs before opening
# ADS reads lib.defs at open time -- this is how the LPF_Design_Demo loads its PDK
pdk_lib_defs = PDK_DIR / "lib.defs"
lib_defs_path = WRK_DIR / "lib.defs"
with open(lib_defs_path, "a") as f:
    f.write(f'\nINCLUDE {pdk_lib_defs}\n')
print(f"[1] PDK injected: {pdk_lib_defs}")

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    workspace.open()

de.create_new_library(LIB_NAME, str(LIB_DIR))
workspace.add_library(LIB_NAME, str(LIB_DIR), de.LibraryMode.SHARED)
print(f"[1] Library '{LIB_NAME}' ready.")

# ================================================================
# Step 2: Build flat schematic
#
# Layout: all series components along y=0, 2 units apart (so each
# occupies x=[n, n+1], gap at n+1 to n+2 = wire).
# Shunts hang downward from the signal wire.
#
# Series chain (left pin x):
#   0:Term1  1:Rpad_in  3:Lpad_in  5:Ri1  7:Li1
#   9:Ron_Q1a  11:Ls_Q1a  13:Rvia_Q1a  15:Lvia_Q1a
#   17:Ron_Q1b  19:Ls_Q1b  21:Rvia_Q1b  23:Lvia_Q1b
#   25:Ro1  27:Lo1  29:Lpad_out  31:Rpad_out
#   33:Term2
#
# Shunt nodes at right-pin x of preceding element:
#   x=4  (after Lpad_in):  Cpad_in(65fF), Ci1a(24fF)    --> both shunt to GND
#   x=8  (after Li1):      Ci1b(24fF)                   --> shunt to GND
#   x=16 (after Lvia_Q1a): Q3a chain + Cgd_Q1a chain    --> shunt to GND
#   x=24 (after Lvia_Q1b): Q3b chain + Cgd_Q1b chain    --> shunt to GND
#   x=28 (after Lo1):      Co1b(24fF)                   --> shunt to GND
#   x=32 (after Rpad_out): Co_end(24fF), Cpad_out(65fF) --> shunt to GND
# ================================================================
print("[2] Building schematic...")
sch = db.create_schematic(f"{LIB_NAME}:spdt_switch:schematic")
tx  = de.db.Transaction(sch, "build_spdt")

def mkR(name, x, y, val, angle=0.0):
    i = sch.add_instance(de.LCVName("ads_rflib","R","symbol"), (x,y), name=name, angle=angle)
    i.parameters["R"].value = val
    return i

def mkL(name, x, y, val, angle=0.0):
    i = sch.add_instance(de.LCVName("ads_rflib","L","symbol"), (x,y), name=name, angle=angle)
    i.parameters["L"].value = val
    return i

def mkC(name, x, y, val, angle=-90.0):
    i = sch.add_instance(de.LCVName("ads_rflib","C","symbol"), (x,y), name=name, angle=angle)
    i.parameters["C"].value = val
    return i

def mkGnd(name, x, y):
    return sch.add_instance(de.LCVName("ads_rflib","GROUND","symbol"),
                             (x,y), name=name, angle=-90.0)

def mkTerm(name, x, y, num):
    i = sch.add_instance(de.LCVName("ads_simulation","Term","symbol"),
                         (x,y), name=name, angle=-90.0)
    i.parameters["Num"].value = str(num)
    i.parameters["Z"].value   = "50 Ohm"
    return i

def wire(pts):
    sch.add_wire(pts)

# ── Ports ─────────────────────────────────────────────────────
mkTerm("Term1",  0, 0, 1)
mkGnd("GND_t1",  0, -1.0)
mkTerm("Term2", 33, 0, 2)
mkGnd("GND_t2", 33, -1.0)

# ── Series chain ──────────────────────────────────────────────
# Input pad
mkR("Rpad_in",   1, 0, "0.05 Ohm")
mkL("Lpad_in",   3, 0, "10 pH")
# Input interconnect
mkR("Ri1",       5, 0, "0.009 Ohm")
mkL("Li1",       7, 0, "120 pH")
# Stage 1: Series FET Q1a ON
# PDK SWAP: replace Ron_Q1a+Ls_Q1a+Rvia_Q1a+Lvia_Q1a with WIN_PP1029_MS NOF=2 UGW=80
mkR("Ron_Q1a",   9, 0, "2.50 Ohm")
mkL("Ls_Q1a",   11, 0, "50 pH")
mkR("Rvia_Q1a", 13, 0, "0.08 Ohm")
mkL("Lvia_Q1a", 15, 0, "50 pH")
# Stage 2: Series FET Q1b ON
# PDK SWAP: replace Ron_Q1b+Ls_Q1b+Rvia_Q1b+Lvia_Q1b with WIN_PP1029_MS NOF=2 UGW=80
mkR("Ron_Q1b",  17, 0, "2.50 Ohm")
mkL("Ls_Q1b",   19, 0, "50 pH")
mkR("Rvia_Q1b", 21, 0, "0.08 Ohm")
mkL("Lvia_Q1b", 23, 0, "50 pH")
# Output interconnect
mkR("Ro1",      25, 0, "0.009 Ohm")
mkL("Lo1",      27, 0, "120 pH")
# Output pad
mkL("Lpad_out", 29, 0, "10 pH")
mkR("Rpad_out", 31, 0, "0.05 Ohm")

# ── Series wires ──────────────────────────────────────────────
for a, b in [(0,1),(2,3),(4,5),(6,7),(8,9),(10,11),(12,13),(14,15),
             (16,17),(18,19),(20,21),(22,23),(24,25),(26,27),(28,29),(30,31),(32,33)]:
    wire([(float(a), 0.0), (float(b), 0.0)])

# ================================================================
# Shunt elements
# For C at angle=-90: P1 (RF) = instance origin (x,y), P2 (GND) = (x, y-1)
# For R/L at angle=-90: P1 = (x,y), P2 = (x, y-1)
# So a vertical chain of (C, R, L, GND) placed at y=0,-1,-2,-3,-4 auto-connects.
# ================================================================

# ── x=4: Cpad_in + Ci1a both shunt to GND ────────────────────
mkC("Cpad_in", 4.2, 0, "65 fF");  mkGnd("GND_cpad_in",  4.2, -1.0)
mkC("Ci1a",    4.6, 0, "24 fF");  mkGnd("GND_ci1a",     4.6, -1.0)

# ── x=8: Ci1b shunt to GND ───────────────────────────────────
mkC("Ci1b",    8.5, 0, "24 fF");  mkGnd("GND_ci1b",     8.5, -1.0)

# ── x=16: Q3a shunt OFF chain + Cgd_Q1a feedback chain ───────

# Q3a OFF: Coff_Q3a(30fF) -> Lsh_Q3a(50pH) -> Rtrm1(47Ohm) -> Lrt_Q3a(25pH) -> GND
# PDK SWAP: replace Coff_Q3a + Lsh_Q3a with WIN_PP1029_MS NOF=2 UGW=50
#           keep Rtrm1 + Lrt_Q3a unchanged, reconnect source pin to Rtrm1
q3a_x = 16.2
mkC("Coff_Q3a", q3a_x,  0.0, "30 fF")
mkL("Lsh_Q3a",  q3a_x, -1.0, "50 pH",  angle=-90.0)
mkR("Rtrm1",    q3a_x, -2.0, "47 Ohm", angle=-90.0)
mkL("Lrt_Q3a",  q3a_x, -3.0, "25 pH",  angle=-90.0)
mkGnd("GND_sh1a", q3a_x, -4.0)

# Cgd_Q1a feedback: Cgd(8fF) -> [Rg(300Ohm) || Cpg(12fF)] -> Lsg(150pH) -> GND
# Chain at x=16.7 (Rg column) and x=17.5 (Cpg parallel column)
cgd1_x  = 16.7
cpg1_x  = 17.5
mkC("Cgd_Q1a",  cgd1_x,  0.0, "8 fF")         # P1=(cgd1_x,0)=n16 on signal, P2=(cgd1_x,-1)=ng1
mkR("Rg_Q1a",   cgd1_x, -1.0, "300 Ohm", angle=-90.0)  # ng1 -> ng2
mkC("Cpg_Q1a",  cpg1_x, -1.0, "12 fF")         # parallel across ng1..ng2
mkL("Lsg_Q1a",  cgd1_x, -2.0, "150 pH",  angle=-90.0)  # ng2 -> GND
mkGnd("GND_gate1a", cgd1_x, -3.0)
wire([(cgd1_x, -1.0), (cpg1_x, -1.0)])   # ng1 horizontal (Rg.P1 <-> Cpg.P1)
wire([(cgd1_x, -2.0), (cpg1_x, -2.0)])   # ng2 horizontal (Rg.P2 <-> Cpg.P2)

# ── x=24: Q3b shunt OFF chain + Cgd_Q1b feedback chain ───────

# Q3b OFF
# PDK SWAP: replace Coff_Q3b + Lsh_Q3b with WIN_PP1029_MS NOF=2 UGW=50
q3b_x = 24.2
mkC("Coff_Q3b", q3b_x,  0.0, "30 fF")
mkL("Lsh_Q3b",  q3b_x, -1.0, "50 pH",  angle=-90.0)
mkR("Rtrm2",    q3b_x, -2.0, "47 Ohm", angle=-90.0)
mkL("Lrt_Q3b",  q3b_x, -3.0, "25 pH",  angle=-90.0)
mkGnd("GND_sh1b", q3b_x, -4.0)

# Co1a (first half output interconnect pi) -- also at x=24
mkC("Co1a",     24.6,  0.0, "24 fF");  mkGnd("GND_co1a", 24.6, -1.0)

# Cgd_Q1b feedback
cgd2_x  = 24.9
cpg2_x  = 25.7
mkC("Cgd_Q1b",  cgd2_x,  0.0, "8 fF")
mkR("Rg_Q1b",   cgd2_x, -1.0, "300 Ohm", angle=-90.0)
mkC("Cpg_Q1b",  cpg2_x, -1.0, "12 fF")
mkL("Lsg_Q1b",  cgd2_x, -2.0, "150 pH",  angle=-90.0)
mkGnd("GND_gate1b", cgd2_x, -3.0)
wire([(cgd2_x, -1.0), (cpg2_x, -1.0)])
wire([(cgd2_x, -2.0), (cpg2_x, -2.0)])

# ── x=28: Co1b shunt to GND ───────────────────────────────────
mkC("Co1b",    28.5, 0, "24 fF");  mkGnd("GND_co1b",    28.5, -1.0)

# ── x=30 (between Lpad_out and Rpad_out): Cpad_out shunt ─────
mkC("Cpad_out",30.5, 0, "65 fF");  mkGnd("GND_cpad_out",30.5, -1.0)

# ── S_Param controller (placed above the circuit) ─────────────
sp = sch.add_instance(de.LCVName("ads_simulation","S_Param","symbol"),
                      (10.0, 4.0), name="SP1")
sp.parameters["Start"].value = "2 GHz"
sp.parameters["Stop"].value  = "18 GHz"
sp.parameters["Step"].value  = "50 MHz"

tx.commit()
sch.save_design()
print("[2] Schematic built and saved.")

# ================================================================
# Step 3: Generate netlist from schematic and simulate
# ================================================================
print("[3] Generating netlist from schematic...")
netlist_text = sch.generate_netlist()

# Save ADS-generated netlist to workspace
ads_net_path = WRK_DIR / "spdt_ads_generated.net"
ads_net_path.write_text(netlist_text, encoding="utf-8")
print(f"[3] ADS-generated netlist: {ads_net_path}")
print(f"[3] ({len(netlist_text.splitlines())} lines)")

print("[3] Running simulation...")
SIM_DIR.mkdir(parents=True, exist_ok=True)
simulator = edatoolbox_ads.CircuitSimulator()
simulator.run_netlist(netlist_text, output_dir=str(SIM_DIR))
print("[3] Simulation complete.")

# ================================================================
# Step 4: Read and validate results
# ================================================================
print("[4] Reading results...")
ds_files = sorted(SIM_DIR.glob("*.ds"))
if not ds_files:
    print("[4] ERROR: no .ds file found!")
    sys.exit(1)

ds = dataset.open(ds_files[0])
df = ds["SP1.SP"].to_dataframe()
freq_hz = df.index.values
S21 = df["S[2,1]"].values
S11 = df["S[1,1]"].values
IL_dB = -20 * np.log10(np.abs(S21))
RL_dB = -20 * np.log10(np.abs(S11))

BASELINE = {
     2e9: 0.459,  4e9: 0.494,  6e9: 0.548,
     8e9: 0.614, 10e9: 0.685, 12e9: 0.755,
    14e9: 0.819, 16e9: 0.886, 18e9: 0.954,
}
TOL_IL = 0.05

print()
print("=" * 65)
print("VALIDATION  (PATH A active: P1->P2)")
print(f"  {'Freq':>4}  {'IL_ADS':>8}  {'IL_ref':>7}  {'delta':>7}  {'RL_ADS':>8}")
print("-" * 65)
all_pass = True
for f_hz in sorted(BASELINE.keys()):
    il_ref = BASELINE[f_hz]
    idx    = np.argmin(np.abs(freq_hz - f_hz))
    il     = IL_dB[idx]
    rl     = RL_dB[idx]
    d      = il - il_ref
    ok     = abs(d) <= TOL_IL
    if not ok:
        all_pass = False
    tag = "PASS" if ok else "FAIL <<"
    print(f"  {f_hz/1e9:>4.0f}  {il:>8.3f}  {il_ref:>7.3f}  {d:>+7.3f}  {rl:>8.2f}  {tag}")
print("-" * 65)
print(f"  Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
print("=" * 65)

# Copy hand-written netlist to workspace too
hw_src = Path(r"C:\Users\jarvis\AppData\Local\Temp\spdt_switch.net")
if hw_src.exists():
    shutil.copy(str(hw_src), str(WRK_DIR / "spdt_switch.net"))

print()
print(f"ADS workspace : {WRK_DIR}")
print(f"Library       : {LIB_NAME}")
print(f"Schematic cell: {LIB_NAME}:spdt_switch:schematic")
print(f"ADS netlist   : {ads_net_path}")
print("Done.")
