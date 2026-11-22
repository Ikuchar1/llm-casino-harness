# Fresh seeded shoe for every hand

Every hand is dealt from its own freshly shuffled 6-deck shoe, seeded from the run seed plus the hand number, instead of dealing a whole run from one continuous seeded shoe. With one continuous shoe, any difference in actions between harness configurations (one hits, one stands) shifts every later card, so configurations would silently play different hands and luck would leak back into the comparison. Per-hand seeding guarantees hand N starts with the same player cards and dealer upcard in every configuration.

## Consequences

- No shoe penetration or card counting is possible. This matches basic strategy, which assumes no knowledge of previously dealt cards, so grading stays consistent.
- Cards drawn after a decision can still differ between configurations when the model chooses differently; only each hand's starting deal is guaranteed identical.
- Don't "simplify" this back to a single shoe: it would invalidate cross-configuration comparisons.
