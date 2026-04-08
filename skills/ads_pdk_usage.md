# ADS PDK Usage

## Purpose

This skill teaches the sub-agent how to reason about PDK-specific implementation in relation to placement planning.

## Core Rule

Assume that `_ads_import.net` already represents the intended PDK-specific logical implementation for the current experiment.

The placement-planning task must not redefine PDK mapping.

## What The Sub-Agent May Assume

The sub-agent may assume:
- PDK devices, libraries, or cells have already been chosen in the ADS-oriented logical file
- the logical circuit should remain unchanged during placement planning
- the downstream builder already knows how to place valid PDK-recognizable components once given a good plan

## WIN_PP1029_DESIGN_KIT — Key Facts

- PDK location: `C:\Users\jarvis\ads_projects\design_kits\WIN_PP1029_DESIGN_KIT`
- Load via lib.defs: `INCLUDE C:\Users\jarvis\ads_projects\design_kits\WIN_PP1029_DESIGN_KIT\lib.defs`
  - **Do NOT quote the path** — ADS rejects quoted INCLUDE paths
- Main switch FET: `WIN_PP1029_CPW` (3-port: gate, drain, source)
  - Use for both series and shunt switch FETs
  - Do NOT use `WIN_PP1029_MS` for switch FETs — its source is pre-grounded
- Passive models: `PP1029_TFR` (resistor), `PP1029_MIM_CAP_Custom` (capacitor)

## SPDT Switch FET Sizing (confirmed)
- Series FETs (Q1a, Q1b): NOF=2, UGW=80 µm → 160 µm total gate width
- Shunt FETs (Q3a, Q3b): NOF=2, UGW=50 µm → 100 µm total gate width

## Gate Bias
Gate pins (ng_Q1a, ng_Q3a, ng_Q1b, ng_Q3b) are intentionally left floating in the initial build. GBIAS networks are added after FET connection verification.

## What The Sub-Agent Should Use PDK Knowledge For

PDK knowledge is relevant to placement planning when it helps the agent understand:

- which components are active-device cores
- which structures belong together functionally
- which components likely need associated control or bias structures
- where conservative spacing is especially important

## What The Sub-Agent Should Not Do

The sub-agent should not:
- reselect PDK devices
- change PDK library references
- reinterpret logical components without reason
- turn placement planning into device-remapping logic

## Practical Summary

Use PDK knowledge to improve grouping and placement understanding, not to alter the existing logical implementation.
