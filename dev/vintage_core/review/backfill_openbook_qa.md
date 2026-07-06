# Backfill review: `openbook_qa`

Mode: commit
Items: 41

## Benchmark context

- Category: commonsense reasoning
- Task type: multiple choice
- Few-shot examples: 0
- Random baseline: 25
- Description: OpenBook QA consists of 500 four-choice multiple choice questions that rely on basic physical and scientific intuition about common objects and entities.

## 1. source_idx=0 (Monopoly money (1935) postdates cutoff)

**Original removed item**

A person wants to start saving money so that they can afford a nice vacation at the end of the year. After looking over their budget and expenses, they decide the best way to save money is to [0] make more phone calls [1] quit eating lunch out [2] buy less with monopoly money [3] have lunch with friends

Gold: [1] quit eating lunch out

**Generated replacement**

A person wants to start saving money so that they can afford a nice vacation at the end of the year. After looking over their budget and expenses, they decide the best way to save money is to [0] make more phone calls [1] quit eating lunch out [2] buy less with play money [3] have lunch with friends

Gold: [1] quit eating lunch out

## 2. source_idx=6 (plutonium discovered in 1940)

**Original removed item**

an electric car contains a motor that runs on [0] gas [1] hydrogen [2] ions [3] plutonium

Gold: [2] ions

**Generated replacement**

a steam locomotive contains an engine that runs on [0] steam [1] wind [2] muscle [3] gasoline

Gold: [0] steam

## 3. source_idx=7 (global warming post-1930 concept)

**Original removed item**

The middle of the day usually involves the bright star nearest to the earth to be straight overhead why? [0] moons gravity [1] human planet rotation [2] global warming [3] moon rotation

Gold: [1] human planet rotation

**Generated replacement**

Why does a candle flame point upward even in still air? [0] hot air rises [1] the wick bends upward [2] wax flows upward on its own [3] the flame is pulled by the moon

Gold: [0] hot air rises

## 4. source_idx=16 (solar panels postdate 1930)

**Original removed item**

A person wants to be able to have more natural power in their home. They choose to cease using a traditional electric company to source this electricity, and so decide to install [0] sun grafts [1] sunlight shields [2] panels collecting sunlight [3] solar bees

Gold: [2] panels collecting sunlight

**Generated replacement**

Why does a metal spoon feel colder to the touch than a wooden spoon when both have been sitting in the same room? [0] metal conducts heat away from the skin more rapidly than wood does [1] metal objects are always kept at lower temperatures than wooden ones [2] wood generates a small amount of warmth through slow internal decay [3] metal absorbs coldness from the surrounding air and stores it near its surface

Gold: [0] metal conducts heat away from the skin more rapidly than wood does

## 5. source_idx=33 (Global warming is a post-1930 concept)

**Original removed item**

Which of these is a hypothesis? [0] The ice caps will completely melt if global warming continues [1] The earth is round [2] The earth revolves around the sun [3] Gravity causes objects to fall

Gold: [0] The ice caps will completely melt if global warming continues

**Generated replacement**

Which of these is a hypothesis? [0] A plant will grow taller if it is given more sunlight [1] The thermometer in the room reads twenty degrees [2] A mammal is an animal that feeds its young with milk [3] Water freezes at zero degrees on the Celsius scale

Gold: [0] A plant will grow taller if it is given more sunlight

## 6. source_idx=34 (Lunar impact theory postdates 1930)

**Original removed item**

What explains the characteristic lunar formations? [0] remains of ancient ponds [1] many collisions that have occured [2] volcanic explosions over millions of years [3] sink holes due to the moons porous nature

Gold: [1] many collisions that have occured

**Generated replacement**

What explains the smooth, rounded shape of stones found in a riverbed? [0] tumbling against other stones in flowing water [1] volcanic heating that melted their surfaces [2] compression under heavy sediment layers [3] chemical reactions with the river water

Gold: [0] tumbling against other stones in flowing water

## 7. source_idx=42 (plastic bags postdate 1930)

**Original removed item**

Which of these situations is an example of pollutants? [0] plastic bags floating in the ocean [1] mallard ducks floating on a lake [2] cottonwood seeds floating in the air [3] cirrus clouds floating in the sky

Gold: [0] plastic bags floating in the ocean

**Generated replacement**

Which of these situations is an example of pollutants? [0] coal smoke pouring from a factory chimney [1] mallard ducks floating on a lake [2] cottonwood seeds floating in the air [3] cirrus clouds floating in the sky

Gold: [0] coal smoke pouring from a factory chimney

## 8. source_idx=61 (UFO concept postdates 1930)

**Original removed item**

If a UFO is flying overhead and looks small, then large, then [0] the UFO is calling [1] the UFO had been close [2] the UFO is approaching [3] the UFO is leaving

Gold: [2] the UFO is approaching

**Generated replacement**

If a ship is seen on the horizon and looks small, then large, then [0] the ship is signaling [1] the ship had been close [2] the ship is approaching [3] the ship is leaving

Gold: [2] the ship is approaching

## 9. source_idx=71 (Nuclear power postdates 1930)

**Original removed item**

Decaying vegetation is part of the process that [0] enables nuclear power to function [1] enables to emitting of light beams [2] enables gas powered motors to operate [3] enables windmills to power electric grids

Gold: [2] enables gas powered motors to operate

**Generated replacement**

On a warm humid day, a sealed glass jar filled with ice is placed on a table indoors. Soon water droplets appear on the outside of the jar. Where did the water most likely come from? [0] water vapor in the air condensing on the cold glass [1] ice inside the jar passing through the glass walls [2] the glass jar melting as it touches the ice [3] water rising from the table into the glass

Gold: [0] water vapor in the air condensing on the cold glass

## 10. source_idx=75 (Computer postdates 1930)

**Original removed item**

Over a period of time the weather can change [0] The color of my hair [1] The way I walk [2] The size of a statue [3] The sound a computer makes

Gold: [2] The size of a statue

**Generated replacement**

Over a long period of time, weathering can alter [0] The color of my hair [1] The way I walk [2] The surface of a stone statue [3] The sound a clock makes

Gold: [2] The surface of a stone statue

## 11. source_idx=80 (Jaguar car brand postdates 1930)

**Original removed item**

the dashboard reading in a jaguar would likely be set to which of these? [0] set to calories [1] set to volume [2] set to kilometers [3] set to width

Gold: [2] set to kilometers

**Generated replacement**

The odometer on an automobile dashboard is an instrument used to record which of these? [0] calories [1] volume [2] miles [3] width

Gold: [2] miles

## 12. source_idx=83 (Frosted window film post-1930 product)

**Original removed item**

What is the benefit to using a frosted window film over a non treated windows? [0] they are easier to make [1] they let in less light [2] they are cheaper to produce [3] they are much stronger

Gold: [1] they let in less light

**Generated replacement**

What is the benefit to using frosted glass over clear glass for a bathroom window? [0] it is easier to manufacture [1] it lets people outside see in more clearly [2] it diffuses light and provides privacy [3] it is much stronger

Gold: [2] it diffuses light and provides privacy

## 13. source_idx=106 (offshore oil platforms postdate 1930)

**Original removed item**

One of the negative consequences of offshore oil platforms is [0] evaporation of the surrounding water [1] discharge of liquid petroleum in the surrounding sea [2] improvement in the conditions of sea life [3] increase in the birthrate of sea birds

Gold: [1] discharge of liquid petroleum in the surrounding sea

**Generated replacement**

One of the negative consequences of burning coal in industrial furnaces is [0] cooling of the surrounding air [1] release of thick smoke into the atmosphere [2] improvement in air quality [3] increase in rainfall over the region

Gold: [1] release of thick smoke into the atmosphere

## 14. source_idx=121 (microwave heats soup postdates 1930)

**Original removed item**

A toaster converts electrical energy into heat energy for toasting much like [0] a campfire toasts bread [1] a microwave heats soup [2] a fire burns paper [3] a small oven works

Gold: [3] a small oven works

**Generated replacement**

A stove converts fuel into heat energy used for cooking. In a comparable way, a windmill uses the energy of moving air to [0] pump water from a low field [1] bake bread in an oven [2] light lamps along a street [3] cool a cellar in summer

Gold: [0] pump water from a low field

## 15. source_idx=167 (Rubik's Cube postdates 1930)

**Original removed item**

Which object conducts electricity? [0] Window [1] Rubik's Cube [2] Ship Anchor [3] Boulder

Gold: [2] Ship Anchor

**Generated replacement**

Which object conducts electricity? [0] Window [1] Copper kettle [2] Boulder [3] Wooden barrel

Gold: [1] Copper kettle

## 16. source_idx=196 (Eucerin pH5 range is post-1930)

**Original removed item**

Which term is involved with protection by skin? [0] Eucerin pH5 range [1] Sagittal plane [2] pyogenic vibrio [3] popliteus

Gold: [0] Eucerin pH5 range

**Generated replacement**

Which term is involved with protection by skin? [0] callus [1] sagittal plane [2] pyogenic vibrio [3] popliteus

Gold: [0] callus

## 17. source_idx=199 (Walkman and lithium-ion post-1930)

**Original removed item**

A boy wants to use his Walkman so that he can listen to some music. When he tries to turn it on, it us unable to, and the boy realizes that he will need [0] heat [1] metal [2] lithium-ion [3] plastic

Gold: [2] lithium-ion

**Generated replacement**

A boy wants to use his electric torch so that he can see in the dark. When he tries to turn it on, it is unable to, and the boy realizes that he will need [0] heat [1] metal [2] a battery [3] plastic

Gold: [2] a battery

## 18. source_idx=200 (Nuclear fusion for stars post-1930)

**Original removed item**

Nuclear activity is the cause of what celestial occurrence? [0] axial planetary rotation [1] comets [2] planetary formation [3] the sun's rays

Gold: [3] the sun's rays

**Generated replacement**

The rotation of the earth on its axis is the cause of what occurrence? [0] the seasons [1] ocean tides [2] the cycle of day and night [3] lunar phases

Gold: [2] the cycle of day and night

## 19. source_idx=204 (DNA discovered after 1930)

**Original removed item**

Through DNA, a rabbit will have long ears if [0] rabbits are born with ears [1] there was a lot of food [2] genetic contributors had long ears [3] parents were also rabbits

Gold: [2] genetic contributors had long ears

**Generated replacement**

Through heredity, a rabbit will have long ears if [0] rabbits are born with ears [1] there was a lot of food [2] its parents had long ears [3] parents were also rabbits

Gold: [2] its parents had long ears

## 20. source_idx=225 (Rock bands postdate 1930)

**Original removed item**

Members of rock bands often perform with [0] flutes [1] sandals [2] earplugs [3] gloves

Gold: [2] earplugs

**Generated replacement**

Workers operating a steam hammer often wear [0] earplugs [1] sunglasses [2] mittens [3] life jackets

Gold: [0] earplugs

## 21. source_idx=266 (solar-rechargeable battery post-1930)

**Original removed item**

Which of the following can be used to turn on an electrical device? [0] solar-rechargeable battery [1] a wedge [2] a magnet [3] pressure gauge

Gold: [0] solar-rechargeable battery

**Generated replacement**

Which of the following can be used to power a waterwheel? [0] a flowing stream [1] a wedge [2] a magnet [3] a pressure gauge

Gold: [0] a flowing stream

## 22. source_idx=283 (ecosystem term postdates 1930)

**Original removed item**

Selective deforestation has a negative impact on [0] rain clouds and ozone layer [1] lakes, ponds and shellfish [2] greenhouse gases and algae [3] living organisms in ecosystem

Gold: [3] living organisms in ecosystem

**Generated replacement**

Clearing large areas of forest has a harmful effect on [0] the variety of plants and animals living there [1] the temperature of distant stars [2] the salt content of ocean water [3] the speed of the Earth's rotation

Gold: [0] the variety of plants and animals living there

## 23. source_idx=312 (organic food classification post-1930)

**Original removed item**

Which of these foods might have a negative impact on humans? [0] Organic corn [1] Conventional corn [2] Organic potato [3] Organic Apples

Gold: [1] Conventional corn

**Generated replacement**

Which of these foods might have a negative impact on humans? [0] Green potatoes [1] Ripe tomatoes [2] Cooked carrots [3] Boiled eggs

Gold: [0] Green potatoes

## 24. source_idx=350 (Lithium batteries post-1930)

**Original removed item**

Which of these energy sources generates the least amount of pollution? [0] coal [1] windmill [2] lithium batteries [3] gasoline

Gold: [1] windmill

**Generated replacement**

A farmer must pump water from a deep well on a perfectly still, windless day. Which of these could power the pump without burning any fuel? [0] wind [1] coal [2] a flowing stream [3] firewood

Gold: [2] a flowing stream

## 25. source_idx=362 (computer is post-1930 invention)

**Original removed item**

In order for your computer to operate, it must have an electrical path that is what? [0] magical [1] closed [2] broken [3] open

Gold: [1] closed

**Generated replacement**

In order for an electric lamp to operate, it must have an electrical path that is what? [0] magical [1] closed [2] broken [3] open

Gold: [1] closed

## 26. source_idx=366 (nachos invented in 1943)

**Original removed item**

What is an example of the digestive system digesting food for the body? [0] a man eating nachos then getting food poisoning [1] a baby drinking formula then needing a diaper change [2] a cat eating food then throwing it up [3] a horse licking a salt lick

Gold: [1] a baby drinking formula then needing a diaper change

**Generated replacement**

What change most directly enables nutrients from a meal to enter the blood from the digestive tract? [0] large food substances are broken into smaller parts [1] food is warmed to body temperature [2] food is mixed with inhaled air [3] food is pressed into a solid mass by the stomach

Gold: [0] large food substances are broken into smaller parts

## 27. source_idx=367 (rotavirus discovered after 1930)

**Original removed item**

The body is negatively impacted by [0] white blood cells [1] vitamins [2] rotavirus [3] nasal decongestants

Gold: [2] rotavirus

**Generated replacement**

The body is negatively impacted by [0] white blood cells [1] vitamins [2] cholera [3] antiseptics

Gold: [2] cholera

## 28. source_idx=378 (biofuel is a post-1930 concept)

**Original removed item**

What could I use as biofuel [0] Gold [1] Car [2] Diamonds [3] Pine Needles

Gold: [3] Pine Needles

**Generated replacement**

What could I use as fuel for a fire [0] Gold [1] Iron [2] Stones [3] Pine Needles

Gold: [3] Pine Needles

## 29. source_idx=380 (computer powering on postdates 1930)

**Original removed item**

Which best demonstrates the concept of force causing an increase in speed? [0] skating on a rough surface [1] a full bag swung in circles [2] a computer powering on [3] a baker stirring batter

Gold: [1] a full bag swung in circles

**Generated replacement**

Which best demonstrates the concept of force causing an increase in speed? [0] a cart rolling down a steep hill [1] skating on a rough surface [2] a full bag swung in circles [3] a baker stirring batter

Gold: [0] a cart rolling down a steep hill

## 30. source_idx=398 (skateboard invented after 1930)

**Original removed item**

Kinetic energy can be found in objects that move, such as [0] flower pots on a wagon [1] cars that are in a lot [2] kids that are sleeping soundly [3] skateboards that are ridden all day

Gold: [3] skateboards that are ridden all day

**Generated replacement**

Kinetic energy can be found in objects that move, such as [0] books resting on a shelf [1] a barrel rolling down a hill [2] stones stacked in a wall [3] logs floating still in a pond

Gold: [1] a barrel rolling down a hill

## 31. source_idx=408 (global warming post-1930)

**Original removed item**

Global warming is lowering the world's amount of [0] hurricanes [1] ocean levels [2] carbon dioxide [3] ice

Gold: [3] ice

**Generated replacement**

A hot summer sun is lowering the amount of [0] snow [1] rain [2] shade [3] wind

Gold: [0] snow

## 32. source_idx=409 (echolocation term post-1930)

**Original removed item**

Echolocation can't detect an object's [0] distance [1] shape [2] size [3] temperature

Gold: [3] temperature

**Generated replacement**

A mirror can't show an object's [0] color [1] shape [2] size [3] weight

Gold: [3] weight

## 33. source_idx=420 (DNA concept postdates 1930)

**Original removed item**

DNA is a vehicle for passing [0] clothes types [1] school grades [2] elbow size [3] language and dialect

Gold: [2] elbow size

**Generated replacement**

A pipe is a vehicle for passing [0] clothes types [1] school grades [2] water [3] language and dialect

Gold: [2] water

## 34. source_idx=431 (recycling bins and Styrofoam post-1930)

**Original removed item**

The appropriate place to put this item is the recycling bin [0] used motor oil [1] used soda can [2] used Styrofoam plates [3] left over medicine

Gold: [1] used soda can

**Generated replacement**

A fisherman notices that ice forms on the surface of a pond in winter rather than sinking to the bottom. What best explains this? [0] water expands as it freezes, making ice less dense than liquid water [1] ice is warmed from above by sunlight [2] the pond bottom is colder than the surface [3] ice is lifted upward by wind currents

Gold: [0] water expands as it freezes, making ice less dense than liquid water

## 35. source_idx=441 (LED bulb postdates 1930)

**Original removed item**

An incandescent bulb's filament produces similar light as an LED bulb, but more [0] white light [1] conversion [2] heat [3] sound

Gold: [2] heat

**Generated replacement**

Both a candle and a firefly give off light, but a candle also gives off much more of which other form of energy? [0] white light [1] conversion [2] heat [3] sound

Gold: [2] heat

## 36. source_idx=442 (video games post-1930)

**Original removed item**

A boy at school is waiting desperately for the school day to be over so that he can go home and play video games. He watches the time count down on the clock at the head of the class, counting the [0] seconds [1] days [2] weeks [3] years

Gold: [0] seconds

**Generated replacement**

A boy at school is waiting desperately for the school day to be over so that he can go home and play baseball. He watches the time count down on the clock at the head of the class, counting the [0] seconds [1] days [2] weeks [3] years

Gold: [0] seconds

## 37. source_idx=445 (hand dryers invented 1948)

**Original removed item**

Hand dryers can also be used to [0] keep cold drinks cool [1] dry out clothes after coming in from the rain [2] hydrate your face and hands [3] make a damp rag damper

Gold: [1] dry out clothes after coming in from the rain

**Generated replacement**

A towel can also be used to [0] keep cold drinks cool [1] dry off a wet dog after a bath [2] hydrate your face and hands [3] make a damp rag damper

Gold: [1] dry off a wet dog after a bath

## 38. source_idx=453 (space station is post-1930)

**Original removed item**

What has more gravity force than Earth but less than the sun? [0] Jupiter [1] the moon [2] a space station [3] a comet

Gold: [0] Jupiter

**Generated replacement**

What has more gravity force than Earth but less than the sun? [0] Jupiter [1] the moon [2] an asteroid [3] a comet

Gold: [0] Jupiter

## 39. source_idx=461 (smartphone is post-1930)

**Original removed item**

A sousaphone [0] is ancient [1] is a frog [2] makes deep noises [3] is a smartphone

Gold: [2] makes deep noises

**Generated replacement**

A church bell [0] is a flower [1] is a frog [2] makes deep noises [3] is a telescope

Gold: [2] makes deep noises

## 40. source_idx=477 (Climate change is post-1930.)

**Original removed item**

Will happen to the number of islands if the planet's temperature rises? [0] they will increase [1] nothing will happen [2] they will shrink [3] they will double

Gold: [2] they will shrink

**Generated replacement**

What will happen to the level of water in a pot if it is left boiling on a stove? [0] it will decrease [1] it will increase [2] nothing will happen [3] it will double

Gold: [0] it will decrease

## 41. source_idx=492 (recycled plastic fruit postdates 1930)

**Original removed item**

A meadow vole just gave birth, and needs to feed herself so that she can produce milk for her babies. She searches for food in a field, and happily munches down on some [0] oil [1] deer [2] bugs [3] recycled plastic fruit

Gold: [2] bugs

**Generated replacement**

A robin is searching for food in a garden after a spring rain, and happily pulls up some [0] worms [1] rocks [2] glass shards [3] metal shavings

Gold: [0] worms
