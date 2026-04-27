# ENVIRONMENT.md — Execution Environment Configuration

**Last updated:** 2026-04-27
**Status:** Ready for production execution

---

## Overview

The net2ads sub-agent requires **Keysight ADS 2026 Update 1** with the bundled Python interpreter.
This file documents the execution environment, auto-detection, and manual setup for different machines.

---

## System Requirements

| Component | Requirement | Verified |
|---|---|---|
| **ADS Version** | Keysight ADS 2026 Update 1 or higher | ✅ 2026-04-27 |
| **Python** | ADS-bundled Python only (not system Python) | ✅ |
| **OS** | Windows (native path required; no WSL for ADS calls) | ✅ Windows 10/11 |
| **Dependencies** | keysight.ads.de, keysight.ads.de.db_uu, pyyaml | ✅ Auto-loaded |

---

## Known Installation Paths

### Jarvis (Production CI Machine)

```
C:\Program Files\Keysight\ADS2026_Update1\
├── bin\
│   └── ads.exe
├── tools\
│   └── python\
│       ├── python.exe
│       └── packages\
│           ├── keysight/
│           │   └── ads/
│           │       ├── de.py
│           │       └── de/
│           │           └── db_uu.py
```

**Python interpreter path:**
```
C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe
```

**Verified working:** 2026-04-15, 2026-04-27

---

### Local Development Machine (Template)

```
C:\Program Files\Keysight\ADS2026_Update1.2\
├── bin\
│   └── ads.exe
├── tools\
│   └── python\
│       ├── python.exe
│       └── packages\
```

**Python interpreter path:**
```
C:\Program Files\Keysight\ADS2026_Update1.2\tools\python\python.exe
```

**Status:** Template (update with actual local path if different)

---

## Auto-Detection (ads_session.py)

The net2ads pipeline uses **automatic ADS directory detection** (no manual path entry needed in most cases).

### Detection Order

1. **Explicit override** (if provided via `ads_dir` parameter to `get_ads_session()`)
2. **Jarvis production path:** `C:\Program Files\Keysight\ADS2026_Update1\`
3. **Local dev path:** `C:\Program Files\Keysight\ADS2026_Update1.2\`
4. **Fallback:** Error (ADS not found on machine)

### Auto-Detection Code (ads_api/ads_session.py)

```python
_ADS_CANDIDATE_DIRS = [
    r"C:\Program Files\Keysight\ADS2026_Update1",
    r"C:\Program Files\Keysight\ADS2026_Update1.2",
]

def _find_ads_dir(explicit: Optional[str] = None) -> Optional[Path]:
    """Return the first valid ADS directory, or None if none found."""
    candidates = [explicit] if explicit else []
    candidates += _ADS_CANDIDATE_DIRS
    
    for candidate in candidates:
        if candidate is None:
            continue
        p = Path(candidate)
        if (p / _PACKAGES_SUBPATH).exists():
            return p
    return None
```

**To add a new machine:** Edit `_ADS_CANDIDATE_DIRS` in `ads_api/ads_session.py` and re-run.

---

## Running net2ads on Different Machines

### Scenario 1: Jarvis (Production) — Auto-Detected ✅

**What you need:**
- ADS 2026 Update 1 installed at `C:\Program Files\Keysight\ADS2026_Update1\`
- net2ads repository cloned to `C:\Users\jarvis\jarvis-ads-experiment\` (or anywhere)

**How to run:**
```bash
cd C:\Users\jarvis\jarvis-ads-experiment
C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe -m jarvis-eda-subagent-net2ads.net2ads examples/spdt_switch --workspace C:\Users\jarvis\ads_projects\spdt_test_wrk
```

Or shorter (auto-detects ADS):
```bash
python net2ads.py examples/spdt_switch/spdt_switch_research.net --workspace C:\Users\jarvis\ads_projects\spdt_test_wrk
```

**Expected output:**
- Workspace created at `C:\Users\jarvis\ads_projects\spdt_test_wrk\`
- ADS schematic built in `net2ads_lib:SPDT_SWITCH:schematic`
- Artifacts written to `examples/spdt_switch/`
- Status block printed to stdout (success/partial/failed)

---

### Scenario 2: New Machine (Not in Candidate List)

**Setup:**
1. Verify ADS 2026 Update 1 installed (or later)
2. Note the full path to the ADS directory (e.g. `C:\Keysight\ADS2026\`)
3. Edit `ads_api/ads_session.py`:
   ```python
   _ADS_CANDIDATE_DIRS = [
       r"C:\Keysight\ADS2026\",          # Add your path here
       r"C:\Program Files\Keysight\ADS2026_Update1",
       r"C:\Program Files\Keysight\ADS2026_Update1.2",
   ]
   ```
4. Commit the change to GitHub
5. Run net2ads normally

**Or use explicit override (no code change):**
```bash
python -c "from ads_api.ads_session import get_ads_session; get_ads_session(ads_dir='C:\\Keysight\\ADS2026\\')"
```

---

## Verification Checklist

Before running net2ads for the first time on a machine:

- [ ] ADS 2026 Update 1 (or later) is installed
- [ ] `C:\Program Files\Keysight\ADS2026_Update1\tools\python\packages\keysight\ads\` exists (or your custom path)
- [ ] No syntax errors in `ads_api/ads_session.py`
- [ ] `_ADS_CANDIDATE_DIRS` includes your ADS installation path (or you'll use explicit override)
- [ ] Test auto-detection:
  ```bash
  python -c "from ads_api.ads_session import get_ads_session, _find_ads_dir; print(_find_ads_dir())"
  ```
  Should print your ADS installation path (not None)

---

## Workspace Setup (Automatic)

The net2ads pipeline automatically creates/configures ADS workspaces. You only need to provide:
- **Workspace directory path** (e.g. `C:\Users\jarvis\ads_projects\spdt_test_wrk\`)
- **Target library name** (default: `net2ads_lib`)

The pipeline will:
1. Create `<workspace>/cds.lib`
2. Create `<workspace>/lib.defs` with `ads_rflib` + target library
3. Create `<workspace>/<lib_name>/` directory with cdsinfo.tag
4. Build schematic in the library

---

## PDK-Aware Workspaces (Phase 2+)

For PDK-aware builds (e.g. WIN_PP1029_DESIGN_KIT):
- PDK lib.defs must be present at one of:
  1. `ads_pdk/<pdk_name>/lib.defs` (local repository)
  2. Path specified in `ads_pdk/pdk_configs/<pdk_name>_core.yaml` (Jarvis path)

Example (Phase 2 — TLIN):
```bash
python net2ads.py examples/two_quarter_wave_lines/two_quarter_wave_lines_research.net \
    --workspace C:\Users\jarvis\ads_projects\tlin_test_wrk \
    --pdk WIN_PP1029_DESIGN_KIT
```

The pipeline will:
- Locate PDK lib.defs (auto-detected)
- Create workspace with PDK included
- Map TLIN → WIN_PP1029_DESIGN_KIT:PP1029_mlin

---

## Troubleshooting

### Error: "ADS not found"

**Cause:** `_find_ads_dir()` returned None (no matching installation detected)

**Fix:**
1. Verify ADS is installed: `dir "C:\Program Files\Keysight\"`
2. Check actual path to ADS 2026 installation
3. Add it to `_ADS_CANDIDATE_DIRS` in `ads_api/ads_session.py`
4. Or run with explicit override:
   ```bash
   python -c "from ads_api.ads_session import get_ads_session; s = get_ads_session(ads_dir='C:\\your\\actual\\path'); print(s.ads_dir)"
   ```

### Error: "ModuleNotFoundError: No module named 'keysight.ads.de'"

**Cause:** ADS packages not in sys.path

**Fix:**
1. Run with explicit ADS interpreter:
   ```bash
   "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" net2ads.py ...
   ```
2. Or verify packages path:
   ```bash
   python -c "import sys; print('\n'.join(sys.path))"
   ```
   Should include `C:\Program Files\Keysight\ADS2026_Update1\tools\python\packages`

### Error: "Workspace already open / access denied"

**Cause:** Another ADS instance is using the workspace

**Fix:**
1. Close all ADS instances
2. Wait 5 seconds
3. Retry the command

---

## Integration with Orchestration Systems

### OpenClaw Subagent Spawn

When spawning net2ads as a sub-agent via OpenClaw:

```yaml
sessions_spawn:
  task: |
    cd ~/.openclaw/workspace/jarvis-ads-experiment
    python -m jarvis-eda-subagent-net2ads.net2ads examples/spdt_switch \
      --workspace /mnt/c/Users/jarvis/ads_projects/spdt_test_wrk
```

**Note:** WSL paths (`/mnt/c/...`) are converted to Windows paths (`C:\...`) internally by the ADS session module. Alternatively, use Windows paths directly when shelling.

---

## Environment Variables (Optional)

You can override ADS detection via environment variables (future extension):

| Variable | Purpose | Example |
|---|---|---|
| `ADS_INSTALL_DIR` | Explicit ADS installation path | `C:\Keysight\ADS2026\` |
| `HPEESOF_DIR` | ADS root (read by some ADS utilities) | Auto-set by ads.exe |

Currently these are **not implemented** but can be added to `ads_api/ads_session.py` if needed.

---

## Current Status Summary

| Aspect | Status | Last Verified |
|---|---|---|
| **Jarvis environment** | ✅ Ready | 2026-04-27 09:14 PDT |
| **ADS 2026 Update 1** | ✅ Confirmed | 2026-04-27 |
| **Auto-detection** | ✅ Working | 2026-04-27 |
| **Local dev path** | ⚠️ Template only | — |
| **PDK (WIN_PP1029)** | ✅ Verified Phase 2 | 2026-04-26 |

---

## Next Steps (For Human Operator)

1. **Confirm this is running on Jarvis (Windows):**
   ```bash
   python -c "from ads_api.ads_session import _find_ads_dir; print(_find_ads_dir())"
   ```
   Should print: `C:\Program Files\Keysight\ADS2026_Update1`

2. **Run net2ads on SPDT example:**
   ```bash
   cd C:\Users\jarvis\jarvis-ads-experiment
   python net2ads.py examples/spdt_switch/spdt_switch_research.net \
     --workspace C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk \
     --sw-map examples/spdt_switch/spdt_switch_sw_map.yaml
   ```

3. **Verify output:**
   - Look for `status: success` in final status block
   - Check `examples/spdt_switch/spdt_switch_placement.yaml` for coordinates
   - Run `ads-schematic-checker` on generated netlist

---

**Document version:** 2026-04-27  
**Maintained by:** net2ads sub-agent development team
