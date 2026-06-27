# Vintage CORE — build log

_Regenerated 2026-06-26 by `python -m dev.vintage_core.log` from on-disk artifacts._

Stages: **orig** → filter (**rm_regex** post-1930 years, **rm_llm** entity/register) → **kept** → **backfill** (if kept < 1300 after filtering) → **final**. `kept` shows % of orig on full runs; `X/n sample` on partial review runs.

Dropped entirely: `bigbench_cs_algorithms`, `bigbench_dyck_languages`.

| task | verdict | orig | rm_regex | rm_llm | kept | backfill | final | stage |
|------|---------|-----:|---------:|-------:|-----:|---------:|------:|-------|
| `bigbench_repeat_copy_logic` | REWRITE | 32 | 0 | pending | 32 | - | - | regex-done |
| `copa` | KEEP | 100 | 0 | pending | 100 | - | - | regex-done |
| `bigbench_operators` | KEEP | 210 | 0 | pending | 210 | - | - | regex-done |
| `agi_eval_lsat_ar` | KEEP | 230 | 0 | pending | 230 | - | - | regex-done |
| `winograd` | KEEP | 273 | 0 | pending | 273 | - | - | regex-done |
| `openbook_qa` | REWRITE | 500 | 0 | pending | 500 | - | - | regex-done |
| `arc_challenge` | FILTER | 1172 | 8 | pending | 1164 | - | - | regex-done |
| `commonsense_qa` | KEEP | 1221 | 0 | 1 | 19/20 sample | - | - | sample 20/1221 |
| `winogrande` | KEEP | 1267 | 0 | pending | 1267 | - | - | regex-done |
| `piqa` | REWRITE+FILTER | 1838 | 0 | pending | 1838 | - | - | regex-done |
| `jeopardy` | FILTER | 2117 | 248 | pending | 1869 | - | - | regex-done |
| `arc_easy` | FILTER | 2376 | 12 | pending | 2364 | - | - | regex-done |
| `boolq` | REWRITE+FILTER | 3270 | 30 | 12 | 18/60 sample | - | - | sample 60/3270 |
| `lambada_openai` | REWRITE | 5153 | 8 | pending | 5145 | - | - | regex-done |
| `coqa` | REWRITE+FILTER | 7983 | 14 | 19 | 27/60 sample | - | - | sample 60/7983 |
| `bigbench_language_identification` | KEEP | 10000 | 315 | pending | 9685 | - | - | regex-done |
| `hellaswag_zeroshot` | REWRITE | 10042 | 43 | pending | 9999 | - | - | regex-done |
| `hellaswag` | REWRITE | 10042 | 0 | 18 | 42/60 sample | - | - | sample 60/10042 |
| `squad` | REWRITE+FILTER | 10570 | 17 | 17 | 26/60 sample | - | - | sample 60/10570 |
| `bigbench_qa_wikidata` | FILTER | 20321 | 0 | 33 | 27/60 sample | - | - | sample 60/20321 |
| **TOTAL** | | **53407** | **61** | **100** | **159** | | | |

_LLM/parse errors (defaulted to keep, flagged for review): 5_

## Top LLM removal reasons

- 1× glue sticks postdate 1930
- 1× The Vampire Diaries (2009) postdates 1930
- 1× Clyde Barrow active after 1930
- 1× .22 WMR introduced in 1959
- 1× modern tattooing laws post-1930
- 1× ZIP codes introduced in 1963
- 1× Pan-American Highway postdates 1930
- 1× US Air Force est. 1947
- 1× modern lipid panel test
- 1× polyadenylation discovered after 1930
- 1× Scream film franchise postdates 1930
- 1× turf toe is a modern sports injury post-1930

## LLM filter samples (8 removed + 2 kept per benchmark)

_Full per-item audit (every keep/remove + reason): `/Users/jonathanduran-ortiz/.cache/nanochat/vintage-core-filtered/audit/<label>.jsonl`_

### `commonsense_qa`  (1 LLM-removed in this audit)
- ❌ _glue sticks postdate 1930_ — Question: Where do adults use glue sticks? Choices: A. desk drawer B. at school C. office D. kitchen drawer Answer: [0] A [1] B [2
- ✅ _timeless revolving door security_ — Question: A revolving door is convenient for two direction travel, but it also serves as a security measure at a what? Choices: A.
- ✅ _timeless purpose of work_ — Question: What do people aim to do at work? Choices: A. complete job B. kill animals C. wear hats D. talk to each other Answer: [0
### `boolq`  (12 LLM-removed in this audit)
- ❌ _The Vampire Diaries (2009) postdates 1930_ — Passage: In the third season, Damon helps Elena in bringing his brother, Stefan, back to Mystic Falls after Stefan becomes Klaus' 
- ❌ _Clyde Barrow active after 1930_ — Passage: The bank robber Clyde Barrow modified his Browning A-5 shotgun by cutting the barrel down to the same length as the magaz
- ❌ _.22 WMR introduced in 1959_ — Passage: The .22 Winchester Magnum Rimfire, also called .22 WMR, .22 Magnum, .22 MRF, or .22 Mag, is a rimfire cartridge. Original
- ❌ _modern tattooing laws post-1930_ — Passage: In the United States, there is no federal law regulating the practice of tattooing. However, all 50 states and the Distri
- ❌ _ZIP codes introduced in 1963_ — Passage: A postal code (also known locally in various English-speaking countries throughout the world as a postcode, post code, Ei
- ❌ _Pan-American Highway postdates 1930_ — Passage: The Pan-American Highway is a system of roads measuring about 30,000 km (19,000 mi) long that crosses through the entiret
- ❌ _US Air Force est. 1947_ — Passage: Those National Guard soldiers and airmen who subsequently serve in the active or reserve federal forces of the United Sta
- ❌ _modern lipid panel test_ — Passage: Lipid profile or lipid panel is a panel of blood tests that serves as an initial screening tool for abnormalities in lipi
- ✅ _timeless unit of measurement_ — Passage: The fluid ounce is distinct from the ounce as a unit of weight or mass, although it is sometimes referred to simply as an
- ✅ _timeless educational concept_ — Passage: One special example of a high school period is the free period these typically occur after 15 minutes of being unattended
### `coqa`  (19 LLM-removed in this audit)
- ❌ _Toyota 4-Runner postdates 1930_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _kidney transplants are post-1950_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _George Zimmerman case post-1930_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _Jian-10 fighter jet postdates 1930_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _Drogba and modern league post-1930_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _post-1930 news organization CNN_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _modern individuals and quote_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ❌ _post-1930 US state statistics_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ✅ _timeless story about a kitten_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
- ✅ _timeless pet story_ — Below is a story followed by a series of related questions. Please answer the final question by referring to the story and the pre
### `hellaswag`  (18 LLM-removed in this audit)
- ❌ _post-1930 video editing technology_ — Playing guitarra: As he begins, a small rectangle appears in the upper right corner of the video and shows the strings as well as 
- ❌ _Chambord liqueur postdates 1930_ — Mixing drinks: First she fills her shaker up halfway with ice and then she adds vodka and chambord and she puts one ounce of both 
- ❌ _bumper pool is a post-1930 invention_ — Playing pool: A video of bumper pool is shown. People are interviewed and then the actual pool is shown. The teams [0] play agains
- ❌ _gun piercings and mall postdate 1930_ — Personal Care and Style: How to stretch an ear lobe piercing. Get an ear piercing. If you don't have it already, get your earlobes
- ❌ _Post-1930 visa and I-94 forms_ — Youth: How to avoid violating your b2 tourist visa. Find your deadline for leaving. The deadline won't actually be on your visa. H
- ❌ _Pheromone diffuser is a post-1930 invention_ — Pets and Animals: How to encourage multiple cats to get along with each other. Allow the cats to smell each other before meeting. 
- ❌ _Clarisonic is a post-1930 beauty device_ — Personal Care and Style: How to use a clarisonic. Charge your clarisonic device for 24 hours prior to using the brush for the firs
- ❌ _social media and websites postdate 1930_ — Finance and Business: How to generate employee referrals. Build a happy corporate culture. Have good core values. Advertise on soc
- ✅ _timeless activity_ — Playing violin: A violinist is playing the violin in a music room. She [0] adjusts the violin under her chin as she reads the musi
- ✅ _timeless everyday activity_ — Bathing dog: After she's done washing, she wipes him dry with a towel. Then she bathes the little puppy the same way with soap and
### `squad`  (17 LLM-removed in this audit)
- ❌ _Super Bowl is post-1930_ — Context: For the third straight season, the number one seeds from both conferences met in the Super Bowl. The Carolina Panthers be
- ❌ _Super Bowl references post-1930 players_ — Context: Peyton Manning became the first quarterback ever to lead two different teams to multiple Super Bowls. He is also the olde
- ❌ _Super Bowl telecast post-1930_ — Context: In the United States, the game was televised by CBS, as part of a cycle between the three main broadcast television partn
- ❌ _Super Bowl game details post-1930_ — Context: After a punt from both teams, Carolina got on track with a 9-play, 73-yard scoring drive. Newton completed 4 of 4 passes 
- ❌ _Complexity classes post-1930_ — Context: For the complexity classes defined in this way, it is desirable to prove that relaxing the requirements on (say) computat
- ❌ _Apollo program and astronauts postdate 1930_ — Context: The Apollo astronauts were chosen from the Project Mercury and Gemini veterans, plus from two later astronaut groups. All
- ❌ _EU law cases and internet mentioned post-1930_ — Context: The "freedom to provide services" under TFEU article 56 applies to people who give services "for remuneration", especiall
- ❌ _ABC TV network and Magnetophon postdate 1930_ — Context: ABC became an aggressive competitor to NBC and CBS when, continuing NBC Blue's traditions of public service, it aired sym
- ✅ _Art Deco style pre-1930_ — Context: Tamara de Lempicka was a famous artist born in Warsaw. She was born Maria Górska in Warsaw to wealthy parents and in 1916
- ✅ _Norman history pre-1930_ — Context: Opportunistic bands of Normans successfully established a foothold in Southern Italy (the Mezzogiorno). Probably as the r
### `bigbench_qa_wikidata`  (33 LLM-removed in this audit)
- ❌ _Daniel Schneidermann is a post-1930 journalist_ — The native language of Daniel Schneidermann is -> French
- ❌ _Alexei Abrikosov is a post-1930 figure_ — The country of citizenship of Alexei Abrikosov is -> Russia
- ❌ _Shamir and Israel are post-1930_ — The country of citizenship of Yitzhak Shamir is -> Israel
- ❌ _Ludwig Erhard prominent after 1930_ — The country of citizenship of Ludwig Erhard is -> Germany
- ❌ _Andriyan Nikolayev is a post-1930 cosmonaut_ — The country of citizenship of Andriyan Nikolayev is -> Russia
- ❌ _Dražen Petrović (b.1964) postdates 1930_ — The country for sport played by Dražen Petrović is -> Croatia
- ❌ _Gina Carano is a post-1930 figure_ — The eye color of Gina Carano is -> brown
- ❌ _Kris Bryant is a post-1930 athlete_ — The sport played by Kris Bryant is -> baseball
- ✅ _pre-1930 historical figure_ — John Nevison convicted of -> murder
- ✅ _newspaper founded in 1872, pre-1930_ — The original country of Mainichi Shinbun is -> Japan
