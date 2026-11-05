"""MCP server for Spectre Terminal: tools over the Local API.

The server is a thin layer on top of :mod:`spectre_terminal`. It speaks the
Model Context Protocol over stdio and exposes a handful of tools designed for
a language model: compact answers, one call per question, no thousand-row
payloads. See :func:`spectre_terminal_mcp.server.build_server`.
"""

from __future__ import annotations

try:
    from importlib.metadata import version as _version

    __version__ = _version("spectre-terminal-mcp")
except Exception:  # a source checkout without the package installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
