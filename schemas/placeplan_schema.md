# Placeplan Schema

## Purpose

This schema defines the expected content of a placement-plan file used to guide ADS schematic generation.

The placement plan is separate from the logical netlist.

Its job is to describe how the logical circuit should be arranged in the schematic.

## Required Concepts

A placeplan should contain:

- design identity
- source reference
- placement objective
- functional groups
- lane definitions
- ordering constraints
- spacing guidance
- routing guidance
- anchor elements
- validation expectations

## Functional Groups

A placeplan should identify meaningful placement groups such as:
- input group
- switch core group
- RF branch groups
- control/bias groups
- shunt/ground-support group
- simulation group

## Lanes

A placeplan should assign groups into visual lanes or regions such as:
- RF main
- control/bias
- shunt/ground
- simulation

## Spacing Guidance

The placeplan should explicitly describe spacing intent, especially:
- spacing between unrelated groups
- branch-point clearance
- separation between RF and control lanes
- clearance near unconnected facing pins

## Routing Guidance

The placeplan should describe preferred schematic routing structure, for example:
- mostly horizontal RF path
- control drops from a separate lane
- shunt returns toward a lower lane
- avoidance of unnecessary crossings

## Rule

The placeplan must not redesign the circuit.

It must organize the existing logical implementation for safer and clearer schematic generation.