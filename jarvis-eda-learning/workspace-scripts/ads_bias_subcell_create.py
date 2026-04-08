"""
ads_bias_subcell_create.py
==========================
Unified cell creation flow — Step 4: Create ADS Cell
Reference implementation for bias network (RC topology, no PDK translation).

Unified flow (see workspace-scripts/WORKFLOW.md for full architecture):
    Step 1  .net input         — topology defined as generated .net (simple RC, no PDK)
    Step 2  Pre-process        — parse .net, extract components, values, connectivity
    Step 3  PDK translation    — skipped for bias network (generic R/C only)
  > Step 4  Create ADS cell    — this script; de_ API from .dem ground truth
    Step 5  Hierarchy          — SPDT cell will instantiate this cell via de_init_item
    Step 6  Simulation         — separate simulation template cell (not baked in here)

Cell created: cell_fetbias_switch_gate in spdt_switch_pdk_lib
Topology:
    v_ctrl (pin) ── C1 (shunt to GND) ── R1 ── sw_gate (pin)
    Rs default 1000 Ohm, Cp default 1 pF

Run on Jarvis:
    "C:/Program Files/Keysight/ADS2026_Update1/tools/python/python.exe" workspace-scripts/ads_bias_subcell_create.py
"""

import sys
from pathlib import Path

# ── ADS Python environment ─────────────────────────────────────────────────────
ADS_DIR = Path("C:/Program Files/Keysight/ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))

import keysight.ads.de as de

# ── Constants ──────────────────────────────────────────────────────────────────
WORKSPACE = "C:/Users/jarvis/ads_projects/spdt_switch_pdk_wrk"
LIB       = "spdt_switch_pdk_lib"
CELL      = "cell_fetbias_switch_gate"
VIEW      = "schematic"
LCV       = f"{LIB}:{CELL}:{VIEW}"


def main():
    # ── Open existing workspace ────────────────────────────────────────────────
    print("=== Opening workspace ===")
    ws = de.open_workspace(WORKSPACE)
    print(f"  {ws}")

    # ── Create schematic view ──────────────────────────────────────────────────
    print("\n=== Creating schematic view ===")
    de.de_create_new_schematic_view(LIB, CELL, VIEW)
    print(f"  created: {LCV}")

    # ── Get design context ─────────────────────────────────────────────────────
    print("\n=== Getting design context ===")
    ctx = de.de_get_design_context_from_name(LCV)
    print(f"  context: {ctx}")

    # ── Place C1 (shunt capacitor, rotated) ───────────────────────────────────
    print("\n=== Placing C1 at (2.875, 0) ===")
    c1 = de.de_init_item("ads_rflib:C:symbol")
    de.de_rotate_inc()
    de.de_place_item(c1, 2.875, 0.0)
    print("  C1 placed")

    # ── Place GND below C1 ────────────────────────────────────────────────────
    print("\n=== Placing GND at (2.875, -1) ===")
    gnd = de.de_init_item("ads_rflib:GROUND:symbol")
    de.de_rotate_image("DOWN")
    de.de_place_item(gnd, 2.875, -1.0)
    print("  GND placed")

    # ── Place R1 (series resistor) ────────────────────────────────────────────
    print("\n=== Placing R1 at (4.25, 0) ===")
    r1 = de.de_init_item("ads_rflib:R:symbol")
    de.de_place_item(r1, 4.25, 0.0)
    print("  R1 placed")

    # ── Create pin: v_ctrl ────────────────────────────────────────────────────
    print("\n=== Creating pin v_ctrl at (1.375, 0) rotation=180 ===")
    de.db_create_pin(ctx, 1.375, 0.0, 180, de.db_layerid(229), 0, "v_ctrl", 2)
    print("  v_ctrl pin created")

    # ── Create pin: sw_gate ───────────────────────────────────────────────────
    print("\n=== Creating pin sw_gate at (5.25, 0) rotation=0 ===")
    de.db_create_pin(ctx, 5.25, 0.0, 0, de.db_layerid(229), 0, "sw_gate", 2)
    print("  sw_gate pin created")

    # ── Wires ─────────────────────────────────────────────────────────────────
    # Main signal path: v_ctrl → C1 → R1 → sw_gate (horizontal at y=0)
    print("\n=== Wiring main path: v_ctrl → C1 → R1 → sw_gate ===")
    de.de_connect()
    de.de_add_wire(1.375, 0.0)
    de.de_add_wire(2.875, 0.0)
    de.de_add_wire(4.25,  0.0)
    de.de_add_wire(5.25,  0.0)
    de.de_end()
    print("  main wire done")

    # Shunt path: C1 bottom → GND (vertical drop at x=2.875)
    print("\n=== Wiring shunt: C1 → GND ===")
    de.de_connect()
    de.de_add_wire(2.875,  0.0)
    de.de_add_wire(2.875, -1.0)
    de.de_end()
    print("  shunt wire done")

    # ── Set R1 parameter: R = Rs Ohm ─────────────────────────────────────────
    print("\n=== Setting R1 parameter: Rs Ohm ===")
    r1_item = de.de_edit_item("R1")
    de.de_set_item_parameters(r1_item, [de.prm_ex("ads_rflib", "StdForm", "Rs Ohm")])
    de.de_end_edit_item(r1_item)
    print("  R1.R = Rs Ohm")

    # ── Set C1 parameter: C = Cp pF ───────────────────────────────────────────
    print("\n=== Setting C1 parameter: Cp pF ===")
    c1_item = de.de_edit_item("C1")
    de.de_set_item_parameters(c1_item, [de.prm_ex("ads_rflib", "StdForm", "Cp pF")])
    de.de_end_edit_item(c1_item)
    print("  C1.C = Cp pF")

    # ── Set design variables: Rs=1000, Cp=1 ──────────────────────────────────
    print("\n=== Setting design variables: Rs=1000, Cp=1 ===")
    de.de_update_item_ex(ctx, [
        de.create_parm("Rs", "", 68608, "StdFormSet", -1,
                       de.prm_ex(LIB, "StdForm", "1000"), None),
        de.create_parm("Cp", "", 68608, "StdFormSet", -1,
                       de.prm_ex(LIB, "StdForm", "1"),    None),
    ])
    print("  Rs=1000, Cp=1")

    # ── Save schematic ─────────────────────────────────────────────────────────
    print("\n=== Saving schematic ===")
    de.de_save_oa_design(LCV)
    print(f"  saved: {LCV}")

    # ── Auto-generate symbol ───────────────────────────────────────────────────
    print("\n=== Generating blackbox symbol ===")
    source_design = de.de_get_design_context_from_name(LCV)
    new_symbol    = de.de_create_new_symbol_view()
    de.de_generate_blackbox_symbol(
        new_symbol, source_design,
        0.25, 0.25,           # pin spacing x, y
        True, True,           # auto-orient pins
        0,                    # pin label style
        False,                # use port names
        "dot",                # pin style
        False, False, False   # misc flags
    )
    print("  symbol generated")

    print("\n=== Done ===")
    print(f"  Cell: {LCV}")
    print(f"  Symbol: {LIB}:{CELL}:symbol")


if __name__ == "__main__":
    main()
