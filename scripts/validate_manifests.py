#!/usr/bin/env python3
"""Validate the Codex plugin manifest, the marketplace file, skills, and role files.

Ported from upstream scripts/validate-manifests.py (tag issue-flow--v0.17.0). The
upstream link and spawn lints check Claude Code behavior and are not ported.

Run it before you push, and let CI run it on every pull request:

    python3 scripts/validate_manifests.py

Each failure below is silent at runtime. Codex logs a warning and ignores a manifest
path that does not start with `./`. A skill with no description never triggers. A role
file key that Codex ignores gives the operator a false sense of control.
"""

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+([-+].+)?$")
PLUGIN_NAME = "issue-flow"
MARKETPLACE_NAME = "issue-flow-codex"
INSTALL_POLICIES = ("NOT_AVAILABLE", "AVAILABLE", "INSTALLED_BY_DEFAULT")
AUTH_POLICIES = ("ON_INSTALL", "ON_USE")
# Codex applies none of these keys in a role file (codex-harness.md, "Role files").
IGNORED_ROLE_KEYS = ("sandbox_mode", "approval_policy", "mcp_servers")
BLOCK_SCALARS = (">", "|", ">-", "|-", ">+", "|+")


def load_json(path, root, errors):
    """Return the parsed file, or None after it adds an error."""
    rel = path.relative_to(root)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{rel}: file is missing")
    except json.JSONDecodeError as exc:
        errors.append(f"{rel}: JSON does not parse - {exc}")
    return None


def has_description(frontmatter):
    """True when a top-level `description` key has text, inline or in a block scalar."""
    lines = frontmatter.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value in BLOCK_SCALARS:
            return any(next_line.strip() and next_line[0] in " \t"
                       for next_line in lines[index + 1:index + 2])
        return bool(value)
    return False


def check_skill(path, root, errors):
    rel = path.relative_to(root)
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    if match is None:
        errors.append(f"{rel}: skill has no YAML frontmatter")
    elif not has_description(match.group(1)):
        errors.append(f"{rel}: skill frontmatter is missing 'description'")


def check_role(path, root, errors):
    rel = path.relative_to(root)
    try:
        role = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        errors.append(f"{rel}: TOML does not parse - {exc}")
        return
    for key in IGNORED_ROLE_KEYS:
        if key in role:
            errors.append(f"{rel}: sets '{key}', which Codex ignores in a role file")


def check_manifest_path(plugin_dir, manifest, field, errors):
    """Codex ignores a manifest path that breaks these rules (manifest.rs, resolve_manifest_path)."""
    value = manifest.get(field)
    if not isinstance(value, str) or not value:
        errors.append(f".codex-plugin/plugin.json: '{field}' is missing")
    elif not value.startswith("./"):
        errors.append(f".codex-plugin/plugin.json: '{field}' must start with './' - {value}")
    elif ".." in value.split("/"):
        errors.append(f".codex-plugin/plugin.json: '{field}' must not contain '..' - {value}")
    elif not (plugin_dir / value[2:]).exists():
        errors.append(f".codex-plugin/plugin.json: '{field}' points at a missing path - {value}")


def check_manifest(plugin_dir, name, errors):
    manifest = load_json(plugin_dir / ".codex-plugin" / "plugin.json", plugin_dir, errors)
    if manifest is None:
        return
    if manifest.get("name") != name:
        errors.append(f"marketplace entry name is '{name}', "
                      f"manifest name is '{manifest.get('name')}'")
    if manifest.get("name") != PLUGIN_NAME:
        errors.append(f".codex-plugin/plugin.json: name is '{manifest.get('name')}', "
                      f"expected '{PLUGIN_NAME}'")
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER.match(version):
        errors.append(f".codex-plugin/plugin.json: version is not semver - {version}")
    for field in ("skills", "hooks"):
        check_manifest_path(plugin_dir, manifest, field, errors)


def resolve_source(source):
    """Return the relative path of a local plugin source, or None for another kind."""
    if isinstance(source, str):
        return source
    if isinstance(source, dict) and source.get("source") == "local":
        return source.get("path", "")
    return None


def check_entry(entry, root, errors):
    name = entry.get("name", "<unnamed>")
    path = resolve_source(entry.get("source"))
    if path is None:
        errors.append(f"marketplace entry '{name}': source is not a local path")
        return None
    if path in (".", "./"):
        plugin_dir = root
    elif not path.startswith("./"):
        errors.append(f"marketplace entry '{name}': source path must start with './' - {path}")
        return None
    else:
        plugin_dir = root / path[2:]
    if not plugin_dir.is_dir():
        errors.append(f"marketplace entry '{name}': source directory is missing - {path}")
        return None

    policy = entry.get("policy") or {}
    for key, allowed in (("installation", INSTALL_POLICIES), ("authentication", AUTH_POLICIES)):
        if policy.get(key) not in allowed:
            errors.append(f"marketplace entry '{name}': policy.{key} must be one of "
                          f"{', '.join(allowed)}")
    if not entry.get("category"):
        errors.append(f"marketplace entry '{name}': category is missing")
    return plugin_dir


def check(root):
    """Return the list of error lines for the repository at `root`."""
    root = Path(root)
    errors = []
    marketplace = load_json(root / ".agents" / "plugins" / "marketplace.json", root, errors)
    if marketplace is None:
        return errors
    if marketplace.get("name") != MARKETPLACE_NAME:
        errors.append(f".agents/plugins/marketplace.json: marketplace name is "
                      f"'{marketplace.get('name')}', expected '{MARKETPLACE_NAME}'")
    entries = marketplace.get("plugins") or []
    if not entries:
        errors.append(".agents/plugins/marketplace.json: lists no plugins")

    for entry in entries:
        plugin_dir = check_entry(entry, root, errors)
        if plugin_dir is None:
            continue
        check_manifest(plugin_dir, entry.get("name"), errors)
        for skill in sorted((plugin_dir / "skills").glob("*/SKILL.md")):
            check_skill(skill, root, errors)
        for role in sorted((plugin_dir / "roles").glob("*.toml")):
            check_role(role, root, errors)
    return errors


def main():
    errors = check(ROOT)
    for message in errors:
        print(f"error: {message}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} error(s)", file=sys.stderr)
        sys.exit(1)
    print("validation passed")


if __name__ == "__main__":
    main()
