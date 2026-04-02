# Current Scope

## Immediate Goal

The immediate goal is to support a narrow experiment on ADS schematic generation quality using the provided switch example files.

The current task is not full RF automation. The current task is to help produce a better schematic placement plan from an existing ADS-oriented logical implementation.

## In-Scope Files

The current working design files are:

- `input/spdt_switch.net`
- `input/spdt_switch_prep.net`
- `input/spdt_switch_ads_import.net`

## In-Scope Agent Task

The sub-agent should:

- review the three example files as a staged flow
- understand the logical role of each file
- treat `spdt_switch_ads_import.net` as the main logical source for placement planning
- generate a placement-plan artifact
- preserve existing circuit meaning and connectivity
- improve schematic readability, functional separation, and connection safety

## Out of Scope

The sub-agent should not:

- redesign the circuit topology
- change electrical intent without instruction
- invent a new `.net` grammar
- optimize transistor sizing
- optimize RF performance
- generalize to all circuit classes
- solve physical layout

## Success Criteria

A good output from this experiment should help ADS schematic generation become:

- clearer
- safer
- more readable
- better separated by function
- less likely to create accidental wrong connections from crowded symbol placement