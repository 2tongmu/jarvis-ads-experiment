r"""
ads_probe_fet_pins.py
======================
# Created by: net-to-ads agent
# Run: 2026-04-06
# Purpose: Probe pin snap_point positions for any ADS PDK component at any angle
# Inputs:  Open ADS workspace; library name, cell name, list of angles to probe
# Outputs: Dict of {angle: {pin_number: (x, y)}} snap_point coordinates
# Replaces: ~4 turns of failed attempts using InstTerm.position (doesn't exist
#           in ADS 2026 Update 1) before discovering InstPin.snap_point.
#           Eliminates need to manually decode symbol geometry or hardcode pin offsets.

Key findings (Run 1, 2026-04-06):
  - InstTerm.position does NOT exist in ADS 2026 Update 1 Python API
  - Correct path: inst.get_inst_term_iter() → it.inst_pins → ip.snap_point
  - snap_point is a PointF(x, y) object; access as ip.snap_point.x, ip.snap_point.y
  - InstTerm.term_name raises RuntimeError for numbered terminals — use term_number instead
  - All positions are ABSOLUTE (relative to schematic origin, not instance origin)
    because the instance is placed at origin (0,0) for probing

WIN_PP1029_CPW verified pin layout (angle=0, placed at origin):
  pin1 (gate):   snap_point = (0.0,  0.0)   <- at origin (left side)
  pin2 (drain):  snap_point = (0.5, +0.5)   <- upper right
  pin3 (source): snap_point = (0.5, -0.5)   <- lower right

WIN_PP1029_CPW verified pin layout (angle=90, placed at origin):
  pin1 (gate):   snap_point = (0.0,  0.0)   <- at origin (bottom)
  pin2 (drain):  snap_point = (-0.5, +0.5)  <- upper left
  pin3 (source): snap_point = (+0.5, +0.5)  <- upper right

Usage:
    "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" ads_probe_fet_pins.py \
        --wrk "C:\Users\jarvis\ads_projects\spdt_switch_pdk_wrk" \
        --lib WIN_PP1029_DESIGN_KIT \
        --cell WIN_PP1029_CPW \
        --scratch "spdt_switch_pdk_lib:spdt_switch:schematic" \
        --angles 0 90 180 -90
"""

import sys, os, warnings, argparse
from pathlib import Path
from typing import Dict, List, Tuple

ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))


def probe_pin_positions(workspace, lib_name: str, cell_name: str,
                        scratch_design_lcv: str,
                        angles: List[float] = None,
                        place_at: Tuple[float, float] = (0.0, 0.0)) -> Dict[float, Dict[int, Tuple[float, float]]]:
    """
    Probe absolute pin snap_point positions for a PDK component at given angles.
    Places scratch instances (rolled back — no design modification).

    Args:
        workspace:          Open ADS workspace
        lib_name:           Library containing the cell
        cell_name:          Cell to probe
        scratch_design_lcv: LCV of an existing writable schematic for scratch use
        angles:             List of rotation angles in degrees (default: [0, 90, -90, 180])
        place_at:           Instance placement origin for probing (default: (0,0))

    Returns:
        Dict: {angle: {pin_number: (x, y)}}
        Pin numbers are 1-indexed integers.
        Coordinates are absolute (= relative to instance origin when placed_at=(0,0)).
    """
    import keysight.ads.de as de
    from keysight.ads.de import db_uu as db

    if angles is None:
        angles = [0.0, 90.0, -90.0, 180.0]

    sch = db.open_design(scratch_design_lcv)
    results = {}

    for angle in angles:
        tx = de.db.Transaction(sch, f"probe_{cell_name}_a{int(angle)}")
        try:
            inst = sch.add_instance(
                de.LCVName(lib_name, cell_name, "symbol"),
                place_at,
                name=f"_probe_{cell_name}_a{int(angle)}",
                angle=float(angle),
            )

            pin_positions = {}
            for it in inst.get_inst_term_iter():
                pin_num = it.term_number   # 1-indexed int; term_name raises for numbered terminals
                for ip in it.inst_pins:
                    sp = ip.snap_point
                    pin_positions[pin_num] = (float(sp.x), float(sp.y))
                    break  # first inst_pin only (scalar nets)

            results[angle] = pin_positions
        finally:
            tx.rollback()

    return results


def print_pin_table(cell_name: str, pin_data: Dict[float, Dict[int, Tuple[float, float]]]) -> None:
    """Pretty-print the pin position table."""
    print(f"\n{'='*60}")
    print(f"Pin snap_point positions: {cell_name}")
    print(f"(placed at origin (0,0) — coordinates are relative offsets)")
    print(f"{'='*60}")
    print(f"{'Angle':>8}  {'Pin':>4}  {'x':>8}  {'y':>8}")
    print(f"{'-'*40}")
    for angle in sorted(pin_data.keys()):
        pins = pin_data[angle]
        for pin_num in sorted(pins.keys()):
            x, y = pins[pin_num]
            print(f"{angle:>8.1f}  {pin_num:>4}  {x:>8.3f}  {y:>8.3f}")
        print()


def get_pin_offset(pin_data: Dict[float, Dict[int, Tuple[float, float]]],
                   angle: float, pin_num: int) -> Tuple[float, float]:
    """
    Get pin offset for a specific angle and pin number.
    To get absolute position: inst_origin + pin_offset.
    """
    return pin_data[angle][pin_num]


def main():
    parser = argparse.ArgumentParser(description="Probe PDK component pin positions.")
    parser.add_argument("--wrk",     required=True, help="Path to ADS workspace dir")
    parser.add_argument("--lib",     required=True, help="Library name (e.g. WIN_PP1029_DESIGN_KIT)")
    parser.add_argument("--cell",    required=True, help="Cell name (e.g. WIN_PP1029_CPW)")
    parser.add_argument("--scratch", required=True, help="Scratch design LCV (lib:cell:schematic)")
    parser.add_argument("--angles",  nargs="+", type=float, default=[0.0, 90.0, -90.0, 180.0],
                        help="Angles to probe (default: 0 90 -90 180)")
    args = parser.parse_args()

    import keysight.ads.de as de

    wrk_dir = Path(args.wrk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workspace = de.open_workspace(str(wrk_dir))

    print(f"[OK] Probing {args.lib}:{args.cell} at angles {args.angles}")

    pin_data = probe_pin_positions(
        workspace=workspace,
        lib_name=args.lib,
        cell_name=args.cell,
        scratch_design_lcv=args.scratch,
        angles=args.angles,
    )

    print_pin_table(args.cell, pin_data)

    # Also emit as a Python dict literal for copy-paste into builder scripts
    print("\n# Python dict literal for builder scripts:")
    print(f"PIN_OFFSETS_{args.cell.upper().replace(' ','_')} = {{")
    for angle in sorted(pin_data.keys()):
        pins = pin_data[angle]
        print(f"    {angle}: {{  # angle={angle}")
        for pin_num in sorted(pins.keys()):
            x, y = pins[pin_num]
            print(f"        {pin_num}: ({x}, {y}),  # pin{pin_num}")
        print(f"    }},")
    print("}")


if __name__ == "__main__":
    main()
