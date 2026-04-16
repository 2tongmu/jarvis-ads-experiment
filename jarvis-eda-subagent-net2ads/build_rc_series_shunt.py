#!/usr/bin/env python3
"""
Build RC series-shunt schematic in ADS workspace
Wrapper around net2ads.py for Windows execution via ADS Python

Run from:
  "C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe" build_rc_series_shunt.py
"""

import sys
import os
from pathlib import Path

# Set up environment for ADS
ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

# Import net2ads pipeline
subagent_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(subagent_dir))

from net2ads import main as net2ads_main
import sys as _sys

# Override args to run the RC circuit
_sys.argv = [
    _sys.argv[0],
    str(subagent_dir / "examples" / "rc_series_shunt" / "rc_series_shunt_research.net"),
    "--workspace", r"C:\Users\jarvis\ads_projects\net2ads_test_1",
    "--lib", "net2ads_lib",
    "--output-dir", str(subagent_dir / "examples" / "rc_series_shunt"),
]

print(f"[BUILD] Running net2ads for RC series-shunt circuit")
print(f"[BUILD] Command: {' '.join(_sys.argv[1:])}")
print()

try:
    net2ads_main()
    print("\n[SUCCESS] RC series-shunt build completed")
except SystemExit as e:
    if e.code != 0:
        print(f"\n[ERROR] Build failed with exit code {e.code}")
        sys.exit(e.code)
except Exception as e:
    print(f"\n[ERROR] Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
