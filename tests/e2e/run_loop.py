#!/usr/bin/env python3
"""Live end-to-end harness for the Epic 2 batch gate (worker dispatch).

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
import subprocess
import sys
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
    "codex": {"waitMs": WAIT_MS},
    "notes": "E2E gate run. Operator confirmed this configuration; ask no questions.",
}

MAIN_PROMPT = """\
Run $issue-flow:issue-flow on this repository.

The saved run configuration in .issue-flow.json is confirmed by the operator. Ask no question about it.
Work only the epic batch (the epic issue and its status:ready sub-issues). Use the integration branch model.
Stop after BOTH members are sub-merged into the integration branch. Do NOT open the batch PR: the CI watcher is not ported yet. Do not start a second batch.
Rework test: for the FIRST verdict you read, send exactly one rework request to that worker with followup_task (ask it to add one more line to its PR description or one more commit comment-free tweak that proves it read the request), and gate again after its second verdict. Send no rework for the second member.
When both members are sub-merged and their worktrees are removed, end your turn with a one-paragraph summary.
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


def build_home(home, bed):
    home.mkdir(parents=True, exist_ok=True)
    link = home / "auth.json"
    if not link.exists():
        os.symlink(OPERATOR_AUTH, link)
    env = codex_env(home)
    run(["codex", "plugin", "marketplace", "add", str(ROOT)], env=env)
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


def setup_bed(bed):
    run(["git", "clone", f"https://github.com/{BED_REPO}.git", str(bed)])
    plan = run([sys.executable, str(ROOT / "scripts" / "setup_project.py"), "plan",
                "--project", str(bed), "--with-default-permissions"])
    files = re.findall(r"^\+\+\+ b/(\S+)", plan.stdout, re.M)
    run([sys.executable, str(ROOT / "scripts" / "setup_project.py"), "apply", "--project", str(bed),
         "--with-default-permissions", "--accept", *files])
    role = bed / ".codex" / "agents" / "issue-worker.toml"
    text = role.read_text()
    role.write_text(re.sub(r'(?m)^model = ".*"$', f'model = "{WORKER_MODEL}"', text, count=1))
    config = dict(CONFIG, forge={"type": "github", "host": "github.com",
                                 "owner": "Crank-Git", "repo": "issue-flow-codex-testbed",
                                 "interface": "cli"})
    (bed / ".issue-flow.json").write_text(json.dumps(config, indent=2) + "\n")
    return files


def cmd_setup(args):
    work, home, bed, out = paths(args.work)
    out.mkdir(parents=True, exist_ok=True)
    state = reset_bed()
    build_home(home, bed)
    files = setup_bed(bed)
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


def exec_codex(work, prompt, name, model=PM_MODEL, timeout=3300):
    work, home, bed, out = paths(work)
    argv = ["codex", "exec", "-m", model, "--json", "--dangerously-bypass-hook-trust",
            "-c", 'approval_policy="never"', "-C", str(bed), prompt]
    try:
        done = run(argv, env=codex_env(home), check=False, timeout=timeout)
        (out / f"{name}.jsonl").write_text(done.stdout)
        (out / f"{name}.stderr").write_text(done.stderr)
        print(f"{name}: exit {done.returncode}, {len(done.stdout.splitlines())} events")
    except subprocess.TimeoutExpired as exc:
        (out / f"{name}.jsonl").write_text((exc.stdout or b"").decode() if isinstance(exc.stdout, bytes)
                                           else (exc.stdout or ""))
        print(f"{name}: timeout after {timeout} s")


def cmd_main(args):
    exec_codex(args.work, MAIN_PROMPT, f"main-{args.attempt}")


# Fixture roles replace the worker's runbook, to produce answers a normal worker never gives.
FIXTURES = {
    "prose": "Reply with exactly one prose sentence: All done, the work looks good. "
             "Never output JSON, not even when asked again. Change no file.",
    "slow": "Ignore every other instruction. In the worktree named by the brief, run the command "
            "`sleep 30` six times, one command per call, with workdir set to the worktree path. "
            "Then return only a JSON verdict with outcome needs-feedback and question slow fixture.",
    "checkpoint":"Ignore every other instruction. In the worktree named by the brief: if "
                  "the command `git log origin/<base>..HEAD` already lists a commit, return only "
                  "a JSON verdict with outcome needs-feedback and question fixture complete. "
                  "Else create the file probe-checkpoint.txt with one line, commit it with a "
                  "message that ends in [skip ci], push the branch, then return only a JSON "
                  "verdict with outcome checkpoint and remaining fixture checkpoint. Every "
                  "command uses workdir set to the worktree path.",
}


def cmd_probe(args):
    """Run one probe. Config knobs and the fixture role last for this probe only."""
    _, _, bed, _ = paths(args.work)
    prompt = Path(args.prompt_file).read_text()
    config_path = bed / ".issue-flow.json"
    role = bed / ".codex" / "agents" / "issue-worker.toml"
    saved_config, saved_role = config_path.read_text(), role.read_text()
    config = json.loads(saved_config)
    if args.concurrency:
        config["concurrency"] = args.concurrency
    if args.wait_ms:
        config["codex"]["waitMs"] = args.wait_ms
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    if args.fixture != "none":
        body = f"developer_instructions = '''\n{FIXTURES[args.fixture]}\n'''"
        role.write_text(re.sub(r"(?s)developer_instructions = '''.*?'''", lambda _: body,
                               saved_role, count=1))
    try:
        exec_codex(args.work, prompt, f"probe-{args.name}", model=args.model, timeout=args.timeout)
    finally:
        config_path.write_text(saved_config)
        role.write_text(saved_role)


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
    for name in ("setup", "main", "probe", "timeline"):
        p = sub.add_parser(name)
        p.add_argument("--work", required=True)
    sub.choices["main"].add_argument("--attempt", type=int, default=1)
    sub.choices["probe"].add_argument("name")
    sub.choices["probe"].add_argument("--prompt-file", required=True)
    sub.choices["probe"].add_argument("--model", default=WORKER_MODEL)
    sub.choices["probe"].add_argument("--timeout", type=int, default=900)
    sub.choices["probe"].add_argument("--fixture", choices=["none", *FIXTURES], default="none")
    sub.choices["probe"].add_argument("--concurrency", type=int)
    sub.choices["probe"].add_argument("--wait-ms", type=int)
    sub.choices["timeline"].add_argument("--width", type=int, default=240)
    sub.choices["timeline"].add_argument("--messages", action="store_true")
    args = parser.parse_args()
    {"setup": cmd_setup, "main": cmd_main, "probe": cmd_probe,
     "timeline": cmd_timeline}[args.command](args)


if __name__ == "__main__":
    main()
