# Vintage CORE — build log

_Regenerated 2026-06-26 by `python -m dev.vintage_core.log` from on-disk artifacts._

Stages: **orig** → filter (**rm_regex** post-1930 years, **rm_llm** entity/register) → **kept** → **backfill** (N≤1300) → **final**.

Dropped entirely: `bigbench_cs_algorithms`, `bigbench_dyck_languages`.

| task | verdict | orig | rm_regex | rm_llm | kept | backfill | final | stage |
|------|---------|-----:|---------:|-------:|-----:|---------:|------:|-------|
| `bigbench_repeat_copy_logic` | REWRITE | 32 | - | - | - | - | - | pending |
| `copa` | KEEP | 100 | - | - | - | - | - | pending |
| `bigbench_operators` | KEEP | 210 | - | - | - | - | - | pending |
| `agi_eval_lsat_ar` | KEEP | 230 | - | - | - | - | - | pending |
| `winograd` | KEEP | 273 | - | - | - | - | - | pending |
| `openbook_qa` | REWRITE | 500 | - | - | - | - | - | pending |
| `arc_challenge` | FILTER | 1172 | - | - | - | - | - | pending |
| `commonsense_qa` | KEEP | 1221 | - | - | - | - | - | pending |
| `winogrande` | KEEP | 1267 | - | - | - | - | - | pending |
| `piqa` | REWRITE+FILTER | 1838 | - | - | - | - | - | pending |
| `jeopardy` | FILTER | 2117 | - | - | - | - | - | pending |
| `arc_easy` | FILTER | 2376 | - | - | - | - | - | pending |
| `boolq` | REWRITE+FILTER | 3270 | - | - | - | - | - | pending |
| `lambada_openai` | REWRITE | 5153 | - | - | - | - | - | pending |
| `coqa` | REWRITE+FILTER | 7983 | - | - | - | - | - | pending |
| `bigbench_language_identification` | KEEP | 10000 | - | - | - | - | - | pending |
| `hellaswag_zeroshot` | REWRITE | 10042 | - | - | - | - | - | pending |
| `hellaswag` | REWRITE | 10042 | - | - | - | - | - | pending |
| `squad` | REWRITE+FILTER | 10570 | - | - | - | - | - | pending |
| `bigbench_qa_wikidata` | FILTER | 20321 | - | - | - | - | - | pending |
