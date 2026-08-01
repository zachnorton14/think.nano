"""
Tests for multi-stage data-mixture pretraining support.

The first and most important test (test_single_stage_reproduces_baseline_bitforbit)
is a *baseline lock*: it captures the exact token stream and resume behavior of the
existing single-source pretokenized dataloader, then asserts that a single-stage,
100%-`original` mixture schedule reproduces that stream byte-for-byte with identical
per-source cursor state. Per the project constraint, a single-stage 100% `original`
config must reproduce the current baseline exactly -- same data order, same RNG draws
(there are none in the pretokenized path), same cursor advancement.

This file is written BEFORE the mixture implementation exists. Tests that exercise the
not-yet-written module are guarded so that the baseline lock runs and passes on its own;
they activate automatically once `nanochat.mixture` lands.
"""

import json
import os

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from nanochat.pretok_dataloader import pretokenized_data_loader_with_state


# -----------------------------------------------------------------------------
# Helpers: build tiny deterministic uint16 token caches on disk.


def _write_cache(directory, train_shards, val_tokens):
    """Write a minimal pretokenized cache dir with the given train/val token content.

    train_shards: list of 1-D uint16-compatible sequences, one per train_*.bin shard.
    val_tokens:   1-D sequence written as a single val_00000.bin.
    Returns the meta dict that was written.
    """
    os.makedirs(directory, exist_ok=True)
    train_files = []
    for i, shard in enumerate(train_shards):
        arr = np.asarray(shard, dtype=np.uint16)
        name = f"train_{i:05d}.bin"
        arr.tofile(os.path.join(directory, name))
        train_files.append({"filename": name, "num_tokens": int(len(arr))})
    val_arr = np.asarray(val_tokens, dtype=np.uint16)
    val_arr.tofile(os.path.join(directory, "val_00000.bin"))
    meta = {
        "dtype": "uint16",
        "train_tokens": int(sum(len(np.asarray(s)) for s in train_shards)),
        "val_tokens": int(len(val_arr)),
        "train_files": train_files,
        "val_files": [{"filename": "val_00000.bin", "num_tokens": int(len(val_arr))}],
    }
    with open(os.path.join(directory, "meta.json"), "w") as f:
        json.dump(meta, f)
    return meta


def _drain(loader, n):
    """Pull n batches, returning list of (flat_x_tokens, state_dict)."""
    out = []
    for _ in range(n):
        x, y, sd = next(loader)
        out.append((x.flatten().tolist(), dict(sd)))
    return out


# -----------------------------------------------------------------------------
# Baseline lock. Runs today against the existing single-source dataloader.


def _baseline_original_dir(tmp_path):
    """A cache resembling the `original` corpus: two train shards, one val shard."""
    directory = str(tmp_path / "original_cache")
    _write_cache(
        directory,
        train_shards=[
            list(range(0, 1000)),      # train_00000.bin
            list(range(1000, 1600)),   # train_00001.bin
        ],
        val_tokens=list(range(5000, 5300)),
    )
    return directory


def test_baseline_dataloader_stream_and_resume(tmp_path):
    """Golden reference: capture the exact single-source stream + resume behavior.

    This does not depend on the mixture module. It documents the invariant that the
    mixture loader's single-100%-source fast path must later reproduce exactly:
      - batches read B*T+1 tokens and advance the cursor by B*T+1 (one-token overlap),
      - a state_dict captured mid-stream resumes the *next* batch identically.
    If this test ever changes, the baseline itself changed and every reproduction
    guarantee downstream must be re-examined.
    """
    directory = _baseline_original_dir(tmp_path)
    B, T = 2, 4

    loader = pretokenized_data_loader_with_state(B, T, "train", device="cpu", data_dir=directory)
    batches = _drain(loader, 3)

    xs = [b[0] for b in batches]
    # Deterministic, contiguous, one-token overlap between consecutive batches.
    assert xs[0] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert xs[1] == [9, 10, 11, 12, 13, 14, 15, 16]
    assert xs[2] == [18, 19, 20, 21, 22, 23, 24, 25]

    # Resume from the state captured after batch 0 reproduces batch 1 exactly.
    resume_state = batches[0][1]
    resumed = pretokenized_data_loader_with_state(
        B, T, "train", device="cpu", data_dir=directory, resume_state_dict=resume_state
    )
    rx, _, _ = next(resumed)
    assert rx.flatten().tolist() == xs[1]


# -----------------------------------------------------------------------------
# Reproduction lock against the mixture loader (activates once the module lands).
#
# NB: use a per-test skip (not module-level importorskip) so the baseline lock above
# always runs, even before nanochat.mixture exists.

try:
    from nanochat import mixture
except ImportError:
    mixture = None

requires_mixture = pytest.mark.skipif(
    mixture is None, reason="nanochat.mixture not implemented yet; baseline lock still runs."
)


def _single_stage_schedule(total_tokens, total_batch_size, seed_data=1234):
    return {
        "total_tokens": total_tokens,
        "seed_data": seed_data,
        "stages": [
            {"name": "base", "start_tokens": 0, "source": "original"},
        ],
    }


@requires_mixture
def test_single_stage_reproduces_baseline_bitforbit(tmp_path):
    """A single-stage schedule reading 'original' must equal the raw single-source stream.

    Same token order, same cursor advancement, and (critically) zero RNG draws: with no
    cross-source blending, one stage reads exactly one source's cursor.
    """
    original_dir = _baseline_original_dir(tmp_path)
    midtrain_dir = str(tmp_path / "midtrain_cache")
    _write_cache(midtrain_dir, train_shards=[list(range(20000, 20500))], val_tokens=list(range(9000, 9100)))

    B, T = 2, 4
    total_batch_size = B * T  # single "rank", one micro-step per step for the test

    # Golden reference from the raw single-source loader.
    ref = _drain(
        pretokenized_data_loader_with_state(B, T, "train", device="cpu", data_dir=original_dir),
        5,
    )
    ref_xs = [r[0] for r in ref]

    schedule = mixture.MixtureSchedule.from_config(
        _single_stage_schedule(total_tokens=10_000, total_batch_size=total_batch_size),
        total_batch_size=total_batch_size,
    )
    loader = mixture.MixtureLoader(
        B, T, split="train", device="cpu",
        source_dirs={"original": original_dir, "midtrain": midtrain_dir},
        schedule=schedule,
    )
    mix_xs = [x.flatten().tolist() for x, y, sd in (next(loader) for _ in range(5))]

    assert mix_xs == ref_xs, "single-stage 'original' must be byte-identical to baseline"


# -----------------------------------------------------------------------------
# Shared multi-source fixtures for the remaining behavioral tests. Each source is a
# whole, already-ratioed dataset; the loader switches sources at stage boundaries.


def _three_source_dirs(tmp_path):
    """Three sources with disjoint id ranges so a test can tell which one a batch came
    from: original [0,20000), r30 [30000,50000), r60 [60000,64000)."""
    d = {
        "original": str(tmp_path / "orig"),
        "midtrain_r30": str(tmp_path / "r30"),
        "midtrain_r60": str(tmp_path / "r60"),
    }
    _write_cache(d["original"], train_shards=[list(range(0, 20000))], val_tokens=[7] * 200)
    _write_cache(d["midtrain_r30"], train_shards=[list(range(30000, 50000))], val_tokens=[30001] * 200)
    _write_cache(d["midtrain_r60"], train_shards=[list(range(60000, 64000))], val_tokens=[60001] * 200)
    return d


def _three_stage_schedule(total_tokens, b1, b2, seed_data=1234, max_epochs=4):
    return {
        "total_tokens": total_tokens,
        "seed_data": seed_data,
        "max_epochs": max_epochs,
        "stages": [
            {"name": "base", "start_tokens": 0, "source": "original"},
            {"name": "injection", "start_tokens": b1, "source": "midtrain_r30"},
            {"name": "decay_mix", "start_tokens": b2, "source": "midtrain_r60"},
        ],
    }


def _source_of_token(tok):
    if tok < 20000:
        return "original"
    if 30000 <= tok < 50000:
        return "midtrain_r30"
    return "midtrain_r60"


@requires_mixture
def test_active_source_matches_stage_every_step(tmp_path):
    """Each stage reads exactly its configured source: every batch's tokens come from the
    source that the active stage names -- no blending, no leakage across stages."""
    dirs = _three_source_dirs(tmp_path)
    B, T = 4, 8
    tbs = B * T  # one micro-batch per step
    # boundaries at 3200 and 4800 tokens (== steps 100 and 150).
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(6400, b1=3200, b2=4800), total_batch_size=tbs
    )
    loader = mixture.MixtureLoader(B, T, "train", "cpu", source_dirs=dirs, schedule=sched)
    for _ in range(200):
        x, y, sd = next(loader)
        prev_cum = sd["mixture"]["cumulative_tokens"] - tbs
        expected_source = sched.stage_for_tokens(prev_cum).source
        got_source = _source_of_token(x.flatten().tolist()[0])
        assert got_source == expected_source, (
            f"at cum={prev_cum} expected {expected_source} got {got_source}"
        )


@requires_mixture
def test_resume_lands_in_correct_stage_and_continues_cursors(tmp_path):
    """Resuming from a mid-run checkpoint lands in the correct stage (derived purely from
    cumulative tokens) and continues each source's cursor -- no source restarts."""
    dirs = _three_source_dirs(tmp_path)
    B, T = 4, 8
    tbs = B * T
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(6400, b1=3200, b2=4800), total_batch_size=tbs
    )
    loader = mixture.MixtureLoader(B, T, "train", "cpu", source_dirs=dirs, schedule=sched)
    saved = None
    for step in range(120):  # cum == 3840 -> in the injection stage
        _, _, sd = next(loader)
        if step == 119:
            saved = json.loads(json.dumps(sd))  # emulate a checkpoint round-trip through JSON

    cum = saved["mixture"]["cumulative_tokens"]
    assert sched.stage_for_tokens(cum).name == "injection"

    resumed = mixture.MixtureLoader(
        B, T, "train", "cpu", source_dirs=dirs, schedule=sched, resume_state_dict=saved
    )
    # Every source's cursor continues exactly where it was saved (no restart).
    for s in dirs:
        assert resumed._cursors[s].state_dict()["pos"] == saved["mixture"]["cursors"][s]["pos"]
        assert resumed._cursors[s].state_dict()["file_idx"] == saved["mixture"]["cursors"][s]["file_idx"]
    # Cumulative ledger restored; the next batch is still the injection source.
    _, _, sd2 = next(resumed)
    prev_cum = sd2["mixture"]["cumulative_tokens"] - tbs
    assert sched.stage_for_tokens(prev_cum).name == "injection"


@requires_mixture
def test_resume_at_exact_boundary_lands_in_next_stage(tmp_path):
    """A checkpoint taken exactly at a stage boundary resumes into the new stage/source,
    with no special-casing -- the active stage is a pure function of cumulative tokens."""
    dirs = _three_source_dirs(tmp_path)
    B, T = 4, 8
    tbs = B * T
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(6400, b1=3200, b2=4800), total_batch_size=tbs
    )
    loader = mixture.MixtureLoader(B, T, "train", "cpu", source_dirs=dirs, schedule=sched)
    saved = None
    for step in range(100):  # after 100 draws, cumulative == 3200 exactly (boundary 1)
        _, _, sd = next(loader)
        saved = json.loads(json.dumps(sd))
    assert saved["mixture"]["cumulative_tokens"] == 3200
    assert sched.stage_for_tokens(3200).name == "injection"
    resumed = mixture.MixtureLoader(
        B, T, "train", "cpu", source_dirs=dirs, schedule=sched, resume_state_dict=saved
    )
    x, _, sd2 = next(resumed)
    assert sched.stage_for_tokens(sd2["mixture"]["cumulative_tokens"] - tbs).name == "injection"
    assert _source_of_token(x.flatten().tolist()[0]) == "midtrain_r30"


# -----------------------------------------------------------------------------
# Schedule-level tests (pure Python, torch-free).


@requires_mixture
def test_epoch_cap_enforced(tmp_path):
    """check_epoch_cap raises when the schedule draws more than max_epochs over a source,
    and passes when within the cap. A stage's whole span is drawn from its single source."""
    tbs = 524288
    # base -> original for [0, 2B); mix -> midtrain for [2B, 10B) == ~8B tokens.
    sched = mixture.MixtureSchedule.from_config(
        {
            "total_tokens": 10_000_000_000,
            "seed_data": 1,
            "max_epochs": 4,
            "stages": [
                {"name": "base", "start_tokens": 0, "source": "original"},
                {"name": "mix", "start_tokens": 2_000_000_000, "source": "midtrain"},
            ],
        },
        total_batch_size=tbs,
    )
    # midtrain draws ~8B tokens; a 1B-token cache => ~8 epochs => must fail.
    with pytest.raises(ValueError, match="epoch cap"):
        sched.check_epoch_cap({"original": 22_000_000_000, "midtrain": 1_000_000_000})
    # A big enough midtrain cache stays within the cap.
    sched.check_epoch_cap({"original": 22_000_000_000, "midtrain": 3_000_000_000})


@requires_mixture
def test_boundaries_snap_to_whole_steps_and_log_both(tmp_path):
    """Token counts are authoritative; boundaries convert to whole steps at load."""
    tbs = 524288
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(10_000_000_000, b1=7_000_000_000, b2=9_000_000_000),
        total_batch_size=tbs,
    )
    assert sched.total_steps == 10_000_000_000 // tbs
    assert sched.stages[0].start_step == 0
    assert sched.stages[1].start_step == round(7_000_000_000 / tbs)
    assert sched.stages[2].start_step == round(9_000_000_000 / tbs)
    steps = [st.start_step for st in sched.stages]
    assert steps == sorted(steps) and len(set(steps)) == len(steps)


@requires_mixture
def test_planner_is_deterministic_and_tokens_exact(tmp_path):
    """Planner per-source token totals are stable and sum to the whole-step horizon.
    Each stage's tokens are attributed entirely to its single source."""
    tbs = 524288
    cfg = _three_stage_schedule(10_000_000_000, b1=7_000_000_000, b2=9_000_000_000)
    a = mixture.MixtureSchedule.from_config(cfg, total_batch_size=tbs)
    b = mixture.MixtureSchedule.from_config(cfg, total_batch_size=tbs)
    assert a.planned_tokens_per_source() == b.planned_tokens_per_source()
    totals = a.planned_tokens_per_source()
    # base span in whole steps * tbs goes entirely to original; each mixed span to its src.
    s0, s1 = a.stage_bounds_steps(0)
    assert totals["original"] == (s1 - s0) * tbs
    assert sum(totals.values()) == a.total_steps * tbs


@requires_mixture
def test_continuation_planner_clips_at_exact_stage_boundary():
    tbs = 100
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(1000, b1=500, b2=800), total_batch_size=tbs
    )

    planned = sched.planned_tokens_per_source(start_tokens=500)

    assert planned == {"original": 0, "midtrain_r30": 300, "midtrain_r60": 200}
    assert sched.active_sources(start_tokens=500) == ["midtrain_r30", "midtrain_r60"]


@requires_mixture
def test_continuation_planner_clips_inside_stage():
    tbs = 100
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(1000, b1=500, b2=800), total_batch_size=tbs
    )

    planned = sched.planned_tokens_per_source(start_tokens=600)

    assert planned == {"original": 0, "midtrain_r30": 200, "midtrain_r60": 200}
    # An inherited source needs no cache and is ignored by epoch-cap validation.
    sched.check_epoch_cap(
        {"midtrain_r30": 100, "midtrain_r60": 100}, start_tokens=600
    )


@requires_mixture
def test_continuation_loader_requires_every_future_source(tmp_path):
    dirs = _three_source_dirs(tmp_path)
    dirs.pop("original")
    dirs.pop("midtrain_r60")
    tbs = 32
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(6400, b1=3200, b2=4800), total_batch_size=tbs
    )

    with pytest.raises(ValueError, match="current/future.*midtrain_r60"):
        mixture.MixtureLoader(
            4, 8, "train", "cpu", source_dirs=dirs, schedule=sched,
            initial_cumulative_tokens=4000,
        )


@requires_mixture
@pytest.mark.parametrize("bad,match", [
    # first stage must start at 0
    ({"total_tokens": 1000, "seed_data": 1, "stages": [
        {"name": "a", "start_tokens": 100, "source": "original"}]}, "first stage"),
    # start_tokens strictly increasing
    ({"total_tokens": 1000, "seed_data": 1, "stages": [
        {"name": "a", "start_tokens": 0, "source": "original"},
        {"name": "b", "start_tokens": 0, "source": "midtrain"}]}, "strictly increasing"),
    # every stage must name a source
    ({"total_tokens": 1000, "seed_data": 1, "stages": [
        {"name": "a", "start_tokens": 0}]}, "single string 'source'"),
    # boundary beyond the horizon
    ({"total_tokens": 1000, "seed_data": 1, "stages": [
        {"name": "a", "start_tokens": 0, "source": "original"},
        {"name": "b", "start_tokens": 5000, "source": "midtrain"}]}, ">= total_tokens"),
])
def test_schedule_validation_rejects_bad_configs(bad, match):
    mod = pytest.importorskip("nanochat.mixture")
    with pytest.raises(ValueError, match=match):
        mod.MixtureSchedule.from_config(bad, total_batch_size=100)


# -----------------------------------------------------------------------------
# Rank sharding. The mixture loader must shard the active source across ranks exactly
# like the single-source loader does, or every rank trains on identical tokens and the
# token ledger -- which drives stage selection -- advances world_size times too slowly.


@pytest.fixture
def as_rank(monkeypatch):
    """Make both loaders believe this process is rank `rank` of `world_size`.

    MixtureLoader imports get_dist_info inside __init__ and pretok_dataloader imports it
    at module scope, so both names have to be patched.
    """
    def apply(rank, world_size):
        info = (world_size > 1, rank, rank, world_size)
        monkeypatch.setattr("nanochat.common.get_dist_info", lambda: info)
        monkeypatch.setattr("nanochat.pretok_dataloader.get_dist_info", lambda: info)
    return apply


@pytest.fixture
def build_ranks(as_rank):
    """Build one loader per rank of a fake world, sharing a schedule and sources."""
    def build(world_size, dirs, sched, B, T, resume_state_dicts=None):
        loaders = []
        for rank in range(world_size):
            as_rank(rank, world_size)
            loaders.append(mixture.MixtureLoader(
                B, T, "train", "cpu", source_dirs=dirs, schedule=sched,
                resume_state_dict=(resume_state_dicts or {}).get(rank),
            ))
        return loaders
    return build


def test_single_source_resume_restores_every_rank_to_its_own_window(tmp_path, as_rank):
    """The single-source loader has the same rank-0-only checkpoint: a resumed rank must
    replay the pending end-of-loop skip and re-apply its own offset, or all ranks read
    rank 0's stream in lockstep for the rest of the run."""
    directory = _baseline_original_dir(tmp_path)
    B, T, world_size = 2, 4, 4

    # It is a generator, so the body -- including get_dist_info() -- does not run until
    # the first next(). Prime each one while its own rank is patched in.
    loaders, drawn = [], []
    for rank in range(world_size):
        as_rank(rank, world_size)
        loader = pretokenized_data_loader_with_state(
            B, T, "train", device="cpu", data_dir=directory
        )
        drawn.append(next(loader))
        loaders.append(loader)
    saved = drawn[0][2]
    for _ in range(2):
        drawn = [next(loader) for loader in loaders]
        saved = drawn[0][2]  # only rank 0's state is checkpointed
    expected = [next(loader)[0].flatten().tolist() for loader in loaders]
    assert len({tuple(w) for w in expected}) == world_size, "ranks overlap before resume"

    rank0_state = json.loads(json.dumps(saved))
    got = []
    for rank in range(world_size):
        as_rank(rank, world_size)
        resumed = pretokenized_data_loader_with_state(
            B, T, "train", device="cpu", data_dir=directory,
            resume_state_dict=rank0_state,
        )
        got.append(next(resumed)[0].flatten().tolist())
    assert got == expected, "resumed ranks did not land back on their own windows"


@requires_mixture
def test_ranks_read_disjoint_windows(tmp_path, build_ranks):
    """Across a 4-rank world every rank draws a different window of the active source,
    and together they tile the stream contiguously."""
    dirs = _three_source_dirs(tmp_path)
    B, T, world_size = 2, 8, 4
    tbs = B * T * world_size
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(64000, b1=32000, b2=48000), total_batch_size=tbs
    )
    loaders = build_ranks(world_size, dirs, sched, B, T)
    for _ in range(6):
        windows = [next(loader)[0].flatten().tolist() for loader in loaders]
        assert len({w[0] for w in windows}) == world_size, (
            f"ranks read overlapping windows: {[w[0] for w in windows]}"
        )
        flat = [tok for w in windows for tok in w]
        assert flat == list(range(flat[0], flat[0] + len(flat))), (
            "ranks do not tile the source contiguously"
        )


@requires_mixture
def test_token_ledger_counts_global_tokens(tmp_path, build_ranks):
    """The ledger advances by the whole global batch per draw, so a boundary declared in
    global tokens lands on the step the schedule says -- not world_size times later."""
    dirs = _three_source_dirs(tmp_path)
    B, T, world_size = 2, 8, 4
    tbs = B * T * world_size  # one micro-batch per rank per step
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(6400, b1=3200, b2=4800), total_batch_size=tbs
    )
    assert sched.stage_for_tokens(3200).name == "injection"
    loader = build_ranks(world_size, dirs, sched, B, T)[0]
    switched_at = None
    for step in range(1, 60):
        x, _, sd = next(loader)
        assert sd["mixture"]["cumulative_tokens"] == step * tbs
        if switched_at is None and _source_of_token(x.flatten().tolist()[0]) != "original":
            switched_at = step
    assert switched_at == 51, (
        f"injection fired on draw {switched_at}, expected 51 (the draw after cum hits 3200)"
    )


@requires_mixture
def test_resume_restores_every_rank_to_its_own_window(tmp_path, build_ranks):
    """Only rank 0's cursors are checkpointed, so on resume every rank must re-derive its
    own offset from that one saved position or the world collapses onto rank 0's stream."""
    dirs = _three_source_dirs(tmp_path)
    B, T, world_size = 2, 8, 4
    tbs = B * T * world_size
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(64000, b1=32000, b2=48000), total_batch_size=tbs
    )
    loaders = build_ranks(world_size, dirs, sched, B, T)
    for _ in range(5):
        saved = [next(loader)[2] for loader in loaders]
    expected = [next(loader)[0].flatten().tolist() for loader in loaders]

    # Every rank resumes from rank 0's checkpointed state, as base_train does.
    rank0_state = json.loads(json.dumps(saved[0]))
    resumed = build_ranks(
        world_size, dirs, sched, B, T,
        resume_state_dicts={rank: rank0_state for rank in range(world_size)},
    )
    got = [next(loader)[0].flatten().tolist() for loader in resumed]
    assert got == expected, "resumed ranks did not land back on their own windows"
    assert len({w[0] for w in got}) == world_size, "ranks collapsed onto one stream"


@requires_mixture
def test_single_rank_stream_is_unchanged_by_sharding(tmp_path, build_ranks):
    """The world_size == 1 stream must stay byte-identical to the unsharded behavior."""
    dirs = _three_source_dirs(tmp_path)
    B, T = 4, 8
    tbs = B * T
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(6400, b1=3200, b2=4800), total_batch_size=tbs
    )
    loader = build_ranks(1, dirs, sched, B, T)[0]
    xs = [next(loader)[0].flatten().tolist() for _ in range(40)]
    ref = mixture.MixtureLoader(B, T, "train", "cpu", source_dirs=dirs, schedule=sched)
    assert xs == [next(ref)[0].flatten().tolist() for _ in range(40)]


# -----------------------------------------------------------------------------
# Branching. Stage boundaries are absolute token counts over a lineage, so a branched run
# enters the schedule at the tokens its parent already trained on.


@requires_mixture
def test_branch_offset_enters_the_schedule_mid_stage(tmp_path):
    """Seeded with a parent's token count past the first boundary, the loader's very first
    draw comes from the injection source rather than restarting at stage 0."""
    dirs = _three_source_dirs(tmp_path)
    dirs.pop("original")  # inherited stage: no cache exists on this cluster
    B, T = 4, 8
    tbs = B * T
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(6400, b1=3200, b2=4800), total_batch_size=tbs
    )
    loader = mixture.MixtureLoader(
        B, T, "train", "cpu", source_dirs=dirs, schedule=sched,
        initial_cumulative_tokens=3200 + tbs,  # a branch taken just past the boundary
    )
    x, _, sd = next(loader)
    assert _source_of_token(x.flatten().tolist()[0]) == "midtrain_r30"
    assert sd["mixture"]["cumulative_tokens"] == 3200 + 2 * tbs
    # source_tokens report what THIS run drew, so the parent's tokens are not credited.
    assert sd["mixture"]["source_tokens"]["original"] == 0
    assert sd["mixture"]["source_tokens"]["midtrain_r30"] == tbs


@requires_mixture
def test_branch_offset_still_reaches_the_final_stage_on_time(tmp_path):
    """A branch taken inside injection switches to decay_mix at the absolute boundary."""
    dirs = _three_source_dirs(tmp_path)
    B, T = 4, 8
    tbs = B * T
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(6400, b1=3200, b2=4800), total_batch_size=tbs
    )
    start = 4000  # inside injection; 25 draws of tbs=32 remain before decay_mix at 4800
    loader = mixture.MixtureLoader(
        B, T, "train", "cpu", source_dirs=dirs, schedule=sched,
        initial_cumulative_tokens=start,
    )
    sources = [_source_of_token(next(loader)[0].flatten().tolist()[0]) for _ in range(30)]
    assert sources[:25] == ["midtrain_r30"] * 25
    assert sources[25:] == ["midtrain_r60"] * 5


@requires_mixture
def test_resume_ignores_the_branch_offset(tmp_path):
    """A resumed run restores its own ledger; re-applying the branch offset would double
    count and jump the run forward through its own schedule."""
    dirs = _three_source_dirs(tmp_path)
    B, T = 4, 8
    tbs = B * T
    sched = mixture.MixtureSchedule.from_config(
        _three_stage_schedule(6400, b1=3200, b2=4800), total_batch_size=tbs
    )
    loader = mixture.MixtureLoader(
        B, T, "train", "cpu", source_dirs=dirs, schedule=sched,
        initial_cumulative_tokens=3200,
    )
    for _ in range(4):
        _, _, sd = next(loader)
    saved = json.loads(json.dumps(sd))
    assert saved["mixture"]["cumulative_tokens"] == 3200 + 4 * tbs

    # An older checkpoint may carry a cursor for the inherited source. A new cluster is
    # allowed to omit that cache and safely ignore the stale cursor.
    continuation_dirs = {name: path for name, path in dirs.items() if name != "original"}
    resumed = mixture.MixtureLoader(
        B, T, "train", "cpu", source_dirs=continuation_dirs, schedule=sched,
        resume_state_dict=saved, initial_cumulative_tokens=3200,
    )
    assert "original" not in resumed._cursors
    _, _, sd2 = next(resumed)
    assert sd2["mixture"]["cumulative_tokens"] == 3200 + 5 * tbs
