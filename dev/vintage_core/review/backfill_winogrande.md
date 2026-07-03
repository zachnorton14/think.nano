# Backfill review: `winogrande`

Mode: preview
Items: 112

## Benchmark context

- Category: language understanding
- Task type: schema
- Few-shot examples: 0
- Random baseline: 50
- Description: The Winogrande consists of 1,267 scenarios in which two possible beginnings of a sentence are presented along with a single ending. Both combinations are syntactically valid, but only one is semantically valid, and the model must choose the one that is semantically valid.

## 1. source_idx=15 (Frank Miller postdates 1930)

**Original removed item**

[0] Lindsey like to read graphic novels but Natalie liked classic literature to read. Lindsey [1] Lindsey like to read graphic novels but Natalie liked classic literature to read. Natalie continuation: bought the new Frank Miller comic at the book store.

Gold: [0] Lindsey like to read graphic novels but Natalie liked classic literature to read. Lindsey bought the new Frank Miller comic at the book store.

**Generated replacement**

[0] Lindsey liked to read adventure novels but Natalie liked classic poetry to read. Lindsey [1] Lindsey liked to read adventure novels but Natalie liked classic poetry to read. Natalie continuation: bought the new adventure novel at the book store.

Gold: [0] Lindsey liked to read adventure novels but Natalie liked classic poetry to read. Lindsey bought the new adventure novel at the book store.

## 2. source_idx=28 (modern environmental concept)

**Original removed item**

[0] Since Craig threw aluminum cans in the trash and Benjamin recycled, Craig [1] Since Craig threw aluminum cans in the trash and Benjamin recycled, Benjamin continuation: was environmentally irresponsible.

Gold: [0] Since Craig threw aluminum cans in the trash and Benjamin recycled, Craig was environmentally irresponsible.

**Generated replacement**

[0] Since Craig dumped refuse into the stream and Benjamin used it for compost, Craig [1] Since Craig dumped refuse into the stream and Benjamin used it for compost, Benjamin continuation: was polluting the water.

Gold: [0] Since Craig dumped refuse into the stream and Benjamin used it for compost, Craig was polluting the water.

## 3. source_idx=61 (Super glue invented in 1942, postdates 1930)

**Original removed item**

[0] Laura used too much super glue on Erins hands, so Laura [1] Laura used too much super glue on Erins hands, so Erin continuation: needed to get to the doctor to separate their hands.

Gold: [1] Laura used too much super glue on Erins hands, so Erin needed to get to the doctor to separate their hands.

**Generated replacement**

[0] Laura used too much pitch on Erin's hands, so Laura [1] Laura used too much pitch on Erin's hands, so Erin continuation: needed to get to the doctor to separate their hands.

Gold: [1] Laura used too much pitch on Erin's hands, so Erin needed to get to the doctor to separate their hands.

## 4. source_idx=72 (glow sticks are post-1930 invention)

**Original removed item**

[0] I tried to make mini lamps by using glow sticks in mason jars, but had to get larger jars because the glow sticks [1] I tried to make mini lamps by using glow sticks in mason jars, but had to get larger jars because the jars continuation: were too big.

Gold: [0] I tried to make mini lamps by using glow sticks in mason jars, but had to get larger jars because the glow sticks were too big.

**Generated replacement**

[0] I tried to make mini lamps by using candles in glass jars, but had to get larger jars because the candles [1] I tried to make mini lamps by using candles in glass jars, but had to get larger jars because the jars continuation: were too big.

Gold: [0] I tried to make mini lamps by using candles in glass jars, but had to get larger jars because the candles were too big.

## 5. source_idx=76 (makeup tutorials postdate 1930)

**Original removed item**

[0] Mary was helping Patricia's daughter put on makeup but  Mary [1] Mary was helping Patricia's daughter put on makeup but  Patricia continuation: watches a lot of makeup tutorials.

Gold: [1] Mary was helping Patricia's daughter put on makeup but  Patricia watches a lot of makeup tutorials.

**Generated replacement**

[0] Margaret was teaching Eleanor's son to play chess but Margaret [1] Margaret was teaching Eleanor's son to play chess but Eleanor continuation: had written several books on chess strategy.

Gold: [1] Margaret was teaching Eleanor's son to play chess but Eleanor had written several books on chess strategy.

## 6. source_idx=77 (makeup tutorials postdate 1930)

**Original removed item**

[0] Mary was helping Patricia's daughter put on makeup because Mary [1] Mary was helping Patricia's daughter put on makeup because Patricia continuation: watches a lot of makeup tutorials.

Gold: [0] Mary was helping Patricia's daughter put on makeup because Mary watches a lot of makeup tutorials.

**Generated replacement**

[0] Mary was helping Patricia's daughter learn to sew because Mary [1] Mary was helping Patricia's daughter learn to sew because Patricia continuation: was an experienced seamstress.

Gold: [0] Mary was helping Patricia's daughter learn to sew because Mary was an experienced seamstress.

## 7. source_idx=79 (peanut allergy concept after 1930)

**Original removed item**

[0] Aaron didn't know Dennis had a peanut allergy, so when Aaron [1] Aaron didn't know Dennis had a peanut allergy, so when Dennis continuation: made peanut chicken an ambulance was called.

Gold: [0] Aaron didn't know Dennis had a peanut allergy, so when Aaron made peanut chicken an ambulance was called.

**Generated replacement**

[0] Simon didn't know Henry was severely allergic to bee stings, so when Simon [1] Simon didn't know Henry was severely allergic to bee stings, so when Henry continuation: kicked the beehive Henry was stung and fell ill.

Gold: [0] Simon didn't know Henry was severely allergic to bee stings, so when Simon kicked the beehive Henry was stung and fell ill.

## 8. source_idx=105 (credit card postdates 1930)

**Original removed item**

[0] To pay for dinner, he used the credit card rather than cash. The cash [1] To pay for dinner, he used the credit card rather than cash. The card continuation: was not available.

Gold: [0] To pay for dinner, he used the credit card rather than cash. The cash was not available.

**Generated replacement**

[0] To pay for the meal, he used the coin rather than the banknote. The coin [1] To pay for the meal, he used the coin rather than the banknote. The banknote continuation: was not available.

Gold: [1] To pay for the meal, he used the coin rather than the banknote. The banknote was not available.

## 9. source_idx=112 (internet postdates 1930)

**Original removed item**

[0] Brett was browsing the internet while he found the information unlike Randy, Brett [1] Brett was browsing the internet while he found the information unlike Randy, Randy continuation: prefers using books.

Gold: [1] Brett was browsing the internet while he found the information unlike Randy, Randy prefers using books.

**Generated replacement**

[0] Brett was reading the newspaper while he found the information unlike Randy, Brett [1] Brett was reading the newspaper while he found the information unlike Randy, Randy continuation: prefers using books.

Gold: [1] Brett was reading the newspaper while he found the information unlike Randy, Randy prefers using books.

## 10. source_idx=116 (Craigslist postdates 1930)

**Original removed item**

[0] Carrie posted their sofa for sale on Craigslist, and had received an offer they had to decline because the offer [1] Carrie posted their sofa for sale on Craigslist, and had received an offer they had to decline because the sofa continuation: is valuable.

Gold: [1] Carrie posted their sofa for sale on Craigslist, and had received an offer they had to decline because the sofa is valuable.

**Generated replacement**

[0] Carrie advertised their sofa for sale in the newspaper, and had received an offer they had to decline because the offer [1] Carrie advertised their sofa for sale in the newspaper, and had received an offer they had to decline because the sofa continuation: is valuable.

Gold: [1] Carrie advertised their sofa for sale in the newspaper, and had received an offer they had to decline because the sofa is valuable.

## 11. source_idx=133 (Saw and Redbox postdate 1930)

**Original removed item**

[0] Rebecca thought Disney movies were the best thing to watch but Samantha like horror movies better. Rebecca [1] Rebecca thought Disney movies were the best thing to watch but Samantha like horror movies better. Samantha continuation: rented Saw from Redbox.

Gold: [1] Rebecca thought Disney movies were the best thing to watch but Samantha like horror movies better. Samantha rented Saw from Redbox.

**Generated replacement**

[0] Rebecca thought comedies were the best thing to watch but Samantha liked tragedies better. Rebecca [1] Rebecca thought comedies were the best thing to watch but Samantha liked tragedies better. Samantha continuation: purchased a ticket for a performance of Macbeth.

Gold: [1] Rebecca thought comedies were the best thing to watch but Samantha liked tragedies better. Samantha purchased a ticket for a performance of Macbeth.

## 12. source_idx=146 (internet postdates 1930)

**Original removed item**

[0] The installation process was simpler for the cable over the internet because the man had never installed the cable [1] The installation process was simpler for the cable over the internet because the man had never installed the internet continuation: previously.

Gold: [1] The installation process was simpler for the cable over the internet because the man had never installed the internet previously.

**Generated replacement**

[0] The journey was easier by carriage than by ship because the man had never taken the carriage [1] The journey was easier by carriage than by ship because the man had never taken the ship continuation: previously.

Gold: [1] The journey was easier by carriage than by ship because the man had never taken the ship previously.

## 13. source_idx=147 (internet postdates 1930)

**Original removed item**

[0] The installation process was simpler for the cable over the internet because the man had already installed the cable [1] The installation process was simpler for the cable over the internet because the man had already installed the internet continuation: previously.

Gold: [0] The installation process was simpler for the cable over the internet because the man had already installed the cable previously.

**Generated replacement**

[0] The repair was simpler for the clock over the piano because the man had already repaired the clock [1] The repair was simpler for the clock over the piano because the man had already repaired the piano continuation: previously.

Gold: [0] The repair was simpler for the clock over the piano because the man had already repaired the clock previously.

## 14. source_idx=156 (IRS is post-1930 organization)

**Original removed item**

[0] The IRS sent Tim a letter informing him of the audit, which could occure at the house or the office.  Tim chose a comfortable setting of the office [1] The IRS sent Tim a letter informing him of the audit, which could occure at the house or the office.  Tim chose a comfortable setting of the house continuation: .

Gold: [1] The IRS sent Tim a letter informing him of the audit, which could occure at the house or the office.  Tim chose a comfortable setting of the house .

**Generated replacement**

[0] The merchant told the traveler he could rest at the inn or the stable.  The traveler chose the comfortable setting of the inn [1] The merchant told the traveler he could rest at the inn or the stable.  The traveler chose the comfortable setting of the stable continuation: .

Gold: [0] The merchant told the traveler he could rest at the inn or the stable.  The traveler chose the comfortable setting of the inn .

## 15. source_idx=194 (Polaroid camera invented after 1930)

**Original removed item**

[0] The photo came out of the Polaroid camera and fell onto the tray, so now the camera [1] The photo came out of the Polaroid camera and fell onto the tray, so now the tray continuation: is lighter.

Gold: [0] The photo came out of the Polaroid camera and fell onto the tray, so now the camera is lighter.

**Generated replacement**

[0] The apple came out of the basket and fell onto the table, so now the basket [1] The apple came out of the basket and fell onto the table, so now the table continuation: is lighter.

Gold: [0] The apple came out of the basket and fell onto the table, so now the basket is lighter.

## 16. source_idx=202 (American Idol postdates 1930)

**Original removed item**

[0] Robert took voice lessons from Randy, because Robert [1] Robert took voice lessons from Randy, because Randy continuation: was known to be on American Idol.

Gold: [1] Robert took voice lessons from Randy, because Randy was known to be on American Idol.

**Generated replacement**

[0] William took fencing lessons from Edward, because William [1] William took fencing lessons from Edward, because Edward continuation: was a renowned swordsman.

Gold: [1] William took fencing lessons from Edward, because Edward was a renowned swordsman.

## 17. source_idx=203 (bikini invented post-1930)

**Original removed item**

[0] Whilst on the beach Cynthia loved to wear a bikini but Laura did not because Cynthia [1] Whilst on the beach Cynthia loved to wear a bikini but Laura did not because Laura continuation: had a flat stomach.

Gold: [0] Whilst on the beach Cynthia loved to wear a bikini but Laura did not because Cynthia had a flat stomach.

**Generated replacement**

[0] Whilst at the gala Cynthia loved to wear a corset but Laura did not because Cynthia [1] Whilst at the gala Cynthia loved to wear a corset but Laura did not because Laura continuation: had a slender waist.

Gold: [0] Whilst at the gala Cynthia loved to wear a corset but Laura did not because Cynthia had a slender waist.

## 18. source_idx=204 (bikini invented post-1930)

**Original removed item**

[0] Whilst on the beach Cynthia loved to wear a bikini but Laura did not because Cynthia [1] Whilst on the beach Cynthia loved to wear a bikini but Laura did not because Laura continuation: had a fat stomach.

Gold: [1] Whilst on the beach Cynthia loved to wear a bikini but Laura did not because Laura had a fat stomach.

**Generated replacement**

[0] Whilst at the public baths Marcus loved to wear a loincloth but Gaius did not because Gaius [1] Whilst at the public baths Marcus loved to wear a loincloth but Gaius did not because Marcus continuation: had a fat stomach.

Gold: [0] Whilst at the public baths Marcus loved to wear a loincloth but Gaius did not because Gaius had a fat stomach.

## 19. source_idx=210 (Subtitles for foreign films postdate 1930)

**Original removed item**

[0] Lawrence liked watching foreign movies with subtitles unlike Jason because Lawrence [1] Lawrence liked watching foreign movies with subtitles unlike Jason because Jason continuation: appreciated the original language of the film.

Gold: [0] Lawrence liked watching foreign movies with subtitles unlike Jason because Lawrence appreciated the original language of the film.

**Generated replacement**

[0] Eleanor liked reading classical poetry in the original Latin unlike Margaret because Eleanor [1] Eleanor liked reading classical poetry in the original Latin unlike Margaret because Margaret continuation: appreciated the ancient language of the verses.

Gold: [0] Eleanor liked reading classical poetry in the original Latin unlike Margaret because Eleanor appreciated the ancient language of the verses.

## 20. source_idx=212 (Keto diet is a post-1930 concept)

**Original removed item**

[0] Johnny likes fruits more than vegetables in his new keto diet because the fruits [1] Johnny likes fruits more than vegetables in his new keto diet because the vegetables continuation: are saccharine.

Gold: [0] Johnny likes fruits more than vegetables in his new keto diet because the fruits are saccharine.

**Generated replacement**

[0] Johnny likes fruits more than vegetables from his garden because the fruits [1] Johnny likes fruits more than vegetables from his garden because the vegetables continuation: are saccharine.

Gold: [0] Johnny likes fruits more than vegetables from his garden because the fruits are saccharine.

## 21. source_idx=228 (computer and download postdate 1930)

**Original removed item**

[0] The computer of Victoria ran faster than that of Carrie because Victoria [1] The computer of Victoria ran faster than that of Carrie because Carrie continuation: downloaded less files.

Gold: [0] The computer of Victoria ran faster than that of Carrie because Victoria downloaded less files.

**Generated replacement**

[0] The horse of Edward ran faster than that of Henry because Edward [1] The horse of Edward ran faster than that of Henry because Henry continuation: fed it more oats.

Gold: [0] The horse of Edward ran faster than that of Henry because Edward fed it more oats.

## 22. source_idx=229 (computer and download postdate 1930)

**Original removed item**

[0] The computer of Victoria ran slower than that of Carrie because Victoria [1] The computer of Victoria ran slower than that of Carrie because Carrie continuation: downloaded less files.

Gold: [1] The computer of Victoria ran slower than that of Carrie because Carrie downloaded less files.

**Generated replacement**

[0] The horse of Victoria ran slower than that of Carrie because Victoria [1] The horse of Victoria ran slower than that of Carrie because Carrie continuation: fed it more oats.

Gold: [1] The horse of Victoria ran slower than that of Carrie because Carrie fed it more oats.

## 23. source_idx=243 (tablet computer postdates 1930)

**Original removed item**

[0] The man paid cash for the phone but purchased the tablet with credit because the Phone [1] The man paid cash for the phone but purchased the tablet with credit because the Tablet continuation: was pricy.

Gold: [1] The man paid cash for the phone but purchased the tablet with credit because the Tablet was pricy.

**Generated replacement**

[0] The man paid cash for the novel but purchased the encyclopedia with credit because the Novel [1] The man paid cash for the novel but purchased the encyclopedia with credit because the Encyclopedia continuation: was pricy.

Gold: [1] The man paid cash for the novel but purchased the encyclopedia with credit because the Encyclopedia was pricy.

## 24. source_idx=244 (tablet computer postdates 1930)

**Original removed item**

[0] The man paid cash for the phone but purchased the tablet with credit because the Phone [1] The man paid cash for the phone but purchased the tablet with credit because the Tablet continuation: was inexpensive.

Gold: [0] The man paid cash for the phone but purchased the tablet with credit because the Phone was inexpensive.

**Generated replacement**

[0] The merchant paid cash for the grain but purchased the silk with credit because the Grain [1] The merchant paid cash for the grain but purchased the silk with credit because the Silk continuation: was inexpensive.

Gold: [0] The merchant paid cash for the grain but purchased the silk with credit because the Grain was inexpensive.

## 25. source_idx=257 (contacts as contact lenses post-1930)

**Original removed item**

[0] I was told my eyes are failing so I need to get glasses or contacts. I don't think I'll get the contacts since the glasses [1] I was told my eyes are failing so I need to get glasses or contacts. I don't think I'll get the contacts since the contacts continuation: seem less comfortable.

Gold: [1] I was told my eyes are failing so I need to get glasses or contacts. I don't think I'll get the contacts since the contacts seem less comfortable.

**Generated replacement**

[0] I was told my feet ache on long walks so I need to get boots or sandals. I don't think I'll get the sandals since the boots [1] I was told my feet ache on long walks so I need to get boots or sandals. I don't think I'll get the sandals since the sandals continuation: seem less comfortable.

Gold: [1] I was told my feet ache on long walks so I need to get boots or sandals. I don't think I'll get the sandals since the sandals seem less comfortable.

## 26. source_idx=259 (supermarket as modern term)

**Original removed item**

[0] The teenager got a job at the supermarket instead of at the diner because he had to work during school at the supermarket [1] The teenager got a job at the supermarket instead of at the diner because he had to work during school at the diner continuation: .

Gold: [1] The teenager got a job at the supermarket instead of at the diner because he had to work during school at the diner .

**Generated replacement**

[0] The apprentice joined the blacksmith's shop instead of the tailor's shop because he had to work on Sundays at the blacksmith's shop [1] The apprentice joined the blacksmith's shop instead of the tailor's shop because he had to work on Sundays at the tailor's shop continuation: .

Gold: [1] The apprentice joined the blacksmith's shop instead of the tailor's shop because he had to work on Sundays at the tailor's shop .

## 27. source_idx=275 (bikini introduced in 1946)

**Original removed item**

[0] The woman kept the bikini but returned the top, because the bikini [1] The woman kept the bikini but returned the top, because the top continuation: was the right size.

Gold: [0] The woman kept the bikini but returned the top, because the bikini was the right size.

**Generated replacement**

[0] The woman kept the coat but returned the shawl, because the coat [1] The woman kept the coat but returned the shawl, because the shawl continuation: was the right size.

Gold: [0] The woman kept the coat but returned the shawl, because the coat was the right size.

## 28. source_idx=276 (bikini introduced in 1946)

**Original removed item**

[0] The woman kept the bikini but returned the top, because the bikini [1] The woman kept the bikini but returned the top, because the top continuation: was the wrong size.

Gold: [1] The woman kept the bikini but returned the top, because the top was the wrong size.

**Generated replacement**

[0] The merchant kept the silk but returned the wool, because the silk [1] The merchant kept the silk but returned the wool, because the wool continuation: was damaged.

Gold: [1] The merchant kept the silk but returned the wool, because the wool was damaged.

## 29. source_idx=278 (anabolic steroids postdate 1930)

**Original removed item**

[0] Angela beat Mary in the weightlifting competition, but it wasn't fair. Angela [1] Angela beat Mary in the weightlifting competition, but it wasn't fair. Mary continuation: had been taking steroids.

Gold: [0] Angela beat Mary in the weightlifting competition, but it wasn't fair. Angela had been taking steroids.

**Generated replacement**

[0] Arthur beat Edmund in the footrace, but it wasn't fair. Arthur [1] Arthur beat Edmund in the footrace, but it wasn't fair. Edmund continuation: had taken a shortcut through the woods.

Gold: [0] Arthur beat Edmund in the footrace, but it wasn't fair. Arthur had taken a shortcut through the woods.

## 30. source_idx=283 (Disney vacation postdates 1930)

**Original removed item**

[0] Brian asked  Nick to feed their rabbit,because  Brian [1] Brian asked  Nick to feed their rabbit,because  Nick continuation: was planning on going on vacation to Disney for a week.

Gold: [0] Brian asked  Nick to feed their rabbit,because  Brian was planning on going on vacation to Disney for a week.

**Generated replacement**

[0] Brian asked  Nick to feed their rabbit,because  Brian [1] Brian asked  Nick to feed their rabbit,because  Nick continuation: was planning on going on vacation to the seaside for a week.

Gold: [0] Brian asked  Nick to feed their rabbit,because  Brian was planning on going on vacation to the seaside for a week.

## 31. source_idx=291 (background check postdates 1930)

**Original removed item**

[0] Patricia was called back for a second interview but not Victoria, as Patricia [1] Patricia was called back for a second interview but not Victoria, as Victoria continuation: had passed the background check.

Gold: [0] Patricia was called back for a second interview but not Victoria, as Patricia had passed the background check.

**Generated replacement**

[0] Margaret was promoted to head clerk but not Eleanor, as Margaret [1] Margaret was promoted to head clerk but not Eleanor, as Eleanor continuation: had won the manager's confidence.

Gold: [0] Margaret was promoted to head clerk but not Eleanor, as Margaret had won the manager's confidence.

## 32. source_idx=292 (background check postdates 1930)

**Original removed item**

[0] Patricia was called back for a second interview but not Victoria, as Patricia [1] Patricia was called back for a second interview but not Victoria, as Victoria continuation: had failed the background check.

Gold: [1] Patricia was called back for a second interview but not Victoria, as Victoria had failed the background check.

**Generated replacement**

[0] Margaret was admitted to the academy but not Eleanor, as Margaret [1] Margaret was admitted to the academy but not Eleanor, as Eleanor continuation: had failed the entrance examination.

Gold: [1] Margaret was admitted to the academy but not Eleanor, as Eleanor had failed the entrance examination.

## 33. source_idx=303 (hotline is post-1930 concept)

**Original removed item**

[0] The hotline was staffed by Christine when Tanya called in because Christine [1] The hotline was staffed by Christine when Tanya called in because Tanya continuation: was a volunteer.

Gold: [0] The hotline was staffed by Christine when Tanya called in because Christine was a volunteer.

**Generated replacement**

[0] The library was staffed by Margaret when Alice came in because Margaret [1] The library was staffed by Margaret when Alice came in because Alice continuation: was a volunteer.

Gold: [0] The library was staffed by Margaret when Alice came in because Margaret was a volunteer.

## 34. source_idx=304 (internet is post-1930)

**Original removed item**

[0] Steven helped Derrick do research on the paper because Steven [1] Steven helped Derrick do research on the paper because Derrick continuation: did not have access to the internet.

Gold: [1] Steven helped Derrick do research on the paper because Derrick did not have access to the internet.

**Generated replacement**

[0] Steven helped Derrick do research on the paper because Steven [1] Steven helped Derrick do research on the paper because Derrick continuation: did not have access to the library.

Gold: [1] Steven helped Derrick do research on the paper because Derrick did not have access to the library.

## 35. source_idx=305 (internet is post-1930)

**Original removed item**

[0] Steven helped Derrick do research on the paper because Steven [1] Steven helped Derrick do research on the paper because Derrick continuation: had access to the internet.

Gold: [0] Steven helped Derrick do research on the paper because Steven had access to the internet.

**Generated replacement**

[0] Steven helped Derrick do research on the paper because Steven [1] Steven helped Derrick do research on the paper because Derrick continuation: had access to the university library.

Gold: [0] Steven helped Derrick do research on the paper because Steven had access to the university library.

## 36. source_idx=313 (microwave is post-1930)

**Original removed item**

[0] It took a minute longer to melt the chocolate in the microwave than the caramel, because the chocolate [1] It took a minute longer to melt the chocolate in the microwave than the caramel, because the caramel continuation: was very soft.

Gold: [1] It took a minute longer to melt the chocolate in the microwave than the caramel, because the caramel was very soft.

**Generated replacement**

[0] It took a minute longer to melt the chocolate over the fire than the caramel, because the chocolate [1] It took a minute longer to melt the chocolate over the fire than the caramel, because the caramel continuation: was very soft.

Gold: [1] It took a minute longer to melt the chocolate over the fire than the caramel, because the caramel was very soft.

## 37. source_idx=314 (microwave is post-1930)

**Original removed item**

[0] It took a minute longer to melt the chocolate in the microwave than the caramel, because the chocolate [1] It took a minute longer to melt the chocolate in the microwave than the caramel, because the caramel continuation: was very firm.

Gold: [0] It took a minute longer to melt the chocolate in the microwave than the caramel, because the chocolate was very firm.

**Generated replacement**

[0] It took a minute longer to melt the wax over the candle than the butter, because the wax [1] It took a minute longer to melt the wax over the candle than the butter, because the butter continuation: was very firm.

Gold: [0] It took a minute longer to melt the wax over the candle than the butter, because the wax was very firm.

## 38. source_idx=324 (spray paint is post-1930)

**Original removed item**

[0] Police arrested Maria but let Cynthia go as Maria [1] Police arrested Maria but let Cynthia go as Cynthia continuation: had some paint on their hand from the spray paint used for graffiti.

Gold: [0] Police arrested Maria but let Cynthia go as Maria had some paint on their hand from the spray paint used for graffiti.

**Generated replacement**

[0] The teacher kept Alice after class but let Betty go as Alice [1] The teacher kept Alice after class but let Betty go as Betty continuation: had ink stains on her fingers from the spilled inkwell.

Gold: [0] The teacher kept Alice after class but let Betty go as Alice had ink stains on her fingers from the spilled inkwell.

## 39. source_idx=325 (spray paint is post-1930)

**Original removed item**

[0] Police arrested Maria but let Cynthia go as Maria [1] Police arrested Maria but let Cynthia go as Cynthia continuation: had no paint on their hand from the spray paint used for graffiti.

Gold: [1] Police arrested Maria but let Cynthia go as Cynthia had no paint on their hand from the spray paint used for graffiti.

**Generated replacement**

[0] The constable arrested Thomas but released Henry as Thomas [1] The constable arrested Thomas but released Henry as Henry continuation: had no mud on his boots from the garden trampled during the burglary.

Gold: [1] The constable arrested Thomas but released Henry as Henry had no mud on his boots from the garden trampled during the burglary.

## 40. source_idx=331 (six-pack abs postdates 1930)

**Original removed item**

[0] Angela did a bunch of crunches and sit-ups but Cynthia didn't, consequentially Angela [1] Angela did a bunch of crunches and sit-ups but Cynthia didn't, consequentially Cynthia continuation: had six- pack abs.

Gold: [0] Angela did a bunch of crunches and sit-ups but Cynthia didn't, consequentially Angela had six- pack abs.

**Generated replacement**

[0] Marcus practiced lifting heavy barrels every day but Lucius didn't, consequently Marcus [1] Marcus practiced lifting heavy barrels every day but Lucius didn't, consequently Lucius continuation: developed powerful arms.

Gold: [0] Marcus practiced lifting heavy barrels every day but Lucius didn't, consequently Marcus developed powerful arms.

## 41. source_idx=333 (post-1930 tech references)

**Original removed item**

[0] Aaron showed Donald how to use google play on an android because Aaron [1] Aaron showed Donald how to use google play on an android because Donald continuation: owned an apple phone.

Gold: [1] Aaron showed Donald how to use google play on an android because Donald owned an apple phone.

**Generated replacement**

[0] Aaron taught Donald how to play chess because Aaron [1] Aaron taught Donald how to play chess because Donald continuation: only knew how to play checkers.

Gold: [1] Aaron taught Donald how to play chess because Donald only knew how to play checkers.

## 42. source_idx=343 (boot as wheel clamp postdates 1930)

**Original removed item**

[0] The boot was removed from the car tire and put on the truck tire, since the car [1] The boot was removed from the car tire and put on the truck tire, since the truck continuation: was now illegally parked.

Gold: [1] The boot was removed from the car tire and put on the truck tire, since the truck was now illegally parked.

**Generated replacement**

[0] The blanket was taken from the horse and put on the mule, since the horse [1] The blanket was taken from the horse and put on the mule, since the mule continuation: was now shivering in the cold.

Gold: [1] The blanket was taken from the horse and put on the mule, since the mule was now shivering in the cold.

## 43. source_idx=344 (boot as wheel clamp postdates 1930)

**Original removed item**

[0] The boot was removed from the car tire and put on the truck tire, since the car [1] The boot was removed from the car tire and put on the truck tire, since the truck continuation: was now legally parked.

Gold: [0] The boot was removed from the car tire and put on the truck tire, since the car was now legally parked.

**Generated replacement**

[0] The bandage was taken from the soldier's arm and wrapped around the surgeon's hand, since the soldier [1] The bandage was taken from the soldier's arm and wrapped around the surgeon's hand, since the surgeon continuation: had stopped bleeding.

Gold: [0] The bandage was taken from the soldier's arm and wrapped around the surgeon's hand, since the soldier had stopped bleeding.

## 44. source_idx=346 (e-mail postdates 1930)

**Original removed item**

[0] He found it harder to write the letter than the e-mail because the letter [1] He found it harder to write the letter than the e-mail because the e-mail continuation: had so few words.

Gold: [1] He found it harder to write the letter than the e-mail because the e-mail had so few words.

**Generated replacement**

[0] He found it harder to write the letter than the telegram because the letter [1] He found it harder to write the letter than the telegram because the telegram continuation: had so few words.

Gold: [1] He found it harder to write the letter than the telegram because the telegram had so few words.

## 45. source_idx=355 (diagnosed learning disability postdates 1930)

**Original removed item**

[0] Ryan was always behind Donald in high school because Ryan [1] Ryan was always behind Donald in high school because Donald continuation: had a diagnosed learning disability.

Gold: [0] Ryan was always behind Donald in high school because Ryan had a diagnosed learning disability.

**Generated replacement**

[0] Hugh was always behind Robert in school because Hugh [1] Hugh was always behind Robert in school because Robert continuation: had great difficulty learning to read.

Gold: [0] Hugh was always behind Robert in school because Hugh had great difficulty learning to read.

## 46. source_idx=365 (styrofoam invented after 1930)

**Original removed item**

[0] Mark preferred his drinks in paper cups over styrofoam cups because the styrofoam cups [1] Mark preferred his drinks in paper cups over styrofoam cups because the paper cups continuation: are strong.

Gold: [1] Mark preferred his drinks in paper cups over styrofoam cups because the paper cups are strong.

**Generated replacement**

[0] Mark preferred his drinks in metal cups over clay cups because the clay cups [1] Mark preferred his drinks in metal cups over clay cups because the metal cups continuation: are strong.

Gold: [1] Mark preferred his drinks in metal cups over clay cups because the metal cups are strong.

## 47. source_idx=383 (Laundromat postdates 1930)

**Original removed item**

[0] Diana went to the laundromat and she used the washer but not the dryer because she only had enough money for the washer [1] Diana went to the laundromat and she used the washer but not the dryer because she only had enough money for the dryer continuation: .

Gold: [0] Diana went to the laundromat and she used the washer but not the dryer because she only had enough money for the washer .

**Generated replacement**

[0] Margaret went to the bakery and she bought the bread but not the cake because she only had enough coins for the bread [1] Margaret went to the bakery and she bought the bread but not the cake because she only had enough coins for the cake continuation: .

Gold: [0] Margaret went to the bakery and she bought the bread but not the cake because she only had enough coins for the bread .

## 48. source_idx=398 (superglue is post-1930 invention)

**Original removed item**

[0] Betty used glue to fix Megan's toy because Betty [1] Betty used glue to fix Megan's toy because Megan continuation: was too young to use superglue.

Gold: [1] Betty used glue to fix Megan's toy because Megan was too young to use superglue.

**Generated replacement**

[0] Betty used thread to fix Megan's dress because Betty [1] Betty used thread to fix Megan's dress because Megan continuation: was too young to use a needle.

Gold: [1] Betty used thread to fix Megan's dress because Megan was too young to use a needle.

## 49. source_idx=403 (post-1930 term 'significant other')

**Original removed item**

[0] At their high school's homecoming dance, Natalie stayed on the floor for the slow dance while Maria got food during it, because Natalie [1] At their high school's homecoming dance, Natalie stayed on the floor for the slow dance while Maria got food during it, because Maria continuation: had broken up with her significant other.

Gold: [1] At their high school's homecoming dance, Natalie stayed on the floor for the slow dance while Maria got food during it, because Maria had broken up with her significant other.

**Generated replacement**

[0] At the harvest festival, Eleanor joined the country dance while Margaret sat by the refreshment table, because Eleanor [1] At the harvest festival, Eleanor joined the country dance while Margaret sat by the refreshment table, because Margaret continuation: had quarreled with her dance partner.

Gold: [1] At the harvest festival, Eleanor joined the country dance while Margaret sat by the refreshment table, because Margaret had quarreled with her dance partner.

## 50. source_idx=404 (post-1930 term 'significant other')

**Original removed item**

[0] At their high school's homecoming dance, Natalie stayed on the floor for the slow dance while Maria got food during it, because Natalie [1] At their high school's homecoming dance, Natalie stayed on the floor for the slow dance while Maria got food during it, because Maria continuation: currently had a significant other.

Gold: [0] At their high school's homecoming dance, Natalie stayed on the floor for the slow dance while Maria got food during it, because Natalie currently had a significant other.

**Generated replacement**

[0] At the market, Eleanor chose the heavy wool coat while Catherine chose the light cotton dress, because Eleanor [1] At the market, Eleanor chose the heavy wool coat while Catherine chose the light cotton dress, because Catherine continuation: lived in a much colder climate.

Gold: [0] At the market, Eleanor chose the heavy wool coat while Catherine chose the light cotton dress, because Eleanor lived in a much colder climate.

## 51. source_idx=433 (internet postdates 1930)

**Original removed item**

[0] Erin was sick of the pests like Amy always cutting out their internet, so Erin [1] Erin was sick of the pests like Amy always cutting out their internet, so Amy continuation: decided to lay low.

Gold: [1] Erin was sick of the pests like Amy always cutting out their internet, so Amy decided to lay low.

**Generated replacement**

[0] Thomas was sick of the pests like Henry always trampling his garden, so Thomas [1] Thomas was sick of the pests like Henry always trampling his garden, so Henry continuation: decided to lay low.

Gold: [1] Thomas was sick of the pests like Henry always trampling his garden, so Henry decided to lay low.

## 52. source_idx=462 (Google is post-1930 technology)

**Original removed item**

[0] So Betty [1] So Cynthia continuation: ignores Google to search for information because Betty trusts in it and Cynthia doesn't.

Gold: [1] So Cynthia ignores Google to search for information because Betty trusts in it and Cynthia doesn't.

**Generated replacement**

[0] So Betty [1] So Cynthia continuation: ignores the encyclopedia to search for information because Betty trusts in it and Cynthia doesn't.

Gold: [1] So Cynthia ignores the encyclopedia to search for information because Betty trusts in it and Cynthia doesn't.

## 53. source_idx=517 (nicotine patch postdates 1930)

**Original removed item**

[0] Samantha wanted to reduce smoking by relying on a new nicotine patch and therapy video, but the patch [1] Samantha wanted to reduce smoking by relying on a new nicotine patch and therapy video, but the video continuation: was boring.

Gold: [1] Samantha wanted to reduce smoking by relying on a new nicotine patch and therapy video, but the video was boring.

**Generated replacement**

[0] Margaret wanted to improve her health by relying on a new herbal tonic and a lecture on hygiene, but the tonic [1] Margaret wanted to improve her health by relying on a new herbal tonic and a lecture on hygiene, but the lecture continuation: was boring.

Gold: [1] Margaret wanted to improve her health by relying on a new herbal tonic and a lecture on hygiene, but the lecture was boring.

## 54. source_idx=518 (nicotine patch postdates 1930)

**Original removed item**

[0] Samantha wanted to reduce smoking by relying on a new nicotine patch and therapy video, but the patch [1] Samantha wanted to reduce smoking by relying on a new nicotine patch and therapy video, but the video continuation: was addictive.

Gold: [0] Samantha wanted to reduce smoking by relying on a new nicotine patch and therapy video, but the patch was addictive.

**Generated replacement**

[0] Margaret wanted to reduce her coffee habit by relying on a strong tea and a pamphlet, but the tea [1] Margaret wanted to reduce her coffee habit by relying on a strong tea and a pamphlet, but the pamphlet continuation: was addictive.

Gold: [0] Margaret wanted to reduce her coffee habit by relying on a strong tea and a pamphlet, but the tea was addictive.

## 55. source_idx=519 (apps are post-1930)

**Original removed item**

[0] Craig had a slower running phone than Logan because Craig [1] Craig had a slower running phone than Logan because Logan continuation: had more apps running on theirs.

Gold: [0] Craig had a slower running phone than Logan because Craig had more apps running on theirs.

**Generated replacement**

[0] Craig had a slower moving wagon than Logan because Craig [1] Craig had a slower moving wagon than Logan because Logan continuation: carried more cargo on theirs.

Gold: [0] Craig had a slower moving wagon than Logan because Craig carried more cargo on theirs.

## 56. source_idx=520 (Modern smartphone and apps concept post-1930)

**Original removed item**

[0] Craig had a faster running phone than Logan because Craig [1] Craig had a faster running phone than Logan because Logan continuation: had more apps running on theirs.

Gold: [1] Craig had a faster running phone than Logan because Logan had more apps running on theirs.

**Generated replacement**

[0] Craig's horse ran faster than Logan's because Craig [1] Craig's horse ran faster than Logan's because Logan continuation: carried heavier saddlebags on theirs.

Gold: [1] Craig's horse ran faster than Logan's because Logan carried heavier saddlebags on theirs.

## 57. source_idx=552 (vaccine-autism link postdates 1930)

**Original removed item**

[0] The children were not vaccinated, which was fine with Betty but annoyed Mary. Betty [1] The children were not vaccinated, which was fine with Betty but annoyed Mary. Mary continuation: knew they didn't make kids autistic.

Gold: [1] The children were not vaccinated, which was fine with Betty but annoyed Mary. Mary knew they didn't make kids autistic.

**Generated replacement**

[0] The meat was not cooked, which was fine with Betty but annoyed Mary. Betty [1] The meat was not cooked, which was fine with Betty but annoyed Mary. Mary continuation: knew it could make the children sick.

Gold: [1] The meat was not cooked, which was fine with Betty but annoyed Mary. Mary knew it could make the children sick.

## 58. source_idx=553 (vaccine-autism link postdates 1930)

**Original removed item**

[0] The children were not vaccinated, which was fine with Betty but annoyed Mary. Betty [1] The children were not vaccinated, which was fine with Betty but annoyed Mary. Mary continuation: believed they made kids autistic.

Gold: [0] The children were not vaccinated, which was fine with Betty but annoyed Mary. Betty believed they made kids autistic.

**Generated replacement**

[0] The children were not given any medicine, which was fine with Betty but annoyed Mary. Betty [1] The children were not given any medicine, which was fine with Betty but annoyed Mary. Mary continuation: believed it was harmful.

Gold: [0] The children were not given any medicine, which was fine with Betty but annoyed Mary. Betty believed it was harmful.

## 59. source_idx=557 (dental implants postdate 1930)

**Original removed item**

[0] Donna needed dentures or implants for her bad teeth. She chose the dentures [1] Donna needed dentures or implants for her bad teeth. She chose the implants continuation: because they are cheaper.

Gold: [0] Donna needed dentures or implants for her bad teeth. She chose the dentures because they are cheaper.

**Generated replacement**

[0] Anna needed a candle or a lantern for her dark room. She chose the candle [1] Anna needed a candle or a lantern for her dark room. She chose the lantern continuation: because it is cheaper.

Gold: [0] Anna needed a candle or a lantern for her dark room. She chose the candle because it is cheaper.

## 60. source_idx=558 (dental implants postdate 1930)

**Original removed item**

[0] Donna needed dentures or implants for her bad teeth. She chose the dentures [1] Donna needed dentures or implants for her bad teeth. She chose the implants continuation: because they are permanent.

Gold: [1] Donna needed dentures or implants for her bad teeth. She chose the implants because they are permanent.

**Generated replacement**

[0] Sarah needed a candle or an oil lamp for reading at night. She chose the candle [1] Sarah needed a candle or an oil lamp for reading at night. She chose the oil lamp continuation: because it burns longer.

Gold: [1] Sarah needed a candle or an oil lamp for reading at night. She chose the oil lamp because it burns longer.

## 61. source_idx=585 (botox therapy postdates 1930)

**Original removed item**

[0] Tom recently was approved for botox therapy.  He had a choice between near the office or near his house and went with his weekday convenience of the office [1] Tom recently was approved for botox therapy.  He had a choice between near the office or near his house and went with his weekday convenience of the house continuation: .

Gold: [0] Tom recently was approved for botox therapy.  He had a choice between near the office or near his house and went with his weekday convenience of the office .

**Generated replacement**

[0] Tom recently scheduled a fitting with his tailor.  He had a choice between near the office or near his house and went with his weekday convenience of the office [1] Tom recently scheduled a fitting with his tailor.  He had a choice between near the office or near his house and went with his weekday convenience of the house continuation: .

Gold: [0] Tom recently scheduled a fitting with his tailor.  He had a choice between near the office or near his house and went with his weekday convenience of the office .

## 62. source_idx=598 (junk food postdates 1930)

**Original removed item**

[0] Brett threw away all the soda and junk food to reduce Leslie's dependence on unhealthy foods because Brett [1] Brett threw away all the soda and junk food to reduce Leslie's dependence on unhealthy foods because Leslie continuation: cares for his health.

Gold: [0] Brett threw away all the soda and junk food to reduce Leslie's dependence on unhealthy foods because Brett cares for his health.

**Generated replacement**

[0] The tutor assigned the student extra reading to improve his Latin because the tutor [1] The tutor assigned the student extra reading to improve his Latin because the student continuation: was preparing for the examination.

Gold: [1] The tutor assigned the student extra reading to improve his Latin because the student was preparing for the examination.

## 63. source_idx=604 (modern term 'flight attendant' post-1930)

**Original removed item**

[0] Elena was an excellent flight attendant when Sarah boarded the plane with a fear of flying because, Elena [1] Elena was an excellent flight attendant when Sarah boarded the plane with a fear of flying because, Sarah continuation: was able to overcome their fears.

Gold: [1] Elena was an excellent flight attendant when Sarah boarded the plane with a fear of flying because, Sarah was able to overcome their fears.

**Generated replacement**

[0] Margaret was a skilled physician when Helen came to her clinic with a terrible fever because, Margaret [1] Margaret was a skilled physician when Helen came to her clinic with a terrible fever because, Helen continuation: was able to recover fully.

Gold: [1] Margaret was a skilled physician when Helen came to her clinic with a terrible fever because, Helen was able to recover fully.

## 64. source_idx=619 (gothic lolita style postdates 1930)

**Original removed item**

[0] The gothic lolita style suited Victoria better than Sarah because Victoria [1] The gothic lolita style suited Victoria better than Sarah because Sarah continuation: looked the worst in frilly dresses.

Gold: [1] The gothic lolita style suited Victoria better than Sarah because Sarah looked the worst in frilly dresses.

**Generated replacement**

[0] The formal uniform suited Edward better than Henry because Edward [1] The formal uniform suited Edward better than Henry because Henry continuation: looked the worst in stiff collars.

Gold: [1] The formal uniform suited Edward better than Henry because Henry looked the worst in stiff collars.

## 65. source_idx=644 (drug detection dogs post-1930)

**Original removed item**

[0] The dog was more suspicious of the locker than of the package because the drugs were in the locker [1] The dog was more suspicious of the locker than of the package because the drugs were in the package continuation: .

Gold: [0] The dog was more suspicious of the locker than of the package because the drugs were in the locker .

**Generated replacement**

[0] The hound was more interested in the chest than in the sack because the meat was in the chest [1] The hound was more interested in the chest than in the sack because the meat was in the sack continuation: .

Gold: [0] The hound was more interested in the chest than in the sack because the meat was in the chest .

## 66. source_idx=662 (computers are post-1930)

**Original removed item**

[0] The library always had more books than computers, most likely because the books [1] The library always had more books than computers, most likely because the computers continuation: are smaller.

Gold: [0] The library always had more books than computers, most likely because the books are smaller.

**Generated replacement**

[0] The library always had more books than globes, most likely because the books [1] The library always had more books than globes, most likely because the globes continuation: are smaller.

Gold: [0] The library always had more books than globes, most likely because the books are smaller.

## 67. source_idx=663 (computers are post-1930)

**Original removed item**

[0] The library always had more books than computers, most likely because the books [1] The library always had more books than computers, most likely because the computers continuation: are bigger.

Gold: [1] The library always had more books than computers, most likely because the computers are bigger.

**Generated replacement**

[0] The shelf always held more pamphlets than atlases, most likely because the pamphlets [1] The shelf always held more pamphlets than atlases, most likely because the atlases continuation: are bigger.

Gold: [1] The shelf always held more pamphlets than atlases, most likely because the atlases are bigger.

## 68. source_idx=696 (RV postdates 1930)

**Original removed item**

[0] Justin bought a new RV but Lawrence liked his old one, so Justin [1] Justin bought a new RV but Lawrence liked his old one, so Lawrence continuation: decided to buy it.

Gold: [1] Justin bought a new RV but Lawrence liked his old one, so Lawrence decided to buy it.

**Generated replacement**

[0] Justin bought a new wagon but Lawrence liked his old one, so Justin [1] Justin bought a new wagon but Lawrence liked his old one, so Lawrence continuation: decided to buy it.

Gold: [1] Justin bought a new wagon but Lawrence liked his old one, so Lawrence decided to buy it.

## 69. source_idx=697 (RV postdates 1930)

**Original removed item**

[0] Justin bought a new RV but Lawrence liked his old one, so Justin [1] Justin bought a new RV but Lawrence liked his old one, so Lawrence continuation: decided to sell it.

Gold: [0] Justin bought a new RV but Lawrence liked his old one, so Justin decided to sell it.

**Generated replacement**

[0] Justin bought a new carriage but Lawrence liked his old one, so Justin [1] Justin bought a new carriage but Lawrence liked his old one, so Lawrence continuation: decided to sell it.

Gold: [0] Justin bought a new carriage but Lawrence liked his old one, so Justin decided to sell it.

## 70. source_idx=712 (computer and tablet post-1930)

**Original removed item**

[0] The computer ran faster than the tablet because the files on the tablet [1] The computer ran faster than the tablet because the files on the computer continuation: were larger.

Gold: [0] The computer ran faster than the tablet because the files on the tablet were larger.

**Generated replacement**

[0] The cart moved slower than the carriage because the load on the cart [1] The cart moved slower than the carriage because the load on the carriage continuation: was heavier.

Gold: [0] The cart moved slower than the carriage because the load on the cart was heavier.

## 71. source_idx=743 (X-rated film rating postdates 1930)

**Original removed item**

[0] Randy was going to see an X-rated film but was stopped on the sidewalk and yelled at by Nick. The anger showed on Randy [1] Randy was going to see an X-rated film but was stopped on the sidewalk and yelled at by Nick. The anger showed on Nick continuation: 's face.

Gold: [1] Randy was going to see an X-rated film but was stopped on the sidewalk and yelled at by Nick. The anger showed on Nick 's face.

**Generated replacement**

[0] Randy was going to see a play but was stopped on the sidewalk and yelled at by Nick. The anger showed on Randy [1] Randy was going to see a play but was stopped on the sidewalk and yelled at by Nick. The anger showed on Nick continuation: 's face.

Gold: [1] Randy was going to see a play but was stopped on the sidewalk and yelled at by Nick. The anger showed on Nick 's face.

## 72. source_idx=744 (X-rated film rating postdates 1930)

**Original removed item**

[0] Randy was going to see an X-rated film but was stopped on the sidewalk and yelled at by Nick. The shame showed on Randy [1] Randy was going to see an X-rated film but was stopped on the sidewalk and yelled at by Nick. The shame showed on Nick continuation: 's face.

Gold: [0] Randy was going to see an X-rated film but was stopped on the sidewalk and yelled at by Nick. The shame showed on Randy 's face.

**Generated replacement**

[0] Randy was sneaking into the tavern but was stopped on the sidewalk and yelled at by Nick. The shame showed on Randy [1] Randy was sneaking into the tavern but was stopped on the sidewalk and yelled at by Nick. The shame showed on Nick continuation: 's face.

Gold: [0] Randy was sneaking into the tavern but was stopped on the sidewalk and yelled at by Nick. The shame showed on Randy 's face.

## 73. source_idx=750 (Frisbee invented after 1930)

**Original removed item**

[0] Donald was able to catch the Frisbee thrown by Eric, then Donald [1] Donald was able to catch the Frisbee thrown by Eric, then Eric continuation: was thrown the Frisbee back.

Gold: [1] Donald was able to catch the Frisbee thrown by Eric, then Eric was thrown the Frisbee back.

**Generated replacement**

[0] Donald was able to catch the ball thrown by Eric, then Donald [1] Donald was able to catch the ball thrown by Eric, then Eric continuation: was thrown the ball back.

Gold: [1] Donald was able to catch the ball thrown by Eric, then Eric was thrown the ball back.

## 74. source_idx=751 (Frisbee invented after 1930)

**Original removed item**

[0] Donald was able to catch the Frisbee thrown by Eric, then Donald [1] Donald was able to catch the Frisbee thrown by Eric, then Eric continuation: threw the Frisbee back.

Gold: [0] Donald was able to catch the Frisbee thrown by Eric, then Donald threw the Frisbee back.

**Generated replacement**

[0] Donald was able to catch the ball thrown by Eric, then Donald [1] Donald was able to catch the ball thrown by Eric, then Eric continuation: threw the ball back.

Gold: [0] Donald was able to catch the ball thrown by Eric, then Donald threw the ball back.

## 75. source_idx=772 (disco party postdates 1930)

**Original removed item**

[0] Kenneth explained to Ryan that he was dressed like this because he was going to a disco party.  Kenneth [1] Kenneth explained to Ryan that he was dressed like this because he was going to a disco party.  Ryan continuation: was excited.

Gold: [0] Kenneth explained to Ryan that he was dressed like this because he was going to a disco party.  Kenneth was excited.

**Generated replacement**

[0] Kenneth explained to Ryan that he was dressed like this because he was going to a masquerade ball.  Kenneth [1] Kenneth explained to Ryan that he was dressed like this because he was going to a masquerade ball.  Ryan continuation: was excited.

Gold: [0] Kenneth explained to Ryan that he was dressed like this because he was going to a masquerade ball.  Kenneth was excited.

## 76. source_idx=775 (email postdates 1930)

**Original removed item**

[0] Paolo tries to remember what he read in the textbook, but all he can think of is the email from his friend because he read the email [1] Paolo tries to remember what he read in the textbook, but all he can think of is the email from his friend because he read the textbook continuation: ages ago.

Gold: [1] Paolo tries to remember what he read in the textbook, but all he can think of is the email from his friend because he read the textbook ages ago.

**Generated replacement**

[0] Paolo tries to remember what he read in the textbook, but all he can think of is the letter from his friend because he read the letter [1] Paolo tries to remember what he read in the textbook, but all he can think of is the letter from his friend because he read the textbook continuation: ages ago.

Gold: [1] Paolo tries to remember what he read in the textbook, but all he can think of is the letter from his friend because he read the textbook ages ago.

## 77. source_idx=779 ('cleavage' sense post-1930)

**Original removed item**

[0] The cleavage had to be hidden for this event's clothing because the cleavage [1] The cleavage had to be hidden for this event's clothing because the clothing continuation: was inappropriate.

Gold: [0] The cleavage had to be hidden for this event's clothing because the cleavage was inappropriate.

**Generated replacement**

[0] The tattoo had to be hidden for this event's uniform because the tattoo [1] The tattoo had to be hidden for this event's uniform because the uniform continuation: was inappropriate.

Gold: [0] The tattoo had to be hidden for this event's uniform because the tattoo was inappropriate.

## 78. source_idx=782 (Cinnamon challenge postdates 1930)

**Original removed item**

[0] Rebecca had a sneezing reflex unlike Monica, so when they took the cinnamon challenge Rebecca [1] Rebecca had a sneezing reflex unlike Monica, so when they took the cinnamon challenge Monica continuation: won.

Gold: [1] Rebecca had a sneezing reflex unlike Monica, so when they took the cinnamon challenge Monica won.

**Generated replacement**

[0] Rebecca had a weak stomach unlike Monica, so when they ate the spoiled meat Rebecca [1] Rebecca had a weak stomach unlike Monica, so when they ate the spoiled meat Monica continuation: became ill.

Gold: [0] Rebecca had a weak stomach unlike Monica, so when they ate the spoiled meat Rebecca became ill.

## 79. source_idx=786 (Computers and peripherals postdate 1930)

**Original removed item**

[0] The intelligence agency ordered new computers for the workers and kept the same peripherals because the computers [1] The intelligence agency ordered new computers for the workers and kept the same peripherals because the peripherals continuation: were at risk.

Gold: [0] The intelligence agency ordered new computers for the workers and kept the same peripherals because the computers were at risk.

**Generated replacement**

[0] The navy ordered new ships for the crew and kept the same anchors because the ships [1] The navy ordered new ships for the crew and kept the same anchors because the anchors continuation: were at risk.

Gold: [0] The navy ordered new ships for the crew and kept the same anchors because the ships were at risk.

## 80. source_idx=794 ('stoner' and 'herb' slang post-1930)

**Original removed item**

[0] Steven was disappointed as Logan asked him if he had any herb.  Steven [1] Steven was disappointed as Logan asked him if he had any herb.  Logan continuation: was a stoner.

Gold: [1] Steven was disappointed as Logan asked him if he had any herb.  Logan was a stoner.

**Generated replacement**

[0] The merchant was annoyed as the beggar asked him if he had any bread.  The merchant [1] The merchant was annoyed as the beggar asked him if he had any bread.  The beggar continuation: was starving.

Gold: [1] The merchant was annoyed as the beggar asked him if he had any bread.  The beggar was starving.

## 81. source_idx=833 (designated driver postdates 1930)

**Original removed item**

[0] Justin went with Donald to the game because Justin [1] Justin went with Donald to the game because Donald continuation: wanted to be the designated driver.

Gold: [0] Justin went with Donald to the game because Justin wanted to be the designated driver.

**Generated replacement**

[0] Justin went with Donald to the fair because Justin [1] Justin went with Donald to the fair because Donald continuation: wanted to drive the wagon.

Gold: [0] Justin went with Donald to the fair because Justin wanted to drive the wagon.

## 82. source_idx=834 (Photoshop software postdates 1930)

**Original removed item**

[0] Mike wanted to make the picture with the Photoshop software instead of  the Paintshop software because the Photoshop software [1] Mike wanted to make the picture with the Photoshop software instead of  the Paintshop software because the Paintshop software continuation: was more reliable.

Gold: [0] Mike wanted to make the picture with the Photoshop software instead of  the Paintshop software because the Photoshop software was more reliable.

**Generated replacement**

[0] Mike wanted to draw the picture with the pencil instead of the crayon because the pencil [1] Mike wanted to draw the picture with the pencil instead of the crayon because the crayon continuation: was more reliable.

Gold: [0] Mike wanted to draw the picture with the pencil instead of the crayon because the pencil was more reliable.

## 83. source_idx=882 (solar panels postdate 1930)

**Original removed item**

[0] Al got solar panels and a small generator installed at his house for electricity as the panels [1] Al got solar panels and a small generator installed at his house for electricity as the generator continuation: would be his main power supply.

Gold: [0] Al got solar panels and a small generator installed at his house for electricity as the panels would be his main power supply.

**Generated replacement**

[0] Al got a windmill and a small hand pump installed at his farm for water as the windmill [1] Al got a windmill and a small hand pump installed at his farm for water as the hand pump continuation: would be his main water supply.

Gold: [0] Al got a windmill and a small hand pump installed at his farm for water as the windmill would be his main water supply.

## 84. source_idx=889 (music videos postdate 1930)

**Original removed item**

[0] Applying to dance in music videos was great for Erin but not Lindsey because Erin [1] Applying to dance in music videos was great for Erin but not Lindsey because Lindsey continuation: was a beginner dancer.

Gold: [1] Applying to dance in music videos was great for Erin but not Lindsey because Lindsey was a beginner dancer.

**Generated replacement**

[0] Applying to dance in the ballet was great for Erin but not Lindsey because Erin [1] Applying to dance in the ballet was great for Erin but not Lindsey because Lindsey continuation: was a beginner dancer.

Gold: [1] Applying to dance in the ballet was great for Erin but not Lindsey because Lindsey was a beginner dancer.

## 85. source_idx=954 (post-1930 Windows software)

**Original removed item**

[0] The Windows software attempted to install the upgrades onto the computer, but the software [1] The Windows software attempted to install the upgrades onto the computer, but the computer continuation: exceeded data capacity.

Gold: [0] The Windows software attempted to install the upgrades onto the computer, but the software exceeded data capacity.

**Generated replacement**

[0] The merchant attempted to load the cargo onto the wagon, but the cargo [1] The merchant attempted to load the cargo onto the wagon, but the wagon continuation: exceeded weight capacity.

Gold: [0] The merchant attempted to load the cargo onto the wagon, but the cargo exceeded weight capacity.

## 86. source_idx=955 (post-1930 computer concept)

**Original removed item**

[0] The Windows software attempted to install the upgrades onto the computer, but the software [1] The Windows software attempted to install the upgrades onto the computer, but the computer continuation: was outdated.

Gold: [1] The Windows software attempted to install the upgrades onto the computer, but the computer was outdated.

**Generated replacement**

[0] The farmer attempted to load the hay onto the wagon, but the wagon [1] The farmer attempted to load the hay onto the wagon, but the hay continuation: was already full.

Gold: [0] The farmer attempted to load the hay onto the wagon, but the wagon was already full.

## 87. source_idx=969 (reality show postdates 1930)

**Original removed item**

[0] Monica chose Kayla as the winning contestant on the reality show because Monica [1] Monica chose Kayla as the winning contestant on the reality show because Kayla continuation: was a contestant on the show.

Gold: [1] Monica chose Kayla as the winning contestant on the reality show because Kayla was a contestant on the show.

**Generated replacement**

[0] The queen chose Alice as the winner of the baking contest because Alice [1] The queen chose Alice as the winner of the baking contest because the queen continuation: was a contestant in the contest.

Gold: [0] The queen chose Alice as the winner of the baking contest because Alice was a contestant in the contest.

## 88. source_idx=971 (UFC octagon postdates 1930)

**Original removed item**

[0] Kenneth worked hard at training martial arts but not Samuel. Kenneth [1] Kenneth worked hard at training martial arts but not Samuel. Samuel continuation: couldn't made their dream come true of fighting in the UFC octagon.

Gold: [1] Kenneth worked hard at training martial arts but not Samuel. Samuel couldn't made their dream come true of fighting in the UFC octagon.

**Generated replacement**

[0] Henry worked hard at training for the footrace but not William. Henry [1] Henry worked hard at training for the footrace but not William. William continuation: couldn't make his dream come true of competing in the Olympic games.

Gold: [1] Henry worked hard at training for the footrace but not William. William couldn't make his dream come true of competing in the Olympic games.

## 89. source_idx=985 (insurance plan postdates 1930)

**Original removed item**

[0] The doctor treated Natalie, but refused to see Tanya, because Natalie [1] The doctor treated Natalie, but refused to see Tanya, because Tanya continuation: has an incredible insurance plan.

Gold: [0] The doctor treated Natalie, but refused to see Tanya, because Natalie has an incredible insurance plan.

**Generated replacement**

[0] The innkeeper welcomed the merchant, but turned away the beggar, because the merchant [1] The innkeeper welcomed the merchant, but turned away the beggar, because the beggar continuation: had plenty of gold coins.

Gold: [0] The innkeeper welcomed the merchant, but turned away the beggar, because the merchant had plenty of gold coins.

## 90. source_idx=989 (name Kayla is post-1930)

**Original removed item**

[0] Amy's being taught how to pay it forward by Kayla, so Amy [1] Amy's being taught how to pay it forward by Kayla, so Kayla continuation: is likely the younger person.

Gold: [0] Amy's being taught how to pay it forward by Kayla, so Amy is likely the younger person.

**Generated replacement**

[0] Amy's being taught how to play chess by Kayla, so Amy [1] Amy's being taught how to play chess by Kayla, so Kayla continuation: is likely the younger person.

Gold: [0] Amy's being taught how to play chess by Kayla, so Amy is likely the younger person.

## 91. source_idx=999 (microchip is post-1930 invention)

**Original removed item**

[0] Carrie tried to convince Cynthia that the cat needed a microchip because Carrie [1] Carrie tried to convince Cynthia that the cat needed a microchip because Cynthia continuation: was concerned about the cat getting lost.

Gold: [0] Carrie tried to convince Cynthia that the cat needed a microchip because Carrie was concerned about the cat getting lost.

**Generated replacement**

[0] Carrie tried to convince Cynthia that the cat needed a bell on its collar because Carrie [1] Carrie tried to convince Cynthia that the cat needed a bell on its collar because Cynthia continuation: was concerned about the cat getting lost.

Gold: [0] Carrie tried to convince Cynthia that the cat needed a bell on its collar because Carrie was concerned about the cat getting lost.

## 92. source_idx=1017 (belly piercing postdates 1930)

**Original removed item**

[0] The teenager chose a jeweled pin for her belly piercing, but the piercing [1] The teenager chose a jeweled pin for her belly piercing, but the pin continuation: was too tiny.

Gold: [0] The teenager chose a jeweled pin for her belly piercing, but the piercing was too tiny.

**Generated replacement**

[0] The knight chose a heavy lance for the tournament, but the lance [1] The knight chose a heavy lance for the tournament, but the tournament continuation: was too long.

Gold: [0] The knight chose a heavy lance for the tournament, but the lance was too long.

## 93. source_idx=1018 (belly piercing postdates 1930)

**Original removed item**

[0] The teenager chose a jeweled pin for her belly piercing, but the piercing [1] The teenager chose a jeweled pin for her belly piercing, but the pin continuation: was too huge.

Gold: [1] The teenager chose a jeweled pin for her belly piercing, but the pin was too huge.

**Generated replacement**

[0] The prisoner chose a file for the iron bar, but the file [1] The prisoner chose a file for the iron bar, but the bar continuation: was too dull.

Gold: [0] The prisoner chose a file for the iron bar, but the file was too dull.

## 94. source_idx=1031 (laptop and modern phone post-1930)

**Original removed item**

[0] The battery of the the phone died faster than the laptop battery, because the phone [1] The battery of the the phone died faster than the laptop battery, because the laptop continuation: was always off.

Gold: [1] The battery of the the phone died faster than the laptop battery, because the laptop was always off.

**Generated replacement**

[0] The iron exposed to rain rusted faster than the iron kept indoors, because the outdoor iron [1] The iron exposed to rain rusted faster than the iron kept indoors, because the indoor iron continuation: was sheltered from moisture.

Gold: [1] The iron exposed to rain rusted faster than the iron kept indoors, because the indoor iron was sheltered from moisture.

## 95. source_idx=1032 (laptop and modern phone post-1930)

**Original removed item**

[0] The battery of the the phone died faster than the laptop battery, because the phone [1] The battery of the the phone died faster than the laptop battery, because the laptop continuation: was always on.

Gold: [0] The battery of the the phone died faster than the laptop battery, because the phone was always on.

**Generated replacement**

[0] The oil in the lamp by the gate burned out faster than the oil in the lamp in the parlor, because the lamp by the gate [1] The oil in the lamp by the gate burned out faster than the oil in the lamp in the parlor, because the lamp in the parlor continuation: was lit every night.

Gold: [0] The oil in the lamp by the gate burned out faster than the oil in the lamp in the parlor, because the lamp by the gate was lit every night.

## 96. source_idx=1034 (hairspray postdates 1930)

**Original removed item**

[0] I wanted to use pomade on my hair instead of hairspray but it was old so the pomade [1] I wanted to use pomade on my hair instead of hairspray but it was old so the hairspray continuation: was unusable.

Gold: [0] I wanted to use pomade on my hair instead of hairspray but it was old so the pomade was unusable.

**Generated replacement**

[0] I wanted to write with ink instead of a pencil but it had dried out so the ink [1] I wanted to write with ink instead of a pencil but it had dried out so the pencil continuation: was unusable.

Gold: [0] I wanted to write with ink instead of a pencil but it had dried out so the ink was unusable.

## 97. source_idx=1038 (sunscreen postdates 1930)

**Original removed item**

[0] Kayla always wears sunscreen outdoors but Natalie doesn't because Kayla [1] Kayla always wears sunscreen outdoors but Natalie doesn't because Natalie continuation: isn't concerned about getting neck wrinkles.

Gold: [1] Kayla always wears sunscreen outdoors but Natalie doesn't because Natalie isn't concerned about getting neck wrinkles.

**Generated replacement**

[0] Marcus always carries an umbrella outdoors but Philip doesn't because Marcus [1] Marcus always carries an umbrella outdoors but Philip doesn't because Philip continuation: doesn't mind getting soaked in the rain.

Gold: [1] Marcus always carries an umbrella outdoors but Philip doesn't because Philip doesn't mind getting soaked in the rain.

## 98. source_idx=1066 (snowboard/biathlon are modern)

**Original removed item**

[0] Logan preferred to snowboard while Kyle wanted to do biathlon so Logan [1] Logan preferred to snowboard while Kyle wanted to do biathlon so Kyle continuation: went up the hill.

Gold: [0] Logan preferred to snowboard while Kyle wanted to do biathlon so Logan went up the hill.

**Generated replacement**

[0] Logan preferred to ski while Kyle wanted to skate so Logan [1] Logan preferred to ski while Kyle wanted to skate so Kyle continuation: went up the hill.

Gold: [0] Logan preferred to ski while Kyle wanted to skate so Logan went up the hill.

## 99. source_idx=1072 (velcro (invented 1941) is post-1930)

**Original removed item**

[0] The dress could use either velcro or a zipper to close, the velcro [1] The dress could use either velcro or a zipper to close, the zipper continuation: would last longer.

Gold: [1] The dress could use either velcro or a zipper to close, the zipper would last longer.

**Generated replacement**

[0] The book could use either thread or glue to bind, the thread [1] The book could use either thread or glue to bind, the glue continuation: would last longer.

Gold: [0] The book could use either thread or glue to bind, the thread would last longer.

## 100. source_idx=1154 (telemarketing postdates 1930)

**Original removed item**

[0] Natalie is extremely shy, but Lindsey is good at talking to strangers, which makes Natalie [1] Natalie is extremely shy, but Lindsey is good at talking to strangers, which makes Lindsey continuation: worse at telemarketing.

Gold: [0] Natalie is extremely shy, but Lindsey is good at talking to strangers, which makes Natalie worse at telemarketing.

**Generated replacement**

[0] Martha is extremely shy, but Sarah is good at talking to strangers, which makes Martha [1] Martha is extremely shy, but Sarah is good at talking to strangers, which makes Sarah continuation: worse at selling goods in the marketplace.

Gold: [0] Martha is extremely shy, but Sarah is good at talking to strangers, which makes Martha worse at selling goods in the marketplace.

## 101. source_idx=1155 (modern phone systems)

**Original removed item**

[0] Benjamin thought Android was the superior phone system but Ian thought IOS was better. Benjamin [1] Benjamin thought Android was the superior phone system but Ian thought IOS was better. Ian continuation: bought a new Note 9 from Verizon.

Gold: [0] Benjamin thought Android was the superior phone system but Ian thought IOS was better. Benjamin bought a new Note 9 from Verizon.

**Generated replacement**

[0] Benjamin thought the railway was the superior mode of travel but Ian thought the stagecoach was better. Benjamin [1] Benjamin thought the railway was the superior mode of travel but Ian thought the stagecoach was better. Ian continuation: bought a ticket on the new express train.

Gold: [0] Benjamin thought the railway was the superior mode of travel but Ian thought the stagecoach was better. Benjamin bought a ticket on the new express train.

## 102. source_idx=1156 (iOS, iPhone post-1930)

**Original removed item**

[0] Benjamin thought Android was the superior phone system but Ian thought IOS was better. Benjamin [1] Benjamin thought Android was the superior phone system but Ian thought IOS was better. Ian continuation: bought a new iPhone 9 from Verizon.

Gold: [1] Benjamin thought Android was the superior phone system but Ian thought IOS was better. Ian bought a new iPhone 9 from Verizon.

**Generated replacement**

[0] Thomas thought steam locomotives were the superior mode of transport but James thought horse-drawn carriages were better. Thomas [1] Thomas thought steam locomotives were the superior mode of transport but James thought horse-drawn carriages were better. James continuation: bought a new team of horses from the livery stable.

Gold: [1] Thomas thought steam locomotives were the superior mode of transport but James thought horse-drawn carriages were better. James bought a new team of horses from the livery stable.

## 103. source_idx=1163 (Twitter postdates 1930)

**Original removed item**

[0] Elena is concerned that Megan might have a Twitter addiction, but Elena [1] Elena is concerned that Megan might have a Twitter addiction, but Megan continuation: is probably worrying about nothing.

Gold: [0] Elena is concerned that Megan might have a Twitter addiction, but Elena is probably worrying about nothing.

**Generated replacement**

[0] Elena is concerned that Megan might have a gambling problem, but Elena [1] Elena is concerned that Megan might have a gambling problem, but Megan continuation: is probably worrying about nothing.

Gold: [0] Elena is concerned that Megan might have a gambling problem, but Elena is probably worrying about nothing.

## 104. source_idx=1167 (FDA approval post-1930)

**Original removed item**

[0] The pharmacy offered a product that could cure any disease, made of a new chemical and container, but the chemical [1] The pharmacy offered a product that could cure any disease, made of a new chemical and container, but the container continuation: was not FDA approved.

Gold: [0] The pharmacy offered a product that could cure any disease, made of a new chemical and container, but the chemical was not FDA approved.

**Generated replacement**

[0] The vintner poured wine from a bottle sealed with cork and glass, but the cork [1] The vintner poured wine from a bottle sealed with cork and glass, but the glass continuation: had dried out and let air into the wine.

Gold: [0] The vintner poured wine from a bottle sealed with cork and glass, but the cork had dried out and let air into the wine.

## 105. source_idx=1186 (post-1930 term 'upcharge')

**Original removed item**

[0] Ryan ordered the salad with added avocado, but Randy passed, because Ryan [1] Ryan ordered the salad with added avocado, but Randy passed, because Randy continuation: wasn't ok with the $3 upcharge.

Gold: [1] Ryan ordered the salad with added avocado, but Randy passed, because Randy wasn't ok with the $3 upcharge.

**Generated replacement**

[0] Thomas ordered the roast beef with extra gravy, but William passed, because Thomas [1] Thomas ordered the roast beef with extra gravy, but William passed, because William continuation: wasn't willing to pay the extra shilling.

Gold: [1] Thomas ordered the roast beef with extra gravy, but William passed, because William wasn't willing to pay the extra shilling.

## 106. source_idx=1187 (post-1930 term 'upcharge')

**Original removed item**

[0] Ryan ordered the salad with added avocado, but Randy passed, because Ryan [1] Ryan ordered the salad with added avocado, but Randy passed, because Randy continuation: was ok with the $3 upcharge.

Gold: [0] Ryan ordered the salad with added avocado, but Randy passed, because Ryan was ok with the $3 upcharge.

**Generated replacement**

[0] Thomas ordered the pie with extra currants, but William passed, because Thomas [1] Thomas ordered the pie with extra currants, but William passed, because William continuation: was willing to pay the additional penny.

Gold: [0] Thomas ordered the pie with extra currants, but William passed, because Thomas was willing to pay the additional penny.

## 107. source_idx=1207 (acrylic paint invented after 1930)

**Original removed item**

[0] Ann liked using oil paint rather than acrylic on canvas because acrylic [1] Ann liked using oil paint rather than acrylic on canvas because oil continuation: had a shortened working time.

Gold: [0] Ann liked using oil paint rather than acrylic on canvas because acrylic had a shortened working time.

**Generated replacement**

[0] Ann liked using oil paint rather than watercolor on canvas because watercolor [1] Ann liked using oil paint rather than watercolor on canvas because oil continuation: had a shortened working time.

Gold: [0] Ann liked using oil paint rather than watercolor on canvas because watercolor had a shortened working time.

## 108. source_idx=1224 (conditioner postdates 1930)

**Original removed item**

[0] Sandra tried out a new conditioner for her hair that makes it curly, but was upset with the results because the conditioner [1] Sandra tried out a new conditioner for her hair that makes it curly, but was upset with the results because the hair continuation: was too straight.

Gold: [1] Sandra tried out a new conditioner for her hair that makes it curly, but was upset with the results because the hair was too straight.

**Generated replacement**

[0] Margaret tried a new salve for her rash that makes it smooth, but was disappointed with the results because the salve [1] Margaret tried a new salve for her rash that makes it smooth, but was disappointed with the results because the rash continuation: was still rough.

Gold: [1] Margaret tried a new salve for her rash that makes it smooth, but was disappointed with the results because the rash was still rough.

## 109. source_idx=1225 (conditioner postdates 1930)

**Original removed item**

[0] Sandra tried out a new conditioner for her hair that makes it curly, but was upset with the results because the conditioner [1] Sandra tried out a new conditioner for her hair that makes it curly, but was upset with the results because the hair continuation: was too mild.

Gold: [0] Sandra tried out a new conditioner for her hair that makes it curly, but was upset with the results because the conditioner was too mild.

**Generated replacement**

[0] Margaret tried a new soap for her skin that makes it soft, but was upset with the results because the soap [1] Margaret tried a new soap for her skin that makes it soft, but was upset with the results because the skin continuation: was too mild.

Gold: [0] Margaret tried a new soap for her skin that makes it soft, but was upset with the results because the soap was too mild.

## 110. source_idx=1235 (post-1930 addiction intervention concept)

**Original removed item**

[0] Monica suspected that Rebecca had become an alcoholic, but Monica [1] Monica suspected that Rebecca had become an alcoholic, but Rebecca continuation: predicted an intervention to address the problem.

Gold: [1] Monica suspected that Rebecca had become an alcoholic, but Rebecca predicted an intervention to address the problem.

**Generated replacement**

[0] Catherine suspected that Charlotte had fallen ill with a fever, but Catherine [1] Catherine suspected that Charlotte had fallen ill with a fever, but Charlotte continuation: foresaw that the family would summon a physician.

Gold: [1] Catherine suspected that Charlotte had fallen ill with a fever, but Charlotte foresaw that the family would summon a physician.

## 111. source_idx=1236 (skateboard invented post-1930)

**Original removed item**

[0] The skateboard got broken under the weight of the fat boy and his luggage. The skateboard [1] The skateboard got broken under the weight of the fat boy and his luggage. The weight continuation: is light.

Gold: [0] The skateboard got broken under the weight of the fat boy and his luggage. The skateboard is light.

**Generated replacement**

[0] The old rope snapped under the strain of the heavy cargo. The rope [1] The old rope snapped under the strain of the heavy cargo. The strain continuation: was frayed and worn.

Gold: [0] The old rope snapped under the strain of the heavy cargo. The rope was frayed and worn.

## 112. source_idx=1261 (modern term 'staycation')

**Original removed item**

[0] Angela was a homebody while Amy loved to travel the world whenever they could. Angela [1] Angela was a homebody while Amy loved to travel the world whenever they could. Amy continuation: took a staycation at home over the summer.

Gold: [0] Angela was a homebody while Amy loved to travel the world whenever they could. Angela took a staycation at home over the summer.

**Generated replacement**

[0] Marcus preferred quiet evenings by the hearth while Lucius loved to wander the city markets whenever he could. Marcus [1] Marcus preferred quiet evenings by the hearth while Lucius loved to wander the city markets whenever he could. Lucius continuation: stayed indoors all winter tending the fire.

Gold: [0] Marcus preferred quiet evenings by the hearth while Lucius loved to wander the city markets whenever he could. Marcus stayed indoors all winter tending the fire.
