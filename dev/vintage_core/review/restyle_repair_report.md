# Vintage CORE Offline Repair Report

Date: 2026-07-10

## Provenance

- Pre-repair restyle snapshot: commit `c346dc2`
- Tracked filtered reference: commit `25c53a0`
- Canonical repaired bundle: `artifacts/vintage-core-restyle`
- No model or network calls were used for this repair.

Unsafe generated rows were replaced with the exact same-index row from
`artifacts/vintage-core-filtered`. Safe vintage rewrites were retained byte-for-byte. Source
metadata was restored where the earlier packaging step had stripped it.

## Content reverts

| Task | Reverted to filtered | Reason summary |
| --- | ---: | --- |
| `copa` | 4 | Broken causal/choice joints |
| `winograd` | 6 | Terminal punctuation collisions with protected continuation |
| `openbook_qa` | 2 | Changed stem-choice relation / broken joint |
| `arc_challenge` | 17 | Audited hints plus strict digit/answer gates |
| `commonsense_qa` | 6 | Duplicate scaffold, answer hints, strict digit drift |
| `winogrande` | 20 | Broken joints, answer absorption, schema bias |
| `piqa` | 5 | Task reframing and answer leakage |
| `jeopardy` | 178 | Category-prefix loss, clue corruption, answer leakage, digit drift |
| `arc_easy` | 22 | Answer/choice leakage, proper-name/digit drift |
| `boolq` | 224 | Scaffold, quoted material, digit and semantic drift |
| `coqa` | 1,683 | Scaffold/layout loss, filled answers, digit/target drift |
| `hellaswag` | 31 | Broken joints, answer absorption, digits, quotes/units |
| `squad` | 2,061 | Scaffold/layout loss, filled answers, digit/target drift |

HellaSwag is one physical file shared by the few-shot and zero-shot task labels, so its 31
reverts apply to both without duplicated edits.

## Metadata restored

- OpenBookQA: provenance on 44 backfill rows.
- ARC-Challenge: provenance on 167 backfill rows.
- COPA: provenance on 4 backfill rows.
- Winograd: provenance on 9 backfill rows.
- CommonsenseQA: provenance on 117 otherwise-safe rows.
- Winogrande: provenance on 109 otherwise-safe rows.
- Jeopardy: `category` on all 1,637 applicable rows.

## Final coverage

The authoritative per-task coverage table is in
`artifacts/vintage-core-restyle/RESTYLE_REPORT.md`.

- Unique physical rows retaining vintage/manual text: 20,556/47,092 (43.7%).
- Task-level rows retaining vintage/manual text: 26,586/53,168 (50.0%).
- The lower percentages are intentional: correctness-preserving filtered originals replace
  uncertain generations, especially in CoQA and SQuAD.

## Reproducible commands

```bash
python -m dev.vintage_core.repairs.repair_longform
python -m dev.vintage_core.repairs.repair_science_qa
python -m dev.vintage_core.repairs.repair_commonsense
python -m dev.vintage_core.bundle_validation \
  --source artifacts/vintage-core-filtered \
  --candidate artifacts/vintage-core-restyle
```

Each repair command is idempotent and supports `--check`.

## Release gates

The repaired bundle passes exhaustive comparison across 47,092 unique rows:

- task configuration, count, and row order;
- exact source key sets and task metadata;
- choices, choice order, gold labels, and protected continuations;
- strict digit-bearing tokens, including sentence-final years, ordinals, and prefixed years;
- quoted spans;
- BoolQ, CoQA, SQuAD, CommonsenseQA, and Jeopardy scaffolding;
- no newly inserted exact choice/continuation answer text;
- schema minimal-pair preservation and continuation-joint punctuation;
- HellaSwag shared-file identity.

Vintage-style imperfections, verbosity, and non-ASCII period punctuation were not treated as
release blockers in this salvage pass, per the requested priority on correctness.
