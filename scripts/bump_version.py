#!/usr/bin/env python3
"""Bump the one version of every package and close the changelog section.

Usage: ``python3 scripts/bump_version.py <kind> [--dry-run]``

``kind`` is one of:

- ``major`` / ``minor`` / ``patch`` — from a stable version ``X.Y.Z``;
- ``rc`` — ``X.Y.Z-rc.N`` → ``X.Y.Z-rc.N+1``, or from a stable ``X.Y.Z`` the
  candidate of the next patch, ``X.Y.Z+1-rc.1``;
- ``release`` — ``X.Y.Z-rc.N`` → ``X.Y.Z``.

From a release candidate only ``rc`` and ``release`` are allowed: a candidate
is finished or continued, not skipped over. The version is written to
``typescript/package.json`` (and its lock file) in SemVer, to
``python/pyproject.toml`` and ``mcp/pyproject.toml`` in PEP 440 (``rc.N`` →
``rcN``); the MCP server pins the client of the same version. The
``[Unreleased]`` section of ``CHANGELOG.md`` becomes ``[version] - date`` and a
fresh empty ``[Unreleased]`` is opened above it. Prints the new SemVer version.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE_JSON = ROOT / "typescript" / "package.json"
PYPROJECTS = [ROOT / "python" / "pyproject.toml", ROOT / "mcp" / "pyproject.toml"]
CHANGELOG = ROOT / "CHANGELOG.md"
KINDS = ("major", "minor", "patch", "rc", "release")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")


def current() -> str:
    return json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["version"]


def bump(version: str, kind: str) -> str:
    match = SEMVER.match(version)
    if not match:
        raise SystemExit(f"unsupported version {version!r}: expected X.Y.Z or X.Y.Z-rc.N")
    major, minor, patch, rc = (int(g) if g is not None else None for g in match.groups())
    if rc is not None:
        if kind == "rc":
            return f"{major}.{minor}.{patch}-rc.{rc + 1}"
        if kind == "release":
            return f"{major}.{minor}.{patch}"
        raise SystemExit(f"{version} is a release candidate: use rc or release, not {kind}")
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if kind == "rc":
        return f"{major}.{minor}.{patch + 1}-rc.1"
    raise SystemExit(f"{version} is not a release candidate: nothing to release")


def pep440(version: str) -> str:
    return re.sub(r"-rc\.(\d+)$", r"rc\1", version)


def write_pyprojects(version: str, dry_run: bool) -> None:
    py = pep440(version)
    for path in PYPROJECTS:
        text = path.read_text(encoding="utf-8")
        text, n = re.subn(r'^version = "[^"]+"', f'version = "{py}"', text, count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"{path}: no version line")
        text, _ = re.subn(
            r'"spectre-terminal[=<>!~][^"]*"', f'"spectre-terminal=={py}"', text, count=1
        )
        if not dry_run:
            path.write_text(text, encoding="utf-8")


def write_package_json(version: str, dry_run: bool) -> None:
    if dry_run:
        return
    subprocess.run(
        ["npm", "version", version, "--no-git-tag-version", "--allow-same-version"],
        cwd=ROOT / "typescript",
        check=True,
        capture_output=True,
    )


def close_changelog(version: str, dry_run: bool) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    head = "## [Unreleased]\n"
    if head not in text:
        raise SystemExit("CHANGELOG.md has no [Unreleased] section")
    before, after = text.split(head, 1)
    body, sep, rest = after.partition("\n## [")
    if not body.strip():
        body = "\nNo user-facing changes.\n"
    today = dt.date.today().isoformat()
    text = f"{before}{head}\n## [{version}] - {today}\n{body.rstrip()}\n{sep}{rest}"
    if not dry_run:
        CHANGELOG.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in argv
    if len(args) != 1 or args[0] not in KINDS:
        print(__doc__, file=sys.stderr)
        return 2
    version = bump(current(), args[0])
    write_pyprojects(version, dry_run)
    write_package_json(version, dry_run)
    close_changelog(version, dry_run)
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
