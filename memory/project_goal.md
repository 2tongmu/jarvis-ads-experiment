# Project Goal

## Purpose

This project teaches an agent how to help transform an RF circuit design flow into a simulation-ready ADS schematic through explicit, staged artifacts.

The current priority is not to automate everything at once. The current priority is to make the flow more structured, more reviewable, and safer for repeated experiments.

## Long-Term Direction

The long-term direction is a staged flow:

1. An abstract circuit is represented in `original.net`
2. Functional regrouping and replacement intent are represented in `_prep.net`
3. A PDK-specific logical implementation is represented in `_ads_import.net`
4. A separate placement-planning artifact guides ADS schematic generation
5. Deterministic scripts build the schematic and run simulation

## Core Principle

The agent should reason about meaning, grouping, intent, and placement structure.

Deterministic scripts should enforce legality, placement execution, schematic creation, and simulation.

## Current Priority

The current focus is a narrow experiment:

Use existing example `.net` files to help generate a better ADS schematic placement plan, so the resulting schematic is clearer, more readable, and less likely to create accidental wrong connections due to poor symbol proximity.