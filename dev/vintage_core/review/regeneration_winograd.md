# Regeneration review: `winograd`

Items: 1

This file shows only audited replacements. The authoritative preview is unchanged until
`python -m dev.vintage_core.regenerate apply` succeeds.

## 1. source_idx=229

- Audit status: `review`
- Regeneration mode: `revise`
- Concern: The gold relation is understandable, but people do not normally pass an entire chessboard when turns change.

**Previous staged item**

[0] Bill passed the chessboard to John because Bill's [1] Bill passed the chessboard to John because John's continuation: turn was next.

Gold: [1] Bill passed the chessboard to John because John's turn was next.

**Regenerated candidate**

[0] Bill passed the dice to John because Bill's [1] Bill passed the dice to John because John's continuation: turn was next.

Gold: [1] Bill passed the dice to John because John's turn was next.
