# HISTORY-EVENT reconstruction and evaluation

This directory reconstructs the HISTORY-EVENT benchmark described in [*The Past is a Foreign Country: Era-Specific Language Models*](https://arxiv.org/abs/2606.02991). It is an independent derivative, not the authors' official dataset: the paper does not release exact Wikipedia revisions, scraper code, or the Gemini screening prompt. The pipeline therefore preserves provenance and publishes observed discrepancies rather than forcing the paper's row counts.

Pipeline code is MIT licensed with think.nano. Published Wikipedia-derived text is CC BY-SA 4.0 with revision-level attribution.

## Local dataset pipeline

From the repository root:

```bash
uv sync --group dev
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event prepare
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event status
```

`prepare` downloads the four pinned Wikipedia revisions once, stores their hashes and timestamps, evaluates documented parsing profiles against Figure 4, and writes all events, recall candidates, four-digit rejections, and an exact discrepancy report under `artifacts/history-event/`.

Verify `OPENCODE_API_KEY` in `.env` without displaying it, probe the paid route, then run DeepSeek:

```bash
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -c 'from dotenv import load_dotenv; import os; load_dotenv(); assert os.getenv("OPENCODE_API_KEY"), "OPENCODE_API_KEY missing"; print("OpenCode key found")'
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event gold --probe
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event gold --batch-size 8 --workers 64
```

The full command is interruption-safe. Re-run it unchanged to skip valid rows and retry errors. Repeated 429, 403, transport, or malformed responses lower subsequent waves to 32 workers. `status` must show all candidate answers complete, every year-valid answer judged, and zero unresolved errors.

Generate the report, validate all three Hugging Face configurations, and publish the public dataset:

```bash
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event report
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event package
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event publish --repo-id jbduran/history-event-reconstruction
```

Packaging refuses incomplete or errored gold runs. It derives README counts from the package manifest and validates the card/config paths and JSON schemas locally with Hugging Face tooling before upload.

## Vast BPB run

Provision one A100 or H100 with at least 40 GB VRAM using the locked image from `dev/providers/vast` (no Vast API credential is configured). Attach at least 250 GB of disk, clone this branch, and place `HF_TOKEN` in `.env`. The token needs read access to gated Llama 3.1 and write access to `jbduran/history-event-reconstruction`.

The image tag is derived from the lock file by `dev/providers/vast/build_and_push.sh`; use its immutable `cu128-torch291-<lock-sha>` tag, not `latest`.

Run the full seven-checkpoint comparison sequentially:

```bash
bash runs/history-event-vast.sh all
```

If official Llama access is unavailable, run the explicitly labeled ungated proxy set:

```bash
bash runs/history-event-vast.sh all-smollm3
```

This substitutes pinned `HuggingFaceTB/SmolLM3-3B` for Llama and writes its chart under `chart-smollm3`. SmolLM3 does not disclose a factual knowledge cutoff, so the proxy has no cutoff line and no pre/post ratio. It is not presented as a reproduction of the paper's Llama baseline.

Or resume one model:

```bash
bash runs/history-event-vast.sh think-unbounded-d32-step9600
bash runs/history-event-vast.sh think-unbounded-d32-sft-c3-robust-v2
bash runs/history-event-vast.sh gpt1900-d34
bash runs/history-event-vast.sh gpt1900-sft
bash runs/history-event-vast.sh talkie-1930-13b-base
bash runs/history-event-vast.sh talkie-1930-13b-it
bash runs/history-event-vast.sh llama-3.1-8b-instruct
bash runs/history-event-vast.sh smollm3-3b
```

The runner checks CUDA/bf16, at least 40 GB VRAM, free disk, Hugging Face identity, the dataset, exact artifact revisions, and a one-event model load/score before each full run. It restores prior partial JSONL from the dataset repository, uploads changed results while scoring, and unloads each process before starting the next model. It never applies chat templates or quantization.

The `all` set compares our d32 base and SFT checkpoints, GPT-1900 base and SFT, Talkie 1930 base and IT, and Llama-3.1-8B-Instruct. Every checkpoint is scored as a raw language model with the same conditioning prefix and target span; instruction-tuned checkpoints do not receive chat templates. Recall-question generation and judging are a separate evaluation stage and are not performed by this runner.

Once all seven summaries are complete, the runner produces and uploads PNG, SVG, CSV, JSON, and a hash-complete run manifest. Locally, the same chart command is:

```bash
env XDG_CACHE_HOME=/tmp/thinknano-history-event-cache uv run --group dev python -m dev.history_event chart
```
