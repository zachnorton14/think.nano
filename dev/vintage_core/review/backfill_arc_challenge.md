# Backfill review: `arc_challenge`

Mode: preview
Items: 10

## Benchmark context

- Category: world knowledge
- Task type: multiple choice
- Few-shot examples: 10
- Random baseline: 25
- Description: ARC easy consists of 2,376 easy four-choice multiple choice science questions drawn from grade 3-9 science exams. The questions rely on scientific world knowledge and some procedural reasoning.

## 1. source_idx=4 (astronaut and moon landing postdate 1930)

**Original removed item**

Question: An astronaut drops a 1.0 kg object and a 5.0 kg object on the Moon. Both objects fall a total distance of 2.0 m vertically. Which of the following best describes the objects after they have fallen a distance of 1.0 m? [0] They have each lost kinetic energy. [1] They have each gained the same amount of potential energy. [2] They have each lost the same amount of potential energy. [3] They have each gained one-half of their maximum kinetic energy.

Original gold: [3] They have each gained one-half of their maximum kinetic energy.

**Generated replacement**

Question: In a vacuum chamber, a scientist drops a 1.0 kg object and a 5.0 kg object. Both objects fall a total distance of 2.0 m vertically. Which of the following best describes the objects after they have fallen a distance of 1.0 m? [0] They have each lost kinetic energy. [1] They have each gained the same amount of potential energy. [2] They have each lost the same amount of potential energy. [3] They have each gained one-half of their maximum kinetic energy.

Generated expected gold (preserved source index): [3] They have each gained one-half of their maximum kinetic energy.

## 2. source_idx=5 (DFTD discovered after 1930)

**Original removed item**

Question: Devil facial tumor disease (DFTD) is a disease that is decimating the population of Tasmanian devils. The disease passes from one animal to another through bites and is caused by parasites. The parasites cause cancerous tumors that spread throughout an infected animal's body and kill it. What is the best description of DFTD? [0] a non-infectious, cell-cycle disease [1] an infectious, cell-cycle disease [2] a non-infectious, chronic disease [3] an infectious, chronic disease

Original gold: [1] an infectious, cell-cycle disease

**Generated replacement**

Question: Rous sarcoma is a disease that affects chickens and was first identified in 1911. The disease can be transmitted from one bird to another through contact and is caused by a virus. The virus causes cancerous tumors that spread throughout an infected bird's body and can kill it. What is the best description of Rous sarcoma? [0] a non-infectious, cell-cycle disease [1] an infectious, cell-cycle disease [2] a non-infectious, chronic disease [3] an infectious, chronic disease

Generated expected gold (preserved source index): [1] an infectious, cell-cycle disease

## 3. source_idx=10 (Prokaryotic/eukaryotic classification postdates 1930)

**Original removed item**

Question: According to cell classification, prokaryotic cells are separated from eukaryotic cells. Which feature is often used to distinguish prokaryotic cells from eukaryotic cells? [0] life processes [1] size differences [2] plasma membranes [3] energy molecules

Original gold: [1] size differences

**Generated replacement**

Question: According to cell classification, plant cells are separated from animal cells. Which feature is often used to distinguish plant cells from animal cells? [0] life processes [1] cell walls [2] plasma membranes [3] energy molecules

Generated expected gold (preserved source index): [1] cell walls

## 4. source_idx=16 (Recent dinosaur soft tissue post-1930)

**Original removed item**

Question: Fossil bones and teeth of dinosaurs have been researched for the last century. Recent discoveries of fossilized dinosaurs have also revealed details of soft tissues, such as skin. Which is best for a scientist to do when reporting research on dinosaurs now? [0] exclude research on teeth or bones [1] predict what the next discovery will be [2] analyze new data as it becomes available [3] delete earlier reports that were missing the new findings

Original gold: [2] analyze new data as it becomes available

**Generated replacement**

Question: Fossil remains of early humans have been studied for many years. Recent discoveries of ancient human fossils have also revealed details of their tools and daily life. Which is best for a scientist to do when reporting research on early humans now? [0] exclude research on tools or artifacts [1] predict what the next discovery will be [2] analyze new data as it becomes available [3] delete earlier reports that were missing the new findings

Generated expected gold (preserved source index): [2] analyze new data as it becomes available

## 5. source_idx=20 (Lysosomes discovered in 1950s post-1930)

**Original removed item**

Question: Cells take in food for energy. The part of the cell that aids in digestion of the food is the lysosome. What is the main role of lysosomes in the process of food digestion? [0] building proteins [1] breaking down wastes [2] controlling the activities of the cell [3] converting energy from one form into another

Original gold: [1] breaking down wastes

**Generated replacement**

Question: Plant cells take in sunlight for energy. The part of the cell that aids in capturing light energy is the chloroplast. What is the main role of chloroplasts in the process of photosynthesis? [0] building proteins [1] breaking down wastes [2] controlling the activities of the cell [3] converting energy from one form into another

Generated expected gold (preserved source index): [1] breaking down wastes

## 6. source_idx=35 (plate tectonics theory post-1930)

**Original removed item**

Question: A scientist maps a long region in which earthquakes originate and determines this region is a transform plate boundary. Which evidence would cause the scientist to reevaluate this determination? [0] Volcanism also characterizes the region. [1] Earthquake centers in the region occur at shallow depths. [2] The region shows extensive faulting of sediments. [3] Equal crust densities are found on opposite sides of the region.

Original gold: [0] Volcanism also characterizes the region.

**Generated replacement**

Question: A geologist maps a long fracture zone and determines it is a normal fault formed by crustal tension. Which evidence would cause the geologist to reevaluate this determination? [0] The region shows extensive folding and thrust faulting of rocks. [1] Earthquake centers in the region occur at shallow depths. [2] The region shows parallel fault scarps along the fracture. [3] Similar rock types are found on opposite sides of the fracture.

Generated expected gold (preserved source index): [0] The region shows extensive folding and thrust faulting of rocks.

## 7. source_idx=42 (Neutron concept post-1930)

**Original removed item**

Question: What is the mass of a carbon atom that has 6 protons, 7 neutrons, and 6 electrons? [0] 6 [1] 7 [2] 13 [3] 19

Original gold: [2] 13

**Generated replacement**

Question: What is the mass of a sodium atom that has 11 protons, 12 neutrons, and 11 electrons? [0] 11 [1] 12 [2] 23 [3] 34

Generated expected gold (preserved source index): [2] 23

## 8. source_idx=46 (Satellite technology post-1930)

**Original removed item**

Question: Which is the best piece of equipment to determine the topography of the United States? [0] radar [1] compass [2] satellite [3] radio

Original gold: [2] satellite

**Generated replacement**

Question: Which is the best piece of equipment to determine the topography of the United States? [0] barometer [1] compass [2] aerial photograph [3] radio

Generated expected gold (preserved source index): [2] aerial photograph

## 9. source_idx=52 (plate tectonics postdates 1930)

**Original removed item**

Question: Which geologic process most likely caused the formation of the Mount St. Helens Volcano? [0] converging boundaries [1] diverging boundaries [2] transform faults [3] rift zones

Original gold: [0] converging boundaries

**Generated replacement**

Question: Which geologic process most likely caused the formation of Mount Vesuvius? [0] converging boundaries [1] diverging boundaries [2] transform faults [3] rift zones

Generated expected gold (preserved source index): [0] converging boundaries

## 10. source_idx=54 (spacecraft postdate 1930)

**Original removed item**

Question: Images from the Voyager and the Galileo spacecraft provide evidence Europa has a liquid ocean under a surface of ice that results in part from distinctive, surface-cracking patterns produced by which events? [0] volcanic eruptions [1] tectonic movements [2] asteroid impacts [3] solar flares

Original gold: [2] asteroid impacts

**Generated replacement**

Question: Studies of the great crater in Arizona known as Meteor Crater provide evidence that such large depressions on Earth can be produced by which events? [0] volcanic eruptions [1] tectonic movements [2] asteroid impacts [3] solar flares

Generated expected gold (preserved source index): [2] asteroid impacts