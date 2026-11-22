# LLM Casino Harness

An ablation study measuring how much of an LLM agent's casino decision-making comes from the model versus the harness around it, starting with blackjack graded against basic strategy.

## Language

### Study design

**Harness**:
Everything around the LLM that shapes its decisions: state presentation, tools, memory, and self-checks.
_Avoid_: Wrapper, scaffold, framework

**Harness component**:
One toggleable piece of the harness: the probability tool, strategy information, memory, or self-evaluation.
_Avoid_: Feature, module, plugin

**Baseline**:
The harness configuration with every harness component off: game description, current state, and legal actions only.
_Avoid_: Control, vanilla

**Probability tool**:
The harness component that gives the model computed odds for the current state, such as bust probability or the dealer's final-total distribution.
_Avoid_: Calculation tool, calculator, odds tool

### Blackjack

**Rule set**:
The fixed table rules every run uses: 6 decks, dealer stands on soft 17, double on any two cards and after a split, one split only, split aces get one card, no surrender, dealer peeks, blackjack pays 3:2.
_Avoid_: House rules, variant

**Decision**:
One action the model chooses at a point where it has a real choice; a hand played hit, hit, stand is three decisions.
_Avoid_: Move, turn, step

**Basic strategy**:
The mathematically optimal action for each player hand and dealer upcard under the rule set, ignoring past cards.
_Avoid_: Optimal play, the chart, perfect strategy

**Correct decision**:
A decision that matches the best legal action under basic strategy (e.g., the chart says double but doubling isn't offered, so the hit or stand fallback is what counts as correct).
_Avoid_: Right move, good play

**Decision accuracy**:
The share of decisions that are correct decisions; the study's primary metric.
_Avoid_: Win rate, score

**Scenario set**:
A fixed list of forced starting situations covering every basic strategy cell once, used to measure accuracy evenly; it produces no return numbers.
_Avoid_: Test hands, drill set

**Invalid action**:
A model reply that can't be parsed into an action or names an action that isn't legal; it counts as an incorrect decision and the player stands.
_Avoid_: Error, bad output, parse failure
