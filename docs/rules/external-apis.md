# External APIs — read the docs, never assume

Before you write anything that depends on a tool below, confirm the command, the
field, or the behavior from the source in the table. Cite the evidence in the PR body.
`docs/specs/pages/codex-harness.md` holds the Codex facts that a live run already
confirmed. A Codex claim that is not on that page needs new evidence.

| Tool | Version pinned | Authoritative source, in order |
|---|---|---|
| Codex CLI | 0.166.0 or later | 1. `codex <cmd> --help`. 2. A live `codex exec` run in an isolated `CODEX_HOME`. 3. Source at https://github.com/openai/codex. 4. https://learn.chatgpt.com/docs/ |
| GitHub CLI | the installed `gh` | `gh <cmd> --help`, then https://cli.github.com/manual/ |
| Gitea CLI | the installed `tea` | `tea <cmd> --help`, then the Gitea API docs at the server version |
| GitHub Actions | current | https://docs.github.com/en/actions |
| Upstream issue-flow | the tag in `upstream.lock` | The upstream file at that tag |

Rules:

- Codex changes between releases. When `--help`, the source, and the docs disagree, a live run decides. Record the run in the PR.
- Never copy, print, or commit `~/.codex/auth.json` or a forge token. Link `auth.json` into an isolated `CODEX_HOME`; never copy it.
- Never change the operator's `~/.codex/config.toml`. Live tests use an isolated `CODEX_HOME`.
- Anything that creates, deletes, or changes a remote repository, issue, or release outside the test beds needs the maintainer's approval first.
- A live Codex run uses the operator's quota. Ask before you run one.
