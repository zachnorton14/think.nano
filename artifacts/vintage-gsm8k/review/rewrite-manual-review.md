# Vintage GSM8K terminal rewrite review

Reviewed the latest terminal `status=manual` record for every currently unresolved rewrite ID: 23 train rows and 1 test row.

## Outcome

- 8 rows have a usable candidate that can be accepted unchanged after a narrow, documented validator override.
- 12 rows have a preferred candidate requiring a small exact edit, a calculation-audit repair, or date/context reclassification.
- 4 rows need a deterministic manual rewrite from the source because no attempt preserves both temporal accessibility and the original calculation graph.
- 6 preferred candidates need calculation-audit repairs: `gsm8k-main-train-001464`, `gsm8k-main-train-002168`, `gsm8k-main-train-001595`, `gsm8k-main-train-001708`, `gsm8k-main-train-006570`, and `gsm8k-main-test-000481`.

## Main failure pattern

The strict ordered-numeric-literal gate is catching numerals embedded in the very post-1930 entities that must be removed, including `COVID-19`, `401(k)`, `Boeing 747`, `iPhone 12`, `Taipei 101`, and `Warhammer 40k`. Currency-symbol substitutions also trigger it. Those cases should use narrow reviewed exceptions while continuing to enforce all math-bearing literals and the calculation graph.

The four rows without a safe preferred attempt are:

- `gsm8k-main-train-001068`: preserve `2*4` and `3*2` with pre-1930 football scoring.
- `gsm8k-main-train-002002`: keep 50 as a decorative-flag quantity instead of changing the U.S. state count.
- `gsm8k-main-train-004007`: replace basketball scoring with extra points, field goals, and safeties.
- `gsm8k-main-train-005191`: make 50 the size of a license-plate collection rather than the number of U.S. states.

The decision-ready details and exact edits are in `rewrite-manual-review.jsonl`.
