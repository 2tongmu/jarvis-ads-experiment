from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Any

import yaml

from net_graph_utils import Component, NetGraph, infer_main_backbone, classify_component_basic


@dataclass
class FunctionalGroup:
    name: str
    role: str
    members: List[str]
    lane: str
    anchor_priority: int


@dataclass
class Placeplan:
    design: Dict[str, Any]
    placement_objective: Dict[str, Any]
    functional_groups: List[Dict[str, Any]]
    lanes: List[Dict[str, Any]]
    ordering_constraints: List[Dict[str, Any]]
    spacing_guidance: Dict[str, Any]
    routing_guidance: Dict[str, Any]
    anchor_elements: List[str]
    validation_expectations: List[str]
    review_notes: Dict[str, Any]


def parse_ads_import_net(net_path: Path) -> NetGraph:
    """
    Skeleton parser.
    Replace this with your actual .net parser or import from net_parse.py later.

    Expected current behavior:
    - skip comments/blank lines
    - parse one instance per line
    - infer component name, type, nets, params
    """
    graph = NetGraph()

    for raw_line in net_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("!", "#", ";", "//")):
            continue

        # Placeholder parse logic:
        # Assumption: NAME TYPE NET1 NET2 [NET3 ...] PARAM=VALUE ...
        tokens = line.split()
        if len(tokens) < 4:
            continue

        name = tokens[0]
        ctype = tokens[1]

        nets = []
        params = {}
        for tok in tokens[2:]:
            if "=" in tok:
                k, v = tok.split("=", 1)
                params[k] = v
            else:
                nets.append(tok)

        comp = Component(name=name, ctype=ctype, nets=nets, params=params)
        graph.add_component(comp)

    return graph


def build_functional_groups(graph: NetGraph, backbone: List[str]) -> List[FunctionalGroup]:
    """
    Minimal heuristic grouping for first experiment.
    """
    groups: List[FunctionalGroup] = []

    ports = [c for c in backbone if classify_component_basic(graph.components[c]) == "port"]
    active = [c for c in backbone if classify_component_basic(graph.components[c]) == "active_core"]
    rf_other = [c for c in backbone if classify_component_basic(graph.components[c]) == "rf_or_passive"]

    if ports:
        groups.append(FunctionalGroup("rf_input_group", "input_port", ports[:1], "rf_main", 1))
    switch_members = active + rf_other
    if switch_members:
        groups.append(FunctionalGroup("switch_core_group", "main_switch_core", switch_members, "rf_main", 2))

    control_members = []
    ground_members = []
    sim_members = []
    other_members = []

    backbone_set = set(backbone)
    for name, comp in graph.components.items():
        if name in backbone_set:
            continue
        cls = classify_component_basic(comp)
        if cls == "control_bias":
            control_members.append(name)
        elif cls == "ground_support":
            ground_members.append(name)
        elif cls == "simulation":
            sim_members.append(name)
        else:
            other_members.append(name)

    if control_members:
        groups.append(FunctionalGroup("control_bias_group", "control_bias", control_members, "control_bias", 4))
    if ground_members:
        groups.append(FunctionalGroup("shunt_return_group", "shunt_ground_support", ground_members, "shunt_ground", 5))
    if sim_members:
        groups.append(FunctionalGroup("simulation_group", "simulation_control", sim_members, "simulation", 6))
    if other_members:
        groups.append(FunctionalGroup("support_group", "support_misc", other_members, "rf_main", 7))

    return groups


def make_placeplan(net_path: Path, template_path: Path | None = None) -> Placeplan:
    graph = parse_ads_import_net(net_path)
    backbone = infer_main_backbone(graph)

    groups = build_functional_groups(graph, backbone)

    design = {
        "name": net_path.stem.replace("_ads_import", ""),
        "variant": "auto_generated_placeplan",
        "source_file": str(net_path),
    }

    placement_objective = {
        "summary": "Auto-generated starter placeplan from ADS import netlist.",
        "priorities": [
            "clear_main_rf_path",
            "separate_control_and_bias_from_rf",
            "reduce_ambiguous_symbol_proximity",
            "support_deterministic_ads_build",
            "preserve_logical_meaning",
        ],
    }

    lanes = [
        {"name": "rf_main", "purpose": "Main RF signal path lane", "relative_position": "center"},
        {"name": "control_bias", "purpose": "Control and bias lane", "relative_position": "top"},
        {"name": "shunt_ground", "purpose": "Shunt and ground-support lane", "relative_position": "bottom"},
        {"name": "simulation", "purpose": "Simulation lane", "relative_position": "side"},
    ]

    ordering_constraints = [
        {"type": "left_to_right_rf_flow", "description": "Use left-to-right ordering for the main RF backbone."},
        {"type": "control_near_driven_blocks", "description": "Keep control groups near driven active blocks but off the RF lane."},
    ]

    spacing_guidance = {
        "unrelated_group_spacing": {"level": "large"},
        "branch_point_clearance": {"level": "large"},
        "control_to_rf_lane_spacing": {"level": "large"},
        "unconnected_pin_clearance": {"level": "extra_large"},
    }

    routing_guidance = {
        "main_rf_route": {"style": "mostly_horizontal"},
        "control_route": {"style": "separate_lane_with_vertical_drops"},
        "shunt_return_route": {"style": "vertical_returns_to_lower_lane"},
    }

    anchor_elements = [g.name for g in groups if g.anchor_priority <= 3]

    validation_expectations = [
        "main_rf_path_is_visually_clear",
        "control_and_bias_are_separated_from_rf",
        "unrelated_components_are_not_crowded",
        "placement_plan_preserves_logical_connectivity",
    ]

    review_notes = {
        "status": "auto_generated",
        "inferred_backbone": backbone,
        "parser_note": "Backbone and groups were inferred heuristically. Review before ADS build.",
    }

    return Placeplan(
        design=design,
        placement_objective=placement_objective,
        functional_groups=[asdict(g) for g in groups],
        lanes=lanes,
        ordering_constraints=ordering_constraints,
        spacing_guidance=spacing_guidance,
        routing_guidance=routing_guidance,
        anchor_elements=anchor_elements,
        validation_expectations=validation_expectations,
        review_notes=review_notes,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a starter ADS placeplan from an ADS-import netlist.")
    parser.add_argument("--net", required=True, help="Path to *_ads_import.net")
    parser.add_argument("--out", required=True, help="Output YAML path")
    args = parser.parse_args()

    net_path = Path(args.net)
    out_path = Path(args.out)

    placeplan = make_placeplan(net_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(asdict(placeplan), f, sort_keys=False)

    print(f"[OK] Wrote placeplan to {out_path}")


if __name__ == "__main__":
    main()