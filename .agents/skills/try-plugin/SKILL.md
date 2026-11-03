---
name: try-plugin
description: Install this working tree as a Codex plugin in an isolated CODEX_HOME, to see a change in a real Codex session. Use when asked to try, install, or demo the plugin.
---

# Try the plugin from the working tree

The operator's `~/.codex` stays unchanged. Every step uses a temporary `CODEX_HOME`.

1. Create a temporary directory. Call it `$H`.
2. Link the login: `ln -s ~/.codex/auth.json "$H/auth.json"`. Never copy the file.
3. Add the working tree as a marketplace: `CODEX_HOME="$H" codex plugin marketplace add "$PWD"`.
4. Install the plugin: `CODEX_HOME="$H" codex plugin add issue-flow@issue-flow-codex`.
5. Tell the operator the command to start a session: `CODEX_HOME="$H" codex -C <test project>`.
6. Tell the operator to run `/hooks` in that session and trust the issue-flow hooks. Codex skips untrusted plugin hooks.

To remove the trial, delete `$H`.

If `.codex-plugin/plugin.json` or `.agents/plugins/marketplace.json` does not exist yet, stop and say so. Epic 1 builds them.
