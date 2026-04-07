r"""
ads_bias_subcell_create.py
==========================
# Created by: net-to-ads agent
# Run: 2026-04-07
# Purpose: Create a reusable GBIAS_SWITCH_GATE bias subcircuit cell in an ADS library
# Inputs:  --workspace <path to ADS workspace directory>
#          --type      bias type key: "switch_gate" (others are stubs)
#          --lib       ADS library name to place the subcell into
# Outputs: GBIAS_SWITCH_GATE schematic cell built into <lib_name>
# Replaces: Manual gate bias component placement repeated per FET in every
#           top-level builder script (currently 4x gate_stub() calls in
#           ads_build_spdt_pdk.py). Subcell encapsulates Rs, Cp, Vctrl once.

Internal topology of GBIAS_SWITCH_GATE:

    PORT_CTRL (x=0) ─── ctrl_node ──────────── Rs_bias (R) ─── gate_pin ─── PORT_GATE
                             │                   (ctrl_node → gate_pin)
                         Cp_bypass (C, shunt)
                             │
                            GND
                         Vctrl_src (V_DC, + at ctrl_node, − at GND)
                             │
                            GND

Cell-level parameters (set per FET instance in parent schematic):
    Rs     Ohm   gate bias series resistor    (isolation + stability)
    Cp     pF    RF bypass cap at ctrl node   (AC short for RF, DC pass)
    Vctrl  V     DC gate control voltage      (drives Vctrl_src internally)

External ports:
    PORT_GATE  → connects to FET gate pin in parent schematic
    PORT_CTRL  → optional external override (drives ctrl_node directly)

Run:
    "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" \
        ads_bias_subcell_create.py --workspace C:\path\to\wrk --type switch_gate
"""

import sys
import os
import argparse
import warnings
from pathlib import Path

# ── ADS Python environment setup ──────────────────────────────────────────────
# Identical to ads_build_spdt_pdk.py — insert ADS packages before any import.
# Verify this path exists on the target machine before running.
ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

import keysight.ads.de as de
from keysight.ads.de import db_uu as db  # db_uu = schematic/cell database access

# ── Default library name ───────────────────────────────────────────────────────
# Can be overridden via CLI --lib argument.
# Using a dedicated library keeps bias subcells separate from circuit cells.
DEFAULT_LIB_NAME = "GBIAS_CELLS"


# ══════════════════════════════════════════════════════════════════════════════
# Workspace helpers
# ══════════════════════════════════════════════════════════════════════════════

def _open_workspace(workspace_path: Path):
    """
    Open an existing ADS workspace without deleting it.

    ads_build_spdt_pdk.py always recreates the workspace from scratch
    (shutil.rmtree → de.create_workspace → workspace.open).
    Here we must NOT delete — the spdt schematic already lives there.

    ⚠ UNVERIFIED: de.create_workspace() on an existing directory may
      raise an error or silently overwrite. If it fails, try:
        workspace = de.Workspace(str(workspace_path))   # hypothetical constructor
        workspace.open()
      and update MEMORY.md with the correct pattern.
    """
    if de.workspace_is_open():
        de.close_workspace()

    # de.create_workspace() is the only confirmed constructor from Run 1.
    # If the directory already exists, ADS may treat this as "open existing".
    workspace = de.create_workspace(str(workspace_path))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # suppress benign vtb.defs warning
        workspace.open()

    print(f"[WRK] Workspace open: {workspace_path}")
    return workspace


def _ensure_library(workspace, lib_name: str, lib_dir: Path):
    """
    Add lib_name to the workspace if it is not already present.
    Checks workspace.libraries before calling add_library to avoid
    duplicate-library errors (confirmed pattern from Run 1).

    ⚠ UNVERIFIED: workspace.libraries may return library objects or strings.
      The .name attribute access below assumes objects with a .name property.
      If it returns strings, change to: if lib_name not in workspace.libraries
    """
    existing = [lib.name for lib in workspace.libraries]
    if lib_name not in existing:
        lib_dir.mkdir(parents=True, exist_ok=True)
        de.create_new_library(lib_name, str(lib_dir))
        workspace.add_library(lib_name, str(lib_dir), de.LibraryMode.SHARED)
        print(f"[LIB] Created and added library: {lib_name}")
    else:
        print(f"[LIB] Library already in workspace: {lib_name}")


# ══════════════════════════════════════════════════════════════════════════════
# GBIAS_SWITCH_GATE subcell builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_switch_gate_subcell(workspace, lib_name: str):
    """
    Build the GBIAS_SWITCH_GATE subcircuit schematic cell.

    Cell name:  GBIAS_SWITCH_GATE
    Cell view:  schematic
    Library:    lib_name (passed in)

    Parameters defined on the cell (not hardcoded):
        Rs     Ohm   default 300 Ohm
        Cp     pF    default 0.012 pF  (= 12 fF, from spdt_switch_prep.net)
        Vctrl  V     default 0.0 V     (overridden per FET role in parent)

    Topology (x increases left→right, signal y=0):
        x=0:    PORT_CTRL pin
        x=1.5:  Vctrl_src (V_DC, + at ctrl_node/y=0, − to GND below)
        x=3.0:  Cp_bypass (C shunt, P1 at ctrl_node, P2 to GND)
        x=5.0:  Rs_bias (R horizontal, P1=4.5 ctrl_node, P2=5.5 gate_pin)
        x=6.5:  PORT_GATE pin
    """
    CELL_NAME = "GBIAS_SWITCH_GATE"

    print(f"[BUILD] Creating cell {lib_name}:{CELL_NAME}:schematic")

    # ── Create schematic view ─────────────────────────────────────────────────
    # Same pattern as ads_build_spdt_pdk.py: db.create_schematic(LCV string).
    # LCV = Library:Cell:View
    sch = db.create_schematic(f"{lib_name}:{CELL_NAME}:schematic")

    # ── Open transaction ──────────────────────────────────────────────────────
    # All add_instance / add_wire / add_variable calls must occur inside a
    # transaction. tx.commit() writes changes; sch.save_design() persists.
    tx = de.db.Transaction(sch, "build_gbias_switch_gate")

    # ── Define cell-level parameters ──────────────────────────────────────────
    # These become the subcell's parameterised interface — parent schematic
    # sets Rs/Cp/Vctrl per FET instance, overriding these defaults.
    #
    # ⚠ UNVERIFIED: sch.add_variable() is inferred from ADS Python API
    #   conventions. Alternatives if this fails:
    #     sch.cell.add_variable(name, default)
    #     sch.design_variables[name] = default
    #   Update MEMORY.md with the confirmed method after first run.
    sch.add_variable("Rs",    "300 Ohm")   # gate bias isolation resistor
    sch.add_variable("Cp",    "0.012 pF")  # RF bypass (12 fF = 0.012 pF)
    sch.add_variable("Vctrl", "0.0 V")     # DC gate control voltage
    print(f"[BUILD] Cell variables defined: Rs=300 Ohm, Cp=0.012 pF, Vctrl=0.0 V")

    # ── Shared helpers (local scope, same pattern as ads_build_spdt_pdk.py) ───

    def mkR(name, x, y, val, angle=0.0):
        # ads_rflib:R — ideal resistor; P1=(x-0.5,y), P2=(x+0.5,y) at angle=0
        i = sch.add_instance(de.LCVName("ads_rflib", "R", "symbol"),
                             (x, y), name=name, angle=angle)
        i.parameters["R"].value = val
        return i

    def mkC(name, x, y, val, angle=-90.0):
        # ads_rflib:C — ideal capacitor; angle=-90 = shunt: P1=(x,y), P2=(x,y-1)
        i = sch.add_instance(de.LCVName("ads_rflib", "C", "symbol"),
                             (x, y), name=name, angle=angle)
        i.parameters["C"].value = val
        return i

    def mkGnd(name, x, y):
        # ads_rflib:GROUND — schematic ground symbol; no parameters
        return sch.add_instance(de.LCVName("ads_rflib", "GROUND", "symbol"),
                                (x, y), name=name, angle=-90.0)

    def wire(pts):
        # sch.add_wire() — confirmed from ads_build_spdt_pdk.py Run 1
        # pts: list of (x,y) tuples; endpoints must exactly match pin snap_points
        sch.add_wire(pts)

    # ── PORT_CTRL pin (x=0, y=0) — external ctrl_node access ────────────────
    # Port pins define the subcell's external interface for a subcircuit.
    # In the parent schematic, PORT_CTRL connects to the optional external
    # control driver. If unused, it floats (Vctrl_src drives ctrl_node instead).
    #
    # ⚠ UNVERIFIED: Port/Pin symbol library and cell name for subcircuit ports.
    #   In ADS GUI, subcircuit pins are placed from system_sch:Pin:symbol.
    #   The "Name" parameter sets the port name visible to the parent schematic.
    #   If this fails, try:
    #     de.LCVName("ads_port", "Pin", "symbol")
    #     de.LCVName("ads_simulation", "Term", "symbol")  (but Term adds S-param port)
    #   Update MEMORY.md with the confirmed library/cell after first run.
    pin_ctrl = sch.add_instance(de.LCVName("system_sch", "Pin", "symbol"),
                                (0.0, 0.0), name="PORT_CTRL", angle=180.0)
    # ⚠ UNVERIFIED: Pin parameter name for the port label.
    #   Likely "Name" or "PinName" — check via dir(pin_ctrl.parameters) on first run.
    pin_ctrl.parameters["Name"].value = "CTRL"
    print(f"[BUILD] PORT_CTRL placed at (0.0, 0.0)")

    # ── Vctrl_src: V_DC source (ctrl_node to GND) ────────────────────────────
    # V_DC provides the default DC gate bias internally.
    # + terminal (P1) connects to ctrl_node at y=0.
    # − terminal (P2) connects to GND below.
    # Component placed at (1.5, -0.5), vertical orientation.
    #
    # ⚠ UNVERIFIED: V_DC library and cell name in ADS Python API.
    #   Best guess: ads_simulation:V_DC:symbol  (matches ADS GUI component palette)
    #   Pin positions at angle=0 (vertical): guessed P1=(1.5,0.0) [+], P2=(1.5,-1.0) [-]
    #   Confirm pin offsets via ads_probe_fet_pins.py pattern if placement fails.
    #   Alternative library: ads_rflib or ads_sources
    vctrl_src = sch.add_instance(de.LCVName("ads_simulation", "V_DC", "symbol"),
                                 (1.5, -0.5), name="Vctrl_src", angle=0.0)
    # Vdc parameter references the cell-level variable Vctrl defined above.
    # ADS resolves bare variable names in parameter fields at simulation time.
    # ⚠ UNVERIFIED: parameter name may be "Vdc" or "V" depending on ADS version.
    vctrl_src.parameters["Vdc"].value = "Vctrl"
    mkGnd("GND_vctrl", 1.5, -1.5)
    print(f"[BUILD] Vctrl_src (V_DC) placed at (1.5, -0.5), Vdc=Vctrl")

    # ── Cp_bypass: RF bypass capacitor (ctrl_node to GND, shunt) ─────────────
    # Cp provides an AC short at the ctrl_node, blocking RF from the control line.
    # Placed at (3.0, 0.0) with angle=-90 (shunt): P1=(3.0,0.0), P2=(3.0,-1.0)
    # Parameter references cell-level variable Cp.
    mkC("Cp_bypass", 3.0, 0.0, "Cp")
    mkGnd("GND_cp", 3.0, -1.5)
    print(f"[BUILD] Cp_bypass (C shunt) placed at (3.0, 0.0), C=Cp")

    # ── Rs_bias: gate isolation resistor (ctrl_node → gate_pin) ──────────────
    # Rs provides RF isolation between the DC control line and the FET gate.
    # Horizontal placement: center=(5.0,0.0), P1=(4.5,0.0), P2=(5.5,0.0)
    # Parameter references cell-level variable Rs.
    mkR("Rs_bias", 5.0, 0.0, "Rs")
    print(f"[BUILD] Rs_bias (R horizontal) placed at (5.0, 0.0), R=Rs")

    # ── PORT_GATE pin (x=6.5, y=0) — connects to FET gate in parent ──────────
    # This is the primary interface pin. In the parent schematic, the gate pin
    # of each PDK FET (WIN_PP1029_CPW pin1) connects here.
    # ⚠ UNVERIFIED: same Pin symbol uncertainty as PORT_CTRL above.
    pin_gate = sch.add_instance(de.LCVName("system_sch", "Pin", "symbol"),
                                (6.5, 0.0), name="PORT_GATE", angle=0.0)
    pin_gate.parameters["Name"].value = "GATE"
    print(f"[BUILD] PORT_GATE placed at (6.5, 0.0)")

    # ── Wires ─────────────────────────────────────────────────────────────────
    # ctrl_node: PORT_CTRL(0,0) → Vctrl+ (guessed 1.5,0) → Cp.P1 (3.0,0) → Rs.P1 (4.5,0)
    wire([(0.0, 0.0), (4.5, 0.0)])    # ctrl_node span: PORT_CTRL through Vctrl+ and Cp tap to Rs.P1
    # gate_pin: Rs.P2 (5.5,0) → PORT_GATE (6.5,0)
    wire([(5.5, 0.0), (6.5, 0.0)])    # gate_pin span: Rs.P2 to PORT_GATE
    print(f"[BUILD] Wires added.")

    # ── Commit and save ───────────────────────────────────────────────────────
    # tx.commit() writes all add_instance / add_wire / add_variable changes.
    # sch.save_design() persists to disk.
    tx.commit()
    sch.save_design()
    print(f"[BUILD] {CELL_NAME} committed and saved to {lib_name}.")
    return sch


# ══════════════════════════════════════════════════════════════════════════════
# Dispatch table
# ══════════════════════════════════════════════════════════════════════════════

# Maps bias_type keys to builder functions.
# Add new bias types here as the agent expands capability.
# None = stub: builder not yet implemented; create_bias_subcell will raise clearly.
BIAS_BUILDERS = {
    "switch_gate": _build_switch_gate_subcell,
    "amp_gate":    None,   # stub — not yet implemented
    "amp_drain":   None,   # stub — not yet implemented
}


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════════

def create_bias_subcell(workspace_path: str, bias_type: str, lib_name: str):
    """
    Open workspace at workspace_path, ensure lib_name exists, and build
    the subcircuit cell for bias_type.

    Args:
        workspace_path: Absolute path to ADS workspace directory.
        bias_type:      Key into BIAS_BUILDERS (e.g. "switch_gate").
        lib_name:       ADS library name to place the subcell into.

    Returns:
        sch: The created schematic object.

    Raises:
        ValueError: If bias_type is not in BIAS_BUILDERS or its builder is None (stub).
    """
    if bias_type not in BIAS_BUILDERS:
        raise ValueError(
            f"Unknown bias_type '{bias_type}'. "
            f"Valid types: {list(BIAS_BUILDERS.keys())}"
        )

    builder = BIAS_BUILDERS[bias_type]
    if builder is None:
        raise ValueError(
            f"bias_type '{bias_type}' is registered but not yet implemented (stub). "
            f"Implement _build_{bias_type.replace('-','_')}_subcell() and assign it in BIAS_BUILDERS."
        )

    workspace_path = Path(workspace_path)
    lib_dir = workspace_path / lib_name

    print(f"\n{'=' * 62}")
    print(f"Bias Subcell Creator")
    print(f"  workspace : {workspace_path}")
    print(f"  bias_type : {bias_type}")
    print(f"  library   : {lib_name}")
    print(f"{'=' * 62}\n")

    workspace = _open_or_create_workspace(workspace_path)
    _ensure_library(workspace, lib_name, lib_dir)
    sch = builder(workspace, lib_name)

    print(f"\n{'=' * 62}")
    print(f"DONE — subcell created.")
    print(f"  Cell: {lib_name}:GBIAS_SWITCH_GATE:schematic")
    print(f"  Next: instantiate in parent schematic via")
    print(f"        sch.add_instance(de.LCVName('{lib_name}','GBIAS_SWITCH_GATE','schematic'), ...)")
    print(f"{'=' * 62}")
    return sch


def _open_or_create_workspace(workspace_path: Path):
    """
    Open an existing workspace, or create a new one if it does not yet exist.

    Does NOT delete the workspace directory — unlike ads_build_spdt_pdk.py
    which always recreates from scratch. This script adds to existing workspaces.

    ⚠ UNVERIFIED: de.create_workspace() behaviour when the target directory
      already exists. It may raise, silently succeed, or behave differently
      across ADS versions. If it raises, investigate:
        workspace = de.Workspace(str(workspace_path))   # hypothetical constructor
        workspace.open()
      and update MEMORY.md with the confirmed pattern.
    """
    if de.workspace_is_open():
        de.close_workspace()

    workspace = de.create_workspace(str(workspace_path))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # suppress benign vtb.defs / SystemVue warnings
        workspace.open()

    return workspace


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create a bias subcircuit cell in an ADS library."
    )
    parser.add_argument(
        "--workspace", required=True,
        help="Absolute path to the ADS workspace directory."
    )
    parser.add_argument(
        "--type", dest="bias_type", required=True,
        choices=list(BIAS_BUILDERS.keys()),
        help="Bias type to build. Currently implemented: switch_gate."
    )
    parser.add_argument(
        "--lib", dest="lib_name", default=DEFAULT_LIB_NAME,
        help=f"ADS library name to place the subcell into. Default: {DEFAULT_LIB_NAME}"
    )
    args = parser.parse_args()
    create_bias_subcell(args.workspace, args.bias_type, args.lib_name)
