"""
ads_api/cell_ops.py
===================
Manage ADS cells and views.

All functions require an ADSSession from ads_session.get_ads_session()
and a library handle from workspace_ops.ensure_library().

All patterns confirmed from ADS_API_REFERENCE.md §2–§3 and validated
in ads_bias_subcell_create.py on Jarvis 2026-04-08.

Key design choices:
  - open_or_create_schematic() always DELETES and RECREATES the schematic view.
    Rationale: idempotent, deterministic, avoids stale geometry from previous runs.
    Downstream: placement_engine.py calls this unconditionally on each build.
  - open_or_create_symbol() does the same for the symbol view.
  - Both return the WRITE-mode design object — callers must not call get_design()
    again; the design is already open and writable.

Usage:
    from ads_api.ads_session import get_ads_session
    from ads_api.workspace_ops import open_workspace, ensure_library
    from ads_api.cell_ops import get_or_create_cell, open_or_create_schematic

    session = get_ads_session()
    ws  = open_workspace(session, "C:/path/to/workspace")
    lib = ensure_library(session, "net2ads_lib")
    cell, design = open_or_create_schematic(session, lib, "rc_series_shunt")
"""

from ads_api.ads_session import ADSSession


# ── Cell ───────────────────────────────────────────────────────────────────────

def get_or_create_cell(session: ADSSession, lib, cell_name: str):
    """
    Return a cell from the library, creating it if it does not exist.

    Args:
        session   : ADSSession
        lib       : library object from ensure_library()
        cell_name : name of the cell (e.g. "rc_series_shunt")

    Returns:
        cell object (keysight.ads.de.Cell)

    API status:
        lib.cell_exists(name)   ✅ CONFIRMED
        lib.cell(name)          ✅ CONFIRMED
        de.Cell.create(lib,n)   ✅ CONFIRMED
    """
    if lib.cell_exists(cell_name):          # ✅ CONFIRMED
        cell = lib.cell(cell_name)          # ✅ CONFIRMED
        print(f"[cell] found existing: {cell_name}")
    else:
        cell = session.de.Cell.create(lib, cell_name)  # ✅ CONFIRMED
        print(f"[cell] created: {cell_name}")
    return cell


# ── Schematic view ─────────────────────────────────────────────────────────────

def open_or_create_schematic(session: ADSSession, lib, cell_name: str):
    """
    Get (or create) a cell and return it with a fresh, writable schematic design.

    Always deletes and recreates the schematic view for determinism.
    Caller must NOT call get_design() again — the returned design is already
    open in WRITE mode.

    Args:
        session   : ADSSession
        lib       : library object from ensure_library()
        cell_name : name of the cell

    Returns:
        (cell, design) tuple where design is open in DesignMode.WRITE

    API status:
        cell.view_exists('schematic')             ✅ CONFIRMED
        cell.delete_view('schematic')             ✅ CONFIRMED
        de.View.create(cell,'schematic','schematic') ✅ CONFIRMED
        sch_view.get_design(DesignMode.WRITE)     ✅ CONFIRMED
    """
    cell = get_or_create_cell(session, lib, cell_name)

    # Delete existing schematic view to start fresh (confirmed idempotent pattern)
    if cell.view_exists("schematic"):                   # ✅ CONFIRMED
        cell.delete_view("schematic")                   # ✅ CONFIRMED
        print(f"[schematic] deleted existing view for: {cell_name}")

    sch_view = session.de.View.create(cell, "schematic", "schematic")  # ✅ CONFIRMED
    print(f"[schematic] created view: {cell_name}:schematic")

    # CRITICAL: must use WRITE mode — default is READ_ONLY, save_design() silently fails
    design = sch_view.get_design(session.DesignMode.WRITE)  # ✅ CONFIRMED
    print(f"[schematic] design open (WRITE mode)")

    return cell, design


# ── Symbol view ────────────────────────────────────────────────────────────────

def open_or_create_symbol(session: ADSSession, lib_name: str, cell, cell_name: str):
    """
    Delete any existing symbol view and create a fresh, writable one.

    Must be called AFTER the schematic has been saved (design.save_design()),
    so that design.terms is populated and symbol_ops can read it.

    Args:
        session   : ADSSession
        lib_name  : library name string (required by db.create_symbol tuple)
        cell      : cell object from get_or_create_cell() or open_or_create_schematic()
        cell_name : cell name string

    Returns:
        sym_design — symbol design object open in DesignMode.WRITE

    API status:
        cell.view_exists('symbol')              ✅ CONFIRMED
        cell.delete_view('symbol')              ✅ CONFIRMED
        db.create_symbol((lib,cell,'symbol'))   ✅ CONFIRMED
        cell.view('symbol')                     ✅ CONFIRMED
        sym_view.get_design(DesignMode.WRITE)   ✅ CONFIRMED
    """
    if cell.view_exists("symbol"):                  # ✅ CONFIRMED
        cell.delete_view("symbol")                  # ✅ CONFIRMED
        print(f"[symbol] deleted existing view for: {cell_name}")

    # db.create_symbol takes a (lib, cell, view) tuple — ✅ CONFIRMED
    session.db.create_symbol((lib_name, cell_name, "symbol"))
    print(f"[symbol] created view: {cell_name}:symbol")

    sym_view   = cell.view("symbol")                         # ✅ CONFIRMED
    sym_design = sym_view.get_design(session.DesignMode.WRITE)  # ✅ CONFIRMED
    print(f"[symbol] design open (WRITE mode)")

    return sym_design


def save_design(design) -> None:
    """
    Save a design (schematic or symbol) to disk.

    ✅ CONFIRMED — must be called explicitly; changes are not auto-saved.
    Applies to both schematic and symbol designs.
    """
    design.save_design()   # ✅ CONFIRMED
    print("[save] design saved")
