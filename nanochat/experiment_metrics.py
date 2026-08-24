"""Compute and W&B metric helpers shared by lineage-aware training stages."""


WANDB_STEP_METRICS = (
    "train/*",
    "val/*",
    "eval/*",
    "core_metric",
    "centered_results.*",
    "chatcore_metric",
    "chatcore_cat",
    "chatcore/*",
    "reward",
    "pass@*",
    "lrm",
)


def training_flops(processed_tokens, training_flops_per_token):
    return float(processed_tokens) * float(training_flops_per_token)


def fixed_batch_stage_flops(
    completed_steps, total_batch_size, training_flops_per_token
):
    return training_flops(
        int(completed_steps) * int(total_batch_size),
        training_flops_per_token,
    )


def rollout_generation_flops(model_token_invocations, training_flops_per_token):
    # The model estimate is forward + backward; rollout generation is forward-only.
    return float(model_token_invocations) * (float(training_flops_per_token) / 3.0)


def cumulative_pipeline_flops(stage_flops, inherited_parent_flops):
    return float(stage_flops) + float(inherited_parent_flops)


def compute_log_fields(step, stage_flops, inherited_parent_flops=0.0):
    stage_flops = float(stage_flops)
    inherited_parent_flops = float(inherited_parent_flops)
    cumulative_flops = cumulative_pipeline_flops(
        stage_flops, inherited_parent_flops
    )
    return {
        "step": int(step),
        "total_training_flops": cumulative_flops,
        "stage_training_flops": stage_flops,
        "inherited_parent_flops": inherited_parent_flops,
        "cumulative_pipeline_training_flops": cumulative_flops,
    }


def checkpoint_compute_fields(meta, fallback_step=0):
    loop_state = meta.get("loop_state", {})
    step = int(meta.get("step", loop_state.get("step", fallback_step)))
    stage_flops = float(loop_state.get("stage_training_flops", 0.0))
    inherited_parent_flops = float(
        loop_state.get("inherited_parent_flops", 0.0)
    )
    fields = compute_log_fields(step, stage_flops, inherited_parent_flops)
    if "cumulative_pipeline_training_flops" in loop_state:
        cumulative_flops = float(
            loop_state["cumulative_pipeline_training_flops"]
        )
        fields["total_training_flops"] = cumulative_flops
        fields["cumulative_pipeline_training_flops"] = cumulative_flops
    return fields


def configure_wandb_metrics(run):
    run.define_metric("step")
    for metric in WANDB_STEP_METRICS:
        run.define_metric(metric, step_metric="step")


def update_wandb_lineage_summary(run, user_config, experiment_id):
    experiment = user_config.get(
        "experiment", user_config.get("resolved_experiment_config", {})
    )
    values = {
        "experiment_id": experiment_id,
        "stage": user_config.get("stage", experiment.get("stage")),
        "base_experiment_id": user_config.get("base_experiment_id"),
        "parent_experiment_id": user_config.get("parent_experiment_id"),
        "parent_checkpoint_step": user_config.get("parent_checkpoint_step"),
        "config_fingerprint": user_config.get("config_fingerprint"),
        "tokenizer_fingerprint": user_config.get("tokenizer_fingerprint"),
        "git_commit_sha": user_config.get("git_commit_sha"),
        "dataset": experiment.get("dataset", {}).get("repo"),
    }
    for key, value in values.items():
        if value is not None and value != "":
            run.summary[key] = value


def update_wandb_compute_summary(run, compute_fields):
    for key in (
        "total_training_flops",
        "stage_training_flops",
        "inherited_parent_flops",
        "cumulative_pipeline_training_flops",
    ):
        run.summary[key] = compute_fields[key]
