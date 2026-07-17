# syntax=docker/dockerfile:1.7

FROM vastai/base-image:cuda-12.8.1-cudnn-devel-ubuntu22.04-py310@sha256:bfb8ad72550737751fff5b5ec8998fec088080ab60fd71e35d87f136273b5652

ARG LOCK_SHA

LABEL org.opencontainers.image.source="https://github.com/zachnorton14/think.nano"
LABEL org.opencontainers.image.description="Locked CUDA 12.8 environment for think.nano H100 training"

ENV UV_HTTP_TIMEOUT=600 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/think-nano-venv \
    NANOCHAT_PREBUILT_VENV=/opt/think-nano-venv \
    NANOCHAT_PREBUILT_LOCK=/opt/think-nano-env/uv.lock

WORKDIR /opt/think-nano-env
COPY pyproject.toml uv.lock ./

RUN test -n "$LOCK_SHA" && echo "$LOCK_SHA  uv.lock" | sha256sum --check --strict -

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --clear --python /venv/main/bin/python /opt/think-nano-venv && \
    uv sync --frozen --extra gpu --no-install-project

RUN /opt/think-nano-venv/bin/python -c \
    "import torch; assert torch.__version__.split('+')[0] == '2.9.1'; assert tuple(map(int, torch.version.cuda.split('.')[:2])) >= (12, 8); print(torch.__version__, torch.version.cuda)"

ENV PATH="/opt/think-nano-venv/bin:${PATH}"
WORKDIR /workspace
