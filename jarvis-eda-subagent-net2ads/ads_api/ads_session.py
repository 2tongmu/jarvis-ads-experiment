"""
ads_api/ads_session.py
======================
Manage the ADS Python session.

Responsibilities:
  - Detect whether the process is running inside the ADS-bundled Python
  - Add ADS packages to sys.path when needed
  - Import the confirmed ADS modules (de, db, TermType, DesignMode)
  - Expose a single ADSSession object that all other ads_api modules share

Usage:
    from ads_api.ads_session import get_ads_session
    session = get_ads_session()                  # raises if ADS not available
    session = get_ads_session(ads_dir="C:/...")  # explicit path override

The session object carries:
    session.de          — keysight.ads.de module
    session.db          — keysight.ads.de.db_uu module
    session.DesignMode  — DesignMode enum (from _pde.db, confirmed import path)
    session.TermType    — TermType enum  (from _pde.db, confirmed import path)
    session.ads_dir     — resolved ADS installation path used

ADS installation is discovered automatically by scanning the Keysight install
directory for ADS* subdirectories, sorted newest-first by version year.
A minimum version of ADS2023 is required for the Python API features used here.
An explicit path can always be passed to override discovery.
"""

import os
import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

_PACKAGES_SUBPATH = Path("tools") / "python" / "packages"

# Minimum ADS release year required for confirmed Python API compatibility.
_MIN_ADS_YEAR = 2023

# Root directory where Keysight installs ADS on Windows.
_KEYSIGHT_ROOT = Path(r"C:\Program Files\Keysight")


def _parse_ads_version(dirname: str) -> tuple:
    """
    Parse a version sort key from an ADS install directory name.

    Examples:
        "ADS2026_Update1.2" → (2026, 1, 2)
        "ADS2025_Update2"   → (2025, 2, 0)
        "ADS2024"           → (2024, 0, 0)

    Returns (0, 0, 0) for names that don't match the pattern.
    """
    m = re.match(r"ADS(\d{4})(?:_Update(\d+)(?:\.(\d+))?)?", dirname, re.IGNORECASE)
    if not m:
        return (0, 0, 0)
    year   = int(m.group(1))
    update = int(m.group(2)) if m.group(2) else 0
    patch  = int(m.group(3)) if m.group(3) else 0
    return (year, update, patch)


def _discover_ads_dirs() -> list:
    """
    Scan the Keysight install root for ADS installation directories.

    Returns a list of Path objects sorted newest-first (highest version first).
    Only directories that contain the expected Python packages subtree are included.
    """
    if not _KEYSIGHT_ROOT.is_dir():
        return []

    candidates = []
    for entry in _KEYSIGHT_ROOT.iterdir():
        if not entry.is_dir():
            continue
        if not entry.name.upper().startswith("ADS"):
            continue
        if not (entry / _PACKAGES_SUBPATH).exists():
            continue
        ver = _parse_ads_version(entry.name)
        if ver[0] == 0:
            continue  # unrecognised name format
        candidates.append((ver, entry))

    # Sort newest version first
    candidates.sort(key=lambda t: t[0], reverse=True)
    return [path for _, path in candidates]


def _find_ads_dir(explicit: Optional[str] = None) -> Optional[Path]:
    """
    Return the best available ADS installation directory, or None.

    Resolution order:
      1. explicit path (if provided) — used as-is, no version check
      2. auto-discovered paths (newest first) — minimum version enforced
    """
    if explicit:
        p = Path(explicit)
        if (p / _PACKAGES_SUBPATH).exists():
            return p
        return None

    for ads_path in _discover_ads_dirs():
        ver = _parse_ads_version(ads_path.name)
        if ver[0] < _MIN_ADS_YEAR:
            continue  # too old — skip
        return ads_path  # first (newest) valid path

    return None


def _ensure_ads_on_path(ads_dir: Path) -> None:
    """Insert ADS packages dir at the front of sys.path if not already present."""
    packages_path = str(ads_dir / _PACKAGES_SUBPATH)
    if packages_path not in sys.path:
        sys.path.insert(0, packages_path)


@dataclass
class ADSSession:
    """
    Lightweight container for ADS module references.
    Created once by get_ads_session() and passed to other ads_api functions.

    Attributes (all set after successful import):
        de          : keysight.ads.de module
        db          : keysight.ads.de.db_uu module
        DesignMode  : DesignMode enum  — ✅ CONFIRMED import from _pde.db
        TermType    : TermType enum    — ✅ CONFIRMED import from _pde.db
        ads_dir     : resolved ADS installation path (string)
    """
    de: object
    db: object
    DesignMode: object
    TermType: object
    ads_dir: str


# Module-level singleton — created on first call, reused thereafter.
_SESSION: Optional[ADSSession] = None


def get_ads_session(ads_dir: Optional[str] = None, force_reinit: bool = False) -> ADSSession:
    """
    Return (or create) the ADS session singleton.

    Args:
        ads_dir       : explicit ADS installation path; overrides auto-detection
        force_reinit  : if True, discard any cached session and re-import

    Returns:
        ADSSession with de, db, DesignMode, TermType populated

    Raises:
        EnvironmentError  : ADS packages directory not found
        ImportError       : keysight.ads.de failed to import
    """
    global _SESSION
    if _SESSION is not None and not force_reinit:
        return _SESSION

    # ── Locate ADS installation ───────────────────────────────────────────────
    found_dir = _find_ads_dir(ads_dir)
    if found_dir is None:
        if ads_dir:
            detail = f"  explicit path: {ads_dir}"
        else:
            discovered = _discover_ads_dirs()
            if discovered:
                detail = (
                    f"  Found ADS installs but none meet minimum year ADS{_MIN_ADS_YEAR}:\n"
                    + "\n".join(f"    {p}" for p in discovered)
                )
            else:
                detail = f"  No ADS* directories found under {_KEYSIGHT_ROOT}"
        raise EnvironmentError(
            "ADS Python packages not found.\n"
            + detail
            + "\nRun this script with the ADS-bundled Python interpreter."
        )

    _ensure_ads_on_path(found_dir)
    os.environ.setdefault("HPEESOF_DIR", str(found_dir))

    # ── Import ADS modules ────────────────────────────────────────────────────
    try:
        import keysight.ads.de as de_module
        from keysight.ads.de import db_uu as db_module
        # CRITICAL: TermType and DesignMode must come from _pde.db, NOT the
        # public keysight.ads.de.db — importing from the wrong module silently
        # fails. Confirmed: ADS_API_REFERENCE.md §10.
        from keysight.ads.de._pde.db import TermType, DesignMode  # ✅ CONFIRMED
    except ImportError as exc:
        raise ImportError(
            f"Failed to import ADS modules from {found_dir}: {exc}\n"
            "Ensure you are running the ADS-bundled Python interpreter."
        ) from exc

    _SESSION = ADSSession(
        de=de_module,
        db=db_module,
        DesignMode=DesignMode,
        TermType=TermType,
        ads_dir=str(found_dir),
    )
    return _SESSION


def is_ads_available(ads_dir: Optional[str] = None) -> bool:
    """
    Return True if ADS Python packages are importable, False otherwise.
    Does not raise — safe to use as a guard in scripts that support dry-run mode.
    """
    try:
        get_ads_session(ads_dir)
        return True
    except (EnvironmentError, ImportError):
        return False
