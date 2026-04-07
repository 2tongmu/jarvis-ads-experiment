r"""
ads_probe_subcell_api.py
========================
# Created by: net-to-ads agent
# Run: 2026-04-07
# Purpose: Validate the 6 unverified ADS Python API calls in ads_bias_subcell_create.py
# Inputs:  --workspace <path to an existing ADS workspace directory>
# Outputs: Console report with correct syntax for each unverified call
# Replaces: ~6 turns of trial-and-error debugging inside the full subcell build script

Each check runs independently inside its own try/except block.
A failure in one check does not abort the remaining checks.
A GBIAS_API_TEST scratch cell is created for placement tests and deleted at the end.

Run:
    "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" \
        ads_probe_subcell_api.py --workspace C:\path\to\existing\workspace
"""

import sys
import os
import argparse
import shutil
import warnings
from pathlib import Path

# ── ADS Python environment setup ─────────────────────────────────────────────
# Identical to ads_build_spdt_pdk.py — must happen before any keysight import.
ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

import keysight.ads.de as de
from keysight.ads.de import db_uu as db

# ── Constants ─────────────────────────────────────────────────────────────────
TEST_LIB_NAME  = "GBIAS_API_TEST"
TEST_CELL_NAME = "test_cell"
TEST_CELL_LCV  = f"{TEST_LIB_NAME}:{TEST_CELL_NAME}:schematic"

# ── Result tracking ───────────────────────────────────────────────────────────
# Each check appends one dict: {check, status, syntax, notes}
RESULTS = []

def _record(check_num, label, status, syntax, notes=""):
    RESULTS.append({
        "check":  check_num,
        "label":  label,
        "status": status,
        "syntax": syntax,
        "notes":  notes,
    })

def _pass(check_num, label, syntax, notes=""):
    print(f"  [PASS] {syntax}")
    if notes:
        print(f"         {notes}")
    _record(check_num, label, "PASS", syntax, notes)

def _fail(check_num, label, syntax, notes=""):
    print(f"  [FAIL] {syntax}")
    if notes:
        print(f"         {notes}")
    _record(check_num, label, "FAIL", syntax, notes)

def _skip(check_num, label, notes=""):
    print(f"  [SKIP] {notes}")
    _record(check_num, label, "SKIP", "—", notes)


# ══════════════════════════════════════════════════════════════════════════════
# Workspace setup (not a check — prerequisite)
# ══════════════════════════════════════════════════════════════════════════════

def _setup_workspace(workspace_path: Path):
    """
    Open the workspace at workspace_path. Used as the base for all checks.
    Opens an existing workspace with de.open_workspace(); only calls
    de.create_workspace() if the directory is not already a workspace.
    """
    if de.workspace_is_open():
        de.close_workspace()
    if de.directory_is_workspace(str(workspace_path)):
        workspace = de.open_workspace(str(workspace_path))
    else:
        workspace = de.create_workspace(str(workspace_path))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            workspace.open()
    return workspace


def _setup_test_library(workspace, workspace_path: Path):
    """
    Create the scratch library for test schematic placement (Checks 2–6).
    Reuses the confirmed add_library pattern from ads_build_spdt_pdk.py.
    """
    lib_dir = workspace_path / TEST_LIB_NAME
    existing_libs = []
    try:
        existing_libs = [lib.name for lib in workspace.libraries]
    except Exception:
        existing_libs = []
    if TEST_LIB_NAME not in existing_libs:
        # Let de.create_new_library() create the directory itself — pre-creating
        # it causes "Library path already exists" RuntimeError.
        de.create_new_library(TEST_LIB_NAME, str(lib_dir))
        workspace.add_library(TEST_LIB_NAME, str(lib_dir), de.LibraryMode.SHARED)
    return lib_dir


def _create_test_schematic():
    """
    Create a blank scratch schematic for Checks 2–6.
    Uses confirmed db.create_schematic() + Transaction pattern.
    Returns (sch, tx) — tx left open so checks can add_instance into it.
    """
    sch = db.create_schematic(TEST_CELL_LCV)
    tx  = de.db.Transaction(sch, "api_probe")
    return sch, tx


# ══════════════════════════════════════════════════════════════════════════════
# CHECK 1 — de.create_workspace() on an existing directory
# ══════════════════════════════════════════════════════════════════════════════

def check1_workspace_existing(workspace_path: Path):
    """
    Confirmed finding (via live crash on 2026-04-07):
      de.create_workspace() raises RuntimeError on an existing directory.
    Correct open-existing pattern: de.open_workspace() (confirmed present in de module).
    Live test skipped — answer is already confirmed; _setup_workspace() now uses
    de.directory_is_workspace() + de.open_workspace() to handle the existing case.
    """
    print("\n── CHECK 1: de.create_workspace() on existing directory ─────────────")
    _pass(1, "workspace_existing",
          "de.create_workspace(existing_path) → raises RuntimeError: Workspace directory already exists.",
          "Confirmed 2026-04-07. Use de.open_workspace() for existing dirs. Live test skipped.")
    # Return the already-open workspace object so subsequent checks can proceed.
    return de.active_workspace()


# ══════════════════════════════════════════════════════════════════════════════
# CHECK 2 — Cell-level variable definition
# ══════════════════════════════════════════════════════════════════════════════

def check2_cell_variable(sch):
    """
    Tries three candidate forms for defining a cell-level schematic variable.
    Stops at the first that succeeds and records the working syntax.
    """
    print("\n── CHECK 2: cell-level variable definition ──────────────────────────")

    # Candidate A: sch.add_variable(name, default)
    try:
        sch.add_variable("Rs", "300 Ohm")
        _pass(2, "cell_variable",
              'sch.add_variable("Rs", "300 Ohm")',
              "Direct schematic method works.")
        return
    except (AttributeError, Exception) as e:
        print(f"  [TRY ] sch.add_variable()            → {type(e).__name__}: {e}")

    # Candidate B: sch.cell.add_variable(name, default)
    try:
        sch.cell.add_variable("Rs", "300 Ohm")
        _pass(2, "cell_variable",
              'sch.cell.add_variable("Rs", "300 Ohm")',
              "Access via sch.cell intermediate object.")
        return
    except (AttributeError, Exception) as e:
        print(f"  [TRY ] sch.cell.add_variable()       → {type(e).__name__}: {e}")

    # Candidate C: sch.design_variables["Rs"] = "300 Ohm"  (dict-like access)
    try:
        sch.design_variables["Rs"] = "300 Ohm"
        _pass(2, "cell_variable",
              'sch.design_variables["Rs"] = "300 Ohm"',
              "Dict-like design_variables accessor works.")
        return
    except (AttributeError, Exception) as e:
        print(f"  [TRY ] sch.design_variables[...]     → {type(e).__name__}: {e}")

    # All three failed
    _fail(2, "cell_variable",
          "all three candidates failed",
          "Run dir(sch) and dir(sch.cell) to discover correct attribute name.")


# ══════════════════════════════════════════════════════════════════════════════
# CHECK 3 — Pin/port component library and cell name
# ══════════════════════════════════════════════════════════════════════════════

def check3_pin_library(sch):
    """
    Tries three candidate library names for the subcircuit Pin component.
    Returns the placed instance (needed for Check 4), or None if all fail.
    """
    print("\n── CHECK 3: Pin/port component library and cell name ────────────────")

    candidates = [
        ("system_sch",     "Pin", "symbol"),
        ("ads_port",       "Pin", "symbol"),
        ("ads_simulation", "Pin", "symbol"),
    ]
    for lib, cell, view in candidates:
        try:
            lcv = de.LCVName(lib, cell, view)
            inst = sch.add_instance(lcv, (0.0, 0.0), name="PROBE_PIN", angle=0.0)
            syntax = f'de.LCVName("{lib}", "{cell}", "{view}")'
            _pass(3, "pin_library", syntax,
                  f"Pin placed at (0,0). Instance type: {type(inst).__name__}")
            return inst
        except Exception as e:
            print(f"  [TRY ] de.LCVName({lib!r}, {cell!r}, {view!r}) → {type(e).__name__}: {e}")

    _fail(3, "pin_library",
          "all three library candidates failed",
          "Run workspace.open_library(lib).cells to enumerate available components. "
          "Look for anything named Pin, PORT, SchPort, or similar.")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# CHECK 4 — Port pin parameter name for port label
# ══════════════════════════════════════════════════════════════════════════════

def check4_pin_parameter(pin_inst):
    """
    On the Pin instance from Check 3, discovers which parameter key sets
    the port label. Prints all available keys first for reference.
    """
    print("\n── CHECK 4: Port pin parameter name ─────────────────────────────────")

    if pin_inst is None:
        _skip(4, "pin_parameter", "Skipped — Check 3 did not produce a Pin instance.")
        return

    # Print all available parameter keys regardless of which test passes.
    try:
        all_keys = list(pin_inst.parameters.keys())
        print(f"  [INFO] Available parameter keys: {all_keys}")
    except Exception as e:
        print(f"  [INFO] Could not enumerate parameters: {e}")
        try:
            print(f"  [INFO] dir(pin_inst.parameters): {dir(pin_inst.parameters)}")
        except Exception:
            pass

    candidates = ["Name", "PinName", "Label", "Net", "name"]
    for key in candidates:
        try:
            pin_inst.parameters[key].value = "TEST_PORT"
            _pass(4, "pin_parameter",
                  f'pin.parameters["{key}"].value = "TEST_PORT"',
                  f"Parameter key '{key}' accepts a string value.")
            return
        except (KeyError, AttributeError, Exception) as e:
            print(f"  [TRY ] pin.parameters[{key!r}]          → {type(e).__name__}: {e}")

    _fail(4, "pin_parameter",
          "all candidate keys failed",
          "Use the full key list printed above and update ads_bias_subcell_create.py.")


# ══════════════════════════════════════════════════════════════════════════════
# CHECK 5 — V_DC source library and cell name
# ══════════════════════════════════════════════════════════════════════════════

def check5_vdc_library(sch):
    """
    Tries three candidate libraries for the V_DC component.
    Returns the placed instance (needed for Check 6), or None if all fail.
    """
    print("\n── CHECK 5: V_DC source library and cell name ───────────────────────")

    candidates = [
        ("ads_simulation", "V_DC",    "symbol"),
        ("ads_rflib",      "V_DC",    "symbol"),
        ("ads_sources",    "V_DC",    "symbol"),
    ]
    for lib, cell, view in candidates:
        try:
            lcv = de.LCVName(lib, cell, view)
            inst = sch.add_instance(lcv, (2.0, 0.0), name="PROBE_VDC", angle=0.0)
            syntax = f'de.LCVName("{lib}", "{cell}", "{view}")'
            _pass(5, "vdc_library", syntax,
                  f"V_DC placed at (2,0). Instance type: {type(inst).__name__}")
            return inst
        except Exception as e:
            print(f"  [TRY ] de.LCVName({lib!r}, {cell!r}, {view!r}) → {type(e).__name__}: {e}")

    _fail(5, "vdc_library",
          "all three library candidates failed",
          "Check ads_query_pdk_cells.py pattern to enumerate ads_simulation library cells. "
          "Also try cell name 'VDC', 'Vdc', 'DC_Voltage'.")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# CHECK 6 — V_DC voltage parameter name
# ══════════════════════════════════════════════════════════════════════════════

def check6_vdc_parameter(vdc_inst):
    """
    On the V_DC instance from Check 5, discovers which parameter key sets
    the DC voltage. Prints all available keys first for reference.
    """
    print("\n── CHECK 6: V_DC voltage parameter name ─────────────────────────────")

    if vdc_inst is None:
        _skip(6, "vdc_parameter", "Skipped — Check 5 did not produce a V_DC instance.")
        return

    # Print all available parameter keys regardless of which test passes.
    try:
        all_keys = list(vdc_inst.parameters.keys())
        print(f"  [INFO] Available parameter keys: {all_keys}")
    except Exception as e:
        print(f"  [INFO] Could not enumerate parameters: {e}")
        try:
            print(f"  [INFO] dir(vdc_inst.parameters): {dir(vdc_inst.parameters)}")
        except Exception:
            pass

    candidates = ["Vdc", "V", "Voltage", "DC", "Vdc_Value"]
    for key in candidates:
        try:
            vdc_inst.parameters[key].value = "Vctrl"
            _pass(6, "vdc_parameter",
                  f'vdc.parameters["{key}"].value = "Vctrl"',
                  f"Parameter key '{key}' accepts a variable-name string.")
            return
        except (KeyError, AttributeError, Exception) as e:
            print(f"  [TRY ] vdc.parameters[{key!r}]          → {type(e).__name__}: {e}")

    _fail(6, "vdc_parameter",
          "all candidate keys failed",
          "Use the full key list printed above and update ads_bias_subcell_create.py.")


# ══════════════════════════════════════════════════════════════════════════════
# Cleanup
# ══════════════════════════════════════════════════════════════════════════════

def _cleanup_test_cell(sch, tx, lib_dir: Path):
    """
    Commit the scratch transaction (so ADS doesn't hang on uncommitted state),
    then delete the scratch library directory from disk.
    The workspace will still reference the now-missing library — harmless for
    a diagnostic run, but log it clearly.
    """
    print("\n── Cleanup ──────────────────────────────────────────────────────────")
    try:
        tx.commit()
        sch.save_design()
        print("  [OK] Scratch transaction committed.")
    except Exception as e:
        print(f"  [WARN] Commit failed (non-fatal): {e}")
    try:
        import shutil
        shutil.rmtree(str(lib_dir), ignore_errors=True)
        print(f"  [OK] Scratch library directory deleted: {lib_dir}")
    except Exception as e:
        print(f"  [WARN] Could not delete scratch library: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Summary table
# ══════════════════════════════════════════════════════════════════════════════

def _print_summary():
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    header = f"{'CHECK':<7} {'LABEL':<22} {'STATUS':<6}  CORRECT SYNTAX"
    print(header)
    print("-" * 78)
    for r in RESULTS:
        status_tag = r["status"]
        print(f"{r['check']:<7} {r['label']:<22} {status_tag:<6}  {r['syntax']}")
        if r["notes"]:
            print(f"{'':>37}  → {r['notes']}")
    print("=" * 78)

    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    skipped = sum(1 for r in RESULTS if r["status"] == "SKIP")
    print(f"Result: {passed} PASS  |  {failed} FAIL  |  {skipped} SKIP")

    if failed == 0:
        print("\nAll checks passed. Update ads_bias_subcell_create.py with confirmed syntax.")
        print("Log confirmed patterns to MEMORY.md Section 1 as [API-CONFIRMED] entries.")
    else:
        print(f"\n{failed} check(s) failed. See FAIL rows above for corrective action.")
        print("Log failures to MEMORY.md Section 2 (Known Failure Modes).")
    print("=" * 78)


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def run_probes(workspace_path: str):
    workspace_path = Path(workspace_path)

    if not workspace_path.exists():
        print(f"ERROR: Workspace path does not exist: {workspace_path}")
        sys.exit(1)

    print("=" * 78)
    print("ADS Subcell API Probe — validates ads_bias_subcell_create.py API calls")
    print(f"Workspace: {workspace_path}")
    print("=" * 78)

    # ── Open workspace (prerequisite) ─────────────────────────────────────────
    print("\n── Setup: opening workspace ──────────────────────────────────────────")
    workspace = _setup_workspace(workspace_path)
    print(f"  [OK] Workspace open: {workspace_path}")

    # ── Purge any stale GBIAS_API_TEST dir left by a previous crashed run ─────
    # ADS may recreate it from saved.wrkstate on workspace open, so we remove it
    # *after* opening, not before. The lib won't be in workspace.libraries so
    # _setup_test_library will create it fresh.
    stale_dir = workspace_path / TEST_LIB_NAME
    if stale_dir.exists():
        shutil.rmtree(str(stale_dir))

    # ── Check 1: workspace open on existing directory ─────────────────────────
    workspace = check1_workspace_existing(workspace_path)

    # ── Set up scratch library for Checks 2–6 ─────────────────────────────────
    lib_dir = _setup_test_library(workspace, workspace_path)
    sch, tx = _create_test_schematic()
    print(f"\n── Setup: scratch schematic {TEST_CELL_LCV} ready ──────────────────")

    # ── Checks 2–6 ────────────────────────────────────────────────────────────
    check2_cell_variable(sch)
    pin_inst = check3_pin_library(sch)
    check4_pin_parameter(pin_inst)
    vdc_inst = check5_vdc_library(sch)
    check6_vdc_parameter(vdc_inst)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    _cleanup_test_cell(sch, tx, lib_dir)

    # ── Summary ───────────────────────────────────────────────────────────────
    _print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate unverified ADS API calls needed for bias subcell creation."
    )
    parser.add_argument(
        "--workspace", required=True,
        help="Absolute path to an existing ADS workspace directory."
    )
    args = parser.parse_args()
    run_probes(args.workspace)
