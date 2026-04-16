"""
net2ads.py
==========
Generic entry point: translate any passive-component research netlist (.net)
into an ADS schematic cell + dual symbol.

Full pipeline: parse -> IR -> map -> placement -> ADS build

Usage:
    python net2ads.py <netlist.net> --workspace <path> [options]

    Options:
      --workspace PATH   ADS workspace directory (required unless --dry-run)
      --lib NAME         Target library name (default: net2ads_lib)
      --output-dir DIR   Where to write artifact YAMLs (default: netlist parent dir)
      --dry-run          Run pipeline stages 1-4, write artifacts; skip ADS API

Supported passive elements — Phase 1:
    R (resistor), L (inductor), C (capacitor)

Extension:
    To add a new component type, register a handler in
    ads_api/schematic_ops.py::_PASSIVE_PLACER_REGISTRY.

Output artifacts (written at Stage 4 regardless of --dry-run):
    <output_dir>/<cell_name>_ir.yaml
    <output_dir>/<cell_name>_buildplan.yaml
    <output_dir>/<cell_name>_placement.yaml

ADS outputs (Stage 5, skipped in --dry-run):
    <lib>:<cell_name>:schematic
    <lib>:<cell_name>:symbol

Status block (stdout, end of every run):
    ================================================================
    status: success | partial | failed
    stage_completed: 1 | 2 | 3
    outputs:
      - <path>
    next_action: <instruction>
    errors: none | <description>
    ================================================================
"""

import argparse
import sys
from pathlib import Path

# ── Subagent root on sys.path ──────────────────────────────────────────────────
SUBAGENT_DIR   = Path(__file__).resolve().parent
MAPPING_CONFIG = SUBAGENT_DIR / "schemas" / "ads_mapping.yaml"

sys.path.insert(0, str(SUBAGENT_DIR))


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(
        description="net2ads: translate a research netlist (.net) to an ADS schematic cell.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("netlist",
                   help="Path to the research netlist file (*.net)")
    p.add_argument("--workspace", default=None,
                   help="ADS workspace directory (required unless --dry-run)")
    p.add_argument("--lib", default="net2ads_lib",
                   help="Target library name in the workspace (default: net2ads_lib)")
    p.add_argument("--output-dir", default=None,
                   help="Directory for intermediate YAML artifacts "
                        "(default: same directory as the netlist)")
    p.add_argument("--dry-run", action="store_true",
                   help="Run pipeline stages 1-4 and write artifacts; skip ADS API calls")
    return p.parse_args()


# ── Workspace file setup ───────────────────────────────────────────────────────

def _setup_workspace_files(ws_path: Path, lib_name: str) -> Path:
    """
    Ensure the workspace directory structure is ready for de.open_workspace().

    Creates cds.lib, lib.defs (with ads_rflib + target library), and the
    library directory (with cdsinfo.tag) if any are missing.  Safe to call
    on an existing workspace — skips any part that is already in place.

    Returns the library subdirectory path.
    """
    ws_path.mkdir(parents=True, exist_ok=True)
    lib_path = ws_path / lib_name

    cds_lib = ws_path / "cds.lib"
    if not cds_lib.exists():
        cds_lib.write_text("softinclude lib.defs\n", encoding="utf-8")
        print(f"[workspace] wrote cds.lib")

    lib_defs_path = ws_path / "lib.defs"
    lib_defs_needed = (
        "INCLUDE $HPEESOF_DIR/oalibs/analog_rf.defs\n"
        f"DEFINE {lib_name} {lib_name}\n"
        f"ASSIGN {lib_name} libMode shared\n"
    )
    current = lib_defs_path.read_text(encoding="utf-8") if lib_defs_path.exists() else ""
    if f"DEFINE {lib_name}" not in current:
        lib_defs_path.write_text(lib_defs_needed, encoding="utf-8")
        print(f"[workspace] wrote lib.defs (registered {lib_name})")

    if not lib_path.exists():
        lib_path.mkdir()
        (lib_path / "cdsinfo.tag").write_text("CDSLIBRARY\nEDITION 5.0\n", encoding="utf-8")
        print(f"[library] created directory: {lib_path}")

    return lib_path


# ── Status block ───────────────────────────────────────────────────────────────

def _status(status: str, stage: int, outputs: list, next_action: str, errors) -> None:
    print()
    print("=" * 66)
    print(f"status: {status}")
    print(f"stage_completed: {stage}")
    if outputs:
        print("outputs:")
        for o in outputs:
            print(f"  - {o}")
    print(f"next_action: {next_action}")
    print(f"errors: {'none' if not errors else ('; '.join(errors) if isinstance(errors, list) else str(errors))}")
    print("=" * 66)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    args    = _parse_args()
    dry_run = args.dry_run

    net_path = Path(args.netlist).resolve()
    if not net_path.exists():
        print(f"[ERROR] Netlist not found: {net_path}")
        _status("failed", 0, [], "Provide a valid netlist path and retry.", str(net_path))
        sys.exit(1)

    if not dry_run and args.workspace is None:
        print("[ERROR] --workspace is required unless --dry-run is set.")
        print("        Example: python net2ads.py my.net --workspace C:/ads/my_workspace")
        sys.exit(1)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else net_path.parent
    lib_name   = args.lib
    outputs: list = []
    errors:  list = []

    print()
    print("=" * 66)
    print("  net2ads pipeline")
    print(f"  netlist    : {net_path.name}")
    print(f"  library    : {lib_name}")
    print(f"  output dir : {output_dir}")
    print(f"  dry-run    : {dry_run}")
    print("=" * 66)

    # ── Translator imports ────────────────────────────────────────────────────
    from translator.parser           import parse_research_netlist
    from translator.ir_builder       import build_ir, write_ir
    from translator.ads_mapper       import map_ir_to_buildplan, write_buildplan, load_mapping_config
    from translator.placement_engine import compute_placement, write_placement

    # ── Stage 1: Parse ────────────────────────────────────────────────────────
    print("\n[Stage 1] Parsing netlist...")
    try:
        parsed = parse_research_netlist(net_path)
    except Exception as exc:
        _status("failed", 0, [], "Fix netlist syntax and retry.", str(exc))
        sys.exit(1)

    cell_name = parsed.cell_name.lower()
    print(f"  cell       : {cell_name}")
    print(f"  ports      : {parsed.subckt_ports}")
    print(f"  components : {len(parsed.components)}")
    for w in parsed.warnings:
        print(f"  [warn] {w}")
        errors.append(w)

    # ── Stage 2: Build IR ─────────────────────────────────────────────────────
    print("\n[Stage 2] Building intermediate representation...")
    try:
        ir = build_ir(parsed)
    except Exception as exc:
        _status("failed", 1, [], "Fix IR build error and retry.", str(exc))
        sys.exit(1)

    ir_path = write_ir(ir, output_dir)
    outputs.append(str(ir_path))
    print(f"  phase required : {ir.phase_required}")
    print(f"  series={ir.metadata.series_count}  shunt={ir.metadata.shunt_count}"
          f"  tline={ir.metadata.tline_count}  switch={ir.metadata.switch_count}")
    print(f"  backbone  : {ir.graph.backbone}")
    print(f"  written   : {ir_path}")

    if ir.phase_required > 1:
        errors.append(
            f"Netlist requires Phase {ir.phase_required} elements "
            f"(TLIN/SW) — only passive R/L/C are fully supported."
        )

    # ── Stage 3: Map to build plan ────────────────────────────────────────────
    print("\n[Stage 3] Mapping IR to ADS build plan...")
    try:
        config  = load_mapping_config(MAPPING_CONFIG)
        plan_bp = map_ir_to_buildplan(ir, config)
    except Exception as exc:
        _status("failed", 1, outputs, "Fix mapping error and retry.", str(exc))
        sys.exit(1)

    bp_path = write_buildplan(plan_bp, output_dir)
    outputs.append(str(bp_path))
    print(f"  instances : {len(plan_bp.instances)}")
    for w in plan_bp.warnings:
        print(f"  [warn] {w}")
        if "UNCONFIRMED" in w.upper():
            errors.append(w)
    print(f"  written   : {bp_path}")

    # ── Stage 4: Placement ────────────────────────────────────────────────────
    print("\n[Stage 4] Computing placement...")
    try:
        placement = compute_placement(plan_bp)
    except Exception as exc:
        _status("failed", 2, outputs, "Fix placement error and retry.", str(exc))
        sys.exit(1)

    pl_path = write_placement(placement, output_dir)
    outputs.append(str(pl_path))
    for inst in placement.instances:
        print(f"  {inst.role:<8} {inst.id:<28} @ ({inst.x:6.3f}, {inst.y:5.1f})"
              f"  angle={inst.angle:6.1f}  {inst.ads_lib}:{inst.ads_cell}"
              + (f"  {inst.params}" if inst.params else ""))
    for wire in placement.wires:
        print(f"  wire     {wire.id}  {wire.points}  [{wire.note}]")
    for w in placement.warnings:
        print(f"  [warn] {w}")
        errors.append(w)
    print(f"  written   : {pl_path}")

    if dry_run:
        _status(
            status="success" if not errors else "partial",
            stage=3,
            outputs=outputs,
            next_action=(
                f"Run without --dry-run to build ADS cell {lib_name}:{cell_name}:\n"
                f"  python net2ads.py {net_path} --workspace <path> --lib {lib_name}"
            ),
            errors=errors,
        )
        return

    # ── Stage 5: ADS Build ────────────────────────────────────────────────────
    print("\n[Stage 5] Building ADS cell...")

    from ads_api.ads_session   import get_ads_session
    from ads_api.workspace_ops import open_workspace
    from ads_api.cell_ops      import open_or_create_schematic, save_design, commit_design
    from ads_api.schematic_ops import place_port, place_instance, connect
    from ads_api.symbol_ops    import create_dual_symbol

    try:
        session  = get_ads_session()
        ws_path  = Path(args.workspace).resolve()
        _setup_workspace_files(ws_path, lib_name)
        open_workspace(session, str(ws_path))
        lib = session.de.get_open_library(lib_name)
        print(f"  [ads] workspace: {ws_path}")
        print(f"  [ads] library  : {lib_name}")
    except Exception as exc:
        _status("partial", 3, outputs,
                "Fix ADS session / workspace setup and retry.", str(exc))
        sys.exit(1)

    port_angles = {p.name: (180.0 if p.number == 1 else 0.0) for p in placement.ports}

    try:
        cell, design = open_or_create_schematic(session, lib, cell_name)

        for port in sorted(placement.ports, key=lambda p: p.number):
            place_port(session, design, port.name,
                       x=port.x, y=port.y, angle=port_angles[port.name])

        for inst in placement.instances:
            place_instance(session, design, inst)

        for wire in placement.wires:
            connect(design, wire.points)

        # CRITICAL FIX: Commit transaction to finalize all instances in OpenAccess.
        # Without this, instances are not registered in the database and will be
        # invisible to the ADS netlister (causing open-circuit simulation).
        # See ads_build_spdt_pdk.py for confirmed pattern.
        commit_design(session, design)
        save_design(design)
        print(f"  [schematic] {lib_name}:{cell_name}:schematic  saved")

        create_dual_symbol(session, lib, lib_name, cell, cell_name, design,
                           port_angles=port_angles)
        print(f"  [symbol]    {lib_name}:{cell_name}:symbol     saved")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        _status("partial", 3, outputs,
                "ADS build failed — check output above.", str(exc))
        sys.exit(1)

    _status(
        status="success" if not errors else "partial",
        stage=3,
        outputs=outputs + [
            f"{lib_name}:{cell_name}:schematic",
            f"{lib_name}:{cell_name}:symbol",
        ],
        next_action=(
            f"Open ADS GUI and verify {lib_name}:{cell_name} schematic and symbol.\n"
            f"  Workspace: {args.workspace}"
        ),
        errors=errors,
    )


if __name__ == "__main__":
    main()
