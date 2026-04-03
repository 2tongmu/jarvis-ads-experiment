# Placeplan Concepts

## Core Idea

A placeplan is a structured description of how to arrange a logically correct circuit in an ADS schematic.

It is not the electrical source of truth.
It is the schematic-organization source of truth.

## Main Concepts

### Functional groups
Meaningful placement units, such as:
- input port group
- switch core
- upper branch
- lower branch
- gate bias group
- shunt return group
- simulation group

### Lanes
Visual regions in the schematic:
- RF main
- control or bias
- shunt or ground
- simulation

### Ordering constraints
Examples:
- RF input left of switch core
- switch core left of outputs
- upper branch above lower branch
- control groups close to driven devices but not in RF lane

### Spacing guidance
Examples:
- large spacing between unrelated groups
- extra spacing near branch points
- extra clearance between unconnected facing pins

### Routing guidance
Examples:
- RF route mostly horizontal
- control route from upper lane with vertical drops
- shunt route downward to lower lane

### Anchor elements
Elements placed first:
- input port
- switch core
- outputs
- simulation group

## Why It Matters

A logical netlist can still produce a poor ADS schematic if symbol placement is careless.

The placeplan reduces that risk by making placement:
- explicit
- reviewable
- deterministic