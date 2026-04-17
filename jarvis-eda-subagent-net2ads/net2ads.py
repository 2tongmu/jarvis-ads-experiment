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
from typing import Optional

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
    p.add_argument("--pdk", default=None, metavar="PDK_NAME",
                   help="PDK name for component mapping and workspace setup "
                        "(e.g. WIN_PP1029_DESIGN_KIT). "
                        "Enables pdk_override in ads_mapping.yaml so TLIN maps to the "
                        "PDK microstrip cell. PDK lib.defs must exist at "
                        "ads_pdk/<PDK_NAME>/lib.defs relative to the net2ads root.")
    return p.parse_args()


# ── PDK lib.defs resolution ───────────────────────────────────────────────────

def _resolve_pdk_lib_defs(pdk_name: str) -> Optional[Path]:
    """
    Find the PDK lib.defs file for a given PDK name.

    Search order:
      1. <subagent_root>/ads_pdk/<pdk_name>/lib.defs   (local install)
      2. pdk_lib_defs entry in pdk_configs/<pdk_name>_core.yaml  (Jarvis path)

    Returns the resolved Path, or None if not found.
    """
    # 1. Local install path (relative to this script)
    local_path = SUBAGENT_DIR / "ads_pdk" / pdk_name / "lib.defs"
    if local_path.exists():
        return local_path

    # 2. Jarvis path from core.yaml
    core_yaml = SUBAGENT_DIR / "ads_pdk" / "pdk_configs" / f"{pdk_name}_core.yaml"
    if core_yaml.exists():
        try:
            import yaml as _yaml
            with open(core_yaml, encoding="utf-8") as f:
                cfg = _yaml.safe_load(f)
            jarvis_defs = cfg.get("pdk_lib_defs", "")
            if jarvis_defs and Path(jarvis_defs).exists():
                return Path(jarvis_defs)
        except Exception:
            pass

    return None


def _enable_pdk_override(config: dict, pdk_name: str) -> None:
    """
    Patch the loaded mapping config to enable pdk_override for TLIN entries
    that match the given PDK name.

    Modifies config in-place.
    """
    for entry in config.get("component_map", []):
        if entry.get("research_type", "").upper() == "TLIN":
            override = entry.get("pdk_override", {})
            if override.get("ads_lib") == pdk_name:
                override["enabled"] = True
                print(f"[mapping] enabled pdk_override for TLIN -> {pdk_name}:{override.get('ads_cell')}")


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
    pdk_name = args.pdk   # may be None

    net_path = Path(args.netlist).resolve()
    if not net_path.exists():
        print(f"[ERROR] Netlist not found: {net_path}")
        _status("failed", 0, [], "Provide a valid netlist path and retry.", str(net_path))
        sys.exit(1)

    if not dry_run and args.workspace is None:
        print("[ERROR] --workspace is required unless --dry-run is set.")
        print("        Example: python net2ads.py my.net --workspace C:/ads/my_workspace")
        sys.exit(1)

    # Resolve PDK lib.defs when --pdk is specified
    pdk_lib_defs: Optional[Path] = None
    if pdk_name:
        pdk_lib_defs = _resolve_pdk_lib_defs(pdk_name)
        if pdk_lib_defs is None and not dry_run:
            print(f"[ERROR] PDK lib.defs not found for '{pdk_name}'.")
            print(f"  Looked in: {SUBAGENT_DIR / 'ads_pdk' / pdk_name / 'lib.defs'}")
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
    print(f"  pdk        : {pdk_name or '(none — default ADS libs)'}")
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

    if ir.phase_required == 2 and not pdk_name:
        errors.append(
            f"Netlist has TLIN elements (Phase 2). Use --pdk to map them to a PDK "
            "microstrip component, or run without --pdk to use ideal TLIN (UNCONFIRMED)."
        )
    elif ir.phase_required > 2:
        errors.append(
            f"Netlist requires Phase {ir.phase_required} elements (SW) — not yet supported."
        )

    # ── Stage 3: Map to build plan ────────────────────────────────────────────
    print("\n[Stage 3] Mapping IR to ADS build plan...")
    try:
        config  = load_mapping_config(MAPPING_CONFIG)
        if pdk_name:
            _enable_pdk_override(config, pdk_name)
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
    from ads_api.workspace_ops import open_workspace, open_workspace_with_pdk
    from ads_api.cell_ops      import open_or_create_schematic, save_design, commit_design
    from ads_api.schematic_ops import place_port, place_instance, connect
    from ads_api.symbol_ops    import create_dual_symbol

    try:
        session  = get_ads_session()
        ws_path  = Path(args.workspace).resolve()

        if pdk_name and pdk_lib_defs:
            # PDK workspace: pre-write lib.defs with PDK include, then open
            open_workspace_with_pdk(
                session, str(ws_path), str(pdk_lib_defs), lib_name
            )
        else:
            # Standard workspace (Phase 1 pattern)
            _setup_workspace_files(ws_path, lib_name)
            open_workspace(session, str(ws_path))

        lib = session.de.get_open_library(lib_name)
        print(f"  [ads] workspace: {ws_path}")
        print(f"  [ads] library  : {lib_name}")
        if pdk_name:
            print(f"  [ads] PDK      : {pdk_name}")
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
