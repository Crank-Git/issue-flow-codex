#!/usr/bin/env python3
"""Run the worker and checker eval cases on `codex exec` and grade each run.

    python3 scripts/run_evals.py --suite worker|checker [--case <glob>] [--tag <tag>]
        [--runs N] [--out <dir>] [--worker-model <id>] [--worker-effort <level>]
        [--max-quota-percent <p>|off] [--keep]

Ports `scripts/run-evals.py` of upstream tag issue-flow--v0.21.0, which uses `claude -p`.
Each run gets a temporary sandbox: a git repo with a local bare origin, a tracker.json
that the fake `gh` serves, a copy of the plugin tree, and an isolated CODEX_HOME. The
copy leaves out evals/, so the agent cannot read the hidden tests or a reference patch.
The isolated home links auth.json from the operator's Codex home and holds the role files
of this working tree. The fake `gh` is first on PATH, so no run reaches a real forge.
The `codex` binary comes from IFE_CODEX, so the tests use a fake and spend nothing.

The record format and the summary are in evals/README.md.
"""

import argparse
import datetime
import fnmatch
import glob
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import conformance  # noqa: E402
import usage  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The sandbox copy leaves these out. The agent can read the whole disk, so the hidden tests
# and the reference patches of evals/ must not sit in any path that it is told about.
PLUGIN_COPY_IGNORE = shutil.ignore_patterns(".git", "evals", ".worktrees", ".claude")
DISPATCHER_MODEL = "gpt-6-luna"
DEFAULT_TIMEOUT_S = 900
FAKE_TOKEN = "ife-eval-fake-token-without-access"
EFFORTS = ("low", "medium", "high", "xhigh")
# Per suite: the role that the dispatcher spawns, and the role file that holds its model.
SUITES = {
    "worker": ("issue_worker", "issue-worker.toml"),
    "checker": ("criteria_checker", "criteria-checker.toml"),
}
# The host variables that a run takes. A run gets no other host variable (and no host secret).
KEEP_ENV = frozenset({
    "HOME", "USER", "LOGNAME", "SHELL", "PATH", "TMPDIR", "TERM", "TZ", "LANG",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
})
KEEP_ENV_PREFIXES = ("LC_",)
SANDBOX_GIT = {"GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@example.invalid",
               "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@example.invalid"}
# No host git config (so no credential helper, url rewrite or signing key), no ssh, and no
# prompt. A run that pushes can then reach only a remote that needs no login: the sandbox origin.
GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_SSH_COMMAND": "false", "GIT_TERMINAL_PROMPT": "0"}
# The agent can write the repo's .git/config. These settings stop the code it names from
# running when the runner itself calls git there.
GIT_SAFE_CONFIG = ("-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
                   "-c", "core.pager=cat")
# Codex fact 18: a command that the sandbox refuses leaves this text in the tool output.
SANDBOX_DENIAL = "sandbox_apply: Operation not permitted"
LAST_MESSAGE_LIMIT = 2000


class CaseError(Exception):
    """A case file that does not match the case format."""


# ---------------------------------------------------------------- cases


def load_cases(evals_dir, suite, case_glob=None, tag=None):
    """Return the valid cases of one suite, sorted by name; a bad case raises CaseError."""
    cases = []
    for path in sorted(glob.glob(os.path.join(evals_dir, suite, "*", "case.json"))):
        case_dir = os.path.dirname(path)
        with open(path) as handle:
            try:
                case = json.load(handle)
            except json.JSONDecodeError as error:
                raise CaseError(f"{path}: not JSON: {error}")
        validate_case(case, path)
        if case_glob and not fnmatch.fnmatch(case["name"], case_glob):
            continue
        if tag and tag not in case["tags"]:
            continue
        case["dir"] = case_dir
        case["tracker_path"] = os.path.join(case_dir, case.get("tracker", "tracker.json"))
        case["fixture_path"] = os.path.join(case_dir, case["fixture"]) if case.get("fixture") else None
        case["patch_path"] = os.path.join(case_dir, case["patch"]) if case.get("patch") else None
        if not os.path.isfile(case["tracker_path"]):
            raise CaseError(f"{path}: tracker file {case['tracker_path']} is missing")
        if case["fixture_path"] and not os.path.isdir(case["fixture_path"]):
            raise CaseError(f"{path}: fixture directory {case['fixture_path']} is missing")
        if case["patch_path"] and not os.path.isfile(case["patch_path"]):
            raise CaseError(f"{path}: patch file {case['patch_path']} is missing")
        cases.append(case)
    return cases


def validate_case(case, path):
    for key, kind in (("name", str), ("suite", str), ("tags", list), ("graders", list), ("prompt", str)):
        if not isinstance(case.get(key), kind):
            raise CaseError(f"{path}: '{key}' must be a {kind.__name__}")
    if not case["graders"]:
        raise CaseError(f"{path}: a case needs at least one grader")
    for grader in case["graders"]:
        if grader.get("type") not in GRADERS:
            raise CaseError(f"{path}: unknown grader type {grader.get('type')!r}")
    docs = case.get("docs_paths", [])
    if not (isinstance(docs, list) and all(isinstance(item, str) for item in docs)):
        raise CaseError(f"{path}: 'docs_paths' must be a list of path globs")
    if "patch" in case and not (isinstance(case["patch"], str) and isinstance(case.get("patch_branch"), str)):
        raise CaseError(f"{path}: a 'patch' needs a 'patch_branch' to commit it on")


def brief_of(case):
    """Return the brief between the BRIEF START and BRIEF END lines of the case prompt."""
    match = re.search(r"^BRIEF START\n(.*?)^BRIEF END", case["prompt"], re.S | re.M)
    if not match:
        raise CaseError(f"{case['name']}: the prompt has no BRIEF START and BRIEF END lines")
    return match.group(1)


def brief_field(brief, name):
    match = re.search(rf"^{name}:\s+(\S.*)$", brief, re.M)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------- sandbox


def minimal_env(home):
    """The environment of a command the runner starts in the sandbox: no host secret, no host git setup."""
    env = {name: os.environ[name] for name in ("PATH", "TMPDIR", "LANG") if name in os.environ}
    env.update(HOME=home, XDG_CONFIG_HOME=os.devnull, **GIT_ISOLATION, **SANDBOX_GIT)
    return env


def git(cwd, *args):
    """Run git in a sandbox repo that the agent can change, so no code it planted runs."""
    result = subprocess.run(["git", *GIT_SAFE_CONFIG, *args], cwd=cwd, capture_output=True, text=True,
                            env=minimal_env(os.devnull))
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in the sandbox: {result.stderr.strip()}")
    return result.stdout.strip()


def plugin_dir(sandbox):
    return os.path.join(sandbox, "plugin")


def fake_gh_dir(sandbox):
    return os.path.join(sandbox, "fakegh")


def build_sandbox(case):
    """Create the temp dir, the fixture repo with a local bare origin, and the tracker."""
    # macOS temp dirs sit behind a symlink (/var -> /private/var), and git reports the resolved path.
    sandbox = os.path.realpath(tempfile.mkdtemp(prefix="ife-"))
    shutil.copytree(ROOT, plugin_dir(sandbox), ignore=PLUGIN_COPY_IGNORE)
    shutil.copytree(os.path.join(ROOT, "evals", "fakegh"), fake_gh_dir(sandbox))
    repo = os.path.join(sandbox, "repo")
    if case["fixture_path"]:
        shutil.copytree(case["fixture_path"], repo)
    else:
        os.makedirs(repo)
        with open(os.path.join(repo, "README.md"), "w") as handle:
            handle.write(f"# {case['name']}\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "fixture")
    origin = os.path.join(sandbox, "origin.git")
    git(sandbox, "init", "-q", "--bare", origin)
    git(repo, "remote", "add", "origin", origin)
    if case.get("patch_path"):
        # The work under review: one commit on its own branch, as a worker would push it.
        git(repo, "checkout", "-q", "-b", case["patch_branch"])
        git(repo, "apply", case["patch_path"])
        git(repo, "add", "-A")
        git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "work under review")
        git(repo, "checkout", "-q", "main")
    git(repo, "push", "-q", "origin", "--all")
    git(repo, "fetch", "-q", "origin")
    git(repo, "remote", "set-head", "origin", "main")
    # Neither directory belongs in a commit that the agent makes.
    with open(os.path.join(repo, ".git", "info", "exclude"), "a") as handle:
        handle.write(".worktrees/\n.eval/\n")
    os.makedirs(os.path.join(repo, ".eval"))
    shutil.copyfile(case["tracker_path"], os.path.join(sandbox, "tracker.json"))
    os.makedirs(os.path.join(sandbox, "gh-config"))
    # A login shell reads the profile of its user, and a profile such as Homebrew shellenv puts
    # the real gh first on PATH again. Zsh reads the files of ZDOTDIR instead, and these put the fake gh first.
    zdotdir = os.path.join(sandbox, "zdotdir")
    os.makedirs(zdotdir)
    for name in (".zshenv", ".zprofile"):
        with open(os.path.join(zdotdir, name), "w") as handle:
            handle.write(f'export PATH="{fake_gh_dir(sandbox)}:$PATH"\n')
    return sandbox, repo


def refs_of(path, pattern="refs/heads"):
    """Return {ref: sha} for the branches of a repo."""
    lines = git(path, "for-each-ref", "--format=%(refname) %(objectname)", pattern).splitlines()
    return dict(line.split() for line in lines)


def start_state(case, sandbox, repo):
    """What a grader compares with after the run: the patch head and the branches as the runner left them."""
    head = git(repo, "rev-parse", f"refs/heads/{case['patch_branch']}") if case.get("patch_path") else None
    return {"head_sha": head, "start_refs": refs_of(os.path.join(sandbox, "origin.git")),
            "start_local_refs": refs_of(repo)}


def make_worktree(case, suite, repo, brief, head_sha):
    """Make the git worktree of the run and return its path.

    A worker gets `.worktrees/issue-<n>` on the branch of its brief. A checker gets
    `.worktrees/check-<n>`, detached at the commit under review.
    """
    repo = os.path.realpath(repo)
    number = re.search(r"#(\d+)", brief_field(brief, "issue") or "")
    if not number:
        raise CaseError(f"{case['name']}: the brief has no issue number")
    if suite == "worker":
        path = os.path.join(repo, ".worktrees", f"issue-{number.group(1)}")
        branch = brief_field(brief, "branch")
        if not branch:
            raise CaseError(f"{case['name']}: the brief has no branch")
        git(repo, "worktree", "add", "-q", path, "-b", branch, brief_field(brief, "base") or "origin/main")
    else:
        path = os.path.join(repo, ".worktrees", f"check-{number.group(1)}")
        git(repo, "worktree", "add", "-q", "--detach", path, head_sha)
    return path


def host_env_kept(name):
    return name in KEEP_ENV or name.startswith(KEEP_ENV_PREFIXES)


def sandbox_env(sandbox, codex_home):
    """The run's environment: the allowed host variables, the fake gh, the isolated home, and git with no host setup.

    The fake gh is first on PATH, SHELL is zsh (the ZDOTDIR files cover zsh only), and GH_TOKEN and GITHUB_TOKEN are a fake token. Git reads no
    global or system config, so it has no credential helper; ssh for git fails, and git never prompts.
    """
    env = {name: value for name, value in os.environ.items() if host_env_kept(name)}
    env.update(
        PATH=fake_gh_dir(sandbox) + os.pathsep + env.get("PATH", ""),
        SHELL="/bin/zsh",
        CODEX_HOME=codex_home,
        IFE_TRACKER=os.path.join(sandbox, "tracker.json"),
        IFE_GH_LOG=os.path.join(sandbox, "gh-log.jsonl"),
        GH_TOKEN=FAKE_TOKEN, GITHUB_TOKEN=FAKE_TOKEN,
        GH_CONFIG_DIR=os.path.join(sandbox, "gh-config"), GH_PROMPT_DISABLED="1",
        ZDOTDIR=os.path.join(sandbox, "zdotdir"),
        **GIT_ISOLATION, **SANDBOX_GIT,
    )
    return env


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


# ---------------------------------------------------------------- isolated Codex home


def operator_auth():
    """The operator's auth.json. HOME is read at call time, so a test can point it elsewhere."""
    return os.path.join(os.path.expanduser("~"), ".codex", "auth.json")


def set_role_key(text, key, value):
    """Set one top-level key of a role file. Fails when the key is missing."""
    new, count = re.subn(rf'(?m)^{key} = ".*"$', f'{key} = "{value}"', text, count=1)
    if not count:
        raise RuntimeError(f"the role file has no {key} line")
    return new


def role_key(text, key):
    match = re.search(rf'(?m)^{key} = "(.*)"$', text)
    return match.group(1) if match else None


def build_codex_home(home, suite, worker_model=None, worker_effort=None):
    """Make the isolated CODEX_HOME and return the model and effort of the role the suite spawns.

    Fact 26: a role file in `$CODEX_HOME/agents/` loads in every project. Fact 31: the role
    file model wins over a spawn model, so a model under test goes into the role file copy.
    The operator's own role files and Codex home stay untouched.
    """
    os.makedirs(os.path.join(home, "agents"))
    os.symlink(operator_auth(), os.path.join(home, "auth.json"))
    with open(os.path.join(home, "config.toml"), "w") as handle:
        # Codex fact 32: tool commands run in a login shell unless this root key is false.
        handle.write("allow_login_shell = false\n" + conformance.PROFILE)
    for role in glob.glob(os.path.join(ROOT, "roles", "*.toml")):
        shutil.copy(role, os.path.join(home, "agents", os.path.basename(role)))
    copy = os.path.join(home, "agents", SUITES[suite][1])
    with open(copy) as handle:
        text = handle.read()
    if worker_model:
        text = set_role_key(text, "model", worker_model)
    if worker_effort:
        text = set_role_key(text, "model_reasoning_effort", worker_effort)
    with open(copy, "w") as handle:
        handle.write(text)
    return role_key(text, "model"), role_key(text, "model_reasoning_effort")


def dispatcher_prompt(case, suite, head_sha, worktree, plugin):
    """Return the Codex dispatcher prompt: spawn one role with `fork_turns: "none"` and the brief.

    The case prompt is the upstream prompt for Claude Code, and its brief is what carries over.
    The brief names the sandbox copy of the plugin as `pluginRoot`, and the worktree of the run.
    """
    plugin = os.path.realpath(plugin)
    worktree = os.path.realpath(worktree)
    brief = brief_of(case).replace("{plugin_dir}", plugin)
    if head_sha:
        brief = brief.replace("{head_sha}", head_sha)
    brief = brief.rstrip("\n") + f"\nworktree:     {worktree}\n"
    if suite == "worker":
        brief += f"qualityRule:  {os.path.join(plugin, 'docs', 'rules', 'quality.md')}\n"
    role = SUITES[suite][0]
    number = re.search(r"#(\d+)", brief_field(brief, "issue") or "").group(1)
    target = "verdict.json" if suite == "worker" else "checker-verdict.json"
    return (
        "You are a dispatcher in an automated eval. Nobody is available to answer questions. "
        "Do only these steps:\n\n"
        "1. Call spawn_agent once, with:\n"
        f'   - agent_type: "{role}"\n'
        '   - fork_turns: "none"\n'
        f'   - task_name: "{suite}_{number}"\n'
        "   - message: the brief between the BRIEF START and BRIEF END lines below, unchanged.\n"
        "2. Call wait_agent until the agent finishes. Do not do its work yourself.\n"
        f"3. Write the agent's final message, unchanged, to `.eval/{target}` in the current directory.\n"
        "4. Reply with one line: the outcome of the agent.\n\n"
        f"BRIEF START\n{brief}BRIEF END\n"
    )


# ---------------------------------------------------------------- codex


def exec_argv(repo, last_message, prompt):
    """Fact 11: `codex exec` has no `-a` flag, so approval comes from `-c approval_policy="never"`."""
    return [*shlex.split(os.environ.get("IFE_CODEX", "codex")), "exec", "-m", DISPATCHER_MODEL, "--json",
            "-c", 'approval_policy="never"', "-C", os.path.realpath(repo), "-o", last_message, prompt]


def run_codex(argv, cwd, env, timeout_s):
    """Run codex with stdin closed, in its own process group; return (exit, stdout, stderr, timed_out)."""
    process = subprocess.Popen(argv, cwd=cwd, env=env, text=True, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
        return process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        # A killed run leaves no result; stop the whole tree so no child keeps working.
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr, True


def read_rollouts(home):
    """Return the `usage.read_rollout` summary of each rollout file in the isolated home."""
    paths = sorted(glob.glob(os.path.join(home, "sessions", "**", "rollout-*.jsonl"), recursive=True))
    return [usage.read_rollout(path) for path in paths]


def sandbox_denied(rollouts):
    """True when a tool output in the rollout of a spawned agent shows a command that the sandbox refused.

    Text that the agent read or wrote is not a denial, so only `function_call_output` lines count.
    """
    for row in rollouts:
        if row["role"] == "root":
            continue
        with open(row["path"], errors="replace") as handle:
            for line in handle:
                if SANDBOX_DENIAL not in line:
                    continue
                try:
                    payload = json.loads(line).get("payload")
                except ValueError:
                    continue
                if isinstance(payload, dict) and payload.get("type") == "function_call_output" \
                        and SANDBOX_DENIAL in json.dumps(payload.get("output")):
                    return True
    return False


def restore_auth(codex_home):
    """Copy a token that Codex wrote over the auth.json link back to the operator's file.

    Codex writes auth.json through a temporary file and a rename (codex-harness, "auth.json is written through a temporary file"). When
    that replaces the link, the refreshed token would die with the sandbox, and the operator's
    file would keep a refresh token that Codex has retired.
    """
    link = os.path.join(codex_home, "auth.json")
    if os.path.islink(link) or not os.path.isfile(link):
        return
    target = operator_auth()
    temporary = target + ".ife-tmp"
    shutil.copyfile(link, temporary)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    print(f"restored a refreshed auth.json to {target}", file=sys.stderr)


# ---------------------------------------------------------------- graders


def log_text(entry):
    skip = 1 if entry.get("cmd") == "api" else len(entry.get("cmd", "").split())
    return " ".join(str(arg) for arg in entry.get("argv", [])[skip:])


def matches(spec, entry):
    # A spec with only a `kind` (for example `write`) matches every call of that kind.
    if "kind" in spec and entry.get("kind") != spec["kind"]:
        return False
    if ("cmd" in spec or "kind" not in spec) and entry.get("cmd") != spec.get("cmd"):
        return False
    # No re.M here: the args text holds the body lines too, and `^` must anchor at the issue number.
    if "args" in spec and not re.search(spec["args"], log_text(entry)):
        return False
    if "body" in spec and not re.search(spec["body"], entry.get("body") or "", re.M):
        return False
    return True


def describe(spec):
    parts = [spec.get("cmd") or f"any {spec.get('kind', '?')} call"]
    if "args" in spec:
        parts.append(f"args /{spec['args']}/")
    if "body" in spec:
        parts.append(f"body /{spec['body']}/")
    return " ".join(parts)


def grade_gh_log(grader, ctx):
    """Every `expect` entry matches a successful call (in order when `ordered`); no call matches a `forbid` entry."""
    done = [entry for entry in ctx["gh_log"] if entry.get("kind") != "error"]
    problems = []
    last_seq = 0
    for spec in grader.get("expect", []):
        floor = last_seq if grader.get("ordered") else 0
        hit = next((e for e in done if e["seq"] > floor and matches(spec, e)), None)
        if hit is None:
            problems.append(f"missing {describe(spec)}" + (" (in order)" if grader.get("ordered") else ""))
        else:
            last_seq = hit["seq"]
    # A refused call still shows the decision, so forbid checks every call.
    for spec in grader.get("forbid", []):
        for entry in ctx["gh_log"]:
            if matches(spec, entry):
                problems.append(f"forbidden {describe(spec)} (seq {entry['seq']}: {' '.join(map(str, entry['argv']))})")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(grader.get('expect', []))} expected, {len(grader.get('forbid', []))} forbidden"


VERDICT_PATH = ".eval/verdict.json"
OUTCOMES = {"ready-to-merge", "checkpoint", "needs-feedback", "blocked"}
HIDDEN_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "hidden_test*.py"]
# The words that name the pre-patch run. The worker brief gives no fixed field for it, so
# workers say it in their own words.
PREPATCH_RUN = (r"(?i)\bpre-?(patch|fix|change)|\bunpatched\b"
                r"|\b(before|without) (the|my|this|any) (fix|change|patch|implementation)\b")


def acceptance_criteria(tracker, number):
    """Return the checklist items under the issue's `Acceptance criteria` heading, in order."""
    issue = next((item for item in tracker.get("issues", []) if item["number"] == number), None)
    found, inside = [], False
    for line in ((issue or {}).get("body") or "").splitlines():
        if line.startswith("#"):
            inside = line.lstrip("#").strip().lower() == "acceptance criteria"
            continue
        item = re.match(r"\s*[-*] \[[ xX]\] (.+)", line)
        if inside and item:
            found.append(item.group(1).strip())
    return found


def path_allowed(path, allow):
    return any(fnmatch.fnmatch(path, pattern) for pattern in allow)


def fixture_commit(repo):
    """The commit that build_sandbox made from the fixture: the root commit of main."""
    return git(repo, "rev-list", "--max-parents=0", "main").splitlines()[-1]


def issue_branch(repo, number):
    """Return ((ref, sha), None) for the worker's issue/<number>-* branch, or (None, reason).

    A local branch wins over origin, because a worker can commit after its last push.
    """
    for pattern in (f"refs/heads/issue/{number}-*", f"refs/remotes/origin/issue/{number}-*"):
        refs = git(repo, "for-each-ref", "--format=%(refname) %(objectname)", pattern).splitlines()
        if len(refs) > 1:
            return None, f"more than one branch matches {pattern}: {', '.join(r.split()[0] for r in refs)}"
        if refs:
            return tuple(refs[0].split()), None
    return None, f"no branch issue/{number}-* in the sandbox repo or its origin"


def grade_hidden_tests(grader, ctx):
    """Run the case's hidden tests in a clean checkout of the worker's branch; pass on exit 0.

    FR-14: this runs after the agent has finished, and the tests go into a separate clone,
    so they never reach the repo the agent worked in.
    """
    found, reason = issue_branch(ctx["repo"], grader["issue"])
    if found is None:
        return False, reason
    ref, sha = found
    checkout = os.path.join(ctx["sandbox"], "grading")
    shutil.rmtree(checkout, ignore_errors=True)
    try:
        git(ctx["sandbox"], "clone", "-q", "--no-checkout", ctx["repo"], checkout)
        git(checkout, "checkout", "-q", "--detach", sha)
        hidden = os.path.join(ctx["case"]["dir"], grader.get("dir", "hidden"))
        for entry in sorted(os.listdir(hidden)):
            shutil.copy(os.path.join(hidden, entry), checkout)
        try:
            # The tests run the agent's code, so they get no host variable but the basics.
            result = subprocess.run(grader.get("command") or HIDDEN_COMMAND, cwd=checkout,
                                    capture_output=True, text=True, timeout=grader.get("timeout_s", 300),
                                    env=minimal_env(ctx["sandbox"]))
        except subprocess.TimeoutExpired:
            return False, f"the hidden tests on {ref} ran past {grader.get('timeout_s', 300)}s"
    finally:
        shutil.rmtree(checkout, ignore_errors=True)
    output = (result.stderr + result.stdout).strip().splitlines()
    tail = " | ".join(line for line in output if re.match(r"(Ran \d+|OK|FAILED)", line)) or " | ".join(output[-3:])
    verdict = "pass" if result.returncode == 0 else f"fail (exit {result.returncode})"
    return result.returncode == 0, f"hidden tests on {ref} {sha[:8]}: {verdict}: {tail[:300]}"


def read_verdict(path):
    """Return (verdict, None), or (None, reason). A JSON object inside a code fence also counts."""
    if not os.path.isfile(path):
        return None, f"{os.path.basename(os.path.dirname(path))}/{os.path.basename(path)} does not exist"
    with open(path, errors="replace") as handle:
        text = handle.read().strip()
    for candidate in [text, *re.findall(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.S)]:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data, None
    return None, f"the verdict file holds no JSON object: {text[:120]!r}"


def grade_verdict(grader, ctx):
    """The verdict parses, has the expected outcome, and backs every acceptance criterion with evidence."""
    verdict, reason = read_verdict(os.path.join(ctx["repo"], grader.get("path", VERDICT_PATH)))
    if verdict is None:
        return False, reason
    problems = []
    outcome = verdict.get("outcome")
    if outcome not in OUTCOMES:
        problems.append(f"outcome {outcome!r} is not one of {sorted(OUTCOMES)}")
    if grader.get("outcome") and outcome != grader["outcome"]:
        problems.append(f"outcome {outcome!r}, expected {grader['outcome']!r}")
    if str(verdict.get("issue", "")).lstrip("#") != str(grader["issue"]):
        problems.append(f"issue {verdict.get('issue')!r}, expected {grader['issue']}")
    if outcome == "needs-feedback" and not str(verdict.get("question") or "").strip():
        problems.append("needs-feedback without a question")
    if outcome == "ready-to-merge":
        with open(ctx["case"]["tracker_path"]) as handle:
            expected = acceptance_criteria(json.load(handle), grader["issue"])
        criteria = [c for c in verdict.get("criteria") or [] if isinstance(c, dict)]
        if len(criteria) < len(expected):
            problems.append(f"criteria has {len(criteria)} entries for {len(expected)} acceptance criteria")
        for index, criterion in enumerate(criteria, start=1):
            if criterion.get("met") is not True:
                problems.append(f"criterion {index} is not met")
            if not str(criterion.get("evidence") or "").strip():
                problems.append(f"criterion {index} has no evidence")
    if grader.get("prepatch"):
        checks = str(verdict.get("localChecks") or "")
        if not (re.search(PREPATCH_RUN, checks) and re.search(r"(?i)\bfail", checks)):
            problems.append(f"localChecks names no pre-patch failing run: {checks[:160]!r}")
    if problems:
        return False, "; ".join(problems)
    return True, f"outcome {outcome}, {len(verdict.get('criteria') or [])} criteria"


def grade_diff_scope(grader, ctx):
    """main does not move, and the worker's branch changes only allowed paths (or nothing is committed)."""
    repo = ctx["repo"]
    base = fixture_commit(repo)
    origin = os.path.join(ctx["sandbox"], "origin.git")
    problems = [f"{where} main moved off the fixture commit"
                for where, path in (("the local", repo), ("origin's", origin))
                if git(path, "rev-parse", "refs/heads/main") != base]
    if grader.get("no_commits"):
        # Every ref, worktree HEADs included, in the repo and in its origin.
        new = set()
        for path in (repo, origin):
            new.update(git(path, "rev-list", "--all", "--not", base).split())
        if new:
            problems.append(f"{len(new)} commit(s) beyond the fixture, expected none")
        detail = "no commits beyond the fixture"
    else:
        found, reason = issue_branch(repo, grader["issue"])
        if found is None:
            return False, reason
        ref, sha = found
        changed = git(repo, "diff", "--no-ext-diff", "--name-only", base, sha).splitlines()
        # A worker brief asks for docs of a changed interface, so the case's docs are always allowed.
        allow = grader.get("allow", []) + ctx["case"].get("docs_paths", [])
        outside = [path for path in changed if not path_allowed(path, allow)]
        if outside:
            problems.append(f"{ref} changes paths outside the allowlist: {', '.join(outside)}")
        if not changed:
            problems.append(f"{ref} changes nothing")
        detail = f"{ref} changes {len(changed)} path(s), all allowed"
    if problems:
        return False, "; ".join(problems)
    return True, detail


CHECKER_VERDICT_PATH = ".eval/checker-verdict.json"
CHECKER_STATUSES = ("met", "unmet", "unclear")


def grade_checker_verdict(grader, ctx):
    """The checker's verdict follows its contract, names the head it checked, and gives the expected statuses.

    `expect: all-met` passes when every criterion is `met`. `expect: unmet` passes when each
    criterion that `criteria` lists (counted from 1) is `unmet`; `unclear` does not count.
    """
    verdict, reason = read_verdict(os.path.join(ctx["repo"], grader.get("path", CHECKER_VERDICT_PATH)))
    if verdict is None:
        return False, reason
    with open(ctx["case"]["tracker_path"]) as handle:
        expected = acceptance_criteria(json.load(handle), grader["issue"])
    problems = []
    if str(verdict.get("issue", "")).lstrip("#") != str(grader["issue"]):
        problems.append(f"issue {verdict.get('issue')!r}, expected {grader['issue']}")
    head, sha = str(verdict.get("headSha") or ""), ctx.get("head_sha") or ""
    if not (re.fullmatch(r"[0-9a-f]{7,40}", head) and sha.startswith(head)):
        problems.append(f"headSha {verdict.get('headSha')!r} is not the head under review {sha[:12]}")
    if not str(verdict.get("testsRun") or "").strip():
        problems.append("testsRun is empty")
    criteria = [c for c in verdict.get("criteria") or [] if isinstance(c, dict)]
    if len(criteria) != len(expected):
        problems.append(f"criteria has {len(criteria)} entries for {len(expected)} acceptance criteria")
    statuses = [c.get("status") for c in criteria]
    for index, criterion in enumerate(criteria, start=1):
        if criterion.get("status") not in CHECKER_STATUSES:
            problems.append(f"criterion {index} status {criterion.get('status')!r} is not one of {list(CHECKER_STATUSES)}")
        if not str(criterion.get("evidence") or "").strip():
            problems.append(f"criterion {index} has no evidence")
    if grader.get("expect") == "all-met" and any(status != "met" for status in statuses):
        problems.append(f"expected every criterion met, got {statuses}")
    if grader.get("expect") == "unmet":
        for number in grader.get("criteria", []):
            got = statuses[number - 1] if number <= len(statuses) else None
            if got != "unmet":
                problems.append(f"criterion {number} is {got!r}, expected 'unmet'")
    if problems:
        return False, "; ".join(problems)
    return True, f"statuses {statuses} on {head[:8]}"


def grade_refs_unchanged(grader, ctx):
    """No branch of origin changed, and no local branch that the runner made moved: the agent wrote no commit."""
    problems = []
    now = refs_of(os.path.join(ctx["sandbox"], "origin.git"))
    if now != ctx["start_refs"]:
        moved = sorted(ref for ref in set(now) | set(ctx["start_refs"]) if now.get(ref) != ctx["start_refs"].get(ref))
        problems.append(f"origin refs changed: {', '.join(moved)}")
    local = refs_of(ctx["repo"])
    # A worktree adds a branch of its own, so only the branches that existed at the start count.
    moved = sorted(ref for ref, sha in ctx["start_local_refs"].items() if local.get(ref) != sha)
    if moved:
        problems.append(f"local refs moved: {', '.join(moved)}")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(now)} origin ref(s) unchanged"


# The `llm` judge grader and the `spawns` grader of upstream are not ported. Each grader
# returns (passed, detail).
GRADERS = {"gh_log": grade_gh_log, "hidden_tests": grade_hidden_tests, "verdict": grade_verdict,
           "diff_scope": grade_diff_scope, "checker_verdict": grade_checker_verdict,
           "refs_unchanged": grade_refs_unchanged}


# ---------------------------------------------------------------- one run


def run_case(case, suite, run_number, args, run_dir):
    """Run one case once and return its record."""
    sandbox, repo = build_sandbox(case)
    state = start_state(case, sandbox, repo)
    codex_home = os.path.join(sandbox, "codex-home")
    model, effort = build_codex_home(codex_home, suite, args.worker_model, args.worker_effort)
    brief = brief_of(case).replace("{plugin_dir}", plugin_dir(sandbox))
    worktree = make_worktree(case, suite, repo, brief, state["head_sha"])
    prompt = dispatcher_prompt(case, suite, state["head_sha"], worktree, plugin_dir(sandbox))
    last_message = os.path.join(sandbox, "last-message.txt")
    timeout_s = case.get("timeout_s", DEFAULT_TIMEOUT_S)

    started = time.time()
    code, stdout, stderr, timed_out = run_codex(exec_argv(repo, last_message, prompt), repo,
                                                sandbox_env(sandbox, codex_home), timeout_s)
    duration = time.time() - started
    restore_auth(codex_home)
    rollouts = read_rollouts(codex_home)
    error = None
    if timed_out:
        error = f"timeout after {timeout_s}s"
    elif code != 0:
        last_line = next((line for line in reversed((stderr or "").splitlines()) if line.strip()), "")
        error = f"codex exit {code}: {last_line.strip()[:300]}"

    os.makedirs(run_dir, exist_ok=True)
    for name, text in (("codex-stdout.jsonl", stdout), ("codex-stderr.txt", stderr)):
        with open(os.path.join(run_dir, name), "w") as handle:
            handle.write(text or "")
    for name in ("gh-log.jsonl", "tracker.json"):
        if os.path.exists(os.path.join(sandbox, name)):
            shutil.copyfile(os.path.join(sandbox, name), os.path.join(run_dir, name))
    # The root rollout carries the quota samples of the run. The others show why an agent failed.
    os.makedirs(os.path.join(run_dir, "rollouts"), exist_ok=True)
    for row in rollouts:
        shutil.copyfile(row["path"], os.path.join(run_dir, "rollouts", os.path.basename(row["path"])))

    ctx = {"sandbox": sandbox, "repo": repo, "case": case,
           "gh_log": read_jsonl(os.path.join(sandbox, "gh-log.jsonl")), **state}
    graders = []
    for grader in case["graders"]:
        try:
            passed, detail = GRADERS[grader["type"]](grader, ctx)
        except Exception as crash:  # a broken grader fails its own check, not the whole suite
            passed, detail = False, f"grader crashed: {crash!r}"
        graders.append({"type": grader["type"], "passed": passed, "detail": detail})

    if not error and not all(g["passed"] for g in graders) and sandbox_denied(rollouts):
        error = "the sandbox denied a command of the agent"

    message = ""
    if os.path.isfile(last_message):
        with open(last_message, errors="replace") as handle:
            message = handle.read().strip()[:LAST_MESSAGE_LIMIT]
    if args.keep:
        kept = sandbox
    else:
        shutil.rmtree(sandbox, ignore_errors=True)
        kept = None

    outcome = "error" if error else "pass" if all(g["passed"] for g in graders) else "fail"
    record = {
        "case": case["name"], "run": run_number, "suite": suite,
        "worker_model": model, "worker_effort": effort, "dispatcher_model": DISPATCHER_MODEL,
        "graders": graders, "outcome": outcome, "error": error,
        "duration_s": round(duration, 3),
        "usage": usage.sum_counts(rollouts),
        "rollouts": [{key: row[key] for key in ("path", "id", "role", "model", "calls")} for row in rollouts],
        "last_message": message,
        "sandbox": kept,
    }
    with open(os.path.join(run_dir, "record.json"), "w") as handle:
        json.dump(record, handle, indent=2)
    return record


# ---------------------------------------------------------------- summary


def mean(values):
    return round(sum(values) / len(values), 3) if values else None


def summarize_group(records):
    """Counts, rates and means of one group of records.

    A run with the outcome `error` is counted apart. A rate and a mean take only the runs
    that were graded, so that a denied command does not lower the pass rate of a model.
    """
    graded = [r for r in records if r["outcome"] != "error"]
    hidden = [next(g["passed"] for g in r["graders"] if g["type"] == "hidden_tests")
              for r in graded if any(g["type"] == "hidden_tests" for g in r["graders"])]
    return {
        "runs": len(records), "passed": sum(r["outcome"] == "pass" for r in records),
        "failed": sum(r["outcome"] == "fail" for r in records),
        "errors": sum(r["outcome"] == "error" for r in records),
        "pass_rate": mean([r["outcome"] == "pass" for r in graded]),
        "hidden_tests_pass_rate": mean(hidden),
        "mean_input_tokens": mean([r["usage"]["input"] for r in graded]),
        "mean_output_tokens": mean([r["usage"]["output"] for r in graded]),
    }


def summarize(records):
    """Return the summary of the suite and of each case (FR-17)."""
    cases = sorted({r["case"] for r in records})
    return {"suite": summarize_group(records),
            "cases": {name: summarize_group([r for r in records if r["case"] == name]) for name in cases}}


def quota_limit(text):
    """Return the limit of `--max-quota-percent` as a float, or None for `off`."""
    if text == "off":
        return None
    try:
        return float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number or 'off'") from None


def quota_samples(out, records):
    """Return the time-ordered (used_percent, resets_at) samples of the root rollouts of `records`.

    Only a root rollout holds the account-wide `rate_limits` of its run (see scripts/usage.py).
    """
    timed = []
    for record in records:
        pattern = os.path.join(out, record["case"], f"run-{record['run']}", "rollouts", "rollout-*.jsonl")
        for path in sorted(glob.glob(pattern)):
            row = usage.read_rollout(path)
            if row["role"] == "root":
                timed.extend(row["samples"])
    timed.sort(key=lambda sample: (sample[0] is None, sample[0]))
    return [(used, resets) for _, used, resets in timed]


def quota_exceeded(results, out, limit):
    """Return a reason to stop before the next run, or None.

    The share counts the samples of the runs of this invocation only (FR-18, FR-19). Without
    a sample after the first run the share is unknown, so the runner stops instead of
    running without a limit.
    """
    if limit is None or not results["records"]:
        return None
    samples = quota_samples(out, results["records"])
    if not samples:
        return ("no quota samples in the rollouts of the earlier runs; "
                "start again with --max-quota-percent off to run without a limit")
    share = usage.quota_share(samples)
    if share >= limit:
        return f"quota share {share:g}% of this invocation is at or above the limit of {limit:g}%"
    return None


# ---------------------------------------------------------------- main


def summary_line(record):
    line = (f"{record['case']} run {record['run']}: {record['outcome'].upper()}  "
            f"input {record['usage']['input']}  output {record['usage']['output']}")
    if record["error"]:
        line += f"  error: {record['error']}"
    failed = [f"    {g['type']}: {g['detail']}" for g in record["graders"] if not g["passed"]]
    return "\n".join([line, *failed])


def write_json(path, data):
    temporary = path + ".tmp"
    with open(temporary, "w") as handle:
        json.dump(data, handle, indent=2)
    os.replace(temporary, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the issue-flow eval cases on codex exec.")
    parser.add_argument("--suite", required=True, choices=sorted(SUITES), help="worker or checker")
    parser.add_argument("--case", help="only the cases whose name matches this glob")
    parser.add_argument("--tag", help="only the cases that carry this tag")
    parser.add_argument("--runs", type=int, help="runs per case; overrides the case's own count")
    parser.add_argument("--out", help="the results directory (default evals/results/<UTC time>)")
    parser.add_argument("--worker-model", help="model of the role that the suite spawns; set in the isolated role copy")
    parser.add_argument("--worker-effort", choices=EFFORTS, help="model_reasoning_effort of that role copy")
    parser.add_argument("--max-quota-percent", type=quota_limit, default=3.0, metavar="P|off",
                        help="stop before a new run when this invocation used P%% of the weekly quota (default 3)")
    parser.add_argument("--keep", action="store_true", help="keep each sandbox for inspection")
    parser.add_argument("--evals-dir", default=os.path.join(ROOT, "evals"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        cases = load_cases(args.evals_dir, args.suite, args.case, args.tag)
    except CaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if not cases:
        print("error: no case matches", file=sys.stderr)
        return 2
    # Large cases run last, so that a quota stop leaves the cheap cases measured.
    cases.sort(key=lambda case: "large" in case["tags"])

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.abspath(args.out or os.path.join(args.evals_dir, "results", stamp))
    os.makedirs(out, exist_ok=True)
    results = {"suite": args.suite, "worker_model": args.worker_model, "worker_effort": args.worker_effort,
               "dispatcher_model": DISPATCHER_MODEL, "started": stamp, "finished": None,
               "partial": False, "stop_reason": None, "records": []}
    plan = [(case, k) for case in cases for k in range(1, (args.runs or case.get("runs", 1)) + 1)]
    for index, (case, run_number) in enumerate(plan):
        reason = quota_exceeded(results, out, args.max_quota_percent)
        if reason:
            results.update(partial=True, stop_reason=reason)
            print(f"stopped: {reason}; {len(plan) - index} run(s) not started")
            break
        run_dir = os.path.join(out, case["name"], f"run-{run_number}")
        try:
            record = run_case(case, args.suite, run_number, args, run_dir)
        except (CaseError, RuntimeError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        results["records"].append(record)
        write_json(os.path.join(out, "results.json"), results)
        print(summary_line(record), flush=True)

    results["finished"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(os.path.join(out, "results.json"), results)
    summary = {**summarize(results["records"]), "partial": results["partial"],
               "stop_reason": results["stop_reason"]}
    write_json(os.path.join(out, "summary.json"), summary)
    suite = summary["suite"]
    print(f"\n{suite['passed']} pass, {suite['failed']} fail, {suite['errors']} error of {suite['runs']} runs; "
          f"results in {out}")
    return 0 if suite["passed"] == suite["runs"] and not results["partial"] else 1


if __name__ == "__main__":
    sys.exit(main())
