#!/usr/bin/env python3
"""Release helpers: keep Git tags and the manifest version in sync.

Commands:
  next [--bump patch|minor|major]  Print the next version.
  set VERSION                      Write VERSION into the manifest.
  check VERSION                    Fail unless the manifest has VERSION.
  latest-tag                       Print the highest release tag (or nothing).
  changed                          Exit 0 if the integration changed since the
                                   latest tag, 1 if not. The manifest version
                                   field is ignored, so release bumps don't count.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

MANIFEST = Path("custom_components/yahoofinance/manifest.json")
# Paths whose changes affect what users install through HACS
RELEASE_PATHS = ("custom_components", "hacs.json")
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
BUMPS = ("patch", "minor", "major")

Version = tuple[int, int, int]


def parse_version(value: str) -> Version:
    """Parse ``1.2.3`` or ``v1.2.3``."""
    match = SEMVER.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid semantic version: {value!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def stringify(version: Version) -> str:
    """Return ``1.2.3``."""
    return ".".join(str(part) for part in version)


def bump(version: Version, kind: str) -> Version:
    """Return the version bumped by ``kind``."""
    major, minor, patch = version
    if kind == "major":
        return major + 1, 0, 0
    if kind == "minor":
        return major, minor + 1, 0
    if kind == "patch":
        return major, minor, patch + 1
    raise ValueError(f"Unknown bump: {kind!r}")


def git(*args: str) -> str:
    """Run git and return stdout."""
    return subprocess.check_output(["git", *args], text=True)


def read_manifest(text: str | None = None) -> dict:
    """Return the manifest, from ``text`` or the working tree."""
    if text is None:
        text = MANIFEST.read_text(encoding="utf-8")
    return json.loads(text)


def latest_tag() -> str | None:
    """Return the highest semantic version tag, if any."""
    tags = [tag for tag in git("tag", "--list").splitlines() if SEMVER.fullmatch(tag)]
    return max(tags, key=parse_version) if tags else None


def next_version(kind: str = "patch") -> Version:
    """Return the next version from the higher of the manifest and latest tag."""
    current = parse_version(str(read_manifest()["version"]))
    tag = latest_tag()
    if tag is not None:
        current = max(current, parse_version(tag))
    return bump(current, kind)


def manifests_equal_ignoring_version(old: dict, new: dict) -> bool:
    """Compare manifests without their version field."""
    return {k: v for k, v in old.items() if k != "version"} == {
        k: v for k, v in new.items() if k != "version"
    }


def integration_changed_since(tag: str) -> bool:
    """Return True if anything users install changed since ``tag``."""
    changed = git("diff", "--name-only", tag, "HEAD", "--", *RELEASE_PATHS).split()
    others = [path for path in changed if path != MANIFEST.as_posix()]
    if others:
        return True
    if MANIFEST.as_posix() in changed:
        old = read_manifest(git("show", f"{tag}:{MANIFEST.as_posix()}"))
        return not manifests_equal_ignoring_version(old, read_manifest())
    return False


def main() -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    next_parser = sub.add_parser("next")
    next_parser.add_argument("--bump", choices=BUMPS, default="patch")
    for command in ("set", "check"):
        sub.add_parser(command).add_argument("version")
    sub.add_parser("latest-tag")
    sub.add_parser("changed")
    args = parser.parse_args()

    if args.command == "next":
        print(stringify(next_version(args.bump)))
    elif args.command == "latest-tag":
        print(latest_tag() or "")
    elif args.command == "changed":
        tag = latest_tag()
        if tag is None or integration_changed_since(tag):
            print("changed")
            return 0
        print(f"unchanged since {tag}")
        return 1
    else:
        expected = stringify(parse_version(args.version))
        contents = read_manifest()
        if args.command == "set":
            contents["version"] = expected
            MANIFEST.write_text(json.dumps(contents, indent=2) + "\n", encoding="utf-8")
        elif contents["version"] != expected:
            print(
                f"Manifest version {contents['version']} != {expected}", file=sys.stderr
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
