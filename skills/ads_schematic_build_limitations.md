# ADS Schematic Build Limitations

## Purpose

This skill captures known limitations and risks in the current ADS schematic generation flow so the sub-agent can plan more conservatively.

## Known Limitation

A logically correct ADS-oriented file can still produce a poor schematic if symbol placement is careless.

In particular, components that are too close to unrelated symbols or pins may create ambiguous or wrong-looking connections.

## Implication For The Sub-Agent

The sub-agent should treat placement as a safety and readability problem, not just a formatting problem.

## Conservative Planning Rules

Prefer:
- larger spacing between unrelated groups
- clearer lane separation
- more obvious branch structure
- more room near branch points
- cleaner separation between RF and control structures

Avoid:
- tight packing
- arbitrary local placement
- mixing unrelated functions in one crowded region
- assuming the downstream builder will automatically fix bad geometry

## Practical Summary

When uncertain, choose the placement rule that makes the schematic easier to inspect and less likely to hide a connection mistake.