# Think Experiment Log

A running summary of experiments and findings for the Think dataset work.

---

## 2026-06-19: Think d12 ratio scout (inconclusive, useful)

Ran a d12 base pretraining run on the Think dataset with a target ratio of 30, then evaluated several intermediate checkpoints to quickly scout whether the best stopping region was closer to r12, r20, r26, or r30.

W&B run: [think-d12-1ep-65sh-r30](https://wandb.ai/jbduran-thinkingmachinesncsu/think.nano/runs/6465e19b/overview?nw=nwuserjbduran)

### Setup
- Run: `think-d12-1ep-65sh-r30`
- Checkpoints evaluated: 2500, 3500, 4000, 4500, 5500, 6300
- Metrics: full CORE and full validation BPB

The goal was not to produce a final scaling law. The goal was to cheaply identify whether further runs should focus around r12, r20, or higher ratios.

### Results

| Step | Ratio | EFLOPs | CORE | Val BPB |
|---:|---:|---:|---:|---:|
| 2500 | 11.90 | 1.1627 | 0.04720 | 1.14370 |
| 3500 | 16.67 | 1.6278 | 0.06823 | 1.10496 |
| 4000 | 19.05 | 1.8604 | 0.06920 | 1.08422 |
| 4500 | 21.43 | 2.0929 | 0.07931 | 1.06425 |
| 5500 | 26.19 | 2.5580 | 0.08353 | 1.01587 |
| 6300 | 30.00 | 2.9301 | 0.08956 | 0.99446 |

![Think d12 ratio scout](figures/think-d12-ratio-scout.png)

### Read

The results do not support r12 as the right stopping point for this run. Validation BPB improved monotonically through r30, and CORE also improved overall. The run therefore suggests that r12 is too low for this dataset/model combination.

However, the result is not clean enough to conclude that r30 is the correct target. These checkpoints all come from one r30 learning-rate schedule. That means the intermediate checkpoints are not fair independent r12, r16, r20, or r26 runs. A checkpoint can look worse simply because the scheduler was designed to finish much later.

CORE is also not the cleanest primary signal for this dataset. The Think dataset is built from older books, while parts of CORE reward modern knowledge and benchmark-specific coverage. Validation BPB is the more direct signal for dataset fit, while CORE is useful as a broader transfer check.

### Conclusion

This was a useful scout but not a definitive scaling-law experiment. The practical takeaway is to stick near r20 for now while the dataset and architecture are still moving. Running more ratio sweeps before those are settled would probably waste A100 time.

Once the dataset and architecture are stable, rerun a cleaner scaling analysis with independent schedules, likely around r16, r20, r24/r26, and r30. For now, r20 is a reasonable default because it is conservative, cheaper than r30, and close to the region where the scout started showing stronger quality without committing to the full long run.
