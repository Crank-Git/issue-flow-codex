# External facts

Facts that agents need and that live outside the code. Names only. Never put a secret, a token, or a value here.

## Upstream

- Repository: `https://github.com/Sniper7Kills-LLC/claude-plugins`, directory `issue-flow/`.
- Release tags: `issue-flow--v<semver>`. The port tracks the tag in `upstream.lock`.
- Author: sniper7kills. License: MIT.

## Codex

- Install: Homebrew `codex`. Minimum version: 0.166.0.
- Login: the operator's OpenAI account, through `codex login`. The conformance suite links `~/.codex/auth.json`. It never copies it.
- Docs: `https://learn.chatgpt.com/docs/` (the old `developers.openai.com/codex/` paths redirect there).
- Source: `https://github.com/openai/codex`.

## Test beds

- GitHub test bed: `Crank-Git/issue-flow-codex-testbed`, private. Consumers read the name from `ISSUE_FLOW_TESTBED_GITHUB`.
- Gitea test bed: `e/issue-flow-codex-testbed`, private, on the `tea` login `telescope` (`https://telescope.lan`, Gitea 1.25.3). Consumers read the name from `ISSUE_FLOW_TESTBED_GITEA` and the server from `GITEA_SERVER_URL`. The server is the operator's real Gitea: the reset script touches only this one repository.
- Seed: `testbed/seed/` holds the seed project and `testbed/seed/issues.json`, one epic and five sub-issues.
- Reset: `python3 scripts/testbed-reset.py --forge github|gitea`. The script reads `ISSUE_FLOW_TESTBED_GITHUB` and `ISSUE_FLOW_TESTBED_GITEA`, defaults to the two names above, and touches no other repository. It exits 1 before any remote call when a repository name does not end in `-testbed`. It does these steps in order:
  1. Reuse the repository, or create it when it is missing.
  2. Force-push the seed commit to `main` and `dev`.
  3. Delete every other branch.
  4. Close every open pull request.
  5. Close every issue outside the seed set.
  6. Create the missing labels.
  7. Open the seed issues.

  A second run changes nothing. The script exits 1 and names the server URL when the Gitea server is down.
- Tokens: the `gh` and `tea` credential stores on the operator's machine. The script never reads or prints a token; `git` gets the Gitea token through `tea logins helper`.

## Browser MCP

- Server name: `playwright`. Added at user scope with `codex mcp add playwright -- npx -y @playwright/mcp@0.0.84 --output-dir .worktrees/review/playwright-mcp`.
- The server entry in `~/.codex/config.toml` also needs `default_tools_approval_mode = "approve"` under `[mcp_servers.playwright]`. Without it, Codex refuses each browser call when the approval policy is `never` (codex-harness facts 22-24).
