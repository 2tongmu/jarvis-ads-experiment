r"""
ads_query_pdk_cells.py
=======================
# Created by: net-to-ads agent
# Run: 2026-04-06
# Purpose: List all cells in an ADS PDK library, their views, and parameter names
# Inputs:  Existing ADS workspace with PDK loaded; PDK library name
# Outputs: Printed table of cell names, views, and optionally parameter names
# Replaces: ~6 turns of manual PDK directory decoding and ADS Python API cell
#           enumeration to find the correct cell name for WIN_PP1029_CPW.
#           (The OA cell directories use %XX percent-encoding; the API name is
#           different from what you'd guess from reading directory names.)

Key finding (Run 1, 2026-04-06):
  - Cell name in ADS Python API: WIN_PP1029_CPW (in lib WIN_PP1029_DESIGN_KIT)
  - TransistorModel parameter value: PP1029_CPW_PDK  (this is NOT the cell name)
  - The generated netlist uses PP1029_CPW_PDK as the model reference
  - lib.cells only returns cells with OA symbol or schematic views;
    cells with only layout views may be omitted depending on ADS version

Usage:
    # List all cells in a PDK library (standalone):
    "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" ads_query_pdk_cells.py \
        --wrk "C:\Users\jarvis\ads_projects\spdt_switch_pdk_wrk" \
        --pdk-lib WIN_PP1029_DESIGN_KIT

    # Or import and call:
    from ads_query_pdk_cells import query_pdk_cells
    cells = query_pdk_cells(workspace, "WIN_PP1029_DESIGN_KIT", show_params=True)
"""

import sys, os, warnings, argparse
from pathlib import Path

ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))


def query_pdk_cells(workspace, pdk_lib_name: str,
                    show_params: bool = False,
                    filter_str: str = None,
                    verbose: bool = True) -> list:
    """
    Enumerate all cells in a PDK library via ADS Python API.

    Args:
        workspace:     Open ADS workspace object
        pdk_lib_name:  Name of the PDK library (e.g. "WIN_PP1029_DESIGN_KIT")
        show_params:   If True, probe and print parameter names for each cell
        filter_str:    If set, only print cells whose name contains this string
        verbose:       If True, print results

    Returns:
        List of dicts: [{name, views, params (if show_params)}]
    """
    import keysight.ads.de as de
    from keysight.ads.de import db_uu as db

    lib = workspace.open_library(pdk_lib_name)
    cells = list(lib.cells)

    results = []
    for cell in cells:
        views = [v.name for v in cell.views]
        entry = {"name": cell.name, "views": views}

        if filter_str and filter_str.lower() not in cell.name.lower():
            continue

        if show_params and "symbol" in views:
            # Probe params by placing a scratch instance (rolled back)
            params = []
            try:
                # Find a writable design to use as scratch space
                # Use a temporary approach: probe via LCVName
                lcv = de.LCVName(pdk_lib_name, cell.name, "symbol")
                # We can't place without a design context; just note symbol exists
                entry["params"] = "(probe requires open design)"
            except Exception as e:
                entry["params"] = f"error: {e}"

        results.append(entry)

        if verbose:
            param_str = f"  params={entry.get('params','')}" if show_params else ""
            print(f"  {cell.name:40s}  views={views}{param_str}")

    if verbose:
        print(f"\nTotal: {len(results)} cells in {pdk_lib_name}")

    return results


def probe_cell_params(workspace, lib_name: str, cell_name: str,
                      scratch_design_lcv: str = None) -> dict:
    """
    Place a scratch instance of a cell to read its default parameter names/values.
    Rolls back — does not modify any design.

    Args:
        workspace:          Open ADS workspace
        lib_name:           Library containing the cell
        cell_name:          Cell name to probe
        scratch_design_lcv: LCV string of an existing writable schematic to use
                            as scratch space (e.g. "mylib:myschematic:schematic")
                            If None, raises ValueError.

    Returns:
        Dict of {param_name: default_value}
    """
    import keysight.ads.de as de
    from keysight.ads.de import db_uu as db

    if scratch_design_lcv is None:
        raise ValueError("scratch_design_lcv required — provide an existing writable schematic LCV.")

    sch = db.open_design(scratch_design_lcv)
    tx = de.db.Transaction(sch, f"probe_{cell_name}")
    try:
        inst = sch.add_instance(
            de.LCVName(lib_name, cell_name, "symbol"),
            (999.0, 999.0), name=f"_probe_{cell_name}"
        )
        params = {}
        for p in inst.parameters:
            params[p.name] = p.value
        return params
    finally:
        tx.rollback()


def main():
    parser = argparse.ArgumentParser(description="List PDK cells via ADS Python API.")
    parser.add_argument("--wrk",     required=True, help="Path to open ADS workspace dir")
    parser.add_argument("--pdk-lib", required=True, help="PDK library name to query")
    parser.add_argument("--filter",  default=None,  help="Filter: only cells containing this string")
    parser.add_argument("--params",  action="store_true", help="Show parameter names (requires scratch design)")
    parser.add_argument("--scratch", default=None,  help="Scratch design LCV for param probing")
    args = parser.parse_args()

    import keysight.ads.de as de

    wrk_dir = Path(args.wrk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workspace = de.open_workspace(str(wrk_dir))

    print(f"[OK] Workspace open: {wrk_dir}")
    print(f"[OK] Querying: {args.pdk_lib}\n")

    cells = query_pdk_cells(
        workspace,
        pdk_lib_name=args.pdk_lib,
        show_params=args.params,
        filter_str=args.filter,
        verbose=True,
    )

    if args.params and args.scratch:
        print("\n--- Parameter details (probe via scratch design) ---")
        for c in cells:
            if "symbol" in c["views"]:
                try:
                    params = probe_cell_params(workspace, args.pdk_lib, c["name"], args.scratch)
                    print(f"\n{c['name']}:")
                    for k, v in params.items():
                        print(f"  {k:25s} = {v!r}")
                except Exception as e:
                    print(f"\n{c['name']}: ERROR — {e}")


if __name__ == "__main__":
    main()
