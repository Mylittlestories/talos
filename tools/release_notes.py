#!/usr/bin/env python3
"""
Pull the release notes for one version out of CHANGELOG.md.

    python tools/release_notes.py 2.0.0 > notes.md

The release workflow uses this so the tag, the changelog and the GitHub
Release can never drift apart. Falls back to the first `## [x.y.z]` section
when no argument is given, and exits non-zero if the version is missing —
a release without notes is a bug.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"

SECTION = re.compile(r"^##\s+\[([^\]]+)\].*$")


def section_for(version: str) -> str:
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    wanted = version.lstrip("v")
    start = None
    for index, line in enumerate(lines):
        match = SECTION.match(line)
        if not match:
            continue
        if match.group(1).strip().lstrip("v") == wanted:
            start = index + 1
            break
    if start is None:
        raise SystemExit(f"no [ {wanted} ] section in {CHANGELOG}")
    body = []
    for line in lines[start:]:
        if SECTION.match(line):
            break
        body.append(line)
    text = "\n".join(body).strip()
    return text + "\n"


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        version = argv[1]
    else:
        # no argument: the newest real version in the file
        versions = [m.group(1) for m in
                    (SECTION.match(line) for line in
                     CHANGELOG.read_text(encoding="utf-8").splitlines()) if m]
        versions = [v for v in versions if v.strip().lower() != "unreleased"]
        if not versions:
            raise SystemExit("CHANGELOG.md has no version sections")
        version = versions[0]
    sys.stdout.write(section_for(version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
