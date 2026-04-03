# jarvis-eda-learning

Collected skills, scripts, and netlists from Jarvis-EDA's `.net → ADS schematic` work.

## Structure

```
jarvis-eda-learning/
├── workspace-scripts/      # Python scripts developed during net-to-ADS experiments
│   ├── ads_run_example.py          # Original LPF S-param automation (ADS Python API demo)
│   ├── ads_import_netlist.py       # Parse .net → build ADS schematic → simulate (LPF)
│   ├── ads_lpf_skill_test.py       # LPF schematic skill test / validation script
│   ├── ads_build_spdt.py           # SPDT switch schematic builder
│   ├── net_parse.py                # Netlist parser utility
│   └── net_prepare.py              # Netlist preprocessor / @PDK_SWAP annotator
│
├── workspace-netlists/     # Netlists used as input or generated during experiments
│   ├── lpf_demo.net                # Hand-written 3-element Butterworth LPF (~1 GHz, 50 Ω)
│   ├── spdt_switch.net             # Raw SPDT switch netlist
│   ├── spdt_switch_prep.net        # Preprocessed netlist with @PDK_SWAP tags
│   └── spdt_switch_ads_import.net  # ADS-ready netlist for import
│
└── skills/
    ├── ads-netlist-translator/     # Skill: translate Python RF circuits → ADS netlists/schematics
    │   ├── SKILL.md
    │   ├── scripts/parse_circuit.mjs
    │   └── references/
    │       ├── ads-netlist-format.md
    │       ├── ads-python-api.md
    │       └── pdk-pipeline.md
    │
    └── ads-schematic-checker/      # Skill: verify ADS schematic connectivity post-build
        ├── SKILL.md
        └── scripts/check_netlist.py
```

## Key Outcomes

- **LPF demo** (`ads_import_netlist.py` + `lpf_demo.net`): Full pipeline from `.net` → ADS schematic → simulation. Results matched Python baseline exactly (delta = 0.000 dB across 0.1–5 GHz).
- **SPDT switch** (`ads_build_spdt.py` + `spdt_switch*.net`): PDK-based schematic build using WIN_PP1029 pHEMT FETs.
- **Skills** capture the reusable patterns: netlist format, ADS Python API patterns, PDK swap pipeline, and connectivity checking.
