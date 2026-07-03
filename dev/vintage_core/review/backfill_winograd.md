# Backfill review: `winograd`

Mode: preview
Items: 9

## Benchmark context

- Category: language understanding
- Task type: schema
- Few-shot examples: 0
- Random baseline: 50
- Description: The Winograd Schema Challenge consists of 273 scenarios in which the model must use semantics to correctly resolve the anaphora in a sentence. Two possible beginnings to a sentence are presented as well as an ending. Both involve some anaphora being resolved in a different way, only one of which would be semantically valid, and the model must choose which option produces the valid resolution.

## 1. source_idx=17 (Styrofoam postdates 1930)

**Original removed item**

[0] The large ball crashed right through the table because the large ball [1] The large ball crashed right through the table because the table continuation: was made of styrofoam.

Gold: [1] The large ball crashed right through the table because the table was made of styrofoam.

**Generated replacement**

[0] The large ball crashed right through the table because the large ball [1] The large ball crashed right through the table because the table continuation: was made of cardboard.

Gold: [1] The large ball crashed right through the table because the table was made of cardboard.

## 2. source_idx=188 (chocolate chip cookies invented after 1930)

**Original removed item**

[0] Everyone really loved the oatmeal cookies; only a few people liked the chocolate chip cookies. Next time, we should make more of the oatmeal cookies [1] Everyone really loved the oatmeal cookies; only a few people liked the chocolate chip cookies. Next time, we should make more of the chocolate chip cookies continuation: .

Gold: [0] Everyone really loved the oatmeal cookies; only a few people liked the chocolate chip cookies. Next time, we should make more of the oatmeal cookies .

**Generated replacement**

[0] Everyone really loved the oatmeal cookies; only a few people liked the raisin cookies. Next time, we should make more of the oatmeal cookies [1] Everyone really loved the oatmeal cookies; only a few people liked the raisin cookies. Next time, we should make more of the raisin cookies continuation: .

Gold: [0] Everyone really loved the oatmeal cookies; only a few people liked the raisin cookies. Next time, we should make more of the oatmeal cookies .

## 3. source_idx=189 (chocolate chip cookies invented after 1930)

**Original removed item**

[0] Everyone really loved the oatmeal cookies; only a few people liked the chocolate chip cookies. Next time, we should make fewer of the oatmeal cookies [1] Everyone really loved the oatmeal cookies; only a few people liked the chocolate chip cookies. Next time, we should make fewer of the chocolate chip cookies continuation: .

Gold: [1] Everyone really loved the oatmeal cookies; only a few people liked the chocolate chip cookies. Next time, we should make fewer of the chocolate chip cookies .

**Generated replacement**

[0] Everyone really loved the raisin cakes; only a few people liked the plum cakes. Next time, we should make fewer of the raisin cakes [1] Everyone really loved the raisin cakes; only a few people liked the plum cakes. Next time, we should make fewer of the plum cakes continuation: .

Gold: [1] Everyone really loved the raisin cakes; only a few people liked the plum cakes. Next time, we should make fewer of the plum cakes .

## 4. source_idx=228 (gameboy is a post-1930 product)

**Original removed item**

[0] Bill passed the gameboy to John because Bill's [1] Bill passed the gameboy to John because John's continuation: turn was over.

Gold: [0] Bill passed the gameboy to John because Bill's turn was over.

**Generated replacement**

[0] Bill passed the dice to John because Bill's [1] Bill passed the dice to John because John's continuation: turn was over.

Gold: [0] Bill passed the dice to John because Bill's turn was over.

## 5. source_idx=229 (gameboy is a post-1930 product)

**Original removed item**

[0] Bill passed the gameboy to John because Bill's [1] Bill passed the gameboy to John because John's continuation: turn was next.

Gold: [1] Bill passed the gameboy to John because John's turn was next.

**Generated replacement**

[0] Bill passed the chessboard to John because Bill's [1] Bill passed the chessboard to John because John's continuation: turn was next.

Gold: [1] Bill passed the chessboard to John because John's turn was next.

## 6. source_idx=267 (Madonna (singer) postdates 1930)

**Original removed item**

[0] Madonna fired her trainer because Madonna [1] Madonna fired her trainer because the trainer continuation: couldn't stand her boyfriend.

Gold: [0] Madonna fired her trainer because Madonna couldn't stand her boyfriend.

**Generated replacement**

[0] The queen banished the maid because the queen [1] The queen banished the maid because the maid continuation: was caught stealing jewelry from the palace.

Gold: [1] The queen banished the maid because the maid was caught stealing jewelry from the palace.

## 7. source_idx=268 (Madonna (singer) postdates 1930)

**Original removed item**

[0] Madonna fired her trainer because Madonna [1] Madonna fired her trainer because the trainer continuation: slept with her boyfriend.

Gold: [1] Madonna fired her trainer because the trainer slept with her boyfriend.

**Generated replacement**

[0] Catherine dismissed her tutor because Catherine [1] Catherine dismissed her tutor because the tutor continuation: insulted her husband.

Gold: [1] Catherine dismissed her tutor because the tutor insulted her husband.

## 8. source_idx=269 (Madonna (singer) postdates 1930)

**Original removed item**

[0] Madonna fired her trainer because she slept with Madonna's [1] Madonna fired her trainer because she slept with the trainer's continuation: boyfriend.

Gold: [0] Madonna fired her trainer because she slept with Madonna's boyfriend.

**Generated replacement**

[0] Cleopatra dismissed her handmaiden because she slept with Cleopatra's [1] Cleopatra dismissed her handmaiden because she slept with the handmaiden's continuation: husband.

Gold: [0] Cleopatra dismissed her handmaiden because she slept with Cleopatra's husband.

## 9. source_idx=270 (Madonna (b.1958) and modern trainer concept)

**Original removed item**

[0] Madonna fired her trainer because she couldn't stand Madonna's [1] Madonna fired her trainer because she couldn't stand the trainer's continuation: boyfriend.

Gold: [1] Madonna fired her trainer because she couldn't stand the trainer's boyfriend.

**Generated replacement**

[0] Mary dismissed her governess because she couldn't stand Mary's [1] Mary dismissed her governess because she couldn't stand the governess's continuation: boyfriend.

Gold: [1] Mary dismissed her governess because she couldn't stand the governess's boyfriend.
