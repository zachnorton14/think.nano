# Backfill review: `commonsense_qa`

Mode: preview
Items: 118

## Benchmark context

- Category: commonsense reasoning
- Task type: multiple choice
- Few-shot examples: 10
- Random baseline: 20
- Description: Commonsense QA consists of 1,221 four-choice multiple choice questions that rely on very basic commonsense reasoning about everyday items.

## 1. source_idx=19 (glue sticks postdate 1930)

**Original removed item**

Question: Where do adults use glue sticks? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where do adults use fountain pens? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 2. source_idx=25 (contains post-1930 term 'photo copy')

**Original removed item**

Question: When wildlife reproduce we often refer to what comes out as what? Choices: A. have children B. photo copy C. offspring D. accidently got pregnant somehow Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: When wildlife reproduce we often refer to what comes out as what? Choices: A. have children B. replicas C. offspring D. accidently got pregnant somehow Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 3. source_idx=26 (contains post-1930 invention 'freezer')

**Original removed item**

Question: The weasel was becoming a problem, it kept getting into the chicken eggs kept in the what? Choices: A. forrest B. barn C. out of doors D. freezer Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: The weasel was becoming a problem, it kept getting into the chicken eggs kept in the what? Choices: A. forest B. barn C. out of doors D. pantry Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 4. source_idx=31 (refers to 1950s, post-1930 decade)

**Original removed item**

Question: James wanted to find an old underground map from the 50s.  Where might he look for one? Choices: A. library B. county engineer's office C. super market D. home Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: James wanted to find an old map of the city from the 1850s.  Where might he look for one? Choices: A. library B. county engineer's office C. super market D. home Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 5. source_idx=34 (senior center is post-1930 institution)

**Original removed item**

Question: She was always helping at the senior center, it brought her what? Choices: A. satisfaction B. feel better C. pay D. happiness Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: She was always helping at the orphanage, it brought her what? Choices: A. satisfaction B. fatigue C. pay D. boredom Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 6. source_idx=38 (whirlpool bath invented post-1930)

**Original removed item**

Question: A human wants to submerge himself in water, what should he use? Choices: A. whirlpool bath B. cup C. soft drink D. puddle Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: A human wants to submerge himself in water, what should he use? Choices: A. bathtub B. cup C. puddle D. drinking fountain Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 7. source_idx=42 (online is post-1930)

**Original removed item**

Question: He needed more information to fix it, so he consulted the what? Choices: A. chickens B. newspaper C. online D. manual Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: He needed more information to fix it, so he consulted the what? Choices: A. chickens B. newspaper C. dictionary D. manual Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 8. source_idx=61 (computer user post-1930 concept)

**Original removed item**

Question: Where would a computer user be using their own computer? Choices: A. hell B. indoors C. internet cafe D. house Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: Where would a telephone user be using their own telephone? Choices: A. hell B. indoors C. public booth D. house Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 9. source_idx=72 (Disneyland postdates 1930)

**Original removed item**

Question: The kids didn't clean up after they had done what? Choices: A. play games B. disneyland C. play with toys D. talking Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: The kids didn't clean up after they had done what? Choices: A. play games B. go to the park C. play with toys D. talking Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 10. source_idx=89 (modern term 'texting' post-1930)

**Original removed item**

Question: Friday was James's 5th Anniversary.  They planned on going to bed early so that they could spend a long time doing what? Choices: A. rest B. insomnia C. making love D. texting Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Friday was James's 5th Anniversary.  They planned on going to bed early so that they could spend a long time doing what? Choices: A. rest B. insomnia C. making love D. reading Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 11. source_idx=103 (computers postdate 1930)

**Original removed item**

Question: An underrated thing about computers is how they manage workflow, at one time it was a big deal when they could first do what? Choices: A. share files B. turn on C. cost money D. multitask Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: An underrated thing about clocks is how they manage time, at one time it was a big deal when they could first do what? Choices: A. fit in a pocket B. make noise C. use gears D. cost money Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 12. source_idx=120 (Falcons and Jets postdate 1930)

**Original removed item**

Question: John and James are idiots. They bought two tickets to the Falcons vs the Jets even though neither wanted to see the what? Choices: A. internet cafe B. sporting event C. obesity D. hockey game Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: John and James are idiots. They bought two tickets to the Giants vs the Cubs even though neither wanted to see the what? Choices: A. theater play B. sporting event C. obesity D. chess match Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 13. source_idx=124 (Roswell incident postdates 1930)

**Original removed item**

Question: From where do aliens arrive? Choices: A. outer space B. roswell C. universe D. mars Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: From where does rain come? Choices: A. clouds B. rivers C. trees D. mountains Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 14. source_idx=144 (computer program postdates 1930)

**Original removed item**

Question: James thought of criminal justice like a computer program.  It need to work right.   What ideas might James not like? Choices: A. process information B. power down C. control model D. reason exists Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: James thought of criminal justice like a clock.  It needs to run smoothly.  What ideas might James not like? Choices: A. regular timing B. winding the spring C. random errors D. proper gears Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 15. source_idx=145 (ATM/bank machine postdates 1930)

**Original removed item**

Question: With the card slot lit up he knew how to get started finding his balance with what? Choices: A. slot machine B. bank machine C. telephone D. automated teller Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: With the dial set he knew how to get started finding his direction with what? Choices: A. compass B. telescope C. barometer D. hourglass Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 16. source_idx=153 (computer programming postdates 1930)

**Original removed item**

Question: In order to learn to program from another person you can do what? Choices: A. have a friend B. knowledge C. take class D. have computer Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: In order to learn to paint from another person you can do what? Choices: A. have a friend B. knowledge C. take class D. have paints Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 17. source_idx=156 (television cartoons postdate 1930)

**Original removed item**

Question: The man was going fishing instead of work, what is he seeking? Choices: A. food B. relaxation C. missing morning cartoons D. boredom Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: The man was going fishing instead of work, what is he seeking? Choices: A. food B. relaxation C. missing the morning paper D. boredom Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 18. source_idx=172 (supermarket is post-1930)

**Original removed item**

Question: A supermarket is uncommon in what type of collection of shops? Choices: A. strip mall B. shoppingcentre C. boutique D. vermont Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: A large bakery is uncommon in what type of collection of shops? Choices: A. market square B. bazaar C. apothecary D. arcade Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 19. source_idx=191 (computer as modern device postdates 1930)

**Original removed item**

Question: The computer was difficult for he to understand at the store, so what did she sign up for to learn more? Choices: A. classroom B. school C. apartment D. demonstration Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: The sewing machine was difficult for he to understand at the store, so what did she sign up for to learn more? Choices: A. classroom B. school C. apartment D. demonstration Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 20. source_idx=199 (TV show postdates 1930)

**Original removed item**

Question: The gimmicky low brow TV show was about animals when they what? Choices: A. sick B. males C. bite D. attack Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: The sensational dime novel about wild beasts was about animals when they what? Choices: A. sick B. males C. bite D. attack Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 21. source_idx=205 (Ray Charles is post-1930)

**Original removed item**

Question: Who might wear dark glasses indoors? Choices: A. blind person B. movie studio C. ray charles D. glove compartment Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: Who might wear dark glasses indoors? Choices: A. blind person B. movie studio C. Homer D. glove compartment Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 22. source_idx=215 (Skateboard is post-1930 invention)

**Original removed item**

Question: What to kids do for boredom on a ramp? Choices: A. watch film B. hang out at bar C. go skiing D. skateboard Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: What do kids do for boredom on a ramp? Choices: A. read a book B. slide down C. play chess D. cook dinner Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 23. source_idx=244 (Women wearing pants acceptable after 1930)

**Original removed item**

Question: Women used to be expected to wear a dress but it's now acceptable for them to wear what? Choices: A. man suit B. pants C. action D. long skirt Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: In polite society, a man is expected to remove his hat indoors, but it is acceptable for him to keep it on where? Choices: A. at the dinner table B. in church C. outdoors D. in a parlor Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 24. source_idx=251 (skateboard postdates 1930)

**Original removed item**

Question: People do many things to alleviate boredom.  If you can't get out of the house you might decide to do what? Choices: A. skateboard B. meet interesting people C. listen to music D. go to a concert Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: People do many things to alleviate boredom.  If you can't get out of the house you might decide to do what? Choices: A. play tennis B. visit friends C. listen to music D. attend a play Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 25. source_idx=255 (multivitamin postdates 1930)

**Original removed item**

Question: Minerals can be obtained in what way for a person who avoids leafy greens? Choices: A. multivitamin B. michigan C. earth D. ore Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: A person who avoids eating meat can obtain protein from what source? Choices: A. beans B. water C. salt D. sugar Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 26. source_idx=260 (Disneyland (1955) postdates 1930)

**Original removed item**

Question: The traveling business man was glad his credit card had perks, it offset the high prices for travel from a what? Choices: A. car B. theatre C. airport D. disneyland Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: The traveling merchant was glad his railway pass had perks, it offset the high prices for travel from a what? Choices: A. cart B. theatre C. station D. fairground Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 27. source_idx=272 (printer and queue are post-1930)

**Original removed item**

Question: Printing on a printer can get expensive because it does what? Choices: A. explode B. use paper C. queue D. noise Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: Burning an oil lamp can get expensive because it does what? Choices: A. explode B. use oil C. glow D. flicker Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 28. source_idx=287 (post-1930 year [2000])

**Original removed item**

Question: John had a massive debt to 50 million dollars.  Compared to that, Leo's 2000 dollar debt seemed what? Choices: A. dwarf B. inconsequential C. insubstantial D. tiny Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: A king's treasury held fifty thousand gold coins. Compared to that, a peasant's two coins seemed what? Choices: A. massive B. equal C. insubstantial D. heavier Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 29. source_idx=293 (sharknado is post-1930 pop culture)

**Original removed item**

Question: During a shark filled tornado where should you not be? Choices: A. marine museum B. noodle house C. bad movie D. outside Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: During a severe lightning storm where should you not shelter? Choices: A. inside a house B. under a tall tree C. inside a barn D. in a carriage Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 30. source_idx=301 (Donald (Trump/Rumsfeld) post-1930)

**Original removed item**

Question: Donald is a prominent figure for the federal government, so in what city does he likely spend a lot of time? Choices: A. everything B. tourist sites C. canada D. washington d.c Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: The Pope is a prominent figure for the Catholic Church, so in what city does he likely spend a lot of time? Choices: A. everything B. tourist sites C. france D. rome Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 31. source_idx=304 (Gap brand (1969) post-1930)

**Original removed item**

Question: Where can you buy jeans at one of may indoor merchants? Choices: A. gap B. shopping mall C. laundromat D. bathroom Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: Where can you buy a wool coat from one of many indoor merchants? Choices: A. tailor's shop B. market hall C. stable D. kitchen Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 32. source_idx=308 (Kramer (Seinfeld) post-1930)

**Original removed item**

Question: Kramer wrote a self-referential book.  What might that book be about? Choices: A. counter B. coffee table C. backpack D. bedside table Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: A writer penned a self-referential pocket book.  What might that book be about? Choices: A. pockets B. coats C. hats D. shoes Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 33. source_idx=325 (nuclear weapons post-1930)

**Original removed item**

Question: WHat leads to an early death? Choices: A. poisonous gas B. homicide C. nuclear weapons D. cyanide Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: WHat leads to an early death? Choices: A. poisonous gas B. homicide C. old age D. cyanide Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 34. source_idx=342 (computers postdate 1930)

**Original removed item**

Question: Pens, computers, text books and paper clips can all be found where? Choices: A. desktop B. university C. table D. work Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: Pens, inkwells, text books and paper clips can all be found where? Choices: A. desktop B. university C. table D. work Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 35. source_idx=362 (Batman postdates 1930)

**Original removed item**

Question: Batman bought beer.  There were no bottles available.  He had to settle for what?. Choices: A. soccer game B. keg C. can D. refrigerator Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: A sailor bought beer.  There were no bottles available.  He had to settle for what?. Choices: A. soccer game B. keg C. can D. refrigerator Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 36. source_idx=417 (Empire State Building postdates 1930)

**Original removed item**

Question: Where is the large area location of the empire state building? Choices: A. manhattan B. the city C. fifth avenue D. new york city Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: Where is the large area location of the Eiffel Tower? Choices: A. champ de mars B. the city C. seventh arrondissement D. paris Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 37. source_idx=426 (Mall is a post-1930 concept)

**Original removed item**

Question: Where would you go if you want to buy some clothes? Choices: A. mall B. grocery store C. shop D. supermarket Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: Where would you go if you want to buy a loaf of bread? Choices: A. bakery B. hardware store C. bookshop D. pharmacy Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 38. source_idx=431 (post-1930 actors John Candy and Dan Aykroyd)

**Original removed item**

Question: While John Candy and Dan Aykroyd didn't run into a gazelle, you'd have to go where to see one? Choices: A. eastern hemisphere B. open plain C. television program D. great outdoors Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: While Robin Hood and Little John didn't run into a deer, you'd have to go where to see one? Choices: A. eastern hemisphere B. open plain C. traveling circus D. great outdoors Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 39. source_idx=450 (freeway post-1930 concept)

**Original removed item**

Question: Where do cars usually travel at very high speeds? Choices: A. freeway B. road C. race track D. parking lot Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where do automobiles usually travel at very high speeds? Choices: A. race track B. city street C. parking lot D. driveway Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 40. source_idx=454 (office park is post-1930 concept)

**Original removed item**

Question: If somebody is working at a reception desk, they are located at the front entrance of the what? Choices: A. motel B. hostel C. building D. office park Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: If somebody is working at a reception desk, they are located at the front entrance of the what? Choices: A. inn B. shop C. building D. factory Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 41. source_idx=475 (Harry Potter is post-1930 creative work)

**Original removed item**

Question: According to what book did an apple tree lead to the downfall of man? Choices: A. bible B. harry potter C. new york D. woods Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: According to what book did an apple tree lead to the downfall of man? Choices: A. bible B. odyssey C. new york D. woods Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 42. source_idx=482 (post-1930 phones and internet)

**Original removed item**

Question: Where do most people turn to get information on their phones? Choices: A. book B. online C. google D. manual Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where do most people turn to get information on a word they do not understand? Choices: A. dictionary B. newspaper C. cookbook D. atlas Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 43. source_idx=504 (modern term 'tupperware' post-1930)

**Original removed item**

Question: how can i store cooked steak? Choices: A. oven B. freezer C. tupperware D. grill Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: how can i store cooked steak? Choices: A. oven B. freezer C. skillet D. grill Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 44. source_idx=514 (PWR (nuclear reactor) postdates 1930)

**Original removed item**

Question: Where is the control room that controls a PWR located? Choices: A. building B. window C. prison D. nuclear power plant Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: Where is the switchboard that connects a town's telephone calls located? Choices: A. post office B. telephone exchange C. telegraph office D. town hall Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 45. source_idx=522 (video game postdates 1930)

**Original removed item**

Question: Where could there be a battle that involves words? Choices: A. court room B. video game C. iraq D. church Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: Where could there be a battle that involves words? Choices: A. court room B. kitchen C. stable D. quarry Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 46. source_idx=530 (fast food restaurant post-1930)

**Original removed item**

Question: Where is a good place to put a hamburger? Choices: A. resturant B. fast food restaurant C. mouth D. pizza Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where is a good place to put a slice of bread? Choices: A. bakery B. kitchen C. mouth D. cheese Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 47. source_idx=532 (World War II (post-1930))

**Original removed item**

Question: A story about World War II would be set when? Choices: A. book or magazine B. newspaper C. past D. future Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: A story about the American Civil War would be set when? Choices: A. book or magazine B. newspaper C. past D. future Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 48. source_idx=541 (big box retailer is post-1930 concept)

**Original removed item**

Question: Where is a great place to buy fresh fruit? Choices: A. san francisco B. big box retailer C. tree D. market Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: Where is a great place to buy fresh fruit? Choices: A. san francisco B. tavern C. tree D. market Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 49. source_idx=564 (fast food restaurants postdate 1930)

**Original removed item**

Question: In what country are the most fast food restaurants? Choices: A. blocks of flats B. center of town C. america D. big cities Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: In what country is the Taj Mahal located? Choices: A. a marble tomb B. the city of Agra C. india D. the banks of a river Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 50. source_idx=568 (networking concept postdates 1930)

**Original removed item**

Question: What do people do when networking? Choices: A. build trust B. ignore people C. believe in god D. jump to conclusions Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: What do people do when they are thirsty? Choices: A. drink water B. go to sleep C. read a book D. plant a tree Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 51. source_idx=574 (shrink ray is post-1930 invention)

**Original removed item**

Question: The person tried to reduce his weight with a shrink ray, but he got it backwards and only did what? Choices: A. grow B. gain weight C. make larger D. get bigger Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: The person tried to use a magnifying glass to make the letters smaller, but he got it backwards and only did what? Choices: A. shrink the letters B. blur the letters C. make the letters larger D. darken the letters Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 52. source_idx=580 (internet is post-1930 technology)

**Original removed item**

Question: Where is known to be a wealth of information? Choices: A. internet B. meeting C. library D. book Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where is known to be a wealth of information? Choices: A. conversation B. meeting C. library D. book Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 53. source_idx=611 (X-ray luggage screening post-1930)

**Original removed item**

Question: Where are you if your bieifcase is going through an x-ray machine? Choices: A. luggage store B. courtroom C. airport D. hand Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where are you if you are sitting in a pew listening to a sermon? Choices: A. theater B. church C. classroom D. courtroom Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 54. source_idx=616 (Corn mazes postdate 1930)

**Original removed item**

Question: What does a farmer need to do to make  a maze on his farm in the fall? Choices: A. plant seeds B. garden C. grow corn D. produce food Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: What does a gardener need to do to make a maze in a grand garden? Choices: A. plant seeds B. lay stones C. grow hedges D. spread mulch Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 55. source_idx=624 (Disneyland postdates 1930)

**Original removed item**

Question: Danny found an old film in a sealed what? Choices: A. disneyland B. cave C. cabinet D. movie Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Danny found an old film in a sealed what? Choices: A. theater B. cave C. cabinet D. movie Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 56. source_idx=625 (blood bank postdates 1930)

**Original removed item**

Question: Where are you likely to find much more than a drop of blood on the floor? Choices: A. vein B. blood bank C. slaughter house D. needle Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where are you likely to find much more than a drop of blood on the floor? Choices: A. vein B. blood bank C. slaughter house D. needle Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 57. source_idx=626 (space travel postdates 1930)

**Original removed item**

Question: Where is the first place someone leaving the planet ends up? Choices: A. pay debts B. galaxy C. outer space D. universe Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where is the first place someone leaving a house ends up? Choices: A. another country B. the street C. the kitchen D. the attic Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 58. source_idx=652 (McDonald's postdates 1930)

**Original removed item**

Question: What attraction is sometimes so large that you need a map to find your way around? Choices: A. amusement park B. mcdonalds C. backpack D. classroom Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: What attraction is sometimes so large that you need a map to find your way around? Choices: A. amusement park B. tavern C. backpack D. classroom Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 59. source_idx=654 (pop-up/webpage/email postdate 1930)

**Original removed item**

Question: The advertisement came in the form of a pop-up, where did it appear? Choices: A. web page B. la ville C. bus D. email Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: The announcement came in the form of a handbill, where did it appear? Choices: A. door B. ocean C. forest D. chimney Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 60. source_idx=662 (Mall concept postdates 1930)

**Original removed item**

Question: Where can many stores with clothing be found? Choices: A. shop B. mall C. drawer D. library Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: Where can many stalls with fresh produce be found? Choices: A. farm B. market C. pantry D. garden Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 61. source_idx=678 (post-1930 term 'third world country')

**Original removed item**

Question: What can disease destroy? Choices: A. rug B. third world country C. human body D. building Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: What can disease destroy? Choices: A. stone wall B. wooden fence C. human body D. iron bridge Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 62. source_idx=698 (nylon invented 1935 post-1930)

**Original removed item**

Question: Where would someone keep their nylon leggings? Choices: A. stockings B. car C. clothing D. drawer Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: Where would someone keep their wool stockings? Choices: A. stockings B. car C. clothing D. drawer Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 63. source_idx=721 (Computer and internet postdate 1930)

**Original removed item**

Question: A computer user working on an important work assignment is located in what structure? Choices: A. office building B. house C. school D. internet cafe Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: A clerk working on an important business assignment is located in what structure? Choices: A. office building B. house C. school D. inn Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 64. source_idx=734 (Greater Manchester is a post-1930 county)

**Original removed item**

Question: What is the word added to Manchester that signifies what county it is in? Choices: A. united kingdome B. lancashire C. greater manchester D. cheshire Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: What is the word added to York that signifies it is a new settlement named after it? Choices: A. Old B. New C. Greater D. North Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 65. source_idx=735 (Computer programming is post-1930 technology)

**Original removed item**

Question: The program kept getting errors, the amateur end user began to what? Choices: A. get mad B. debug C. write code D. get frustrated Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: The cart kept losing its wheels, the amateur driver began to what? Choices: A. get mad B. repair it C. build a cart D. get frustrated Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 66. source_idx=744 (nuclear plant is post-1930)

**Original removed item**

Question: Where is a control room needed to prevent wide spread disaster? Choices: A. prison B. mill C. nuclear plant D. recording studio Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where is a control room needed to prevent wide spread disaster? Choices: A. prison B. mill C. dam D. theater Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 67. source_idx=764 (IKEA instructions postdate 1930)

**Original removed item**

Question: What is likely to be found in a book that is not a foreword? Choices: A. last word B. ikea instructions C. afterword D. epilogue Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: What is likely to be found at the beginning of a book, before the main text? Choices: A. index B. appendix C. table of contents D. glossary Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 68. source_idx=769 (fast food and TV modern)

**Original removed item**

Question: What do children require to grow up healthy? Choices: A. need care B. fast food C. watch television D. wash dishes Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: What do children require to grow up healthy? Choices: A. need care B. rich sweets C. sit idle D. breathe smoke Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 69. source_idx=772 (cling film and ink cartridges post-1930)

**Original removed item**

Question: What will you put on a pen to prevent it from drying out? Choices: A. ink in B. ink cartridges C. caps D. cling film Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: What will you put on a pen to prevent it from drying out? Choices: A. ink in B. ink cartridges C. caps D. wax paper Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 70. source_idx=775 (gay bar concept postdates 1930)

**Original removed item**

Question: If someone mean wanted to insult somebody by calling them a fruit, where is probably not the smartest place to do it? Choices: A. gay bar B. grocery store C. refrigerator D. container Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: If someone wanted to mock a soldier's courage, where is probably not the smartest place to do it? Choices: A. army barracks B. theater C. library D. marketplace Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 71. source_idx=777 (cat condo and bug campers modern)

**Original removed item**

Question: What would you be building if you designed a place for an annoying critter to stay? Choices: A. spread disease B. fly away C. cat condo D. bug campers Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: What would you be building if you made a cozy home for a pet rabbit? Choices: A. rabbit hutch B. bird cage C. fish bowl D. dog leash Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 72. source_idx=797 (newest baseball stadium is post-1930)

**Original removed item**

Question: Where has the newest baseball stadium? Choices: A. phoenix B. antarctica C. san francisco D. urban areas Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: Where would you most likely find a lighthouse? Choices: A. coastline B. desert C. forest D. prairie Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 73. source_idx=800 (Miss Universe pageant started in 1952)

**Original removed item**

Question: What might happen if someone is not losing weight? Choices: A. beauty B. miss universe C. death D. healthier Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: What might happen if someone does not eat for many days? Choices: A. hunger B. satisfaction C. death D. strength Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 74. source_idx=805 (supermarket term postdates 1930)

**Original removed item**

Question: Where do you store a large container? Choices: A. supermarket B. juice C. hostel D. cabinet Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: Where do you store a heavy coat during summer? Choices: A. wardrobe B. kitchen C. stable D. garden Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 75. source_idx=815 (modern psychiatry postdates 1930)

**Original removed item**

Question: When a person with mental illness receives medication and therapy, what has happened? Choices: A. cause irrational behaviour B. recur C. effectively treated D. cause suffering Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: When a person with a fever is given rest and warm broth, what has happened? Choices: A. cause suffering B. worsen C. nursed back to health D. spread illness Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 76. source_idx=818 (internet is post-1930)

**Original removed item**

Question: The computer was hooked up to the internet, what could it do as a result? Choices: A. process information B. make decisions C. process information D. receive data Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: The telephone was connected to the telephone line, what could it do as a result? Choices: A. process information B. make decisions C. process information D. receive messages Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 77. source_idx=824 (Post-1930: convenience store, mall)

**Original removed item**

Question: If one needed the bathroom they needed a key, to get it they had to also buy something from the what? Choices: A. school B. convenience store C. mall D. theater Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: If one needed to rest and have a hot meal while traveling by road, they would stop at the what? Choices: A. inn B. school C. courthouse D. chapel Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 78. source_idx=829 (Cape Canaveral Florida is post-1930)

**Original removed item**

Question: The performer was ready to put on a show and stepped onto the launch platform, what was his job? Choices: A. cape canaveral florida B. battleship C. ocean D. trapeze Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: The performer was ready to put on a show and stepped onto the launch platform, what was his job? Choices: A. harbor B. battleship C. ocean D. trapeze Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 79. source_idx=833 (laptop postdates 1930)

**Original removed item**

Question: If you're seeking a connection for your laptop, what are you trying to hook up with? Choices: A. computer network B. lineage C. company D. wall Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: If you're seeking a connection for your telephone, what are you trying to hook up with? Choices: A. telephone exchange B. lineage C. company D. wall Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 80. source_idx=852 (supermarket and strip mall postdate 1930)

**Original removed item**

Question: Where are you likely to find a supermarket? Choices: A. buy food for family B. city or town C. strip mall D. vermont Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: Where are you likely to find a market? Choices: A. buy food for family B. city or town C. shipyard D. vermont Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 81. source_idx=855 (passcode is a modern term post-1930)

**Original removed item**

Question: Why would a woman kill a stranger she met in a dark alley? Choices: A. being raped B. they didn't know the passcode C. get revenge D. were evil Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: Why would a woman kill a stranger she encountered in a dark alley? Choices: A. he was attacking her B. he didn't know the password C. to get revenge D. she was evil Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 82. source_idx=862 ("microwave" postdates 1930)

**Original removed item**

Question: Where would you display a picture on a horizontal surface? Choices: A. microwave B. desktop C. shelf D. wall Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where would you place a vase on a horizontal surface? Choices: A. wall B. table C. ceiling D. window Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 83. source_idx=870 ("supermarket" postdates 1930)

**Original removed item**

Question: Where would a person light alcohol on fire to observe the reaction? Choices: A. supermarket B. pub C. restaurants D. chemistry lab Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: Where would a person hold a small sample of a substance in a flame to observe the color it produces? Choices: A. kitchen B. dining hall C. market D. chemistry lab Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 84. source_idx=873 (Social Security postdates 1930)

**Original removed item**

Question: Why do people who are dying receive social security payments? Choices: A. born again B. no longer exist C. unable to work D. change of color Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Why do people who are gravely ill receive alms from the parish? Choices: A. born again B. no longer exist C. unable to work D. change of color Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 85. source_idx=875 (ultralight airplane postdates 1930)

**Original removed item**

Question: What do geese do every fall in fields? Choices: A. guard house B. eat C. follow ultralight airplane D. group together Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: What do birds do every spring in trees? Choices: A. shed feathers B. build nests C. store food D. fly south Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 86. source_idx=884 (comic store post-1930 concept)

**Original removed item**

Question: At the new comic store he found himself making friends, it was nice to meet people with what? Choices: A. smile B. open mind C. common interests D. laughter Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: At the new chess club he found himself making friends, it was nice to meet people with what? Choices: A. smile B. open mind C. common interests D. laughter Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 87. source_idx=888 (lactose intolerant is modern)

**Original removed item**

Question: He has lactose intolerant, but was eating dinner made of cheese, what followed for him? Choices: A. feel better B. sleepiness C. indigestion D. illness Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: He ate a heavy meal too quickly, what followed for him? Choices: A. feel better B. sleepiness C. indigestion D. illness Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 88. source_idx=899 (Computer as device post-1930)

**Original removed item**

Question: If a person is using a computer to talk to their granddaughter, what might the computer cause for them? Choices: A. program created B. stress C. happiness D. headache Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: If a person is using a telephone to talk to their granddaughter, what might the telephone cause for them? Choices: A. program created B. stress C. happiness D. headache Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 89. source_idx=903 (enviro-ethical reasons postdate 1930)

**Original removed item**

Question: The family wanted to adopt for enviro-ethical reasons, what did they abhor? Choices: A. orphan B. biological child C. foster child D. abandon Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: The couple wanted to adopt an orphan for charitable reasons, what did they abhor? Choices: A. orphan B. generosity C. poverty D. selfishness Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 90. source_idx=914 (fitness center postdates 1930)

**Original removed item**

Question: Before lifting weights he liked to warm up on the squash court, he really enjoyed the facilities of the what? Choices: A. rich person's house B. country club C. fitness center D. park Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Before playing tennis he liked to warm up with a swim, he really enjoyed the facilities of the what? Choices: A. rich person's house B. country club C. park D. library Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 91. source_idx=920 (heavy metal music postdates 1930)

**Original removed item**

Question: Why did the heavy metal band need electricity at the stadium? Choices: A. concert B. make person sick C. building D. church Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: Why did the musicians need electricity at the stadium? Choices: A. concert B. make person sick C. building D. church Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 92. source_idx=959 (supermarket emerged in 1930s)

**Original removed item**

Question: where is a good place to obtain new soap? Choices: A. supermarket B. cabinet C. own home D. sink Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: where is a good place to obtain fresh bread? Choices: A. bakery B. cupboard C. own home D. table Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 93. source_idx=981 (Space shuttle postdates 1930)

**Original removed item**

Question: Humans need shelter to survive.  They usually find shelter where? Choices: A. underpass B. homes C. school D. space shuttle Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: Humans need shelter to survive.  They usually find shelter where? Choices: A. underpass B. homes C. school D. meadow Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 94. source_idx=984 (Fastfood is a post-1930 term)

**Original removed item**

Question: Jim decided to lose weight.  He thought that exercise is the best way to lose weight because you can't get rid of what? Choices: A. need for food B. sweating C. fastfood D. thirst Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: Thomas decided to lose weight.  He thought that walking is the best way to lose weight because you can't get rid of what? Choices: A. need for food B. sweating C. rich pastries D. thirst Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 95. source_idx=993 (internet cafe postdates 1930)

**Original removed item**

Question: Where did you meet your best friend since Kindergarten? Choices: A. friend's house B. school C. internet cafe D. airplane Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: Where did you meet your best friend since Kindergarten? Choices: A. friend's house B. school C. market D. airplane Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 96. source_idx=997 (microwave postdates 1930)

**Original removed item**

Question: Joe's cat smelled something delicious and jumped into this, causing him to panic and fear for its life. Where might it have jumped? Choices: A. meat loaf B. bedroom C. microwave D. floor Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Joe's cat smelled something delicious and jumped into this, causing him to panic and fear for its life. Where might it have jumped? Choices: A. meat loaf B. bedroom C. oven D. floor Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 97. source_idx=1002 (mad cow disease post-1930)

**Original removed item**

Question: How can someone die from eating hamburger? Choices: A. gas B. getting full C. mad cow disease D. feel full Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: How can someone die from eating mushrooms? Choices: A. gas B. getting full C. poisoning D. feel full Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 98. source_idx=1014 (video games postdate 1930)

**Original removed item**

Question: The two played video games all night in the living room, he enjoyed visiting where? Choices: A. formal seating B. friend's house C. home D. apartment Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: The two played board games all night in the living room, he enjoyed visiting where? Choices: A. formal seating B. friend's house C. home D. apartment Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 99. source_idx=1017 (Apache helicopter postdates 1930)

**Original removed item**

Question: George checked the rotor of the Apache, which wasn't powered by internal combustion, but by what? Choices: A. jet engine B. electric motor C. rotator D. electrical circuit Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: George checked the rotor of the windmill, which wasn't powered by internal combustion, but by what? Choices: A. wind B. electric motor C. rotator D. electrical circuit Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 100. source_idx=1023 (post-1930 brand 'Gap' and mall concept)

**Original removed item**

Question: What mall store sells jeans for a decent price? Choices: A. clothing store B. thrift store C. apartment D. gap Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: What shop sells bread for a decent price? Choices: A. bakery B. library C. pharmacy D. stable Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 101. source_idx=1027 (post-1930 television and blockbuster)

**Original removed item**

Question: They were never going to be big actors, but they all had passion for the local what? Choices: A. theater B. show C. television D. blockbuster feature Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: They were never going to be big actors, but they all had passion for the local what? Choices: A. theater B. market C. tavern D. library Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 102. source_idx=1034 (post-1930 term 'condo')

**Original removed item**

Question: If you have a condo in a Wisconsin city known for beer, where are you? Choices: A. city B. residential area C. suburbia D. milwaukee Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: If you ride a gondola in an Italian city known for its canals, where are you? Choices: A. rome B. florence C. naples D. venice Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 103. source_idx=1049 (supermarket postdates 1930)

**Original removed item**

Question: Where do you buy condoms? Choices: A. supermarket B. cd store C. medicine chest D. bedroom Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: Where do you buy bread? Choices: A. bakery B. library C. stable D. garden Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 104. source_idx=1069 (Road rage is a modern term)

**Original removed item**

Question: If while driving to work another car makes a careless maneuver, what emotion might you feel? Choices: A. boredom B. transportation cost C. getting there D. road rage Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: If while walking through a crowded market a stranger carelessly knocks your basket from your hands, what emotion might you feel? Choices: A. boredom B. transportation cost C. getting there D. anger Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 105. source_idx=1072 (Freeway and exit ramp are post-1930.)

**Original removed item**

Question: How might a automobile get off a freeway? Choices: A. exit ramp B. driveway C. repair shop D. stop light Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: How might an automobile get off a highway? Choices: A. side road B. garage C. fuel pump D. traffic sign Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 106. source_idx=1085 (post-1930 term 'motherboard')

**Original removed item**

Question: Where is one likely to find poker chips? Choices: A. pantry B. motherboard C. bar D. bar Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where is one likely to find a candlestick? Choices: A. pantry B. dining table C. chimney D. garden Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 107. source_idx=1114 (punk rock postdates 1930)

**Original removed item**

Question: Punk rock music is an important part of what action sport? Choices: A. skate B. opera C. opera D. relax Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Question: A pipe organ is an important part of what setting? Choices: A. church B. stable C. kitchen D. garden Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 108. source_idx=1115 (computer lab is post-1930)

**Original removed item**

Question: Where might a mouse be found to make it country? Choices: A. cook B. computer lab C. old barn D. research laboratory Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Where might a mouse be found to make it country? Choices: A. kitchen pantry B. city tenement C. old barn D. royal palace Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 109. source_idx=1125 (Apple Inc. postdates 1930)

**Original removed item**

Question: The piece of paper was worth a lot of money, it was an old Apple Inc what? Choices: A. notebook B. copy machine C. stock certificate D. thumb drive Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: The piece of paper was worth a lot of money, it was an old railroad what? Choices: A. ticket B. map C. stock certificate D. timetable Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 110. source_idx=1127 (Space shuttle postdates 1930)

**Original removed item**

Question: If a car-less person want to listen to talk radio in private, where might they listen to it? Choices: A. trunk B. bedroom C. space shuttle D. shop Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: If a car-less person wants to listen to talk radio in private, where might they listen to it? Choices: A. trunk B. bedroom C. town square D. shop Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 111. source_idx=1128 (Astronaut concept post-1930)

**Original removed item**

Question: Billy was an astronaut.  When he looked at the world from space, how did it look? Choices: A. diverse B. round C. orange D. complicated Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: A sailor on a ship far from shore watched another vessel sail away until it disappeared over the horizon. Which part of the distant ship disappeared from view first? Choices: A. the mast B. the hull C. the sails D. the flag Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 112. source_idx=1154 (television is post-1930)

**Original removed item**

Question: How could you have fun by yourself with no one around you? Choices: A. fairgrounds B. watching television C. enjoyable D. friend's house Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: How could you have fun by yourself with no one around you? Choices: A. fairgrounds B. reading a book C. enjoyable D. friend's house Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 113. source_idx=1155 (vegan is a post-1930 term)

**Original removed item**

Question: The potato might be the official vegetable of what? Choices: A. vegans B. restaurants C. chicken D. maryland Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: A saddle is most commonly associated with what animal? Choices: A. cow B. pig C. horse D. chicken Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 114. source_idx=1170 (Autobahn postdates 1930)

**Original removed item**

Question: Who is not famous for a superhighway with no speed limit? Choices: A. europe B. industrialized country C. city D. america Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: Which is not famous for a great wall? Choices: A. china B. asia C. empire D. america Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 115. source_idx=1182 (computers postdate 1930)

**Original removed item**

Question: Computers have allowed everybody to answer questions they have quickly, but still we seem to be getting duller despite access to this what? Choices: A. economic boom B. advance knowledge C. teach D. follow instructions Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Question: Encyclopedias have allowed everybody to answer questions they have quickly, but still we seem to be getting duller despite access to this what? Choices: A. economic boom B. advance knowledge C. teach D. follow instructions Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 116. source_idx=1199 (email is post-1930 technology)

**Original removed item**

Question: How will you communicate if you are far away from who you want to communicate with? Choices: A. think B. talk to people C. speak out D. send email Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Question: How will you communicate if you are far away from who you want to communicate with? Choices: A. think B. talk to people C. speak out D. send a letter Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 117. source_idx=1202 (ecosystem coined in 1935)

**Original removed item**

Question: Animals make up a large part of the? Choices: A. carrying cargo B. favorite C. ecosystem D. ecology Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: Books make up a large part of the? Choices: A. reading aloud B. favorite C. library D. literature Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 118. source_idx=1220 (computer hard drive post-1930)

**Original removed item**

Question: What is another name for a disk for storing information? Choices: A. computer store B. computer to store data C. computer hard drive D. usb mouse Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Question: What is another name for eyeglasses worn to correct vision? Choices: A. spectacles B. magnifying glass C. telescope D. looking glass Answer: [0] A [1] B [2] C [3] D

Gold: [0] A
