"""
ads_api/probe_pin_offsets.py
=============================
One-time ADS probe script: measures actual pin positions for each component
registered in ads_pdk/pin_offsets.yaml and writes the results back.

Run this whenever a new component is added to ads_mapping.yaml or
when the ADS version changes and pin geometry may have shifted.

Must be run with the ADS-bundled Python interpreter:
  C:\\Program Files\\Keysight\\ADS2026_Update1.2\\tools\\python\\python.exe

Usage:
    python ads_api/probe_pin_offsets.py \\
        --workspace <path_to_any_ads_workspace> \\
        --lib net2ads_lib \\
        [--cells ads_rflib:R ads_sources:V_DC ...]   # subset to probe; all if omitted

Output:
    Updates ads_pdk/pin_offsets.yaml in-place, setting source="probed" and
    recording measured offsets. Existing entries marked source="confirmed" are
    NOT overwritten (they represent manually verified data).

How it works:
    For each (lib, cell, angle) combination registered in pin_offsets.yaml:
      1. Place a single test instance at (0.0, 0.0) in a throwaway schematic.
      2. Query instance.pins to get the schematic-coordinates of each pin.
      3. Pin offset = (pin.x - 0.0, pin.y - 0.0) = (pin.x, pin.y).
      4. Compare with registered offsets; report discrepancies.
      5. Update the YAML entry with measured values.
"""

import argparse
import sys
from pathlib import Path

SUBAGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUBAGENT_DIR))

PIN_OFFSETS_YAML = SUBAGENT_DIR / "ads_pdk" / "pin_offsets.yaml"
PROBE_CELL_NAME  = "_probe_tmp"   # throwaway cell used during probing
PROBE_LIB_NAME   = "net2ads_lib"


def _parse_args():
    p = argparse.ArgumentParser(
        description="Probe ADS pin positions and update pin_offsets.yaml."
    )
    p.add_argument("--workspace", required=True,
                   help="Path to an ADS workspace (must already exist)")
    p.add_argument("--lib", default=PROBE_LIB_NAME,
                   help=f"Library to use for probe instances (default: {PROBE_LIB_NAME})")
    p.add_argument("--cells", nargs="*", default=None,
                   metavar="lib:cell",
                   help="Subset of cells to probe, e.g. 'ads_rflib:R ads_sources:V_DC'. "
                        "If omitted, all cells in pin_offsets.yaml are probed.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print measured offsets but do not update pin_offsets.yaml")
    return p.parse_args()


def _load_pin_offsets() -> dict:
    try:
        import yaml
    except ImportError:
        raise RuntimeError("PyYAML not available — install with: pip install pyyaml")
    with open(PIN_OFFSETS_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_pin_offsets(data: dict) -> None:
    import yaml
    with open(PIN_OFFSETS_YAML, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    print(f"[probe] updated: {PIN_OFFSETS_YAML}")


def _setup_probe_env(ads_dir: str) -> tuple:
    """Import ADS Python modules. Returns (de, db) modules."""
    import os
    sys.path.insert(0, str(Path(ads_dir) / "tools" / "python" / "packages"))
    os.environ.setdefault("HPEESOF_DIR", ads_dir)
    try:
        import keysight.ads.de as de
        from keysight.ads.de import db_uu as db
        from keysight.ads.de._pde.db import DesignMode
        return de, db, DesignMode
    except ImportError as e:
        raise ImportError(
            f"ADS Python packages not available: {e}\n"
            "Run with the ADS-bundled Python interpreter."
        ) from e


def _probe_component(de, db, DesignMode, design, ads_lib: str, ads_cell: str,
                     angle: float, registered_pins: list) -> dict:
    """
    Place one instance at (0,0) with given angle, read back pin positions.

    Returns dict: {pin_id: [dx, dy]} measured offsets.
    """
    lcv = de.LCVName(ads_lib, ads_cell, "symbol")
    try:
        inst = design.add_instance(lcv, (0.0, 0.0), name="_probe_inst", angle=angle)
    except Exception as exc:
        print(f"  [probe] FAILED to place {ads_lib}:{ads_cell} at angle={angle}: {exc}")
        return {}

    measured = {}
    try:
        pins = list(inst.pins)
        print(f"  [probe] {ads_lib}:{ads_cell} angle={angle:6.1f} → {len(pins)} pins")
        for pin in pins:
            try:
                pin_x = round(float(pin.position.x), 6)
                pin_y = round(float(pin.position.y), 6)
                pin_name = str(pin.name)
                measured[pin_name] = [pin_x, pin_y]
                print(f"           {pin_name:12s}  ({pin_x:+.4f}, {pin_y:+.4f})")
            except Exception as exc2:
                print(f"           pin read error: {exc2}")
    except Exception as exc:
        print(f"  [probe] could not read pins for {ads_lib}:{ads_cell}: {exc}")
    finally:
        try:
            inst.destroy()
        except Exception:
            pass

    return measured


def _match_to_registered(measured: dict, registered_pins: list, angle: float) -> list:
    """
    Map measured pin dict to registered pin order.

    ADS pin names (e.g. "pin1", "pin2") may differ from the semantic IDs
    in pin_offsets.yaml (e.g. "P1", "drain"). We match by position order
    (sorted by x then y) when names don't align.

    Returns list of [dx, dy] in registered pin order.
    """
    if not measured:
        return []

    # Try direct name match first
    result = []
    for reg_pin in registered_pins:
        pid = reg_pin["id"]
        if pid in measured:
            result.append(measured[pid])
        else:
            result.append(None)

    # If any are unmatched, fall back to position-order matching
    if any(v is None for v in result):
        sorted_pos = sorted(measured.values(), key=lambda p: (p[1], p[0]))  # sort y then x
        for i, v in enumerate(result):
            if v is None and i < len(sorted_pos):
                result[i] = sorted_pos[i]

    return result


def main():
    args = _parse_args()

    # ── Load pin offsets registry ─────────────────────────────────────────────
    data = _load_pin_offsets()
    entries = data.get("pin_offsets", {})

    # ── Filter to requested cells ─────────────────────────────────────────────
    probe_keys = set(args.cells) if args.cells else set(entries.keys())
    entries_to_probe = {k: v for k, v in entries.items() if k in probe_keys}

    if not entries_to_probe:
        print("[probe] No matching cells to probe.")
        sys.exit(0)

    print(f"[probe] Will probe {len(entries_to_probe)} cell(s):")
    for key in entries_to_probe:
        print(f"  {key}")

    # ── ADS setup ─────────────────────────────────────────────────────────────
    ads_dir = r"C:\Program Files\Keysight\ADS2026_Update1.2"
    import warnings as _warnings
    de, db, DesignMode = _setup_probe_env(ads_dir)

    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        ws = de.open_workspace(args.workspace)
    print(f"[probe] workspace: {ws}")

    lib = de.get_open_library(args.lib)

    # Create / reuse probe cell
    if lib.cell_exists(PROBE_CELL_NAME):
        probe_cell = lib.cell(PROBE_CELL_NAME)
    else:
        probe_cell = de.Cell.create(lib, PROBE_CELL_NAME)

    if probe_cell.view_exists("schematic"):
        probe_cell.delete_view("schematic")
    sch_view  = de.View.create(probe_cell, "schematic", "schematic")
    design    = sch_view.get_design(DesignMode.WRITE)

    # ── Probe each entry ──────────────────────────────────────────────────────
    updated = 0
    discrepancies = []

    for key, entry in entries_to_probe.items():
        # Skip confirmed entries (manually verified — don't overwrite)
        if entry.get("source") == "confirmed" and not args.dry_run:
            print(f"\n[probe] SKIP {key} (source=confirmed — not overwriting)")
            continue

        parts = key.split(":", 1)
        if len(parts) != 2:
            print(f"[probe] SKIP {key} — expected 'lib:cell' key format")
            continue
        ads_lib, ads_cell = parts

        registered_pins = entry.get("pins", [])
        offsets_by_angle = entry.get("offsets_by_angle", {})

        print(f"\n[probe] {key}")
        new_offsets = {}

        for angle_str, registered_offsets in offsets_by_angle.items():
            angle = float(angle_str)
            measured = _probe_component(
                de, db, DesignMode, design, ads_lib, ads_cell, angle, registered_pins
            )
            if not measured:
                print(f"  [probe] angle={angle}: no data — keeping registered values")
                new_offsets[angle_str] = registered_offsets
                continue

            matched = _match_to_registered(measured, registered_pins, angle)

            # Check for discrepancies
            for i, (reg, meas) in enumerate(zip(registered_offsets, matched)):
                if meas is None:
                    continue
                dx_diff = abs(reg[0] - meas[0])
                dy_diff = abs(reg[1] - meas[1])
                if dx_diff > 0.01 or dy_diff > 0.01:
                    pid = registered_pins[i]["id"] if i < len(registered_pins) else f"pin{i}"
                    msg = (f"  DISCREPANCY {key} angle={angle} pin '{pid}': "
                           f"registered={reg} measured={meas}")
                    print(f"  ⚠  {msg}")
                    discrepancies.append(msg)

            new_offsets[angle_str] = [m if m is not None else r
                                      for m, r in zip(matched, registered_offsets)]

        if not args.dry_run:
            entry["offsets_by_angle"] = new_offsets
            entry["source"] = "probed"
            updated += 1

    # ── Save updated YAML ─────────────────────────────────────────────────────
    if not args.dry_run and updated > 0:
        _save_pin_offsets(data)
        print(f"\n[probe] updated {updated} entr(ies) in pin_offsets.yaml")
    elif args.dry_run:
        print("\n[probe] dry-run — pin_offsets.yaml not modified")

    if discrepancies:
        print("\n[probe] DISCREPANCIES FOUND (registered vs measured):")
        for d in discrepancies:
            print(f"  {d}")
        print("  Update pin_offsets.yaml if ADS measurements are authoritative.")
    else:
        print("\n[probe] All probed offsets match registered values.")

    # Clean up probe cell
    try:
        design.save_design()
        probe_cell.delete_view("schematic")
    except Exception:
        pass


if __name__ == "__main__":
    main()
