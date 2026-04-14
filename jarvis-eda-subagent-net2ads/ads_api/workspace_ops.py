"""
ads_api/workspace_ops.py
========================
Manage ADS workspace lifecycle and library registration.

All functions require an ADSSession from ads_session.get_ads_session().

API status notes (sourced from ADS_API_REFERENCE.md §1–§2):
    open_workspace()       : de.open_workspace(path)              ✅ CONFIRMED
    create_workspace()     : de.create_workspace(path)            ⚠️ UNCONFIRMED
    close_workspace()      : de.close_workspace()                 ⚠️ UNCONFIRMED
    workspace_is_open()    : de.workspace_is_open()               ⚠️ UNCONFIRMED
    get_open_library()     : de.get_open_library(name)            ✅ CONFIRMED
    create_new_library()   : de.create_new_library(name, path)    ⚠️ UNCONFIRMED

The only fully confirmed workspace entry point is open_workspace().
All other workspace-level calls are wrapped with informative error messages
so failures surface cleanly on first Jarvis run.

Usage:
    from ads_api.ads_session import get_ads_session
    from ads_api.workspace_ops import open_workspace, ensure_library

    session = get_ads_session()
    ws  = open_workspace(session, "C:/Users/jarvis/ads_projects/net2ads_wrk")
    lib = ensure_library(session, "net2ads_lib")
"""

import warnings as _warnings
from pathlib import Path
from typing import Optional

from ads_api.ads_session import ADSSession


# ── Workspace ──────────────────────────────────────────────────────────────────

def open_workspace(session: ADSSession, path: str):
    """
    Open an existing ADS workspace and return the workspace object.

    Suppresses the benign vtb.defs / SystemVue warning that ADS emits on
    workspace open — confirmed safe to suppress (ADS_API_REFERENCE.md §1).

    Args:
        session : ADSSession from get_ads_session()
        path    : absolute path to the workspace directory

    Returns:
        workspace object (type: keysight.ads.de.Workspace)

    Raises:
        FileNotFoundError : workspace directory does not exist
        RuntimeError      : ADS rejects the path as a workspace
    """
    ws_path = Path(path)
    if not ws_path.exists():
        raise FileNotFoundError(
            f"Workspace path does not exist: {path}\n"
            "Create it with create_workspace() first, or provide an existing workspace."
        )

    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")           # suppress vtb.defs ✅ CONFIRMED pattern
        ws = session.de.open_workspace(str(ws_path))  # ✅ CONFIRMED

    print(f"[workspace] opened: {path}")
    return ws


def create_workspace(session: ADSSession, path: str):
    """
    Create a new ADS workspace at the given path and return it.

    ⚠️ UNCONFIRMED: de.create_workspace() — not yet verified on Jarvis.
    If this fails, the workspace must be created manually via ADS GUI,
    or via the ads_build_spdt_pdk.py pattern (create + lib.defs edit + reopen).

    Args:
        session : ADSSession from get_ads_session()
        path    : absolute path for the new workspace directory

    Returns:
        workspace object, or raises RuntimeError with guidance

    Raises:
        RuntimeError : if de.create_workspace is unavailable or fails
    """
    try:
        ws = session.de.create_workspace(str(path))  # ⚠️ UNCONFIRMED
        print(f"[workspace] created: {path}")
        return ws
    except AttributeError:
        raise RuntimeError(
            "de.create_workspace() is not available in this ADS version.\n"
            "Workaround: create the workspace in ADS GUI, then use open_workspace()."
        )
    except Exception as exc:
        raise RuntimeError(
            f"de.create_workspace() failed: {exc}\n"
            "Workaround: create the workspace in ADS GUI, then use open_workspace()."
        ) from exc


def open_or_create_workspace(session: ADSSession, path: str):
    """
    Open an existing workspace if it exists; otherwise create it.

    Args:
        session : ADSSession from get_ads_session()
        path    : absolute path to the workspace directory

    Returns:
        workspace object
    """
    ws_path = Path(path)
    if ws_path.exists():
        return open_workspace(session, path)
    else:
        return create_workspace(session, path)


def close_workspace(session: ADSSession) -> None:
    """
    Close the currently open workspace.

    ⚠️ UNCONFIRMED: de.close_workspace() — not yet verified on Jarvis.
    Safe to skip if the script exits immediately after saving.
    """
    try:
        session.de.close_workspace()   # ⚠️ UNCONFIRMED
        print("[workspace] closed")
    except AttributeError:
        print("[workspace] close_workspace() not available — skipped (safe at script exit)")
    except Exception as exc:
        print(f"[workspace] close_workspace() failed (non-fatal): {exc}")


# ── Library ────────────────────────────────────────────────────────────────────

def ensure_library(session: ADSSession, lib_name: str, lib_path: Optional[str] = None):
    """
    Return an open library handle. If the library is already open in the
    workspace, return it. If not, attempt to create it.

    The primary confirmed path is de.get_open_library() — this works when the
    library was already registered in the workspace (either via lib.defs or a
    prior create_new_library() call that persisted with the workspace).

    Args:
        session  : ADSSession from get_ads_session()
        lib_name : library name (e.g. "net2ads_lib")
        lib_path : directory for the library (required for creation; optional if it already exists)

    Returns:
        library object (type: keysight.ads.de.Library)

    Raises:
        RuntimeError : library cannot be found or created
    """
    # Try confirmed path first: get already-open library
    try:
        lib = session.de.get_open_library(lib_name)  # ✅ CONFIRMED
        print(f"[library] found existing: {lib_name}")
        return lib
    except Exception:
        pass  # library not open yet — proceed to create

    # Attempt creation — de.create_new_library is ⚠️ UNCONFIRMED
    if lib_path is None:
        raise RuntimeError(
            f"Library '{lib_name}' is not open and no lib_path provided.\n"
            "Either provide lib_path to create it, or ensure it is registered in workspace lib.defs."
        )

    try:
        lib = session.de.create_new_library(lib_name, str(lib_path))  # ⚠️ UNCONFIRMED
        print(f"[library] created: {lib_name} at {lib_path}")
        return lib
    except AttributeError:
        raise RuntimeError(
            f"de.create_new_library() not available in this ADS version.\n"
            f"Register library '{lib_name}' manually in the workspace lib.defs:\n"
            f"  DEFINE {lib_name} {lib_path}"
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to create library '{lib_name}': {exc}\n"
            f"Register the library manually in workspace lib.defs."
        ) from exc
