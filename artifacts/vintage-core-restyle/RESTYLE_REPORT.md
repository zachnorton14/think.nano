# Vintage CORE Restyle Coverage

This report counts meaningful packaged differences from the tracked filtered bundle.
For SQuAD, CoQA, and BoolQ it compares only the editable passage/story component and
ignores scaffold, question, and boundary-whitespace-only differences.
A filtered-original row is an intentional correctness-preserving fallback.
The >=98% target applies to normally restyled benchmarks. Designated exact-copy tasks,
the excluded LAMBADA restyle, and the manually authored repeat-copy task are exceptions.

| Task | N | Vintage/manual rows | Filtered-original rows | Coverage |
| --- | ---: | ---: | ---: | ---: |
| `bigbench_repeat_copy_logic` | 32 | 16 | 16 | 50.0% |
| `copa` | 100 | 98 | 2 | 98.0% |
| `bigbench_operators` | 210 | 0 | 210 | 0.0% |
| `agi_eval_lsat_ar` | 230 | 0 | 230 | 0.0% |
| `winograd` | 273 | 268 | 5 | 98.2% |
| `openbook_qa` | 500 | 490 | 10 | 98.0% |
| `arc_challenge` | 1172 | 1154 | 18 | 98.5% |
| `commonsense_qa` | 1221 | 1213 | 8 | 99.3% |
| `winogrande` | 1267 | 1242 | 25 | 98.0% |
| `piqa` | 1319 | 1293 | 26 | 98.0% |
| `jeopardy` | 1638 | 1609 | 29 | 98.2% |
| `arc_easy` | 2020 | 1992 | 28 | 98.6% |
| `boolq` | 1015 | 958 | 57 | 94.4% |
| `lambada_openai` | 4387 | 0 | 4387 | 0.0% |
| `coqa` | 4270 | 4036 | 234 | 94.5% |
| `bigbench_language_identification` | 7570 | 0 | 7570 | 0.0% |
| `hellaswag_zeroshot` | 6076 | 6030 | 46 | 99.2% |
| `hellaswag` | 6076 | 6030 | 46 | 99.2% |
| `squad` | 4284 | 4137 | 147 | 96.6% |
| `bigbench_qa_wikidata` | 9508 | 0 | 9508 | 0.0% |

Task-level rows: 30,566/53,168 changed (57.5%).
Unique physical rows: 24,536/47,092 changed (52.1%).

Validation status: run `python -m dev.vintage_core.bundle_validation`; a released bundle must report zero issues.
