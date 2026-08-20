#!/usr/bin/env python3
"""
Redeploy bartholomew-iii from this working tree, and verify it before trusting it.

    python dev/hosting/beam/ops/redeploy.py                  # deploy and check
    python dev/hosting/beam/ops/redeploy.py --bust-snapshot  # ...and force a real boot
    python dev/hosting/beam/ops/redeploy.py --dry-run        # show what would ship

The local replacement for colab_beam_redeploy.ipynb. It does the same thing and
refuses in the same places, with three changes:

  * it deploys THIS tree, not a fresh clone of origin/<branch>, so uncommitted
    work ships and is reported before it does;
  * config.py is the authority. Nothing is rewritten unless you pass the flag
    for it. The notebook rewrote GPU, UI_FILE, the step and the persona path on
    every run out of its own configuration cell, which is how a Colab copy saved
    before the A10G fix redeployed RTX4090 on top of corrected code;
  * after deploying it compares the serving process's age against its own
    container's uptime. A process cannot predate its container, and that is the
    only externally visible proof that a container booted rather than being
    restored from a stale memory snapshot.

Needs `beam` on PATH and authenticated:

    uv tool install beam-client
    beam configure default --token <token from the Beam dashboard>
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beamops as ops                                          # noqa: E402

# The root-level shim, not dev/hosting/beam/app.py itself: the SDK records the
# handler and on_start by the DEFINING file's path relative to the cwd, and on
# Windows that path has backslashes -- a module name the Linux container cannot
# import (every task cancels before the app exists; v9, 2026-08-20). A root
# file has no separators to mangle, so it deploys identically from every OS.
ENTRYPOINT = "beam_app.py:handler"
PROBE_ENTRYPOINT = "beam_app.py:probe_handler"


# ----------------------------------------------------------------- preflight

def preflight(cfg):
    """Everything that costs nothing and would waste a deploy if wrong."""
    problems = []
    ui_file = cfg["ui_file"]

    required = ["app.py", "config.py", "conversation.py", "fast_load.py",
                "beamignore.template", ui_file]
    missing = [f for f in required if not os.path.exists(os.path.join(ops.HOSTING, f))]
    if missing:
        problems.append("not in dev/hosting/beam: " + ", ".join(missing))

    # The deploy entrypoint. It must sit at the repo root and it must DEFINE the
    # handler; importing one from dev/hosting/beam would put the Windows
    # backslash path right back into the stub.
    shim = os.path.join(ops.ROOT, ENTRYPOINT.split(":")[0])
    if not os.path.exists(shim):
        problems.append("%s is missing at the repo root -- the deploy entrypoint" % ENTRYPOINT.split(":")[0])
    else:
        shim_src = open(shim, encoding="utf-8").read()
        for name in ("def handler", "def probe_handler", "def load_engine"):
            if name not in shim_src:
                problems.append("beam_app.py no longer defines %s()" % name.split()[1])

    # The boot-error patch. Without it a failed load is invisible again: every
    # request dies deep inside a route instead of /health serving the traceback.
    if "app.py" not in missing:
        app_src = open(os.path.join(ops.HOSTING, "app.py"), encoding="utf-8").read()
        if "boot_error" not in app_src:
            problems.append("app.py predates the boot-error patch -- a failed on_start "
                            "would be invisible again")

    if ui_file not in missing:
        problems += check_ui(os.path.join(ops.HOSTING, ui_file), ui_file)

    # .beamignore must not exclude anything the container imports or serves.
    ignore = open(os.path.join(ops.HOSTING, "beamignore.template"), encoding="utf-8").read()
    for needed in ("*.html", "*.py", "dev/hosting", "nanochat"):
        if any(line.strip() == needed for line in ignore.splitlines()):
            problems.append(".beamignore excludes %s, which the container needs" % needed)

    for p in problems:
        print("  FAIL  " + p)
    if problems:
        raise ops.Fatal("Preflight failed -- fix the above before deploying.")
    print("  ok    files, boot-error patch, UI, .beamignore")


def check_ui(path, label):
    """The UI failures that leave a page which renders and never works."""
    problems = []
    html = open(path, encoding="utf-8").read()
    if html.count("<script") != html.count("</script>"):
        problems.append("%s has unbalanced <script> tags" % label)

    ids = set(re.findall(r'\bid="([^"]+)"', html))
    used = set(re.findall(r'el\("([^"]+)"\)', html)) | set(re.findall(r'rows\("([^"]+)"', html))
    used |= {c + s for c in ("temp", "topk", "maxtok") for s in ("", "-v")}
    for m in sorted(used - ids):
        problems.append("%s: JS references #%s, which is not in the markup" % (label, m))

    # Actually parse the JavaScript. Balanced tags and resolvable ids say nothing
    # about whether the script runs: one bad string literal is a parse error that
    # kills the whole <script> block, so no JS runs at all. The page still
    # renders -- it is static HTML and CSS -- so it looks deployed and is merely
    # inert, with the composer stuck on its "Waiting for the model..." placeholder
    # and nothing ever calling /health.
    import tempfile
    js_path = os.path.join(tempfile.gettempdir(), "_ui_check.js")
    for block in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S):
        if not block.strip():
            continue
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(block)
        code, out = ops.stream(["node", "--check", js_path], quiet=True, timeout=30)
        if code == 0:
            continue
        if "not found" in out.lower() or code == 127:
            print("  WARN  node is unavailable, so %s's JavaScript was NOT parsed." % label)
            break
        problems.append("%s has a JavaScript syntax error -- the whole <script> block "
                        "would fail to run, leaving a page that renders but never "
                        "contacts the model:\n      %s" % (label, out.strip()))
    return problems


def check_against_volume(cfg, vol):
    """Refuse a deploy the volume cannot serve.

    The container reads all three of these by path, and each missing one is a
    FileNotFoundError inside on_start rather than anything visible from here.
    """
    if not vol["usable"]:
        raise ops.Fatal(
            "No step under the volume has BOTH a model_*.pt and a meta_*.json.\n"
            "Rebuild it:  python dev/hosting/beam/ops/deploy.py --force-reprep")
    if not vol["tokenizer"]:
        raise ops.Fatal("No tokenizer.pkl on the volume -- the loader cannot start.")

    step = (cfg["step"] or "").strip()
    if step and int(step) not in vol["usable"]:
        raise ops.Fatal(
            "config.py pins NANOCHAT_STEP = %s, which is not on the volume.\n"
            "Usable steps: %s\n"
            "Fix it with --step %d, or --step auto to take the newest."
            % (step, vol["usable"], vol["step"]))

    persona = (cfg["system_prompt_file"] or "").strip()
    if persona and not vol["persona"]:
        raise ops.Fatal(
            "config.py points NANOCHAT_SYSTEM_PROMPT_FILE at %s, which is not on\n"
            "the volume -- on_start would raise. Upload it, or pass --persona none."
            % persona)
    if not persona:
        print("  WARN  no system prompt configured. The C3-robust SFT was trained with")
        print("        one, so this serves a different model than your evals measured.")
        print("        --persona /vol/model/pre1930-companion.txt sets it.")


# -------------------------------------------------------------------- verify

def verify(url, app_name, cfg, site_origin):
    """Everything that decides whether this deploy actually worked."""
    ok = True

    print()
    print("-- /health " + "-" * 55)
    health = ops.probe(url + "/health", timeout=600)
    ops.show("GET /health", health, body_chars=4000)
    if health["kind"] != "ok":
        if ops.edge_error(health) or health["kind"] == "network":
            # Beam's edge answered (or nothing answered at all), so the app was
            # never reached and nothing here describes your code.
            ops.diagnose_no_container(app_name, cfg["gpu"])
            raise ops.Fatal(
                "No container answered (%s). That came from Beam's edge or from a\n"
                "timeout, not from app.py -- the reasons are above, and none of\n"
                "them are the build."
                % (health.get("status") or health.get("error")))
        detail = health.get("body", "")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("error") or parsed.get("detail") or detail
        except Exception:
            pass
        raise ops.Fatal(
            "The deployment is up but cannot serve. With the boot-error patch in\n"
            "place a 503 body is the on_start traceback and its last line names\n"
            "the failure:\n\n" + str(detail)[-2000:])

    info = json.loads(health["body"])
    runtime, model = info.get("runtime", {}), info.get("model", {})
    print()
    print("  step            %s" % model.get("step"))
    print("  dtype           %s" % runtime.get("compute_dtype"))
    print("  vram            %s GiB" % runtime.get("vram_gib"))
    print("  boot            %ss" % runtime.get("boot_seconds"))
    if runtime.get("compute_dtype") != "torch.bfloat16":
        print("  WARN  not bf16 -- this GPU lacks bf16 tensor cores; change GPU.")
        ok = False
    if (runtime.get("vram_gib") or 0) > 7:
        print("  WARN  above the ~5.25 GiB a bf16 export needs; check the volume.")

    # The check that catches a container serving a previous version's process.
    ok = ops.print_restore_check(
        ops.restore_check(url, app_name, health_body=health["body"]),
        expected_gpu=cfg["gpu"]) and ok

    print()
    print("-- streaming and generation " + "-" * 39)
    sp = ops.probe(url + "/stream-probe", timeout=120, read_bytes=4000)
    ops.show("GET /stream-probe", sp, body_chars=0)
    frames = sp.get("body", "").count("data: ")
    print("       %d SSE frame(s) in the first 4 KB (the route emits 7 over ~3s)" % frames)
    if sp["kind"] == "ok" and frames < 2:
        print("       Buffered somewhere. Not fatal -- the UI falls back to stream:false --")
        print("       but every reply then arrives in one lump after a long pause.")

    gen = ops.stream_timing(url + "/chat/completions", {
        "messages": [{"role": "user", "content": "What is the wireless telegraph?"}],
        "max_tokens": 16, "stream": True}, deadline=180,
        label="POST /chat/completions")
    if gen["error"] or not gen["frames"]:
        print("  Generation failed. /health answering while this hangs is the")
        print("  signature of a container restored with a dead CUDA context.")
        ok = False
    else:
        print("  Generation works: %r" % gen["text"])

    print()
    print("-- CORS, for the copy of the page on your own site " + "-" * 16)
    pre = ops.probe(url + "/chat/completions", method="OPTIONS", timeout=60, extra={
        "Origin": site_origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    ops.show("OPTIONS /chat/completions", pre, body_chars=0)
    acao = ops.header_values(pre, "access-control-allow-origin")
    acam = ops.header_values(pre, "access-control-allow-methods")
    print("  Access-Control-Allow-Origin  : %s" % (acao or "ABSENT"))
    print("  Access-Control-Allow-Methods : %s" % (acam or "ABSENT"))
    if len(acao) > 1:
        # Two of them read as "*, *" to a browser, which rejects the response.
        print("  FAIL  two Allow-Origin headers. Something is adding CORS on top of")
        print("        Beam's proxy -- check CORSMiddleware has not gone back into app.py.")
        ok = False
    elif not acao:
        print("  FAIL  no Allow-Origin at all. Serve the page from Beam itself until")
        print("        this comes back, and do NOT add CORSMiddleware to app.py: that")
        print("        is what produced the doubled header. Ask Beam.")
        ok = False
    elif acao[0] not in ("*", site_origin):
        print("  FAIL  Allow-Origin is %r, which does not cover %s" % (acao[0], site_origin))
        ok = False
    else:
        print("  ok    point your site at it with:")
        print('        <meta name="api-base" content="%s">' % url)
    return ok


def cold_start_test(url, app_name, cfg):
    """Idle the container out and take the boot your readers will really get.

    The failure that takes this deployment down arrives on the SECOND boot, not
    the first: a fresh deploy always boots for real, and only a later cold start
    goes through the restore path. Nothing else here exercises it.
    """
    keep_warm = int(cfg["keep_warm_seconds"] or 600)
    if int(cfg["min_containers"] or 0) > 0:
        print("  MIN_CONTAINERS > 0, so a container is always up and nothing ever cold")
        print("  starts. That is a real fix for this failure, not a way around the test.")
        return True

    print("  Do not open the page while this runs -- a request resets the window.")
    ops.wait(keep_warm + 120, "letting the container idle out (keep_warm %ds + 2 min)" % keep_warm)

    print()
    print("=" * 66)
    print("COLD START -- the boot that has been failing")
    print("=" * 66)
    cold = ops.probe(url + "/health", timeout=420)
    ops.show("GET /health (cold)", cold, body_chars=1500)
    if cold["kind"] != "ok":
        print("  The cold start failed -- which is the bug, now reproduced. If the body")
        print("  says the GPU is not responding, a restored snapshot is the cause.")
        return False

    ok = ops.print_restore_check(
        ops.restore_check(url, app_name, health_body=cold["body"]), expected_gpu=cfg["gpu"])

    gen = ops.stream_timing(url + "/chat/completions", {
        "messages": [{"role": "user", "content": "What is the wireless telegraph?"}],
        "max_tokens": 16, "stream": True}, deadline=180,
        label="POST /chat/completions (on the cold container)")
    if not gen["frames"] or gen["error"]:
        print("  Generation failed on a cold container -- the original bug.")
        return False
    return ok


def stop_old_versions(app_name):
    """Every deploy leaves the previous version holding its own containers.

    The unversioned URL only warms the newest, so anything older is paying to be
    warm for nobody -- and holding account GPU concurrency the new one needs.
    """
    deps, raw = ops.deployments(app_name)
    if len(deps) < 2:
        print("  no older versions of %s" % app_name)
        return
    for d in deps[1:]:
        if not ops.is_active(d):
            continue
        print("  stopping v%s  %s" % (d["version"], d["id"]))
        ops.stream(["beam", "deployment", "stop", d["id"]], quiet=True, timeout=120)
    print("  `beam deployment start <id>` brings one back to roll back to it.")


# ----------------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Redeploy and verify the Beam deployment from this working tree.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--app-name", default=None,
                   help="deployment name (default: APP_NAME from config.py)")
    p.add_argument("--volume", default="think-nano-weights")
    p.add_argument("--model-tag", default=None,
                   help="default: MODEL_TAG from config.py")
    p.add_argument("--site-origin", default="https://www.unboundedlab.com",
                   help="origin the CORS probes pretend to come from")

    pin = p.add_argument_group(
        "config.py overrides",
        "Each writes into config.py and stays there. Without one, the committed "
        "value ships unchanged -- which is the point.")
    pin.add_argument("--gpu", help='e.g. A10G. Not RTX4090: checkpoint restore is broken there')
    pin.add_argument("--ui", dest="ui_file", help="ui_updated.html or ui.html")
    pin.add_argument("--step", help='an exact step, or "auto" for the newest on the volume')
    pin.add_argument("--persona", help='path on the volume, or "none" to serve without one')
    pin.add_argument("--fix-punctuation", choices=("on", "off"),
                     help="append a period to visitor turns that end without punctuation "
                          "(nanochat/prompt_shaping.py). Free: no extra context, no extra "
                          "latency, and nothing the visitor typed is edited")
    pin.add_argument("--priming-turns",
                     help='"default" for the built-in exchange, a path on the volume, '
                          'or "off". Costs ~40-80 tokens of context per request')
    pin.add_argument("--min-containers", type=int)
    pin.add_argument("--keep-warm", type=int, dest="keep_warm_seconds")
    pin.add_argument("--checkpoint", dest="checkpoint", action="store_true", default=None)
    pin.add_argument("--no-checkpoint", dest="checkpoint", action="store_false")

    p.add_argument("--bust-snapshot", action="store_true",
                   help="deploy twice: once with checkpointing off to force a real boot "
                        "and discard the cached process image, then again with it on")
    p.add_argument("--cold-start-test", action="store_true",
                   help="idle the container out afterwards and measure the restore path "
                        "(adds keep_warm + 2 min)")
    p.add_argument("--keep-old-versions", action="store_true",
                   help="do not stop the previous versions")
    p.add_argument("--dry-run", action="store_true", help="check everything, deploy nothing")
    p.add_argument("--yes", "-y", action="store_true", help="do not ask before deploying")
    args = p.parse_args(argv)

    print("=" * 70)
    print("REDEPLOY  " + ops.ROOT)
    print("=" * 70)

    head, dirty = ops.git_state()
    print("  HEAD            %s" % head)
    if dirty:
        # beam deploy syncs the working directory, so these ship. That is the
        # difference between this and the notebook, and it is worth seeing.
        print("  uncommitted     %d file(s) -- THESE WILL BE DEPLOYED:" % len(dirty))
        for f in dirty[:15]:
            print("                  " + f)
        if len(dirty) > 15:
            print("                  ... and %d more" % (len(dirty) - 15))
    else:
        print("  uncommitted     none")

    ops.require_beam()

    # --- config, and the overrides that change it -----------------------------
    cfg = ops.read_config()
    app_name = args.app_name or cfg["app_name"]
    model_tag = args.model_tag or re.search(
        r'^MODEL_TAG = "([^"]+)"', open(ops.CONFIG_PATH, encoding="utf-8").read(), re.M).group(1)

    print()
    print("-- the volume " + "-" * 53)
    vol = ops.volume_state(args.volume, model_tag)
    print("  usable steps    %s" % (vol["usable"] or "NONE"))
    print("  tokenizer.pkl   %s" % ("present" if vol["tokenizer"] else "MISSING"))
    print("  persona file    %s" % ("present" if vol["persona"] else "missing"))

    overrides = {}
    if args.gpu:
        overrides["gpu"] = args.gpu
    if args.ui_file:
        overrides["ui_file"] = args.ui_file
    if args.min_containers is not None:
        overrides["min_containers"] = args.min_containers
    if args.keep_warm_seconds is not None:
        overrides["keep_warm_seconds"] = args.keep_warm_seconds
    if args.checkpoint is not None:
        overrides["checkpoint_enabled"] = args.checkpoint
    if args.step:
        if args.step == "auto":
            if vol["step"] is None:
                raise ops.Fatal("--step auto needs a usable step on the volume; found none.")
            overrides["step"] = vol["step"]
        else:
            overrides["step"] = int(args.step)
    if args.persona:
        overrides["system_prompt_file"] = "" if args.persona == "none" else args.persona
    if args.fix_punctuation:
        overrides["fix_punctuation"] = "1" if args.fix_punctuation == "on" else ""
    if args.priming_turns:
        overrides["priming_turns"] = "" if args.priming_turns == "off" else args.priming_turns

    if overrides:
        print()
        print("-- writing to config.py " + "-" * 43)
        for line in ops.pin_config(**overrides):
            print("  " + line)
        cfg = ops.read_config()

    print()
    print("-- preflight " + "-" * 54)
    preflight(cfg)
    check_against_volume(cfg, vol)

    print()
    ops.show_config(cfg, extra=["deploying as       %s" % app_name])

    if args.dry_run:
        print()
        print("--dry-run: nothing deployed.")
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            raise ops.Fatal("Not a terminal, so nothing was deployed. Pass --yes to proceed.")
        answer = input("\nDeploy this? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Nothing deployed.")
            return 1

    ops.ensure_beamignore()

    # --- deploy ---------------------------------------------------------------
    original_checkpoint = cfg["checkpoint_enabled"]
    reverted = True
    try:
        if args.bust_snapshot and original_checkpoint != "False":
            print()
            print("=" * 70)
            print("PASS 1 of 2 -- checkpointing OFF, to force a real boot")
            print("=" * 70)
            print("Beam caches the memory snapshot per app name, on the volume it mounts")
            print("at /checkpoint-model-cache-%s, and that cache outlives a" % app_name)
            print("redeploy. Deploying with it off is what makes the next container run")
            print("on_start for real instead of replaying a previous version's process.")
            print()
            ops.pin_config(checkpoint_enabled=False)
            reverted = False
            url, _ = ops.deploy(ENTRYPOINT, app_name)
            print("\n  URL: %s" % (url or "NOT FOUND -- read it off the output above"))
            if not url:
                raise ops.Fatal("No URL in the deploy output; cannot verify pass 1.")

            print("\n  waking it (a boot without the snapshot takes ~25s) ...")
            health = ops.probe(url + "/health", timeout=600)
            ops.show("GET /health", health, body_chars=1500)
            if health["kind"] != "ok":
                if ops.edge_error(health):
                    ops.diagnose_no_container(app_name, cfg["gpu"])
                    raise ops.Fatal(
                        "Pass 1 never got a container, so nothing was proved about the\n"
                        "snapshot either way. The previous version is still serving its\n"
                        "own -vN URL; the unversioned one now points at this deploy.")
                raise ops.Fatal("Pass 1 did not come up. Its /health body is above.")
            result = ops.restore_check(url, app_name, health_body=health["body"])
            if not ops.print_restore_check(result, expected_gpu=cfg["gpu"]):
                raise ops.Fatal(
                    "Pass 1 still did not boot cleanly, so the snapshot cache is\n"
                    "authoritative even with checkpointing off. Leave CHECKPOINT_ENABLED\n"
                    "False for now and clear the cache volume:\n\n"
                    "    beam volume list        # find checkpoint-model-cache-%s\n"
                    "    beam rm <that volume>/<contents>\n" % app_name)

            print()
            print("=" * 70)
            print("PASS 2 of 2 -- checkpointing back ON")
            print("=" * 70)
            ops.pin_config(checkpoint_enabled=True)
            reverted = True

        url, _ = ops.deploy(ENTRYPOINT, app_name)
    finally:
        if not reverted:
            # Never leave the tree pinned to the temporary pass-1 value.
            ops.pin_config(checkpoint_enabled=original_checkpoint == "True")

    print()
    print("=" * 70)
    print("APP URL: %s" % (url or "NOT FOUND -- read it off the output above"))
    print("The unversioned root is the URL to publish; a -vN link freezes at one build.")
    print("=" * 70)
    if not url:
        return 1

    cfg = ops.read_config()
    ok = verify(url, app_name, cfg, args.site_origin)

    if args.cold_start_test:
        print()
        print("-- the cold-start regression test " + "-" * 33)
        ok = cold_start_test(url, app_name, cfg) and ok

    if not args.keep_old_versions:
        print()
        print("-- older versions " + "-" * 49)
        stop_old_versions(app_name)

    print()
    print("=" * 70)
    print("%s   %s" % ("PASSED" if ok else "PROBLEMS ABOVE", url))
    print("=" * 70)
    if not args.cold_start_test:
        print("Nothing here has tested a cold start. The failure that takes this")
        print("deployment down arrives on the second boot, not the first --")
        print("--cold-start-test is the only check that exercises it.")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except subprocess.CalledProcessError as exc:
        sys.exit("\n%s failed with exit code %s" % (exc.cmd, exc.returncode))
