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
- Gitea test bed: `a/issue-flow-codex-testbed` on the `tea` login `testgitea`. Consumers read the name from `ISSUE_FLOW_TESTBED_GITEA` and the server from `GITEA_SERVER_URL` (`http://192.168.2.21:3000`).
- Seed: `testbed/seed/` holds the seed project and `testbed/seed/issues.json`, one epic and five sub-issues.
- Reset: `python3 scripts/testbed-reset.py --forge github|gitea`. The script pins both names above and touches no other repository. It reuses an existing repository, force-pushes the seed commit to `main` and `dev`, deletes every other branch, closes every open pull request and every issue outside the seed set, creates the missing labels, and opens the seed issues. A second run changes nothing. It exits 1 and names the server URL when the Gitea server is down.
- Tokens: the `gh` and `tea` credential stores on the operator's machine. The script never reads or prints a token; `git` gets the Gitea token through `tea logins helper`.

## Browser MCP

- Server name: `playwright`. Added at user scope with `codex mcp add playwright -- npx -y @playwright/mcp@<version>`. TODO(#issue): Epic 5 pins the version.
