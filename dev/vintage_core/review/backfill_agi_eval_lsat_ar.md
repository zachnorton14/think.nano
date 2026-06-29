# Backfill review: `agi_eval_lsat_ar`

Mode: preview
Items: 7

## Benchmark context

- Category: symbolic problem solving
- Task type: multiple choice
- Few-shot examples: 3
- Random baseline: 20
- Description: AGI Eval LSAT Analytical Reasoning consists of 230 four-choice multiple choice logic puzzles. The questions are taken from the AGI Eval benchmark.

## Preview skips

- source_idx=82: agi_eval_lsat_ar source_idx=82 failed validation: missing keys: ['choices', 'gold', 'query']
- source_idx=83: agi_eval_lsat_ar source_idx=83 failed validation: no JSON in response: 'I need to create a new LSAT Analytical Reasoning logic puzzle that a well-read person in 1930 could answer. 
- source_idx=84: agi_eval_lsat_ar source_idx=84 failed validation: no JSON in response: 'The original item is an LSAT Analytical Reasoning logic puzzle. I need to create a new logic puzzle with the
- source_idx=86: agi_eval_lsat_ar source_idx=86 failed validation: no JSON in response: 'Let me analyze this LSAT Analytical Reasoning problem and create a new one that a well-read person in 1930 c
- source_idx=103: agi_eval_lsat_ar source_idx=103 failed validation: no JSON in response: 'Let me analyze this LSAT Analytical Reasoning problem carefully.\n\nWe have three clients: Image, Solide, a

## 1. source_idx=81 (software company postdates 1930)

**Original removed item**

Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work in its three sales zones—Zone 1, Zone 2, and Zone 3. Each sales representative works in exactly one of the sales zones, in accordance with the following conditions: Either Parra or Tiao (but not both) works in Zone 1. Either Tiao or Udall (but not both) works in Zone 2. Parra and Quinn work in the same sales zone as each other. Stuckey and Udall work in the same sales zone as each other. There are more of the sales representatives working in Zone 3 than in Zone 2. Q: Which one of the following could be an accurate matching of the sales representatives to the sales zones in which they work? Choices: A.) Zone 1: Parra, Quinn Zone 2: Kim, Udall Zone 3: Mahr, Stuckey, Tiao B.) Zone 1: Kim, Parra Zone 2: Stuckey, Udall Zone 3: Mahr, Quinn, Tiao C.) Zone 1: Kim, Tiao Zone 2: Stuckey, Udall Zone 3: Mahr, Parra, Quinn D.) Zone 1: Stuckey, Udall Zone 2: Kim, Tiao Zone 3: Mahr, Parra, Quinn Answer: [0] A [1] B [2] C [3] D

Original gold: [2] C

**Generated replacement**

Passage: A railway company employs exactly seven conductors—Adams, Bell, Crane, Doyle, Evans, Foster, and Grant—to work on its three rail lines—the Northern Line, the Southern Line, and the Western Line. Each conductor works on exactly one of the rail lines, in accordance with the following conditions: Either Crane or Foster (but not both) works on the Northern Line. Either Foster or Grant (but not both) works on the Southern Line. Crane and Doyle work on the same rail line as each other. Evans and Grant work on the same rail line as each other. There are more of the conductors working on the Western Line than on the Southern Line. Q: Which one of the following could be an accurate matching of the conductors to the rail lines on which they work? Choices: A.) Northern Line: Crane, Doyle Southern Line: Adams, Grant Western Line: Bell, Evans, Foster B.) Northern Line: Adams, Crane Southern Line: Evans, Grant Western Line: Bell, Doyle, Foster C.) Northern Line: Adams, Foster Southern Line: Evans, Grant Western Line: Bell, Crane, Doyle D.) Northern Line: Evans, Grant Southern Line: Adams, Foster Western Line: Bell, Crane, Doyle Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [2] C

## 2. source_idx=85 (software company postdates 1930)

**Original removed item**

Passage: A software company employs exactly seven sales representatives—Kim, Mahr, Parra, Quinn, Stuckey, Tiao, and Udall—to work in its three sales zones—Zone 1, Zone 2, and Zone 3. Each sales representative works in exactly one of the sales zones, in accordance with the following conditions: Either Parra or Tiao (but not both) works in Zone 1. Either Tiao or Udall (but not both) works in Zone 2. Parra and Quinn work in the same sales zone as each other. Stuckey and Udall work in the same sales zone as each other. There are more of the sales representatives working in Zone 3 than in Zone 2. Q: Quinn CANNOT work in the same sales zone as which one of the following? Choices: A.) Mahr B.) Kim C.) Tiao D.) Stuckey Answer: [0] A [1] B [2] C [3] D

Original gold: [2] C

**Generated replacement**

Passage: A shipping firm employs exactly seven clerks—Adams, Bell, Crane, Doyle, Evans, Frost, and Grant—to work in its three offices—Office 1, Office 2, and Office 3. Each clerk works in exactly one of the offices, in accordance with the following conditions: Either Crane or Frost (but not both) works in Office 1. Either Frost or Grant (but not both) works in Office 2. Crane and Doyle work in the same office as each other. Evans and Grant work in the same office as each other. There are more of the clerks working in Office 3 than in Office 2. Q: Doyle CANNOT work in the same office as which one of the following? Choices: A.) Bell B.) Adams C.) Frost D.) Evans Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [2] C

## 3. source_idx=102 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: If none of the clients has a voicemail target of 3 days, then each of the following must be true EXCEPT: Choices: A.) Image's website target is 1 day. B.) Truvest's voicemail target is 2 days. C.) Solide's voicemail target is 2 days. D.) Solide's website target is 2 days. Answer: [0] A [1] B [2] C [3] D

Original gold: [3] D

**Generated replacement**

Passage: A shipping firm that handles cargo for three merchants—Atlas, Baring, and Cromwell—plans to set targets for its average delivery times. Delivery targets will be set at 3 weeks, 2 weeks, or 1 week. Two delivery targets are set for each merchant—one for cargo sent by rail and one for cargo sent by sea. The six targets are set according to the following conditions: None of the merchants can have a rail target that is longer than its sea target. Atlas's sea target must be shorter than the other merchants' sea targets. Baring's rail target must be shorter than Cromwell's rail target. Q: If none of the merchants has a sea target of 3 weeks, then each of the following must be true EXCEPT: Choices: A.) Atlas's rail target is 1 week. B.) Cromwell's sea target is 2 weeks. C.) Baring's sea target is 2 weeks. D.) Baring's rail target is 2 weeks. Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [3] D

## 4. source_idx=104 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: If Image's website target is 2 days, which one of the following targets must also be 2 days? Choices: A.) Truvest's website target B.) Truvest's voicemail target C.) Image's voicemail target D.) Solide's website target Answer: [0] A [1] B [2] C [3] D

Original gold: [2] C

**Generated replacement**

Passage: A delivery company that takes orders from three merchants—Hartwell, Pembroke, and Queensbury—plans to set targets for its average delivery times. Delivery targets will be set at 3 days, 2 days, or 1 day. Two delivery targets are set for each merchant—one for orders received by post and one for orders received by telegram. The six targets are set according to the following conditions: None of the merchants can have a post target that is longer than its telegram target. Hartwell's telegram target must be shorter than the other merchants' telegram targets. Pembroke's post target must be shorter than Queensbury's post target. Q: If Hartwell's post target is 2 days, which one of the following targets must also be 2 days? Choices: A.) Queensbury's post target B.) Queensbury's telegram target C.) Hartwell's telegram target D.) Pembroke's post target Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [2] C

## 5. source_idx=105 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: If Solide's voicemail target is shorter than Truvest's website target, which one of the following targets could be 2 days? Choices: A.) Solide's website target B.) Image's website target C.) Truvest's website target D.) Image's voicemail target Answer: [0] A [1] B [2] C [3] D

Original gold: [0] A

**Generated replacement**

Passage: A shipping company that handles deliveries for three clients—Hartwell, Knox, and Pembroke—plans to set targets for its average delivery times. Delivery targets will be set at 3 days, 2 days, or 1 day. Two delivery targets are set for each client—one for parcels sent by express post and one for parcels sent by regular post. The six targets are set according to the following conditions: None of the clients can have an express post target that is longer than its regular post target. Hartwell's regular post target must be shorter than the other clients' regular post targets. Knox's express post target must be shorter than Pembroke's express post target. Q: If Knox's regular post target is shorter than Pembroke's express post target, which one of the following targets could be 2 days? Choices: A.) Knox's express post target B.) Hartwell's express post target C.) Pembroke's express post target D.) Hartwell's regular post target Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [0] A

## 6. source_idx=106 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: Which one of the following targets CANNOT be set for more than one of the clients? Choices: A.) a 3-day voicemail target B.) a 1-day website target C.) a 3-day website target D.) a 2-day website target Answer: [0] A [1] B [2] C [3] D

Original gold: [2] C

**Generated replacement**

Passage: A delivery company that takes orders from three merchants—Hartwell, Knox, and Pembroke—plans to set targets for its average delivery times. Delivery targets will be set at 3 days, 2 days, or 1 day. Two delivery targets are set for each merchant—one for orders received through the company's telegraph office and one for orders received by post. The six targets are set according to the following conditions: None of the merchants can have a telegraph target that is longer than its post target. Hartwell's post target must be shorter than the other merchants' post targets. Knox's telegraph target must be shorter than Pembroke's telegraph target. Q: Which one of the following targets CANNOT be set for more than one of the merchants? Choices: A.) a 3-day post target B.) a 1-day telegraph target C.) a 3-day telegraph target D.) a 2-day telegraph target Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [2] C

## 7. source_idx=107 (post-1930 term 'website')

**Original removed item**

Passage: A maintenance company that takes service requests from three clients—Image, Solide, and Truvest—plans to set targets for its average service response times. Service targets will be set at 3 days, 2 days, or 1 day. Two service targets are set for each client—one for requests received through the maintenance company's website and one for requests received by voicemail. The six targets are set according to the following conditions: None of the clients can have a website target that is longer than its voicemail target. Image's voicemail target must be shorter than the other clients' voicemail targets. Solide's website target must be shorter than Truvest's website target. Q: If none of the clients has a website target of 2 days, which one of the following could be true? Choices: A.) Truvest's website target is shorter than Image's. B.) Solide's voicemail target is shorter than Truvest's. C.) Truvest's voicemail target is shorter than Solide's. D.) Solide's website target is shorter than Image's. Answer: [0] A [1] B [2] C [3] D

Original gold: [1] B

**Generated replacement**

Passage: A railway company that serves three towns—Hartford, Norwood, and Easton—plans to set schedules for its delivery times. Delivery schedules will be set at 3 days, 2 days, or 1 day. Two schedules are set for each town—one for freight shipments and one for passenger service. The six schedules are set according to the following conditions: None of the towns can have a freight schedule that is longer than its passenger schedule. Hartford's passenger schedule must be shorter than the other towns' passenger schedules. Norwood's freight schedule must be shorter than Easton's freight schedule. Q: If none of the towns has a freight schedule of 2 days, which one of the following could be true? Choices: A.) Easton's freight schedule is shorter than Hartford's. B.) Norwood's passenger schedule is shorter than Easton's. C.) Easton's passenger schedule is shorter than Norwood's. D.) Norwood's freight schedule is shorter than Hartford's. Answer: [0] A [1] B [2] C [3] D

Generated expected gold (preserved source index): [1] B