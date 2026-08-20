"""
Shared plumbing for the local Beam operations scripts.

These scripts replace the colab_*.ipynb notebooks that used to live beside them.
The notebooks existed because Colab has the bandwidth and the RAM that the
*first* deploy needs -- an 8.4 GiB download from HuggingFace, a bf16 export that
wants ~9 GiB of RAM, and a 5.25 GiB upload. Everything else they did needs
neither: `beam deploy` syncs a directory and the rest is HTTP.

Three differences from the notebooks, each of which is a bug they had:

  * They cloned from GitHub, so they deployed what was pushed. These deploy the
    working tree, which is what you are actually looking at. `git_state()`
    prints the difference rather than hiding it.
  * They rewrote config.py from their own configuration cell on every run. A
    Colab copy saved before a fix therefore re-applied the old value on top of
    new code -- which is how a deployment configured for A10G in git shipped on
    RTX4090 on 2026-08-20. Here config.py is the authority and nothing is
    rewritten unless you pass a flag that says so.
  * They read /health and believed it. A container restored from a Beam memory
    snapshot replays the whole heap, so `runtime.gpu` and `process_age_seconds`
    describe the process that was *captured*, not the one you just deployed.
    `restore_check()` compares the process's age against its own container's
    uptime, which is the one comparison that catches it.
"""

import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

# Beam draws its tables with box characters. A Windows console defaults to a
# codepage that cannot encode them, and a UnicodeEncodeError halfway through a
# deploy is a miserable way to find that out.
for _out in (sys.stdout, sys.stderr):
    try:
        _out.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


# --------------------------------------------------------------- subprocesses

def stream(cmd, stdin_text=None, quiet=False, timeout=None):
    """Run cmd, echoing output as it arrives. Returns (exit_code, output).

    `timeout` kills the child after that many seconds. Some beam subcommands
    tail rather than return -- `beam logs` most of all -- and one of those in a
    loop is the difference between a step that takes two seconds and one you
    have to interrupt.
    """
    # PYTHONIOENCODING, because `beam` is itself a Python program and its stdout
    # is a pipe here. Without this it picks up the console codepage -- cp1252 on
    # Windows -- and dies with a UnicodeEncodeError on the first box-drawing
    # character in its own table, which is not a failure of the command you ran.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        text=True, bufsize=1, encoding="utf-8", errors="replace", env=env)
    if stdin_text is not None:
        proc.stdin.write(stdin_text)
        proc.stdin.flush()
        proc.stdin.close()

    # A flag rather than the exit code: a killed child reports -9 on Linux but 1
    # on Windows, and these scripts should read the same either way.
    fired = []

    def _kill():
        fired.append(True)
        proc.kill()

    killer = threading.Timer(timeout, _kill) if timeout else None
    if killer:
        killer.daemon = True
        killer.start()
    out = []
    try:
        for line in proc.stdout:
            if not quiet:
                print(line, end="")
            out.append(line)
        code = proc.wait()
    finally:
        if killer:
            killer.cancel()
    if fired:
        out.append("\n[killed after %ss -- this command does not return on its own]\n" % timeout)
        if not quiet:
            print(out[-1], end="")
    return code, "".join(out)


def run(cmd, check=True, stdin_text=None, quiet=False, timeout=None):
    code, out = stream(cmd, stdin_text, quiet, timeout)
    if check and code != 0:
        raise subprocess.CalledProcessError(code, " ".join(cmd), out)
    return out


class Fatal(SystemExit):
    """A stop with a reason, printed without a traceback."""

    def __init__(self, message):
        super().__init__("\n" + str(message))


# ------------------------------------------------------- Beam CLI table/JSON

_RULES = "│┃|"


def parse_table(text):
    """Beam's CLI table as a list of dicts. Deliberately forgiving.

    The table layout is not an API and has changed shape before, so every caller
    keeps the raw text too: a parse that comes back empty degrades to "read it
    yourself above" rather than to a crash in the middle of a cleanup.

    Only builds that draw column rules can be read this way, and the current one
    does not -- it separates columns with whitespace and truncates ids to fit the
    terminal ("093a56f4-4..."). A truncated id cannot be passed back to
    `beam deployment stop` anyway, so JSON is the only actionable form and this
    is a fallback for reading, not for acting.
    """
    rows = []
    for line in text.splitlines():
        if not any(ch in line for ch in _RULES):
            continue
        cells = [c.strip() for c in re.split("[" + _RULES + "]", line.strip())]
        cells = [c for c in cells if c]
        if cells:
            rows.append(cells)
    if not rows:
        return []
    header = [re.sub(r"\W+", "_", h.lower()).strip("_") for h in rows[0]]
    parsed = []
    for cells in rows[1:]:
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        if all(set(v) <= set("-─━ ") for v in row.values()):
            continue        # a horizontal rule that happened to have pipes
        parsed.append(row)
    return parsed


def field(row, *candidates):
    """Read a column by any of several plausible names, ignoring punctuation."""
    norm = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in row.items()}
    for c in candidates:
        key = re.sub(r"[^a-z0-9]", "", c.lower())
        if key in norm and norm[key] not in (None, ""):
            return str(norm[key])
    return ""


def beam_rows(args, label=None, verbose=False):
    """`beam <args>` as (rows, raw_text), preferring JSON if this CLI offers it.

    JSON matters for more than tidiness: the table truncates ids to fit the
    terminal (093a56f4-4...), and a truncated id cannot be handed back to
    `beam deployment stop`.
    """
    code, out = stream(["beam"] + args + ["--format", "json"], quiet=True)
    if code == 0 and "[" in out and "]" in out:
        try:
            data = json.loads(out[out.index("["):out.rindex("]") + 1])
            if isinstance(data, list):
                if label and verbose:
                    print("%s: %d row(s), read as JSON" % (label, len(data)))
                return data, out
        except Exception:
            pass
    code, out = stream(["beam"] + args, quiet=not verbose)
    rows = parse_table(out) if code == 0 else []
    if code == 0 and out.strip() and not rows:
        # Silence here would look like an empty account rather than an unread
        # table, and a caller would go on to report "nothing to do".
        print("  WARN  `beam %s` produced output that could not be parsed, and this"
              % " ".join(args))
        print("        CLI did not offer --format json. Anything below that depends on")
        print("        those rows is missing them; read the listing yourself.")
    return rows, out


def require_beam():
    """Fail early and with the fix, rather than inside a deploy."""
    code, out = stream(["beam", "machine", "list"], quiet=True, timeout=120)
    if code != 0:
        raise Fatal(
            "The beam CLI is not usable here.\n\n"
            "  install:      uv tool install beam-client\n"
            "  authenticate: beam configure default --token <token from the dashboard>\n\n"
            "`beam machine list` said:\n" + (out.strip()[-1500:] or "(nothing)"))
    return out


# ------------------------------------------------------------ the repo itself

def repo_root(start=None):
    """Walk up to the directory that holds nanochat/.

    The same rule app.py uses to find its own root, so a deploy from here and an
    import inside the container agree about what the repo is.
    """
    path = os.path.abspath(start or __file__)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    while not os.path.isdir(os.path.join(path, "nanochat")):
        parent = os.path.dirname(path)
        if parent == path:
            raise Fatal("No nanochat/ package found above %s" % (start or __file__))
        path = parent
    return path


ROOT = repo_root()
HOSTING = os.path.join(ROOT, "dev", "hosting", "beam")
CONFIG_PATH = os.path.join(HOSTING, "config.py")


def git_state():
    """(head, dirty_paths) for the tree that is about to be deployed.

    `beam deploy` syncs the working directory, so uncommitted edits ship. That
    is usually what you want from a laptop and never what the notebooks did,
    which is exactly why it gets printed rather than assumed either way.
    """
    code, sha = stream(["git", "-C", ROOT, "log", "-1", "--format=%h %s"], quiet=True)
    code2, status = stream(["git", "-C", ROOT, "status", "--porcelain"], quiet=True)
    dirty = [ln[3:].strip() for ln in status.splitlines() if ln.strip()] if code2 == 0 else []
    return (sha.strip() if code == 0 else "(not a git checkout)"), dirty


def ensure_beamignore():
    """Copy beamignore.template to the repo root, where beam actually reads it.

    Without it the sync uploads .git, every figure and any checkpoint sitting in
    the tree, which turns a five-second deploy into a very long one.
    """
    import shutil
    dest = os.path.join(ROOT, ".beamignore")
    shutil.copy(os.path.join(HOSTING, "beamignore.template"), dest)
    return dest


# ------------------------------------------------------------------ config.py

CONFIG_KEYS = {
    "gpu": (r"^GPU = .*$", 'GPU = "%s"'),
    "ui_file": (r"^UI_FILE = .*$", 'UI_FILE = "%s"'),
    "app_name": (r"^APP_NAME = .*$", 'APP_NAME = "%s"'),
    "min_containers": (r"^MIN_CONTAINERS = .*$", "MIN_CONTAINERS = %s"),
    "max_containers": (r"^MAX_CONTAINERS = .*$", "MAX_CONTAINERS = %s"),
    "keep_warm_seconds": (r"^KEEP_WARM_SECONDS = .*$", "KEEP_WARM_SECONDS = %s"),
    "checkpoint_enabled": (r"^CHECKPOINT_ENABLED = .*$", "CHECKPOINT_ENABLED = %s"),
}

ENV_KEYS = {
    "step": "NANOCHAT_STEP",
    "system_prompt_file": "NANOCHAT_SYSTEM_PROMPT_FILE",
    "fix_punctuation": "NANOCHAT_FIX_PUNCTUATION",
    "priming_turns": "NANOCHAT_PRIMING_TURNS",
}


def read_config():
    """config.py's deploy-time values, without importing it.

    Importing would pull in `beam`, which wants a configured CLI context and
    kills the process if it does not find one -- a poor way for a read-only
    summary to behave.
    """
    text = open(CONFIG_PATH, encoding="utf-8").read()
    out = {}
    for key, (pattern, _) in CONFIG_KEYS.items():
        m = re.search(pattern, text, re.M)
        out[key] = m.group(0).split("=", 1)[1].strip().strip('"') if m else None

    # CONTAINER_ENV builds some paths out of MOUNT_PATH with an f-string, so the
    # literal in the file is not the value the container sees. Resolve the two
    # names that appear there rather than reporting "{MOUNT_PATH}/..." at a
    # reader who is trying to check a path against `beam ls`.
    consts = {name: (re.search(r'^%s = "([^"]+)"' % name, text, re.M) or [None, ""])[1]
              for name in ("MOUNT_PATH", "MODEL_TAG")}
    for key, env in ENV_KEYS.items():
        m = re.search(r'"%s": f?"([^"]*)",' % env, text)
        value = m.group(1) if m else None
        if value:
            for name, resolved in consts.items():
                value = value.replace("{%s}" % name, resolved)
        out[key] = value
    return out


def pin_config(**overrides):
    """Write deploy-time values into config.py. Returns the lines that changed.

    Only what you name is touched. The notebooks rewrote a fixed set on every
    run from their own configuration cell, which meant a stale copy of a
    notebook silently reverted whatever had been fixed in git since.
    """
    text = original = open(CONFIG_PATH, encoding="utf-8").read()
    changed = []
    for key, value in overrides.items():
        if value is None:
            continue
        if key in CONFIG_KEYS:
            pattern, template = CONFIG_KEYS[key]
            replacement = template % value
            text, n = re.subn(pattern, replacement.replace("\\", "\\\\"), text, flags=re.M)
        elif key in ENV_KEYS:
            # Writes a plain literal even where an f-string was there before:
            # a pinned value is a fact about this deployment, not a formula.
            replacement = '"%s": "%s",' % (ENV_KEYS[key], value)
            text, n = re.subn(r'"%s": f?"[^"]*",' % ENV_KEYS[key],
                              replacement.replace("\\", "\\\\"), text)
        else:
            raise Fatal("pin_config does not know the key %r" % key)
        if not n:
            raise Fatal("config.py has no line to set %r -- has its shape changed?" % key)
        changed.append(replacement)
    if text != original:
        open(CONFIG_PATH, "w", encoding="utf-8").write(text)
    return changed


def show_config(cfg, extra=()):
    print("  what will ship, read out of config.py:")
    for key in ("app_name", "gpu", "ui_file", "checkpoint_enabled",
                "min_containers", "max_containers", "keep_warm_seconds"):
        print("    %-22s %s" % (key, cfg.get(key)))
    print("    %-22s %s" % ("NANOCHAT_STEP",
                            cfg.get("step") or "(blank -- highest model_*.pt on the volume)"))
    print("    %-22s %s" % ("system prompt file",
                            cfg.get("system_prompt_file")
                            or "(blank -- NO PERSONA, which is not what the SFT measured)"))
    print("    %-22s %s" % ("fix punctuation", cfg.get("fix_punctuation") or "(off)"))
    for line in extra:
        print("    " + line)


# ---------------------------------------------------------------- HTTP probes

def probe(url, method="GET", body=None, origin=None, extra=None,
          timeout=300, read_bytes=8000):
    """One HTTP call, reported as data rather than as an exception.

    Every failure mode here means something different -- a DNS error is a URL
    that no longer exists, a 503 is a container that started and could not load,
    a timeout is one that never started at all -- so none of them may collapse
    into a bare traceback.
    """
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if origin:
        req.add_header("Origin", origin)
    for k, v in (extra or {}).items():
        req.add_header(k, v)

    t0 = time.perf_counter()
    try:
        res = urllib.request.urlopen(req, timeout=timeout)
        text = res.read(read_bytes).decode("utf-8", "replace")
        return dict(kind="ok", status=res.status, headers=list(res.headers.items()),
                    body=text, seconds=time.perf_counter() - t0)
    except urllib.error.HTTPError as exc:
        text = exc.read(read_bytes).decode("utf-8", "replace")
        return dict(kind="http", status=exc.code, headers=list(exc.headers.items()),
                    body=text, seconds=time.perf_counter() - t0)
    except urllib.error.URLError as exc:
        return dict(kind="network", status=None, headers=[], body="",
                    error=str(exc.reason), seconds=time.perf_counter() - t0)
    except TimeoutError as exc:
        # A read timeout, not a connect failure: the edge accepted the request
        # and held it open, but no container ever answered. Same meaning as a
        # network failure for every caller -- nothing was scheduled in time.
        return dict(kind="network", status=None, headers=[], body="",
                    error="timed out after %.0fs with no response" % (time.perf_counter() - t0),
                    seconds=time.perf_counter() - t0)
    except Exception as exc:
        return dict(kind="other", status=None, headers=[], body="",
                    error="%s: %s" % (type(exc).__name__, exc),
                    seconds=time.perf_counter() - t0)


def edge_error(result):
    """Did Beam's edge answer this, rather than the app?

    The two speak different JSON, and the key name is the whole tell:

        {"message": "..."}   Beam's routing layer -- your app was never reached
        {"detail": "..."}    FastAPI -- a live container served a route it lacks
        {"status": "error"}  app.py's own boot-error handler, with the traceback

    An edge 5xx therefore says nothing about your code. It means no container
    answered: none scheduled, or none could be created at all.
    """
    body = result.get("body") or ""
    return bool(result.get("status")) and result["status"] >= 400 and '"message"' in body


def gpu_capacity():
    """{gpu: serverless state} from `beam machine list`.

    Serverless offers a much shorter list than the on-demand price table beside
    it, and the state matters:

        ready        warm capacity, schedules immediately
        available    offered, but not necessarily schedulable right now
        (blank)      on-demand only -- a deploy naming it has nowhere to run

    `beam deploy` prints "GPU capacity for X is currently low" for the middle
    case and deploys anyway. The containers then never appear and every request
    comes back as an edge 500, which looks exactly like a broken build.
    """
    code, out = stream(["beam", "machine", "list"], quiet=True, timeout=120)
    states = {}
    if code != 0:
        return states
    for line in out.splitlines():
        cells = [c for c in re.sub(r"[^\x20-\x7e]", " ", line).split() if c]
        if len(cells) >= 2 and re.fullmatch(r"[A-Za-z0-9-]+", cells[0]):
            for word in cells[1:]:
                if word.lower() in ("ready", "available"):
                    states[cells[0]] = word.lower()
                    break
    return states


def diagnose_no_container(app_name, gpu):
    """Why did nothing answer? Called when the edge, not the app, returned 5xx."""
    rows, _ = containers()
    deps, _ = deployments(app_name)
    # Only the newest version counts. An older one can still hold a container --
    # anything that probed its -vN URL wakes it -- and counting those would
    # report capacity that the version you just deployed does not have.
    newest = deps[0]["id"] if deps else ""
    mine = [c for c in rows if field(c, "deployment_id") == newest]
    others = [c for c in rows if field(c, "deployment_id") != newest]
    states = gpu_capacity()
    state = states.get(gpu, "")

    print("  containers for v%s : %d%s"
          % (deps[0]["version"] if deps else "?", len(mine),
             "   (%d on older versions)" % len(others) if others else ""))
    print("  %s in serverless   : %s" % (gpu, state or "NOT OFFERED -- on-demand only"))
    if not mine and state != "ready":
        print()
        print("  No container exists and %s is not warm, so nothing was ever" % gpu)
        print("  scheduled -- this is capacity, not code. `beam deploy` warns")
        print("  \"GPU capacity for %s is currently low\" and deploys anyway;" % gpu)
        print("  the edge then 500s because it has nothing to route to.")
        warm = sorted(g for g, s in states.items() if s == "ready")
        if warm:
            print()
            print("  Warm in serverless right now: %s" % ", ".join(warm))
            print("  Every one of those is a consumer card, so checkpoint restore is a")
            print("  bad bet on them -- pair a switch with --no-checkpoint.")
    return len(mine)


def header_values(result, name):
    """All values for a header, duplicates included -- that is the point.

    Two Access-Control-Allow-Origin headers is a specific, real bug (the browser
    reads them as `*, *` and rejects the response), and a dict would hide it.
    """
    name = name.lower()
    return [v for k, v in result.get("headers", []) if k.lower() == name]


def show(label, result, body_chars=600):
    status = result.get("status")
    mark = "ok  " if result["kind"] == "ok" else "FAIL"
    print("%s %-34s %4s  %6.1fs  %s" % (mark, label, str(status or "-"),
                                        result["seconds"], result.get("error", "")))
    body = (result.get("body") or "").strip()
    if body and (result["kind"] != "ok" or body_chars):
        for line in body[:body_chars].splitlines():
            print("       | " + line)
        if len(body) > body_chars:
            print("       | ... (%d bytes total)" % len(body))


def stream_timing(url, body, deadline=180, label="POST"):
    """POST and report when each frame actually lands, live.

    A reply that takes minutes has three unrelated explanations and a single
    elapsed number cannot separate them:

      * nothing arrives at all, ever        -> queued behind something, or hung
      * a long silence, then a steady flow  -> a cold start you did not expect
      * a steady flow that is simply slow   -> throughput; now you have tok/s
    """
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")

    t0 = time.perf_counter()
    frames, text, err = [], [], None
    print("%s %s" % (label, url))
    print("   deadline %ss, streaming -- frames appear below as they land" % deadline)
    try:
        res = urllib.request.urlopen(req, timeout=deadline)
        print("   [%6.1fs] headers, HTTP %s" % (time.perf_counter() - t0, res.status))
        buf = b""
        while time.perf_counter() - t0 < deadline:
            chunk = res.read1(2048) if hasattr(res, "read1") else res.read(1)
            if not chunk:
                break
            now = time.perf_counter() - t0
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data: "):
                    continue
                try:
                    evt = json.loads(line[6:])
                except Exception:
                    continue
                frames.append((now, evt))
                if "token" in evt:
                    text.append(evt["token"])
                    if len(frames) <= 3 or len(frames) % 10 == 0:
                        print("   [%6.1fs] frame %3d  %r" % (now, len(frames), evt["token"]))
                elif evt.get("error"):
                    print("   [%6.1fs] SERVER ERROR: %s" % (now, evt["error"]))
                    err = evt["error"]
                elif evt.get("done"):
                    print("   [%6.1fs] done" % now)
    except urllib.error.HTTPError as exc:
        err = "HTTP %s: %s" % (exc.code, exc.read(2000).decode("utf-8", "replace"))
        print("   [%6.1fs] %s" % (time.perf_counter() - t0, err))
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, exc)
        print("   [%6.1fs] %s" % (time.perf_counter() - t0, err))

    total = time.perf_counter() - t0
    tokens = [f for f in frames if "token" in f[1]]
    ttft = tokens[0][0] if tokens else None
    rate = ""
    if len(tokens) > 1:
        span = tokens[-1][0] - tokens[0][0]
        if span > 0:
            rate = ", %.1f tok/s once flowing" % ((len(tokens) - 1) / span)
    print("   --- %d token frame(s) in %.1fs%s%s"
          % (len(tokens), total,
             (", first at %.1fs" % ttft) if ttft is not None else ", none arrived", rate))
    return dict(seconds=total, frames=frames, ttft=ttft, text="".join(text),
                error=err, timed_out=total >= deadline and not frames)


# ----------------------------------------------------------------- deployment

def native_entrypoint(entrypoint):
    """Rewrite file/obj to this platform's path separator.

    Beam turns the path into a module name with

        module_path.replace(".py", "").replace(os.path.sep, ".")

    (beta9/utils.py, load_module_spec). On Windows os.path.sep is a backslash,
    so the POSIX form every doc and runbook uses survives intact and beam tries
    to import a module literally called "dev/hosting/beam/app". The file check
    just above it uses pathlib and passes, so the error arrives as a
    ModuleNotFoundError from deep inside importlib rather than as a bad path.

    Both forms produce the same stub -- handler "dev.hosting.beam.app:handler" --
    so this changes nothing about what is deployed.
    """
    path, sep, obj = entrypoint.partition(":")
    return os.path.join(*path.split("/")) + sep + obj


def deploy(entrypoint, name, cwd=None):
    """`beam deploy`, returning (unversioned_url, output).

    The `-vN` suffix is stripped: that form freezes at one build, while the
    unversioned root follows every later deploy. The unversioned one is what
    belongs in a paper, on a site, or in <meta name="api-base">.
    """
    cwd = cwd or ROOT
    here = os.getcwd()
    os.chdir(cwd)
    try:
        code, out = stream(["beam", "deploy", native_entrypoint(entrypoint), "--name", name])
        if code != 0:
            raise Fatal("beam deploy failed. Its output is above.")
    finally:
        os.chdir(here)
    found = re.findall(r"https://[A-Za-z0-9.-]+\.app\.beam\.cloud", out)
    return (re.sub(r"-v\d+(?=\.app\.beam\.cloud)", "", found[-1]) if found else ""), out


def deployments(app_name=None):
    """Every deployment, newest version of each app first."""
    rows, raw = beam_rows(["deployment", "list"], "deployments")
    out = []
    for d in rows:
        try:
            version = int(re.sub(r"\D", "", field(d, "version", "v")) or 0)
        except ValueError:
            version = 0
        out.append(dict(
            id=field(d, "id", "deployment_id", "stub_id"),
            app_id=field(d, "app_id"),
            stub_id=field(d, "stub_id"),
            name=field(d, "name", "app_name", "stub_name"),
            version=version,
            active=field(d, "active", "status", "state"),
            raw=d))
    out.sort(key=lambda r: r["version"], reverse=True)
    if app_name:
        out = [r for r in out if r["name"] == app_name]
    return out, raw


def is_active(row):
    return str(row.get("active", "")).lower() in ("true", "yes", "active", "ready", "1")


def containers():
    return beam_rows(["container", "list"], "containers")


def _parse_iso(text):
    """Beam prints RFC3339 with a Z, which Python before 3.11 will not parse."""
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def restore_check(url, app_name, health_body=None):
    """Is the process answering older than the container it lives in?

    This is the check the notebooks did not have, and its absence is why a
    deployment configured for A10G could report RTX4090 from a container that
    passed every other test on 2026-08-20.

    Beam's memory snapshot is cached per APP NAME -- the volume it mounts is
    literally /checkpoint-model-cache-<app>, and it outlives a redeploy. So a
    new version can restore a *previous* version's process image: the same heap,
    and with it the `gpu_name` and `booted_at` that on_start recorded under
    whichever GPU that older version was deployed on. Every field /health reads
    out of on_start_value is then describing a deployment you have replaced.

    A process cannot predate its own container. `process_age_seconds` greater
    than the container's uptime is therefore proof that this container never ran
    on_start, and that everything it reports about itself is replayed memory.

    Returns a dict whose `verdict` is "booted", "restored" or "unknown".
    """
    if health_body is None:
        h = probe(url + "/health", timeout=600)
        if h["kind"] != "ok":
            return dict(verdict="unknown", why="/health did not answer 200", health=h)
        health_body = h["body"]
    try:
        info = json.loads(health_body)
    except Exception:
        return dict(verdict="unknown", why="/health body did not parse")

    age = info.get("process_age_seconds")
    if age is None:
        return dict(verdict="unknown", info=info,
                    why="this build of app.py does not report process_age_seconds")

    deps, _ = deployments(app_name)
    active_ids = {d["id"] for d in deps if is_active(d)} or {d["id"] for d in deps[:1]}
    rows, _ = containers()
    mine = [c for c in rows
            if field(c, "deployment_id") in active_ids
            and field(c, "status").upper() in ("RUNNING", "READY", "")]
    if not mine and len(rows) == 1:
        mine = rows      # one container in the whole account: no ambiguity to resolve
    if not mine:
        return dict(verdict="unknown", info=info,
                    why="no running container matched the active deployment")

    started = _parse_iso(field(mine[0], "started_at", "scheduled_at"))
    if started is None:
        return dict(verdict="unknown", info=info,
                    why="could not read started_at off the container row")
    uptime = (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds()

    # 30s of slack for clock skew between this laptop and Beam's control plane.
    # A real boot always lands well under its container's uptime, by however long
    # on_start took -- ~150s cold, or ~15s through the fast loader.
    return dict(verdict="restored" if age > uptime + 30 else "booted", info=info,
                age=age, uptime=uptime, container=mine[0],
                gpu=info.get("runtime", {}).get("gpu"),
                started_at=started.isoformat())


def print_restore_check(result, expected_gpu=None):
    """Report restore_check(), and say what to do about it. True if it is fine."""
    if result["verdict"] == "unknown":
        print("  restore check   inconclusive: %s" % result.get("why"))
        return True
    print("  process age     %.0fs" % result["age"])
    print("  container up    %.0fs  (started %s)" % (result["uptime"], result["started_at"]))
    print("  gpu reported    %s" % result["gpu"])

    if result["verdict"] == "booted":
        print("  This container really booted -- the process is younger than the")
        print("  container, so on_start ran here and /health is describing itself.")
        want = (expected_gpu or "").replace("RTX", "").strip()
        if want and want.lower() not in str(result["gpu"]).replace("RTX", "").lower():
            print("  WARN  but it booted on %s, not the %s you deployed."
                  % (result["gpu"], expected_gpu))
            return False
        return True

    print()
    print("  RESTORED, NOT BOOTED. The process is %.0fs older than the container"
          % (result["age"] - result["uptime"]))
    print("  it is running in, which is only possible if this container never ran")
    print("  on_start -- it came back from a Beam memory snapshot. Everything")
    print("  /health says about itself, the GPU name included, is replayed from")
    print("  whenever that image was captured, under whichever version was live")
    print("  then.")
    print()
    print("  That cache is keyed by app name and survives a redeploy, so deploying")
    print("  again will not clear it. Break it with:")
    print()
    print("      python dev/hosting/beam/ops/redeploy.py --bust-snapshot")
    print()
    print("  which deploys once with checkpointing off to force a real boot, then")
    print("  again with it on so the next snapshot is captured on the right GPU.")
    return False


# ------------------------------------------------------------------ the volume

def volume_state(volume, model_tag):
    """What the volume actually holds, as the loader will see it."""
    _c, ckpt = stream(["beam", "ls", "%s/%s" % (volume, model_tag)], quiet=True)
    _c2, tok = stream(["beam", "ls", "%s/%s/tokenizer" % (volume, model_tag)], quiet=True)
    _c3, root = stream(["beam", "ls", volume], quiet=True)
    models = {int(m) for m in re.findall(r"model_(\d+)\.pt", ckpt)}
    metas = {int(m) for m in re.findall(r"meta_(\d+)\.json", ckpt)}
    usable = sorted(models & metas)
    return dict(models=sorted(models), metas=sorted(metas), usable=usable,
                step=max(usable) if usable else None,
                tokenizer="tokenizer.pkl" in tok,
                persona="pre1930-companion.txt" in root,
                listings=dict(checkpoint=ckpt, tokenizer=tok, root=root))


def wait(seconds, why):
    """A visible sleep. A silent one looks like a hang."""
    print("%s -- waiting %ss" % (why, seconds))
    end = time.time() + seconds
    while True:
        left = end - time.time()
        if left <= 0:
            break
        print("\r   %5.0fs remaining " % left, end="", flush=True)
        time.sleep(min(5, left))
    print("\r   done" + " " * 20)
