#!/usr/bin/env python3
"""
check_netlist.py — ADS generated netlist connectivity checker
Part of the ads-schematic-checker skill.

Usage:
    python check_netlist.py path/to/generated.net

Exit code: 0 = all pass, 1 = failures found
"""

import sys
import re
from collections import defaultdict
from pathlib import Path


def parse_netlist(path):
    """Parse ADS-generated netlist into component list.
    Returns list of (type, name, nodes, params) tuples.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    components = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#") or line.startswith("\\"):
            continue
        # Skip keyword-only lines
        if line.startswith("Options") or line.startswith("SweepPlan") or \
           line.startswith("OutputPlan") or line.startswith("Component"):
            continue

        # Match: Type:Name  node1 node2 ... param=val ...
        # Also handles quoted type: "PP1029_CPW_PDK":Q1a  ...
        m = re.match(r'^(?:"([^"]+)"|(\w+)):(\w+)\s+(.*)', line)
        if not m:
            continue

        ctype = m.group(1) or m.group(2)
        cname = m.group(3)
        rest  = m.group(4)

        # Extract nodes (tokens before first '=')
        tokens = rest.split()
        nodes = []
        for tok in tokens:
            if "=" in tok:
                break
            nodes.append(tok)

        components.append((ctype, cname, nodes))

    return components


def build_node_map(components):
    """Build node -> set of (type, name) that reference it."""
    node_map = defaultdict(set)
    for ctype, cname, nodes in components:
        for node in nodes:
            node_map[node].add((ctype, cname))
    return node_map


def check_floating_nodes(node_map):
    """Find nodes connected to only 1 component (floating)."""
    floating = []
    for node, comps in node_map.items():
        if node == "0":
            continue  # GND is special
        if len(comps) == 1:
            comp = list(comps)[0]
            floating.append((node, comp))
    return floating


def find_ports(components):
    """Find Port/Term components and return (name, rf_node)."""
    ports = {}
    for ctype, cname, nodes in components:
        if ctype in ("Port", "Term") and nodes:
            ports[cname] = nodes[0]
    return ports


def check_signal_path(components, node_map, ports):
    """BFS from Term1 node to Term2 node through component graph."""
    if "Term1" not in ports or "Term2" not in ports:
        return None, "Term1 or Term2 not found in netlist"

    start = ports["Term1"]
    goal  = ports["Term2"]

    # Build adjacency: node -> set of reachable nodes (through any component)
    adj = defaultdict(set)
    for ctype, cname, nodes in components:
        for i, n1 in enumerate(nodes):
            for j, n2 in enumerate(nodes):
                if i != j:
                    adj[n1].add(n2)

    # BFS
    visited = {start}
    queue   = [start]
    hops    = 0
    while queue:
        next_q = []
        for node in queue:
            if node == goal:
                return True, f"Signal path Term1 → Term2 connected ({hops} hops)"
            for neighbor in adj[node]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_q.append(neighbor)
        queue = next_q
        hops += 1
        if hops > 1000:
            break

    return False, f"Signal path broken — Term2 node '{goal}' not reachable from Term1 '{start}'"


def check_fet_pins(components, node_map):
    """Check all PDK FET pins appear in ≥2 components."""
    issues = []
    fet_types = {"PP1029_CPW_PDK", "PP1029_MS_PDK", "WIN_PP1029_CPW", "WIN_PP1029_MS"}
    for ctype, cname, nodes in components:
        if ctype in fet_types:
            pin_names = ["gate", "drain", "source"]
            for i, node in enumerate(nodes[:3]):
                if node == "0":
                    continue  # grounded source is fine
                refs = node_map.get(node, set())
                if len(refs) < 2:
                    pname = pin_names[i] if i < len(pin_names) else f"pin{i}"
                    issues.append(f"{cname} {pname} pin floating (node {node} in {len(refs)} component(s))")
    return issues


def check_gnd_connectivity(node_map, components):
    """GND node (0) should appear in multiple components."""
    gnd_refs = node_map.get("0", set())
    # Expect at least one per shunt element
    shunt_types = {"C", "R", "L", "GROUND"}
    shunt_count = sum(1 for ct, cn, _ in components if ct in shunt_types)
    expected_min = max(2, shunt_count // 4)
    if len(gnd_refs) < expected_min:
        return False, f"GND node appears in only {len(gnd_refs)} components (expected ≥{expected_min})"
    return True, f"GND node appears in {len(gnd_refs)} components"


def main():
    if len(sys.argv) < 2:
        print("Usage: check_netlist.py <netlist.net>")
        sys.exit(1)

    net_path = Path(sys.argv[1])
    if not net_path.exists():
        print(f"[ERROR] File not found: {net_path}")
        sys.exit(1)

    print(f"[CHECK] Parsing: {net_path.name}")
    components = parse_netlist(net_path)
    node_map   = build_node_map(components)
    ports      = find_ports(components)

    print(f"[CHECK] Components: {len(components)}  |  Nodes: {len(node_map)}")
    print(f"[CHECK] Ports found: {list(ports.keys())}")
    print()

    failures = []

    # 1. Floating nodes
    floating = check_floating_nodes(node_map)
    if floating:
        for node, comp in floating:
            msg = f"Floating node {node} -- only in: {comp[0]}:{comp[1]}"
            print(f"[FAIL] {msg}")
            failures.append(msg)
    else:
        print("[PASS] No floating nodes detected")

    # 2. Signal path
    ok, msg = check_signal_path(components, node_map, ports)
    if ok is None:
        print(f"[SKIP] Signal path: {msg}")
    elif ok:
        print(f"[PASS] {msg}")
    else:
        print(f"[FAIL] {msg}")
        failures.append(msg)

    # 3. FET pins
    fet_issues = check_fet_pins(components, node_map)
    if fet_issues:
        for issue in fet_issues:
            print(f"[FAIL] {issue}")
            failures.append(issue)
    else:
        # Check if any FETs exist
        fet_count = sum(1 for ct, _, _ in components
                        if ct in {"PP1029_CPW_PDK","PP1029_MS_PDK","WIN_PP1029_CPW","WIN_PP1029_MS"})
        if fet_count > 0:
            print(f"[PASS] All FET pins connected ({fet_count} FETs checked)")
        else:
            print("[SKIP] No PDK FETs found in netlist")

    # 4. GND connectivity
    ok, msg = check_gnd_connectivity(node_map, components)
    if ok:
        print(f"[PASS] {msg}")
    else:
        print(f"[WARN] {msg}")

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED ❌")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED ✅")
        sys.exit(0)


if __name__ == "__main__":
    main()
