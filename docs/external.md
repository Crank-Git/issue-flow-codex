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

- GitHub test bed: repository name in `ISSUE_FLOW_TESTBED_GITHUB`. TODO(#issue): Epic 0 creates it.
- Gitea test bed: repository name in `ISSUE_FLOW_TESTBED_GITEA`, server in `GITEA_SERVER_URL`. TODO(#issue): Epic 0 creates it.
- Tokens: the `gh` and `tea` credential stores on the operator's machine.

## Browser MCP

- Server name: `playwright`. Added at user scope with `codex mcp add playwright -- npx -y @playwright/mcp@<version>`. TODO(#issue): Epic 5 pins the version.
