"""
ads_bias_subcell_create.py
==========================
Unified cell creation flow — Step 4: Create ADS Cell
Reference implementation for bias network (RC topology, no PDK translation).

Unified flow:
    Step 1  .net input         — topology defined as generated .net (simple RC, no PDK)
    Step 2  Pre-process        — parse .net, extract components, values, connectivity
    Step 3  PDK translation    — skipped for bias network (generic R/C only)
  > Step 4  Create ADS cell    — this script; de Python API (keysight.ads.de)
    Step 5  Hierarchy          — SPDT cell will instantiate this cell
    Step 6  Simulation         — separate simulation template cell (not baked in here)

Cell created: cell_fetbias_switch_gate in spdt_switch_pdk_lib
Topology:
    v_ctrl (pin) ── C1 (shunt to GND) ── R1 ── sw_gate (pin)
    Rs default 1000 Ohm, Cp default 1 pF

REWRITTEN 2026-04-08: Proper Python API (keysight.ads.de), no AEL bridge functions.

Run on Jarvis:
    "C:/Program Files/Keysight/ADS2026_Update1/tools/python/python.exe" workspace-scripts/ads_bias_subcell_create.py
"""

import sys
import warnings
from pathlib import Path

# ── ADS Python environment ─────────────────────────────────────────────────────
ADS_DIR = Path("C:/Program Files/Keysight/ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))

import os
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

import keysight.ads.de as de
from keysight.ads.de import db_uu as db

# ── Constants ──────────────────────────────────────────────────────────────────
WORKSPACE = "C:/Users/jarvis/ads_projects/spdt_switch_pdk_wrk"
LIB       = "spdt_switch_pdk_lib"
CELL      = "cell_fetbias_switch_gate"
VIEW      = "schematic"
LCV       = f"{LIB}:{CELL}:{VIEW}"


def main():
    # ── Open existing workspace ────────────────────────────────────────────────
    print("=== Opening workspace ===")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # suppress benign vtb.defs / SystemVue warnings
        ws = de.open_workspace(WORKSPACE)
    print(f"  {ws}")

    # ── Get library and cell ───────────────────────────────────────────────────
    print("\n=== Getting library and cell ===")
    lib = de.get_open_library(LIB)
    
    # Create cell if it doesn't exist
    if lib.cell_exists(CELL):
        cell = lib.cell(CELL)
        print(f"  cell exists: {CELL}")
    else:
        print(f"  creating new cell: {CELL}")
        cell = de.Cell.create(lib, CELL)
    print(f"  cell: {cell}")

    # ── Create or get schematic view ───────────────────────────────────────────
    print(f"\n=== Creating/getting schematic view: {LCV} ===")
    if cell.view_exists(VIEW):
        # Delete and recreate to start fresh
        cell.delete_view(VIEW)
        print(f"  deleted existing view")
    sch_view = de.View.create(cell, VIEW, "schematic")
    print(f"  created: {LCV}")

    # ── Get design ─────────────────────────────────────────────────────────────
    print(f"\n=== Getting design context ===")
    design = sch_view.get_design()
    print(f"  design: {design}")

    # ── Start transaction ──────────────────────────────────────────────────────
    print(f"\n=== Starting transaction ===")
    tx = de.db.Transaction(design, "build_fetbias_cell")

    # ── Create two Port symbols (pins): v_ctrl and sw_gate ─────────────────────
    print(f"\n=== Creating Port pins ===")
    port_ctrl = design.add_instance(de.LCVName("ads_simulation", "Term", "symbol"),
                                    (1.375, 0.0), name="PORT_CTRL", angle=180.0)
    port_ctrl.parameters["Num"].value = "1"
    print(f"  PORT_CTRL at (1.375, 0.0)")

    port_gate = design.add_instance(de.LCVName("ads_simulation", "Term", "symbol"),
                                    (5.25, 0.0), name="PORT_GATE", angle=0.0)
    port_gate.parameters["Num"].value = "2"
    print(f"  PORT_GATE at (5.25, 0.0)")

    # ── Place C1 (shunt capacitor) ─────────────────────────────────────────────
    print(f"\n=== Placing C1 (capacitor, shunt) ===")
    c1 = design.add_instance(de.LCVName("ads_rflib", "C", "symbol"),
                             (2.875, 0.0), name="C1", angle=-90.0)
    c1.parameters["C"].value = "Cp"
    print(f"  C1 at (2.875, 0.0), angle=-90 (shunt), C=Cp")

    # ── Place GND below C1 ─────────────────────────────────────────────────────
    print(f"\n=== Placing GND ===")
    gnd = design.add_instance(de.LCVName("ads_rflib", "GROUND", "symbol"),
                              (2.875, -1.0), name="GND", angle=-90.0)
    print(f"  GND at (2.875, -1.0)")

    # ── Place R1 (series resistor, horizontal) ────────────────────────────────
    print(f"\n=== Placing R1 (resistor, series) ===")
    r1 = design.add_instance(de.LCVName("ads_rflib", "R", "symbol"),
                             (4.25, 0.0), name="R1", angle=0.0)
    r1.parameters["R"].value = "Rs"
    print(f"  R1 at (4.25, 0.0), angle=0 (horizontal), R=Rs")

    # ── Add wires ──────────────────────────────────────────────────────────────
    print(f"\n=== Adding wires ===")
    # Main path: PORT_CTRL -> C1 -> R1 -> PORT_GATE (y=0 horizontal)
    design.add_wire([(1.375, 0.0), (2.875, 0.0), (4.25, 0.0), (5.25, 0.0)])
    print(f"  main signal path: v_ctrl -> C1 -> R1 -> sw_gate")

    # Shunt path: C1 bottom -> GND (vertical at x=2.875)
    design.add_wire([(2.875, 0.0), (2.875, -1.0)])
    print(f"  shunt path: C1 -> GND")

    # ── Define design variables (cell parameters) ──────────────────────────────
    print(f"\n=== Setting design variables ===")
    design.cell.write_design_variables([
        ("Rs", "1000 Ohm"),
        ("Cp", "1 pF"),
    ])
    print(f"  Rs=1000 Ohm, Cp=1 pF (defaults)")

    # ── Commit transaction ────────────────────────────────────────────────────
    print(f"\n=== Committing transaction ===")
    tx.commit()
    print(f"  transaction committed")
    
    # ── Save design ────────────────────────────────────────────────────────────
    print(f"\n=== Saving design ===")
    try:
        design.save_design()
        print(f"  {LCV} saved")
    except RuntimeError as e:
        if "read-only" in str(e):
            print(f"  WARNING: Design is read-only after commit (expected in some ADS versions)")
            print(f"  Data should be saved via transaction; proceeding without explicit save")
        else:
            raise

    print(f"\n=== Done ===")
    print(f"  Cell: {LCV}")
    print(f"  Ports: v_ctrl (Num=1) -> sw_gate (Num=2)")
    print(f"  Parameters: Rs (default 1000 Ohm), Cp (default 1 pF)")


if __name__ == "__main__":
    main()
