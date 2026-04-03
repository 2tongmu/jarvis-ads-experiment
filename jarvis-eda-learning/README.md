# jarvis-eda-learning

Collected skills, scripts, netlists, and agent definitions from Jarvis-EDA's `.net → ADS schematic` work.

This repo covers the full pipeline from rfscikit-generated RF circuit netlists to simulation-ready ADS schematics, including:

- Netlist parsing and PDK component substitution
- Placement planning and deterministic ADS schematic generation
- Reusable skills for translation, placement, and connectivity checking
- A shippable sub-agent definition (`net-to-ads`) for orchestrated use in larger projects

The goal is to make `.net → ADS schematic` more reliable, more readable, and less likely to create accidental wrong connections caused by poor symbol placement.

---

## Structure

```text
jarvis-eda-learning/
├── workspace-scripts/      # Python scripts developed during net-to-ADS experiments
│   ├── ads_run_example.py           # Original LPF S-param automation (ADS Python API demo)
│   ├── ads_import_netlist.py        # Parse .net → build ADS schematic → simulate (LPF)
│   ├── ads_lpf_skill_test.py        # LPF schematic skill test / validation script
│   ├── ads_build_spdt.py            # SPDT switch schematic builder
│   ├── net_parse.py                 # Netlist parser utility
│   ├── net_prepare.py               # Netlist preprocessor / @PDK_SWAP annotator
│   ├── net_graph_utils.py           # Connectivity graph utilities for backbone/group inference
│   ├── ads_placeplan_generate.py    # Generate schematic placeplan from ADS-oriented netlist
│   └── ads_placeplan_to_ads.py      # Convert placeplan into deterministic ADS build coordinates
│
├── workspace-netlists/      # Netlists used as input or generated during experiments
│   ├── lpf_demo.net                 # Hand-written 3-element Butterworth LPF (~1 GHz, 50 Ω)
│   ├── spdt_switch.net              # Raw SPDT switch netlist
│   ├── spdt_switch_prep.net         # Preprocessed netlist with @PDK_SWAP tags
│   ├── spdt_switch_ads_import.net   # ADS-oriented logical implementation
│   ├── spdt_switch_placeplan.yaml   # Placement-planning artifact for ADS schematic generation
│   └── spdt_switch_ads_buildplan.yaml # Deterministic build plan with coordinates for ADS placement
│
├── skills/
│   ├── ads-netlist-translator/      # Skill: translate Python RF circuits → ADS netlists/schematics
│   │   ├── SKILL.md
│   │   ├── scripts/parse_circuit.mjs
│   │   └── references/
│   │       ├── ads-netlist-format.md
│   │       ├── ads-python-api.md
│   │       └── pdk-pipeline.md
│   │
│   ├── ads-schematic-checker/       # Skill: verify ADS schematic connectivity post-build
│   │   ├── SKILL.md
│   │   └── scripts/check_netlist.py
│   │
│   └── ads-schematic-placement/     # Skill: generate placement plan from logical ADS netlist
│       ├── SKILL.md
│       └── references/
│           └── placeplan-concepts.md
│
└── agents/
    └── net-to-ads/                  # Sub-agent: rfscikit .net → simulation-ready ADS schematic
        ├── IDENTITY.md              # Who the agent is, role, scope, inputs/outputs
        ├── SKILLS.md                # Skills and scripts the agent is authorized to use
        ├── PLAYBOOK.md              # 3-stage workflow with decision rules and escalation logic
        ├── CONSTRAINTS.md           # Hard runtime limits: token, time, cost, irreversible actions
        ├── IMPROVEMENT.md           # What the agent can improve, how, and what is frozen
        ├── GRADUATION.md            # Phase-gated stop criteria and release status (human-controlled)
        └── MEMORY.md                # Learning log (training) / handoff brief (production)
```

---

## Key Outcomes

- **LPF demo** (`ads_import_netlist.py` + `lpf_demo.net`): Full pipeline from `.net` → ADS schematic → simulation. Results matched Python baseline exactly (delta = 0.000 dB across 0.1–5 GHz).
- **SPDT switch** (`ads_build_spdt.py` + `spdt_switch*.net`): PDK-based schematic build using WIN_PP1029 pHEMT FETs.
- **Skills** capture the reusable patterns: netlist format, ADS Python API patterns, PDK swap pipeline, and connectivity checking.
- **`net-to-ads` agent** packages the full pipeline as a shippable, self-improvable sub-agent ready to be orchestrated by Jarvis or a project-level agent.

---

## Agent Framework

The `net-to-ads` sub-agent follows a standard 7-file definition framework used across all Jarvis EDA agents:

| File | Purpose | Editable By |
|---|---|---|
| `IDENTITY.md` | Who the agent is — role, scope, inputs, outputs | Human only |
| `SKILLS.md` | What it can do — tools, scripts, and skills authorized | Human only |
| `PLAYBOOK.md` | How it works — step-by-step workflow and decision rules | Human only |
| `CONSTRAINTS.md` | Hard limits — token, time, cost, and irreversible action guardrails | Human only |
| `IMPROVEMENT.md` | What the agent can improve, how, and what is frozen | Human only |
| `GRADUATION.md` | Phase-gated stop criteria and release status | Human only |
| `MEMORY.md` | Learning log (training) / handoff brief (production) | Agent + Human |

### Frozen vs. Open

The framework enforces a strict boundary between what the agent controls and what only a human can change:

- **Frozen (framework files):** IDENTITY, SKILLS, PLAYBOOK, CONSTRAINTS, IMPROVEMENT, GRADUATION — define what the agent *is*. Never modified autonomously.
- **Open (execution layer):** Python scripts, intermediate netlists, YAML artifacts, MEMORY — define how the agent *does it*. Agent may improve these autonomously within rules defined in IMPROVEMENT.md.

### Development Phases

GRADUATION.md gates the agent through sequential development phases, each with a defined stop criterion requiring human sign-off before advancing:

| Phase | Stop Criterion |
|---|---|
| 1 — Schematic Generation | ADS schematic created and checker passes — human visual review |
| 2 — Simulation Execution | Simulation runs and returns valid S-parameter data |
| 3 — Result Validation | ADS output matches rfscikit baseline within tolerance |
| 4 — Release Candidate | Full pipeline completes on 2 circuit types without intervention |
| 5 — Released | Agent in production; self-improvement suspended |

This framework is designed to be reusable: any new EDA task agent starts from the same 7-file template and is filled in for the specific task. Agents defined this way are rehydratable (resumable after pause), shippable (handable to an orchestrator), self-improvable (within defined boundaries), and release-gated (no autonomous graduation between phases).