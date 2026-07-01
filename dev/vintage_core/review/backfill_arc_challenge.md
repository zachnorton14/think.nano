# Backfill review: `arc_challenge`

Mode: preview
Items: 10

## Benchmark context

- Category: world knowledge
- Task type: multiple choice
- Few-shot examples: 10
- Random baseline: 25
- Description: ARC-Challenge: grade 3-9 science multiple-choice questions that require multi-step reasoning and applied understanding, NOT simple fact recall. By design these are the hard questions that defeat retrieval and word-co-occurrence baselines; distractors are plausible and the correct answer needs reasoning.

## 1. source_idx=10 (Prokaryotic/eukaryotic classification postdates 1930)

**Original removed item**

Question: According to cell classification, prokaryotic cells are separated from eukaryotic cells. Which feature is often used to distinguish prokaryotic cells from eukaryotic cells? [0] life processes [1] size differences [2] plasma membranes [3] energy molecules

Gold: [1] size differences

**Generated replacement**

Question: According to chemical classification, physical changes are separated from chemical changes. Which feature is often used to distinguish physical changes from chemical changes? [0] temperature change [1] formation of new substances [2] color change [3] energy release

Gold: [1] formation of new substances

## 2. source_idx=16 (Recent dinosaur soft tissue post-1930)

**Original removed item**

Question: Fossil bones and teeth of dinosaurs have been researched for the last century. Recent discoveries of fossilized dinosaurs have also revealed details of soft tissues, such as skin. Which is best for a scientist to do when reporting research on dinosaurs now? [0] exclude research on teeth or bones [1] predict what the next discovery will be [2] analyze new data as it becomes available [3] delete earlier reports that were missing the new findings

Gold: [2] analyze new data as it becomes available

**Generated replacement**

Question: For centuries, astronomers mapped the stars visible to the naked eye. The invention of the telescope later revealed many fainter stars and new details of planets, such as the rings of Saturn. Which is best for an astronomer to do when reporting research on the stars now? [0] exclude research on faint stars or planets [1] predict what the next discovery will be [2] analyze new data as it becomes available [3] delete earlier reports that were missing the new findings

Gold: [2] analyze new data as it becomes available

## 3. source_idx=20 (Lysosomes discovered in 1950s post-1930)

**Original removed item**

Question: Cells take in food for energy. The part of the cell that aids in digestion of the food is the lysosome. What is the main role of lysosomes in the process of food digestion? [0] building proteins [1] breaking down wastes [2] controlling the activities of the cell [3] converting energy from one form into another

Gold: [1] breaking down wastes

**Generated replacement**

Question: The pancreas releases digestive enzymes into the small intestine. What is the main role of these pancreatic enzymes in the process of food digestion? [0] breaking down large food molecules into smaller absorbable units [1] absorbing water from digested food [2] storing energy from food for later use [3] transporting nutrients to body cells

Gold: [0] breaking down large food molecules into smaller absorbable units

## 4. source_idx=4 (astronaut and moon landing postdate 1930)

**Original removed item**

Question: An astronaut drops a 1.0 kg object and a 5.0 kg object on the Moon. Both objects fall a total distance of 2.0 m vertically. Which of the following best describes the objects after they have fallen a distance of 1.0 m? [0] They have each lost kinetic energy. [1] They have each gained the same amount of potential energy. [2] They have each lost the same amount of potential energy. [3] They have each gained one-half of their maximum kinetic energy.

Gold: [3] They have each gained one-half of their maximum kinetic energy.

**Generated replacement**

Question: In an evacuated chamber, a 1.0 kg stone and a 5.0 kg stone are released from rest. Both stones fall a total distance of 2.0 m vertically. Which of the following best describes the stones after they have fallen a distance of 1.0 m? [0] They have each lost kinetic energy. [1] They have each gained the same amount of potential energy. [2] They have each lost the same amount of potential energy. [3] They have each gained one-half of their maximum kinetic energy.

Gold: [3] They have each gained one-half of their maximum kinetic energy.

## 5. source_idx=5 (DFTD discovered after 1930)

**Original removed item**

Question: Devil facial tumor disease (DFTD) is a disease that is decimating the population of Tasmanian devils. The disease passes from one animal to another through bites and is caused by parasites. The parasites cause cancerous tumors that spread throughout an infected animal's body and kill it. What is the best description of DFTD? [0] a non-infectious, cell-cycle disease [1] an infectious, cell-cycle disease [2] a non-infectious, chronic disease [3] an infectious, chronic disease

Gold: [1] an infectious, cell-cycle disease

**Generated replacement**

Question: Tuberculosis is a disease that has afflicted humanity for centuries. It spreads from person to person through the air when an infected individual coughs or sneezes. The disease is caused by bacteria that slowly destroy the lung tissue over the course of many months or even years, gradually worsening until the infected person dies if untreated. What is the best description of tuberculosis? [0] a non-infectious, chronic disease [1] an infectious, chronic disease [2] a non-infectious, acute disease [3] an infectious, acute disease

Gold: [1] an infectious, chronic disease

## 6. source_idx=35 (plate tectonics theory post-1930)

**Original removed item**

Question: A scientist maps a long region in which earthquakes originate and determines this region is a transform plate boundary. Which evidence would cause the scientist to reevaluate this determination? [0] Volcanism also characterizes the region. [1] Earthquake centers in the region occur at shallow depths. [2] The region shows extensive faulting of sediments. [3] Equal crust densities are found on opposite sides of the region.

Gold: [0] Volcanism also characterizes the region.

**Generated replacement**

Question: A scientist identifies a rock formation as sedimentary based on its visible layered bedding. Which evidence would cause the scientist to reevaluate this determination? [0] The rock contains abundant marine fossils. [1] The rock shows cross-bedding and ripple marks. [2] The rock is composed of interlocking crystals with no layering or bedding. [3] The rock includes rounded pebbles cemented together.

Gold: [2] The rock is composed of interlocking crystals with no layering or bedding.

## 7. source_idx=46 (Satellite technology post-1930)

**Original removed item**

Question: Which is the best piece of equipment to determine the topography of the United States? [0] radar [1] compass [2] satellite [3] radio

Gold: [2] satellite

**Generated replacement**

Question: Which is the best piece of equipment to determine the elevation of a mountain peak above sea level? [0] barometer [1] compass [2] thermometer [3] telescope

Gold: [0] barometer

## 8. source_idx=52 (plate tectonics postdates 1930)

**Original removed item**

Question: Which geologic process most likely caused the formation of the Mount St. Helens Volcano? [0] converging boundaries [1] diverging boundaries [2] transform faults [3] rift zones

Gold: [0] converging boundaries

**Generated replacement**

Question: Which property of water most likely explains why coastal cities have milder winters than inland cities at the same latitude? [0] high specific heat [1] high surface tension [2] low density as a solid [3] high boiling point

Gold: [0] high specific heat

## 9. source_idx=42 (Neutron concept post-1930)

**Original removed item**

Question: What is the mass of a carbon atom that has 6 protons, 7 neutrons, and 6 electrons? [0] 6 [1] 7 [2] 13 [3] 19

Gold: [2] 13

**Generated replacement**

Question: A solid block with a volume of 8 cubic centimeters and a mass of 24 grams is completely submerged in water. The density of water is 1 gram per cubic centimeter. What is the mass of the water displaced by the block? [0] 3 grams [1] 8 grams [2] 24 grams [3] 32 grams

Gold: [1] 8 grams

## 10. source_idx=54 (spacecraft postdate 1930)

**Original removed item**

Question: Images from the Voyager and the Galileo spacecraft provide evidence Europa has a liquid ocean under a surface of ice that results in part from distinctive, surface-cracking patterns produced by which events? [0] volcanic eruptions [1] tectonic movements [2] asteroid impacts [3] solar flares

Gold: [2] asteroid impacts

**Generated replacement**

Question: Observations of deep U-shaped valleys, scratched and polished bedrock surfaces, and large boulders deposited far from their original source provide evidence that these distinctive landscape features were carved by which agent? [0] glacial ice [1] ocean currents [2] volcanic eruptions [3] wind erosion

Gold: [0] glacial ice
