#!/usr/bin/env python3
"""Run the live Codex conformance probes P1 to P12 and write conformance-report.md.

Each probe runs `codex exec` in a new temporary CODEX_HOME. The operator's
auth.json is linked into that home, never copied. The run uses the operator's
Codex quota, so run it only on request.

Exit codes: 0 when every probe passes, 1 when a probe fails or the operator's
config.toml changed, 2 when codex is missing or not logged in.
"""

import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "conformance"
REPORT = ROOT / "conformance-report.md"
OPERATOR_HOME = Path.home() / ".codex"

PLUGIN = "issue-flow-probe"
MARKETPLACE = "issue-flow-probe-market"
MODEL = "gpt-6-luna"
TIMEOUT = 420

# The profile from docs/specs/pages/codex-harness.md, fact 8. default_permissions
# must come before the first table header (fact 12).
PROFILE = """default_permissions = "issue_flow"

[permissions.issue_flow]
extends = ":workspace"

[permissions.issue_flow.filesystem.":workspace_roots"]
"." = "write"
".git" = "write"

[permissions.issue_flow.network]
enabled = true
"""

SPAWN = 'spawn_agent with agent_type "{role}" and fork_turns "none"'


class ProbeTimeout(Exception):
    def __init__(self, seconds):
        super().__init__(f"timeout after {seconds} s")
        self.seconds = seconds


class ProbeError(Exception):
    """A probe could not run. The message is the report evidence."""


def format_line(probe_id, passed, evidence):
    evidence = " ".join(evidence.split())
    return f"{probe_id}  {'pass' if passed else 'fail'}  {evidence}"


def run_probe(probe_id, probe):
    """Run one probe function. Return (id, passed, evidence)."""
    try:
        passed, evidence = probe()
    except ProbeTimeout as exc:
        return probe_id, False, f"timeout after {exc.seconds} s"
    except ProbeError as exc:
        return probe_id, False, str(exc)
    return probe_id, passed, evidence


def link_auth(home, source):
    os.symlink(source, Path(home) / "auth.json")


def read_hook_log(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class Env:
    def __init__(self, home, workdir, log, token):
        self.home = home
        self.workdir = workdir
        self.log = log
        self.token = token

    def run(self, argv, deny_role=None, timeout=TIMEOUT):
        env = dict(
            os.environ,
            CODEX_HOME=str(self.home),
            PROBE_LOG=str(self.log),
            PROBE_TOKEN=self.token,
        )
        if deny_role:
            env["PROBE_DENY_ROLE"] = deny_role
        try:
            return subprocess.run(
                argv, cwd=self.workdir, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise ProbeTimeout(timeout) from None

    def exec(self, prompt, *, sandbox="workspace-write", bypass_hooks=True, deny_role=None):
        """Run one `codex exec` session. Return (last message, events)."""
        out = self.home / "last-message.txt"
        argv = [
            "codex", "exec", "-m", MODEL, "-c", 'approval_policy="never"',
            "--json", "-o", str(out), "-C", str(self.workdir),
        ]
        if sandbox:
            argv += ["-s", sandbox]
        if bypass_hooks:
            argv.append("--dangerously-bypass-hook-trust")
        done = self.run(argv + [prompt], deny_role=deny_role)
        if done.returncode != 0:
            raise ProbeError(f"codex exec exited {done.returncode}: {done.stderr.strip()[-200:]}")
        events = []
        for line in done.stdout.splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                events.append(json.loads(line))
        message = out.read_text() if out.exists() else ""
        return message, events

    def hooks(self):
        return read_hook_log(self.log)

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git", *args], cwd=cwd or self.workdir, capture_output=True, text=True,
        )


@contextlib.contextmanager
def probe_env(profile=False):
    """Make a new CODEX_HOME with the probe plugin installed, and a git work directory."""
    with tempfile.TemporaryDirectory(prefix="conformance-") as tmp:
        tmp = Path(tmp)
        home = tmp / "home"
        home.mkdir()
        link_auth(home, OPERATOR_HOME / "auth.json")
        if profile:
            (home / "config.toml").write_text(PROFILE)
        market = tmp / "market"
        shutil.copytree(FIXTURES, market, ignore=shutil.ignore_patterns("roles"))
        workdir = tmp / "work"
        agents = workdir / ".codex" / "agents"
        agents.mkdir(parents=True)
        for role in (FIXTURES / "roles").glob("*.toml"):
            shutil.copy(role, agents / role.name)
        env = Env(home, workdir, tmp / "hooks.jsonl", secrets.token_hex(6))
        for args in (
            ["git", "init", "-q"],
            ["git", "config", "user.name", "probe"],
            ["git", "config", "user.email", "probe@example.invalid"],
            ["git", "commit", "-q", "--allow-empty", "-m", "init"],
        ):
            subprocess.run(args, cwd=workdir, check=True, capture_output=True)
        for args in (
            ["codex", "plugin", "marketplace", "add", str(market)],
            ["codex", "plugin", "add", f"{PLUGIN}@{MARKETPLACE}"],
        ):
            done = env.run(args, timeout=120)
            if done.returncode != 0:
                raise ProbeError(f"{' '.join(args[:4])} exited {done.returncode}: {done.stderr.strip()[-200:]}")
        yield env


def commands(events):
    """Return (command, exit code) for each command the root session finished."""
    found = []
    for event in events:
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "command_execution":
            found.append((item.get("command", ""), item.get("exit_code")))
    return found


def hook_events(env, event, tool_suffix):
    return [
        h for h in env.hooks()
        if h.get("hook_event_name") == event and str(h.get("tool_name", "")).endswith(tool_suffix)
    ]


def json_objects(text):
    decoder = json.JSONDecoder()
    found = []
    for match in re.finditer(r"\{", text):
        with contextlib.suppress(json.JSONDecodeError):
            found.append(decoder.raw_decode(text[match.start():])[0])
    return found


def p1():
    with probe_env() as env:
        message, _ = env.exec(
            "List the skills you can use whose name ends in ':ping'. Reply with the exact skill names and nothing else."
        )
        name = f"{PLUGIN}:ping"
        return name in message, f"model listed {name}" if name in message else f"reply was {message.strip()!r}"


def p2():
    with probe_env() as env:
        message, _ = env.exec("Your context holds a line that starts with PROBE_TOKEN=. Reply with the value after the equals sign and nothing else.")
        ok = env.token in message
        return ok, "SessionStart additionalContext reached the model" if ok else f"reply was {message.strip()!r}"


def p3():
    with probe_env() as env:
        env.exec("Reply with the word ready.", bypass_hooks=False)
        count = len(env.hooks())
        return count == 0, f"hook log holds {count} entries without --dangerously-bypass-hook-trust"


def spawn_two_prompt():
    return (
        f"Use {SPAWN.format(role='echo_worker')} twice. Give subagent one the task: reply with only "
        '{"worker": 1}. Give subagent two the task: reply with only {"worker": 2}. '
        "Wait for both with wait_agent. Then print both JSON verdicts and nothing else."
    )


def p4():
    with probe_env() as env:
        message, _ = env.exec(spawn_two_prompt())
        workers = {o.get("worker") for o in json_objects(message) if isinstance(o, dict)}
        return {1, 2} <= workers, f"final message held workers {sorted(w for w in workers if w)}"


def p5():
    with probe_env() as env:
        env.exec(spawn_two_prompt())
        spawns = hook_events(env, "PreToolUse", "spawn_agent")
        roles = [s.get("tool_input", {}).get("agent_type") for s in spawns]
        names = {s.get("tool_name") for s in spawns}
        ok = bool(spawns) and set(roles) == {"echo_worker"} and all(re.search("spawn_agent$", n) for n in names)
        return ok, f"tool_name {sorted(names)}, agent_type {roles}"


def p6():
    with probe_env() as env:
        message, _ = env.exec(
            f"Use {SPAWN.format(role='echo_worker')} with the task: run the shell command `echo started`. "
            "If the spawn is refused, reply with the exact refusal reason and nothing else. "
            "Do not do the task yourself. Otherwise wait for the subagent.",
            deny_role="echo_worker",
        )
        reason = f"DENIED-{env.token}"
        started = [h for h in env.hooks() if h.get("agent_type") == "echo_worker"]
        return reason in message and not started, f"deny reason in reply: {reason in message}; subagent hook entries: {len(started)}"


WORKTREE = "git worktree add .worktrees/t1 -b t1"


def p7():
    with probe_env() as env:
        message, _ = env.exec(f"Run `{WORKTREE}` and reply with its exit code and error text.")
        branch = env.git("branch", "--list", "t1").stdout.strip()
        denied = "Operation not permitted" in message
        return denied and not branch, f"error text holds 'Operation not permitted': {denied}; branch t1 exists: {bool(branch)}"


def p8():
    with probe_env(profile=True) as env:
        _, events = env.exec(
            f"Run these three commands in order and reply with the exit code of each: `{WORKTREE}`, "
            "`git -C .worktrees/t1 commit --allow-empty -m probe`, "
            "`git ls-remote https://github.com/openai/codex HEAD`.",
            sandbox=None,
        )
        wanted = ("worktree add", "commit --allow-empty", "ls-remote")
        codes = {w: [c for cmd, c in commands(events) if w in cmd] for w in wanted}
        ok = all(codes[w] and all(c == 0 for c in codes[w]) for w in wanted)
        return ok, f"exit codes {codes}"


def p9():
    with probe_env(profile=True) as env:
        env.exec(
            f"Use {SPAWN.format(role='git_worker')} with the task: run `git worktree add .worktrees/t2 -b t2`, "
            "then run `git -C .worktrees/t2 commit --allow-empty -m probe-commit`. Wait for the subagent, then reply done.",
            sandbox=None,
        )
        subject = env.git("log", "-1", "--format=%s", "t2").stdout.strip()
        return subject == "probe-commit", f"commit subject on branch t2: {subject!r}"


def p10():
    with probe_env(profile=True) as env:
        env.exec(
            f"Use {SPAWN.format(role='git_worker')} with the task: run `git status --short`. "
            "Wait for the subagent, then reply done.",
            sandbox=None,
        )
        inner = [
            h for h in env.hooks()
            if h.get("hook_event_name") == "PreToolUse" and h.get("agent_type") == "git_worker"
        ]
        ids = {h.get("agent_id") for h in inner}
        return bool(inner) and None not in ids, f"{len(inner)} PreToolUse entries with agent_type git_worker, agent ids {sorted(map(str, ids))}"


WAIT_MS = 120000


def p11():
    with probe_env() as env:
        env.exec(
            f"Use {SPAWN.format(role='echo_worker')} with the task: reply with only {{\"ok\": 1}}. "
            f"Then call wait_agent once with timeout_ms {WAIT_MS}. Then reply done."
        )
        before = hook_events(env, "PreToolUse", "wait_agent")
        after = hook_events(env, "PostToolUse", "wait_agent")
        if not before or not after:
            return False, f"hook log holds {len(before)} PreToolUse and {len(after)} PostToolUse wait_agent entries"
        elapsed = after[0]["probe_ts"] - before[0]["probe_ts"]
        return elapsed < WAIT_MS / 1000, f"wait_agent returned after {elapsed:.1f} s of {WAIT_MS // 1000} s"


def p12():
    with probe_env() as env:
        message, _ = env.exec(
            f"Use {SPAWN.format(role='echo_worker')} with the task: reply with only {{\"turn\": 1}}. "
            "Wait for it with wait_agent. Then call followup_task on the same subagent with the task: "
            'reply with only {"turn": 2}. Wait again. Then print both JSON verdicts and nothing else.'
        )
        turns = {o.get("turn") for o in json_objects(message) if isinstance(o, dict)}
        followups = hook_events(env, "PreToolUse", "followup_task")
        return {1, 2} <= turns and bool(followups), f"verdict turns {sorted(t for t in turns if t)}, followup_task calls {len(followups)}"


PROBES = {f"P{i}": fn for i, fn in enumerate((p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12), 1)}


def check_codex():
    """Return the codex version line, or raise ProbeError when codex cannot run."""
    if shutil.which("codex") is None:
        raise ProbeError("codex is not on PATH")
    status = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
    if status.returncode != 0:
        raise ProbeError("codex is not logged in")
    return subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--probe", action="append", choices=list(PROBES), help="run only this probe (repeatable)")
    args = parser.parse_args(argv)
    try:
        version = check_codex()
    except ProbeError as exc:
        print(f"conformance: {exc}", file=sys.stderr)
        return 2
    config = OPERATOR_HOME / "config.toml"
    before = config.read_bytes() if config.exists() else None
    lines = [version]
    failed = False
    for probe_id in args.probe or PROBES:
        result = run_probe(probe_id, PROBES[probe_id])
        failed = failed or not result[1]
        lines.append(format_line(*result))
        print(lines[-1], flush=True)
    REPORT.write_text("\n".join(lines) + "\n")
    after = config.read_bytes() if config.exists() else None
    if before != after:
        print("conformance: ~/.codex/config.toml changed during the run", file=sys.stderr)
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
