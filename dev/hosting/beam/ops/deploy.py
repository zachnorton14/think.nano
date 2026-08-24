#!/usr/bin/env python3
"""
First-time setup: get the checkpoint onto the Beam volume, then deploy.

    python dev/hosting/beam/ops/deploy.py               # idempotent; skips what is done
    python dev/hosting/beam/ops/deploy.py --force-reprep  # redo download/export/upload
    python dev/hosting/beam/ops/deploy.py --volume-only   # prepare the volume, do not deploy

The local replacement for colab_beam_deploy.ipynb. Every step is idempotent and
skips work already done, so re-running is safe: once the volume holds the model
this goes straight to deploying, which takes a couple of minutes.

**This is the one job the notebook was genuinely better at.** A first run pulls
~8.4 GiB from HuggingFace, wants ~9 GiB of RAM to export, and pushes ~5.25 GiB
to Beam -- none of which has to cross a home connection from Colab. On a laptop
it works, it is just slow, and it needs ~25 GiB free on disk. Every later run
touches none of that.

Environment:
    HF_TOKEN     required for the download (not needed once the volume is ready)
    beam CLI     installed and authenticated -- see redeploy.py's docstring
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beamops as ops                                          # noqa: E402
import redeploy                                                # noqa: E402

PERSONA_SOURCE = os.path.join("configs", "system_prompts", "pre1930-companion.txt")


def total_ram_gib():
    """Portable enough for the two platforms this runs on."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (AttributeError, ValueError, OSError):
        pass
    try:
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.ullTotalPhys / 1024 ** 3
    except Exception:
        return None


def machine_report(work_dir):
    ram = total_ram_gib()
    free = shutil.disk_usage(os.path.dirname(work_dir) or ".").free / 1024 ** 3
    print("  RAM             %s" % ("%.1f GiB" % ram if ram else "unknown"))
    print("  free disk       %.1f GiB  (%s)" % (free, work_dir))
    have_gpu = False
    try:
        import torch
        if torch.cuda.is_available():
            cap = torch.cuda.get_device_capability()
            have_gpu = cap >= (8, 0)
            print("  GPU             %s (SM %d%d), bf16 %s"
                  % (torch.cuda.get_device_name(0), cap[0], cap[1],
                     "yes" if have_gpu else "NO -- the end-to-end check will skip"))
        else:
            print("  GPU             none (fine; the end-to-end check will skip)")
    except ImportError:
        print("  GPU             torch is not installed here; local checks will skip")
    if ram and ram < 9:
        print("  WARN  the bf16 export wants ~9 GiB of RAM. It may be killed here.")
    if free < 25:
        print("  WARN  a first run needs ~25 GiB free for the download plus the export.")
    return have_gpu


def end_to_end(export_dir, step, system_prompt_path):
    """Drive the real serving path against the real weights, before uploading.

    fast_load.load_model_fast, the real prompt renderer, Engine.generate. The
    last check that costs nothing, and the only one that would catch a bad
    export before it becomes a boot failure inside a container.
    """
    import torch
    sys.path.insert(0, ops.HOSTING)
    from fast_load import load_model_fast
    from conversation import render_conversation_tokens
    from nanochat.engine import Engine

    system_prompt = ""
    if system_prompt_path and os.path.exists(system_prompt_path):
        system_prompt = open(system_prompt_path, encoding="utf-8").read().strip()

    model, tokenizer, meta = load_model_fast(
        export_dir, torch.device("cuda"), step=step,
        tokenizer_dir=os.path.join(export_dir, "tokenizer"))
    engine = Engine(model, tokenizer)

    question = "What is the wireless telegraph, and what has it meant for ships at sea?"
    tokens = render_conversation_tokens(
        tokenizer, model.config.sequence_len,
        [{"role": "user", "content": question}], 128,
        default_system_prompt=system_prompt)
    print("  prompt: %d tokens\n\n> %s\n" % (len(tokens), question))

    end = tokenizer.encode_special("<|assistant_end|>")
    bos = tokenizer.get_bos_token_id()
    out = []
    for column, _ in engine.generate(tokens, num_samples=1, max_tokens=128,
                                     temperature=0.8, top_k=50, seed=0):
        if column[0] in (end, bos):
            break
        out.append(column[0])
    print(tokenizer.decode(out))
    del engine, model
    torch.cuda.empty_cache()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--volume", default="think-nano-weights")
    p.add_argument("--model-tag", default=None, help="default: MODEL_TAG from config.py")
    p.add_argument("--base-experiment-id", default=None,
                   help="default: BASE_EXPERIMENT_ID from config.py")
    p.add_argument("--hf-repo", default="jbduran/bart-experiments")
    p.add_argument("--work-dir", default=os.path.join(ops.ROOT, "dev-ignore", "beam-deploy"),
                   help="where the download and the export land (gitignored by default)")
    p.add_argument("--force-reprep", action="store_true",
                   help="download, export and upload again even if the volume is ready")
    p.add_argument("--volume-only", action="store_true", help="prepare the volume, do not deploy")
    p.add_argument("--skip-e2e", action="store_true", help="skip the local GPU generation check")
    p.add_argument("--run-probe", action="store_true",
                   help="also deploy the CPU-only probe app first, as a dress rehearsal")
    p.add_argument("--yes", "-y", action="store_true")
    args = p.parse_args(argv)

    config_text = open(ops.CONFIG_PATH, encoding="utf-8").read()

    def from_config(name):
        m = re.search(r'^%s = "([^"]+)"' % name, config_text, re.M)
        return m.group(1) if m else None

    model_tag = args.model_tag or from_config("MODEL_TAG")
    base_id = args.base_experiment_id or from_config("BASE_EXPERIMENT_ID")
    cfg = ops.read_config()
    app_name = cfg["app_name"]
    ckpt_dir = os.path.join(args.work_dir, "ckpt")
    export_dir = os.path.join(args.work_dir, "ckpt-bf16")

    print("=" * 70)
    print("DEPLOY  %s  ->  %s" % (model_tag, app_name))
    print("=" * 70)
    have_gpu = machine_report(args.work_dir)
    ops.require_beam()

    print()
    print("-- is the checkpoint already on the volume? " + "-" * 23)
    vol = ops.volume_state(args.volume, model_tag)
    ready = bool(vol["usable"]) and not args.force_reprep
    step = vol["step"]
    if ready:
        print("  The volume holds %s at step %s." % (model_tag, step))
        print("  Skipping download, export and upload. --force-reprep redoes them.")
    else:
        print("  Nothing usable on the volume -- will download, export and upload.")
        if not os.environ.get("HF_TOKEN"):
            raise ops.Fatal("HF_TOKEN is not set, and the download needs it.\n"
                            "    export HF_TOKEN=...        (PowerShell: $env:HF_TOKEN='...')")

    # Five assertions, seconds, no GPU and no checkpoint needed: the bf16 cast
    # must produce bit-identical logits and identical greedy token streams, and
    # fast_load must match the stock loader parameter for parameter. Cheap
    # enough to run every time, and the check that would catch a bad merge.
    print()
    print("-- proving the export is safe " + "-" * 37)
    code, _ = ops.stream([sys.executable, os.path.join(ops.HOSTING, "test_export.py")])
    if code != 0:
        raise ops.Fatal("test_export.py failed -- do not upload anything until it passes.")

    if not ready:
        print()
        print("-- downloading from HuggingFace " + "-" * 35)
        fetch = [sys.executable, os.path.join(ops.HOSTING, "fetch_checkpoint.py"),
                 "--repo", args.hf_repo, "--model-tag", model_tag,
                 "--base-experiment-id", base_id, "--out", ckpt_dir]
        ops.run(fetch + ["--list-only"])
        ops.run(fetch)

        print()
        print("-- exporting to bf16 (8.37 GiB -> 5.25 GiB) " + "-" * 23)
        ops.run([sys.executable, os.path.join(ops.HOSTING, "export_bf16.py"),
                 "--in-dir", ckpt_dir, "--out-dir", export_dir,
                 "--tokenizer-dir", os.path.join(ckpt_dir, "tokenizer"), "--force"])
        step = max(int(re.search(r"model_(\d+)\.pt", p).group(1))
                   for p in glob.glob(os.path.join(export_dir, "model_*.pt")))
        print("  exported step %s" % step)

        if have_gpu and not args.skip_e2e:
            print()
            print("-- end-to-end on the real weights " + "-" * 33)
            end_to_end(export_dir, step, os.path.join(ops.ROOT, PERSONA_SOURCE))

        print()
        print("-- uploading to the volume " + "-" * 40)
        ops.stream(["beam", "volume", "create", args.volume])   # already-exists is fine
        ops.run(["beam", "cp", export_dir, "beam://%s/%s" % (args.volume, model_tag)])
        persona = os.path.join(ops.ROOT, PERSONA_SOURCE)
        if os.path.exists(persona):
            ops.run(["beam", "cp", persona, "beam://%s/" % args.volume])
        ops.stream(["beam", "ls", "%s/%s" % (args.volume, model_tag)])
        # Volume writes take up to 60s to become visible to containers.
        ops.wait(60, "letting the volume write propagate")
        vol = ops.volume_state(args.volume, model_tag)

    if args.volume_only:
        print("\n--volume-only: the volume is ready, nothing deployed.")
        return 0

    if not step:
        raise ops.Fatal("No usable step: the volume check and the export both failed.")

    print()
    print("-- config " + "-" * 57)
    # A first deploy is the one time pinning is right rather than dangerous:
    # there is nothing committed yet that it could silently revert.
    changed = ops.pin_config(step=step,
                             system_prompt_file="/vol/model/pre1930-companion.txt"
                             if vol["persona"] else None)
    for line in changed:
        print("  " + line)
    cfg = ops.read_config()
    ops.show_config(cfg)
    print()
    print("  Commit these values. They are what is deployed, and a config.py in git")
    print("  that disagrees with the running deployment is how this setup lost its")
    print("  persona and its GPU choice before.")

    if not args.yes:
        if not sys.stdin.isatty():
            raise ops.Fatal("Not a terminal. Pass --yes to proceed.")
        if input("\nDeploy? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing deployed.")
            return 1

    ops.ensure_beamignore()

    if args.run_probe:
        # The CPU dress rehearsal: a second, model-less deployment that proves
        # the sync, the volume layout, the public URL and that SSE is not
        # buffered, without waiting on a GPU.
        print()
        print("-- CPU probe deployment " + "-" * 43)
        probe_url, _ = ops.deploy(redeploy.PROBE_ENTRYPOINT, "%s-probe" % app_name)
        print("  probe URL: %s" % probe_url)
        if probe_url:
            ops.run([sys.executable, os.path.join(ops.HOSTING, "smoke_test.py"), probe_url],
                    check=False)
        print("  Delete it when you are done: beam deployment list, then delete <id>")

    url, _ = ops.deploy(redeploy.ENTRYPOINT, app_name)
    print()
    print("=" * 70)
    print("APP URL: %s" % (url or "NOT FOUND -- read it off the output above"))
    print("This unversioned root is the URL to publish.")
    print("=" * 70)
    if not url:
        return 1

    ok = redeploy.verify(url, app_name, cfg, "https://www.unboundedlab.com")

    print()
    print("-- afterwards " + "-" * 53)
    print("  1. Commit the config.py values above.")
    print("  2. The first cold start after a deploy is always slow -- the snapshot")
    print("     takes up to 3 min to capture and 5 more to propagate. Measure the")
    print("     real one with:")
    print("       python dev/hosting/beam/ops/redeploy.py --cold-start-test")
    print("  3. Put that number in the UI, not the placeholder.")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except subprocess.CalledProcessError as exc:
        sys.exit("\n%s failed with exit code %s" % (exc.cmd, exc.returncode))
