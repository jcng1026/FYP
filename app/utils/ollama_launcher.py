"""Best-effort auto-start of a local Ollama server at application launch.

MarkAssist's natural-language feedback (Local AI Settings -> Ollama) needs a
local Ollama server on localhost:11434. If Ollama is installed but not running,
feedback silently falls back to the built-in templates. This starts the server
once at launch so it is ready by the time a teacher generates feedback.

Ollama is a native application installed separately - not bundled with
MarkAssist. See docs/requirements-ai.txt or scripts/setup_ollama.ps1 for the
one-line install (`winget install --id Ollama.Ollama -e` and
`ollama pull llama3.2`).

Entirely optional and non-fatal: if Ollama is not installed, already running, or
cannot start, the application is unaffected. Nothing here ever raises.
"""
import os
import shutil
import subprocess
import sys
import urllib.request

_OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"


def _ollama_reachable(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(_OLLAMA_TAGS_URL, timeout=timeout):
            return True
    except Exception:
        return False


def _find_ollama_exe():
    """The Ollama CLI/server executable, or None if it is not installed."""
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Ollama", "ollama.exe"),
        shutil.which("ollama"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def ensure_ollama_running() -> str:
    """Start a local Ollama server if one is installed but not already running.

    Returns a short status string (for logging/diagnostics):
      'already_running' | 'started' | 'not_installed' | 'error'
    Never raises - a failure just means feedback uses the offline templates.
    """
    try:
        if _ollama_reachable():
            return "already_running"
        exe = _find_ollama_exe()
        if not exe:
            return "not_installed"
        creationflags = 0
        if sys.platform == "win32":
            # Detached + no console window: the server outlives and is
            # independent of the MarkAssist process, and shows no terminal.
            creationflags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
        return "started"
    except Exception:
        return "error"
