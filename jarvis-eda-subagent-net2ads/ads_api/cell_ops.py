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


def commit_design(session: ADSSession, design) -> None:
    """
    Commit a design transaction to finalize all changes in OpenAccess.

    CRITICAL FIX for metadata registration bug:
    When instances are created via add_instance(), they exist in memory but
    must be finalized via Transaction.commit() to be registered in the
    OpenAccess database. Without this, instances are invisible to the
    ADS netlister and cause "no instances" or open-circuit behavior.

    Pattern (confirmed from ads_build_spdt_pdk.py):
        tx = de.db.Transaction(design, "operation_name")
        # ... add instances, wires, ports, etc ...
        tx.commit()
        design.save_design()

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)

    API status:
        de.db.Transaction(design, label)   ✅ CONFIRMED from ads_build_spdt_pdk.py
        transaction.commit()                ✅ CONFIRMED
    """
    session.db.Transaction(design, "net2ads_build").commit()
    print("[commit] design transaction committed (OpenAccess metadata finalized)")


def write_itemdef_ael(cell_dir_path, cell_name: str, design_variables: list) -> None:
    """
    Write itemdef.ael file to expose design variables as user parameters.

    In ADS, schematic design variables are only exposed as "user parameters"
    (Component Parameters) when instantiated in a parent schematic if the cell
    has an itemdef.ael file.

    This function generates and writes the AEL file that registers design
    variables as component parameters. ALL design variables from the netlist
    (.VAR declarations) are automatically included.

    Args:
        cell_dir_path     : path to the cell directory (e.g. C:\...\net2ads_lib\fetbias_sw_gate\)
        cell_name         : name of the cell (e.g. "fetbias_sw_gate")
        design_variables  : list of (var_name, var_value) tuples
                            e.g. [("Vgate", "0.0 V"), ("Rs", "1000.0 Ohm"), ("Cp", "2272.73 fF")]

    API status:
        File I/O only — no ADS API involved (itemdef.ael is static text)
    """
    from pathlib import Path
    
    cell_dir = Path(cell_dir_path)
    itemdef_path = cell_dir / 'itemdef.ael'
    
    # Build parameter declarations from ALL design variables
    parm_list = []
    for var_name, var_value in design_variables:
        # Extract the numeric part and convert to scientific notation
        # "0.0 V" -> 0.0 -> "0"
        # "1000.0 Ohm" -> 1000.0 -> "1e3"
        # "2272.73 fF" -> 2272.73 -> "2.27273e+03"
        parts = var_value.strip().split()
        num_str = parts[0]
        
        try:
            num_float = float(num_str)
            # Use simple format: if it's a power of 10, use e-notation
            # Otherwise use scientific notation
            if num_float == 0:
                sci = "0"
            elif num_float >= 1e9:
                sci = f"{num_float:.1e}".replace('e+0', 'e+').replace('e-0', 'e-')
            elif num_float >= 1:
                # Check if it's a power of 10
                import math
                if num_float == 10 ** round(math.log10(num_float)):
                    exp = round(math.log10(num_float))
                    sci = f"1e{exp}"
                else:
                    sci = f"{num_float:.5e}".rstrip('0').rstrip('.')
            else:
                sci = f"{num_float:.2e}".replace('e-0', 'e-').replace('+0', '+')
        except:
            sci = num_str
        
        # Description: generate from var_name
        # Vgate -> "gate voltage", Rs -> "series resistance", Cp -> "parallel capacitance"
        if var_name.lower() == "vgate":
            desc = "gate control voltage (V)"
        elif var_name.lower() == "rs":
            desc = "series resistance (ohm)"
        elif var_name.lower() == "cp":
            desc = "parallel capacitance (F)"
        else:
            desc = f"{var_name.lower()} parameter"
        
        # Create parameter: create_parm("name", "description", flags, "StdFormSet", -1, prm("StdForm", "default"))
        parm = f'create_parm("{var_name}","{desc}",68608,"StdFormSet",-1,prm("StdForm","{sci}"))'
        parm_list.append(parm)
    
    # Join parameters with comma + newline
    parm_args = ',\n'.join(parm_list)
    
    # Build the create_item call
    # Reference format (from manual cell):
    # create_item("cell_name","cell_name","X",16,-1,NULL,"Component Parameters",NULL,
    #     "%43?global %;%d:%t %# %44?0%:%31?%C%:_net%c%;%;%e %b%r%8?%29?%:%30?%p %:%k%?[%1i]%;=%p %;%;%;%e%e",
    #     "cell_name",
    #     "%t%b%r%38?%:\n%30?%s%:%k%?[%1i]%;=%s%;%;%e%e%;","",3,NULL,0,
    #     create_parm(...),
    #     create_parm(...));
    
    ael_content = (
        f'create_item("{cell_name}","{cell_name}","X",16,-1,NULL,"Component Parameters",NULL,'
        f'"%43?global %;%d:%t %# %44?0%:%31?%C%:_net%c%;%;%e %b%r%8?%29?%:%30?%p %:%k%?[%1i]%;=%p %;%;%;%e%e",'
        f'"{cell_name}",'
        f'"%t%b%r%38?%:\n%30?%s%:%k%?[%1i]%;=%s%;%;%e%e%;","",3,NULL,0,\n'
        f'{parm_args});'
    )
    
    itemdef_path.write_text(ael_content, encoding='utf-8')
    print(f"[itemdef] wrote {itemdef_path}")
    print(f"[itemdef] auto-generated {len(parm_list)} user parameters from .VAR declarations:")
