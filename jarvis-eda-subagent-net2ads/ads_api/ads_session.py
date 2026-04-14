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

ADS Python interpreter paths:
    Jarvis (CI):    C:/Program Files/Keysight/ADS2026_Update1/tools/python/python.exe
    Local dev:      C:/Program Files/Keysight/ADS2026_Update1.2/tools/python/python.exe
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


# Default search order for ADS installation directories.
# The first path that exists and contains the packages directory is used.
_ADS_CANDIDATE_DIRS = [
    r"C:\Program Files\Keysight\ADS2026_Update1",
    r"C:\Program Files\Keysight\ADS2026_Update1.2",
]

_PACKAGES_SUBPATH = Path("tools") / "python" / "packages"


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
        checked = [ads_dir] + _ADS_CANDIDATE_DIRS if ads_dir else _ADS_CANDIDATE_DIRS
        raise EnvironmentError(
            "ADS Python packages not found. Checked:\n"
            + "\n".join(f"  {p}" for p in checked if p)
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
