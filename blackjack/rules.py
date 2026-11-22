"""The blackjack rule set every run uses, kept in one config object."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleSet:
    """Table rules for the simulator. The defaults are the study's locked rule set.

    6 decks, dealer stands on soft 17 (S17), double on any first two cards and
    double after split (DAS), split once only, split aces get one card each,
    splitting allowed on any two equal-value cards (e.g. K+Q), no surrender,
    no insurance, dealer peeks for blackjack under an A or 10-value upcard,
    blackjack pays 3:2, flat 1-unit bet. A two-card 21 after a split is 21,
    not blackjack.

    Some fields exist only so the rules are written down in one place; the
    engine does not implement their alternatives and refuses them.
    """

    num_decks: int = 6
    dealer_hits_soft_17: bool = False
    double_after_split: bool = True
    max_splits: int = 1
    split_aces_one_card: bool = True
    surrender_allowed: bool = False
    insurance_offered: bool = False
    dealer_peeks: bool = True
    blackjack_payout: float = 1.5
    bet: int = 1

    def __post_init__(self) -> None:
        if self.surrender_allowed:
            raise ValueError("Surrender is not implemented.")
        if self.insurance_offered:
            raise ValueError("Insurance is not implemented.")
        if not self.dealer_peeks:
            raise ValueError("Only dealer-peek (American) rules are implemented.")
        if self.max_splits not in (0, 1):
            raise ValueError("Only max_splits of 0 or 1 is implemented (no resplitting).")


DEFAULT_RULES = RuleSet()
