r"""
ads_lpf_skill_test.py
=====================
Skill test: ads-netlist-translator
Circuit:    Ideal 3rd-order Butterworth LPF (~1 GHz, 50 Ohm)

Steps:
  1. Build flat ADS schematic (L1-C1-L2 + Term1/Term2 + S_Param) — no subcircuit
  2. Run S-parameter simulation
  3. Export ADS-generated netlist to lpf_ads_generated.net
  4. Print S11/S21 results and compare to Python baseline

Run with:
  C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe ads_lpf_skill_test.py
"""

import sys, os, shutil, time, subprocess
from pathlib import Path

ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

import keysight.ads.de as de
from keysight.ads.de import db_uu as db

# ── Component values (from parse_circuit.mjs / lpf_demo.net) ─────────────────
L1_val = "7.958 nH"
C1_val = "6.366 pF"
L2_val = "7.958 nH"

# ── Workspace ─────────────────────────────────────────────────────────────────
WRK_DIR = Path(r"C:\Users\jarvis\ads_projects\lpf_skill_test_wrk")
LIB_NAME = "lpf_skill_lib"

print("=" * 62)
print("ADS Skill Test -- LPF Schematic + Simulation")
print("=" * 62)

shutil.rmtree(str(WRK_DIR), ignore_errors=True)
if de.workspace_is_open():
    de.close_workspace()

workspace = de.create_workspace(str(WRK_DIR))
workspace.open()
de.create_new_library(LIB_NAME, str(WRK_DIR / LIB_NAME))
workspace.add_library(LIB_NAME, str(WRK_DIR / LIB_NAME), de.LibraryMode.SHARED)
print(f"[OK] Workspace: {WRK_DIR}")

# ── Build flat schematic (no subcircuit) ──────────────────────────────────────
# Layout on a single row with standard ADS component spacing:
#
#  Term1(0,0) --wire-- L1(1,0) --wire-- C1(2.5,0)--wire--0  --wire-- L2(3.5,0) --wire-- Term2(5,0)
#                                            |
#                                         GND(2.5,-1)
#
# ADS ads_rflib:L symbol: body width ~1 unit, pins at x-0.5 and x+0.5 of origin
# ADS ads_rflib:C symbol: at angle=-90, pins at top (origin) and bottom (origin-1 in y)
# ADS ads_simulation:Term at angle=-90: RF pin at the instance origin (top of symbol)

sch = db.create_schematic(f"{LIB_NAME}:LPF_SP:schematic")
tx  = de.db.Transaction(sch, "Build LPF flat schematic")

# Pin positions (from symbol inspection):
#   ads_rflib:L   R0:    P1 at origin (x+0.0, y), P2 at (x+1.0, y)
#   ads_rflib:C   R270:  P1 at origin (x, y+0.0), P2 at (x, y-1.0)  [rotated]
#   ads_sim:Term  R270:  P1 at origin (x, y+0.0), P2 at (x, y-1.0)  [rotated]
#
# Layout (all on y=0 signal line):
#   Term1 @ (0,0)  P1=(0,0)  --wire--  L1 @ (1.5,0)  P1=(1.5,0) P2=(2.5,0)
#   --wire--  C1 @ (3.0,0) [R270] P1=(3.0,0) P2=(3.0,-1)  --wire--  L2 @ (4.0,0)
#   P1=(4.0,0) P2=(5.0,0)  --wire--  Term2 @ (6.0,0) P1=(6.0,0)

# Term1 — P1 (RF) at (0, 0), angle=-90 (R270)
t1 = sch.add_instance(de.LCVName("ads_simulation","Term","symbol"),
                       (0.0, 0.0), name="Term1", angle=-90.0)
t1.parameters["Num"].value = "1"
t1.parameters["Z"].value   = "50 Ohm"

# L1 — P1 at (1.5, 0), P2 at (2.5, 0)
l1 = sch.add_instance(de.LCVName("ads_rflib","L","symbol"),
                       (1.5, 0.0), name="L1", angle=0.0)
l1.parameters["L"].value = L1_val

# C1 — placed at (3.0, 0), R270: P1 at (3.0, 0) [top], P2 at (3.0, -1) [bottom/GND]
c1 = sch.add_instance(de.LCVName("ads_rflib","C","symbol"),
                       (3.0, 0.0), name="C1", angle=-90.0)
c1.parameters["C"].value = C1_val

# GROUND below C1 — pin at top, placed at (3.0, -1.0)
sch.add_instance(de.LCVName("ads_rflib","GROUND","symbol"),
                 (3.0, -1.0), name="GND1", angle=-90.0)

# L2 — P1 at (4.0, 0), P2 at (5.0, 0)
l2 = sch.add_instance(de.LCVName("ads_rflib","L","symbol"),
                       (4.0, 0.0), name="L2", angle=0.0)
l2.parameters["L"].value = L2_val

# Term2 — P1 (RF) at (6.0, 0), angle=-90 (R270)
t2 = sch.add_instance(de.LCVName("ads_simulation","Term","symbol"),
                       (6.0, 0.0), name="Term2", angle=-90.0)
t2.parameters["Num"].value = "2"
t2.parameters["Z"].value   = "50 Ohm"

# S_Param controller
sp = sch.add_instance(de.LCVName("ads_simulation","S_Param","symbol"),
                       (1.5, -3.0), name="SP1", angle=0.0)
sp.parameters["Start"].value = "100 MHz"
sp.parameters["Stop"].value  = "5 GHz"
sp.parameters["Step"].value  = "100 MHz"

# GND refs for Term1 and Term2
sch.add_instance(de.LCVName("ads_rflib","GROUND","symbol"),
                 (0.0, -1.0), name="GND2", angle=-90.0)
sch.add_instance(de.LCVName("ads_rflib","GROUND","symbol"),
                 (6.0, -1.0), name="GND3", angle=-90.0)

# ── Wires (pin-to-pin exact coordinates) ──────────────────────────────────────
sch.add_wire([(0.0, 0.0), (1.5, 0.0)])   # Term1.P1 -> L1.P1
sch.add_wire([(2.5, 0.0), (3.0, 0.0)])   # L1.P2 -> C1.P1 (mid node)
sch.add_wire([(3.0, 0.0), (4.0, 0.0)])   # C1.P1 (mid node) -> L2.P1
sch.add_wire([(5.0, 0.0), (6.0, 0.0)])   # L2.P2 -> Term2.P1

tx.commit()
sch.save_design()
print("[OK] Schematic saved: LPF_SP:schematic")

# ── Verify connectivity ───────────────────────────────────────────────────────
print("\nConnectivity check:")
for inst in sch.instances:
    it_list = list(inst.get_inst_term_iter())
    nets = []
    for it in it_list:
        try:    nets.append(f"{it.term_name}={it.net.name if it.net else 'OPEN'}")
        except: nets.append(f"#{it.term_number}={it.net.name if it.net else 'OPEN'}")
    print(f"  {inst.name:10s}  {' | '.join(nets)}")

# ── Generate & export netlist ─────────────────────────────────────────────────
print("\n[STEP 2] Generating ADS netlist...")
netlist_text = sch.generate_netlist()
lines = netlist_text.splitlines()
print(f"  {len(lines)} lines generated")

netlist_out = Path(r"C:\Users\jarvis\ads_projects\lpf_skill_test_wrk\lpf_ads_generated.net")
netlist_out.write_text(netlist_text, encoding="utf-8")
print(f"  Exported: {netlist_out}")

print("\n--- ADS Generated Netlist ---")
for ln in lines:
    print(f"  {ln}")
print("--- End Netlist ---")

# ── Simulate ──────────────────────────────────────────────────────────────────
print("\n[STEP 3] Running simulation...")
OUTPUT_DIR = WRK_DIR / "sim_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

sim_ok = False
try:
    from keysight.edatoolbox import ads as edatoolbox_ads
    simulator = edatoolbox_ads.CircuitSimulator()
    t0 = time.time()
    simulator.run_netlist(netlist_text, output_dir=str(OUTPUT_DIR))
    print(f"  [OK] Simulation done in {time.time()-t0:.1f}s")
    sim_ok = True
except Exception as e:
    print(f"  [WARN] CircuitSimulator: {e} -- trying hpeesofsim fallback")

if not sim_ok:
    net_file = OUTPUT_DIR / "lpf_flat.net"
    net_file.write_text(netlist_text, encoding="utf-8")
    env = dict(os.environ)
    env["PATH"]        = str(ADS_DIR/"bin") + os.pathsep + env.get("PATH","")
    env["HPEESOF_DIR"] = str(ADS_DIR)
    res = subprocess.run([str(ADS_DIR/"bin"/"hpeesofsim.exe"), str(net_file)],
                         capture_output=True, text=True, env=env,
                         cwd=str(OUTPUT_DIR), timeout=120)
    print(f"  hpeesofsim exit: {res.returncode}")
    if res.stdout: print(res.stdout[:2000])
    if res.stderr: print(res.stderr[:400])
    sim_ok = (res.returncode == 0)

# ── Read & report results ─────────────────────────────────────────────────────
print("\n[STEP 4] Results vs Python baseline:")
try:
    import numpy as np
    import keysight.ads.dataset as dataset

    ds_files = sorted(OUTPUT_DIR.glob("*.ds"))
    if not ds_files:
        print("  No .ds file found -- sim output:")
        for f in OUTPUT_DIR.iterdir(): print(f"    {f.name}")
    else:
        ds = dataset.open(ds_files[0])
        sp_key = next((k for k in ds.keys() if "SP" in k.upper()), None)
        df = ds[sp_key].to_dataframe()
        freqs_GHz = df.index.values / 1e9
        S21 = df["S[2,1]"].values
        S11 = df["S[1,1]"].values
        IL_dB = -20*np.log10(np.maximum(np.abs(S21), 1e-30))
        RL_dB = -20*np.log10(np.maximum(np.abs(S11), 1e-30))

        # Python baseline
        baseline = {0.1:0.000, 0.5:0.067, 1.0:3.010, 2.0:18.129, 5.0:41.939}

        print(f"  {'Freq':>6}  {'IL_ADS':>8}  {'IL_Py':>8}  {'Delta':>7}  {'RL':>8}")
        print("  " + "-"*48)
        spot = [0.1, 0.5, 1.0, 2.0, 5.0]
        for f in spot:
            idx = np.argmin(np.abs(freqs_GHz - f))
            il  = IL_dB[idx]
            rl  = RL_dB[idx]
            py  = baseline.get(f, float('nan'))
            delta = il - py
            print(f"  {f:>5.1f}G  {il:>8.3f}  {py:>8.3f}  {delta:>+7.3f}  {rl:>8.2f}")

except Exception as e:
    print(f"  [WARN] {e}")
    import traceback; traceback.print_exc()

workspace.close()
print("\n" + "="*62)
print("COMPLETE")
print(f"Workspace : {WRK_DIR}")
print(f"Netlist   : {netlist_out}")
print(f"Open in ADS: File > Open Workspace > {WRK_DIR}")
print("="*62)
