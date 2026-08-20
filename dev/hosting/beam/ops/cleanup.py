#!/usr/bin/env python3
"""
Clean up the Beam account. Prints the plan and stops; --execute to act.

    python dev/hosting/beam/ops/cleanup.py                 # the plan, nothing else
    python dev/hosting/beam/ops/cleanup.py --execute       # do it

The local replacement for colab_beam_cleanup.ipynb.

    keep               the think-nano-weights volume
    stop, not delete   every version of the app named by --preserve-url-for
    delete             everything else: old app names, probes, all their versions

The middle row is the one to understand before running this. Stopping a version
kills its containers -- which is exactly what frees one stuck holding an
in-flight request. *Deleting* every version of an app risks taking the app with
it, and the public hostname is derived from the app, so that is what turns a
redeploy into a new URL and a dead link on your own site. Stopping gets you the
fix; deleting gets you the fix plus a URL change you did not ask for.

That split is the whole answer to "is it easier to just delete it?" -- for
deployments, yes. For the volume, no: it holds 5.25 GiB that cost an 8.4 GiB
download, an export and an upload to put there, and none of the symptoms you are
chasing are caused by a volume that lists correctly. This proves it lists
correctly *before* deleting anything, and only removes it behind --delete-volume
naming it exactly.

Why clutter is not merely cosmetic: every deploy leaves the previous version live
with its own containers and its own warm state, each holding a share of the
account's GPU concurrency that a new container has to schedule against, each
billing while it idles, and each making `beam logs` ambiguous.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beamops as ops                                          # noqa: E402


def inventory():
    """Everything the account is holding, which the dashboard makes hard to read."""
    out = {}
    for what in ("deployment", "pod", "volume", "task", "container"):
        rows, raw = ops.beam_rows([what, "list"], what)
        out[what] = rows
        print("  %-12s %d" % (what + "s", len(rows)))
    pending = [t for t in out["task"]
               if ops.field(t, "status", "state").upper() in ("PENDING", "RUNNING", "QUEUED")]
    if pending:
        # With tasks_per_container = 1, requests stacked behind a task that never
        # finished are indistinguishable, from a browser, from a broken model.
        print("\n  NOTE  %d task(s) are PENDING/RUNNING. If they belong to a deployment"
              % len(pending))
        print("        you are about to delete they go with it; if they belong to the")
        print("        one you are keeping, they sit ahead of every new request.")
    return out


def prove_weights(volume, model_tag):
    """Confirm what is on the volume while the deployments still exist.

    The order matters: if this reports the checkpoint missing, you have learned
    the actual cause of the outage rather than having just deleted the evidence.
    """
    vol = ops.volume_state(volume, model_tag)
    print("  model_*.pt      %s" % (vol["models"] or "MISSING"))
    print("  meta_*.json     %s" % (vol["metas"] or "MISSING"))
    print("  tokenizer.pkl   %s" % ("present" if vol["tokenizer"] else "MISSING"))
    print("  persona file    %s" % ("present" if vol["persona"]
                                    else "missing (would serve without one)"))
    print("  usable step     %s" % vol["step"])
    ok = vol["step"] is not None and vol["tokenizer"]
    print()
    if ok:
        print("  WEIGHTS OK -- the volume is complete, so deleting deployments is safe")
        print("  and a redeploy will find everything it needs.")
    else:
        print("  WEIGHTS INCOMPLETE. This alone would explain the container errors: the")
        print("  loader raises FileNotFoundError in on_start and every request after it")
        print("  fails. Do not delete the volume. Rebuild it with")
        print("      python dev/hosting/beam/ops/deploy.py --force-reprep")
    return ok


def build_plan(deps, keep, preserve, delete):
    targets, unparsed = [], 0
    for d in deps:
        if not d["id"]:
            unparsed += 1
            continue
        if d["name"] in keep:
            action = "KEEP"
        elif d["name"] in preserve:
            action = "stop only (keeps the URL)"
        else:
            action = "stop + delete" if delete else "stop"
        targets.append(dict(d, action=action))
    return targets, unparsed


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preserve-url-for", nargs="*", default=None,
                   help="app names to stop but never delete (default: APP_NAME from config.py)")
    p.add_argument("--keep", nargs="*", default=[],
                   help="app names to leave running entirely")
    p.add_argument("--no-delete", dest="delete", action="store_false",
                   help="stop everything, delete nothing (reversible with deployment start)")
    p.add_argument("--volume", default="think-nano-weights")
    p.add_argument("--model-tag", default=None)
    p.add_argument("--delete-volume", default="",
                   help="type the volume name exactly to delete it. You almost certainly "
                        "do not want to.")
    p.add_argument("--execute", action="store_true", help="actually do it")
    args = p.parse_args(argv)

    cfg = ops.read_config()
    preserve = args.preserve_url_for if args.preserve_url_for is not None else [cfg["app_name"]]
    model_tag = args.model_tag or re.search(
        r'^MODEL_TAG = "([^"]+)"', open(ops.CONFIG_PATH, encoding="utf-8").read(), re.M).group(1)
    ops.require_beam()

    print("=" * 70)
    print("INVENTORY")
    print("=" * 70)
    stuff = inventory()

    print()
    print("=" * 70)
    print("ARE THE WEIGHTS INTACT? (before anything is deleted)")
    print("=" * 70)
    weights_ok = prove_weights(args.volume, model_tag)

    deps, _ = ops.deployments()
    targets, unparsed = build_plan(deps, args.keep, preserve, args.delete)

    print()
    print("=" * 70)
    print("THE PLAN")
    print("=" * 70)
    print("%-22s%-5s%-9s%-38saction" % ("name", "ver", "active", "id"))
    print("-" * 100)
    for t in targets:
        print("%-22s%-5s%-9s%-38s%s" % (t["name"][:21], t["version"], t["active"][:8],
                                        t["id"], t["action"]))
    doomed = [t for t in targets if t["action"] != "KEEP"]
    to_delete = [t for t in doomed if t["action"].startswith("stop + delete")]
    print()
    print("%d deployment(s) to act on: %d deleted, %d stopped only."
          % (len(doomed), len(to_delete), len(doomed) - len(to_delete)))
    if preserve:
        print("App(s) kept so the URL survives: %s" % ", ".join(preserve))
        print("  Their containers stop -- which is the point -- but the app is not")
        print("  deleted, so a redeploy should come back on the same hostname.")
    if unparsed:
        print("%d row(s) had no readable id; handle those by hand." % unparsed)
    print("The %s volume is NOT touched here." % args.volume)

    if not args.execute:
        print()
        print("Nothing done. Re-run with --execute to carry this out.")
        return 0
    if not weights_ok:
        raise ops.Fatal("Refusing to --execute while the volume looks incomplete. "
                        "Rebuild it first, or re-run with the volume proved good.")

    print()
    print("=" * 70)
    print("EXECUTING")
    print("=" * 70)
    # Stop before delete on purpose: a stop takes effect immediately, so a delete
    # that is refused (a container still draining, say) still leaves the
    # deployment inert rather than half-handled.
    failures = []
    for t in doomed:
        print("--- %s v%s (%s)  [%s]" % (t["name"], t["version"], t["id"], t["action"]))
        code, _ = ops.stream(["beam", "deployment", "stop", t["id"]], timeout=120)
        if code != 0:
            print("    stop failed (often just \"already stopped\")")
        if t["action"].startswith("stop + delete"):
            code, out = ops.stream(["beam", "deployment", "delete", t["id"]], timeout=120)
            if code != 0:
                failures.append((t, (out.strip().splitlines() or [""])[-1]))
        print()

    print("=" * 70)
    print("%d/%d handled." % (len(doomed) - len(failures), len(doomed)))
    for t, msg in failures:
        print("  FAILED  %s %s: %s" % (t["name"], t["id"], msg))
    if failures:
        print("\nDelete those from the dashboard, or leave them stopped -- a stopped")
        print("deployment costs nothing and cannot answer a request.")

    if args.delete_volume:
        if args.delete_volume != args.volume:
            print("\n--delete-volume must name the volume exactly. Not armed.")
        else:
            print("\nDeleting the volume. Rebuild with deploy.py --force-reprep.")
            ops.stream(["beam", "volume", "delete", args.volume])

    print()
    print("=" * 70)
    print("THE ACCOUNT NOW")
    print("=" * 70)
    ops.stream(["beam", "deployment", "list"])
    ops.stream(["beam", "volume", "list"])
    print()
    print("Next: python dev/hosting/beam/ops/redeploy.py")
    print("Check the URL it prints against the one on your site -- with the app")
    print("preserved it should come back unchanged, but the hostname suffix is not")
    print("derivable from anything the CLI exposes, so read it rather than assume.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
