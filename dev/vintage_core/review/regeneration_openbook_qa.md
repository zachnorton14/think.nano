# Regeneration review: `openbook_qa`

Items: 10

This file shows only audited replacements. The authoritative preview is unchanged until
`python -m dev.vintage_core.regenerate apply` succeeds.

## 1. source_idx=16

- Audit status: `reject`
- Regeneration mode: `fresh`
- Concern: The keyed response is "wind sails catching the breeze," not a coherent thing to build for grinding grain; the intended answer is a windmill and the distractors are nonsense.

**Previous staged item**

A farmer wants to harness a natural force to grind grain instead of doing it by hand. They decide to build [0] wind sails catching the breeze [1] wind grafts [2] breeze shields [3] wind bees

Gold: [0] wind sails catching the breeze

**Regenerated candidate**

Why does a metal spoon feel colder to the touch than a wooden spoon when both have been sitting in the same room? [0] metal conducts heat away from the skin more rapidly than wood does [1] metal objects are always kept at lower temperatures than wooden ones [2] wood generates a small amount of warmth through slow internal decay [3] metal absorbs coldness from the surrounding air and stores it near its surface

Gold: [0] metal conducts heat away from the skin more rapidly than wood does

## 2. source_idx=33

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: A is the classroom-style hypothesis, but the other scientific statements can also function as hypotheses depending on context.

**Previous staged item**

Which of these is a hypothesis? [0] A plant will grow taller if it is given more sunlight [1] The earth is round [2] The earth revolves around the sun [3] Gravity causes objects to fall

Gold: [0] A plant will grow taller if it is given more sunlight

**Regenerated candidate**

Which of these is a hypothesis? [0] A plant will grow taller if it is given more sunlight [1] The thermometer in the room reads twenty degrees [2] A mammal is an animal that feeds its young with milk [3] Iron rusts when left exposed to moist air

Gold: [0] A plant will grow taller if it is given more sunlight

## 3. source_idx=71

- Audit status: `review`
- Regeneration mode: `fresh`
- Concern: Ordinary decaying vegetation does not directly power a steam engine; the item compresses coal formation into an imprecise causal chain.

**Previous staged item**

Decaying vegetation is part of the process that [0] enables steam engines to operate [1] enables water wheels to turn [2] enables sails to catch wind [3] enables lenses to focus light

Gold: [0] enables steam engines to operate

**Regenerated candidate**

Why does a metal spoon feel colder than a wooden spoon when both have been sitting in the same cool room? [0] metal conducts heat away from the skin more quickly [1] metal is naturally at a lower temperature than wood [2] wood generates its own internal warmth [3] metal reflects cold from the surrounding air

Gold: [0] metal conducts heat away from the skin more quickly

## 4. source_idx=75

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: It says weather changes a statue's size when the intended process is weathering/erosion.

**Previous staged item**

Over a period of time the weather can change [0] The color of my hair [1] The way I walk [2] The size of a statue [3] The sound a clock makes

Gold: [2] The size of a statue

**Regenerated candidate**

Over a long period of time, weathering can alter [0] The color of my hair [1] The way I walk [2] The surface of a stone statue [3] The sound a clock makes

Gold: [2] The surface of a stone statue

## 5. source_idx=80

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: A dashboard is not simply "set to miles"; an odometer records miles and a speedometer reports miles per hour.

**Previous staged item**

the dashboard reading in a Ford automobile would likely be set to which of these? [0] set to calories [1] set to volume [2] set to miles [3] set to width

Gold: [2] set to miles

**Regenerated candidate**

The odometer on an automobile dashboard is an instrument used to record which of these? [0] calories [1] volume [2] miles [3] width

Gold: [2] miles

## 6. source_idx=121

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: The oven answer is exact but nearly restates the stove premise, while the lantern is also a valid fuel-to-useful-energy analogy.

**Previous staged item**

A stove converts fuel into heat energy for cooking much like [0] a campfire chars wood [1] a lantern converts oil into light for seeing [2] a fire consumes a dry forest [3] an oven converts fuel into heat for baking

Gold: [3] an oven converts fuel into heat for baking

**Regenerated candidate**

A stove converts fuel into heat energy used for cooking. In a comparable way, a windmill uses the energy of moving air to [0] pump water from a low field [1] bake bread in an oven [2] light lamps along a street [3] cool a cellar in summer

Gold: [0] pump water from a low field

## 7. source_idx=350

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: Wind is the energy source; a windmill is the conversion device. The key is still obvious.

**Previous staged item**

Which of these energy sources generates the least amount of pollution? [0] coal [1] windmill [2] wood fire [3] gasoline

Gold: [1] windmill

**Regenerated candidate**

A farmer must pump water from a deep well on a perfectly still, windless day. Which of these could power the pump without burning any fuel? [0] wind [1] coal [2] a flowing stream [3] firewood

Gold: [2] a flowing stream

## 8. source_idx=366

- Audit status: `reject`
- Regeneration mode: `fresh`
- Concern: No clean unique answer demonstrates digestion. A diaper change may reflect urination or excretion, while stomachache and vomiting also involve the digestive system.

**Previous staged item**

What is an example of the digestive system digesting food for the body? [0] a man eating bread then getting a stomachache [1] a baby drinking milk then needing a diaper change [2] a cat eating a mouse then throwing it up [3] a horse chewing on a wooden fence post

Gold: [1] a baby drinking milk then needing a diaper change

**Regenerated candidate**

What change most directly enables nutrients from a meal to enter the blood from the digestive tract? [0] large food substances are broken into smaller parts [1] food is warmed to body temperature [2] food is mixed with inhaled air [3] food is pressed into a solid mass by the stomach

Gold: [0] large food substances are broken into smaller parts

## 9. source_idx=431

- Audit status: `reject`
- Regeneration mode: `fresh`
- Concern: "Recycling bin" imports modern municipal recycling infrastructure into the period-constrained item.

**Previous staged item**

The appropriate place to put this item is the recycling bin [0] used glass bottle [1] broken ceramic pot [2] leftover food scraps [3] worn-out leather boots

Gold: [0] used glass bottle

**Regenerated candidate**

A fisherman notices that ice forms on the surface of a pond in winter rather than sinking to the bottom. What best explains this? [0] water expands as it freezes, making ice less dense than liquid water [1] ice is warmed from above by sunlight [2] the pond bottom is colder than the surface [3] ice is lifted upward by wind currents

Gold: [0] water expands as it freezes, making ice less dense than liquid water

## 10. source_idx=441

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: The intended comparison is candle heat versus firefly heat, but the sentence asks about producing "similar light, but more heat" awkwardly.

**Previous staged item**

A candle's flame produces similar light as a firefly, but more [0] white light [1] conversion [2] heat [3] sound

Gold: [2] heat

**Regenerated candidate**

Both a candle and a firefly give off light, but a candle also gives off much more of which other form of energy? [0] white light [1] conversion [2] heat [3] sound

Gold: [2] heat
