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
    p.add_argument("--sw-map", default=None, metavar="SW_MAP_YAML",
                   help="Optional: path to a pre-existing SW annotation YAML "
                        "(e.g. examples/spdt_switch/spdt_switch_sw_map.yaml). "
                        "If omitted and the netlist contains SW elements, "
                        "fet_bias_preprocessor.py is run automatically to generate it. "
                        "Pass this flag only to reuse a previously generated sw_map "
                        "without re-running the preprocessor.")
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


# ── Subcell builder (dependency pre-build) ────────────────────────────────────

def _build_subcell(session, lib, lib_name: str, ws_path: Path,
                   net_path: Path, pdk_name: Optional[str], dry_run: bool) -> None:
    """
    Build a dependency subcell using an already-open ADS session.

    Runs the full 5-stage pipeline for net_path without reopening the workspace.
    Used to pre-build fetbias_sw_gate before the parent SPDT cell.

    Raises on failure (caller handles sys.exit).
    """
    from translator.parser            import parse_research_netlist
    from translator.ir_builder        import build_ir, write_ir
    from translator.ads_mapper        import map_ir_to_buildplan, write_buildplan, load_mapping_config
    from translator.placement_engine  import compute_placement, write_placement
    from translator.placement_checker import check_placement
    from ads_api.cell_ops      import open_or_create_schematic, save_design, commit_design, write_itemdef_ael
    from ads_api.schematic_ops import place_port, place_instance, connect
    from ads_api.symbol_ops    import create_dual_symbol

    output_dir = net_path.parent

    # Stale YAML cleanup
    for suffix in ("_ir.yaml", "_buildplan.yaml", "_placement.yaml"):
        p = output_dir / (net_path.stem + suffix)
        if p.exists() and net_path.stat().st_mtime > p.stat().st_mtime:
            p.unlink()

    # Stages 1-4
    parsed    = parse_research_netlist(net_path)
    cell_name = parsed.cell_name.lower()
    ir        = build_ir(parsed)
    write_ir(ir, output_dir)

    config = load_mapping_config(MAPPING_CONFIG)
    if pdk_name:
        _enable_pdk_override(config, pdk_name)
    plan_bp = map_ir_to_buildplan(ir, config, sw_map=None)
    write_buildplan(plan_bp, output_dir)

    placement = compute_placement(plan_bp)
    write_placement(placement, output_dir)

    for msg in check_placement(plan_bp, placement):
        print(f"    [sub-build check] {msg}")

    if dry_run:
        print(f"    [sub-build] dry-run — skipping ADS build of {cell_name}")
        return

    # Stage 5 — use already-open session, skip workspace setup
    port_angles = {}
    for p in placement.ports:
        if p.name == "GATE":
            port_angles[p.name] = 0.0
        elif p.number == 1 or p.name.startswith("VCTRL"):
            port_angles[p.name] = 180.0
        else:
            port_angles[p.name] = 0.0

    cell, design = open_or_create_schematic(session, lib, cell_name)
    for port in sorted(placement.ports, key=lambda p: p.number):
        place_port(session, design, port.name,
                   x=port.x, y=port.y, angle=port_angles[port.name])
    for inst in placement.instances:
        place_instance(session, design, inst)
    for wire in placement.wires:
        connect(design, wire.points)
    if plan_bp.design_variables:
        design.cell.write_design_variables(plan_bp.design_variables)
    commit_design(session, design)
    save_design(design)
    print(f"    [sub-build] {lib_name}:{cell_name}:schematic  saved")

    create_dual_symbol(session, lib, lib_name, cell, cell_name, design,
                       port_angles=port_angles)
    print(f"    [sub-build] {lib_name}:{cell_name}:symbol     saved")

    if plan_bp.design_variables:
        write_itemdef_ael(ws_path / lib_name / cell_name,
                          cell_name, plan_bp.design_variables)


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

    # ── Auto-preprocessing: detect SW elements → generate sw_map + fetbias ─────
    # If the netlist has SW: elements and no --sw-map was provided, run
    # fet_bias_preprocessor to generate _sw_map.yaml and fetbias_sw_gate.net
    # before entering the main 5-stage pipeline. This keeps the orchestrator
    # interface simple: hand the sub-agent a .net file, get an ADS cell back.
    fetbias_net_path: Optional[Path] = None
    if not args.sw_map:
        from translator.fet_bias_preprocessor import _parse_sw_elements, process_switch_netlist
        raw_sw = _parse_sw_elements(net_path)
        if raw_sw:
            print(f"\n[Pre-Stage] {len(raw_sw)} SW element(s) detected "
                  "— running fet_bias_preprocessor...")
            try:
                process_switch_netlist(net_path)
            except Exception as exc:
                print(f"  [ERROR] Preprocessor failed: {exc}")
                _status("failed", 0, [], "Fix netlist or PDK config and retry.", str(exc))
                sys.exit(1)
            stem = net_path.stem.replace("_research", "")
            sw_map_auto = net_path.parent / f"{stem}_sw_map.yaml"
            if sw_map_auto.exists():
                args.sw_map = str(sw_map_auto)
                print(f"  [sw_map]  auto-generated: {sw_map_auto.name}")
            fetbias_net = net_path.parent / "fetbias_sw_gate" / "fetbias_sw_gate_research.net"
            if fetbias_net.exists():
                fetbias_net_path = fetbias_net
                print(f"  [fetbias] auto-generated: fetbias_sw_gate/fetbias_sw_gate_research.net")
    else:
        # sw_map provided explicitly; fetbias may already exist alongside parent
        fetbias_net = net_path.parent / "fetbias_sw_gate" / "fetbias_sw_gate_research.net"
        if fetbias_net.exists():
            fetbias_net_path = fetbias_net

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
    from translator.ads_mapper        import map_ir_to_buildplan, write_buildplan, load_mapping_config, load_sw_map
    from translator.placement_engine  import compute_placement, write_placement
    from translator.placement_checker import check_placement

    # ── Pre-Stage 1: Detect and clean stale YAML files ────────────────────────
    # If netlist is newer than cached YAMLs, delete them to force regeneration.
    # This ensures YAML artifacts reflect the latest netlist (especially after
    # netlist topology changes like 2-port → 1-port).
    def _clean_stale_yamls(net_path: Path, output_dir: Path) -> None:
        """Delete stale _ir.yaml, _buildplan.yaml, _placement.yaml if netlist is newer."""
        net_mtime = net_path.stat().st_mtime
        cell_stem = net_path.stem
        
        yaml_files = [
            output_dir / f"{cell_stem}_ir.yaml",
            output_dir / f"{cell_stem}_buildplan.yaml",
            output_dir / f"{cell_stem}_placement.yaml",
        ]
        
        for yaml_file in yaml_files:
            if yaml_file.exists():
                yaml_mtime = yaml_file.stat().st_mtime
                if net_mtime > yaml_mtime:
                    print(f"  [stale] {yaml_file.name} (netlist is newer)")
                    yaml_file.unlink()
    
    print("\n[Pre-Stage 1] Checking for stale YAML artifacts...")
    _clean_stale_yamls(net_path, output_dir)

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
        # Phase 3: may have V (voltage sources) or SW (switches).
        # SW elements are handled by the auto-preprocessor above.
        # V elements (vsource/fetbias) need no sw_map.
        has_sw = any(c.type == "SW" for c in ir.components)
        if has_sw and not args.sw_map:
            # Should not reach here: preprocessor above sets args.sw_map.
            # Guard for edge case (e.g. preprocessor write failed).
            errors.append(
                "SW elements present but sw_map could not be generated. "
                "Check PDK config paths and retry."
            )

    # ── Stage 3: Map to build plan ────────────────────────────────────────────
    print("\n[Stage 3] Mapping IR to ADS build plan...")
    try:
        config  = load_mapping_config(MAPPING_CONFIG)
        if pdk_name:
            _enable_pdk_override(config, pdk_name)
        sw_map_data = load_sw_map(Path(args.sw_map)) if args.sw_map else None
        if sw_map_data:
            print(f"  [sw_map] loaded {len(sw_map_data)} SW mappings from {args.sw_map}")
        plan_bp = map_ir_to_buildplan(ir, config, sw_map=sw_map_data)
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
        if not w.startswith("[INFO]"):   # [INFO] messages are informational, not errors
            errors.append(w)
    print(f"  written   : {pl_path}")

    # ── Stage 4b: Connectivity check ─────────────────────────────────────────
    print("\n[Stage 4b] Checking placement connectivity...")
    check_errors = check_placement(plan_bp, placement)
    if check_errors:
        for msg in check_errors:
            print(f"  {msg}")
            errors.append(msg)
        print(f"  connectivity: {len(check_errors)} issue(s) found")
    else:
        print("  connectivity: OK — all pins connected")

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
    from ads_api.cell_ops      import open_or_create_schematic, save_design, commit_design, write_itemdef_ael
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

    # ── Pre-build fetbias_sw_gate if this cell needs it ───────────────────────
    # The build plan may reference net2ads_lib:fetbias_sw_gate as a subcell.
    # If that cell doesn't exist in the library yet, build it now using the
    # already-open session (no second workspace open needed).
    needs_fetbias = any(
        bi.ads_lib == "net2ads_lib" and bi.ads_cell == "fetbias_sw_gate"
        for bi in plan_bp.instances
    )
    if needs_fetbias:
        if lib.cell_exists("fetbias_sw_gate"):
            print("  [fetbias] fetbias_sw_gate already in library — reusing")
        elif fetbias_net_path:
            print("  [fetbias] Building fetbias_sw_gate dependency...")
            try:
                _build_subcell(session, lib, lib_name, ws_path,
                               fetbias_net_path, None, dry_run)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                _status("partial", 3, outputs,
                        "fetbias_sw_gate pre-build failed — check output above.", str(exc))
                sys.exit(1)
        else:
            print("  [ERROR] fetbias_sw_gate not in library and netlist not found.")
            _status("failed", 3, outputs,
                    "Re-run without --sw-map to trigger auto-preprocessing, "
                    "which generates fetbias_sw_gate_research.net alongside the parent netlist.",
                    "fetbias_sw_gate missing")
            sys.exit(1)

    # Port facing directions:
    #   angle=180 (left-facing): RF input P1, VCTRL bias control pins
    #   angle=0   (right-facing): RF outputs (P2, P3, ...), GATE pin on fetbias subcell
    # GATE is port 1 on fetbias_sw_gate but connects to the FET gate on its RIGHT side.
    # The dual symbol places it at x=symbol_width=2.0 when angle=0, so that
    # instance at (gate_x-2.0, gate_y) puts GATE at (gate_x, gate_y) = FET gate. ✓
    port_angles = {}
    for p in placement.ports:
        if p.name == "GATE":
            port_angles[p.name] = 0.0    # right-side: connects to FET gate to the right
        elif p.number == 1 or p.name.startswith("VCTRL"):
            port_angles[p.name] = 180.0  # left-side: RF input or bias control
        else:
            port_angles[p.name] = 0.0    # right-side: RF outputs

    try:
        cell, design = open_or_create_schematic(session, lib, cell_name)

        for port in sorted(placement.ports, key=lambda p: p.number):
            place_port(session, design, port.name,
                       x=port.x, y=port.y, angle=port_angles[port.name])

        for inst in placement.instances:
            place_instance(session, design, inst)

        for wire in placement.wires:
            connect(design, wire.points)

        # Write design variables before commit (e.g. Rs, Cp for fetbias cell)
        if plan_bp.design_variables:
            design.cell.write_design_variables(plan_bp.design_variables)
            print(f"  [design vars] {plan_bp.design_variables}")

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

        # Generate itemdef.ael to expose design variables as user parameters
        # This enables the design variables (e.g. Rs, Cp) to appear as editable
        # "Component Parameters" when the cell is instantiated in a parent schematic.
        if plan_bp.design_variables:
            cell_dir = Path(args.workspace) / lib_name / cell_name
            write_itemdef_ael(cell_dir, cell_name, plan_bp.design_variables)

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
