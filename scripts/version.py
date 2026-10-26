#!/usr/bin/env python3
"""Keep Yahoo Finance Git release tags and manifest versions synchronized."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

MANIFEST = Path("custom_components/yahoofinance/manifest.json")
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())


def stringify(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def highest_tag() -> tuple[int, int, int] | None:
    output = subprocess.check_output(["git", "tag", "--list"], text=True)
    found = [parse_version(tag) for tag in output.splitlines() if SEMVER.fullmatch(tag)]
    return max(found) if found else None


def next_version() -> tuple[int, int, int]:
    current = parse_version(str(manifest()["version"]))
    tagged = highest_tag()
    if tagged is not None:
        current = max(current, tagged)
    return current[0], current[1], current[2] + 1


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("next")
    for command in ("set", "check"):
        item = sub.add_parser(command)
        item.add_argument("version")
    args = parser.parse_args()

    if args.command == "next":
        print(stringify(next_version()))
        return

    expected = stringify(parse_version(args.version))
    contents = manifest()
    if args.command == "set":
        contents["version"] = expected
        MANIFEST.write_text(json.dumps(contents, indent=2) + "\n", encoding="utf-8")
    elif contents["version"] != expected:
        raise SystemExit(f"Manifest version {contents['version']} != {expected}")


if __name__ == "__main__":
    main()
