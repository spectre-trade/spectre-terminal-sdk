#!/usr/bin/env python3
"""List the terminal's exchange connections.

Needs a running terminal with the Local API switched on and the token in
``SPECTRE_LOCAL_API_TOKEN``.
"""

from __future__ import annotations

import sys

from spectre_terminal import SpectreTerminalError, Terminal


def main() -> int:
    terminal = Terminal.discover()
    meta = terminal.meta()
    print(f"Spectre Terminal {meta.app_version} ({meta.build_env}), API v{meta.api_version}")
    for connection in terminal.connections():
        last = connection.status.last_event
        event = f"{last.code} @ {last.ts}" if last else "-"
        flags = ", ".join(
            name
            for name, on in (
                ("enabled", connection.enabled),
                ("read-only", connection.read_only),
                ("credentials", connection.has_credentials),
                ("proxy", connection.proxy_bound),
            )
            if on
        )
        print(
            f"{connection.id:>4}  {connection.exchange}:{connection.market:<8} "
            f"{connection.label!r:<20} {connection.status.state:<10} [{flags}]  last: {event}"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SpectreTerminalError as error:
        sys.exit(f"error: {error}")
