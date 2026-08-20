#!/usr/bin/env python3
"""
What is actually wrong with the deployment. Reads; changes nothing.

    python dev/hosting/beam/ops/debug.py
    python dev/hosting/beam/ops/debug.py --url https://bartholomew-iii-xxxx.app.beam.cloud
    python dev/hosting/beam/ops/debug.py --no-wake      # never start a GPU container

The local replacement for colab_beam_debug.ipynb. Run it BEFORE cleanup.py: it
works by interrogating the live deployment, and a deleted deployment has nothing
to say. Only one probe can wake a GPU container (it is marked, and it is the
point of that probe); everything else is a CLI read or a request Beam's proxy
answers by itself.

"Errors from the container" is three unrelated failures wearing the same coat:

  hangs, then a network error   no container ever started -- GPU capacity, quota,
                                or every replica held by a stale deployment
  fails fast with a 5xx         a container started and on_start raised
  works direct, fails on site   CORS, or a stale api-base on the page

The probes are ordered so the cheap, container-free ones run first: by the time
anything wakes a GPU you already know whether it is worth waking.
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beamops as ops                                          # noqa: E402

BUNDLE = []


def note(section, text):
    BUNDLE.append((section, text))
    return text


def url_alive(url):
    """Does anything own this hostname?

    Reads the shape of the 404 rather than its status. Beam's edge answers
    {"message": ...} for a hostname with no deployment behind it; FastAPI
    answers {"detail": ...} for a path a live container does not serve. Anything
    other than an edge 404 -- a 503 or a timeout included -- means the hostname
    is real and the problem is further in.

    A preflight is NOT an existence check: the edge answers OPTIONS with 204 and
    CORS headers for any hostname under *.app.beam.cloud, deployed or not.
    """
    r = ops.probe(url + "/__beam_existence_probe__", timeout=90)
    body = r.get("body") or ""
    edge_404 = r.get("status") == 404 and '"message"' in body
    return (not edge_404 and r["kind"] != "network"), r


def find_url(given, app_name, deps, dep_raw):
    """The unversioned URL is https://<name>-<hex>.app.beam.cloud.

    The suffix is NOT derivable from anything the CLI exposes -- not the
    deployment id, not the stub id, not the app id (hosting.md says so, and
    building one from those ids yields hostnames that 404). So the repo writes
    the real one down, and those documented URLs are checked first; the
    id-derived guesses are only a fallback for a fresh account.
    """
    candidates = []
    if given:
        candidates.append(given.rstrip("/"))
    for doc in ("dev/hosting/hosting.md", "dev/hosting/beam/RUNBOOK.md"):
        path = os.path.join(ops.ROOT, doc)
        if not os.path.exists(path):
            continue
        for url in re.findall(r"https://%s-[a-z0-9]+\.app\.beam\.cloud" % re.escape(app_name),
                              open(path, encoding="utf-8").read()):
            candidates.append(re.sub(r"-v\d+(?=\.app\.beam\.cloud)", "", url))
    for url in re.findall(r"https://[A-Za-z0-9.-]+\.app\.beam\.cloud", dep_raw):
        candidates.append(re.sub(r"-v\d+(?=\.app\.beam\.cloud)", "", url))
    for key in ("app_id", "stub_id", "id"):
        for d in deps:
            ident = str(d.get(key) or "").replace("-", "")[:8]
            if ident:
                candidates.append("https://%s-%s.app.beam.cloud" % (d["name"] or app_name, ident))

    seen, live = set(), ""
    for url in candidates:
        if url in seen or live:
            continue
        seen.add(url)
        alive, r = url_alive(url)
        print("%-6s %s" % ("LIVE" if alive else "dead", url))
        print("       %s  %.1fs  %s" % (r.get("status") or r.get("error"), r["seconds"],
                                        (r.get("body") or "").strip()[:80]))
        if alive:
            live = url
    note("url candidates", "\n".join(sorted(seen)))
    return live


def read_logs(deps):
    """`beam logs` takes options only, and which ones has changed between
    releases. Read them out of --help rather than guessing."""
    _c, logs_help = ops.stream(["beam", "logs", "--help"], quiet=True, timeout=30)
    flags = sorted(set(re.findall(r"(--[a-z][a-z0-9-]*id)\b", logs_help)))
    print("  id-shaped options this CLI accepts: %s" % (flags or "none found"))

    newest = {}
    for d in deps:
        if d["version"] >= newest.get(d["name"], {"version": -1})["version"]:
            newest[d["name"]] = d

    collected = {}
    for d in newest.values():
        print()
        print("=" * 70)
        print("logs: %s v%s  %s" % (d["name"], d["version"], d["id"]))
        print("=" * 70)
        got = ""
        for flag in flags:
            key = flag.lstrip("-").replace("-", "_")
            value = d.get(key) or d["id"]
            # 25s: beam logs tails rather than returning, so every extra id is
            # another 25s of waiting for output that may never come.
            code, out = ops.stream(["beam", "logs", flag, value], quiet=True, timeout=25)
            if out.strip() and "Usage:" not in out:
                print("(%s %s)" % (flag, value))
                print(out[-6000:])
                got = out
                break
        if not got:
            print("(no log output -- read them from the dashboard for this id)")
        collected[d["id"]] = got

    joined = "\n".join(collected.values())
    print("=" * 70)
    for pattern, meaning in [
            (r"\[boot\] FAILED", "on_start raised -- the traceback is above"),
            (r"FileNotFoundError", "a path the container reads is not on the volume"),
            (r"ModuleNotFoundError|ImportError", "an import failed -- check .beamignore"),
            (r"CUDA error|no kernel image|device-side assert", "the GPU cannot run this build"),
            (r"out of memory|OOM", "memory limit too low, or a non-exported checkpoint"),
            (r"Killed|SIGKILL", "the container was killed -- usually host RAM, see MEMORY"),
            (r"\[boot\] ready in", "at least one container booted successfully")]:
        hits = len(re.findall(pattern, joined, re.I))
        if hits:
            print("  %3d x  %s" % (hits, meaning))
    return note("logs", joined[-20000:] or "(no logs retrieved)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="", help="skip URL discovery and interrogate this one")
    p.add_argument("--app-name", default=None)
    p.add_argument("--volume", default="think-nano-weights")
    p.add_argument("--model-tag", default=None)
    p.add_argument("--site-origin", default="https://www.unboundedlab.com")
    p.add_argument("--no-wake", dest="wake", action="store_false",
                   help="skip the generation probe, which starts a GPU container and bills")
    p.add_argument("--out", default=os.path.join(ops.ROOT, "beam-debug-bundle.txt"))
    args = p.parse_args(argv)

    cfg = ops.read_config()
    app_name = args.app_name or cfg["app_name"]
    config_text = open(ops.CONFIG_PATH, encoding="utf-8").read()
    model_tag = args.model_tag or re.search(r'^MODEL_TAG = "([^"]+)"',
                                            config_text, re.M).group(1)
    ops.require_beam()

    print("=" * 70)
    print("WHICH DEPLOYMENTS EXIST, AND WHICH ONE IS LIVE")
    print("=" * 70)
    deps, dep_raw = ops.deployments()
    by_name = {}
    for d in deps:
        by_name.setdefault(d["name"], []).append(d)
    for name, group in sorted(by_name.items()):
        live = [r for r in group if ops.is_active(r)]
        print("%s: %d version(s), %d marked active" % (name, len(group), len(live)))
        for i, r in enumerate(group):
            print("    v%-4s active=%-8s %s%s"
                  % (r["version"], r["active"], r["id"],
                     "  <- unversioned URL routes here" if i == 0 else ""))
    extra = sorted(set(by_name) - {app_name})
    if extra:
        print("\nOther app names in this account: %s" % ", ".join(extra))
        print("Each holds its own containers and its own share of the account GPU")
        print("concurrency. At the limit, a new container for %s cannot" % app_name)
        print("schedule -- which looks exactly like a broken model.")
    note("deployments", "\n".join("%s v%s active=%s id=%s" % (d["name"], d["version"],
                                                              d["active"], d["id"])
                                  for d in deps))

    print()
    print("=" * 70)
    print("FIND THE URL")
    print("=" * 70)
    live_url = find_url(args.url, app_name, deps, dep_raw)
    print()
    if not live_url:
        print("No hostname answered as a live deployment -- every candidate returned the")
        print("edge's own 404, so nothing is deployed behind any of them. Either the")
        print("deployments really are gone, or the URL scheme is not the one derived")
        print("here: pass --url with the link you have been opening.")
    else:
        print("using: %s" % live_url)
    note("live url", live_url or "none reachable")

    health, health_ok, boot_traceback = None, False, ""
    if live_url:
        print()
        print("=" * 70)
        print("CORS -- answered by the proxy, so nothing starts")
        print("=" * 70)
        pre = ops.probe(live_url + "/chat/completions", method="OPTIONS", timeout=30, extra={
            "Origin": args.site_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        ops.show("OPTIONS /chat/completions", pre, body_chars=200)
        acao = ops.header_values(pre, "access-control-allow-origin")
        acam = ops.header_values(pre, "access-control-allow-methods")
        print("  Allow-Origin  : %s" % (acao or "ABSENT"))
        print("  Allow-Methods : %s" % (acam or "ABSENT"))
        cors_notes = []
        if len(acao) > 1:
            cors_notes.append("TWO Allow-Origin headers. A browser reads that as '*, *' and "
                              "refuses the response. Check CORSMiddleware has not gone back "
                              "into app.py.")
        elif not acao:
            cors_notes.append("No Allow-Origin at all. Do NOT fix this by adding "
                              "CORSMiddleware -- that is what produced the doubled header.")
        elif acao[0] not in ("*", args.site_origin):
            cors_notes.append("Allow-Origin is %r, which does not cover %s"
                              % (acao[0], args.site_origin))
        if acam and acam[0].strip() != "*" and "POST" not in acam[0].upper():
            cors_notes.append("POST is not in Allow-Methods, so the chat call is blocked.")
        for n in cors_notes:
            print("  " + n)
        print("  CORS looks fine." if not cors_notes else "")
        note("cors", "preflight=%s allow-origin=%s allow-methods=%s\n%s"
             % (pre.get("status"), acao, acam, "\n".join(cors_notes)))

        print()
        print("=" * 70)
        print("/health -- the one that says why")
        print("=" * 70)
        print("200 means the model is loaded and the problem is downstream of boot.")
        print("503 with a traceback in the body IS the bug -- read it.")
        print("A timeout means nothing is being scheduled: capacity or quota, not code.")
        print()
        health = ops.probe(live_url + "/health", timeout=420)
        ops.show("GET /health", health, body_chars=4000)
        health_ok = health["kind"] == "ok"
        if health.get("status") == 503:
            try:
                payload = json.loads(health["body"])
                boot_traceback = str(payload.get("error") or payload.get("detail") or "")
            except Exception:
                boot_traceback = health["body"]
        if health_ok:
            info = json.loads(health["body"])
            runtime, model = info.get("runtime", {}), info.get("model", {})
            print()
            print("  step        %s" % model.get("step"))
            print("  gpu         %s" % runtime.get("gpu"))
            print("  dtype       %s" % runtime.get("compute_dtype"))
            print("  vram        %s GiB" % runtime.get("vram_gib"))
            print("  boot        %ss" % runtime.get("boot_seconds"))
            print()
            # The GPU name above is read out of on_start_value, so on a restored
            # container it describes the process that was captured, not this one.
            ops.print_restore_check(
                ops.restore_check(live_url, app_name, health_body=health["body"]),
                expected_gpu=cfg["gpu"])
        elif boot_traceback:
            print("  on_start raised. The last line of the traceback names the failure:")
            print("    FileNotFoundError model_*.pt  -> NANOCHAT_STEP pinned to a step")
            print("                                     that is not on the volume")
            print("    ImportError / ModuleNotFound  -> .beamignore excluded something")
            print("    CUDA / device-side error      -> this GPU cannot run bf16")
        note("health", "status=%s kind=%s %.1fs\n%s"
             % (health.get("status"), health["kind"], health["seconds"],
                health.get("body", "")[:4000]))

    print()
    print("=" * 70)
    print("CONTAINER LOGS")
    print("=" * 70)
    read_logs(deps)

    if live_url:
        print()
        print("=" * 70)
        print("STREAMING AND GENERATION")
        print("=" * 70)
        sp = ops.probe(live_url + "/stream-probe", timeout=120, read_bytes=4000)
        ops.show("GET /stream-probe", sp, body_chars=0)
        frames = sp.get("body", "").count("data: ")
        print("       %d SSE frame(s) in the first 4 KB (the route emits 7 over ~3s)" % frames)
        if sp["kind"] == "ok" and frames < 2:
            print("       Buffered somewhere -- every reply arrives in one lump.")

        if args.wake:
            # Whether the container was warm when the POST left is the single
            # fact that makes the timing readable, and it can easily have scaled
            # down while you were reading the output above.
            warm = ops.probe(live_url + "/health", timeout=300)
            was_warm = warm["kind"] == "ok" and warm["seconds"] < 3
            print("\n/health immediately before the POST: %s in %.1fs -> %s"
                  % (warm.get("status"), warm["seconds"],
                     "WARM" if was_warm else "COLD or busy"))
            gen = ops.stream_timing(live_url + "/chat/completions", {
                "messages": [{"role": "user",
                              "content": "Describe the wireless telegraph in one sentence."}],
                "max_tokens": 16, "stream": True}, deadline=180)
            print()
            if gen["error"]:
                print("  The server said what went wrong -- that message is the bug.")
            elif not gen["frames"]:
                print("  Nothing arrived at all. With concurrent_requests = 1 the usual")
                print("  cause is a request already in flight holding the container: an")
                print("  abandoned SSE stream from a browser tab never closes, so Beam")
                print("  keeps queueing behind it. Redeploying clears it.")
            elif gen["ttft"] and gen["ttft"] > 30:
                print("  First token took %.0fs, then flowed -- a cold start, not a broken"
                      % gen["ttft"])
                print("  model. Either the container had scaled down or the snapshot is")
                print("  not being restored.")
            else:
                print("  Generation works: %r" % gen["text"])
            note("generation", "ttft=%s total=%.1fs frames=%d error=%s warm_before=%s\n%r"
                 % (gen["ttft"], gen["seconds"], len(gen["frames"]), gen["error"],
                    was_warm, gen["text"]))
        else:
            print("\n--no-wake: skipped the generation probe.")

    print()
    print("=" * 70)
    print("IS THE VOLUME WHAT THE CONFIG EXPECTS?")
    print("=" * 70)
    vol = ops.volume_state(args.volume, model_tag)
    print("  steps with both model and meta : %s" % (vol["usable"] or "NONE"))
    print("  tokenizer.pkl                  : %s" % ("present" if vol["tokenizer"] else "MISSING"))
    print("  pre1930-companion.txt          : %s" % ("present" if vol["persona"] else "missing"))
    print("  config.py pins NANOCHAT_STEP   : %s" % (cfg["step"] or "(blank -- newest)"))
    served_step = None
    if health_ok:
        try:
            served_step = json.loads(health["body"]).get("model", {}).get("step")
        except Exception:
            pass
    if served_step is not None:
        print("  step the container reports     : %s" % served_step)
        if vol["step"] is not None and int(served_step) != vol["step"]:
            print("    NOTE  the container serves an older step than the volume holds.")
            print("          Fine if it is pinned on purpose; a surprise otherwise.")
    # Sizes, not just names: a bf16 d32 export is ~5.25 GiB, and the step number
    # alone would never tell you that the wrong artefact got uploaded.
    print("\n  what `beam ls` reported -- check model_*.pt is ~5.25 GiB:")
    for line in vol["listings"]["checkpoint"].splitlines():
        if re.search(r"model_|meta_|GiB|MiB|KiB|bytes", line):
            print("   " + line.strip())
    note("volume", "steps=%s tokenizer=%s persona=%s served_step=%s\n%s"
         % (vol["usable"], vol["tokenizer"], vol["persona"], served_step,
            vol["listings"]["checkpoint"]))

    print()
    print("=" * 70)
    print("IS THE GPU YOU PINNED ACTUALLY AVAILABLE?")
    print("=" * 70)
    _c, machines = ops.stream(["beam", "machine", "list"])
    note("machines", machines)
    want = (cfg["gpu"] or "").replace("RTX", "")
    if want and re.search(re.escape(want), machines, re.I):
        print("\n%s appears in the machine list." % cfg["gpu"])
    else:
        print("\n%s does NOT appear in the machine list. If /health also timed out"
              % cfg["gpu"])
        print("rather than erroring, this is very likely the whole problem: nothing is")
        print("being scheduled. A10G, L40S and H100 all satisfy the two constraints")
        print("(bf16 tensor cores, and checkpoint restore that works).")

    # ------------------------------------------------------------- the bundle
    lines = ["=" * 78, "BEAM DEBUG BUNDLE",
             time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
             "app: %s   url: %s" % (app_name, live_url or "(none reachable)"),
             "=" * 78, ""]
    for section, text in BUNDLE:
        lines += ["--- %s %s" % (section, "-" * max(0, 70 - len(section))),
                  str(text).rstrip(), ""]

    verdict = []
    edge_404 = bool(health) and health.get("status") == 404 and \
        '"message"' in (health.get("body") or "")
    if not live_url:
        verdict.append("No hostname answered as a live deployment. Pass --url with the "
                       "link you have been opening and re-run before reading anything else.")
    elif edge_404:
        verdict.append("Every route returned 404 {\"message\": ...} from Beam's edge, not "
                       "from the app: a hostname with no deployment behind it. Nothing "
                       "here describes your deployment. Pass --url and re-run.")
    elif health_ok:
        verdict.append("/health returned 200 -- the model is loaded and the container is "
                       "fine. If the page is still broken it is CORS or a stale api-base "
                       "on the site, not the deployment.")
    elif boot_traceback:
        verdict.append("on_start raised. Last line of the traceback:")
        verdict.append("    " + (boot_traceback.strip().splitlines() or [""])[-1])
    elif health and health["kind"] == "network":
        verdict.append("Nothing answered /health. No container is being scheduled -- look "
                       "at GPU availability, the account quota, and how many other "
                       "deployments are holding containers.")
    else:
        verdict.append("/health returned %s with no readable reason. The logs section is "
                       "the next place to look." % (health or {}).get("status"))

    lines += ["=" * 78, "READING", "=" * 78] + verdict + [""]
    report = "\n".join(lines)
    print()
    print("\n".join(lines[-(len(verdict) + 4):]))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report)
    print("full bundle saved to %s" % args.out)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
