"""Where the port and the token come from.

The terminal publishes the port of its Local API as ``local_api_port`` in
``instance.json`` next to its database. The token comes only from the
``SPECTRE_LOCAL_API_TOKEN`` environment variable or an explicit argument.
Nothing else in the terminal's data directory is ever read.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .errors import LocalApiDisabled

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "TOKEN_ENV",
    "instance_path",
    "read_port",
    "token_from_env",
]

DEFAULT_HOST = "127.0.0.1"
"""The only host the terminal listens on."""

DEFAULT_PORT = 48180
"""The port used when ``instance.json`` cannot be read."""

TOKEN_ENV = "SPECTRE_LOCAL_API_TOKEN"
"""Environment variable holding the token copied from the Settings App."""

_APP_DIR = "spectre-terminal"
_INSTANCE_FILE = "instance.json"


def instance_path() -> Path:
    """The path of the terminal's ``instance.json`` on this platform.

    Linux: ``$XDG_DATA_HOME`` or ``~/.local/share``; macOS:
    ``~/Library/Application Support``; Windows: ``%LOCALAPPDATA%``, then
    ``%APPDATA%`` — each followed by ``spectre-terminal/instance.json``. The
    file is not required to exist.
    """
    platform = sys.platform
    if platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / _APP_DIR / _INSTANCE_FILE


def read_port(path: Path | None = None) -> int | None:
    """The Local API port published in ``instance.json``, or ``None`` when unknown.

    ``None`` means the file is missing or unreadable — the caller falls back
    to :data:`DEFAULT_PORT`. A file whose ``local_api_port`` is ``null`` or
    absent means the terminal is running with the API switched off, which
    raises :class:`~spectre_terminal.errors.LocalApiDisabled`.
    """
    file = instance_path() if path is None else path
    try:
        text = file.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        info = json.loads(text)
    except ValueError:
        return None
    if not isinstance(info, dict):
        return None
    port = info.get("local_api_port")
    if port is None:
        raise LocalApiDisabled(
            "the terminal is running but its Local API is switched off: "
            "enable it in Settings App -> General -> Local API"
        )
    if isinstance(port, bool) or not isinstance(port, int):
        return None
    return port


def token_from_env() -> str | None:
    """The token from ``SPECTRE_LOCAL_API_TOKEN``, or ``None`` when unset or blank."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    return token or None
