# Launch ADS Placeplan Sub-Agent

## Purpose

This file instructs Jarvis-EDA to create a narrow-scope sub-agent focused on ADS schematic placement planning for the provided switch example.

## Sub-Agent Name

`ads_placeplan_agent`

## Mission

Read the existing knowledge and example files, then generate a placement-planning artifact that improves ADS schematic generation quality for the switch example.

The sub-agent should focus on readability, function separation, spacing, and connection safety.

## Files The Sub-Agent Must Read

### Memory
- `memory/project_goal.md`
- `memory/current_scope.md`
- `memory/ads_execution_context.md`

### Skills
- `skills/understand_net_roles.md`
- `skills/focus_on_ads_schematic_quality.md`
- `skills/ads_python_interface.md`
- `skills/ads_pdk_usage.md`
- `skills/ads_component_recognition.md`
- `skills/ads_schematic_build_limitations.md`

### Workflows
- `workflows/review_example_net_flow.md`
- `workflows/ads_import_to_placeplan.md`

### Schema
- `schemas/placeplan_schema.md`

### Example design files
- `input/spdt_switch.net`
- `input/spdt_switch_prep.net`
- `input/spdt_switch_ads_import.net`

## Required Outputs

Create new files only:

- `notes/spdt_switch_placeplan_review.md`
- `input/spdt_switch_placeplan.yaml`

Do not modify the existing example `.net` files.

## Constraints

The sub-agent must not:
- redesign the circuit
- change intended connectivity
- invent a new netlist grammar
- replace the logical ADS implementation
- optimize RF performance
- over-compress the schematic plan

The sub-agent should:
- preserve logical meaning
- identify the main RF path
- identify branch and control structure
- define lanes, ordering, spacing, routing guidance, and anchors
- optimize for safer and clearer ADS schematic generation

## Execution Order

1. Read the memory, skills, workflows, schema, and example files
2. Review the example net flow
3. Create a review note
4. Create the placeplan yaml
5. Save outputs as new files only