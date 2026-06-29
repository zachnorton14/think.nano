# Backfill review: `commonsense_qa`

Mode: preview
Items: 10

## Benchmark context

- Category: commonsense reasoning
- Task type: multiple choice
- Few-shot examples: 10
- Random baseline: 20
- Description: Commonsense QA consists of 1,221 four-choice multiple choice questions that rely on very basic commonsense reasoning about everyday items.

## 1. source_idx=19 (glue sticks postdate 1930)

**Original removed item**

Question: Where do adults use glue sticks? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2] C [3] D

Original gold: [2] C

**Generated replacement**

Question: Where do adults use paste? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [2] C

## 2. source_idx=25 (contains post-1930 term 'photo copy')

**Original removed item**

Question: When wildlife reproduce we often refer to what comes out as what? Choices: A. have children B. photo copy C. offspring D. accidently got pregnant somehow Answer: [0] A [1] B [2] C [3] D

Original gold: [2] C

**Generated replacement**

Question: When animals in the wild mate and produce young, what do we commonly call their young? Choices: A. have children B. carbon copy C. offspring D. accidently got pregnant somehow Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [2] C

## 3. source_idx=26 (contains post-1930 invention 'freezer')

**Original removed item**

Question: The weasel was becoming a problem, it kept getting into the chicken eggs kept in the what? Choices: A. forrest B. barn C. out of doors D. freezer Answer: [0] A [1] B [2] C [3] D

Original gold: [1] B

**Generated replacement**

Question: The weasel was becoming a problem, it kept getting into the chicken eggs kept in the what? Choices: A. forest B. barn C. out of doors D. icebox Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [1] B

## 4. source_idx=31 (refers to 1950s, post-1930 decade)

**Original removed item**

Question: James wanted to find an old underground map from the 50s.  Where might he look for one? Choices: A. library B. county engineer's office C. super market D. home Answer: [0] A [1] B [2] C [3] D

Original gold: [0] A

**Generated replacement**

Question: James wanted to find an old map of the London Underground from the 1910s. Where might he look for one? Choices: A. library B. county engineer's office C. super market D. home Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [0] A

## 5. source_idx=34 (senior center is post-1930 institution)

**Original removed item**

Question: She was always helping at the senior center, it brought her what? Choices: A. satisfaction B. feel better C. pay D. happiness Answer: [0] A [1] B [2] C [3] D

Original gold: [3] D

**Generated replacement**

Question: She was always helping at the orphanage, it brought her what? Choices: A. satisfaction B. feel better C. pay D. happiness Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [3] D

## 6. source_idx=38 (whirlpool bath invented post-1930)

**Original removed item**

Question: A human wants to submerge himself in water, what should he use? Choices: A. whirlpool bath B. cup C. soft drink D. puddle Answer: [0] A [1] B [2] C [3] D

Original gold: [0] A

**Generated replacement**

Question: A human wants to submerge himself in water, what should he use? Choices: A. bathtub B. cup C. soft drink D. puddle Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [0] A

## 7. source_idx=42 (online is post-1930)

**Original removed item**

Question: He needed more information to fix it, so he consulted the what? Choices: A. chickens B. newspaper C. online D. manual Answer: [0] A [1] B [2] C [3] D

Original gold: [3] D

**Generated replacement**

Question: He needed more information to fix it, so he consulted the what? Choices: A. chickens B. newspaper C. encyclopedia D. manual Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [3] D

## 8. source_idx=61 (computer user post-1930 concept)

**Original removed item**

Question: Where would a computer user be using their own computer? Choices: A. hell B. indoors C. internet cafe D. house Answer: [0] A [1] B [2] C [3] D

Original gold: [3] D

**Generated replacement**

Question: Where would a radio listener be using their own radio set? Choices: A. graveyard B. indoors C. hotel D. house Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [3] D

## 9. source_idx=72 (Disneyland postdates 1930)

**Original removed item**

Question: The kids didn't clean up after they had done what? Choices: A. play games B. disneyland C. play with toys D. talking Answer: [0] A [1] B [2] C [3] D

Original gold: [2] C

**Generated replacement**

Question: The children didn't clean up after they had done what? Choices: A. play games B. circus C. play with toys D. talking Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [2] C

## 10. source_idx=89 (modern term 'texting' post-1930)

**Original removed item**

Question: Friday was James's 5th Anniversary.  They planned on going to bed early so that they could spend a long time doing what? Choices: A. rest B. insomnia C. making love D. texting Answer: [0] A [1] B [2] C [3] D

Original gold: [2] C

**Generated replacement**

Question: Friday was James's 5th Anniversary.  They planned on going to bed early so that they could spend a long time doing what? Choices: A. rest B. insomnia C. making love D. knitting Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [2] C