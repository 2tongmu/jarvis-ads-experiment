# ads_import_netlist.py
# Pipeline stage 3: parse (circuit)_ads_import.net --> ADS schematic
#
# Reads spdt_switch_ads_import.net and builds a complete ADS schematic:
#   - Ideal R/L/C passives via ads_rflib
#   - PDK FETs via WIN_PP1029_CPW (3-port: drain, source, gate)
#   - Gate bias networks (Rg || Cpg -> Lsg -> GND) per FET
#   - Generates netlist from schematic for opening in ADS GUI
#
# WIN_PP1029_CPW pin layout (confirmed from symbol probe):
#   bbox: (0, -0.5) to (0.68125, 0.5)
#   P1 (Drain)  at instance origin (x, y)        -- left pin
#   P2 (Source) at (x + CPW_WIDTH, y)            -- right pin
#   P3 (Gate)   at (x + CPW_WIDTH/2, y + 0.5)   -- top pin (centre)
#
# Run via ADS Python:
#   "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" ads_import_netlist.py

import sys, os, shutil, warnings, re
from pathlib import Path

ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

import numpy as np
import keysight.ads.de as de
from keysight.ads.de import db_uu as db
import keysight.ads.dataset as dataset

PDK_DIR  = Path(r"C:\Users\jarvis\ads_projects\design_kits\WIN_PP1029_DESIGN_KIT")
WRK_DIR  = Path(r"C:\Users\jarvis\ads_projects\spdt_pdk_wrk")
LIB_NAME = "spdt_switch_lib"
LIB_DIR  = WRK_DIR / LIB_NAME
NET_FILE = Path(r"C:\Users\jarvis\AppData\Local\Temp\spdt_switch_ads_import.net")

# WIN_PP1029_CPW symbol geometry (CONFIRMED from pin probe, ADS 2026)
# bbox: (0,-0.5) to (0.68125, 0.5)
# P1 = Gate   snap (0.0,   0.0)  -- left pin
# P2 = Drain  snap (0.5,  +0.5)  -- top pin
# P3 = Source snap (0.5,  -0.5)  -- bottom pin
# Netlist order: gate drain source  (P1 P2 P3)
CPW_GATE_X  = 0.0    # gate (P1) x offset from instance origin
CPW_GATE_Y  = 0.0    # gate (P1) y offset from instance origin
CPW_DRAIN_X = 0.5    # drain (P2) x offset
CPW_DRAIN_Y = 0.5    # drain (P2) y offset
CPW_SRC_X   = 0.5    # source (P3) x offset
CPW_SRC_Y   = -0.5   # source (P3) y offset

print("=" * 60)
print("SPDT Switch -- ADS Import + PDK Schematic (Stage 3)")
print("=" * 60)
print(f"Input: {NET_FILE.name}")

# ================================================================
# Step 1: Parse ads_import.net (before workspace is wiped)
# ================================================================
print("\n[1] Parsing ads_import netlist...")
netlist_src_text = NET_FILE.read_text(encoding="utf-8")

def parse_ads_import(path):
    lines  = path.read_text(encoding="utf-8").splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith(';') and '-- ' in s and '[' in s:
            m = re.match(r';\s+--\s+(\w+)\s+\[(\w+)\]\s*(.*)', s)
            if m:
                bname, btype, bdesc = m.group(1), m.group(2), m.group(3).strip()
                body = []
                i += 1
                while i < len(lines):
                    bl = lines[i].strip()
                    if bl.startswith(';') and '-- ' in bl and '[' in bl:
                        break
                    if bl and not bl.startswith(';') and not bl.startswith('#'):
                        body.append(lines[i].rstrip())
                    i += 1
                blocks.append({'name': bname, 'type': btype,
                                'desc': bdesc, 'body': body})
                continue
        i += 1
    return blocks

blocks = parse_ads_import(NET_FILE)
for b in blocks:
    print(f"  [{b['type']:16}] {b['name']:15}  {b['desc'][:48]}")

# ================================================================
# Step 2: Open or create workspace with PDK
# ================================================================
import time

if de.workspace_is_open():
    de.close_workspace()

if WRK_DIR.exists():
    print(f"\n[2] Workspace exists -- opening: {WRK_DIR}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workspace = de.open_workspace(str(WRK_DIR))

    # Delete existing cell directory on disk before opening workspace
    # (avoids lock errors if ADS GUI had it open previously)
    cell_dir = LIB_DIR / "spdt_switch"
    if cell_dir.exists():
        shutil.rmtree(str(cell_dir), ignore_errors=True)
        print(f"[2] Deleted existing cell dir: {cell_dir}")
    else:
        print(f"[2] No existing cell found -- will create fresh.")

    # Only add library if not already registered
    existing_libs = [lib.name for lib in workspace.libraries]
    if LIB_NAME not in existing_libs:
        if not LIB_DIR.exists():
            de.create_new_library(LIB_NAME, str(LIB_DIR))
        workspace.add_library(LIB_NAME, str(LIB_DIR), de.LibraryMode.SHARED)
        print(f"[2] Library '{LIB_NAME}' added.")
    else:
        print(f"[2] Library '{LIB_NAME}' already registered -- skipping.")
else:
    print(f"\n[2] Creating new workspace: {WRK_DIR}")
    workspace = de.create_workspace(str(WRK_DIR))

    # Inject PDK into lib.defs
    with open(WRK_DIR / "lib.defs", "a") as f:
        f.write(f'\nINCLUDE {PDK_DIR / "lib.defs"}\n')

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workspace.open()

    de.create_new_library(LIB_NAME, str(LIB_DIR))
    workspace.add_library(LIB_NAME, str(LIB_DIR), de.LibraryMode.SHARED)

    # Copy PDK sim config from working rf_switch workspace
    REF_WRK = Path(r"C:\Users\jarvis\ads_projects\rf_switch_design_wrk")
    for cfg in ["hpeesofsim.cfg", "de_sim.cfg"]:
        src = REF_WRK / cfg
        if src.exists():
            txt = src.read_text(encoding="utf-8")
            txt = txt.replace(str(REF_WRK), str(WRK_DIR))
            txt = txt.replace("rf_switch_design_lib:switch_design_ideal:schematic",
                              f"{LIB_NAME}:spdt_switch:schematic")
            (WRK_DIR / cfg).write_text(txt, encoding="utf-8")
    print(f"[2] PDK sim config copied.")

print(f"[2] PDK: {PDK_DIR.name}")
print(f"[2] Library '{LIB_NAME}' ready.")

# Always keep a copy of the import netlist in the workspace
(WRK_DIR / NET_FILE.name).write_text(netlist_src_text, encoding="utf-8")

# ================================================================
# Step 3: Build schematic
#
# Layout: flat, signal path along y=0 left to right.
#
# Series chain x-positions (left pin of each element):
#   0   : Term1
#   1   : Rpad_in     (right pin = 2)
#   3   : Lpad_in     (right pin = 4)  -> n2
#   5   : Ri1         (right pin = 6)
#   7   : Li1         (right pin = 8)  -> n4
#   9   : Q1a drain   (right pin = 9+CPW_WIDTH) -> n8
#   9+CPW_WIDTH+1 : Q1b drain (right pin = Q1b_x+CPW_WIDTH) -> n12
#   ... : Ro1, Lo1, Lpad_out, Rpad_out, Term2
#
# Shunt elements hang downward (y < 0).
# Gate pins of CPW FETs are at y = +CPW_GATE_Y above signal line.
# Gate bias chains (Rg||Cpg -> Lsg -> GND) hang upward from gate pin.
# ================================================================
print("\n[3] Building schematic...")
sch = db.create_schematic(f"{LIB_NAME}:spdt_switch:schematic")
tx  = de.db.Transaction(sch, "build_spdt_cpw")

# ── Helpers ───────────────────────────────────────────────────
def mkR(name, x, y, val, angle=0.0):
    i = sch.add_instance(de.LCVName("ads_rflib","R","symbol"),(x,y),name=name,angle=angle)
    i.parameters["R"].value = val;  return i

def mkL(name, x, y, val, angle=0.0):
    i = sch.add_instance(de.LCVName("ads_rflib","L","symbol"),(x,y),name=name,angle=angle)
    i.parameters["L"].value = val;  return i

def mkC(name, x, y, val, angle=-90.0):
    i = sch.add_instance(de.LCVName("ads_rflib","C","symbol"),(x,y),name=name,angle=angle)
    i.parameters["C"].value = val;  return i

def mkGnd(name, x, y):
    return sch.add_instance(de.LCVName("ads_rflib","GROUND","symbol"),
                             (x,y),name=name,angle=-90.0)

def mkTerm(name, x, y, num):
    i = sch.add_instance(de.LCVName("ads_simulation","Term","symbol"),
                         (x,y),name=name,angle=-90.0)
    i.parameters["Num"].value = str(num)
    i.parameters["Z"].value   = "50 Ohm";  return i

def mkCPW_series(name, drain_x, y, nof, ugw):
    """Series FET: angle=90, Drain at (drain_x, y), Source at (drain_x+1, y).
    Instance centre at (drain_x+0.5, y-0.5).
    Gate pin at (drain_x+0.5, y-0.5) -- below signal line."""
    cx, cy = drain_x + 0.5, y - 0.5
    i = sch.add_instance(
        de.LCVName("WIN_PP1029_DESIGN_KIT","WIN_PP1029_CPW","symbol"),
        (cx, cy), name=name, angle=90.0)
    i.parameters["NOF"].value = str(nof)
    i.parameters["UGW"].value = f"{ugw} um"
    return drain_x + 1.0   # return source x (next node)

def mkCPW_shunt(name, rf_x, y, nof, ugw):
    """Shunt FET: angle=0, Drain at (rf_x, y), Source at (rf_x, y-1).
    Instance centre at (rf_x-0.5, y-0.5).
    Gate pin at (rf_x-0.5, y-0.5) -- left of shunt column."""
    cx, cy = rf_x - 0.5, y - 0.5
    i = sch.add_instance(
        de.LCVName("WIN_PP1029_DESIGN_KIT","WIN_PP1029_CPW","symbol"),
        (cx, cy), name=name, angle=0.0)
    i.parameters["NOF"].value = str(nof)
    i.parameters["UGW"].value = f"{ugw} um"
    return (rf_x, y - 1.0)   # return source xy

def wire(pts):
    sch.add_wire(pts)

# ================================================================
# ================================================================
# LAYOUT: same as ads_build_spdt.py -- everything on y=0, left to right.
# Each block gets its own x-region with a 2-unit gap before the next.
# Shunt FETs hang downward from the signal line (drain on y=0).
# R/L placed at midpoint x: P1=(cx-0.5,y), P2=(cx+0.5,y)
# C shunt at tap x: P1=(x,0), P2=(x,-1)
# CPW series: drain at (drain_x, 0), source at (drain_x+1, 0), gate at (drain_x+0.5, -0.5)
# CPW shunt:  drain at (rf_x, 0),   source at (rf_x, -1),       gate at (rf_x-0.5, -0.5)
# ================================================================

Y = 0.0    # signal line y-coordinate (everything connects here)

# ── Term1 ────────────────────────────────────────────────────────
mkTerm("Term1", 0, Y, 1);  mkGnd("GND_t1", 0, Y-1)
wire([(0, Y), (0.5, Y)])

# ── PAD_in block: Rpad(0.05) + Lpad(10pH) + Cpad(65fF) shunt ────
# x=1: Rpad  P1=0.5, P2=1.5
# x=3: Lpad  P1=2.5, P2=3.5  (n2)
# Cpad shunt at x=3.5
mkR("Rpad_in", 1, Y, "0.05 Ohm")
mkL("Lpad_in", 3, Y, "10 pH")
mkC("Cpad_in", 3.5, Y, "65 fF");  mkGnd("GND_cpad_in", 3.5, Y-1)
wire([(1.5, Y), (2.5, Y)])    # Rpad P2 -> Lpad P1
wire([(3.5, Y), (4.5, Y)])    # n2 -> INT_in

# ── INT_in block: Ci1a shunt + Ri1 + Li1 + Ci1b shunt ───────────
# Ci1a shunt at x=4.5 (n2 tap)
# x=6: Ri1  P1=5.5, P2=6.5
# x=8: Li1  P1=7.5, P2=8.5  (n4)
# Ci1b shunt at x=8.5
mkC("Ci1a", 4.5, Y, "24 fF");  mkGnd("GND_ci1a", 4.5, Y-1)
mkR("Ri1",  6,   Y, "0.009 Ohm")
mkL("Li1",  8,   Y, "120 pH")
mkC("Ci1b", 8.5, Y, "24 fF");  mkGnd("GND_ci1b", 8.5, Y-1)
wire([(4.5, Y), (5.5, Y)])    # Ci1a -> Ri1 P1
wire([(6.5, Y), (7.5, Y)])    # Ri1 P2 -> Li1 P1
# n4 = 8.5 (Li1 P2 and Ci1b tap -- coincide, no wire needed)

# ── 2-unit gap before FETs ───────────────────────────────────────
# n4 at x=8.5, gap to x=10.5 for Q1a drain

# ── Q1a series FET: drain=10.5, source=11.5 ─────────────────────
mkCPW_series("Q1a", drain_x=10.5, y=Y, nof=2, ugw=80)
wire([(8.5, Y), (10.5, Y)])   # n4 -> Q1a drain

# ── Q3a shunt FET at x=11.5 (n8), source hangs down ─────────────
Q3a_src = mkCPW_shunt("Q3a", rf_x=11.5, y=Y, nof=2, ugw=50)
# Rtrm1 + Lrt_Q3a below Q3a source
# Q3a source at (11.5, -1.0). R/L at angle=-90: place at (x, y) gives P1=(x,y) P2=(x,y-1)
mkR("Rtrm1",   11.5, -1.75, "47 Ohm", angle=-90.0)
mkL("Lrt_Q3a", 11.5, -3.25, "25 pH",  angle=-90.0)
mkGnd("GND_sh_Q3a", 11.5, -4.25)
wire([(11.5, -1.0), (11.5, -1.75)])   # Q3a source -> Rtrm1 P1

# ── Q1b series FET: drain=11.5, source=12.5 (n8 shared with Q3a drain) ──
mkCPW_series("Q1b", drain_x=11.5, y=Y, nof=2, ugw=80)
# n8 = x=11.5 (Q1a source = Q3a drain = Q1b drain -- all on same x, y=0)
# No wire needed: Q1a source P2=(11.5,0), Q3a drain=(11.5,0), Q1b drain=(11.5,0) -- coincide

# ── Q3b shunt FET at x=12.5 (n12) ───────────────────────────────
Q3b_src = mkCPW_shunt("Q3b", rf_x=12.5, y=Y, nof=2, ugw=50)
mkR("Rtrm2",   12.5, -1.75, "47 Ohm", angle=-90.0)
mkL("Lrt_Q3b", 12.5, -3.25, "25 pH",  angle=-90.0)
mkGnd("GND_sh_Q3b", 12.5, -4.25)
wire([(12.5, -1.0), (12.5, -1.75)])

# ── 2-unit gap before output ─────────────────────────────────────
# n12 = x=12.5 (Q1b source = Q3b drain), gap to x=14.5

# ── INT_out block: Co1a shunt + Ro1 + Lo1 + Co1b shunt ──────────
# Co1a shunt at x=14.5 (n12 tap)
# x=16: Ro1  P1=15.5, P2=16.5
# x=18: Lo1  P1=17.5, P2=18.5  (n14)
# Co1b shunt at x=18.5
mkC("Co1a", 14.5, Y, "24 fF");  mkGnd("GND_co1a", 14.5, Y-1)
mkR("Ro1",  16,   Y, "0.009 Ohm")
mkL("Lo1",  18,   Y, "120 pH")
mkC("Co1b", 18.5, Y, "24 fF");  mkGnd("GND_co1b", 18.5, Y-1)
wire([(12.5, Y), (14.5, Y)])    # n12 -> Co1a/Ro1 P1
wire([(14.5, Y), (15.5, Y)])    # Co1a -> Ro1 P1
wire([(16.5, Y), (17.5, Y)])    # Ro1 P2 -> Lo1 P1
# n14 = 18.5 (Lo1 P2 and Co1b tap -- coincide)

# ── PAD_out block: Cpad shunt + Lpad + Rpad ──────────────────────
# Cpad shunt at x=18.5 (n14 tap, same as Co1b)
# x=20: Lpad  P1=19.5, P2=20.5
# x=22: Rpad  P1=21.5, P2=22.5
mkC("Cpad_out", 18.5, Y, "65 fF");  mkGnd("GND_cpad_out", 18.2, Y-1)
mkL("Lpad_out", 20,   Y, "10 pH")
mkR("Rpad_out", 22,   Y, "0.05 Ohm")
wire([(18.5, Y), (19.5, Y)])   # n14 -> Lpad P1
wire([(20.5, Y), (21.5, Y)])   # Lpad P2 -> Rpad P1

# ── Term2 ────────────────────────────────────────────────────────
mkTerm("Term2", 23.5, Y, 2);  mkGnd("GND_t2", 23.5, Y-1)
wire([(22.5, Y), (23.5, Y)])   # Rpad P2 -> Term2

# ── S_Param controller ───────────────────────────────────────────
sp = sch.add_instance(de.LCVName("ads_simulation","S_Param","symbol"),
                      (5.0, 4.0), name="SP1")
sp.parameters["Start"].value = "2 GHz"
sp.parameters["Stop"].value  = "18 GHz"
sp.parameters["Step"].value  = "50 MHz"

tx.commit()
sch.save_design()
print("[3] Schematic built and saved.")

# ================================================================
# Step 4: Generate netlist from schematic (for ADS GUI use)
# ================================================================
print("\n[4] Generating netlist from schematic...")
netlist_text = sch.generate_netlist()
ads_net = WRK_DIR / "spdt_ads_import_generated.net"
ads_net.write_text(netlist_text, encoding="utf-8")
print(f"[4] ADS-generated netlist: {ads_net.name} ({len(netlist_text.splitlines())} lines)")

print("\n[4] PDK component lines:")
for ln in netlist_text.splitlines():
    if "PP1029_CPW" in ln or "PP1029_MS" in ln:
        print(f"    {ln.strip()}")

print(f"\nADS workspace : {WRK_DIR}")
print(f"Schematic cell: {LIB_NAME}:spdt_switch:schematic")
print(f"Input netlist : {NET_FILE.name}")
print(f"Open in ADS and simulate from the schematic directly.")
print("Done.")
