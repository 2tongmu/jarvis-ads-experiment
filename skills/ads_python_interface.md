# ADS Python Interface

## Purpose

This skill records how the sub-agent should think about the ADS Python interface without trying to directly replace deterministic ADS builder logic.

## Role of the Sub-Agent

The sub-agent should assume that ADS can be driven through Python-based automation, but the sub-agent itself is not the final execution engine.

Its output should be structured so that a deterministic Python builder can consume it reliably.

## What The Sub-Agent Should Produce

The sub-agent should produce information that is useful for Python-based schematic generation, such as:

- functional groups
- placement lanes
- ordering constraints
- spacing rules
- routing preferences
- anchor elements
- validation expectations

## What The Sub-Agent Should Avoid

The sub-agent should avoid:
- relying on hidden ADS state
- assuming undocumented API behavior
- inventing unsupported ADS operations
- mixing placement planning with low-level ADS command details unless known explicitly

## Interface Principle

The placement plan should be:
- structured
- explicit
- deterministic-script-friendly
- easy to validate before ADS execution

## Practical Summary

Think of the ADS Python layer as a downstream consumer.

The sub-agent should provide clean placement intent, not fragile implementation improvisation.