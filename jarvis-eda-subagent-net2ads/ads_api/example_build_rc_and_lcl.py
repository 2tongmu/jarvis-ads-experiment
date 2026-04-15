"""
ads_api/example_build_rc_and_lcl.py
=====================================
Usage example: build ADS schematic cells for both Phase 1 circuits.

Demonstrates the complete ads_api layer for:
  1. rc_series_shunt  — R series + C shunt
  2. t_network_lcl    — L-C-L T-network (low-pass filter)

Run with the ADS-bundled Python interpreter:
  "C:\\Program Files\\Keysight\\ADS2026_Update1\\tools\\python\\python.exe" ^
      ads_api/example_build_rc_and_lcl.py --workspace C:\\path\\to\\workspace

Add --dry-run to check the flow without touching ADS.

Coordinate reference (all confirmed from net_to_ads_cell.py / ads_bias_subcell_create.py):
  Port 1 (left)    x = 1.375
  First shunt      x = 2.875, y = 0.0;  GND at y = -1.0
  First series     x = 4.25,  y = 0.0
  Port 2 (right)   x = 5.25  (for 1-shunt + 1-series topology)

Angles:
  R / L series:  0.0   (horizontal)
  C shunt:      -90.0  (vertical, pin1 at top — confirmed ads_build_spdt_pdk.py)
  GND:          -90.0  (confirmed)
"""

import argparse
import sys

# ── CLI ────────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Build Phase 1 ADS cells via ads_api layer.")
parser.add_argument("--workspace", required=True, help="Path to ADS workspace directory")
parser.add_argument("--library",   default="net2ads_lib", help="Target library name")
parser.add_argument("--lib-path",  default=None, help="Library directory (for creation)")
parser.add_argument("--dry-run",   action="store_true",
                    help="Print plan without calling ADS API")
args = parser.parse_args()

WORKSPACE = args.workspace
LIB_NAME  = args.library
LIB_PATH  = args.lib_path or f"{WORKSPACE}/{LIB_NAME}"
DRY_RUN   = args.dry_run

# ── Dry-run guard ──────────────────────────────────────────────────────────────
if DRY_RUN:
    print("=" * 62)
    print("DRY-RUN MODE — no ADS calls will be made")
    print(f"  workspace : {WORKSPACE}")
    print(f"  library   : {LIB_NAME}")
    print("=" * 62)
    print()
    print("Would build:")
    print("  [1] rc_series_shunt")
    print("      R1_SER  R=50 Ohm    @ (4.25,  0.0) angle=0")
    print("      C1_SH   C=2.0 pF   @ (2.875, 0.0) angle=-90")
    print("      GND     GROUND      @ (2.875,-1.0) angle=-90")
    print("      ports: P1@(1.375,0) P2@(5.25,0)")
    print("      wire: [(1.375,0),(2.875,0)]  P1 -> C1_SH tap")
    print("      wire: [(2.875,0),(4.25,0)]   C1_SH tap -> R1_SER.P1")
    print("      note: R1_SER.P2(5.25) co-locates with P2(5.25) — no wire needed")
    print("      note: GND wire drawn by place_ground() — no explicit shunt wire")
    print()
    print("  [2] t_network_lcl")
    print("      C1_SH   C=1.2 pF   @ (2.875, 0.0) angle=-90")
    print("      L1_SER  L=3.3 nH   @ (4.25,  0.0) angle=0")
    print("      L2_SER  L=3.3 nH   @ (6.25,  0.0) angle=0")
    print("      GND     GROUND      @ (2.875,-1.0) angle=-90")
    print("      ports: P1@(1.375,0) P2@(7.25,0)")
    print("      wire: [(1.375,0),(2.875,0)]  P1 -> C1_SH tap")
    print("      wire: [(2.875,0),(4.25,0)]   C1_SH tap -> L1_SER.P1")
    print("      wire: [(5.25,0),(6.25,0)]    L1_SER.P2 -> L2_SER.P1")
    print("      note: L2_SER.P2(7.25) co-locates with P2(7.25) — no wire needed")
    print("      note: GND wire drawn by place_ground() — no explicit shunt wire")
    sys.exit(0)

# ── ADS session ────────────────────────────────────────────────────────────────
from ads_api.ads_session import get_ads_session
from ads_api.workspace_ops import open_or_create_workspace, ensure_library
from ads_api.cell_ops import open_or_create_schematic, save_design
from ads_api.schematic_ops import (
    place_port, place_ground,
    place_resistor, place_capacitor, place_inductor,
    connect,
)
from ads_api.symbol_ops import create_basic_symbol

session = get_ads_session()
ws  = open_or_create_workspace(session, WORKSPACE)
lib = ensure_library(session, LIB_NAME, LIB_PATH)

# ══════════════════════════════════════════════════════════════════════════════
# Circuit 1: rc_series_shunt
#
# Topology:
#   P1 ── R1_SER ── N_OUT ── P2
#                   │
#                  C1_SH
#                   │
#                  GND
#
# Coordinates:
#   P1:       x=1.375, y=0
#   C1_SH:    x=2.875, y=0  (shunt first, to the left of series)
#   GND:      x=2.875, y=-1
#   R1_SER:   x=4.25,  y=0
#   P2:       x=5.25,  y=0
# ══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 62)
print("Building: rc_series_shunt")
print("=" * 62)

cell_rc, design_rc = open_or_create_schematic(session, lib, "rc_series_shunt")

place_port(session, design_rc, "P1", x=1.375, y=0.0)
place_port(session, design_rc, "P2", x=5.25,  y=0.0)

place_capacitor(session, design_rc, "C1_SH",  value="2.0 pF", x=2.875, y=0.0,  angle=-90.0)
place_ground   (session, design_rc, "GND_C1", x=2.875,        y=-1.0)
place_resistor (session, design_rc, "R1_SER", value="50 Ohm", x=4.25,  y=0.0,  angle=0.0)

# Signal path — separate segments (ADS connects pins only at wire ENDPOINTS):
#   P1_port → C1_SH.P1 tap
connect(design_rc, [(1.375, 0.0), (2.875, 0.0)])
#   C1_SH.P1 tap → R1_SER.P1
connect(design_rc, [(2.875, 0.0), (4.25, 0.0)])
# R1_SER.P2 (5.25) co-locates with P2 port (5.25) — no wire needed.
# GND wire from C1_SH.P2 to GND.P1 is drawn by place_ground() — no explicit shunt wire here.

save_design(design_rc)
create_basic_symbol(session, lib, LIB_NAME, cell_rc, "rc_series_shunt", design_rc)
print("rc_series_shunt: DONE")


# ══════════════════════════════════════════════════════════════════════════════
# Circuit 2: t_network_lcl
#
# Topology:
#   P1 ── L1_SER ── N_MID ── L2_SER ── P2
#                    │
#                   C1_SH
#                    │
#                   GND
#
# Coordinates:
#   P1:       x=1.375, y=0
#   C1_SH:    x=2.875, y=0  (shunt at midpoint)
#   GND:      x=2.875, y=-1
#   L1_SER:   x=4.25,  y=0  (first series, to the right of shunt)
#   L2_SER:   x=6.25,  y=0  (second series, +2.0 units)
#   P2:       x=7.25,  y=0
#
# ══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 62)
print("Building: t_network_lcl")
print("=" * 62)

cell_lcl, design_lcl = open_or_create_schematic(session, lib, "t_network_lcl")

place_port(session, design_lcl, "P1", x=1.375, y=0.0)
place_port(session, design_lcl, "P2", x=7.25,  y=0.0)

place_capacitor(session, design_lcl, "C1_SH",  value="1.2 pF", x=2.875, y=0.0, angle=-90.0)
place_ground   (session, design_lcl, "GND_C1", x=2.875,         y=-1.0)

place_inductor(session, design_lcl, "L1_SER", value="3.3 nH", x=4.25, y=0.0, angle=0.0)
place_inductor(session, design_lcl, "L2_SER", value="3.3 nH", x=6.25, y=0.0, angle=0.0)

# Signal path — separate segments (ADS connects pins only at wire ENDPOINTS):
#   P1_port → C1_SH.P1 tap
connect(design_lcl, [(1.375, 0.0), (2.875, 0.0)])
#   C1_SH.P1 tap → L1_SER.P1
connect(design_lcl, [(2.875, 0.0), (4.25, 0.0)])
#   L1_SER.P2 → L2_SER.P1
connect(design_lcl, [(5.25, 0.0), (6.25, 0.0)])
# L2_SER.P2 (7.25) co-locates with P2 port (7.25) — no wire needed.
# GND wire from C1_SH.P2 to GND.P1 is drawn by place_ground() — no explicit shunt wire here.

save_design(design_lcl)
create_basic_symbol(session, lib, LIB_NAME, cell_lcl, "t_network_lcl", design_lcl)
print("t_network_lcl: DONE")


# ══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 62)
print("ALL DONE")
print(f"  {LIB_NAME}:rc_series_shunt:schematic  ✅")
print(f"  {LIB_NAME}:rc_series_shunt:symbol     ✅")
print(f"  {LIB_NAME}:t_network_lcl:schematic    ✅")
print(f"  {LIB_NAME}:t_network_lcl:symbol       ✅")
print()
print("Next: open ADS GUI and verify schematics visually.")
print("      Confirm ads_rflib:L:symbol works — update MEMORY.md OI-02.")
print("=" * 62)
