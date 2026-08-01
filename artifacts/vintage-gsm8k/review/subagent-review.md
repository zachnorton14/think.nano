# Vintage GSM8K subagent review

Generated: 2026-08-01T18:26:04.766095+00:00

## Coverage and decisions

All **1,027** flagged IDs were reviewed against the source question and full normalized solution. Coverage validates at exactly one record per ID, in canonical source order.

- Rewrite: **989**
- Keep (suspected false positives): **34**
- Manual: **4**

This review is advisory. It does not modify `decisions.jsonl`, judge logs, or source data, and no rewrite calls were made.

## Suspected false-positive patterns

The judge sometimes equated “not common by 1930” with “not available by 1930.” Pre-cutoff examples include pet insurance, ant farms, hair conditioner, GPA, dental implants, ski lifts, water slides, scavenger hunts, joystick aircraft controls, early television programs, and television advertising. Generic pre-1931 science-fiction ideas—spaceships, alien craft, space stations, and interplanetary travel—were also treated as later real-world technologies.

A second pattern was inference beyond the text. Generic labels such as “Iron nickels,” “Death by Chocolate,” “black burger,” “Key West Turtle Race,” “Officer Hopps,” “Novel Corona High School,” and “the Catapult” do not require later knowledge. “The pandemic” can refer to 1918 influenza, and “his site” need not mean a website when the same sentence calls the venue a store.

Keep recommendations (34):

- `gsm8k-main-train-000095`
- `gsm8k-main-train-000153`
- `gsm8k-main-train-000285`
- `gsm8k-main-train-000396`
- `gsm8k-main-train-000754`
- `gsm8k-main-train-000978`
- `gsm8k-main-train-001044`
- `gsm8k-main-train-001155`
- `gsm8k-main-train-001231`
- `gsm8k-main-train-001246`
- `gsm8k-main-train-001500`
- `gsm8k-main-train-002154`
- `gsm8k-main-train-002406`
- `gsm8k-main-train-002570`
- `gsm8k-main-train-002774`
- `gsm8k-main-train-003312`
- `gsm8k-main-train-003646`
- `gsm8k-main-train-004384`
- `gsm8k-main-train-005128`
- `gsm8k-main-train-005595`
- `gsm8k-main-train-005780`
- `gsm8k-main-train-005849`
- `gsm8k-main-train-005979`
- `gsm8k-main-train-006072`
- `gsm8k-main-train-006221`
- `gsm8k-main-train-006307`
- `gsm8k-main-train-006835`
- `gsm8k-main-train-006940`
- `gsm8k-main-train-006969`
- `gsm8k-main-test-000268`
- `gsm8k-main-test-000534`
- `gsm8k-main-test-000596`
- `gsm8k-main-test-000790`
- `gsm8k-main-test-001099`

## Manual decisions

- `gsm8k-main-train-000391` — “Astronaut” and fictional space travelers were current by about 1929, but the college-to-professional-astronaut path may imply the later space program.
- `gsm8k-main-train-004379` — Dashboard fuel gauges existed before 1931, but “the gas indicator comes on” may mean a later automatic low-fuel warning lamp.
- `gsm8k-main-train-005910` — Shrinking devices appeared in early speculative fiction, but the exact “shrink ray” usage may postdate 1930.
- `gsm8k-main-test-000140` — Automatic-transmission prototypes predate 1931, but automatic and semi-automatic rental-car categories may be later usage.

The judge's three original `review` rows resolve to **keep**:

- `gsm8k-main-train-002570`: joystick aircraft-control usage predates the cutoff; no video game is stated.
- `gsm8k-main-train-006072`: hair-conditioning products existed by 1900.
- `gsm8k-main-test-001099`: water-toboggan slides existed by 1923; “Five Flags” is fictional.

## Rewrite and prompt risks

- `gsm8k-main-train-004693` is incorrectly labeled `mode="date"` despite containing no date. Treat it as a surface terminology rewrite of “carpal tunnel syndrome.”
- Date rewrites must move every date to `<=1930` and recompute dependent reasoning and `####` where necessary; ordinary surface numeric-invariant checks do not apply.
- Surface rewrites should change the smallest anachronistic span in both question and solution. Do not apply the supplied Vintage CORE restyling prompt wholesale: its requirement to thoroughly recast every sentence conflicts with this pipeline's “no wholesale vintage prose” rule.
- Preserve the complete reasoning trace and exactly one `####` line. Reject calculator annotations, Python, tool tokens, answer-only output, silent unit changes, and added hints.
- Modern brands and concepts often recur in the solution. Rewriting the question alone is insufficient.
- Keep one row per request: long solutions and calculation audits make batched alignment risky.

## Representative examples

- True surface rewrite: `gsm8k-main-train-000015` uses DVDs throughout; records or books can preserve every number and operation.
- True date rewrite: `gsm8k-main-train-000181` uses 2017–2019; shift the window and retain the two successive 10% growth steps.
- False positive: `gsm8k-main-train-000978` uses an ant farm, commercially available by about 1929.
- False positive: `gsm8k-main-test-000596` uses dental implants and a crown, represented in pre-1931 dentistry.
- Inference risk: `gsm8k-main-train-005128` says “site” and “store”; it does not state website or online shopping.
- Manual boundary: `gsm8k-main-test-000140` uses automatic and semi-automatic rental-car categories whose prototypes and consumer usage straddle the cutoff.
