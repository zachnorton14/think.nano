# LAMBADA Isolated Subagent Pass

The generator and auditor were separate isolated subagents. The generator received only record
IDs, editable narration, and the copy-editing contract; it was not given targets, frozen tails,
benchmark metadata, prior candidates, or audit history. A second subagent independently reviewed
the deterministic survivors. Candidates were applied only when both the reviewer and all code
gates accepted them.

## Rounds

| Round | Inputs | Generator changes | Deterministic survivors | Auditor accepts | Net new rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial representative trial | 200 | 153 | 103 | 99 | 53 |
| General remainder A | 500 | 157 | 118 after gate fixes | 98 | 97 |
| General remainder B | 700 | 136 | 89 | 69 | 68 |
| General remainder C | 700 | 106 | 49 | 23 | 22 |
| Contraction-focused | 74 | 65 | 62 | 61 | 61 |
| Contraction tail | 13 | 4 | 1 | 0 | 0 |
| Safe-lexical focused | 44 | 37 | 32 | 29 | 27 |

The apparent differences between auditor accepts and net rows arise when a candidate still fails
the final row-level bundle gate or was already applied during an earlier audit of the same batch.

## Outcome

- Safe rows added by the isolated pass: **328**.
- LAMBADA passages with at least one accepted edit: **2,202/4,387 (50.2%)**.
- Coverage among rows with editable narration: **64.4%**.
- Accepted edited sentence/chunks: **2,890/6,669 eligible chunks (43.3%)**.
- Continuations and frozen final fragments remain byte-identical.
- Exhaustive bundle validation: **47,092 rows, 0 issues**.

The final round's input, candidate, enriched audit, and verdict JSONL files are retained beside this
report as concrete workflow examples. Earlier rounds were checkpointed into the benchmark artifact
and summarized above.
