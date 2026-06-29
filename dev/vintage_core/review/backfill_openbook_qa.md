# Backfill review: `openbook_qa`

Mode: preview
Items: 10

## Benchmark context

- Category: commonsense reasoning
- Task type: multiple choice
- Few-shot examples: 0
- Random baseline: 25
- Description: OpenBook QA consists of 500 four-choice multiple choice questions that rely on basic physical and scientific intuition about common objects and entities.

## 1. source_idx=0 (Monopoly money (1935) postdates cutoff)

**Original removed item**

A person wants to start saving money so that they can afford a nice vacation at the end of the year. After looking over their budget and expenses, they decide the best way to save money is to [0] make more phone calls [1] quit eating lunch out [2] buy less with monopoly money [3] have lunch with friends

Original gold: [1] quit eating lunch out

**Generated replacement**

A person wants to start saving money so that they can afford a nice vacation at the end of the year. After looking over their budget and expenses, they decide the best way to save money is to [0] make more phone calls [1] quit eating lunch out [2] buy less with play money [3] have lunch with friends

Generated expected gold (preserved source index): [1] quit eating lunch out

## 2. source_idx=6 (plutonium discovered in 1940)

**Original removed item**

an electric car contains a motor that runs on [0] gas [1] hydrogen [2] ions [3] plutonium

Original gold: [2] ions

**Generated replacement**

an electric streetcar contains a motor that runs on [0] coal [1] steam [2] ions [3] kerosene

Generated expected gold (preserved source index): [2] ions

## 3. source_idx=7 (global warming post-1930 concept)

**Original removed item**

The middle of the day usually involves the bright star nearest to the earth to be straight overhead why? [0] moons gravity [1] human planet rotation [2] global warming [3] moon rotation

Original gold: [1] human planet rotation

**Generated replacement**

The middle of the day usually involves the sun being at its highest point in the sky why? [0] moons gravity [1] earths rotation [2] seasonal changes [3] moon rotation

Generated expected gold (preserved source index): [1] earths rotation

## 4. source_idx=16 (solar panels postdate 1930)

**Original removed item**

A person wants to be able to have more natural power in their home. They choose to cease using a traditional electric company to source this electricity, and so decide to install [0] sun grafts [1] sunlight shields [2] panels collecting sunlight [3] solar bees

Original gold: [2] panels collecting sunlight

**Generated replacement**

A person wants to be able to have more natural power in their home. They choose to cease using a traditional electric company to source this electricity, and so decide to install [0] wind grafts [1] wind shields [2] windmills catching wind [3] wind bees

Generated expected gold (preserved source index): [2] windmills catching wind

## 5. source_idx=33 (Global warming is a post-1930 concept)

**Original removed item**

Which of these is a hypothesis? [0] The ice caps will completely melt if global warming continues [1] The earth is round [2] The earth revolves around the sun [3] Gravity causes objects to fall

Original gold: [0] The ice caps will completely melt if global warming continues

**Generated replacement**

Which of these is a hypothesis? [0] Mars has canals built by intelligent beings [1] The earth is round [2] The earth revolves around the sun [3] Gravity causes objects to fall

Generated expected gold (preserved source index): [0] Mars has canals built by intelligent beings

## 6. source_idx=34 (Lunar impact theory postdates 1930)

**Original removed item**

What explains the characteristic lunar formations? [0] remains of ancient ponds [1] many collisions that have occured [2] volcanic explosions over millions of years [3] sink holes due to the moons porous nature

Original gold: [1] many collisions that have occured

**Generated replacement**

What explains the circular depressions found on the moon's surface? [0] dried remains of ancient lunar oceans [1] strikes by rocks and other bodies from space [2] volcanic eruptions that occurred long ago [3] collapse of hollow caverns beneath the surface

Generated expected gold (preserved source index): [1] strikes by rocks and other bodies from space

## 7. source_idx=42 (plastic bags postdate 1930)

**Original removed item**

Which of these situations is an example of pollutants? [0] plastic bags floating in the ocean [1] mallard ducks floating on a lake [2] cottonwood seeds floating in the air [3] cirrus clouds floating in the sky

Original gold: [0] plastic bags floating in the ocean

**Generated replacement**

Which of these situations is an example of pollutants? [0] oil slicks floating on the ocean [1] mallard ducks floating on a lake [2] cottonwood seeds floating in the air [3] cirrus clouds floating in the sky

Generated expected gold (preserved source index): [0] oil slicks floating on the ocean

## 8. source_idx=61 (UFO concept postdates 1930)

**Original removed item**

If a UFO is flying overhead and looks small, then large, then [0] the UFO is calling [1] the UFO had been close [2] the UFO is approaching [3] the UFO is leaving

Original gold: [2] the UFO is approaching

**Generated replacement**

If an airship is flying overhead and looks small, then large, then [0] the airship is calling [1] the airship had been close [2] the airship is approaching [3] the airship is leaving

Generated expected gold (preserved source index): [2] the airship is approaching

## 9. source_idx=71 (Nuclear power postdates 1930)

**Original removed item**

Decaying vegetation is part of the process that [0] enables nuclear power to function [1] enables to emitting of light beams [2] enables gas powered motors to operate [3] enables windmills to power electric grids

Original gold: [2] enables gas powered motors to operate

**Generated replacement**

Decaying vegetation is part of the process that [0] enables sailing ships to travel [1] enables water wheels to turn [2] enables steam locomotives to operate [3] enables pendulum clocks to keep time

Generated expected gold (preserved source index): [2] enables steam locomotives to operate

## 10. source_idx=75 (Computer postdates 1930)

**Original removed item**

Over a period of time the weather can change [0] The color of my hair [1] The way I walk [2] The size of a statue [3] The sound a computer makes

Original gold: [2] The size of a statue

**Generated replacement**

Over a period of time the weather can change [0] The color of my hair [1] The way I walk [2] The size of a statue [3] The sound a phonograph makes

Generated expected gold (preserved source index): [2] The size of a statue