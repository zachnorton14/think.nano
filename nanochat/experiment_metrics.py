"""Compute accounting shared by the lineage-aware training stages."""


def training_flops(processed_tokens, training_flops_per_token):
    return float(processed_tokens) * float(training_flops_per_token)


def rollout_generation_flops(model_token_invocations, training_flops_per_token):
    # The model estimate is forward + backward; rollout generation is forward-only.
    return float(model_token_invocations) * (float(training_flops_per_token) / 3.0)


def cumulative_pipeline_flops(stage_flops, inherited_parent_flops):
    return float(stage_flops) + float(inherited_parent_flops)
