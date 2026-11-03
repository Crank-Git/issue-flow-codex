#!/usr/bin/env python3
"""Live end-to-end harness for the Epic 2 and Epic 3 batch gates (worker dispatch, loop operations).

Port-only, Python stdlib. The file name starts with `run_`, so `unittest discover`
skips it and CI stays offline. Every subcommand needs `ISSUE_FLOW_E2E=1`, because it
spends Codex quota and changes the test bed repository `Crank-Git/issue-flow-codex-testbed`.

    python3 tests/e2e/run_loop.py setup --work <dir>      # home, plugin, test bed reset, clone
    python3 tests/e2e/run_loop.py main  --work <dir>      # one `codex exec` PM run
    python3 tests/e2e/run_loop.py probe --work <dir> <name>

`<dir>` holds the isolated CODEX_HOME (`home/`), the test bed clone (`bed/`), and the
raw output of each run (`out/`). The operator's `~/.codex` is never changed: `auth.json`
is linked into the isolated home, not copied.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OPERATOR_AUTH = Path.home() / ".codex" / "auth.json"
BED_REPO = "Crank-Git/issue-flow-codex-testbed"
PM_MODEL = "gpt-6.1-sol"
WORKER_MODEL = "gpt-6-luna"
WAIT_MS = 60000

CONFIG = {
    "version": 1,
    "pluginVersion": "0.17.0",
    "concurrency": 2,
    "batchSize": 4,
    "runLength": {"mode": "one batch", "value": 1},
    "prGranularity": "batch",
    "prAuthority": "autonomous",
    "planReview": False,
    "reviewWipLimit": 2,
    "review": {"when": "never"},
    "deploy": {"mode": "none"},
    "docsMcp": {"offered": [], "installed": [], "marketplacesAdded": [],
                "declined": True, "restartPending": False},
    "practices": {"tdd": False, "ddd": False, "e2e": "none", "coverage": None,
                  "commitStyle": "conventional", "docs": "none"},
    "notes": "E2E gate run. Saved values only; the PM must still ask.",
}

# The Codex-only settings live in their own file with flat keys (FR-loop-operations-11, 12).
CODEX_CONFIG = {"version": 1, "pluginVersion": "0.1.0", "pmModel": PM_MODEL,
                "workerModel": WORKER_MODEL, "workerEffort": "low",
                "helperModel": WORKER_MODEL, "waitMs": WAIT_MS}

MAIN_PROMPT = """\
Run $issue-flow:issue-flow on this repository.

Work only the epic batch (the epic issue and its status:ready sub-issues). Use the integration branch model.
Take the run configuration through the normal confirmation step.
Run the whole loop for one batch: build both members, sub-merge them, open the batch PR, have a ci_watcher
watch its CI, merge the batch PR when the verdict is success, and post the digest on the status issue.
Then end your turn with a one-paragraph summary.
"""


def run(argv, *, cwd=None, env=None, check=True, timeout=None, stdin=subprocess.DEVNULL):
    done = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True,
                          timeout=timeout, stdin=stdin)
    if check and done.returncode != 0:
        raise SystemExit(f"command failed ({done.returncode}): {' '.join(map(str, argv))}\n"
                         f"{done.stdout[-800:]}\n{done.stderr[-800:]}")
    return done


def paths(work):
    work = Path(work).resolve()
    return work, work / "home", work / "bed", work / "out"


def codex_env(home):
    return dict(os.environ, CODEX_HOME=str(home))


def require_opt_in():
    if os.environ.get("ISSUE_FLOW_E2E") != "1":
        raise SystemExit("set ISSUE_FLOW_E2E=1: this harness spends quota and changes the test bed")


def build_plugin_copy(work):
    """Copy the checkout to `<work>/plugin` and set the worker role there to the cheap model.

    The setup check demands that the role files in the test bed equal the plugin's role files
    byte for byte. A copy with the cheap model keeps that check green and keeps the PM from
    passing a model override. The checkout itself is never changed.
    """
    target = work / "plugin"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns(".git", ".claude", "__pycache__"))
    role = target / "roles" / "issue-worker.toml"
    role.write_text(re.sub(r'(?m)^model = ".*"$', f'model = "{WORKER_MODEL}"', role.read_text(), count=1))
    # The marketplace add needs a git repository.
    run(["git", "init", "-q"], cwd=target)
    run(["git", "add", "-A"], cwd=target)
    run(["git", "-c", "user.name=gate", "-c", "user.email=gate@example.invalid",
         "commit", "-q", "-m", "gate plugin copy"], cwd=target)
    return target


def build_home(home, bed, plugin):
    home.mkdir(parents=True, exist_ok=True)
    link = home / "auth.json"
    if not link.exists():
        os.symlink(OPERATOR_AUTH, link)
    env = codex_env(home)
    run(["codex", "plugin", "marketplace", "add", str(plugin)], env=env)
    run(["codex", "plugin", "add", "issue-flow@issue-flow-codex"], env=env)
    # A project config loads only for a trusted project.
    with open(home / "config.toml", "a") as handle:
        handle.write(f'\n[projects."{bed}"]\ntrust_level = "trusted"\n')


def reset_bed():
    done = run([sys.executable, str(ROOT / "scripts" / "testbed-reset.py"), "--forge", "github"])
    return json.loads(done.stdout.strip().splitlines()[-1])


def issue_list():
    done = run(["gh", "issue", "list", "-R", BED_REPO, "--state", "open", "--limit", "50",
                "--json", "number,title,labels"])
    return json.loads(done.stdout)


def restore_seed_issues():
    """Give each seed issue its seed labels and body again.

    `testbed-reset.py` reopens a closed seed issue but keeps its old labels and body. A second
    run on the same repository then starts with `status:batched` labels and a stale batch
    block in the epic body. Return the epic number.
    """
    seed = json.loads((ROOT / "testbed" / "seed" / "issues.json").read_text())
    everything = json.loads(run(["gh", "issue", "list", "-R", BED_REPO, "--state", "all", "--limit", "100",
                                 "--json", "number,title,state"]).stdout)
    open_first = sorted(everything, key=lambda i: (i["state"] != "OPEN", i["number"]))
    by_title = {}
    for issue in open_first:
        by_title.setdefault(issue["title"], issue["number"])
    numbers = {item["title"]: by_title[item["title"]] for item in seed["issues"]}
    checklist = "\n".join(f"- [ ] #{number} {title}" for title, number in numbers.items())
    items = [(item, item["body"]) for item in seed["issues"]]
    items.append((seed["epic"], seed["epic"]["body"].replace("{{checklist}}", checklist)))
    for item, body in items:
        number = by_title[item["title"]]
        payload = json.dumps({"body": body, "labels": item["labels"], "state": "open"})
        subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{BED_REPO}/issues/{number}", "--input", "-"],
                       input=payload, text=True, capture_output=True, check=True)
    for issue in everything:
        if issue["state"] == "OPEN" and issue["number"] not in by_title.values():
            run(["gh", "issue", "close", str(issue["number"]), "-R", BED_REPO])
    return by_title[seed["epic"]["title"]]


def setup_bed(bed, plugin):
    run(["git", "clone", f"https://github.com/{BED_REPO}.git", str(bed)])
    # The thread count that setup writes comes from `concurrency`, so write the config first.
    config = dict(CONFIG, forge={"type": "github", "host": "github.com",
                                 "owner": "Crank-Git", "repo": "issue-flow-codex-testbed",
                                 "interface": "cli"})
    (bed / ".issue-flow.json").write_text(json.dumps(config, indent=2) + "\n")
    (bed / ".issue-flow.codex.json").write_text(json.dumps(CODEX_CONFIG, indent=2) + "\n")
    setup = plugin / "scripts" / "setup_project.py"
    plan = run([sys.executable, str(setup), "plan", "--project", str(bed), "--with-default-permissions"])
    files = re.findall(r"^\+\+\+ b/(\S+)", plan.stdout, re.M)
    run([sys.executable, str(setup), "apply", "--project", str(bed),
         "--with-default-permissions", "--accept", *files])
    return files


def cmd_setup(args):
    work, home, bed, out = paths(args.work)
    out.mkdir(parents=True, exist_ok=True)
    state = reset_bed()
    restore_seed_issues()
    plugin = build_plugin_copy(work)
    build_home(home, bed, plugin)
    files = setup_bed(bed, plugin)
    issues = issue_list()
    epic = next(i["number"] for i in issues
                if any(label["name"] == "type:epic" for label in i["labels"]))
    subs = sorted(i["number"] for i in issues if i["number"] != epic)
    # Two members only: label the last three sub-issues status:blocked.
    for number in subs[2:]:
        run(["gh", "issue", "edit", str(number), "-R", BED_REPO,
             "--remove-label", "status:ready", "--add-label", "status:blocked"])
    info = {"epic": epic, "members": subs[:2], "blocked": subs[2:], "setup_files": files,
            "reset": state}
    (work / "state.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info))


def exec_codex(work, prompt, name, model=PM_MODEL, timeout=3300, trust_hooks=True,
               extra=(), resume=None):
    """Run `codex exec` (or `codex exec resume <session>`) with stdin closed. Return the session id.

    `trust_hooks=False` omits --dangerously-bypass-hook-trust (probe M1). `extra` holds
    `-c key=value` overrides, for example a low `model_auto_compact_token_limit`.
    """
    work, home, bed, out = paths(work)
    argv = ["codex", "exec"]
    if resume:
        argv.append("resume")
    argv += ["-m", model, "--json"]
    if trust_hooks:
        argv.append("--dangerously-bypass-hook-trust")
    argv += ["-c", 'approval_policy="never"']
    for item in extra:
        argv += ["-c", item]
    if not resume:
        argv += ["-C", str(bed)]
    argv += [resume, prompt] if resume else [prompt]
    cwd = bed if resume else None
    session = resume
    # A resumed turn that the service refused ("at capacity") changed nothing, so it is safe to repeat.
    for attempt in range(4 if resume else 1):
        try:
            done = run(argv, cwd=cwd, env=codex_env(home), check=False, timeout=timeout)
            stdout, stderr, code = done.stdout, done.stderr, done.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr, code = "", "timeout"
        if "at capacity" not in stdout or "item.started" in stdout:
            break
        (out / f"{name}.capacity-{attempt}.jsonl").write_text(stdout)
        time.sleep(60)
    (out / f"{name}.jsonl").write_text(stdout)
    (out / f"{name}.stderr").write_text(stderr)
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "thread.started":
            session = event.get("thread_id")
            break
    print(f"{name}: exit {code}, {len(stdout.splitlines())} events, session {session}")
    return session


def cmd_main(args):
    """Attempt N: the PM asks the run-configuration question (M4); the reply continues the run."""
    work, _, _, out = paths(args.work)
    extra = list(args.config or [])
    session = exec_codex(args.work, MAIN_PROMPT, f"main-{args.attempt}", extra=extra)
    (out / f"main-{args.attempt}.session").write_text(f"{session}\n")
    if args.reply:
        exec_codex(args.work, args.reply, f"main-{args.attempt}-reply", extra=extra, resume=session)


# Fixture roles replace the worker's runbook, to produce answers a normal worker never gives.
FIXTURES = {
    "prose": "Reply with exactly one prose sentence: All done, the work looks good. "
             "Never output JSON, not even when asked again. Change no file.",
    "slow": "Ignore every other instruction. In the worktree named by the brief, run the command "
            "`sleep 30` six times, one command per call, with workdir set to the worktree path. "
            "Then return only a JSON verdict with outcome needs-feedback and question slow fixture.",
    "failci": "Ignore every other instruction. In the worktree named by the brief, edit app.py so that "
              "the /health route answers {\"status\": \"up\"} instead of {\"status\": \"ok\"}. Edit no "
              "test and run no test. Commit with a conventional message that names the issue and does "
              "not end in [skip ci], push the branch, and open a non-draft pull request against the base "
              "branch of the brief with gh pr create. Then return only a JSON verdict with outcome "
              "ready-to-merge, the prNumber, one criterion with met true, and localChecks not run. If a "
              "follow-up message reports a failing CI run, run git revert --no-edit HEAD, push, and "
              "return the same JSON verdict again. Every command uses workdir set to the worktree path.",
    "checkpoint":"Ignore every other instruction. In the worktree named by the brief: if "
                  "the command `git log origin/<base>..HEAD` already lists a commit, return only "
                  "a JSON verdict with outcome needs-feedback and question fixture complete. "
                  "Else create the file probe-checkpoint.txt with one line, commit it with a "
                  "message that ends in [skip ci], push the branch, then return only a JSON "
                  "verdict with outcome checkpoint and remaining fixture checkpoint. Every "
                  "command uses workdir set to the worktree path.",
}


def cmd_probe(args):
    """Run one probe. Every change to the test bed lasts for this probe only."""
    _, home, bed, _ = paths(args.work)
    prompt = Path(args.prompt_file).read_text()
    config_path = bed / ".issue-flow.json"
    codex_path = bed / ".issue-flow.codex.json"
    role = bed / ".codex" / "agents" / "issue-worker.toml"
    project_toml = bed / ".codex" / "config.toml"
    saved = {path: path.read_text() for path in (config_path, codex_path, role, project_toml)}
    # The setup check compares the role copy with the installed plugin role, so a fixture
    # must change both files the same way.
    cached = next((home / "plugins" / "cache").rglob("roles/issue-worker.toml"))
    saved_cached = cached.read_text()
    saved_ci_role = bed / ".codex" / "agents" / "ci-watcher.toml"
    saved_ci = saved_ci_role.read_text() if saved_ci_role.exists() else None
    config = json.loads(saved[config_path])
    codex = json.loads(saved[codex_path])
    if args.concurrency:
        config["concurrency"] = args.concurrency
    if args.wait_ms:
        codex["waitMs"] = args.wait_ms
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    codex_path.write_text(json.dumps(codex, indent=2) + "\n")
    if args.fixture != "none":
        body = f"developer_instructions = '''\n{FIXTURES[args.fixture]}\n'''"
        fixture_text = re.sub(r"(?s)developer_instructions = '''.*?'''", lambda _: body,
                              saved[role], count=1)
        role.write_text(fixture_text)
        cached.write_text(fixture_text)
    if args.drop_role:
        role.unlink()
    try:
        session = exec_codex(args.work, prompt, f"probe-{args.name}", model=args.model,
                             timeout=args.timeout, trust_hooks=not args.untrusted,
                             extra=list(args.config or []))
        if args.reply:
            exec_codex(args.work, args.reply, f"probe-{args.name}-reply", model=args.model,
                       timeout=args.timeout, trust_hooks=not args.untrusted,
                       extra=list(args.config or []), resume=session)
    finally:
        for path, text in saved.items():
            path.write_text(text)
        cached.write_text(saved_cached)
        if saved_ci is not None:
            saved_ci_role.write_text(saved_ci)


UPSTREAM_CLONE = Path.home() / "Development" / "Personal" / "claude-plugins"
UPSTREAM_TAG = "issue-flow--v0.17.0"


def cmd_upstream(args):
    """M9: run the upstream 0.17.0 `preflight.py` against a clone of the test bed.

    The hook reads labels, pull requests, and the status issue that the Codex PM wrote.
    It must exit 0 and print its digest. The upstream clone is read only (`git show`).
    """
    work, _, _, out = paths(args.work)
    script = run(["git", "show", f"{UPSTREAM_TAG}:issue-flow/hooks/preflight.py"], cwd=UPSTREAM_CLONE).stdout
    target = work / "upstream-bed"
    if target.exists():
        shutil.rmtree(target)
    run(["git", "clone", "-q", "-b", args.branch, f"https://github.com/{BED_REPO}.git", str(target)])
    hook = work / "upstream_preflight.py"
    hook.write_text(script)
    payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup", "cwd": str(target)})
    done = subprocess.run([sys.executable, str(hook)], input=payload, text=True, capture_output=True,
                          cwd=target, timeout=120)
    (out / "upstream-preflight.txt").write_text(done.stdout)
    print(f"exit {done.returncode}")
    print(done.stdout)
    print("stderr:", done.stderr[-500:])
    print("config files in the clone:", sorted(f.name for f in target.glob(".issue-flow*")))


def cmd_show(args):
    """Print the commands and messages of one `--json` run, one line each."""
    _, _, _, out = paths(args.work)
    for name in args.names:
        print(f"===== {name}")
        for line in (out / f"{name}.jsonl").read_text().splitlines():
            event = json.loads(line)
            item = event.get("item", {})
            if item.get("type") == "command_execution" and event["type"] == "item.completed":
                print("CMD", item["command"][:args.width], "->", item["exit_code"],
                      item["aggregated_output"][:args.width].replace("\n", " | "))
            elif item.get("type") == "agent_message":
                print("MSG", item["text"][:args.width * 4].replace("\n", " "))
            elif event["type"] in ("error", "turn.failed"):
                print("ERR", json.dumps(event)[:args.width])


def cmd_sleeper(args):
    """M7: push a branch whose CI run stays pending for `--seconds`, and print its head SHA.

    The branch changes only the workflow file, on a branch of the test bed. Cancel the run
    afterward with `gh run cancel`.
    """
    work, _, _, _ = paths(args.work)
    target = work / "sleeper"
    if target.exists():
        shutil.rmtree(target)
    run(["git", "clone", "-q", "-b", "dev", f"https://github.com/{BED_REPO}.git", str(target)])
    workflow = target / ".github" / "workflows" / "ci.yml"
    workflow.write_text(workflow.read_text().rstrip("\n") + f"\n      - run: sleep {args.seconds}\n")
    run(["git", "checkout", "-q", "-b", args.branch], cwd=target)
    run(["git", "-c", "user.name=gate", "-c", "user.email=gate@example.invalid",
         "commit", "-q", "-am", "test: keep the CI run pending"], cwd=target)
    run(["git", "push", "-q", "origin", args.branch], cwd=target)
    print(run(["git", "rev-parse", "HEAD"], cwd=target).stdout.strip())


def cmd_resume(args):
    """Send one more reply to a session that waits for the operator (`codex exec resume`)."""
    exec_codex(args.work, args.text, args.name, model=args.model, timeout=args.timeout,
               extra=list(args.config or []), resume=args.session)


def cmd_timeline(args):
    """Print every tool call of every session under the isolated home, oldest first."""
    _, home, _, _ = paths(args.work)
    for rollout in sorted((home / "sessions").rglob("*.jsonl")):
        events = [json.loads(line) for line in rollout.read_text().splitlines() if line.strip()]
        meta = events[0]["payload"]
        print(f"===== {rollout.name} source={json.dumps(meta.get('source'))[:160]}"
              f" role={meta.get('agent_role')} model={meta.get('model')} cwd={meta.get('cwd')}")
        for event in events:
            payload = event["payload"]
            if event["type"] == "response_item" and payload.get("type") == "function_call":
                print(f"{event['timestamp'][11:19]} {payload['name']} "
                      f"{payload.get('arguments', '')[:args.width]}".replace("\n", " "))
            elif event["type"] == "response_item" and payload.get("type") == "custom_tool_call":
                print(f"{event['timestamp'][11:19]} {payload['name']} "
                      f"{str(payload.get('input', ''))[:args.width]}".replace("\n", " "))
            elif event["type"] == "turn_context":
                print(f"{event['timestamp'][11:19]} TURN model={payload.get('model')} cwd={payload.get('cwd')}")
            elif event["type"] == "event_msg" and payload.get("type") == "task_complete":
                print(f"{event['timestamp'][11:19]} TASK-COMPLETE "
                      f"{str(payload.get('last_agent_message'))[:args.width * 4]}".replace("\n", " "))
            elif event["type"] == "response_item" and payload.get("type") == "message" \
                    and payload.get("role") == "user" and args.messages:
                text = json.dumps(payload.get("content"))[:args.width]
                print(f"{event['timestamp'][11:19]} USER-MSG {text}")


def main():
    require_opt_in()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("setup", "main", "probe", "timeline", "upstream", "show", "sleeper", "resume"):
        p = sub.add_parser(name)
        p.add_argument("--work", required=True)
    sub.choices["upstream"].add_argument("--branch", default="dev")
    sub.choices["sleeper"].add_argument("--seconds", type=int, default=420)
    sub.choices["sleeper"].add_argument("--branch", default="probe/m7-pending")
    sub.choices["resume"].add_argument("session")
    sub.choices["resume"].add_argument("name")
    sub.choices["resume"].add_argument("--text", default="ok")
    sub.choices["resume"].add_argument("--model", default=WORKER_MODEL)
    sub.choices["resume"].add_argument("--timeout", type=int, default=2400)
    sub.choices["resume"].add_argument("--config", action="append")
    sub.choices["show"].add_argument("names", nargs="+")
    sub.choices["show"].add_argument("--width", type=int, default=200)
    sub.choices["main"].add_argument("--attempt", type=int, default=1)
    sub.choices["main"].add_argument("--reply", help="text for `codex exec resume` after the first turn")
    sub.choices["main"].add_argument("--config", action="append", help="extra `-c key=value`, repeatable")
    sub.choices["probe"].add_argument("name")
    sub.choices["probe"].add_argument("--prompt-file", required=True)
    sub.choices["probe"].add_argument("--model", default=WORKER_MODEL)
    sub.choices["probe"].add_argument("--timeout", type=int, default=900)
    sub.choices["probe"].add_argument("--fixture", choices=["none", *FIXTURES], default="none")
    sub.choices["probe"].add_argument("--concurrency", type=int)
    sub.choices["probe"].add_argument("--wait-ms", type=int)
    sub.choices["probe"].add_argument("--untrusted", action="store_true",
                                      help="omit --dangerously-bypass-hook-trust (probe M1)")
    sub.choices["probe"].add_argument("--drop-role", action="store_true",
                                      help="delete issue-worker.toml from the test bed (probe M2)")
    sub.choices["probe"].add_argument("--reply")
    sub.choices["probe"].add_argument("--config", action="append")
    sub.choices["timeline"].add_argument("--width", type=int, default=240)
    sub.choices["timeline"].add_argument("--messages", action="store_true")
    args = parser.parse_args()
    {"setup": cmd_setup, "main": cmd_main, "probe": cmd_probe,
     "timeline": cmd_timeline, "upstream": cmd_upstream, "show": cmd_show, "sleeper": cmd_sleeper, "resume": cmd_resume}[args.command](args)


if __name__ == "__main__":
    main()
