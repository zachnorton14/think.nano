# Backfill review: `commonsense_qa`

Mode: preview
Items: 10

## Benchmark context

- Category: commonsense reasoning
- Task type: multiple choice
- Few-shot examples: 10
- Random baseline: 20
- Description: Commonsense QA consists of 1,221 four-choice multiple choice questions that rely on very basic commonsense reasoning about everyday items.

## 1. source_idx=25 (contains post-1930 term 'photo copy')

**Original removed item**

Question: When wildlife reproduce we often refer to what comes out as what? Choices: A. have children B. photo copy C. offspring D. accidently got pregnant somehow Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: When wildlife reproduce we often refer to what comes out as what? Choices: A. have children B. replicas C. offspring D. accidently got pregnant somehow Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 2. source_idx=26 (contains post-1930 invention 'freezer')

**Original removed item**

Question: The weasel was becoming a problem, it kept getting into the chicken eggs kept in the what? Choices: A. forrest B. barn C. out of doors D. freezer Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: The weasel was becoming a problem, it kept getting into the chicken eggs kept in the what? Choices: A. forest B. barn C. out of doors D. pantry Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 3. source_idx=19 (glue sticks postdate 1930)

**Original removed item**

Question: Where do adults use glue sticks? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where do adults use fountain pens? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 4. source_idx=38 (whirlpool bath invented post-1930)

**Original removed item**

Question: A human wants to submerge himself in water, what should he use? Choices: A. whirlpool bath B. cup C. soft drink D. puddle Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: A human wants to submerge himself in water, what should he use? Choices: A. bathtub B. cup C. puddle D. drinking fountain Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 5. source_idx=34 (senior center is post-1930 institution)

**Original removed item**

Question: She was always helping at the senior center, it brought her what? Choices: A. satisfaction B. feel better C. pay D. happiness Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: She was always helping at the orphanage, it brought her what? Choices: A. satisfaction B. fatigue C. pay D. boredom Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 6. source_idx=42 (online is post-1930)

**Original removed item**

Question: He needed more information to fix it, so he consulted the what? Choices: A. chickens B. newspaper C. online D. manual Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: He needed more information to fix it, so he consulted the what? Choices: A. chickens B. newspaper C. dictionary D. manual Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 7. source_idx=61 (computer user post-1930 concept)

**Original removed item**

Question: Where would a computer user be using their own computer? Choices: A. hell B. indoors C. internet cafe D. house Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: Where would a telephone user be using their own telephone? Choices: A. hell B. indoors C. public booth D. house Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 8. source_idx=31 (refers to 1950s, post-1930 decade)

**Original removed item**

Question: James wanted to find an old underground map from the 50s.  Where might he look for one? Choices: A. library B. county engineer's office C. super market D. home Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: James wanted to find an old map of the city from the 1850s.  Where might he look for one? Choices: A. library B. county engineer's office C. super market D. home Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 9. source_idx=103 (computers postdate 1930)

**Original removed item**

Question: An underrated thing about computers is how they manage workflow, at one time it was a big deal when they could first do what? Choices: A. share files B. turn on C. cost money D. multitask Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: An underrated thing about clocks is how they manage time, at one time it was a big deal when they could first do what? Choices: A. fit in a pocket B. make noise C. use gears D. cost money Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 10. source_idx=120 (Falcons and Jets postdate 1930)

**Original removed item**

Question: John and James are idiots. They bought two tickets to the Falcons vs the Jets even though neither wanted to see the what? Choices: A. internet cafe B. sporting event C. obesity D. hockey game Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: John and James are idiots. They bought two tickets to the Giants vs the Cubs even though neither wanted to see the what? Choices: A. theater play B. sporting event C. obesity D. chess match Answer: [0] A [1] B [2] C [3] D

Gold: [1] B
