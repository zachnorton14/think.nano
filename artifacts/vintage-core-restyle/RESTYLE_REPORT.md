# Vintage CORE Restyle Coverage

This report counts actual packaged row differences from the tracked filtered bundle.
A filtered-original row is an intentional correctness-preserving fallback.

| Task | N | Vintage/manual rows | Filtered-original rows | Coverage |
| --- | ---: | ---: | ---: | ---: |
| `bigbench_repeat_copy_logic` | 32 | 16 | 16 | 50.0% |
| `copa` | 100 | 94 | 6 | 94.0% |
| `bigbench_operators` | 210 | 0 | 210 | 0.0% |
| `agi_eval_lsat_ar` | 230 | 0 | 230 | 0.0% |
| `winograd` | 273 | 263 | 10 | 96.3% |
| `openbook_qa` | 500 | 476 | 24 | 95.2% |
| `arc_challenge` | 1172 | 1154 | 18 | 98.5% |
| `commonsense_qa` | 1221 | 1213 | 8 | 99.3% |
| `winogrande` | 1267 | 1241 | 26 | 97.9% |
| `piqa` | 1319 | 1274 | 45 | 96.6% |
| `jeopardy` | 1638 | 1458 | 180 | 89.0% |
| `arc_easy` | 2020 | 1992 | 28 | 98.6% |
| `boolq` | 1015 | 785 | 230 | 77.3% |
| `lambada_openai` | 4387 | 0 | 4387 | 0.0% |
| `coqa` | 4270 | 3303 | 967 | 77.4% |
| `bigbench_language_identification` | 7570 | 0 | 7570 | 0.0% |
| `hellaswag_zeroshot` | 6076 | 6030 | 46 | 99.2% |
| `hellaswag` | 6076 | 6030 | 46 | 99.2% |
| `squad` | 4284 | 3094 | 1190 | 72.2% |
| `bigbench_qa_wikidata` | 9508 | 0 | 9508 | 0.0% |

Task-level rows: 28,423/53,168 changed (53.5%).
Unique physical rows: 22,393/47,092 changed (47.6%).

Validation status: run `python -m dev.vintage_core.bundle_validation`; a released bundle must report zero issues.
