#!/usr/bin/env python3
"""Select the port tag when the plugin manifest version changes."""

import argparse
import json
import re
import sys
from pathlib import Path

VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z")


def tag_for_change(previous, current):
    """Return the release tag when the manifest version changes."""
    new_version = json.loads(current)["version"]
    old_version = json.loads(previous)["version"] if previous.strip() else None
    if old_version is not None and not isinstance(old_version, str):
        raise ValueError("previous manifest version must be a string")
    if not isinstance(new_version, str):
        raise ValueError("manifest version must be a string")
    if not VERSION.fullmatch(new_version):
        raise ValueError(f"invalid manifest version: {new_version}")
    if old_version == new_version:
        return None
    return f"issue-flow-codex--v{new_version}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args(argv)
    try:
        tag = tag_for_change(args.previous.read_bytes(), args.current.read_bytes())
    except (OSError, KeyError, ValueError) as error:
        print(f"cannot select release tag: {error}", file=sys.stderr)
        return 1
    if tag:
        print(tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
