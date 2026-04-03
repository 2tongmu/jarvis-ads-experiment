r"""
ads_run_example.py
==================
Launches ADS 2026 in automation mode (keysight.ads as a Python library),
opens the built-in LPF_Design_Demo example workspace, runs an S-parameter
simulation, and reports key results (S11, S21, -3dB cutoff).

Run with ADS's bundled Python:
  C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe ads_run_example.py

Requirements:
  - ADS 2026 Update 1 installed at default path
  - Valid ADS license
"""

import os
import sys
import shutil
import time
from pathlib import Path

# ── 1.  Set up paths ─────────────────────────────────────────────────────────
ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
PYTHON_PACKAGES = ADS_DIR / "tools" / "python" / "packages"
ADS_BIN = ADS_DIR / "bin"

if str(PYTHON_PACKAGES) not in sys.path:
    sys.path.insert(0, str(PYTHON_PACKAGES))

os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

# ── 2.  Import keysight.ads ───────────────────────────────────────────────────
print("=" * 60)
print("ADS Python Automation - LPF Example Simulation")
print("=" * 60)

try:
    import keysight.ads.de as de
    from keysight.ads.de import db_uu as db
    print("[OK] keysight.ads imported successfully (automation mode)")
except ImportError as e:
    print(f"[ERROR] Could not import keysight.ads: {e}")
    print(f"        Run with: {ADS_DIR/'tools'/'python'/'python.exe'}")
    sys.exit(1)

# ── 3.  Unarchive the built-in LPF_Design_Demo example ───────────────────────
EXAMPLE_ZAP = ADS_DIR / "examples" / "RF_Microwave" / "LPF_Design_Demo_wrk.7zads"
DEST_DIR = Path(os.environ.get("USERPROFILE", r"C:\Users\Public")) / "ads_lpf_demo_wrk"

print(f"\n[STEP 1] Source example: {EXAMPLE_ZAP.name}")
print(f"         Destination:    {DEST_DIR}")

if DEST_DIR.exists():
    print("         Removing previous extraction ...")
    shutil.rmtree(str(DEST_DIR), ignore_errors=True)

if de.workspace_is_open():
    de.close_workspace()

print("         Unarchiving workspace ...")
de.unarchive_file(str(EXAMPLE_ZAP), str(DEST_DIR))
print("[OK] Unarchived.")

# ── 4.  Find the actual workspace directory created ──────────────────────────
# unarchive_file may create a subdirectory; find the .wrk dir
wrk_candidates = [DEST_DIR] + list(DEST_DIR.iterdir()) if DEST_DIR.exists() else []
wrk_dir = None
for c in wrk_candidates:
    if c.is_dir() and (c / "lib.defs").exists():
        wrk_dir = c
        break
if wrk_dir is None:
    # Fallback: just use dest_dir itself
    wrk_dir = DEST_DIR
print(f"         Workspace dir:  {wrk_dir}")

# ── 5.  Open the workspace ────────────────────────────────────────────────────
print("\n[STEP 2] Opening workspace ...")
workspace = de.open_workspace(str(wrk_dir))
print(f"         Open: {workspace.is_open}")

# ── 6.  List libraries and designs ───────────────────────────────────────────
print("\n[STEP 3] Discovering designs ...")
all_views = []
for lib_name in workspace.writable_library_names:
    lib = workspace.open_library(lib_name)
    for cell in lib.cells:
        for view in cell.views:
            lcv = str(view.lcv_name)
            all_views.append(lcv)
            print(f"         Found: {lcv}")

# Find a schematic with a simulation controller
sim_design = None
for lcv in all_views:
    if ":schematic" in lcv.lower():
        try:
            d = db.open_design(lcv)
            # Check if it has a simulation controller component
            instances = list(d.instances)
            comp_names = [str(getattr(inst, 'component_name', '')) for inst in instances]
            has_sim = any("S_Param" in c or "SP" in c or "AC" in c for c in comp_names)
            if has_sim:
                sim_design = d
                print(f"\n[OK] Selected design for simulation: {lcv}")
                print(f"     Components: {[inst.name for inst in instances[:8]]}")
                break
            d  # keep ref alive
        except Exception as e:
            print(f"         [skip] {lcv}: {e}")

if sim_design is None and all_views:
    # Just open the first schematic
    for lcv in all_views:
        if ":schematic" in lcv.lower():
            sim_design = db.open_design(lcv)
            print(f"\n[INFO] Using first schematic: {lcv}")
            break

if sim_design is None:
    print("[ERROR] No suitable schematic found.")
    workspace.close()
    sys.exit(1)

# ── 7.  Generate netlist ──────────────────────────────────────────────────────
print("\n[STEP 4] Generating netlist ...")
netlist = sim_design.generate_netlist()
lines = netlist.splitlines()
print(f"         Netlist: {len(lines)} lines")

print("\n--- NETLIST (first 35 lines) ---")
for i, line in enumerate(lines[:35]):
    print(f"  {line}")
if len(lines) > 35:
    print(f"  ... ({len(lines) - 35} more lines)")
print("--- END NETLIST ---")

# ── 8.  Run simulation ────────────────────────────────────────────────────────
OUTPUT_DIR = wrk_dir / "python_sim_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"\n[STEP 5] Running simulation (output: {OUTPUT_DIR}) ...")

try:
    from keysight.edatoolbox import ads as edatoolbox_ads
    simulator = edatoolbox_ads.CircuitSimulator()
    t0 = time.time()
    simulator.run_netlist(netlist, output_dir=str(OUTPUT_DIR))
    elapsed = time.time() - t0
    print(f"[OK] Simulation finished in {elapsed:.1f} s")
    sim_ok = True
except Exception as e:
    print(f"[WARN] CircuitSimulator raised: {e}")
    sim_ok = False

# Fallback: hpeesofsim.exe directly
if not sim_ok:
    import subprocess
    netlist_path = OUTPUT_DIR / "design.net"
    netlist_path.write_text(netlist, encoding="utf-8")
    hpeesim = ADS_BIN / "hpeesofsim.exe"
    env = dict(os.environ)
    env["PATH"] = str(ADS_BIN) + os.pathsep + env.get("PATH", "")
    cmd = [str(hpeesim), str(netlist_path)]
    print(f"         Fallback: {cmd[0]} {netlist_path.name}")
    res = subprocess.run(cmd, capture_output=True, text=True, env=env,
                         cwd=str(OUTPUT_DIR), timeout=120)
    print(f"         Exit code: {res.returncode}")
    if res.stdout:
        print(res.stdout[:1500])
    if res.stderr:
        print(res.stderr[:400])
    sim_ok = (res.returncode == 0)

# ── 9.  Read and report results ───────────────────────────────────────────────
print("\n[STEP 6] Reading results ...")
try:
    import keysight.ads.dataset as dataset
    import numpy as np

    ds_files = list(OUTPUT_DIR.glob("*.ds"))
    if not ds_files:
        print("[WARN] No .ds file found. Output directory contents:")
        for f in OUTPUT_DIR.iterdir():
            print(f"  {f.name}")
    else:
        ds_path = ds_files[0]
        print(f"         Dataset: {ds_path.name}")
        ds = dataset.open(ds_path)

        print("\n--- AVAILABLE MEASUREMENTS ---")
        for k in ds.keys():
            print(f"  {k}")

        # Try S-param results
        sp_key = next((k for k in ds.keys() if "SP" in k.upper()), None)
        if sp_key:
            df = ds[sp_key].to_dataframe().reset_index()
            freq_col = next(c for c in df.columns if "freq" in str(c).lower())
            freqs = df[freq_col].values
            freqs_GHz = freqs / 1e9

            print(f"\n--- S-PARAMETER RESULTS ({sp_key}) ---")
            print(f"  Frequency range: {freqs_GHz[0]:.4f} GHz – {freqs_GHz[-1]:.3f} GHz")
            print(f"  Points: {len(freqs)}")
            print(f"  Columns: {[c for c in df.columns if c != freq_col]}")

            for param in ["S[2,1]", "S[1,1]", "S21", "S11"]:
                cols = [c for c in df.columns if param in str(c)]
                if not cols:
                    continue
                col = cols[0]
                vals = df[col].values
                mag_dB = 20 * np.log10(np.maximum(np.abs(vals), 1e-30))

                print(f"\n  {param} magnitude (dB) — sampled at 10 points:")
                print(f"    {'Freq (GHz)':>12}  {'|S| (dB)':>10}")
                print(f"    {'-'*26}")
                step = max(1, len(freqs_GHz) // 10)
                for i in range(0, len(freqs_GHz), step):
                    print(f"    {freqs_GHz[i]:>12.4f}  {mag_dB[i]:>10.2f}")

                if "S[2,1]" in param or "S21" in param:
                    ref = mag_dB[0]  # passband reference at lowest frequency
                    crossing = np.where(mag_dB < ref - 3.0)[0]
                    if len(crossing):
                        fc = freqs_GHz[crossing[0]]
                        print(f"\n  *** -3 dB cutoff frequency: {fc:.4f} GHz ({fc*1000:.1f} MHz) ***")
                    else:
                        print(f"\n  (No -3 dB crossing found in sweep range)")
        else:
            print("[INFO] No SP dataset found — listing raw keys above.")

except Exception as e:
    print(f"[WARN] Result reading error: {e}")
    import traceback
    traceback.print_exc()

# ── 10.  Cleanup ──────────────────────────────────────────────────────────────
print("\n[STEP 7] Closing workspace ...")
workspace.close()
print("[OK] Workspace closed.")
print("\n" + "=" * 60)
print("COMPLETE")
print("=" * 60)
