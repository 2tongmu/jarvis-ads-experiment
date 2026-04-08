# ADS Execution Context

## Purpose

This file records environment-specific knowledge that the sub-agent should assume when working on ADS schematic generation planning.

It exists so the sub-agent does not rely on hidden context or unstated assumptions.

## Current Understanding

The current flow includes:

- a PDK-specific logical netlist in `_ads_import.net`
- Python-based interaction with ADS
- downstream schematic generation that depends on component placement quality
- known risk that poor placement can produce ambiguous or wrong-looking connections when unrelated symbols are too close

## Sub-Agent Boundary

The sub-agent is not responsible for directly building the ADS schematic.

The sub-agent is responsible for generating a structured placement-planning artifact that a deterministic ADS build script can consume.

## Environment Assumptions

Assume:

- ADS access is already being explored through Python-based automation
- PDK usage and component recognition already exist in parent-agent knowledge
- the current experiment starts from `spdt_switch_ads_import.net`
- the downstream builder benefits from explicit structure for lanes, spacing, ordering, and grouping

## Main Risk To Reduce

The main implementation risk for this experiment is not logical netlist correctness.

The main risk is schematic-generation quality, especially:
- poor placement
- crowded unrelated symbols
- ambiguous wiring regions
- accidental wrong connectivity caused by proximity or unclear routing space

## Practical Rule

When uncertain, prefer:
- clearer structure
- more conservative spacing
- more explicit grouping
- cleaner lane separation

Do not prefer compactness over clarity in this experiment.