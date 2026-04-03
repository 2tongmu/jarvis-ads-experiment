from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Any

import yaml


@dataclass
class PlacementGrid:
    x_step: int = 120
    y_rf: int = 0
    y_control: int = 140
    y_shunt: int = -140
    y_sim: int = 260


LANE_TO_Y = {
    "rf_main": 0,
    "control_bias": 140,
    "shunt_ground": -140,
    "simulation": 260,
}


def load_placeplan(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def assign_group_anchor_positions(placeplan: Dict[str, Any], grid: PlacementGrid) -> Dict[str, Tuple[int, int]]:
    groups = placeplan.get("functional_groups", [])
    groups_sorted = sorted(groups, key=lambda g: g.get("anchor_priority", 999))

    anchors: Dict[str, Tuple[int, int]] = {}
    x = 0
    for g in groups_sorted:
        lane = g["lane"]
        y = LANE_TO_Y.get(lane, 0)
        anchors[g["name"]] = (x, y)
        x += grid.x_step * 2
    return anchors


def expand_instance_positions(placeplan: Dict[str, Any], anchors: Dict[str, Tuple[int, int]], grid: PlacementGrid) -> Dict[str, Tuple[int, int]]:
    """
    Expand group anchors into per-instance coordinates.
    Very basic first-pass logic:
    - place group members horizontally around the anchor
    """
    inst_positions: Dict[str, Tuple[int, int]] = {}

    for group in placeplan.get("functional_groups", []):
        gx, gy = anchors[group["name"]]
        members = group.get("members", [])
        for idx, inst in enumerate(members):
            inst_positions[inst] = (gx + idx * grid.x_step, gy)

    return inst_positions


def emit_ads_build_plan(placeplan: Dict[str, Any], inst_positions: Dict[str, Tuple[int, int]]) -> Dict[str, Any]:
    """
    This output can be consumed by your future ADS Python builder.
    """
    return {
        "design": placeplan.get("design", {}),
        "instances": [
            {
                "name": inst,
                "x": xy[0],
                "y": xy[1],
            }
            for inst, xy in inst_positions.items()
        ],
        "routing_guidance": placeplan.get("routing_guidance", {}),
        "anchor_elements": placeplan.get("anchor_elements", []),
        "validation_expectations": placeplan.get("validation_expectations", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a placeplan into ADS build coordinates.")
    parser.add_argument("--placeplan", required=True, help="Path to placeplan YAML")
    parser.add_argument("--out", required=True, help="Output YAML/JSON-like plan path")
    args = parser.parse_args()

    placeplan = load_placeplan(Path(args.placeplan))
    grid = PlacementGrid()

    anchors = assign_group_anchor_positions(placeplan, grid)
    inst_positions = expand_instance_positions(placeplan, anchors, grid)
    build_plan = emit_ads_build_plan(placeplan, inst_positions)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(build_plan, f, sort_keys=False)

    print(f"[OK] Wrote ADS build plan to {out_path}")


if __name__ == "__main__":
    main()