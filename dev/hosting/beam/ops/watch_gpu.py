#!/usr/bin/env python3
"""
Wait for serverless GPU capacity, and say so the moment it arrives.

    python dev/hosting/beam/ops/watch_gpu.py --once     # check now, exit 0 if ready
    python dev/hosting/beam/ops/watch_gpu.py            # poll until ready
    python dev/hosting/beam/ops/watch_gpu.py --then-redeploy --checkpoint

Two signals, and the second is the one that matters.

**`beam machine list`** has a Serverless column with three states. `ready` means
warm capacity that schedules immediately; `available` means the type is offered
but constrained -- `beam deploy` prints "GPU capacity for X is currently low",
deploys anyway, and every request comes back as an edge 500 with no container
ever created; blank means on-demand only, and a deploy naming it can never be
scheduled at all. The control plane calls these `available` / `low` / `none`
and returns one on stub creation (`beta9/abstractions/base/capacity.py`).

**The live deployment**, if it is already configured for the GPU you are waiting
on. That is the definitive test and it costs nothing: an active version with
`min_containers = 0` schedules on the first request, so `/health` answering 200
means capacity arrived, and an edge 500 means it has not. Nothing needs
redeploying when it does -- the version is already there and starts working on
its own.

So: if a deploy on the GPU you want is already active, this watches that. It
falls back to the machine list if there is nothing deployed to ask.
"""

import argparse
import datetime
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beamops as ops                                          # noqa: E402


def hostname_is_real(url):
    """Does anything own this hostname?

    Beam's edge answers 404 {"message": ...} for a hostname with no deployment
    behind it, and it answers OPTIONS with CORS headers for *any* name under
    app.beam.cloud, so a preflight proves nothing. Only the 404-shape does.

    A 500 passes this deliberately: that is a real hostname whose routing found
    no container, which is precisely the state being waited out.
    """
    r = ops.probe(url + "/__beam_existence_probe__", timeout=90)
    return not (r.get("status") == 404 and '"message"' in (r.get("body") or ""))


def discover_url(app_name):
    """The unversioned URL, verified rather than derived.

    The hostname suffix is NOT derivable from anything the CLI exposes -- not
    the deployment id, not the stub id, not the app id (hosting.md says so, and
    building one from app_id yields a hostname that 404s). So: take the URLs
    that are written down, and confirm one of them is real.
    """
    candidates = []
    _deps, raw = ops.deployments(app_name)
    for url in re.findall(r"https://[A-Za-z0-9.-]+\.app\.beam\.cloud", raw):
        candidates.append(re.sub(r"-v\d+(?=\.app\.beam\.cloud)", "", url))
    # The repo writes the real one down in two places; prefer those over a guess.
    for doc in ("dev/hosting/hosting.md", "dev/hosting/beam/RUNBOOK.md"):
        path = os.path.join(ops.ROOT, doc)
        if not os.path.exists(path):
            continue
        for url in re.findall(r"https://%s-[a-z0-9]+\.app\.beam\.cloud" % re.escape(app_name),
                              open(path, encoding="utf-8").read()):
            candidates.append(re.sub(r"-v\d+(?=\.app\.beam\.cloud)", "", url))

    seen = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        if hostname_is_real(url):
            return url
    return ""


def check(gpu, url):
    """One poll. Returns (verdict, description) where verdict is
    "ready", "waiting" or "bad-url"."""
    states = ops.gpu_capacity()
    state = states.get(gpu, "")
    warm = sorted(g for g, s in states.items() if s == "ready")
    parts = ["%s=%s" % (gpu, state or "not offered")]
    if warm:
        parts.append("warm: " + ",".join(warm))

    if not url:
        return ("ready" if state == "ready" else "waiting"), "  ".join(parts)

    r = ops.probe(url + "/health", timeout=600)
    if r["kind"] == "ok":
        return "ready", "  ".join(parts + ["/health 200 -- a container is running"])
    if r.get("status") == 404 and '"message"' in (r.get("body") or ""):
        # An edge 404 is a hostname with nothing behind it, which says nothing
        # about capacity. Reporting it as "waiting" would wait forever.
        return "bad-url", "  ".join(parts + ["/health 404 from the edge -- WRONG HOSTNAME"])
    if ops.edge_error(r):
        return "waiting", "  ".join(parts + ["/health %s from the edge -- nothing scheduled"
                                             % r.get("status")])
    # Anything the app itself answered means a container exists: capacity is
    # there, and the problem has moved on to something else entirely.
    return "ready", "  ".join(parts + ["/health %s from the app, not the edge -- a "
                                       "container is up but unhealthy" % r.get("status")])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gpu", default=None, help="default: GPU from config.py")
    p.add_argument("--url", default=None,
                   help="the deployment to watch (default: discovered from the app)")
    p.add_argument("--app-name", default=None)
    p.add_argument("--interval", type=int, default=180, help="seconds between polls")
    p.add_argument("--timeout", type=int, default=0, help="give up after N minutes (0 = never)")
    p.add_argument("--once", action="store_true", help="check once and exit")
    p.add_argument("--then-redeploy", action="store_true",
                   help="run redeploy.py --yes once capacity arrives; any remaining "
                        "arguments are passed through to it")
    args, passthrough = p.parse_known_args(argv)

    cfg = ops.read_config()
    gpu = args.gpu or cfg["gpu"]
    app_name = args.app_name or cfg["app_name"]
    ops.require_beam()

    url = args.url
    if url is None:
        url = discover_url(app_name)
    if url:
        deps, _ = ops.deployments(app_name)
        newest = deps[0]["version"] if deps else "?"
        print("watching %s (newest version v%s) for %s capacity" % (url, newest, gpu))
        print("NOTE  this only answers the question if that version is deployed on %s." % gpu)
    else:
        print("no deployment found to probe; falling back to `beam machine list` alone")
    print("polling every %ss -- Ctrl-C to stop\n" % args.interval)

    deadline = time.time() + args.timeout * 60 if args.timeout else None
    while True:
        verdict, detail = check(gpu, url)
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        print("%s  %-6s %s" % (stamp, verdict, detail))

        if verdict == "bad-url":
            raise ops.Fatal(
                "That hostname has no deployment behind it, so this is watching the\n"
                "wrong thing -- and would have waited forever. Pass the URL you have\n"
                "actually been opening with --url.")
        if verdict == "ready":
            print()
            print("=" * 70)
            print("%s HAS CAPACITY" % gpu)
            print("=" * 70)
            if url:
                print("The active version is already configured for it, so it is serving")
                print("again on its own: %s" % url)
            if args.then_redeploy:
                cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "redeploy.py"), "--yes"] + passthrough
                print("\nrunning: %s\n" % " ".join(cmd))
                return subprocess.call(cmd)
            return 0

        if args.once:
            return 1
        if deadline and time.time() > deadline:
            print("\ngave up after %d minutes." % args.timeout)
            return 1
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped.")
        sys.exit(130)
