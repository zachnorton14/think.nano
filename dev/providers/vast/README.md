# Vast H100 training image

This image preinstalls the exact GPU environment in `uv.lock`. It intentionally
does not include repository source, credentials, token data, compiler caches, or
checkpoints.

The `dev` workflow publishes:

```text
ghcr.io/zachnorton14/think-nano-vast:cu128-torch291-<first-12-uv.lock-sha>
```

Use the immutable lock tag in a private Vast template with:

- Launch mode: Jupyter + SSH
- Disk: 300 GB
- GPUs: 8x H100 SXM with a fully connected NVLink fabric
- Host Max CUDA: 12.8 or newer

The first GHCR package publication may default to private. Make the package
public in GitHub Packages before using it without registry credentials on Vast.
Never place Hugging Face or W&B credentials in this image or a public template.

After connecting, clone the public `dev` branch, create `.env`, and run:

```bash
bash runs/clean1930s-d24-r12.sh
```

Before renting an H100 node, the container itself can be tested on one cheaper
NVIDIA GPU with Max CUDA 12.8 or newer. This checks the image lock, imports,
CUDA matrix multiplication, and `torch.compile` without downloading artifacts
or requiring credentials:

```bash
/opt/think-nano-venv/bin/python -m scripts.container_smoke
```

The matched d12 4K attention ablations each use one command:

```bash
bash runs/clean1930s-d12-r11.25-ctx4096-ablation.sh sssl
bash runs/clean1930s-d12-r11.25-ctx4096-ablation.sh full
```

They share one physical copy of the hosted pretokens. The H100 launcher still
requires eight fully NVLink-connected H100 SXM GPUs for d24 by default. The d12
ablation wrapper explicitly enables a single Hopper GPU and defaults to one.

The launcher verifies that the image copy of `uv.lock` exactly matches the
checkout before it skips environment installation. A stale image fails before
artifact downloads or GPU training begin.

The step-6000 d24 midtraining continuation runs on exactly four fully
NVLink-connected H100 SXM GPUs because it restores four optimizer shards:

```bash
bash runs/clean1930s-d24-r12-ctx4096-sssl-fulltok-mix-og.sh
```

It reuses the parent tokenizer and prepares only the remaining `midtrain_r30`
and `midtrain_r60` sources. The inherited original-data stage remains in the
auditable lineage schedule but its pretok cache is not downloaded or opened.
