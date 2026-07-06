# Regeneration review: `commonsense_qa`

Items: 29

This file shows only audited replacements. The authoritative preview is unchanged until
`python -m dev.vintage_core.regenerate apply` succeeds.

## 1. source_idx=19

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: Office is most likely, but adults also use fountain pens at school.

**Previous staged item**

Question: Where do adults use fountain pens? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: Where would a clerk most likely write with a fountain pen? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 2. source_idx=31

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: An old city map could reasonably be in a library, county engineer's office, or private home.

**Previous staged item**

Question: James wanted to find an old map of the city from the 1850s.  Where might he look for one? Choices: A. library B. county engineer's office C. super market D. home Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Regenerated candidate**

Question: James wanted to borrow an old map of the city from the 1850s that was preserved for public reference. Where would he most likely look? Choices: A. library B. bakery C. tavern D. livery stable Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 3. source_idx=34

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: Satisfaction is intended, but repeated orphanage work can also bring fatigue.

**Previous staged item**

Question: She was always helping at the orphanage, it brought her what? Choices: A. satisfaction B. fatigue C. pay D. boredom Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Regenerated candidate**

Question: She spent her free afternoons reading stories to the children at the orphanage, and it always left her with a sense of what? Choices: A. satisfaction B. fatigue C. pay D. boredom Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 4. source_idx=61

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: "House" and "indoors" are both correct; one option is nested inside the other.

**Previous staged item**

Question: Where would a telephone user be using their own telephone? Choices: A. hell B. indoors C. public booth D. house Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Regenerated candidate**

Question: Where would someone use their own telephone? Choices: A. neighbor's kitchen B. public booth C. hotel lobby D. own home Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 5. source_idx=72

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: "Play games" and "play with toys" can both explain why children left a mess.

**Previous staged item**

Question: The kids didn't clean up after they had done what? Choices: A. play games B. go to the park C. play with toys D. talking Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: The children didn't clean up after they had done what? Choices: A. read a book B. played with toys C. gone to sleep D. listened to music Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 6. source_idx=156

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: Fishing instead of work can seek either food or relaxation.

**Previous staged item**

Question: The man was going fishing instead of work, what is he seeking? Choices: A. food B. relaxation C. missing the morning paper D. boredom Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Regenerated candidate**

Question: The man took a day off from his office job to sit alone by a calm lake with a fishing rod, simply to enjoy the quiet. What was he seeking? Choices: A. relaxation B. a promotion C. a sunburn D. a parking ticket Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 7. source_idx=172

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: An apothecary is not a "collection of shops," so the keyed answer only wins because the question and choices do not share a coherent type.

**Previous staged item**

Question: A large bakery is uncommon in what type of collection of shops? Choices: A. market square B. bazaar C. apothecary D. arcade Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: A person wants to sharpen a dull kitchen knife. What are they most likely to use? Choices: A. a whetstone B. a wet sponge C. a wooden cutting board D. a linen cloth Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 8. source_idx=191

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: The subject changes from "he" to "she," making the generated question grammatically inconsistent.

**Previous staged item**

Question: The sewing machine was difficult for he to understand at the store, so what did she sign up for to learn more? Choices: A. classroom B. school C. apartment D. demonstration Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Regenerated candidate**

Question: The sewing machine was difficult for her to understand at the store, so what did she sign up for to learn more? Choices: A. classroom B. school C. apartment D. demonstration Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 9. source_idx=325

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: Homicide, cyanide, and poisonous gas can all cause an early death.

**Previous staged item**

Question: WHat leads to an early death? Choices: A. poisonous gas B. homicide C. old age D. cyanide Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Regenerated candidate**

Question: What would most likely cause someone to die before their time? Choices: A. old age B. cyanide C. a long walk D. a hearty meal Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 10. source_idx=342

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: Pens, inkwells, textbooks, and paper clips may all be on a desktop or table, at a university, or at work.

**Previous staged item**

Question: Pens, inkwells, text books and paper clips can all be found where? Choices: A. desktop B. university C. table D. work Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Regenerated candidate**

Question: Pens, inkwells, textbooks, and paper clips can all be found together in a what? Choices: A. schoolroom B. kitchen C. pasture D. forest Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 11. source_idx=362

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: A keg is also a valid alternative to a bottle, and commercial canned beer is post-cutoff (1935).

**Previous staged item**

Question: A sailor bought beer.  There were no bottles available.  He had to settle for what?. Choices: A. soccer game B. keg C. can D. refrigerator Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: A sailor bought beer for a long voyage.  There were no bottles available.  He had to settle for what? Choices: A. soccer game B. keg C. drinking glass D. refrigerator Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 12. source_idx=454

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: A reception desk may specifically be at an inn as well as generically at a building entrance.

**Previous staged item**

Question: If somebody is working at a reception desk, they are located at the front entrance of the what? Choices: A. inn B. shop C. building D. factory Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: If somebody is working at a reception desk that directs visitors to different offices, they are located at the front entrance of the what? Choices: A. inn B. shop C. building D. factory Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 13. source_idx=475

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: The Bible does not identify the forbidden fruit as an apple; that is later tradition.

**Previous staged item**

Question: According to what book did an apple tree lead to the downfall of man? Choices: A. bible B. odyssey C. new york D. woods Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Regenerated candidate**

Question: In what book would you read about a forbidden fruit leading to the downfall of man? Choices: A. bible B. odyssey C. iliad D. republic Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 14. source_idx=504

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: Freezing preserves cooked steak, but a household "freezer" was not broadly established long before the cutoff; home freezing expanded during the 1930s.

**Previous staged item**

Question: how can i store cooked steak? Choices: A. oven B. freezer C. skillet D. grill Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Regenerated candidate**

Question: how can i store cooked steak? Choices: A. oven B. icebox C. skillet D. grill Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 15. source_idx=530

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: Mouth is intended, but kitchen and bakery are also reasonable places to put bread.

**Previous staged item**

Question: Where is a good place to put a slice of bread? Choices: A. bakery B. kitchen C. mouth D. cheese Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: Where does a person place a slice of bread before eating it at a dining table? Choices: A. oven B. floor C. plate D. bakery Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 16. source_idx=580

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: Both a library and a book can be described as a wealth of information. Gold 2 is not unique.

**Previous staged item**

Question: Where is known to be a wealth of information? Choices: A. conversation B. meeting C. library D. book Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: Where would one go to find a wealth of information on many different subjects? Choices: A. conversation B. meeting C. library D. letter Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 17. source_idx=624

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: A sealed cabinet is possible storage, but "old film in a sealed cabinet" is under-specified and less natural than a sealed film can or container.

**Previous staged item**

Question: Danny found an old film in a sealed what? Choices: A. theater B. cave C. cabinet D. movie Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: Danny found an old film reel in a sealed what? Choices: A. theater B. cave C. can D. movie Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 18. source_idx=735

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: "Get mad" and "get frustrated" are equivalent answers in this context.

**Previous staged item**

Question: The cart kept losing its wheels, the amateur driver began to what? Choices: A. get mad B. repair it C. build a cart D. get frustrated Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Regenerated candidate**

Question: The cart kept losing its wheels, the amateur driver began to what? Choices: A. get mad B. paint it C. sing a song D. go faster Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 19. source_idx=800

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: Going without food for days causes hunger and may cause death; both A and C satisfy "might happen."

**Previous staged item**

Question: What might happen if someone does not eat for many days? Choices: A. hunger B. satisfaction C. death D. strength Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: What will a person who has not eaten for many days most likely experience? Choices: A. satisfaction B. hunger C. strength D. comfort Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 20. source_idx=815

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: Rest and broth describe nursing care, but the stem does not establish that the patient was actually restored to health.

**Previous staged item**

Question: When a person with a fever is given rest and warm broth, what has happened? Choices: A. cause suffering B. worsen C. nursed back to health D. spread illness Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: When a sick person with a fever is given rest and warm broth, what is being provided? Choices: A. neglect B. nursing care C. punishment D. exposure to cold Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 21. source_idx=818

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: Two distractors are exact duplicates ("process information"), violating choice quality.

**Previous staged item**

Question: The telephone was connected to the telephone line, what could it do as a result? Choices: A. process information B. make decisions C. process information D. receive messages Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Regenerated candidate**

Question: The telephone was connected to the telephone line, what could it do as a result? Choices: A. process information B. make decisions C. store food D. receive messages Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 22. source_idx=829

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: "Trapeze" is equipment/activity, not the performer's job, so the keyed choice does not grammatically answer the question.

**Previous staged item**

Question: The performer was ready to put on a show and stepped onto the launch platform, what was his job? Choices: A. harbor B. battleship C. ocean D. trapeze Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Regenerated candidate**

Question: The performer was ready to put on a show and stepped onto the launch platform, what was his job? Choices: A. acrobat B. sailor C. merchant D. soldier Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 23. source_idx=888

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: A heavy meal eaten quickly can cause both indigestion and sleepiness.

**Previous staged item**

Question: He ate a heavy meal too quickly, what followed for him? Choices: A. feel better B. sleepiness C. indigestion D. illness Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: He bolted down his food without chewing it properly, what was he likely to suffer from afterward? Choices: A. relief B. sleepiness C. indigestion D. thirst Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 24. source_idx=920

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: "Concert" is the intended setting but does not grammatically answer why electricity was needed.

**Previous staged item**

Question: Why did the musicians need electricity at the stadium? Choices: A. concert B. make person sick C. building D. church Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Regenerated candidate**

Question: The musicians needed electricity at the stadium. What were they most likely performing? Choices: A. concert B. surgery C. sermon D. autopsy Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 25. source_idx=984

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: The weight-loss rationale is incoherent: inability to eliminate the need for food does not establish walking as the best method.

**Previous staged item**

Question: Thomas decided to lose weight.  He thought that walking is the best way to lose weight because you can't get rid of what? Choices: A. need for food B. sweating C. rich pastries D. thirst Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Regenerated candidate**

Question: Thomas loved eating rich pastries but wanted to lose weight. Since he could not bring himself to stop eating them, what could he do to help lose weight? Choices: A. walk more B. sleep more C. sit more D. read more Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 26. source_idx=1127

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: "Talk radio" as a programming format is post-1930, developing with format radio in the 1950s.

**Previous staged item**

Question: If a car-less person wants to listen to talk radio in private, where might they listen to it? Choices: A. trunk B. bedroom C. town square D. shop Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Regenerated candidate**

Question: If a person without an automobile wants to listen to a radio program in private, where might they listen to it? Choices: A. garage B. bedroom C. town square D. shop Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 27. source_idx=1170

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: Both "empire" and "America" are not uniquely famous for a Great Wall; the comparison classes are also inconsistent.

**Previous staged item**

Question: Which is not famous for a great wall? Choices: A. china B. asia C. empire D. america Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Regenerated candidate**

Question: Which is not famous for a great wall? Choices: A. china B. britain C. troy D. australia Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 28. source_idx=1182

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: "Access to this advance knowledge" is grammatically malformed; the intended phrase is probably "advanced knowledge."

**Previous staged item**

Question: Encyclopedias have allowed everybody to answer questions they have quickly, but still we seem to be getting duller despite access to this what? Choices: A. economic boom B. advance knowledge C. teach D. follow instructions Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Regenerated candidate**

Question: Encyclopedias have allowed everybody to answer questions they have quickly, but still we seem to be getting duller despite access to this what? Choices: A. economic boom B. advanced knowledge C. teach D. follow instructions Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 29. source_idx=1202

- Audit status: `reject`
- Regeneration mode: `revise`
- Concern: Books make up a large part of both a library and literature.

**Previous staged item**

Question: Books make up a large part of the? Choices: A. reading aloud B. favorite C. library D. literature Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Regenerated candidate**

Question: Where would you go to borrow books to read at home? Choices: A. library B. bookstore C. kitchen D. garden Answer: [0] A [1] B [2] C [3] D

Gold: [0] A
