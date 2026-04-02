# Focus on ADS Schematic Quality

## Purpose

This skill teaches the agent how to think about schematic quality for the current experiment.

The goal is not to redesign the circuit. The goal is to improve how the existing logical circuit is turned into a schematic.

## What Matters Most

For this experiment, schematic quality means:

- the main RF path is visually clear
- branch structure is understandable
- control and bias structures are separated from the RF path
- unrelated symbols are not crowded together
- routing space is preserved
- the schematic is easier for both humans and scripts to verify

## Known Failure Mode

The known problem is that symbols can be placed too close to unrelated symbols or pins, which may produce ambiguous or wrong-looking connections.

The agent should explicitly reason about reducing this risk.

## Placement Priorities

Prioritize:
1. connection safety
2. readability
3. functional separation
4. conservative spacing
5. deterministic structure

Do not prioritize compactness first.

## Practical Summary

The sub-agent is a schematic-quality assistant.

Its job is to generate a placement-oriented plan that helps ADS create a cleaner and safer schematic from an already-defined logical circuit.