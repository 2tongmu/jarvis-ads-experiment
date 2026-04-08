r"""
ads_build_spdt_pdk.py
=====================
Build SPDT switch ADS schematic using WIN_PP1029_DESIGN_KIT PDK FET components.
Phase 1: Schematic generation only — NO simulation.

PDK FET: WIN_PP1029_CPW in library WIN_PP1029_DESIGN_KIT
  pin1 = gate, pin2 = drain, pin3 = source

PIN POSITIONS (verified via snap_point probing):
  angle=0:   gate=(0,0), drain=(+0.5,+0.5), source=(+0.5,-0.5)
  angle=90:  gate=(0,0), drain=(-0.5,+0.5), source=(+0.5,+0.5)

SERIES FET orientation (signal path on y=0):
  Place at (x, -0.5), angle=90:
    gate   = (x,      -0.5)    <- gate bias stub
    drain  = (x-0.5,  +0.0)    <- signal in  (left)
    source = (x+0.5,  +0.0)    <- signal out (right)

SHUNT FET orientation (drain at signal tap, source to GND chain):
  Place at (node_x-0.5, -0.5), angle=0:
    gate   = (node_x-0.5,  -0.5)    <- gate bias stub
    drain  = (node_x,      +0.0)    <- signal tap
    source = (node_x,      -1.0)    <- to GND chain (Rtrm → Lrt → GND)

Run with ADS Python:
  "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" ads_build_spdt_pdk.py
"""

import sys, os, shutil, warnings
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
NET_OUT  = WRK_DIR / "spdt_switch_ads_generated.net"

print("=" * 62)
print("SPDT Switch PDK Build -- Phase 1: Schematic Only")
print("=" * 62)

# ── Step 1: Create workspace ──────────────────────────────────────────────────
print(f"[1] Creating workspace: {WRK_DIR}")
shutil.rmtree(str(WRK_DIR), ignore_errors=True)
if de.workspace_is_open():
    de.close_workspace()

workspace = de.create_workspace(str(WRK_DIR))

pdk_lib_defs  = PDK_DIR / "lib.defs"
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

# ── Step 2: Build schematic ───────────────────────────────────────────────────
print("[2] Building schematic...")
sch = db.create_schematic(f"{LIB_NAME}:spdt_switch:schematic")
tx  = de.db.Transaction(sch, "build_spdt_pdk")

# ── Component factory helpers ─────────────────────────────────────────────────
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

# ── PDK FET helper ────────────────────────────────────────────────────────────
# Cell: WIN_PP1029_CPW in WIN_PP1029_DESIGN_KIT
# Parameters: NOF, UGW (um), Temp, NOISE, S_Deb
def mkFET_CPW_series(name, x_drain, nof, ugw):
    """
    Place series FET (signal path at y=0).
    origin = (x_drain+0.5, -0.5), angle=90
    Pins: drain=(x_drain, 0), source=(x_drain+1, 0), gate=(x_drain+0.5, -0.5)
    Returns dict with pin positions.
    """
    orig_x = x_drain + 0.5
    orig_y = -0.5
    i = sch.add_instance(
        de.LCVName("WIN_PP1029_DESIGN_KIT", "WIN_PP1029_CPW", "symbol"),
        (orig_x, orig_y), name=name, angle=90.0)
    i.parameters["NOF"].value  = str(nof)
    i.parameters["UGW"].value  = f"{ugw} um"
    i.parameters["Temp"].value = "25"
    i.parameters["NOISE"].value= "1"
    i.parameters["S_Deb"].value= "1"
    return {
        "gate":   (orig_x,         orig_y),        # (x_drain+0.5, -0.5)
        "drain":  (orig_x - 0.5,   orig_y + 0.5),  # (x_drain,     0.0)
        "source": (orig_x + 0.5,   orig_y + 0.5),  # (x_drain+1.0, 0.0)
    }

def mkFET_CPW_shunt(name, node_x, nof, ugw):
    """
    Place shunt FET (drain at signal tap node_x, source to GND chain).
    origin = (node_x-0.5, -0.5), angle=0
    Pins: gate=(node_x-0.5, -0.5), drain=(node_x, 0), source=(node_x, -1.0)
    Returns dict with pin positions.
    """
    orig_x = node_x - 0.5
    orig_y = -0.5
    i = sch.add_instance(
        de.LCVName("WIN_PP1029_DESIGN_KIT", "WIN_PP1029_CPW", "symbol"),
        (orig_x, orig_y), name=name, angle=0.0)
    i.parameters["NOF"].value  = str(nof)
    i.parameters["UGW"].value  = f"{ugw} um"
    i.parameters["Temp"].value = "25"
    i.parameters["NOISE"].value= "1"
    i.parameters["S_Deb"].value= "1"
    return {
        "gate":   (orig_x,        orig_y),         # (node_x-0.5, -0.5)
        "drain":  (orig_x + 0.5,  orig_y + 0.5),   # (node_x,     0.0)
        "source": (orig_x + 0.5,  orig_y - 0.5),   # (node_x,    -1.0)
    }

def gate_stub(stub_name, gate_pos, resistor_name="10000 Ohm"):
    """Hang a 10 kOhm gate stub downward from gate pin → GND."""
    gx, gy = gate_pos
    # Resistor: P1 at gate, P2 at gy-1
    mkR(stub_name, gx, gy - 0.5, resistor_name, angle=-90.0)
    mkGnd(f"GND_{stub_name}", gx, gy - 1.5)
    wire([(gx, gy), (gx, gy - 0.5)])

# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT: Signal path along y=0, x increasing left→right
#
#  x:  0   1.5─2.5  3─4  4─5  6─7  7─8   8─9.5
#      T1  Rpad_in  Lpad  --  Ri1  Li1   n4
#                           n2 shunts   n4 shunt
#
#  Q1a drain=9.5  series  source=10.5 (n8 start)
#
#  n8: (10.5→13.0) -- Q3a drain hangs at 11.5
#  Q3a at node_x=11.5, shunt
#
#  Q1b drain=13.0  series  source=14.0 (n12 start)
#
#  n12: (14.0→16.0) -- Q3b drain hangs at 15.0
#  Q3b at node_x=15.0, shunt
#
#  Co1a at 15.5, then INT_out: Ro1, Lo1
#  PAD_out: Co1b, Cpad_out, Lpad_out, Rpad_out → Term2
# ═══════════════════════════════════════════════════════════════════════════════

# ── Ports ─────────────────────────────────────────────────────────────────────
mkTerm("Term1",  0.0, 0.0, 1);   mkGnd("GND_t1",  0.0, -1.0)
mkTerm("Term2", 27.0, 0.0, 2);   mkGnd("GND_t2", 27.0, -1.0)

# ── PAD_in: P1→n1→n2 ─────────────────────────────────────────────────────────
mkR("Rpad_in", 1.5, 0.0, "0.05 Ohm")          # P1=1.5, P2=2.5
mkL("Lpad_in", 3.0, 0.0, "10 pH")              # P1=3.0, P2=4.0
wire([(0.0, 0.0), (1.5, 0.0)])                  # Term1 → Rpad_in.P1
wire([(2.5, 0.0), (3.0, 0.0)])                  # n1: Rpad_in.P2 → Lpad_in.P1
# n2 = x=4.0, shunts:
mkC("Cpad_in", 4.2, 0.0, "65 fF");  mkGnd("GND_cpad_in", 4.2, -1.0)
mkC("Ci1a",    4.6, 0.0, "24 fF");  mkGnd("GND_ci1a",    4.6, -1.0)

# ── INT_in: n2→n3→n4 ─────────────────────────────────────────────────────────
mkR("Ri1", 5.0, 0.0, "0.009 Ohm")             # P1=5.0, P2=6.0
mkL("Li1", 7.0, 0.0, "120 pH")                # P1=7.0, P2=8.0
wire([(4.0, 0.0), (5.0, 0.0)])                 # n2: Lpad_in.P2 → Ri1.P1
wire([(6.0, 0.0), (7.0, 0.0)])                 # n3: Ri1.P2 → Li1.P1
# n4 = x=8.0, shunt:
mkC("Ci1b", 8.3, 0.0, "24 fF");  mkGnd("GND_ci1b", 8.3, -1.0)
wire([(8.0, 0.0), (9.5, 0.0)])                 # extend n4 to Q1a drain

# ── Q1a: series, drain=9.5, source=10.5 ──────────────────────────────────────
# origin=(10.0,-0.5), angle=90: drain=(9.5,0), source=(10.5,0), gate=(10.0,-0.5)
print("[2] Placing Q1a (series, NOF=2, UGW=80um)...")
q1a = mkFET_CPW_series("Q1a", x_drain=9.5, nof=2, ugw=80)
print(f"    Q1a: {q1a}")
gate_stub("Rg_Q1a_stub", q1a["gate"])

# ── Q3a: shunt at n8 (node_x=11.5) ──────────────────────────────────────────
# n8 runs from Q1a.source=(10.5,0) to Q1b.drain=(13.0,0)
# Q3a drain taps n8 at x=11.5: origin=(11.0,-0.5), angle=0
print("[2] Placing Q3a (shunt, NOF=2, UGW=50um)...")
q3a = mkFET_CPW_shunt("Q3a", node_x=11.5, nof=2, ugw=50)
print(f"    Q3a: {q3a}")
gate_stub("Rg_Q3a_stub", q3a["gate"])
# Q3a source → Rtrm1 → Lrt_Q3a → GND (vertical chain below source)
q3a_src = q3a["source"]   # (11.5, -1.0)
mkR("Rtrm1",   q3a_src[0], q3a_src[1],        "47 Ohm", angle=-90.0)   # P1=(11.5,-1.0), P2=(11.5,-2.0)
mkL("Lrt_Q3a", q3a_src[0], q3a_src[1] - 1.0, "25 pH",  angle=-90.0)   # P1=(11.5,-2.0), P2=(11.5,-3.0)
mkGnd("GND_q3a_src", q3a_src[0], q3a_src[1] - 2.0)

# ── Q1b: series, drain=13.0, source=14.0 ─────────────────────────────────────
# origin=(13.5,-0.5), angle=90: drain=(13.0,0), source=(14.0,0), gate=(13.5,-0.5)
print("[2] Placing Q1b (series, NOF=2, UGW=80um)...")
q1b = mkFET_CPW_series("Q1b", x_drain=13.0, nof=2, ugw=80)
print(f"    Q1b: {q1b}")
gate_stub("Rg_Q1b_stub", q1b["gate"])
# Wire n8: Q1a.source → (spans Q3a drain at 11.5) → Q1b.drain
wire([(q1a["source"][0], 0.0), (q1b["drain"][0], 0.0)])   # (10.5,0)→(13.0,0)

# ── Q3b: shunt at n12 (node_x=15.0) ─────────────────────────────────────────
print("[2] Placing Q3b (shunt, NOF=2, UGW=50um)...")
q3b = mkFET_CPW_shunt("Q3b", node_x=15.0, nof=2, ugw=50)
print(f"    Q3b: {q3b}")
gate_stub("Rg_Q3b_stub", q3b["gate"])
# Q3b source → Rtrm2 → Lrt_Q3b → GND
q3b_src = q3b["source"]   # (15.0, -1.0)
mkR("Rtrm2",   q3b_src[0], q3b_src[1],        "47 Ohm", angle=-90.0)
mkL("Lrt_Q3b", q3b_src[0], q3b_src[1] - 1.0, "25 pH",  angle=-90.0)
mkGnd("GND_q3b_src", q3b_src[0], q3b_src[1] - 2.0)
# Wire n12: Q1b.source → (spans Q3b drain at 15.0) → continue to Co1a
wire([(q1b["source"][0], 0.0), (15.5, 0.0)])   # (14.0,0)→(15.5,0) -- Q3b drain at 15.0 on this path

# ── Co1a shunt at n12 ─────────────────────────────────────────────────────────
mkC("Co1a", 15.5, 0.0, "24 fF");  mkGnd("GND_co1a", 15.5, -1.0)

# ── INT_out: n12→n13→n14 ─────────────────────────────────────────────────────
mkR("Ro1", 16.5, 0.0, "0.009 Ohm")      # P1=16.5, P2=17.5
mkL("Lo1", 18.5, 0.0, "120 pH")          # P1=18.5, P2=19.5  (=n14)
wire([(15.5, 0.0), (16.5, 0.0)])          # Co1a → Ro1
wire([(17.5, 0.0), (18.5, 0.0)])          # n13: Ro1.P2 → Lo1.P1

# ── PAD_out: n14→n15→P2 ──────────────────────────────────────────────────────
# n14 = Lo1.P2 = x=19.5, shunts:
mkC("Co1b",    19.8, 0.0, "24 fF");  mkGnd("GND_co1b",    19.8, -1.0)
mkC("Cpad_out",20.2, 0.0, "65 fF");  mkGnd("GND_cpad_out",20.2, -1.0)
mkL("Lpad_out",21.0, 0.0, "10 pH")   # P1=21.0, P2=22.0
mkR("Rpad_out",23.0, 0.0, "0.05 Ohm")  # P1=23.0, P2=24.0
wire([(19.5, 0.0), (21.0, 0.0)])          # n14: Lo1.P2 → Lpad_out.P1
wire([(22.0, 0.0), (23.0, 0.0)])          # n15: Lpad_out.P2 → Rpad_out.P1
wire([(24.0, 0.0), (27.0, 0.0)])          # Rpad_out.P2 → Term2

# ── S_Param controller ────────────────────────────────────────────────────────
sp = sch.add_instance(de.LCVName("ads_simulation","S_Param","symbol"),
                      (5.0, 5.0), name="SP1")
sp.parameters["Start"].value = "2 GHz"
sp.parameters["Stop"].value  = "18 GHz"
sp.parameters["Step"].value  = "50 MHz"

tx.commit()
sch.save_design()
print("[2] Schematic committed and saved.")

# ── Step 3: Connectivity probe ────────────────────────────────────────────────
print("\n[3] Connectivity probe (all instances):")
for inst in sch.instances:
    it_list = list(inst.get_inst_term_iter())
    nets = []
    for it in it_list:
        try:
            net_name = it.net.name if it.net else "OPEN"
        except Exception:
            net_name = "?"
        try:
            tnum = it.term_number
        except Exception:
            tnum = "?"
        nets.append(f"pin{tnum}={net_name}")
    print(f"  {inst.name:18s}  {' | '.join(nets)}")

# ── Step 4: Generate netlist ──────────────────────────────────────────────────
print("\n[4] Generating ADS netlist...")
netlist_text = sch.generate_netlist()
lines = netlist_text.splitlines()
print(f"    {len(lines)} lines generated.")

NET_OUT.write_text(netlist_text, encoding="utf-8")
print(f"[4] Netlist saved: {NET_OUT}")

# Print first 40 lines
print("\n--- Generated Netlist (first 40 lines) ---")
for ln in lines[:40]:
    print(f"  {ln}")
if len(lines) > 40:
    print(f"  ... ({len(lines) - 40} more lines)")
print("--- End ---")

print("\n" + "=" * 62)
print("PHASE 1 COMPLETE")
print(f"  Workspace : {WRK_DIR}")
print(f"  Library   : {LIB_NAME}")
print(f"  Cell      : spdt_switch:schematic")
print(f"  Netlist   : {NET_OUT}")
print("  Next: copy netlist to WSL and run schematic checker.")
print("=" * 62)
