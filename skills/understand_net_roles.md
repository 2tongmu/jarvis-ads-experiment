# Understand Net Roles

## Purpose

This skill teaches the agent the role of each netlist-related file in the current workflow.

Each file belongs to a different stage of meaning. The agent must not mix those roles.

## File Roles

### `original.net`
This file represents abstract circuit intent.

It may include simplified active-device models such as RLC equivalents or controlled-source abstractions.

It is technology-agnostic.

### `_prep.net`
This file represents regrouped function blocks and replacement intent.

It is still technology-agnostic.

It helps later workflows understand what should be preserved, replaced, or interpreted together.

### `_ads_import.net`
This file represents a PDK-specific logical implementation.

It should preserve intended connectivity and be suitable for ADS-oriented downstream use.

It is not the final schematic placement artifact.

### `*_placeplan.yaml`
This file represents placement and schematic-organization intent.

It describes how the logical circuit should be arranged visually and structurally in ADS.

## Core Rule

Do not confuse logical implementation with schematic geometry.

A file can be electrically meaningful without being placement-ready.

## Practical Summary

Use:
- `original.net` for circuit intent
- `_prep.net` for function grouping
- `_ads_import.net` for logical ADS implementation
- `*_placeplan.yaml` for schematic placement planning