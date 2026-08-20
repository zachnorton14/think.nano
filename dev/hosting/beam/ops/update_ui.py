#!/usr/bin/env python3
"""
Ship a UI change and prove the bytes you edited are the bytes being served.

    python dev/hosting/beam/ops/update_ui.py                   # deploy the configured UI
    python dev/hosting/beam/ops/update_ui.py --ui ui.html      # roll back to the first design

The local replacement for colab_update_ui.ipynb. Changing the UI needs none of
the setup: the weights stay on the volume, and the container image is cached and
keyed to the package list, which a UI edit does not change -- so the deploy is
just a file sync.

What it does cost, every time:

  * a new deployment version. The unversioned URL follows it, so a published
    link keeps working, but the previous version keeps its own containers until
    it is stopped (this stops them).
  * a fresh memory snapshot, which takes up to 3 minutes to capture and up to 5
    more to propagate. Expect ~10 minutes of slow cold starts afterwards.

For iterating on design, do it locally instead -- each pass through here costs a
version and a snapshot re-capture:

    python dev/hosting/beam/preview_ui.py            # mock server, no GPU
    python dev/hosting/beam/preview_ui.py --wake 8   # see the wake panel
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beamops as ops                                          # noqa: E402
import redeploy                                                # noqa: E402


def compare_served(url, ui_path):
    """Is the page coming back the file you edited?

    app.py reads the UI off disk once, inside on_start, so a container that was
    already running keeps serving the old bytes until it is replaced.
    """
    served = ops.probe(url + "/", timeout=300, read_bytes=2_000_000)
    if served["kind"] != "ok":
        ops.show("GET /", served, body_chars=400)
        return False
    local = open(ui_path, encoding="utf-8").read()
    same = served["body"].strip() == local.strip()
    print("  served          %d bytes" % len(served["body"]))
    print("  local file      %d bytes" % len(local))
    print("  identical       %s" % same)
    if not same:
        print("  Not identical. Usually an older container still serving the previous")
        print("  version -- wait for keep_warm_seconds to expire and re-check, or")
        print("  confirm the deploy really replaced the active version.")
    return same


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ui", dest="ui_file", help="which file to serve at GET / "
                                                "(default: UI_FILE from config.py)")
    p.add_argument("--app-name", default=None)
    p.add_argument("--site-origin", default="https://www.unboundedlab.com")
    p.add_argument("--keep-old-versions", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", "-y", action="store_true")
    args = p.parse_args(argv)

    print("=" * 70)
    print("UPDATE UI  " + ops.ROOT)
    print("=" * 70)

    head, dirty = ops.git_state()
    print("  HEAD            %s" % head)
    print("  uncommitted     %s" % ("%d file(s), which WILL be deployed" % len(dirty)
                                    if dirty else "none"))

    ops.require_beam()

    if args.ui_file:
        print()
        for line in ops.pin_config(ui_file=args.ui_file):
            print("  " + line)

    cfg = ops.read_config()
    app_name = args.app_name or cfg["app_name"]
    ui_path = os.path.join(ops.HOSTING, cfg["ui_file"])
    if not os.path.exists(ui_path):
        raise ops.Fatal("%s is not in dev/hosting/beam." % cfg["ui_file"])

    print()
    print("-- checking %s (%s bytes) %s" % (cfg["ui_file"], f"{os.path.getsize(ui_path):,}",
                                            "-" * 20))
    problems = redeploy.check_ui(ui_path, cfg["ui_file"])
    for problem in problems:
        print("  FAIL  " + problem)
    if problems:
        raise ops.Fatal("A blank page after a deploy is a miserable way to find a typo.")
    print("  ok    tags balanced, every id the JS reaches for exists, JS parses")

    if args.dry_run:
        print("\n--dry-run: nothing deployed.")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            raise ops.Fatal("Not a terminal. Pass --yes to proceed.")
        if input("\nDeploy %s? [y/N] " % cfg["ui_file"]).strip().lower() not in ("y", "yes"):
            print("Nothing deployed.")
            return 1

    ops.ensure_beamignore()
    url, _ = ops.deploy(redeploy.ENTRYPOINT, app_name)
    print()
    print("=" * 70)
    print("APP URL: %s" % (url or "NOT FOUND -- read it off the output above"))
    print("=" * 70)
    if not url:
        return 1

    print()
    print("-- is the new UI actually being served? " + "-" * 27)
    ok = compare_served(url, ui_path)
    ok = redeploy.verify(url, app_name, cfg, args.site_origin) and ok

    if not args.keep_old_versions:
        print()
        print("-- older versions " + "-" * 49)
        redeploy.stop_old_versions(app_name)

    print()
    print("=" * 70)
    print("%s   %s" % ("PASSED" if ok else "PROBLEMS ABOVE", url))
    print("=" * 70)
    print("Cold starts will be slow for ~10 minutes while the new snapshot captures")
    print("and propagates. If someone is about to look at it, warm it first:")
    print("    curl -s %s/health > /dev/null" % url)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
