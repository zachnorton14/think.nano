# Beam operations, from a laptop

Everything operational, as scripts that run from a laptop. These replaced a set
of `colab_*.ipynb` notebooks (deleted 2026-08-20; git has them) — same steps,
same refusals, no Colab and no clone.

```
uv tool install beam-client
beam configure default --token <token from the Beam dashboard>
```

That is the whole setup. Every script finds the repo root by walking up to the
directory that holds `nanochat/` — the same rule `app.py` uses — so it does not
matter which directory you run them from.

| script | replaces | what it does |
|---|---|---|
| `redeploy.py` | `colab_beam_redeploy.ipynb` | deploy this tree, then verify it rather than trust it |
| `update_ui.py` | `colab_update_ui.ipynb` | ship a UI change and prove the served bytes are yours |
| `deploy.py` | `colab_beam_deploy.ipynb` | first-time setup: download, export, upload, deploy |
| `debug.py` | `colab_beam_debug.ipynb` | interrogate a live deployment; changes nothing |
| `cleanup.py` | `colab_beam_cleanup.ipynb` | stop and delete old versions; dry run by default |
| `watch_gpu.py` | — | wait for serverless GPU capacity and say when it lands |

Day-to-day it is one line:

```bash
python dev/hosting/beam/ops/redeploy.py
```

## Three things these do that the notebooks did not

**They deploy this working tree.** The notebooks cloned `origin/dev`, so they
shipped what was pushed. `beam deploy` syncs the working directory, so
uncommitted edits ship from here — which is usually what you want from a laptop
and is never silent: every script prints HEAD and lists the uncommitted files it
is about to deploy.

**`config.py` is the authority.** The notebooks rewrote `GPU`, `UI_FILE`, the
step and the persona path on every run, out of their own configuration cell.
That is how a Colab copy saved before the A10G fix redeployed RTX4090 on top of
corrected code on 2026-08-20. Nothing here rewrites `config.py` unless you pass
the flag for it, and when you do, the new value stays in the file where the next
person can read it.

**They check whether the container booted.** Beam caches the memory snapshot per
*app name*, on a volume it mounts at `/checkpoint-model-cache-<app>`, and that
cache outlives a redeploy — so a new version can restore a previous version's
process, replaying its heap and with it the `gpu_name` and `booted_at` that
`on_start` recorded under a GPU you have since changed. Every field `/health`
reads out of `on_start_value` is then describing a deployment you replaced.

A process cannot predate its own container. `process_age_seconds` greater than
the container's uptime is proof that the container never ran `on_start`, and
that comparison runs after every deploy. When it fires:

```bash
python dev/hosting/beam/ops/redeploy.py --bust-snapshot
```

which deploys once with checkpointing off to force a real boot, then again with
it on so the next snapshot is captured on the right hardware. Redeploying
normally will not clear a stale image.

## Common invocations

```bash
# see exactly what would ship, deploy nothing
python dev/hosting/beam/ops/redeploy.py --dry-run

# the deploy plus the cold-start regression test (adds keep_warm + 2 min)
python dev/hosting/beam/ops/redeploy.py --cold-start-test

# change something and leave it changed in config.py
python dev/hosting/beam/ops/redeploy.py --gpu A10G --step auto --min-containers 1

# turn on the always-append-a-period repair (nanochat/prompt_shaping.py)
python dev/hosting/beam/ops/redeploy.py --fix-punctuation on

# roll the UI back to the first design
python dev/hosting/beam/ops/update_ui.py --ui ui.html

# something is wrong and you do not know what
python dev/hosting/beam/ops/debug.py            # add --no-wake to bill nothing

# waiting on GPU capacity: check once, or poll until it lands
python dev/hosting/beam/ops/watch_gpu.py --once
python dev/hosting/beam/ops/watch_gpu.py

# the account is cluttered; print the plan, then carry it out
python dev/hosting/beam/ops/cleanup.py
python dev/hosting/beam/ops/cleanup.py --execute
```

## One Windows note

The entrypoint is `beam_app.py:handler` — a shim at the **repo root** that
defines the deployed callables and delegates into `dev/hosting/beam/app.py`.
That location is not cosmetic. The SDK records the handler *and* `on_start` as
`<module>:<name>`, deriving the module from the defining file's path:

```python
os.path.relpath(module.__file__, start=os.getcwd()).replace("/", ".")
```

(`beta9/abstractions/base/runner.py`, `_map_callable_to_attr`). On Windows,
`relpath` returns backslashes and the `.replace` never fires, so a handler
defined under `dev/hosting/beam/` is recorded as `dev\hosting\beam\app:handler`
— a module name the Linux container can never import, **no matter how you type
the entrypoint on the command line**. Every task then cancels before the app
exists and the edge answers 500. That is what took v9 down on 2026-08-20,
while v8 (deployed from Colab, so with a dotted path) kept working. A file at
the repo root has no separators to mangle, so it deploys identically from
every OS.

(An earlier version of this note claimed typing the path with backslashes was
enough. It was not: that fixes only the CLI's *local* import, not the handler
string baked into the stub.)

## The one heavy step

`deploy.py --force-reprep`. A first run pulls ~8.4 GiB from HuggingFace, wants
~9 GiB of RAM for the bf16 export, and pushes ~5.25 GiB to Beam. It works from
a laptop; it is just slow, and it needs ~25 GiB free on disk. (This is the one
job the deleted Colab notebooks were genuinely better at — run it from any
beefy box if your connection is thin.) Once the volume holds the model, nothing
else here touches any of that.
