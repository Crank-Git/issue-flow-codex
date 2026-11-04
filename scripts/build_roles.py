#!/usr/bin/env python3
"""Build the Codex role files in roles/ from the ported agent files in agents/.

Port-only script. Run it after you edit a ported agent file:

    python3 scripts/build_roles.py          # write roles/*.toml
    python3 scripts/build_roles.py --check  # exit 1 when a role file is stale

Codex applies only `developer_instructions`, the model keys, and a few more keys in a
role file (codex-harness.md, "Role files"). The script writes only those keys.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# An agent file joins this list when its feature ports it. Other agent files keep their
# Claude Code front-matter until then (issue #35).
PORTED = (
    "issue-worker", "ci-watcher", "ux-explorer", "deploy-verifier",
    "review-scribe", "code-auditor",
)
# The Codex model and effort of each ported role. The agent file names a Claude model.
CODEX_MODELS = {
    "issue_worker": ("gpt-6.1-sol", "medium"),
    "ci_watcher": ("gpt-6-luna", "low"),
    "ux_explorer": ("gpt-6.1-sol", "medium"),
    "deploy_verifier": ("gpt-6-luna", "low"),
    "review_scribe": ("gpt-6.1-sol", "medium"),
    "code_auditor": ("gpt-6-luna", "low"),
}
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)
LITERAL_DELIMITER = "'''"


def parse_agent(text):
    """Return (name, description, body) of an agent file."""
    match = FRONTMATTER.match(text)
    header = match.group(1)
    name = re.search(r"^name:\s*(\S+)", header, re.M).group(1)
    block = re.search(r"^description:\s*[>|]-?\n((?:[ \t]+.*\n?)+)", header + "\n", re.M)
    description = " ".join(line.strip() for line in block.group(1).splitlines())
    return name, description, text[match.end():].strip("\n") + "\n"


def toml_basic(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(text):
    """Return the TOML text of the role file for one agent file."""
    name, description, body = parse_agent(text)
    role = name.replace("-", "_")
    model, effort = CODEX_MODELS[role]
    if LITERAL_DELIMITER in body:
        raise ValueError(f"{name}: the body holds {LITERAL_DELIMITER}, "
                         "which ends a TOML literal string")
    # A literal string keeps backslashes and backticks as they are.
    return "\n".join([
        f"name = {toml_basic(role)}",
        f"description = {toml_basic(description)}",
        f"model = {toml_basic(model)}",
        f"model_reasoning_effort = {toml_basic(effort)}",
        f"developer_instructions = {LITERAL_DELIMITER}",
        body + LITERAL_DELIMITER,
    ]) + "\n"


def built(root):
    """Return {relative path: TOML text} for each ported agent file."""
    return {f"roles/{stem}.toml": render((root / "agents" / f"{stem}.md").read_text(encoding="utf-8"))
            for stem in PORTED}


def write(root):
    for rel, text in built(root).items():
        target = root / rel
        target.parent.mkdir(exist_ok=True)
        target.write_text(text, encoding="utf-8")


def stale(root):
    """Return the role files that are missing or differ from a fresh build."""
    return [rel for rel, text in built(root).items()
            if not (root / rel).is_file() or (root / rel).read_text(encoding="utf-8") != text]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when a role file is stale")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.check:
        write(args.root)
        return 0
    old = stale(args.root)
    if old:
        print("error: stale role file, run scripts/build_roles.py: " + ", ".join(old),
              file=sys.stderr)
    return 1 if old else 0


if __name__ == "__main__":
    sys.exit(main())
