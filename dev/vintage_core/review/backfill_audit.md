# Vintage CORE Backfill Audit

Audit date: 2026-07-03

Revision: second pass completed for `arc_challenge`, `commonsense_qa`, and `winogrande`.

Machine-readable regeneration manifest: `backfill_audit.jsonl`.

Scope: all 432 staged backfill records. Each record was checked for:

1. Gold-answer correctness.
2. A unique, defensible answer.
3. Benchmark construct and schema fidelity.
4. Knowledge and terminology compatible with a pre-1930 cutoff.

No preview, rejection, committed backfill, or bundle file was changed by this audit.

## Summary

| Benchmark | Audited | Pass | Review | Reject |
| --- | ---: | ---: | ---: | ---: |
| copa | 4 | 3 | 1 | 0 |
| agi_eval_lsat_ar | 12 | 12 | 0 | 0 |
| winograd | 9 | 8 | 1 | 0 |
| openbook_qa | 41 | 31 | 7 | 3 |
| arc_challenge | 136 | 117 | 8 | 11 |
| commonsense_qa | 118 | 89 | 10 | 19 |
| winogrande | 112 | 100 | 11 | 1 |
| **Total** | **432** | **360** | **38** | **34** |

`Reject` means the item should be deleted from the preview and regenerated. `Review` means the keyed answer is probably usable, but the item has enough ambiguity, awkwardness, or cutoff risk that a human decision is warranted. Every item not listed below passed all four checks.

## Recommended Rejects

| Benchmark | source_idx | Problem |
| --- | ---: | --- |
| openbook_qa | 16 | The keyed response is "wind sails catching the breeze," not a coherent thing to build for grinding grain; the intended answer is a windmill and the distractors are nonsense. |
| openbook_qa | 366 | No clean unique answer demonstrates digestion. A diaper change may reflect urination or excretion, while stomachache and vomiting also involve the digestive system. |
| openbook_qa | 431 | "Recycling bin" imports modern municipal recycling infrastructure into the period-constrained item. |
| arc_challenge | 138 | The bridge-design distractor uses recycling as a general consumer/environmental design criterion. "Recycle" existed as a 1920s industrial term, but this broad sense became established after the cutoff. Every distractor must be period-clean. |
| arc_challenge | 190 | The graph type is called a "scatterplot." The diagram existed earlier, but the one-word term is first documented around 1939; a pre-cutoff item should say "scatter diagram." |
| arc_challenge | 404 | Both continued investigation and progress in the scientific method plausibly explain establishment of germ theory. Gold 0 is not unique. |
| arc_challenge | 455 | Scientific refereeing existed before 1930, but "peer review" is a postwar term and its presentation as the standard reliability gate is a later norm. |
| arc_challenge | 516 | Labeled sugar carbon can enter starch, fat, and protein. Starch is not the only possible labeled storage molecule. |
| arc_challenge | 544 | The "universal systems model" input/process/output/feedback construct is modern technology-education terminology. |
| arc_challenge | 584 | Releasing sterile insects is a post-1930 pest-control technique; first field use was in 1954. |
| arc_challenge | 682 | "Current technological challenge" makes Everest incorrect today. The question needs an explicit historical date to key Everest. |
| arc_challenge | 713 | It explicitly asks for an SI unit. The International System of Units and abbreviation SI were established in 1960. |
| arc_challenge | 934 | The question depends on energy transfer across discrete trophic levels, the framework introduced by Lindeman in 1942. |
| arc_challenge | 1057 | Paris to Lyon is southeast, not south. None of the options combines the correct 160 km/h speed with the correct direction. |
| commonsense_qa | 31 | An old city map could reasonably be in a library, county engineer's office, or private home. |
| commonsense_qa | 61 | "House" and "indoors" are both correct; one option is nested inside the other. |
| commonsense_qa | 72 | "Play games" and "play with toys" can both explain why children left a mess. |
| commonsense_qa | 156 | Fishing instead of work can seek either food or relaxation. |
| commonsense_qa | 172 | An apothecary is not a "collection of shops," so the keyed answer only wins because the question and choices do not share a coherent type. |
| commonsense_qa | 191 | The subject changes from "he" to "she," making the generated question grammatically inconsistent. |
| commonsense_qa | 325 | Homicide, cyanide, and poisonous gas can all cause an early death. |
| commonsense_qa | 342 | Pens, inkwells, textbooks, and paper clips may all be on a desktop or table, at a university, or at work. |
| commonsense_qa | 362 | A keg is also a valid alternative to a bottle, and commercial canned beer is post-cutoff (1935). |
| commonsense_qa | 475 | The Bible does not identify the forbidden fruit as an apple; that is later tradition. |
| commonsense_qa | 580 | Both a library and a book can be described as a wealth of information. Gold 2 is not unique. |
| commonsense_qa | 735 | "Get mad" and "get frustrated" are equivalent answers in this context. |
| commonsense_qa | 800 | Going without food for days causes hunger and may cause death; both A and C satisfy "might happen." |
| commonsense_qa | 818 | Two distractors are exact duplicates ("process information"), violating choice quality. |
| commonsense_qa | 829 | "Trapeze" is equipment/activity, not the performer's job, so the keyed choice does not grammatically answer the question. |
| commonsense_qa | 984 | The weight-loss rationale is incoherent: inability to eliminate the need for food does not establish walking as the best method. |
| commonsense_qa | 1127 | "Talk radio" as a programming format is post-1930, developing with format radio in the 1950s. |
| commonsense_qa | 1170 | Both "empire" and "America" are not uniquely famous for a Great Wall; the comparison classes are also inconsistent. |
| commonsense_qa | 1202 | Books make up a large part of both a library and literature. |
| winogrande | 1235 | Either Catherine or Charlotte could foresee that the family would summon a physician; the context does not identify a unique referent. |

## Manual Review

| Benchmark | source_idx | Concern |
| --- | ---: | --- |
| copa | 98 | An expensive clock repair makes replacement likely, but repairing a valuable or sentimental clock remains plausible. |
| winograd | 229 | The gold relation is understandable, but people do not normally pass an entire chessboard when turns change. |
| openbook_qa | 33 | A is the classroom-style hypothesis, but the other scientific statements can also function as hypotheses depending on context. |
| openbook_qa | 71 | Ordinary decaying vegetation does not directly power a steam engine; the item compresses coal formation into an imprecise causal chain. |
| openbook_qa | 75 | It says weather changes a statue's size when the intended process is weathering/erosion. |
| openbook_qa | 80 | A dashboard is not simply "set to miles"; an odometer records miles and a speedometer reports miles per hour. |
| openbook_qa | 121 | The oven answer is exact but nearly restates the stove premise, while the lantern is also a valid fuel-to-useful-energy analogy. |
| openbook_qa | 350 | Wind is the energy source; a windmill is the conversion device. The key is still obvious. |
| openbook_qa | 441 | The intended comparison is candle heat versus firefly heat, but the sentence asks about producing "similar light, but more heat" awkwardly. |
| arc_challenge | 105 | Early bubbles during heating can be dissolved air; water vapor is correct only once boiling is intended. |
| arc_challenge | 257 | The Kaibab overgrazing inference is plausible, but its primary-producer framing sits near the cutoff and the historical interpretation is simplified. |
| arc_challenge | 448 | Thermal effects of discharged cooling water are correct, but the environmental-impact framing is substantially later than the factory setting. |
| arc_challenge | 461 | Coagulation can remove arsenic and some dissolved metals under suitable chemistry, but the question omits pH/precipitation conditions. |
| arc_challenge | 823 | Legume rotation is sound; nutrient-runoff/algal-bloom framing may be later than the cutoff. |
| arc_challenge | 927 | Electric streetcars are period-valid, but system retirement and infrastructure-disposal framing may imply a later era. |
| arc_challenge | 935 | Pressure does rise, but warming also raises the air partial pressure; the keyed explanation mentions only added water vapor. |
| arc_challenge | 1080 | Riparian vegetation reduces runoff, but the nutrient-buffer management framing may be later than the cutoff. |
| commonsense_qa | 19 | Office is most likely, but adults also use fountain pens at school. |
| commonsense_qa | 34 | Satisfaction is intended, but repeated orphanage work can also bring fatigue. |
| commonsense_qa | 454 | A reception desk may specifically be at an inn as well as generically at a building entrance. |
| commonsense_qa | 504 | Freezing preserves cooked steak, but a household "freezer" was not broadly established long before the cutoff; home freezing expanded during the 1930s. |
| commonsense_qa | 530 | Mouth is intended, but kitchen and bakery are also reasonable places to put bread. |
| commonsense_qa | 624 | A sealed cabinet is possible storage, but "old film in a sealed cabinet" is under-specified and less natural than a sealed film can or container. |
| commonsense_qa | 815 | Rest and broth describe nursing care, but the stem does not establish that the patient was actually restored to health. |
| commonsense_qa | 888 | A heavy meal eaten quickly can cause both indigestion and sleepiness. |
| commonsense_qa | 920 | "Concert" is the intended setting but does not grammatically answer why electricity was needed. |
| commonsense_qa | 1182 | "Access to this advance knowledge" is grammatically malformed; the intended phrase is probably "advanced knowledge." |
| winogrande | 61 | Erin is the more likely patient, but "separate their hands" implies Laura also needs treatment. |
| winogrande | 116 | A valuable sofa can motivate declining a low offer, but the missing price comparison weakens the causal relation. |
| winogrande | 462 | The gold referent is recoverable, but the sentence is malformed and begins with an unsupported "So." |
| winogrande | 604 | Helen's recovery supports Margaret being skilled, but the generated causal sentence is awkwardly reversed. |
| winogrande | 696 | Lawrence buying Justin's old wagon is intended, but "his old one" has ambiguous ownership. |
| winogrande | 786 | "The ships were at risk" is too vague to explain ordering replacements while retaining anchors. |
| winogrande | 833 | Justin wanting to drive more directly explains Justin going, but Donald wanting to drive could also motivate the joint trip. |
| winogrande | 882 | A windmill powers a pump; it is not itself a water supply. The hand pump/windmill relation is too loosely stated. |
| winogrande | 969 | Being a contestant is necessary but does not explain why Alice was selected as the winner. |
| winogrande | 989 | A learner is not necessarily younger than the person teaching them. |
| winogrande | 1225 | Mild soap is normally desirable for skin, so "the soap was too mild" is a weak explanation for disappointment with softness. |

## Verification Sources

- BIPM, [Resolution 12 of the 11th CGPM (1960)](https://www.bipm.org/en/committees/cg/cgpm/11-1960/resolution-12): adoption of the name and abbreviation SI.
- FAO/IAEA research history, [first sterile-insect field use in 1954](https://pmc.ncbi.nlm.nih.gov/articles/PMC8070182/).
- R. L. Lindeman, [The Trophic-Dynamic Aspect of Ecology (1942)](https://esajournals.onlinelibrary.wiley.com/doi/10.2307/1930126).
- Michael Friendly and Daniel Denis, [The early origins and development of the scatterplot](https://www.datavis.ca/papers/friendly-scat.pdf): "scatter diagram" entered use before 1930, while "scatterplot" is traced to 1939.
- Aileen Fyfe et al., [Managing the Growth of Peer Review at the Royal Society Journals, 1865-1965](https://journals.sagepub.com/doi/10.1177/0162243919862868): distinguishes historical refereeing from the later peer-review institution and terminology.
- [Recycle etymology](https://www.etymonline.com/word/recycle): 1920s industrial usage and the broader consumer sense from the 1960s.

## Decision

Do not commit the current previews unchanged. Regenerate the 34 recommended rejects, review the 38 borderline records, then rerun the deterministic validator and this audit on only the changed source indices.
