# ADS Component Recognition

## Purpose

This skill teaches the sub-agent how to classify components in the ADS-oriented logical file for placement planning.

## Main Recognition Categories

The sub-agent should classify components into categories such as:

- RF path elements
- active switch or active core elements
- control or gate-bias elements
- shunt or ground-support elements
- ports
- simulation or measurement objects

## Why Recognition Matters

Placement planning depends on knowing which components should:

- stay on the main RF lane
- move to a control or bias lane
- move to a shunt or ground-support lane
- stay detached in a simulation lane

## Classification Goal

The goal is not perfect device taxonomy.

The goal is enough functional recognition to create a safe and readable schematic plan.

## Practical Questions

For each component or small cluster, ask:

- Is this part of the direct RF signal path
- Is this primarily for control or bias
- Is this mainly a shunt or return structure
- Is this a support or simulation object
- Which nearby components does it logically belong with

## Practical Summary

Component recognition should support placement grouping, lane assignment, and spacing logic.

The result should be a better schematic plan, not a deeper device-model analysis.