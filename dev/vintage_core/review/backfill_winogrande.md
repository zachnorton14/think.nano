# Backfill review: `winogrande`

Mode: preview
Items: 10

## Benchmark context

- Category: language understanding
- Task type: schema
- Few-shot examples: 0
- Random baseline: 50
- Description: The Winogrande consists of 1,267 scenarios in which two possible beginnings of a sentence are presented along with a single ending. Both combinations are syntactically valid, but only one is semantically valid, and the model must choose the one that is semantically valid.

## 1. source_idx=15 (Frank Miller postdates 1930)

**Original removed item**

[0] Lindsey like to read graphic novels but Natalie liked classic literature to read. Lindsey [1] Lindsey like to read graphic novels but Natalie liked classic literature to read. Natalie continuation: bought the new Frank Miller comic at the book store.

Original gold: [0] Lindsey like to read graphic novels but Natalie liked classic literature to read. Lindsey bought the new Frank Miller comic at the book store.

**Generated replacement**

[0] Lindsey liked to read dime novels but Natalie liked classic literature to read. Lindsey [1] Lindsey liked to read dime novels but Natalie liked classic literature to read. Natalie continuation: bought the new Nick Carter adventure at the book store.

Generated expected gold (preserved source index): [0] Lindsey liked to read dime novels but Natalie liked classic literature to read. Lindsey bought the new Nick Carter adventure at the book store.

## 2. source_idx=28 (modern environmental concept)

**Original removed item**

[0] Since Craig threw aluminum cans in the trash and Benjamin recycled, Craig [1] Since Craig threw aluminum cans in the trash and Benjamin recycled, Benjamin continuation: was environmentally irresponsible.

Original gold: [0] Since Craig threw aluminum cans in the trash and Benjamin recycled, Craig was environmentally irresponsible.

**Generated replacement**

[0] Since Craig tossed tin cans into the gutter and Benjamin saved them for the scrap collector, Craig [1] Since Craig tossed tin cans into the gutter and Benjamin saved them for the scrap collector, Benjamin continuation: was careless with refuse.

Generated expected gold (preserved source index): [0] Since Craig tossed tin cans into the gutter and Benjamin saved them for the scrap collector, Craig was careless with refuse.

## 3. source_idx=61 (Super glue invented in 1942, postdates 1930)

**Original removed item**

[0] Laura used too much super glue on Erins hands, so Laura [1] Laura used too much super glue on Erins hands, so Erin continuation: needed to get to the doctor to separate their hands.

Original gold: [1] Laura used too much super glue on Erins hands, so Erin needed to get to the doctor to separate their hands.

**Generated replacement**

[0] Margaret used too much glue on Helen's hands, so Margaret [1] Margaret used too much glue on Helen's hands, so Helen continuation: needed to get to the doctor to separate their hands.

Generated expected gold (preserved source index): [1] Margaret used too much glue on Helen's hands, so Helen needed to get to the doctor to separate their hands.

## 4. source_idx=72 (glow sticks are post-1930 invention)

**Original removed item**

[0] I tried to make mini lamps by using glow sticks in mason jars, but had to get larger jars because the glow sticks [1] I tried to make mini lamps by using glow sticks in mason jars, but had to get larger jars because the jars continuation: were too big.

Original gold: [0] I tried to make mini lamps by using glow sticks in mason jars, but had to get larger jars because the glow sticks were too big.

**Generated replacement**

[0] I tried to make mini lamps by using candles in glass jars, but had to get larger jars because the candles [1] I tried to make mini lamps by using candles in glass jars, but had to get larger jars because the jars continuation: were too big.

Generated expected gold (preserved source index): [0] I tried to make mini lamps by using candles in glass jars, but had to get larger jars because the candles were too big.

## 5. source_idx=76 (makeup tutorials postdate 1930)

**Original removed item**

[0] Mary was helping Patricia's daughter put on makeup but  Mary [1] Mary was helping Patricia's daughter put on makeup but  Patricia continuation: watches a lot of makeup tutorials.

Original gold: [1] Mary was helping Patricia's daughter put on makeup but  Patricia watches a lot of makeup tutorials.

**Generated replacement**

[0] Elizabeth was helping Margaret's son tune the violin but  Elizabeth [1] Elizabeth was helping Margaret's son tune the violin but  Margaret continuation: plays in the symphony orchestra.

Generated expected gold (preserved source index): [1] Elizabeth was helping Margaret's son tune the violin but  Margaret plays in the symphony orchestra.

## 6. source_idx=77 (makeup tutorials postdate 1930)

**Original removed item**

[0] Mary was helping Patricia's daughter put on makeup because Mary [1] Mary was helping Patricia's daughter put on makeup because Patricia continuation: watches a lot of makeup tutorials.

Original gold: [0] Mary was helping Patricia's daughter put on makeup because Mary watches a lot of makeup tutorials.

**Generated replacement**

[0] Martha was helping Florence's daughter with embroidery because Martha [1] Martha was helping Florence's daughter with embroidery because Florence continuation: had learned needlework from her mother.

Generated expected gold (preserved source index): [0] Martha was helping Florence's daughter with embroidery because Martha had learned needlework from her mother.

## 7. source_idx=79 (peanut allergy concept after 1930)

**Original removed item**

[0] Aaron didn't know Dennis had a peanut allergy, so when Aaron [1] Aaron didn't know Dennis had a peanut allergy, so when Dennis continuation: made peanut chicken an ambulance was called.

Original gold: [0] Aaron didn't know Dennis had a peanut allergy, so when Aaron made peanut chicken an ambulance was called.

**Generated replacement**

[0] Arthur didn't know George was afraid of dogs, so when Arthur [1] Arthur didn't know George was afraid of dogs, so when George continuation: brought his terrier over George fled the room.

Generated expected gold (preserved source index): [0] Arthur didn't know George was afraid of dogs, so when Arthur brought his terrier over George fled the room.

## 8. source_idx=105 (credit card postdates 1930)

**Original removed item**

[0] To pay for dinner, he used the credit card rather than cash. The cash [1] To pay for dinner, he used the credit card rather than cash. The card continuation: was not available.

Original gold: [0] To pay for dinner, he used the credit card rather than cash. The cash was not available.

**Generated replacement**

[0] To pay for dinner, he used the check rather than cash. The cash [1] To pay for dinner, he used the check rather than cash. The check continuation: was not available.

Generated expected gold (preserved source index): [0] To pay for dinner, he used the check rather than cash. The cash was not available.

## 9. source_idx=112 (internet postdates 1930)

**Original removed item**

[0] Brett was browsing the internet while he found the information unlike Randy, Brett [1] Brett was browsing the internet while he found the information unlike Randy, Randy continuation: prefers using books.

Original gold: [1] Brett was browsing the internet while he found the information unlike Randy, Randy prefers using books.

**Generated replacement**

[0] Brett was browsing the newspaper while he found the information unlike Randy, Brett [1] Brett was browsing the newspaper while he found the information unlike Randy, Randy continuation: prefers using books.

Generated expected gold (preserved source index): [1] Brett was browsing the newspaper while he found the information unlike Randy, Randy prefers using books.

## 10. source_idx=116 (Craigslist postdates 1930)

**Original removed item**

[0] Carrie posted their sofa for sale on Craigslist, and had received an offer they had to decline because the offer [1] Carrie posted their sofa for sale on Craigslist, and had received an offer they had to decline because the sofa continuation: is valuable.

Original gold: [1] Carrie posted their sofa for sale on Craigslist, and had received an offer they had to decline because the sofa is valuable.

**Generated replacement**

[0] Carrie posted their sofa for sale in the newspaper, and had received an offer they had to decline because the offer [1] Carrie posted their sofa for sale in the newspaper, and had received an offer they had to decline because the sofa continuation: is valuable.

Generated expected gold (preserved source index): [1] Carrie posted their sofa for sale in the newspaper, and had received an offer they had to decline because the sofa is valuable.