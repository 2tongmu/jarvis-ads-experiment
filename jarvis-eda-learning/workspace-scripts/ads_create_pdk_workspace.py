r"""
ads_create_pdk_workspace.py
============================
# Created by: net-to-ads agent
# Run: 2026-04-06
# Purpose: Create a new ADS workspace with a PDK injected via lib.defs INCLUDE
# Inputs:  WRK_DIR (path), LIB_NAME (str), PDK_DIR (path)
# Outputs: Opened ADS workspace with PDK library visible; writable lib created
# Replaces: ~5 turns of manual exploration to figure out lib.defs INCLUDE pattern
#           and workspace open sequence for PDK-enabled projects

Usage as a library:
    from ads_create_pdk_workspace import create_pdk_workspace
    workspace, lib = create_pdk_workspace(wrk_dir, lib_name, pdk_dir)

Or standalone:
    "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" ads_create_pdk_workspace.py \
        --wrk "C:\Users\jarvis\ads_projects\my_wrk" \
        --lib my_lib \
        --pdk "C:\Users\jarvis\ads_projects\design_kits\WIN_PP1029_DESIGN_KIT"
"""

import sys, os, shutil, warnings, argparse
from pathlib import Path

ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))


def create_pdk_workspace(wrk_dir: Path, lib_name: str, pdk_dir: Path,
                         clean: bool = True, verbose: bool = True) -> tuple:
    """
    Create and open an ADS workspace with a PDK loaded via lib.defs INCLUDE.

    How it works:
      1. Optionally remove any existing workspace at wrk_dir (clean=True)
      2. Call de.create_workspace() — writes default lib.defs
      3. Append INCLUDE <pdk_dir>/lib.defs to workspace lib.defs
         (Must happen BEFORE workspace.open() — ADS reads lib.defs at open time)
      4. Open workspace
      5. Create writable library at wrk_dir/lib_name
      6. Add it to workspace

    Key lesson from Run 1:
      - PDK lib.defs INCLUDE must be written AFTER create_workspace() but
        BEFORE workspace.open() — not before, not after.
      - vtb.defs SystemVue warning on every open is benign; suppress with warnings.

    Args:
        wrk_dir:  Path to workspace directory (Windows path)
        lib_name: Name of the writable design library to create
        pdk_dir:  Path to PDK root (must contain lib.defs)
        clean:    If True, delete existing workspace first
        verbose:  If True, print progress

    Returns:
        (workspace, library) tuple
    """
    import keysight.ads.de as de

    def log(msg):
        if verbose:
            print(msg)

    wrk_dir = Path(wrk_dir)
    pdk_dir = Path(pdk_dir)
    lib_dir = wrk_dir / lib_name
    pdk_lib_defs = pdk_dir / "lib.defs"

    if not pdk_lib_defs.exists():
        raise FileNotFoundError(f"PDK lib.defs not found: {pdk_lib_defs}")

    # Step 1: Clean existing workspace
    if clean and wrk_dir.exists():
        log(f"[create_pdk_workspace] Removing existing workspace: {wrk_dir}")
        shutil.rmtree(str(wrk_dir), ignore_errors=True)

    if de.workspace_is_open():
        de.close_workspace()

    # Step 2: Create workspace (writes default lib.defs)
    log(f"[create_pdk_workspace] Creating workspace: {wrk_dir}")
    workspace = de.create_workspace(str(wrk_dir))

    # Step 3: Inject PDK INCLUDE into lib.defs BEFORE opening
    lib_defs_path = wrk_dir / "lib.defs"
    with open(lib_defs_path, "a") as f:
        f.write(f"\nINCLUDE {pdk_lib_defs}\n")
    log(f"[create_pdk_workspace] PDK injected: {pdk_lib_defs}")

    # Step 4: Open workspace (reads lib.defs — PDK now visible)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # suppress vtb.defs SystemVue warning
        workspace.open()

    # Step 5-6: Create and register writable library
    de.create_new_library(lib_name, str(lib_dir))
    workspace.add_library(lib_name, str(lib_dir), de.LibraryMode.SHARED)
    log(f"[create_pdk_workspace] Library '{lib_name}' ready at {lib_dir}")

    # Verify PDK is visible
    all_libs = list(workspace.library_names) if hasattr(workspace, "library_names") else []
    pdk_name = pdk_dir.name
    if pdk_name in all_libs:
        log(f"[create_pdk_workspace] PDK library confirmed visible: {pdk_name}")
    else:
        log(f"[create_pdk_workspace] WARNING: {pdk_name} not found in library list: {all_libs}")

    lib = workspace.open_library(lib_name)
    return workspace, lib


def main():
    parser = argparse.ArgumentParser(description="Create ADS workspace with PDK.")
    parser.add_argument("--wrk",  required=True, help="Windows path to new workspace dir")
    parser.add_argument("--lib",  required=True, help="Library name to create")
    parser.add_argument("--pdk",  required=True, help="Windows path to PDK root dir")
    parser.add_argument("--no-clean", action="store_true", help="Don't delete existing workspace")
    args = parser.parse_args()

    workspace, lib = create_pdk_workspace(
        wrk_dir=Path(args.wrk),
        lib_name=args.lib,
        pdk_dir=Path(args.pdk),
        clean=not args.no_clean,
        verbose=True,
    )

    import keysight.ads.de as de
    all_libs = list(workspace.library_names) if hasattr(workspace, "library_names") else []
    print(f"\n[OK] Workspace open. Libraries visible ({len(all_libs)}):")
    for lname in sorted(all_libs):
        print(f"  {lname}")


if __name__ == "__main__":
    main()
