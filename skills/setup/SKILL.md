---
name: setup
description: Configure one project for the issue-flow loop. Use when the operator says "$issue-flow:setup", "set up issue-flow", or "configure this project for issue-flow". Copies the role files into .codex/agents/, writes the issue-flow block in .codex/config.toml, and adds .worktrees/ to .gitignore. Shows the diff of each file and writes a file only after the operator accepts it.
---

# Setup — configure a project for the issue-flow loop

A Codex plugin cannot ship roles or a thread limit. This skill puts them in the project.
The script `scripts/setup_project.py` does the file work. This skill shows the diffs and
asks the operator.

## Find the plugin root

The skill catalog gives you the absolute path of this `SKILL.md`. The plugin root is the
directory two levels above it. Call it `<pluginRoot>`. The script is
`<pluginRoot>/scripts/setup_project.py`.

## Procedure

1. Take the project directory from the operator. If the operator names none, use the
   current directory. Call it `<project>`.
2. Run `python3 <pluginRoot>/scripts/setup_project.py plan --project <project>`.
   The command writes nothing. It prints one unified diff for each file that setup
   changes, or the line `no changes`.
3. If the plan prints `no changes`, tell the operator that the project is set up. Go to step 8.
4. Show the operator the full diff of each file. Do not summarize a diff.
5. Ask the operator about `default_permissions = "issue_flow"` as its own question.
   The line makes `issue_flow` the permission profile of every Codex session in the
   project, not only of the loop. Add `--with-default-permissions` to the `plan` and
   `apply` commands only if the operator says yes. If you add it, run `plan` again and
   show the new diff of `.codex/config.toml`.
6. Ask the operator which files to write. Each file is a path that the plan shows, for
   example `.codex/agents/issue_worker.toml`, `.codex/config.toml`, or `.gitignore`.
   Accept a file only when the operator accepts its diff.
7. Run `python3 <pluginRoot>/scripts/setup_project.py apply --project <project> --accept <file>...`
   with the accepted files. Keep the `--with-default-permissions` choice from step 5.
   The command writes only those files. Do not write any other file.
8. Tell the operator these steps:
   - Run `/hooks` and trust the issue-flow hooks. Codex skips plugin hooks that the operator has not trusted.
   - Start a new `codex` session. Codex reads `.codex/` only for a trusted project.

## Rules

- The block in `.codex/config.toml` sits between the lines `# issue-flow:begin` and
  `# issue-flow:end`. The script changes no text outside those lines.
- The thread limit is the run concurrency plus 4. The script reads the concurrency from
  `<project>/.issue-flow.json` and uses 3 when the file has none.
- Run `apply` again with `--with-default-permissions` each time you want the line kept.
  A run without the flag writes the block without that line.
- If the script exits with an error, show the operator the message. Do not edit the files by hand.
