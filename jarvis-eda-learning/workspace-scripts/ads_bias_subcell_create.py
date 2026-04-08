"""
ads_bias_subcell_create.py — Fixed Version with Blackbox Symbol Generation
===========================================================================

Creates a reusable bias sub-circuit cell in an ADS library with:
1. Generic circuit interface pins (not simulation ports)
2. RC topology: v_ctrl -- C1 (shunt) -- R1 -- sw_gate
3. Blackbox symbol auto-generated from schematic terms
4. Parametrized cell: Rs, Cp (user sets per instance in parent)

CRITICAL API FIXES (2026-04-08):
- Open design with DesignMode.WRITE (default is READ_ONLY)
- Call design.save_design() to persist changes to disk  
- Use design.add_term() for sub-cell pins (not ads_simulation:Term)
- Use design.add_pin_fig_for_term_type() to generate blackbox symbol

Run:
    "C:/Program Files/Keysight/ADS2026_Update1/tools/python/python.exe" ads_bias_subcell_create_fixed.py
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
from keysight.ads.de._pde.db import TermType, DesignMode

# ── Constants ──────────────────────────────────────────────────────────────────
WORKSPACE = "C:/Users/jarvis/ads_projects/spdt_switch_pdk_wrk"
LIB       = "spdt_switch_pdk_lib"
CELL      = "cell_fetbias_switch_gate"
VIEW      = "schematic"
SYMBOL    = "symbol"
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

    # ── Get design in WRITE mode ───────────────────────────────────────────────
    # CRITICAL: Must open with DesignMode.WRITE to enable persistence
    # Default is READ_ONLY which prevents save_design() from working
    print(f"\n=== Getting design context (WRITE mode) ===")
    design = sch_view.get_design(DesignMode.WRITE)
    print(f"  design: {design} (writable)")

    # ── Create circuit interface terms (pins for sub-cell) ─────────────────────
    # NOT ads_simulation:Term (those are for top-level simulation only)
    # Instead, add_term creates proper sub-cell pins
    print(f"\n=== Creating sub-cell pins (terms) ===")
    net_ctrl = design.find_or_add_net("v_ctrl")
    term_ctrl = design.add_term(net_ctrl, "v_ctrl", TermType.INPUT_OUTPUT)
    print(f"  v_ctrl term created (pin for parent schematic connection)")

    net_gate = design.find_or_add_net("sw_gate")
    term_gate = design.add_term(net_gate, "sw_gate", TermType.INPUT_OUTPUT)
    print(f"  sw_gate term created (pin for parent schematic connection)")

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
    # NOTE: With add_term, the terms are automatically connected to nets.
    # We just need to wire the components together; nets handle the connectivity.
    print(f"\n=== Adding wires (connecting components) ===")
    
    # Main signal path: v_ctrl net -> C1 -> R1 -> sw_gate net (y=0 horizontal)
    # Wires at y=0 create the main signal path
    design.add_wire([(0.0, 0.0), (2.875, 0.0), (4.25, 0.0), (6.5, 0.0)])
    print(f"  main signal path: v_ctrl -> C1 -> R1 -> sw_gate (y=0 horizontal)")

    # Shunt path: C1 bottom -> GND (vertical at x=2.875)
    design.add_wire([(2.875, 0.0), (2.875, -1.0)])
    print(f"  shunt path: C1 -> GND (vertical)")

    # ── Define design variables (cell parameters) ──────────────────────────────
    print(f"\n=== Setting design variables ===")
    design.cell.write_design_variables([
        ("Rs", "1000 Ohm"),
        ("Cp", "1 pF"),
    ])
    print(f"  Rs=1000 Ohm, Cp=1 pF (defaults)")

    # ── Save design to persist all changes ──────────────────────────────────────
    # CRITICAL: Changes only persist to disk after save_design() is called
    print(f"\n=== Saving design ===")
    design.save_design()
    print(f"  {LCV} saved to disk")

    # ── Create and populate symbol view (blackbox generation) ───────────────────
    print(f"\n=== Creating blackbox symbol ===")
    try:
        if cell.view_exists(SYMBOL):
            cell.delete_view(SYMBOL)
            print(f"  deleted existing symbol view")
        
        # Create empty symbol view
        symbol_design = db.create_symbol((LIB, CELL, SYMBOL))
        print(f"  {SYMBOL} view created")
        
        # Open symbol in WRITE mode
        sym_view = cell.view(SYMBOL)
        sym_design_write = sym_view.get_design(DesignMode.WRITE)
        
        # Generate blackbox symbol: add pin figures for each term in the schematic
        # Pin placement strategy: vertical list on left side, evenly spaced
        sch_terms = list(design.terms)
        print(f"  Found {len(sch_terms)} terms to represent as pins:")
        
        if sch_terms:
            # Calculate vertical spacing for pin placement
            y_spacing = 2.0  # Distance between pins
            y_start = (len(sch_terms) - 1) * y_spacing / 2.0  # Center vertically
            
            for idx, term in enumerate(sch_terms):
                y_pos = y_start - (idx * y_spacing)
                # Place pins on the left edge (x=0) of symbol
                pin_fig = sym_design_write.add_pin_fig_for_term_type(
                    term.term_type,
                    (0.0, y_pos)
                )
                print(f"    {term.name}: pin at (0.0, {y_pos})")
        
        # Save symbol with pin figures
        sym_design_write.save_design()
        print(f"  {SYMBOL} saved with blackbox pin figures")
        
    except Exception as e:
        print(f"  ERROR: Could not create blackbox symbol: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n=== Done ===")
    print(f"  Cell: {LCV}")
    print(f"  Pins: v_ctrl -> sw_gate (circuit interface terms)")
    print(f"  Parameters: Rs (default 1000 Ohm), Cp (default 1 pF)")
    print(f"  Symbol: {SYMBOL} view created with blackbox pin figures")


if __name__ == "__main__":
    main()
