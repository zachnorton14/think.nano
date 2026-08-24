"""
Beam deploy entrypoint. Deploy from the repo root:

    beam deploy beam_app.py:handler --name bartholomew-iii          # the model
    beam deploy beam_app.py:probe_handler --name think-nano-probe   # CPU rehearsal

or, better, let the ops scripts do it and verify the result:

    python dev/hosting/beam/ops/redeploy.py

This file must stay at the REPO ROOT, and the two deployed functions below must
be DEFINED here rather than imported from somewhere deeper. The beam SDK
records every callable it ships -- the handler and on_start alike -- as
"<module>:<name>", building the module name from the defining file's path:

    os.path.relpath(module.__file__, start=os.getcwd()).replace("/", ".")

(beta9/abstractions/base/runner.py, _map_callable_to_attr). On Windows,
relpath returns backslashes and that .replace never fires, so a function
defined under dev/hosting/beam/ is recorded as "dev\\hosting\\beam\\app:handler"
-- a module name the Linux container can never import. Every task then dies
before the app exists and the edge answers 500, which is exactly what took the
deployment down on 2026-08-20 (v9). A file at the root has no separators to
mangle, so it deploys identically from every OS.

Everything real lives in dev/hosting/beam/: app.py builds the FastAPI app and
the container image, config.py holds the deploy-time settings, probe_app.py is
the CPU-only dress rehearsal.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from beam import QueueDepthAutoscaler, asgi  # noqa: E402

# dev/ has no __init__.py anywhere, so these resolve as namespace packages --
# the same way the container will import them. app.py puts its own folder on
# sys.path, so its internal `from config import ...` works from here too.
from dev.hosting.beam import app as _app  # noqa: E402
from dev.hosting.beam import probe_app as _probe  # noqa: E402


def load_engine():
    # A local definition, not `on_start=_app.load_engine`: on_start is recorded
    # by the same relpath rule as the handler, so the imported function would
    # put the backslash path right back into the stub.
    return _app.load_engine()


@asgi(
    name=_app.APP_NAME,
    image=_app.image,
    on_start=load_engine,
    gpu=_app.GPU,
    cpu=_app.CPU,
    memory=_app.MEMORY,
    volumes=[_app.volume],
    env=_app.CONTAINER_ENV,
    keep_warm_seconds=_app.KEEP_WARM_SECONDS,
    concurrent_requests=_app.CONCURRENT_REQUESTS,
    authorized=_app.AUTHORIZED,
    timeout=600,
    checkpoint_enabled=_app.CHECKPOINT_ENABLED,
    autoscaler=QueueDepthAutoscaler(
        min_containers=_app.MIN_CONTAINERS,
        max_containers=_app.MAX_CONTAINERS,
        tasks_per_container=_app.TASKS_PER_CONTAINER,
    ),
)
def handler(context):
    return _app.build_app(context)


@asgi(
    name="think-nano-probe",
    image=_probe.image,
    cpu=1,
    memory="1Gi",
    volumes=[_probe.volume],
    env=_probe.CONTAINER_ENV,
    keep_warm_seconds=60,
    authorized=_probe.AUTHORIZED,
)
def probe_handler(context):
    return _probe.build_app(context)
