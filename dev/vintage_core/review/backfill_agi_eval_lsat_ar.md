# Backfill review: `agi_eval_lsat_ar`

Mode: commit
Items: 12

## Benchmark context

- Category: symbolic problem solving
- Task type: multiple choice
- Few-shot examples: 3
- Random baseline: 20
- Description: AGI Eval LSAT Analytical Reasoning consists of 230 four-choice multiple choice logic puzzles. The questions are taken from the AGI Eval benchmark.

## 1. source_idx=81 (software company postdates 1930)

**Original removed item**

Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work in its three sales zones—Zone 1, Zone 2, and Zone 3. Each sales representative works in exactly one of the sales zones, in accordance with the following conditions: Either Parra or Tiao (but not both) works in Zone 1. Either Tiao or Udall (but not both) works in Zone 2. Parra and Quinn work in the same sales zone as each other. Stuckey and Udall work in the same sales zone as each other. There are more of the sales representatives working in Zone 3 than in Zone 2. Q: Which one of the following could be an accurate matching of the sales representatives to the sales zones in which they work? Choices: A.) Zone 1: Parra, Quinn Zone 2: Kim, Udall Zone 3: Mahr, Stuckey, Tiao B.) Zone 1: Kim, Parra Zone 2: Stuckey, Udall Zone 3: Mahr, Quinn, Tiao C.) Zone 1: Kim, Tiao Zone 2: Stuckey, Udall Zone 3: Mahr, Parra, Quinn D.) Zone 1: Stuckey, Udall Zone 2: Kim, Tiao Zone 3: Mahr, Parra, Quinn Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Passage: A library assigns exactly seven books—Aeneid, Beowulf, Cid, Don Quixote, Edda, Faust, and Gilgamesh—to be displayed on exactly three shelves—Shelf 1, Shelf 2, and Shelf 3. Each book is placed on exactly one shelf, in accordance with the following conditions: Either Cid or Faust (but not both) is on Shelf 1. Either Faust or Gilgamesh (but not both) is on Shelf 2. Cid and Don Quixote are on the same shelf as each other. Edda and Gilgamesh are on the same shelf as each other. There are more books on Shelf 3 than on Shelf 2. Q: Which one of the following could be an accurate matching of the books to the shelves on which they are displayed? Choices: A.) Shelf 1: Cid, Don Quixote, Edda, Gilgamesh Shelf 2: Faust Shelf 3: Aeneid, Beowulf B.) Shelf 1: Aeneid, Cid Shelf 2: Edda, Gilgamesh Shelf 3: Beowulf, Don Quixote, Faust C.) Shelf 1: Aeneid, Faust Shelf 2: Beowulf, Edda, Gilgamesh Shelf 3: Cid, Don Quixote D.) Shelf 1: Edda, Gilgamesh Shelf 2: Aeneid, Faust Shelf 3: Beowulf, Cid, Don Quixote Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 2. source_idx=82 (software company postdates 1930)

**Original removed item**

Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work in its three sales zones—Zone 1, Zone 2, and Zone 3. Each sales representative works in exactly one of the sales zones, in accordance with the following conditions: Either Parra or Tiao (but not both) works in Zone 1. Either Tiao or Udall (but not both) works in Zone 2. Parra and Quinn work in the same sales zone as each other. Stuckey and Udall work in the same sales zone as each other. There are more of the sales representatives working in Zone 3 than in Zone 2. Q: If more sales representatives work in Zone 1 than in Zone 3, then which one of the following could be true? Choices: A.) Udall works in Zone 3. B.) Parra works in Zone 3. C.) Kim works in Zone 2. D.) Tiao works in Zone 1. Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Passage: A guild employs exactly seven apprentices—Aldo, Bella, Ciro, Dora, Enzo, Fina, and Gino—to work in its three workshops—East, North, and South. Each apprentice works in exactly one of the workshops, in accordance with the following conditions: Either Ciro or Fina (but not both) works in East. Either Fina or Gino (but not both) works in North. Ciro and Dora work in the same workshop as each other. Enzo and Gino work in the same workshop as each other. There are more of the apprentices working in South than in North. Q: If more apprentices work in East than in South, then which one of the following could be true? Choices: A.) Gino works in South. B.) Ciro works in South. C.) Aldo works in North. D.) Fina works in East. Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 3. source_idx=83 (software company postdates 1930)

**Original removed item**

Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work in its three sales zones—Zone 1, Zone 2, and Zone 3. Each sales representative works in exactly one of the sales zones, in accordance with the following conditions: Either Parra or Tiao (but not both) works in Zone 1. Either Tiao or Udall (but not both) works in Zone 2. Parra and Quinn work in the same sales zone as each other. Stuckey and Udall work in the same sales zone as each other. There are more of the sales representatives working in Zone 3 than in Zone 2. Q: Which one of the following must be false? Choices: A.) Kim and Stuckey both work in Zone 3. B.) Kim and Stuckey both work in Zone 1. C.) Mahr and Udall both work in Zone 3. D.) Parra and Stuckey both work in Zone I. Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Passage: A trading company employs exactly seven merchants—Anton, Bianca, Carlo, Diego, Elena, Francesco, and Greta—to work in its three ports—Port A, Port B, and Port C. Each merchant works in exactly one of the ports, in accordance with the following conditions: Either Carlo or Francesco (but not both) works at Port A. Either Francesco or Greta (but not both) works at Port B. Carlo and Diego work in the same port as each other. Elena and Greta work in the same port as each other. There are more of the merchants working at Port C than at Port B. Q: Which one of the following must be false? Choices: A.) Anton and Elena both work at Port C. B.) Anton and Elena both work at Port A. C.) Bianca and Greta both work at Port C. D.) Carlo and Elena both work at Port A. Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 4. source_idx=84 (software company postdates 1930)

**Original removed item**

Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work in its three sales zones—Zone 1, Zone 2, and Zone 3. Each sales representative works in exactly one of the sales zones, in accordance with the following conditions: Either Parra or Tiao (but not both) works in Zone 1. Either Tiao or Udall (but not both) works in Zone 2. Parra and Quinn work in the same sales zone as each other. Stuckey and Udall work in the same sales zone as each other. There are more of the sales representatives working in Zone 3 than in Zone 2. Q: Which one of the following could be a complete and accurate list of the sales representatives working in Zone 3? Choices: A.) Kim, Tiao B.) Parra, Quinn, Stuckey, Udall C.) Stuckey, Tiao, Udall D.) Kim, Mahr Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Passage: A trading company employs exactly seven clerks—Adams, Brown, Clark, Davis, Evans, Ford, and Grant—to work in its three warehouses—Warehouse 1, Warehouse 2, and Warehouse 3. Each clerk works in exactly one of the warehouses, in accordance with the following conditions: Either Clark or Ford (but not both) works in Warehouse 1. Either Ford or Grant (but not both) works in Warehouse 2. Clark and Davis work in the same warehouse as each other. Evans and Grant work in the same warehouse as each other. There are more of the clerks working in Warehouse 3 than in Warehouse 2. Q: Which one of the following could be a complete and accurate list of the clerks working in Warehouse 3? Choices: A.) Adams, Ford B.) Clark, Davis, Evans, Grant C.) Evans, Ford, Grant D.) Adams, Brown Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 5. source_idx=85 (software company postdates 1930)

**Original removed item**

Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work in its three sales zones—Zone 1, Zone 2, and Zone 3. Each sales representative works in exactly one of the sales zones, in accordance with the following conditions: Either Parra or Tiao (but not both) works in Zone 1. Either Tiao or Udall (but not both) works in Zone 2. Parra and Quinn work in the same sales zone as each other. Stuckey and Udall work in the same sales zone as each other. There are more of the sales representatives working in Zone 3 than in Zone 2. Q: Quinn CANNOT work in the same sales zone as which one of the following? Choices: A.) Mahr B.) Kim C.) Tiao D.) Stuckey Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Passage: A monastery assigns exactly seven scribes—Aldus, Bruno, Cicero, Dante, Erasmus, Ficino, and Galen—to work in its three scriptoria—Scriptorium I, Scriptorium II, and Scriptorium III. Each scribe works in exactly one of the scriptoria, in accordance with the following conditions: Either Cicero or Ficino (but not both) works in Scriptorium I. Either Ficino or Galen (but not both) works in Scriptorium II. Cicero and Dante work in the same scriptorium as each other. Erasmus and Galen work in the same scriptorium as each other. There are more of the scribes working in Scriptorium III than in Scriptorium II. Q: Dante CANNOT work in the same scriptorium as which one of the following? Choices: A.) Bruno B.) Aldus C.) Ficino D.) Erasmus Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 6. source_idx=86 (software company postdates 1930)

**Original removed item**

Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work in its three sales zones—Zone 1, Zone 2, and Zone 3. Each sales representative works in exactly one of the sales zones, in accordance with the following conditions: Either Parra or Tiao (but not both) works in Zone 1. Either Tiao or Udall (but not both) works in Zone 2. Parra and Quinn work in the same sales zone as each other. Stuckey and Udall work in the same sales zone as each other. There are more of the sales representatives working in Zone 3 than in Zone 2. Q: If Mahr and Stuckey work in the same sales zone, then which one of the following could be true? Choices: A.) Stuckey works in Zone 2. B.) Parra works in Zone 3. C.) Mahr works in Zone 1. D.) Kim works in Zone 2. Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Passage: A trading company assigns exactly seven merchants—Adams, Bell, Crane, Dale, Evans, Frye, and Grant—to work at its three trading posts—Post A, Post B, and Post C. Each merchant works at exactly one of the trading posts, in accordance with the following conditions: Either Crane or Frye (but not both) works at Post A. Either Frye or Grant (but not both) works at Post B. Crane and Dale work at the same trading post as each other. Evans and Grant work at the same trading post as each other. There are more of the merchants working at Post C than at Post B. Q: If Bell and Evans work at the same trading post, then which one of the following could be true? Choices: A.) Evans works at Post A. B.) Crane works at Post C. C.) Frye works at Post A. D.) Adams works at Post B. Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 7. source_idx=102 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: If none of the clients has a voicemail target of 3 days, then each of the following must be true EXCEPT: Choices: A.) Image's website target is 1 day. B.) Truvest's voicemail target is 2 days. C.) Solide's voicemail target is 2 days. D.) Solide's website target is 2 days. Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

**Generated replacement**

Passage: A trading house that sells goods for three merchants—Atlas, Boreal, and Centra—plans to set prices for two types of cloth each merchant supplies: silk and wool. Prices will be set at 3 florins, 2 florins, or 1 florin. Two prices are set for each merchant—one for silk and one for wool. The six prices are set according to the following conditions: None of the merchants can have a silk price that is higher than its wool price. Atlas's wool price must be lower than the other merchants' wool prices. Boreal's silk price must be lower than Centra's silk price. Q: If none of the merchants has a wool price of 3 florins, then each of the following must be true EXCEPT: Choices: A.) Atlas's silk price is 1 florin. B.) Centra's wool price is 2 florins. C.) Boreal's wool price is 2 florins. D.) Boreal's silk price is 2 florins. Answer: [0] A [1] B [2] C [3] D

Gold: [3] D

## 8. source_idx=103 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: If Truvest's website target is shorter than its voicemail target, which one of the following must be true? Choices: A.) Image's website target is 1 day. B.) Solide's website target is 1 day. C.) Image's voicemail target is 2 days. D.) Solide's website target is 2 days. Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Passage: A trading company that accepts orders from three clients—Florin, Genoa, and Lucca—plans to set targets for its average delivery times. Delivery targets will be set at 3 days, 2 days, or 1 day. Two delivery targets are set for each client—one for orders sent by sea and one for orders sent by land. The six targets are set according to the following conditions: None of the clients can have a sea target that is longer than its land target. Florin's land target must be shorter than the other clients' land targets. Genoa's sea target must be shorter than Lucca's sea target. Q: If Lucca's sea target is shorter than its land target, which one of the following must be true? Choices: A.) Florin's sea target is 1 day. B.) Genoa's sea target is 1 day. C.) Florin's land target is 2 days. D.) Genoa's sea target is 2 days. Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

## 9. source_idx=104 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: If Image's website target is 2 days, which one of the following targets must also be 2 days? Choices: A.) Truvest's website target B.) Truvest's voicemail target C.) Image's voicemail target D.) Solide's website target Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Passage: A trading company that handles shipments for three merchants—Atlas, Boreal, and Celest—plans to set delivery schedules. Each schedule will be set at 3 days, 2 days, or 1 day. Two schedules are set for each merchant—one for standard orders and one for rush orders. The six schedules are set according to the following conditions: None of the merchants can have a standard schedule that is longer than its rush schedule. Atlas's rush schedule must be shorter than the other merchants' rush schedules. Boreal's standard schedule must be shorter than Celest's standard schedule. Q: If Atlas's standard schedule is 2 days, which one of the following schedules must also be 2 days? Choices: A.) Celest's standard schedule B.) Celest's rush schedule C.) Atlas's rush schedule D.) Boreal's standard schedule Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 10. source_idx=105 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: If Solide's voicemail target is shorter than Truvest's website target, which one of the following targets could be 2 days? Choices: A.) Solide's website target B.) Image's website target C.) Truvest's website target D.) Image's voicemail target Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

**Generated replacement**

Passage: A trading house that accepts orders from three merchants—Athens, Byzantium, and Carthage—plans to set targets for its average delivery times. Delivery targets will be set at 3 days, 2 days, or 1 day. Two delivery targets are set for each merchant—one for orders sent by land courier and one for orders sent by sea courier. The six targets are set according to the following conditions: None of the merchants can have a land target that is longer than its sea target. Athens's sea target must be shorter than the other merchants' sea targets. Byzantium's land target must be shorter than Carthage's land target. Q: If Byzantium's sea target is shorter than Carthage's land target, which one of the following targets could be 2 days? Choices: A.) Byzantium's land target B.) Athens's land target C.) Carthage's land target D.) Athens's sea target Answer: [0] A [1] B [2] C [3] D

Gold: [0] A

## 11. source_idx=106 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: Which one of the following targets CANNOT be set for more than one of the clients? Choices: A.) a 3-day voicemail target B.) a 1-day website target C.) a 3-day website target D.) a 2-day website target Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

**Generated replacement**

Passage: A trading house that fills orders for three merchants—Hale, Korn, and Lamm—plans to set targets for its average delivery times. Delivery targets will be set at 3 weeks, 2 weeks, or 1 week. Two delivery targets are set for each merchant—one for goods sent by caravan and one for goods sent by ship. The six targets are set according to the following conditions: None of the merchants can have a caravan target that is longer than its ship target. Hale's ship target must be shorter than the other merchants' ship targets. Korn's caravan target must be shorter than Lamm's caravan target. Q: Which one of the following targets CANNOT be set for more than one of the merchants? Choices: A.) a 3-week ship target B.) a 1-week caravan target C.) a 3-week caravan target D.) a 2-week caravan target Answer: [0] A [1] B [2] C [3] D

Gold: [2] C

## 12. source_idx=107 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: If none of the clients has a website target of 2 days, which one of the following could be true? Choices: A.) Truvest's website target is shorter than Image's. B.) Solide's voicemail target is shorter than Truvest's. C.) Truvest's voicemail target is shorter than Solide's. D.) Solide's website target is shorter than Image's. Answer: [0] A [1] B [2] C [3] D

Gold: [1] B

**Generated replacement**

Passage: A trading firm that handles shipments for three merchants—Aldridge, Brentwood, and Carlyle—plans to set targets for its average delivery times. Delivery targets will be set at 3 weeks, 2 weeks, or 1 week. Two delivery targets are set for each merchant—one for shipments sent overland and one for shipments sent by sea. The six targets are set according to the following conditions: None of the merchants can have an overland target that is longer than its sea target. Aldridge's sea target must be shorter than the other merchants' sea targets. Brentwood's overland target must be shorter than Carlyle's overland target. Q: If none of the merchants has an overland target of 2 weeks, which one of the following could be true? Choices: A.) Carlyle's overland target is shorter than Aldridge's. B.) Brentwood's sea target is shorter than Carlyle's. C.) Carlyle's sea target is shorter than Brentwood's. D.) Brentwood's overland target is shorter than Aldridge's. Answer: [0] A [1] B [2] C [3] D

Gold: [1] B
