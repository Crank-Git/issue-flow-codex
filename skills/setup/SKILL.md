---
name: setup
description: Configure one project for the issue-flow loop. Use when the operator says "$issue-flow:setup", "set up issue-flow", or "configure this project for issue-flow". Copies the role files into .codex/agents/, writes the issue-flow block in .codex/config.toml, and adds .worktrees/ to .gitignore. Shows the diff of each file and writes a file only after the operator accepts it. Also checks an existing setup when the operator asks.
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
4. Show the operator the full diff of each file. Do not summarize a diff. If the output
   starts with a `note:` line, repeat it: it says that the config block keeps its
   `default_permissions` line.
5. Ask the operator about `default_permissions = "issue_flow"` as its own question.
   The line makes `issue_flow` the permission profile of every Codex session in the
   project, not only of the loop. Add `--with-default-permissions` to the `plan` and
   `apply` commands only if the operator says yes. If the operator rejects a line that
   the file already holds, add `--without-default-permissions` instead. With neither
   flag, a line that the file holds stays. If you add a flag, run `plan` again and
   show the new diff of `.codex/config.toml`.
6. Ask about each file, one question per file, in plain text. Name the path as the plan
   shows it, for example `.codex/agents/issue_worker.toml`, `.codex/config.toml`, or
   `.gitignore`, and ask whether the operator will apply the change. Then end your turn
   and wait for the answers. Codex has no question tool in default mode. The operator
   answers in the next message. Accept a file only when the operator accepts its diff.
7. Run `python3 <pluginRoot>/scripts/setup_project.py apply --project <project> --accept <file>...`
   for accepted files outside `.codex/` only. Keep the default-permissions flag from
   step 5. The operator applies accepted `.codex/` changes outside Codex because the
   session keeps `.codex/` read-only. Skip the command when no other file is accepted.
8. End with a message that lists the next steps:
   - Apply accepted `.codex/` changes outside Codex.
   - Start a new `codex` session after applying `.codex/config.toml`. Codex reads the
     profile at session start.
   - Run `/hooks` and trust the issue-flow hooks. Codex skips plugin hooks that the operator has not trusted.
   - Start a new `codex` session. Codex reads `.codex/` only for a trusted project.

## Check mode

When the operator asks to check the setup, run
`python3 <pluginRoot>/scripts/setup_project.py check --project <project>` and show the
output. The command writes nothing. Each item is `ok`, `missing`, or `stale`. A role
file is `stale` when its keys other than `model` and `model_reasoning_effort` differ from
the plugin copy. The `hooks` item is always
`unknown`: tell the operator to run `/hooks` to see the trust state. Exit code 1 means
an item is `missing` or `stale`. Offer to run the setup procedure to repair it.

## Rules

- The block in `.codex/config.toml` sits between the lines `# issue-flow:begin` and
  `# issue-flow:end`. The script changes no text outside those lines.
- The thread limit is the run concurrency plus 4. The script reads the concurrency from
  `<project>/.issue-flow.json` and uses 3 when the file has none.
- Setup reads `workerModel`, `workerEffort`, and `helperModel` from
  `<project>/.issue-flow.codex.json`. It uses each plugin role value when a key is absent.
- If the operator changes concurrency, rerun `plan` and show its full diff. Ask about
  `.codex/config.toml` only, then apply only that file with `--accept .codex/config.toml`.
- A rerun of `apply` keeps a `default_permissions` line that the block holds, unless
  the operator rejects it.
- If the script exits with an error, show the operator the message. Do not edit the files by hand.
