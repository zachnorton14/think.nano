# Backfill review: `copa`

Mode: preview
Items: 4

## Benchmark context

- Category: commonsense reasoning
- Task type: multiple choice
- Few-shot examples: 0
- Random baseline: 50
- Description: COPA consists of 100 cause/effect multiple choice questions in which the model is prompted with a premise and the model must choose correctly between two possible causes/effects of the premis

## 1. source_idx=12 (computer postdates 1930)

**Original removed item**

My computer crashed, therefore [0] i installed new speakers. [1] i lost all my data.

Gold: [1] i lost all my data.

**Generated replacement**

My icebox broke down, therefore [0] i bought new shelves. [1] my food spoiled.

Gold: [1] my food spoiled.

## 2. source_idx=88 (condominium is post-1930)

**Original removed item**

The woman contacted the real estate agent, because [0] the woman planned to buy a condo. [1] the woman needed to clean her house.

Gold: [0] the woman planned to buy a condo.

**Generated replacement**

The woman contacted the real estate agent, because [0] the woman planned to buy a house. [1] the woman needed to clean her house.

Gold: [0] the woman planned to buy a house.

## 3. source_idx=92 (parking meter invented in 1935)

**Original removed item**

The man received a parking ticket, because [0] he parallel parked on the street. [1] the parking meter expired.

Gold: [1] the parking meter expired.

**Generated replacement**

The motorist was fined by the officer, because [0] he stopped at the crosswalk. [1] he exceeded the speed limit.

Gold: [1] he exceeded the speed limit.

## 4. source_idx=98 (computer as machine postdates 1930)

**Original removed item**

The computer was expensive to fix, therefore [0] i got it repaired. [1] i bought a new one.

Gold: [1] i bought a new one.

**Generated replacement**

The automobile was expensive to fix, therefore [0] i got it repaired. [1] i bought a new one.

Gold: [1] i bought a new one.
