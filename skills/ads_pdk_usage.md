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