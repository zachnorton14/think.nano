# Backfill review: `boolq`

Mode: preview
Items: 10

## Benchmark context

- Category: reading comprehension
- Task type: multiple choice
- Few-shot examples: 10
- Random baseline: 63
- Description: BoolQ consists of 3,270 short passages on a diverse range of subjects followed by a yes/no questions. The model is expected to answer in multiple-choice format.

## 1. source_idx=1 (post-1930 year [1978])

**Original removed item**

Passage: Property tax or 'house tax' is a local tax on buildings, along with appurtenant land. It is and imposed on the Possessor (not the custodian of property as per 1978, 44th amendment of constitution). It resembles the US-type wealth tax and differs from the excise-type UK rate. The tax power is vested in the states and is delegated to local bodies, specifying the valuation method, rate band, and collection procedures. The tax base is the annual rental value (ARV) or area-based rating. Owner-occupied and other properties not producing rent are assessed on cost and then converted into ARV by applying a percentage of cost, usually four percent. Vacant land is generally exempt. Central government properties are exempt. Instead a 'service charge' is permissible under executive order. Properties of foreign missions also enjoy tax exemption without requiring reciprocity. The tax is usually accompanied by service taxes, e.g., water tax, drainage tax, conservancy (sanitation) tax, lighting tax, all using the same tax base. The rate structure is flat on rural (panchayat) properties, but in the urban (municipal) areas it is mildly progressive with about 80% of assessments falling in the first two brackets. Question: is house tax and property tax are same? [0] no [1] yes

Original gold: [1] yes

**Generated replacement**

Passage: Excise duty, or simply 'the excise,' is a domestic tax levied on goods produced and consumed within a country, as distinguished from customs duties on imported goods. In Britain, excise duties date from the mid-seventeenth century and were initially imposed on alcoholic beverages, later extended to commodities such as tobacco, tea, and sugar. The duty is collected by officers of the Excise Department, who assess and collect the tax at the point of manufacture or sale. The duty is typically a specific rate per unit of quantity, though ad valorem rates are also used for some goods. Exemptions and reduced rates apply to certain categories, such as goods for export. The excise is accompanied by licensing requirements for manufacturers and dealers. The rate structure varies by commodity, with spirits and tobacco bearing the highest rates. In the United States, the corresponding tax is called the 'excise tax,' and is similarly levied on commodities such as tobacco, sugar, and manufactured goods. Question: are excise duty and excise tax the same? [0] no [1] yes

Generated expected gold (preserved source index): [1] yes
## 2. source_idx=11 (post-1930 year [2014])

**Original removed item**

Passage: Bloodline was announced in October 2014 as part of a partnership between Netflix and Sony Pictures Television, representing Netflix's first major deal with a major film studio for a television series. The series was created and executive produced by Todd A. Kessler, Glenn Kessler, and Daniel Zelman, who previously created the FX series Damages. According to its official synopsis released by Netflix, Bloodline ``centers on a close-knit family of four adult siblings whose secrets and scars are revealed when their black sheep brother returns home.'' Question: is the show bloodline based on a true story? [0] no [1] yes

Original gold: [0] no

**Generated replacement**

Passage: The Lost World was published in 1912 by Hodder & Stoughton, representing Arthur Conan Doyle's first major novel with that publisher following his well-publicized decision to retire Sherlock Holmes. The novel was written and illustrated by Conan Doyle, who previously created the popular detective series serialized in The Strand Magazine. According to its official synopsis released by the publisher, The Lost World ``centers on an expedition led by the eccentric Professor Challenger to a remote South American plateau where prehistoric creatures still exist.'' Question: is the novel the lost world based on a true story? [0] no [1] yes

Generated expected gold (preserved source index): [0] no
## 3. source_idx=12 (Shower gels and surfactants post-1930)

**Original removed item**

Passage: Shower gels for men may contain the ingredient menthol, which gives a cooling and stimulating sensation on the skin, and some men's shower gels are also designed specifically for use on hair and body. Shower gels contain milder surfactant bases than shampoos, and some also contain gentle conditioning agents in the formula. This means that shower gels can also double as an effective and perfectly acceptable substitute to shampoo, even if they are not labelled as a hair and body wash. Washing hair with shower gel should give approximately the same result as using a moisturising shampoo. Question: is it bad to wash your hair with shower gel? [0] no [1] yes

Original gold: [1] yes

**Generated replacement**

Passage: Common lye soap, while effective for general laundry purposes, can be harsh on delicate fabrics such as silk and wool. The high alkaline content of lye soap can damage the protein fibers found in wool and silk, causing them to become brittle and deteriorate over time. For these delicate materials, a milder soap such as olive oil soap is recommended, as it cleans effectively without damaging the natural fibers. Using lye soap on wool or silk will likely cause the fabric to weaken and eventually tear, making it inadvisable for laundering such garments. Question: can lye soap damage silk garments? [0] no [1] yes

Generated expected gold (preserved source index): [1] yes
## 4. source_idx=24 (post-1930 year [2011, 2012, 2013, 2014, 2015, 2016, 2017])

**Original removed item**

Passage: The Fire Tablet, formerly called the Kindle Fire, is a tablet computer developed by Amazon.com. Built with Quanta Computer, the Kindle Fire was first released in November 2011, featuring a color 7-inch multi-touch display with IPS technology and running a custom version of Google's Android operating system called Fire OS. The Kindle Fire HD followed in September 2012, and the Kindle Fire HDX in September 2013. In September 2014, when the fourth generation was introduced, the name ``Kindle'' was dropped. In September 2015, the fifth generation Fire 7 was released, followed by the sixth generation Fire HD 8, in September 2016. The seventh generation Fire 7 was released in June 2017. Question: is a fire 7 the same as a kindle? [0] no [1] yes

Original gold: [1] yes

**Generated replacement**

Passage: The SS Leviathan, originally named the SS Vaterland, was an ocean liner built for the Hamburg America Line. Constructed by Blohm & Voss in Hamburg, the Vaterland was launched in April 1914 as the largest passenger vessel in the world at the time. With the outbreak of the First World War, she was laid up at her pier in Hoboken, New Jersey. When the United States entered the war in April 1917, the vessel was seized, renamed USS Leviathan, and used as a troop transport. After the Armistice, she was refitted for passenger service and, under the name SS Leviathan, became the flagship of the United States Lines throughout the 1920s. Question: is the ss vaterland the same as the ss leviathan? [0] no [1] yes

Generated expected gold (preserved source index): [1] yes
## 5. source_idx=33 (post-1930 engine sensor technology)

**Original removed item**

Passage: The crank sensor can be used in combination with a similar camshaft position sensor to monitor the relationship between the pistons and valves in the engine, which is particularly important in engines with variable valve timing. This method is also used to ``synchronise'' a four stroke engine upon starting, allowing the management system to know when to inject the fuel. It is also commonly used as the primary source for the measurement of engine speed in revolutions per minute. Question: is an engine speed sensor the same as a crankshaft sensor? [0] no [1] yes

Original gold: [1] yes

**Generated replacement**

Passage: The centrifugal governor uses two rotating balls that swing outward as the rotational speed increases. It can be used in combination with a throttle valve to regulate the relationship between the steam supply and the engine's output, which is particularly important in engines with variable load requirements. This method is also used to stabilise the engine upon starting, allowing the operator to maintain a steady running speed. It is also commonly used as the primary means for the regulation of engine speed in revolutions per minute. Question: is an engine speed regulator the same as a centrifugal governor? [0] no [1] yes

Generated expected gold (preserved source index): [1] yes
## 6. source_idx=47 (post-1930 year [2002, 2008])

**Original removed item**

Passage: As of October 2008, a condor (four under par) hole-in-one on a par 5 hole had been recorded on four occasions, aided by thin air at high altitude, or by cutting the corner on a doglegged or horseshoe-shaped hole. A horseshoe-shaped par 5 hole once enabled a condor hole in one to be achieved with a 3-iron club. The longest recorded straight drive hole-in-one is believed to be 517 yards or 473 metres, on the par 5 No. 9 hole at Green Valley Ranch Golf Club in Denver in 2002, aided by the thin air due to the high altitude. None of these four par 5 holes-in-one were achieved during a professional tournament. A condor is also known as a double albatross, or a triple eagle. Question: has anyone hit a hole in one on a par 5? [0] no [1] yes

Original gold: [1] yes

**Generated replacement**

Passage: Charles Lindbergh completed the first solo nonstop transatlantic flight on May 21, 1927, flying his custom-built monoplane, the Spirit of St. Louis, from Roosevelt Field on Long Island, New York, to Le Bourget Field in Paris, France. The flight covered approximately 3,600 miles and lasted 33 hours and 30 minutes, during which Lindbergh navigated by dead reckoning, battling fatigue and sleep deprivation without a co-pilot or radio. His achievement earned him the $25,000 Orteig Prize, offered since 1919 for the first nonstop flight between New York and Paris. Prior to Lindbergh's success, several aviators had attempted the crossing, most notably the French war heroes Charles Nungesser and François Coli, who disappeared over the Atlantic in their aircraft L'Oiseau Blanc just weeks before Lindbergh's successful flight. The feat made Lindbergh an international hero and marked a milestone in aviation history. Question: has anyone flown solo nonstop across the Atlantic Ocean? [0] no [1] yes

Generated expected gold (preserved source index): [1] yes
## 7. source_idx=48 (post-1930 year [2010, 2011])

**Original removed item**

Passage: MetLife Stadium is an American sports stadium located in East Rutherford, New Jersey, 8 miles outside of New York City. It is part of the Meadowlands Sports Complex and serves as the home stadium for two National Football League (NFL) franchises: the New York Giants and the New York Jets. The stadium is owned by the MetLife Stadium Company, a joint venture of the Giants and Jets, who jointly built the stadium using private funds on land owned by the New Jersey Sports and Exposition Authority. The stadium opened as New Meadowlands Stadium in 2010. In 2011, MetLife, an insurance company based in New York City, acquired the naming rights to the stadium. At a construction cost of approximately $1.6 billion, it was the most expensive stadium ever built, at the time it opened, and is the second-largest stadium in the NFL in terms of seating capacity. Question: do the jets and giants share a stadium? [0] no [1] yes

Original gold: [1] yes

**Generated replacement**

Passage: The Polo Grounds was a sports stadium located in Upper Manhattan, New York City. It served as the home ballpark for two Major League Baseball franchises: the New York Giants and the New York Yankees. The Yankees, then often called the Highlanders, began sharing the Polo Grounds with the Giants in 1913, after their previous home, Hilltop Park, was closed. The stadium was owned and operated by the New York Giants organization under the ownership of John T. Brush and later Charles Stoneham. The Yankees continued to share the ballpark until 1922, before moving into their own newly constructed Yankee Stadium in the Bronx in 1923. With a seating capacity of roughly 34,000, the Polo Grounds was one of the larger ballparks in Major League Baseball during that era. Question: did the yankees and giants share a stadium? [0] no [1] yes

Generated expected gold (preserved source index): [1] yes
## 8. source_idx=53 (ASU uniform, polyester post-1930)

**Original removed item**

Passage: The ASU includes a midnight blue coat and low waist trousers for male soldiers; and a midnight blue coat, slacks and skirt for female soldiers. The fabric for the ASU is heavier and more wrinkle resistant than previously manufactured uniforms and will consist of 55% wool and 45% polyester material. The ASU coat has a tailored, athletic cut to improve uniform fit and appearance. The ASU includes an improved heavier and wrinkle resistant short and long-sleeved white shirt with permanent military creases and shoulder loops. The JROTC version replaces the white shirt with the prototype grey shirt and gold braid is not worn on the blue trousers or on the sleeves of the class A coat. Compared to the Army's previous uniforms, the ASU does not include a garrison cap; soldiers will continue to wear the Army's berets. Question: can you wear short sleeve shirt with asu jacket? [0] no [1] yes

Original gold: [1] yes

**Generated replacement**

Passage: The Army blue dress uniform includes a dark blue coat and light blue trousers for enlisted men; and a dark blue coat with white trousers for officers. The fabric for the blue coat is made of wool melton and is heavier than the olive drab service uniform. The blue coat has a tailored cut with standing collar and shoulder loops. The uniform includes both a white dress shirt with stiff bosom and a khaki cotton summer shirt with lay-down collar. The garrison version replaces the white shirt with the khaki shirt and braid is not worn on the light blue trousers. Compared to the Army's previous uniforms, the blue dress uniform does not include a campaign hat; soldiers will continue to wear the service cap. Question: can you wear khaki shirt with blue dress coat? [0] no [1] yes

Generated expected gold (preserved source index): [1] yes
## 9. source_idx=56 (post-1930 year [1995, 2018])

**Original removed item**

Passage: Shaquem Alphonso Griffin /ʃəˈkiːm/ (born July 20, 1995) is an American football linebacker for the Seattle Seahawks of the National Football League (NFL). He is the twin brother of Seahawks cornerback Shaquill Griffin, and both brothers played college football for the University of Central Florida Knights. As an amputee with one hand, Shaquem Griffin received extensive media coverage as a prospective 2018 NFL Draft pick. He was selected as a fifth round pick (141st overall) by the Seahawks on April 28, 2018, reuniting him with Shaquill. Question: is there a player in the nfl missing a hand? [0] no [1] yes

Original gold: [1] yes

**Generated replacement**

Passage: Hugh Daily (1847–1927), known as "One-Arm" Daily, was an American professional baseball pitcher who played in Major League Baseball from 1882 to 1887. Despite losing his left hand in a childhood milling accident, Daily pitched for several teams including the Cleveland Blues, Providence Grays, and Detroit Wolverines. He was notable for his curveball and for successfully fielding his position with only one hand, drawing considerable attention from the sporting press of his era. Question: was there a player in major league baseball missing a hand? [0] no [1] yes

Generated expected gold (preserved source index): [1] yes
## 10. source_idx=67 (post-1930 year [2005])

**Original removed item**

Passage: Capital punishment for juveniles in the United States existed until March 1, 2005, when the U.S. Supreme Court banned it in Roper v. Simmons. Question: can you get the death penalty as a minor? [0] no [1] yes

Original gold: [0] no

**Generated replacement**

Passage: Women's suffrage in the United States was achieved nationally on August 26, 1920, when the Nineteenth Amendment to the U.S. Constitution was ratified, prohibiting states from denying the right to vote on the basis of sex. Question: could women vote in U.S. federal elections before 1920? [0] no [1] yes

Generated expected gold (preserved source index): [0] no