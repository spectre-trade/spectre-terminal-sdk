#!/usr/bin/env python3
"""Refresh ``contract/`` from a local checkout of spectre-terminal.

Usage: ``python3 scripts/sync_contract.py /path/to/spectre-terminal``

Copies the contract and the response fixtures verbatim and records the
terminal revision in ``contract/TERMINAL_VERSION``. This is the only way the
``contract/`` directory changes; see CONTRIBUTING.md.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

CONTRACT = pathlib.Path("docs/features/local-api/contract-v1.md")
FIXTURES = pathlib.Path("tests/it/local_api/fixtures")
HERE = pathlib.Path(__file__).resolve().parent.parent / "contract"


def git(terminal: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(terminal), *args], text=True).strip()


def app_version(terminal: pathlib.Path) -> str:
    text = (terminal / "Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else "unknown"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    terminal = pathlib.Path(argv[1]).resolve()
    source_contract = terminal / CONTRACT
    source_fixtures = terminal / FIXTURES
    if not source_contract.is_file() or not source_fixtures.is_dir():
        print(f"not a spectre-terminal checkout: {terminal}", file=sys.stderr)
        return 1

    shutil.copyfile(source_contract, HERE / "contract-v1.md")
    target = HERE / "fixtures"
    for stale in target.glob("*.json"):
        stale.unlink()
    copied = 0
    for fixture in sorted(source_fixtures.glob("*.json")):
        json.loads(fixture.read_text(encoding="utf-8"))  # refuse a broken fixture
        shutil.copyfile(fixture, target / fixture.name)
        copied += 1

    commit = git(terminal, "rev-parse", "--short", "HEAD")
    dirty = bool(git(terminal, "status", "--porcelain", "--", str(CONTRACT), str(FIXTURES)))
    (HERE / "TERMINAL_VERSION").write_text(
        "# The spectre-terminal revision this copy of the contract and fixtures was taken from.\n"
        "# Updated only by scripts/sync_contract.py; do not edit by hand.\n"
        f"commit={commit}{'-dirty' if dirty else ''}\n"
        f"app_version={app_version(terminal)}\n"
        "api_version=1\n",
        encoding="utf-8",
    )
    print(f"contract and {copied} fixtures copied from {commit}{' (dirty)' if dirty else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
