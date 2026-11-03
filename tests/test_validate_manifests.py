"""Tests for scripts/validate_manifests.py.

Ported from upstream scripts/test-validate.py (tag issue-flow--v0.17.0). Upstream
tested the spawn lint. This port tests the Codex manifest, marketplace, skill, and
role rules (FR-plugin-packaging-1 to 9). Each fixture is a small repository in a
temporary directory.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validate_manifests  # noqa: E402

MANIFEST = {
    "name": "issue-flow",
    "version": "0.1.0",
    "description": "Test plugin.",
    "skills": "./skills",
    "hooks": "./hooks/hooks.json",
}
MARKETPLACE = {
    "name": "issue-flow-codex",
    "plugins": [{
        "name": "issue-flow",
        "source": {"source": "local", "path": "./"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }],
}
SKILL = "---\nname: ping\ndescription: Answers a ping.\n---\n\nBody.\n"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path, data):
    write(path, json.dumps(data))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        write_json(self.repo / ".codex-plugin" / "plugin.json", MANIFEST)
        write_json(self.repo / ".agents" / "plugins" / "marketplace.json", MARKETPLACE)
        write_json(self.repo / "hooks" / "hooks.json", {"hooks": {}})
        write(self.repo / "skills" / "ping" / "SKILL.md", SKILL)

    def errors(self):
        return validate_manifests.check(self.repo)

    def edit_manifest(self, **changes):
        write_json(self.repo / ".codex-plugin" / "plugin.json", {**MANIFEST, **changes})

    def edit_entry(self, **changes):
        entry = {**MARKETPLACE["plugins"][0], **changes}
        write_json(self.repo / ".agents" / "plugins" / "marketplace.json",
                   {**MARKETPLACE, "plugins": [entry]})


class ManifestRules(Fixture):
    def test_passes_a_valid_repository(self):
        self.assertEqual(self.errors(), [])

    def test_fails_a_missing_manifest(self):
        (self.repo / ".codex-plugin" / "plugin.json").unlink()
        self.assertTrue(any("plugin.json: file is missing" in e for e in self.errors()))

    def test_fails_a_wrong_plugin_name(self):
        self.edit_manifest(name="other")
        self.assertTrue(any("name is 'other'" in e for e in self.errors()))

    def test_fails_a_version_that_is_not_semver(self):
        self.edit_manifest(version="one")
        self.assertTrue(any("not semver" in e for e in self.errors()))

    def test_fails_a_manifest_path_that_does_not_start_with_dot_slash(self):
        self.edit_manifest(skills="skills")
        self.assertTrue(any("'skills' must start with './'" in e for e in self.errors()))

    def test_fails_a_hooks_path_that_climbs_out_of_the_plugin(self):
        self.edit_manifest(hooks="./../hooks.json")
        self.assertTrue(any("'hooks' must not contain '..'" in e for e in self.errors()))

    def test_fails_a_manifest_path_that_does_not_exist(self):
        self.edit_manifest(hooks="./hooks/missing.json")
        self.assertTrue(any("'hooks' points at a missing path" in e for e in self.errors()))


class MarketplaceRules(Fixture):
    def test_fails_a_wrong_marketplace_name(self):
        write_json(self.repo / ".agents" / "plugins" / "marketplace.json",
                   {**MARKETPLACE, "name": "other"})
        self.assertTrue(any("marketplace name is 'other'" in e for e in self.errors()))

    def test_fails_an_entry_without_a_category(self):
        self.edit_entry(category="")
        self.assertTrue(any("category" in e for e in self.errors()))

    def test_fails_an_unknown_installation_policy(self):
        self.edit_entry(policy={"installation": "SOMETIMES", "authentication": "ON_INSTALL"})
        self.assertTrue(any("policy.installation" in e for e in self.errors()))

    def test_fails_a_missing_authentication_policy(self):
        self.edit_entry(policy={"installation": "AVAILABLE"})
        self.assertTrue(any("policy.authentication" in e for e in self.errors()))

    def test_fails_a_local_source_that_does_not_start_with_dot_slash(self):
        self.edit_entry(source={"source": "local", "path": "plugin"})
        self.assertTrue(any("source path must start with './'" in e for e in self.errors()))

    def test_fails_an_entry_name_that_differs_from_the_manifest(self):
        self.edit_entry(name="other")
        self.assertTrue(any("manifest name is 'issue-flow'" in e for e in self.errors()))


class SkillRules(Fixture):
    def test_fails_a_skill_with_no_description(self):
        write(self.repo / "skills" / "ping" / "SKILL.md", "---\nname: ping\n---\n\nBody.\n")
        self.assertTrue(any("missing 'description'" in e for e in self.errors()))

    def test_fails_a_skill_with_an_empty_description(self):
        write(self.repo / "skills" / "ping" / "SKILL.md",
              "---\nname: ping\ndescription:\n---\n\nBody.\n")
        self.assertTrue(any("missing 'description'" in e for e in self.errors()))

    def test_fails_a_skill_with_no_frontmatter(self):
        write(self.repo / "skills" / "ping" / "SKILL.md", "Body.\n")
        self.assertTrue(any("no YAML frontmatter" in e for e in self.errors()))

    def test_accepts_a_folded_description(self):
        write(self.repo / "skills" / "ping" / "SKILL.md",
              "---\nname: ping\ndescription: >\n  Answers\n  a ping.\n---\n\nBody.\n")
        self.assertEqual(self.errors(), [])


class RoleRules(Fixture):
    def role(self, text):
        write(self.repo / "roles" / "issue_worker.toml", text)

    def test_passes_a_role_file_with_applied_keys(self):
        self.role('model = "gpt-6-luna"\ndeveloper_instructions = "Build."\n')
        self.assertEqual(self.errors(), [])

    def test_fails_a_role_file_that_sets_sandbox_mode(self):
        self.role('sandbox_mode = "read-only"\n')
        self.assertTrue(any("'sandbox_mode'" in e for e in self.errors()))

    def test_fails_a_role_file_that_sets_approval_policy(self):
        self.role('approval_policy = "never"\n')
        self.assertTrue(any("'approval_policy'" in e for e in self.errors()))

    def test_fails_a_role_file_that_sets_mcp_servers(self):
        self.role("[mcp_servers.demo]\ncommand = \"x\"\n")
        self.assertTrue(any("'mcp_servers'" in e for e in self.errors()))

    def test_fails_a_role_file_that_does_not_parse(self):
        self.role("= broken\n")
        self.assertTrue(any("TOML does not parse" in e for e in self.errors()))


class Repository(unittest.TestCase):
    def test_passes_the_repository_manifest(self):
        self.assertEqual(validate_manifests.check(ROOT), [])


if __name__ == "__main__":
    unittest.main()
