#!/usr/bin/env python3
"""Select the port tag when the plugin manifest version changes."""

import argparse
import json
import re
import sys
from pathlib import Path

VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z")


def tag_for_manifest(current, existing_tags):
    """Return the release tag when the current manifest version has no tag."""
    new_version = json.loads(current)["version"]
    if not isinstance(new_version, str):
        raise ValueError("manifest version must be a string")
    if not VERSION.fullmatch(new_version):
        raise ValueError(f"invalid manifest version: {new_version}")
    tag = f"issue-flow-codex--v{new_version}"
    if tag in existing_tags:
        return None
    return tag


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", type=Path)
    parser.add_argument("tags", type=Path)
    args = parser.parse_args(argv)
    try:
        existing_tags = args.tags.read_text(encoding="utf-8").splitlines()
        tag = tag_for_manifest(args.current.read_bytes(), existing_tags)
    except (OSError, KeyError, ValueError) as error:
        print(f"cannot select release tag: {error}", file=sys.stderr)
        return 1
    if tag:
        print(tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
