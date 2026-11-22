#!/usr/bin/env python3
"""A fake `codex` for the tests of scripts/run_evals.py. It makes no model call.

The runner passes no host variable to codex, so the test gives the fake its settings as
options before `exec`: --mode, --patch, --verdict and --record. The fake records what the
runner gave it in --record, then acts as a dispatcher and a worker. --mode picks the behavior:

    worker-pass   apply --patch in the worktree, commit, push, write --verdict
    no-verdict    change nothing and write no verdict
    denied        like no-verdict, and a tool output of the worker shows a refused command
    denied-pass   like worker-pass, with the same refused command in a tool output
    quoted        like no-verdict, and the worker only quotes the refusal text in a message
    replace-auth  like no-verdict, and replace the auth.json link with a file (a token refresh)
    crash         exit 3 with no output
    crash-late    print an event, write "boom" to stderr, and exit 4
    hang          sleep until the runner kills it
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

TOKENS = {"root": (100, 10), "worker": (900, 90)}
DENIAL = "sandbox-exec: sandbox_apply: Operation not permitted\n"
TOOL_OUTPUT = {"timestamp": "2026-11-22T10:00:03.000Z", "type": "response_item",
               "payload": {"type": "function_call_output", "call_id": "c1", "output": DENIAL}}
QUOTED = {"timestamp": "2026-11-22T10:00:03.000Z", "type": "response_item",
          "payload": {"type": "message", "role": "assistant",
                      "content": [{"type": "output_text", "text": "the docs show: " + DENIAL}]}}


def write_rollout(home, name, role, input_tokens, output_tokens, extra=""):
    folder = Path(home) / "sessions" / "2026" / "11" / "22"
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"id": name, "session_id": "root", "cwd": "/x"}
    if role != "root":
        meta.update(parent_thread_id="root", agent_role=role)
    lines = [
        {"timestamp": "2026-11-22T10:00:00.000Z", "type": "session_meta", "payload": meta},
        {"timestamp": "2026-11-22T10:00:01.000Z", "type": "turn_context", "payload": {"model": "gpt-test"}},
        {"timestamp": "2026-11-22T10:00:02.000Z", "type": "event_msg", "payload": {
            "type": "token_count",
            "info": {"total_token_usage": {"input_tokens": input_tokens, "cached_input_tokens": 0,
                                           "output_tokens": output_tokens, "reasoning_output_tokens": 0}},
            "rate_limits": {"primary": {"used_percent": 1.0, "window_minutes": 10080, "resets_at": 1795000000}}}},
    ]
    text = "\n".join(json.dumps(line) for line in lines) + "\n" + extra
    (folder / f"rollout-{name}.jsonl").write_text(text)


def option(argv, flag):
    return argv[argv.index(flag) + 1]


def git(cwd, *args):
    subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True)


def main(argv):
    split = argv.index("exec")
    settings = dict(zip((flag.lstrip("-") for flag in argv[:split:2]), argv[1:split:2]))
    argv = argv[split:]
    mode = settings["mode"]
    home = Path(os.environ["CODEX_HOME"])
    repo = Path(option(argv, "-C"))
    last = option(argv, "-o")
    hidden = [str(p) for pattern in ("hidden_test*.py", "reference.patch") for p in repo.parent.rglob(pattern)]
    plugin = Path(next(line.split(None, 1)[1] for line in argv[-1].splitlines() if line.startswith("pluginRoot:")))
    Path(settings["record"]).write_text(json.dumps({
        "argv": argv,
        "path_first": os.environ["PATH"].split(os.pathsep)[0],
        "auth_is_link": (home / "auth.json").is_symlink(),
        "auth_target": os.readlink(home / "auth.json"),
        "agents": sorted(p.name for p in (home / "agents").glob("*.toml")),
        "worker_role": (home / "agents" / "issue-worker.toml").read_text(),
        "checker_role": (home / "agents" / "criteria-checker.toml").read_text(),
        "config": (home / "config.toml").read_text(),
        "stdin_is_devnull": os.fstat(0).st_rdev == os.stat(os.devnull).st_rdev,
        "hidden_during_run": hidden,
        "sandbox": str(repo.parent),
        "plugin_has": {"roles": (plugin / "roles").is_dir(), "evals": (plugin / "evals").exists(),
                       "git": (plugin / ".git").exists()},
        "gh_on_path": subprocess.run(["which", "gh"], capture_output=True, text=True).stdout.strip(),
    }))
    if mode == "crash":
        sys.exit(3)
    if mode == "replace-auth":
        (home / "auth.json").unlink()
        (home / "auth.json").write_text('{"token": "refreshed"}')
    if mode == "hang":
        time.sleep(60)
    write_rollout(home, "root", "root", *TOKENS["root"])
    extra = {"denied": TOOL_OUTPUT, "denied-pass": TOOL_OUTPUT, "quoted": QUOTED}.get(mode)
    write_rollout(home, "worker", "issue_worker", *TOKENS["worker"],
                  extra=json.dumps(extra) + "\n" if extra else "")
    if mode in ("worker-pass", "denied-pass"):
        worktree = next((repo / ".worktrees").iterdir())
        git(worktree, "apply", settings["patch"])
        git(worktree, "add", "-A")
        git(worktree, "commit", "-q", "-m", "fix")
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=worktree,
                                capture_output=True, text=True).stdout.strip()
        git(worktree, "push", "-q", "origin", branch)
        (repo / ".eval" / "verdict.json").write_text(Path(settings["verdict"]).read_text())
    Path(last).write_text("final words of the dispatcher\n")
    print(json.dumps({"type": "thread.started", "thread_id": "root"}), flush=True)
    if mode == "crash-late":
        print("boom", file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main(sys.argv[1:])
