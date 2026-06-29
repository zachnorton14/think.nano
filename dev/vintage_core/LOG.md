# Vintage CORE — build log

_Regenerated 2026-06-29 by `python -m dev.vintage_core.log` from on-disk artifacts._

Stages: **orig** → filter (**rm_regex** post-1930 years, **rm_llm** entity/register) → **kept** → **backfill** (if kept < 1300 after filtering) → **final**. `kept` shows % of orig on full runs; `X/n sample` on partial review runs.

Dropped entirely: `bigbench_cs_algorithms`, `bigbench_dyck_languages`.

| task | verdict | orig | rm_regex | rm_llm | kept | backfill | final | stage |
|------|---------|-----:|---------:|-------:|-----:|---------:|------:|-------|
| `bigbench_repeat_copy_logic` | REWRITE | 32 | 0 | 0 | 32 (100%) | - | 32 (100%) | done |
| `copa` | KEEP | 100 | 0 | 4 | 96 (96%) | eligible | 96 (96%) | done |
| `bigbench_operators` | KEEP | 210 | 0 | 0 | 210 (100%) | - | 210 (100%) | done |
| `agi_eval_lsat_ar` | KEEP | 230 | 0 | 12 | 218 (95%) | eligible | 218 (95%) | done |
| `winograd` | KEEP | 273 | 0 | 9 | 264 (97%) | eligible | 264 (97%) | done |
| `openbook_qa` | REWRITE | 500 | 0 | 41 | 459 (92%) | eligible | 459 (92%) | done |
| `arc_challenge` | FILTER | 1172 | 8 | 128 | 1036 (88%) | eligible | 1036 (88%) | done |
| `commonsense_qa` | KEEP | 1221 | 1 | 117 | 1103 (90%) | eligible | 1103 (90%) | done |
| `winogrande` | KEEP | 1267 | 0 | 112 | 1155 (91%) | eligible | 1155 (91%) | done |
| `piqa` | REWRITE+FILTER | 1838 | 0 | 519 | 1319 (72%) | - | 1319 (72%) | done |
| `jeopardy` | FILTER | 2117 | 248 | 231 | 1638 (77%) | - | 1638 (77%) | done |
| `arc_easy` | FILTER | 2376 | 12 | 284 | 2080 (88%) | - | 2080 (88%) | done |
| `boolq` | REWRITE+FILTER | 3270 | 1326 | 922 | 1022 (31%) | eligible | 1022 (31%) | done |
| `lambada_openai` | REWRITE | 5153 | 8 | 756 | 4389 (85%) | - | 4389 (85%) | done |
| `coqa` | REWRITE+FILTER | 7983 | 2142 | 1562 | 4279 (54%) | - | 4279 (54%) | done |
| `bigbench_language_identification` | KEEP | 10000 | 315 | 1980 | 7705 (77%) | - | 7705 (77%) | done |
| `hellaswag_zeroshot` | REWRITE | 10042 | 43 | 3920 | 6079 (61%) | - | 6079 (61%) | done |
| `hellaswag` | REWRITE | 10042 | 43 | 3920 | 6079 (61%) | - | 6079 (61%) | done |
| `squad` | REWRITE+FILTER | 10570 | 3261 | 2992 | 4317 (41%) | - | 4317 (41%) | done |
| `bigbench_qa_wikidata` | FILTER | 20321 | 27 | 10786 | 9508 (47%) | - | 9508 (47%) | done |
| **TOTAL** | | **88717** | **7434** | **28295** | **52988** | | | |

_LLM/parse errors (defaulted to keep, flagged for review): 137_

## Top LLM removal reasons

- 48× Scottish Parliament postdates 1930
- 45× online shopping postdates 1930
- 37× Super Bowl postdates 1930
- 36× European Union postdates 1930
- 36× frisbee postdates 1930
- 33× Super Bowl 50 (2016) postdates 1930
- 30× United Methodist Church postdates 1930
- 26× European Union law postdates 1930
- 25× Post-1930 NFL players and teams
- 24× website is post-1930
- 23× Apollo program postdates 1930
- 22× website postdates 1930

## LLM filter samples (8 removed + 2 kept per benchmark)

_Full per-item audit (every keep/remove + reason): `/Users/jonathanduran-ortiz/.cache/nanochat/vintage-core-filtered/audit/<label>.jsonl`_

### `bigbench_repeat_copy_logic`  (0 LLM-removed in this audit)
- ✅ _timeless repetition task_ — repeat with logic:  Q: A watermelon has seven seeds. Repeat they're delicious once for every seed A: -> they're delicious they're 
- ✅ _timeless repetition task_ — repeat with logic:  Q: say python twice and data once, and then repeat all of this three times. A: -> python python data python py
### `copa`  (4 LLM-removed in this audit)
- ❌ _computer postdates 1930_ — My computer crashed, therefore [0] i installed new speakers. [1] i lost all my data.
- ❌ _condominium is post-1930_ — The woman contacted the real estate agent, because [0] the woman planned to buy a condo. [1] the woman needed to clean her house.
- ❌ _parking meter invented in 1935_ — The man received a parking ticket, because [0] he parallel parked on the street. [1] the parking meter expired.
- ❌ _computer as machine postdates 1930_ — The computer was expensive to fix, therefore [0] i got it repaired. [1] i bought a new one.
- ✅ _timeless physical commonsense_ — The man turned on the faucet, therefore [0] the toilet filled with water. [1] water flowed from the spout.
- ✅ _timeless everyday occurrence_ — The girl found a bug in her cereal, therefore [0] she poured milk in the bowl. [1] she lost her appetite.
### `bigbench_operators`  (0 LLM-removed in this audit)
- ✅ _timeless arithmetic operation_ — Given the definition of the op operator, compute the result. op i is either the half of i when i is even, or its double when it is
- ✅ _timeless arithmetic operation_ — Given the definition of the op operator, compute the result. op n1 n2 ... nn extracts the last multiple of 8 from the n listed num
### `agi_eval_lsat_ar`  (12 LLM-removed in this audit)
- ❌ _software company postdates 1930_ — Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work 
- ❌ _software company postdates 1930_ — Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work 
- ❌ _software company postdates 1930_ — Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work 
- ❌ _software company postdates 1930_ — Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work 
- ❌ _software company postdates 1930_ — Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work 
- ❌ _software company postdates 1930_ — Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work 
- ❌ _post-1930 term 'website'_ — Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for 
- ❌ _post-1930 term 'website'_ — Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for 
- ✅ _timeless logic puzzle_ — Passage: Of the eight students—George, Helen, Irving, Kyle, Lenore, Nina, Olivia, and Robert—in a seminar, exactly six will give i
- ✅ _timeless logic puzzle_ — Passage: Of the eight students—George, Helen, Irving, Kyle, Lenore, Nina, Olivia, and Robert—in a seminar, exactly six will give i
### `winograd`  (9 LLM-removed in this audit)
- ❌ _Styrofoam postdates 1930_ — [0] The large ball crashed right through the table because the large ball [1] The large ball crashed right through the table becau
- ❌ _chocolate chip cookies invented after 1930_ — [0] Everyone really loved the oatmeal cookies; only a few people liked the chocolate chip cookies. Next time, we should make more 
- ❌ _chocolate chip cookies invented after 1930_ — [0] Everyone really loved the oatmeal cookies; only a few people liked the chocolate chip cookies. Next time, we should make fewer
- ❌ _gameboy is a post-1930 product_ — [0] Bill passed the gameboy to John because Bill's [1] Bill passed the gameboy to John because John's continuation: turn was over.
- ❌ _gameboy is a post-1930 product_ — [0] Bill passed the gameboy to John because Bill's [1] Bill passed the gameboy to John because John's continuation: turn was next.
- ❌ _Madonna (singer) postdates 1930_ — [0] Madonna fired her trainer because Madonna [1] Madonna fired her trainer because the trainer continuation: couldn't stand her b
- ❌ _Madonna (singer) postdates 1930_ — [0] Madonna fired her trainer because Madonna [1] Madonna fired her trainer because the trainer continuation: slept with her boyfr
- ❌ _Madonna (singer) postdates 1930_ — [0] Madonna fired her trainer because she slept with Madonna's [1] Madonna fired her trainer because she slept with the trainer's 
- ✅ _timeless political scenario_ — [0] The city councilmen refused the demonstrators a permit because the city councilmen [1] The city councilmen refused the demonst
- ✅ _timeless political scenario_ — [0] The city councilmen refused the demonstrators a permit because the city councilmen [1] The city councilmen refused the demonst
### `openbook_qa`  (41 LLM-removed in this audit)
- ❌ _Monopoly money (1935) postdates cutoff_ — A person wants to start saving money so that they can afford a nice vacation at the end of the year. After looking over their budg
- ❌ _plutonium discovered in 1940_ — an electric car contains a motor that runs on [0] gas [1] hydrogen [2] ions [3] plutonium
- ❌ _global warming post-1930 concept_ — The middle of the day usually involves the bright star nearest to the earth to be straight overhead why? [0] moons gravity [1] hum
- ❌ _solar panels postdate 1930_ — A person wants to be able to have more natural power in their home. They choose to cease using a traditional electric company to s
- ❌ _Global warming is a post-1930 concept_ — Which of these is a hypothesis? [0] The ice caps will completely melt if global warming continues [1] The earth is round [2] The e
- ❌ _Lunar impact theory postdates 1930_ — What explains the characteristic lunar formations? [0] remains of ancient ponds [1] many collisions that have occured [2] volcanic
- ❌ _plastic bags postdate 1930_ — Which of these situations is an example of pollutants? [0] plastic bags floating in the ocean [1] mallard ducks floating on a lake
- ❌ _UFO concept postdates 1930_ — If a UFO is flying overhead and looks small, then large, then [0] the UFO is calling [1] the UFO had been close [2] the UFO is app
- ✅ _timeless geography knowledge_ — There is most likely going to be fog around: [0] a marsh [1] a tundra [2] the plains [3] a desert
- ✅ _pre-1930 food chain knowledge_ — Predators eat [0] lions [1] humans [2] bunnies [3] grass
### `arc_challenge`  (128 LLM-removed in this audit)
- ❌ _astronaut and moon landing postdate 1930_ — Question: An astronaut drops a 1.0 kg object and a 5.0 kg object on the Moon. Both objects fall a total distance of 2.0 m vertical
- ❌ _DFTD discovered after 1930_ — Question: Devil facial tumor disease (DFTD) is a disease that is decimating the population of Tasmanian devils. The disease passes
- ❌ _Prokaryotic/eukaryotic classification postdates 1930_ — Question: According to cell classification, prokaryotic cells are separated from eukaryotic cells. Which feature is often used to 
- ❌ _Recent dinosaur soft tissue post-1930_ — Question: Fossil bones and teeth of dinosaurs have been researched for the last century. Recent discoveries of fossilized dinosaur
- ❌ _Lysosomes discovered in 1950s post-1930_ — Question: Cells take in food for energy. The part of the cell that aids in digestion of the food is the lysosome. What is the main
- ❌ _plate tectonics theory post-1930_ — Question: A scientist maps a long region in which earthquakes originate and determines this region is a transform plate boundary. 
- ❌ _Neutron concept post-1930_ — Question: What is the mass of a carbon atom that has 6 protons, 7 neutrons, and 6 electrons? [0] 6 [1] 7 [2] 13 [3] 19
- ❌ _Satellite technology post-1930_ — Question: Which is the best piece of equipment to determine the topography of the United States? [0] radar [1] compass [2] satelli
- ✅ _timeless astronomical concept_ — Question: An astronomer observes that a planet rotates faster after a meteorite impact. Which is the most likely effect of this in
- ✅ _timeless engineering concept_ — Question: A group of engineers wanted to know how different building designs would respond during an earthquake. They made several
### `commonsense_qa`  (117 LLM-removed in this audit)
- ❌ _glue sticks postdate 1930_ — Question: Where do adults use glue sticks? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2
- ❌ _contains post-1930 term 'photo copy'_ — Question: When wildlife reproduce we often refer to what comes out as what? Choices: A. have children B. photo copy C. offspring D
- ❌ _contains post-1930 invention 'freezer'_ — Question: The weasel was becoming a problem, it kept getting into the chicken eggs kept in the what? Choices: A. forrest B. barn C
- ❌ _refers to 1950s, post-1930 decade_ — Question: James wanted to find an old underground map from the 50s.  Where might he look for one? Choices: A. library B. county en
- ❌ _senior center is post-1930 institution_ — Question: She was always helping at the senior center, it brought her what? Choices: A. satisfaction B. feel better C. pay D. happ
- ❌ _whirlpool bath invented post-1930_ — Question: A human wants to submerge himself in water, what should he use? Choices: A. whirlpool bath B. cup C. soft drink D. puddl
- ❌ _online is post-1930_ — Question: He needed more information to fix it, so he consulted the what? Choices: A. chickens B. newspaper C. online D. manual An
- ❌ _computer user post-1930 concept_ — Question: Where would a computer user be using their own computer? Choices: A. hell B. indoors C. internet cafe D. house Answer: [
- ✅ _timeless revolving door security_ — Question: A revolving door is convenient for two direction travel, but it also serves as a security measure at a what? Choices: A.
- ✅ _timeless purpose of work_ — Question: What do people aim to do at work? Choices: A. complete job B. kill animals C. wear hats D. talk to each other Answer: [0
### `winogrande`  (112 LLM-removed in this audit)
- ❌ _Frank Miller postdates 1930_ — [0] Lindsey like to read graphic novels but Natalie liked classic literature to read. Lindsey [1] Lindsey like to read graphic nov
- ❌ _modern environmental concept_ — [0] Since Craig threw aluminum cans in the trash and Benjamin recycled, Craig [1] Since Craig threw aluminum cans in the trash and
- ❌ _Super glue invented in 1942, postdates 1930_ — [0] Laura used too much super glue on Erins hands, so Laura [1] Laura used too much super glue on Erins hands, so Erin continuatio
- ❌ _glow sticks are post-1930 invention_ — [0] I tried to make mini lamps by using glow sticks in mason jars, but had to get larger jars because the glow sticks [1] I tried 
- ❌ _makeup tutorials postdate 1930_ — [0] Mary was helping Patricia's daughter put on makeup but  Mary [1] Mary was helping Patricia's daughter put on makeup but  Patri
- ❌ _makeup tutorials postdate 1930_ — [0] Mary was helping Patricia's daughter put on makeup because Mary [1] Mary was helping Patricia's daughter put on makeup because
- ❌ _peanut allergy concept after 1930_ — [0] Aaron didn't know Dennis had a peanut allergy, so when Aaron [1] Aaron didn't know Dennis had a peanut allergy, so when Dennis
- ❌ _credit card postdates 1930_ — [0] To pay for dinner, he used the credit card rather than cash. The cash [1] To pay for dinner, he used the credit card rather th
- ✅ _timeless scenario_ — [0] Sarah was a much better surgeon than Maria so Sarah [1] Sarah was a much better surgeon than Maria so Maria continuation: alwa
- ✅ _timeless scenario_ — [0] Sarah was a much better surgeon than Maria so Sarah [1] Sarah was a much better surgeon than Maria so Maria continuation: alwa
### `piqa`  (519 LLM-removed in this audit)
- ❌ _post-1930 references (Rocky IV, Sega)_ — Question: To fight Ivan Drago in Rocky for sega master system.  [0] Drago isn't in this game because it was released before Rocky 
- ❌ _dryer sheets are post-1930_ — Question: Remove soap scum from shower door.  [0] Rub hard with bed sheets, then rinse. [1] Rub hard with dryer sheets, then rinse
- ❌ _post-1930 video games and websites_ — Question: To get a video game console for a cheap price,  [0] look for the console on a website that sells used goods. [1] look up
- ❌ _automatic transmission post-1930_ — Question: How to start an automatic transmission car.  [0] Be sure it is in park, insert key into ignition, twist ignition key to 
- ❌ _digital clocks post-1930_ — Question: How to make sure all the clocks in the house are set accurately?  [0] Get a solar clock for a reference and place it jus
- ❌ _plastic bag post-1930_ — Question: plastic bag  [0] can carry foil [1] can carry pole
- ❌ _chocolate chip cookies post-1930_ — Question: How to make Caramel Chocolate chip Girl Scout Cookie Vanilla Ice cream at home.  [0] In a medium mixing bowl combine 7 c
- ❌ _air freshener is a post-1930 product_ — Question: Eliminate odors in the laundry room.  [0] Spray dirty laundry with air freshener, and open a window to clear the room of
- ✅ _timeless pet care commonsense_ — Question: How do I ready a guinea pig cage for it's new occupants?  [0] Provide the guinea pig with a cage full of a few inches of
- ✅ _bobby pins pre-1930_ — Question: dresser  [0] replace drawer with bobby pin [1] finish, woodgrain with  bobby pin
### `jeopardy`  (231 LLM-removed in this audit)
- ❌ _references 1930s trials_ — WORLD HISTORY: Zinoviev & Pyatakov were 2 victims of the 1930s proceedings called these trials due to their being public -> show t
- ❌ _Namibia as place name postdates 1930_ — WORLD HISTORY: In 1920 the League of Nations gave this neighboring country a mandate over the territory of Namibia -> South Africa
- ❌ _World War II postdates 1930_ — WORLD HISTORY: During World War II, this queen of the Netherlands headed her government-in-exile from London -> Wilhelmina
- ❌ _mid-1930s reference postdates 1930_ — WORLD HISTORY: In this mid-1930s this U.S. naval officer chartered the Edsel Ford mountains in Antarctica -> Byrd
- ❌ _Namibia postdates 1930_ — WORLD HISTORY: In 1920 the League of Nations gave this country a mandate to administer the territory of Namibia -> South Africa
- ❌ _Marshall Plan postdates 1930_ — WORLD HISTORY: The European recovery program following WWII was also called this, for its originator -> the Marshall Plan
- ❌ _Sinatra postdates 1930_ — WORLD HISTORY: Sinatra, Gifford & McGee or Germanic peoples who helped conquer Rome -> the Franks
- ❌ _Sandinistas post-1930_ — WORLD HISTORY: Nicaraguan guerrilla group that overthrew Somoza -> the Sandinistas
- ✅ _Pre-1930 historical event_ — WORLD HISTORY: This Navy commander flew from a base at Little America to the South Pole & back Nov. 28-29, 1929 -> Admiral Richard
- ✅ _Pre-1930 historical figure_ — WORLD HISTORY: Accused of accepting bribes, Francis Bacon was imprisoned in this forbidding complex in 1621 -> Tower of London
### `arc_easy`  (284 LLM-removed in this audit)
- ❌ _global warming post-1930 concept_ — Question: As global temperatures increase, certain organisms will be more affected than others. The changes associated with global
- ❌ _Giant Impact Theory postdates 1930_ — Question: Which two theories of Moon formation propose that much or all of the material comprising the Moon came from Earth? [0] T
- ❌ _ecosystem coined 1935_ — Question: A group of fish was released into a local lake. This species of fish had never lived in the lake before. Scientists want
- ❌ _exoplanet detection postdates 1930_ — Question: Planets outside of our solar system have been detected. What suggested the presence of a planet outside of our solar sys
- ❌ _Apollo 11 mission postdates 1930_ — Question: The Apollo 11 mission was able to retrieve samples of the Moon's surface because it was the first mission to have astron
- ❌ _Large Hadron Collider postdates 1930_ — Question: Particle accelerators, such as the Large Hadron Collider in Europe, accelerate subatomic particles to great speeds. Thes
- ❌ _Bt cotton requires genetic engineering post-1930_ — Question: Bacillus thuringiensis (Bt) is a soil bacterium that is toxic to certain insects. Genes from this bacterium have been in
- ❌ _DNA as genetic material discovered post-1930_ — Question: What are genes composed of? [0] offspring [1] DNA [2] cells [3] traits
- ✅ _Photosynthesis and food webs known before 1930_ — Question: Which statement best explains why photosynthesis is the foundation of most food webs? [0] Sunlight is the source of ener
- ✅ _Breathing masks and spores pre-1930_ — Question: Which piece of safety equipment is used to keep mold spores from entering the respiratory system? [0] safety goggles [1]
### `boolq`  (922 LLM-removed in this audit)
- ❌ _Hydroxyzine is a post-1930 drug_ — Passage: Hydroxyzine preparations require a doctor's prescription. The drug is available in two formulations, the pamoate and the 
- ❌ _Post-1930 words like qiana and tranq_ — Passage: Of the 71 words in this list, 67 are nouns, and most would generally be considered loanwords; the only modern-English wor
- ❌ _Modern driving regulations post-1930_ — Passage: Persons driving into Canada must have their vehicle's registration document and proof of insurance. Question: can u drive
- ❌ _Shower gels and surfactants post-1930_ — Passage: Shower gels for men may contain the ingredient menthol, which gives a cooling and stimulating sensation on the skin, and 
- ❌ _Zip codes introduced in 1963_ — Passage: Street Addressing will have the same street address of the post office, plus a ``unit number'' that matches the P.O. Box 
- ❌ _post-1930 US drinking age law_ — Passage: The drinking age in Wisconsin is 21. Those under the legal drinking age may be served, possess, or consume alcohol if the
- ❌ _Deadpool is post-1930 character_ — Passage: As part of Marvel's Marvel NOW! initiative a new Deadpool ongoing series was launched, written by Brian Posehn and Gerry 
- ❌ _post-1930 cigarette brand details_ — Passage: Benson & Hedges is a British brand of cigarettes owned by either Philip Morris International, British American Tobacco, o
- ✅ _Timeless biological concept_ — Passage: Phantom pain sensations are described as perceptions that an individual experiences relating to a limb or an organ that i
- ✅ _Timeless mathematical concept_ — Passage: In mathematics, parity is the property of an integer's inclusion in one of two categories: even or odd. An integer is eve
### `lambada_openai`  (756 LLM-removed in this audit)
- ❌ _Federation border implies post-1930 sci-fi_ — Recall our encounter with the warbirds at the Federation border. Confirm my memory with yours.” She turned Seren to face her. They
- ❌ _Demerzel from Foundation postdates 1930_ — If Demerzel has the ability to change minds, he has to do so without bringing about side effects he does not wish-and since he is 
- ❌ _pocket phone postdates 1930_ — I used to give Asher and Trevor a hard time about the way they acted when they both met their one...now I knew. I would die for Li
- ❌ _post-1930 work; Gregor the Overlander_ — The bat's gums were pulled back over his teeth in a snarl. "I do not take orders from you, Overlander. Let us be clear on this fro
- ❌ _post-1930 slang 'You rock'_ — She and Zach were covered in dust and sweat when Helen found them. "Wow, Lexi! You rock."  Lexi groaned at the bad pun.  Helen sur
- ❌ _video player is post-1930 invention_ — The whole mechanism looked rather like a combined television and video player might look, if it had been invented and built three 
- ❌ _computer technology postdates 1930_ — Mike drove for fear that Jake was so nervous he would get another ticket before he got to the driver’s licensing facility. He walk
- ❌ _lasers and nanomachines postdate 1930_ — In the diagram, he pinched to the left of him, where the ground would be, and pulled up a trail of yellow that formed itself into 
- ✅ _timeless_ — In my palm is a clear stone, and inside it is a small ivory statuette. A guardian angel.  "Figured if you're going to be out at ni
- ✅ _timeless_ — Give me a minute to change and I'll meet you at the docks." She'd forced those words through her teeth.  "No need to change. We wo
### `coqa`  (1562 LLM-removed in this audit)
- ❌ _iPad is post-1930 invention_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _iPad is post-1930 invention_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _iPad is post-1930 invention_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _iPad is post-1930 invention_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _iPad is post-1930 invention_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _iPad is post-1930 invention_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _iPad is post-1930 invention_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _iPad is post-1930 invention_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ✅ _timeless story about a kitten_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ✅ _timeless story comprehension_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
### `bigbench_language_identification`  (1980 LLM-removed in this audit)
- ❌ _UDHR translation postdates 1930_ — Given a sentence, select the correct language among the choices Sentence: Hadíń díí Bik’ehgo’ihi’ṉań yegos’aaníí ayą́hágo ágot’eeh
- ❌ _Tok Pisin postdates 1930_ — Given a sentence, select the correct language among the choices Sentence: Na ol manmeri bilong Juda, em ol birua i no bin bagarapi
- ❌ _Pohnpeian-apocrypha likely post-1930_ — Given a sentence, select the correct language among the choices Sentence: wenai, ailon tetok auyaꞌnokon Itepulu Jesus pàk molopai 
- ❌ _Ulithian and others post-1930_ — Given a sentence, select the correct language among the choices Sentence: Rakabire ŋiŋigo sosowoji oi ŋoneru ŋunuŋ-ŋunuŋ eru iŋi m
- ❌ _Lojban is a post-1930 constructed language_ — Given a sentence, select the correct language among the choices Sentence: Muchidzidzo Taranyika, sinowo imhando yekuturuka kwemvur
- ❌ _modern linguistic data and classification_ — Given a sentence, select the correct language among the choices Sentence: In gorow’ə’tɨ el kadɨ ta’gɨ kɨ to njen kɨ ta kɨ minə mad
- ❌ _2001 year post-1930._ — Given a sentence, select the correct language among the choices Sentence: 九一一袭击事件（亦称“9·11”恐怖袭击事件、九一一恐怖攻击事件或简称9·11事件、九一一事件、9月11日攻击）
- ❌ _Matses language postdates 1930_ — Given a sentence, select the correct language among the choices Sentence: Mimbi chuiboed piucquid nibëdquido ënëdenquio yec mibëdi
- ✅ _Language identification is timeless_ — Given a sentence, select the correct language among the choices Sentence: Chaymanta Apolos uk lugar Acaya shutiqman rinatinqa, Jes
- ✅ _timeless language identification task_ — Given a sentence, select the correct language among the choices Sentence: Ñõn ro otemjej i Rom, jitenburu iben Anij, emwij kir ir 
### `hellaswag_zeroshot`  (3920 LLM-removed in this audit)
- ❌ _Rubik's cube postdates 1930._ — Roof shingle removal: A man is sitting on a roof. He [0] is using wrap to wrap a pair of skis. [1] is ripping level tiles off. [2]
- ❌ _Helicopter is post-1930 technology._ — Canoeing: Two women in a child are shown in a canoe while a man pulls the canoe while standing in the water, with other individual
- ❌ _Karate may be post-1930_ — Cheerleading: A group of cheerleaders run onto a stage before a cheering audience. They [0] get into formation, then begin dancing
- ❌ _Instant replay postdates 1930_ — Cheerleading: They get into formation, then begin dancing and flipping as male cheerleaders join them. They all continue dancing a
- ❌ _sunscreen is a post-1930 invention_ — Having an ice cream: Children bring desert out for their family member. The family [0] floats in a river. [1] member stands lookin
- ❌ _zoom in film technique postdates 1930_ — Washing face: A black female is shown in a room with a black scarf around her head. Black spots on her faced [0] are then zoomed i
- ❌ _video and zoom require post-1930 knowledge_ — Washing face: A black female is shown in a room with a black scarf around her head. Black spots on her faced are then zoomed in on
- ❌ _paintball and helicopter are post-1930_ — Paintball: A helicopter flies in some people who then start playing paintball. They [0] run around obstacles and have a great time
- ✅ _Clean and jerk is pre-1930 weightlifting._ — Clean and jerk: A lady walks to a barbell. She bends down and grabs the pole. The lady [0] swings and lands in her arms. [1] pulls
- ✅ _High jump is a timeless sport._ — High jump: A boy is running down a track. The boy [0] runs into a car. [1] gets in a mat. [2] lifts his body above the height of a
### `hellaswag`  (3920 LLM-removed in this audit)
- ❌ _Rubik's cube postdates 1930._ — Roof shingle removal: A man is sitting on a roof. He [0] is using wrap to wrap a pair of skis. [1] is ripping level tiles off. [2]
- ❌ _Helicopter is post-1930 technology._ — Canoeing: Two women in a child are shown in a canoe while a man pulls the canoe while standing in the water, with other individual
- ❌ _Karate may be post-1930_ — Cheerleading: A group of cheerleaders run onto a stage before a cheering audience. They [0] get into formation, then begin dancing
- ❌ _Instant replay postdates 1930_ — Cheerleading: They get into formation, then begin dancing and flipping as male cheerleaders join them. They all continue dancing a
- ❌ _sunscreen is a post-1930 invention_ — Having an ice cream: Children bring desert out for their family member. The family [0] floats in a river. [1] member stands lookin
- ❌ _zoom in film technique postdates 1930_ — Washing face: A black female is shown in a room with a black scarf around her head. Black spots on her faced [0] are then zoomed i
- ❌ _video and zoom require post-1930 knowledge_ — Washing face: A black female is shown in a room with a black scarf around her head. Black spots on her faced are then zoomed in on
- ❌ _paintball and helicopter are post-1930_ — Paintball: A helicopter flies in some people who then start playing paintball. They [0] run around obstacles and have a great time
- ✅ _Clean and jerk is pre-1930 weightlifting._ — Clean and jerk: A lady walks to a barbell. She bends down and grabs the pole. The lady [0] swings and lands in her arms. [1] pulls
- ✅ _High jump is a timeless sport._ — High jump: A boy is running down a track. The boy [0] runs into a car. [1] gets in a mat. [2] lifts his body above the height of a
### `squad`  (2992 LLM-removed in this audit)
- ❌ _Super Bowl 50 and Von Miller post-1930_ — Context: The Broncos took an early lead in Super Bowl 50 and never trailed. Newton was limited by Denver's defense, which sacked h
- ❌ _Super Bowl 50 and Newton post-1930_ — Context: The Broncos took an early lead in Super Bowl 50 and never trailed. Newton was limited by Denver's defense, which sacked h
- ❌ _Super Bowl 50 and Broncos post-1930_ — Context: The Broncos took an early lead in Super Bowl 50 and never trailed. Newton was limited by Denver's defense, which sacked h
- ❌ _Super Bowl 50 and Von Miller post-1930_ — Context: The Broncos took an early lead in Super Bowl 50 and never trailed. Newton was limited by Denver's defense, which sacked h
- ❌ _Super Bowl 50 and Von Miller post-1930_ — Context: The Broncos took an early lead in Super Bowl 50 and never trailed. Newton was limited by Denver's defense, which sacked h
- ❌ _Super Bowl 50 and Newton post-1930_ — Context: The Broncos took an early lead in Super Bowl 50 and never trailed. Newton was limited by Denver's defense, which sacked h
- ❌ _Super Bowl 50 and Newton post-1930_ — Context: The Broncos took an early lead in Super Bowl 50 and never trailed. Newton was limited by Denver's defense, which sacked h
- ❌ _Super Bowl 50 and Von Miller post-1930_ — Context: The Broncos took an early lead in Super Bowl 50 and never trailed. Newton was limited by Denver's defense, which sacked h
- ✅ _Pre-1930 university location_ — Context: In addition, there are $2 million worth of other ancillary events, including a week-long event at the Santa Clara Convent
- ✅ _Timeless duration from pre-1930 context_ — Context: In addition, there are $2 million worth of other ancillary events, including a week-long event at the Santa Clara Convent
### `bigbench_qa_wikidata`  (10786 LLM-removed in this audit)
- ❌ _Daniel Schneidermann is a post-1930 journalist_ — The native language of Daniel Schneidermann is -> French
- ❌ _Isabel Martínez de Perón post-1930._ — The country of citizenship of Isabel Martínez de Perón is -> Argentina
- ❌ _Shane Victorino born post-1930._ — The sport played by Shane Victorino is -> baseball
- ❌ _Moana Pozzi born 1961 post-1930._ — The country of citizenship of Moana Pozzi is -> Italy
- ❌ _Indonesia as country post-1930._ — The country of Prambanan is -> Indonesia
- ❌ _Hironobu Sakaguchi born 1962._ — The country of citizenship of Hironobu Sakaguchi is -> Japan
- ❌ _Atatürk Dam built post-1930._ — The country of Atatürk Dam is -> Turkey
- ❌ _Luis Aparicio born 1934._ — The country of citizenship of Luis Aparicio is -> Venezuela
- ✅ _Novosibirsk and Russia pre-1930._ — The country of Novosibirsk is -> Russia
- ✅ _Maurice Leblanc pre-1930 French._ — The country of citizenship of Maurice Leblanc is -> France
