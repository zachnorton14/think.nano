"""
Multi-stage data-schedule support for base pretraining.

This module is additive and self-contained: if a base config carries no
``mixture_schedule`` key, none of this code runs and the trainer uses the existing
single-source pretokenized dataloader unchanged.

Model
-----
Each *stage* names exactly ONE pretokenized data source (a whole, already-prepared token
cache). The per-stage data ratio (e.g. 30%/60% midtrain) is baked into the source dataset
itself -- the folders on Hugging Face (``mixed/ratio_30``, ``mixed/ratio_60``) are already
mixed at the desired ratio. So this loader does NOT blend sources on the fly; it simply
switches which source it reads from at each stage boundary.

Concepts
--------
* A *stage* here is a DATA phase (base / injection / decay_mix), NOT the pipeline phase
  (base / sft / posttrain) that ``Experiment.stage`` refers to. The two are completely
  decoupled -- in particular the schedule never touches the LR code path. Stage boundaries
  are declared in tokens and snapped to whole optimizer steps at load time.
* The active stage (and therefore the active source) is a pure function of cumulative
  global tokens. It is never held in mutable runtime state, so resuming from any
  checkpoint lands in the correct stage/source with no special-casing.
* Each source keeps its own persistent cursor (the underlying pretokenized dataloader's
  state_dict). If a source is used by more than one stage its stream continues where it
  left off; it does not restart.

Determinism
-----------
There is no per-step RNG in the pretokenized path, and no cross-source blending here, so
the token stream is fully determined by (source order, B, T, world_size, rank). A
single-stage schedule reads exactly one source's cursor and reproduces the single-source
baseline byte-for-byte.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# NB: torch and the pretokenized cursor are imported lazily inside MixtureLoader so that
# MixtureSchedule (and therefore `experiment.py plan`) stays a pure-Python, sub-second,
# torch-free code path.

DEFAULT_MAX_EPOCHS = 4


# -----------------------------------------------------------------------------
# Schedule


@dataclass(frozen=True)
class Stage:
    name: str
    start_tokens: int
    source: str
    start_step: int = 0  # filled in during step conversion


@dataclass
class MixtureSchedule:
    total_tokens: int
    seed_data: int
    stages: List[Stage]
    total_batch_size: int
    max_epochs: float = DEFAULT_MAX_EPOCHS
    sources: List[str] = field(default_factory=list)
    total_steps: int = 0

    # --- construction / validation -------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict, total_batch_size: int, max_epochs: float = DEFAULT_MAX_EPOCHS):
        """Parse and validate a ``mixture_schedule`` config block.

        Each stage names exactly one ``source``. Validates: every stage has a source,
        start_tokens strictly increasing, first stage starts at 0, boundaries within the
        horizon. Converts token boundaries to whole steps.

        The epoch cap cannot be fully enforced here because per-source cache sizes are not
        known until the caches are prepared; call ``check_epoch_cap`` with real token
        counts at prepare/train time. This method validates the schedule shape.
        """
        if not isinstance(cfg, dict):
            raise ValueError("mixture_schedule must be a mapping")
        if total_batch_size <= 0:
            raise ValueError("total_batch_size must be positive to convert tokens to steps")

        total_tokens = int(cfg["total_tokens"])
        if total_tokens <= 0:
            raise ValueError("mixture_schedule.total_tokens must be positive")
        seed_data = int(cfg.get("seed_data", 0))
        raw_stages = cfg.get("stages")
        if not isinstance(raw_stages, list) or not raw_stages:
            raise ValueError("mixture_schedule.stages must be a non-empty list")

        stages: List[Stage] = []
        sources: List[str] = []
        prev_start = None
        for i, raw in enumerate(raw_stages):
            name = raw.get("name", f"stage{i}")
            source = raw.get("source")
            if not source or not isinstance(source, str):
                raise ValueError(f"stage {name!r} must name a single string 'source'")
            if "start_tokens" not in raw:
                raise ValueError(f"stage {name!r} missing start_tokens")
            start = int(raw["start_tokens"])
            if i == 0 and start != 0:
                raise ValueError("first stage must start at start_tokens=0")
            if prev_start is not None and start <= prev_start:
                raise ValueError(
                    f"stage start_tokens must be strictly increasing; "
                    f"{name!r} start={start} <= previous {prev_start}"
                )
            if start >= total_tokens:
                raise ValueError(
                    f"stage {name!r} start_tokens={start} >= total_tokens={total_tokens}"
                )
            prev_start = start
            if source not in sources:
                sources.append(source)
            stages.append(Stage(name=name, start_tokens=start, source=source))

        schedule = cls(
            total_tokens=total_tokens,
            seed_data=seed_data,
            stages=stages,
            total_batch_size=int(total_batch_size),
            max_epochs=float(cfg.get("max_epochs", max_epochs)),
            sources=sources,
        )
        schedule._convert_to_steps()
        return schedule

    def _convert_to_steps(self):
        """Snap the token horizon and each stage boundary to whole optimizer steps.

        Token counts are authoritative; steps are derived. Each start_tokens boundary is
        rounded to the nearest whole step, preserving strict ordering.
        """
        b = self.total_batch_size
        self.total_steps = self.total_tokens // b
        if self.total_steps <= 0:
            raise ValueError(
                f"total_tokens={self.total_tokens} is smaller than one global batch "
                f"({b}); nothing to train"
            )
        snapped = []
        prev_step = -1
        for st in self.stages:
            step = int(round(st.start_tokens / b))
            step = max(step, 0)
            if step <= prev_step:
                step = prev_step + 1  # preserve strict ordering after snapping
            if step >= self.total_steps and st is not self.stages[0]:
                raise ValueError(
                    f"stage {st.name!r} snaps to step {step} >= total_steps "
                    f"{self.total_steps}; boundary too close to the horizon for this "
                    f"batch size"
                )
            prev_step = step
            snapped.append(Stage(st.name, st.start_tokens, st.source, start_step=step))
        self.stages = snapped

    # --- stage lookup (pure) --------------------------------------------------------

    def stage_for_step(self, step: int) -> Stage:
        """Active stage for a given optimizer step. Pure; no mutable state."""
        active = self.stages[0]
        for st in self.stages:
            if step >= st.start_step:
                active = st
            else:
                break
        return active

    def stage_for_tokens(self, cumulative_tokens: int) -> Stage:
        """Active stage for a given cumulative global token count. Pure."""
        active = self.stages[0]
        for st in self.stages:
            if cumulative_tokens >= st.start_tokens:
                active = st
            else:
                break
        return active

    def stage_index(self, stage: Stage) -> int:
        return self.stages.index(stage)

    def stage_bounds_steps(self, idx: int):
        """(start_step, end_step_exclusive) for stage idx."""
        start = self.stages[idx].start_step
        end = self.stages[idx + 1].start_step if idx + 1 < len(self.stages) else self.total_steps
        return start, end

    # --- planning / epoch accounting ------------------------------------------------

    def planned_tokens_per_source(self) -> Dict[str, int]:
        """Total tokens drawn per source across the whole schedule, at step granularity.

        Each stage spans [start_step, end_step) whole steps == that many * total_batch_size
        tokens, all drawn from that stage's single source. If two stages share a source
        their tokens accumulate.
        """
        totals = {s: 0 for s in self.sources}
        b = self.total_batch_size
        for idx, st in enumerate(self.stages):
            start_step, end_step = self.stage_bounds_steps(idx)
            totals[st.source] += (end_step - start_step) * b
        return totals

    def planned_tokens_per_stage(self) -> List[int]:
        b = self.total_batch_size
        out = []
        for idx in range(len(self.stages)):
            start_step, end_step = self.stage_bounds_steps(idx)
            out.append((end_step - start_step) * b)
        return out

    def realized_epochs(self, source_tokens: Dict[str, int], source_unique_tokens: Dict[str, int]) -> Dict[str, float]:
        return {
            s: (source_tokens.get(s, 0) / source_unique_tokens[s])
            if source_unique_tokens.get(s)
            else 0.0
            for s in self.sources
        }

    def check_epoch_cap(self, source_unique_tokens: Dict[str, int]):
        """Hard-enforce the epoch cap using real per-source cache sizes.

        Raises ValueError if the schedule implies more than ``max_epochs`` passes over any
        source. ``source_unique_tokens`` maps source name -> unique tokens available in its
        cache (from the cache meta.json ``train_tokens``).
        """
        planned = self.planned_tokens_per_source()
        problems = []
        for s in self.sources:
            unique = source_unique_tokens.get(s, 0)
            drawn = planned.get(s, 0)
            if drawn == 0:
                continue
            if unique <= 0:
                problems.append(f"{s!r}: schedule draws {drawn:,} tokens but cache is empty")
                continue
            epochs = drawn / unique
            if epochs > self.max_epochs + 1e-9:
                problems.append(
                    f"{s!r}: schedule draws {drawn:,} tokens over {unique:,} unique "
                    f"({epochs:.2f} epochs) > max_epochs={self.max_epochs}"
                )
        if problems:
            raise ValueError(
                "mixture_schedule exceeds the epoch cap:\n  " + "\n  ".join(problems)
            )

    def as_metadata(self) -> dict:
        """JSON-serializable snapshot for W&B run metadata / checkpoints."""
        return {
            "total_tokens": self.total_tokens,
            "seed_data": self.seed_data,
            "total_batch_size": self.total_batch_size,
            "total_steps": self.total_steps,
            "max_epochs": self.max_epochs,
            "sources": list(self.sources),
            "stages": [
                {
                    "name": st.name,
                    "start_tokens": st.start_tokens,
                    "start_step": st.start_step,
                    "source": st.source,
                }
                for st in self.stages
            ],
        }


# -----------------------------------------------------------------------------
# Loader


class MixtureLoader:
    """Stage-scheduled loader that switches which pretokenized source it reads at each
    stage boundary. The per-stage data ratio is already baked into the source datasets,
    so there is no on-the-fly blending here.

    Yields ``(inputs, targets, state_dict)`` like the single-source loader. The
    ``state_dict`` carries a ``mixture`` sub-dict: per-source cursors, cumulative tokens
    per source, and cumulative global tokens -- everything needed to resume in the correct
    stage/source.
    """

    def __init__(
        self,
        B,
        T,
        split,
        device,
        source_dirs: Dict[str, str],
        schedule: MixtureSchedule,
        resume_state_dict: Optional[dict] = None,
        micro_batches_per_step: int = 1,
    ):
        import torch
        from nanochat.pretok_dataloader import _load_split_files, _TokenCursor

        self._torch = torch
        self._TokenCursor = _TokenCursor

        self.B = B
        self.T = T
        self.split = split
        self.device = device
        self.schedule = schedule
        self.micro_batches_per_step = int(micro_batches_per_step)
        self.tokens_per_microbatch = B * T
        self.tokens_per_step = self.tokens_per_microbatch * self.micro_batches_per_step

        self.sources = list(schedule.sources)
        self._arrays = {}
        self._sizes = {}
        self._cursors: Dict[str, _TokenCursor] = {}

        resume_mix = (resume_state_dict or {}).get("mixture") if resume_state_dict else None

        for s in self.sources:
            data_dir = source_dirs[s]
            arrays, sizes = _load_split_files(split, data_dir)
            self._arrays[s] = arrays
            self._sizes[s] = sizes
            cur_state = (resume_mix or {}).get("cursors", {}).get(s) if resume_mix else None
            if cur_state is None:
                cursor = _TokenCursor(arrays, sizes, file_idx=0, pos=0, epoch=1)
            else:
                cursor = _TokenCursor(
                    arrays,
                    sizes,
                    file_idx=cur_state.get("file_idx", 0),
                    pos=cur_state.get("pos", 0),
                    epoch=cur_state.get("epoch", 1),
                )
            self._cursors[s] = cursor

        # Running ledgers (restored on resume).
        if resume_mix is not None:
            self.cumulative_tokens = int(resume_mix.get("cumulative_tokens", 0))
            self.source_tokens = {s: int(resume_mix.get("source_tokens", {}).get(s, 0)) for s in self.sources}
        else:
            self.cumulative_tokens = 0
            self.source_tokens = {s: 0 for s in self.sources}

        read_tokens = self.tokens_per_microbatch + 1
        use_cuda = device == "cuda"
        self._cpu_buffer = torch.empty(read_tokens, dtype=torch.long, pin_memory=use_cuda)
        self._gpu_buffer = torch.empty(read_tokens, dtype=torch.long, device=device)
        self._read_tokens = read_tokens
        self._use_cuda = use_cuda

    # --- state ----------------------------------------------------------------------

    def _active_stage(self):
        return self.schedule.stage_for_tokens(self.cumulative_tokens)

    def _active_source(self):
        return self._active_stage().source

    def _read_microbatch(self, source: str):
        cursor = self._cursors[source]
        batch_np = cursor.read(self._read_tokens).astype("int64", copy=False)
        self._cpu_buffer.copy_(self._torch.from_numpy(batch_np))
        self._gpu_buffer.copy_(self._cpu_buffer, non_blocking=self._use_cuda)
        flat_x = self._gpu_buffer[:-1]
        flat_y = self._gpu_buffer[1:]
        return flat_x.view(self.B, self.T), flat_y.view(self.B, self.T)

    def state_dict(self):
        return {
            # Aliases so base_train logging that reads file_idx/pos/epoch still works;
            # they mirror the currently-active source's cursor.
            **self._active_cursor_aliases(),
            "mixture": {
                "cursors": {s: self._cursors[s].state_dict() for s in self.sources},
                "cumulative_tokens": self.cumulative_tokens,
                "source_tokens": dict(self.source_tokens),
                "active_stage_idx": self.schedule.stage_index(self._active_stage()),
            },
        }

    def wandb_log_fields(self):
        """Mixture fields to log to W&B on every eval: active stage name, active source,
        cumulative tokens per source, and epochs per source."""
        stage = self._active_stage()
        fields = {
            "mixture/active_stage": stage.name,
            "mixture/active_source": stage.source,
        }
        for s in self.sources:
            fields[f"mixture/cumulative_tokens/{s}"] = self.source_tokens[s]
            unique = self._source_unique_tokens(s)
            fields[f"mixture/epochs/{s}"] = (self.source_tokens[s] / unique) if unique else 0.0
        return fields

    def _source_unique_tokens(self, source):
        return int(sum(self._sizes[source]))

    def _active_cursor_aliases(self):
        cs = self._cursors[self._active_source()].state_dict()
        return {
            "file_idx": cs["file_idx"],
            "pos": cs["pos"],
            "epoch": cs["epoch"],
            "pq_idx": cs["file_idx"],
            "rg_idx": cs["pos"],
        }

    def __iter__(self):
        return self

    def __next__(self):
        source = self._active_source()
        x, y = self._read_microbatch(source)
        add = self.tokens_per_microbatch
        self.source_tokens[source] += add
        self.cumulative_tokens += add
        sd = self.state_dict()
        return x, y, sd


def mixture_data_loader(*args, **kwargs):
    """Helper that omits state_dict from yields (parity with single-source helper)."""
    loader = MixtureLoader(*args, **kwargs)
    for x, y, _ in loader:
        yield x, y
