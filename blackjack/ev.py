"""Expected value (EV) of each legal action at a blackjack decision.

EV is measured in units per 1-unit initial bet: +1.0 means "wins one unit on
average", -2.0 means "always loses a doubled bet". The rule set comes from
blackjack/rules.py (6 decks, dealer stands on soft 17, double any two cards and
after a split, one split, split aces get one card, dealer peeks).

Card-removal model ("decision-point composition")
-------------------------------------------------
At each decision we know some cards: the player's cards and the dealer's
upcard (and, on a split hand, the other split card). We remove those from a
full 6-deck shoe and turn what is left into fixed draw probabilities. Every
later card (the player's hits, the dealer's hole card and hits) is drawn from
those same probabilities, so cards drawn *after* the decision do not deplete
the shoe any further. With num_decks=INFINITE nothing is removed, which is the
textbook infinite-deck model (each rank has probability 1/13).

The dealer peeks, so any decision implies the dealer does not have blackjack:
the hole card is drawn with the blackjack-making card ruled out (no ace under a
10, no 10-value card under an ace).

Splits: one split only. Each split hand starts with one pair card plus one new
card and is valued on its own (EV(split) = 2 x EV of one split hand); the two
hands are treated as independent. Split aces get one card and stand. With DAS,
a split hand may double. A two-card 21 after a split is 21, not blackjack.

Hand totals inside the calculations are (total, is_soft) pairs, where is_soft
means one ace is still counted as 11.
"""

from functools import lru_cache

from blackjack.rules import DEFAULT_RULES, RuleSet

HIT = "hit"
STAND = "stand"
DOUBLE = "double"
SPLIT = "split"

BUST = "bust"
DEALER_OUTCOMES = (17, 18, 19, 20, 21, BUST)

INFINITE = None  # pass as num_decks for the infinite-deck model
CARD_VALUES = range(1, 11)  # 1 = ace, 10 = any 10-value card

# Probabilities are rounded before they become cache keys, so two shoes that
# differ only by floating-point noise share one cache entry.
_KEY_DIGITS = 12


def card_points(rank: str) -> int:
    """A card's value with the ace as 1 (it is promoted to 11 when that helps)."""
    if rank == "A":
        return 1
    if rank in ("J", "Q", "K"):
        return 10
    return int(rank)


def shoe_probabilities(removed: list[str], num_decks: int | None = DEFAULT_RULES.num_decks) -> dict[int, float]:
    """Chance of drawing each card value (1-10) after the known cards are removed.

    num_decks=INFINITE ignores `removed` and gives 1/13 per rank (4/13 for 10s).
    """
    if num_decks is INFINITE:
        return {value: (4 if value == 10 else 1) / 13 for value in CARD_VALUES}

    counts = {value: (16 if value == 10 else 4) * num_decks for value in CARD_VALUES}
    for rank in removed:
        counts[card_points(rank)] -= 1
    cards_left = sum(counts.values())
    return {value: counts[value] / cards_left for value in CARD_VALUES}


def add_card(total: int, is_soft: bool, value: int) -> tuple[int, bool]:
    """The (total, is_soft) after adding one card of the given value."""
    total += value
    if value == 1 and total + 10 <= 21:  # count this ace as 11
        return total + 10, True
    if total > 21 and is_soft:  # an ace counted as 11 drops back to 1
        return total - 10, False
    return total, is_soft


def hand_value(cards: list[str]) -> tuple[int, bool]:
    """(total, is_soft) of a list of ranks."""
    total, is_soft = 0, False
    for rank in cards:
        total, is_soft = add_card(total, is_soft, card_points(rank))
    return total, is_soft


# --- dealer ---------------------------------------------------------------------------


def _probs_key(probs: dict[int, float]) -> tuple[float, ...]:
    """A hashable, rounded version of the probabilities, used as a cache key."""
    return tuple(round(probs[value], _KEY_DIGITS) for value in CARD_VALUES)


def dealer_distribution(
    upcard: str, probs: dict[int, float], rules: RuleSet = DEFAULT_RULES
) -> dict[int | str, float]:
    """Chance of each dealer final total (17-21 or bust), given no dealer blackjack."""
    outcomes = _dealer_distribution(card_points(upcard), _probs_key(probs), rules.dealer_hits_soft_17)
    return dict(zip(DEALER_OUTCOMES, outcomes))


@lru_cache(maxsize=None)
def _dealer_distribution(up_value: int, probs_key: tuple[float, ...], hits_soft_17: bool) -> tuple[float, ...]:
    probs = dict(zip(CARD_VALUES, probs_key))
    start = add_card(0, False, up_value)

    # The hole card can't complete a blackjack (the dealer peeked and didn't have one).
    blackjack_card = {10: 1, 1: 10}.get(up_value)
    allowed = {value: p for value, p in probs.items() if value != blackjack_card}
    scale = 1 / sum(allowed.values())

    result = [0.0] * len(DEALER_OUTCOMES)
    for value, p in allowed.items():
        total, is_soft = add_card(*start, value)
        for i, q in enumerate(_dealer_finish(total, is_soft, probs_key, hits_soft_17)):
            result[i] += p * scale * q
    return tuple(result)


@lru_cache(maxsize=None)
def _dealer_finish(total: int, is_soft: bool, probs_key: tuple[float, ...], hits_soft_17: bool) -> tuple[float, ...]:
    """Final-total chances for a dealer hand that already has its two cards (or more)."""
    if total > 21:
        return tuple(1.0 if outcome == BUST else 0.0 for outcome in DEALER_OUTCOMES)
    must_hit = total < 17 or (total == 17 and is_soft and hits_soft_17)
    if not must_hit:
        return tuple(1.0 if outcome == total else 0.0 for outcome in DEALER_OUTCOMES)

    result = [0.0] * len(DEALER_OUTCOMES)
    for value, p in zip(CARD_VALUES, probs_key):
        for i, q in enumerate(_dealer_finish(*add_card(total, is_soft, value), probs_key, hits_soft_17)):
            result[i] += p * q
    return tuple(result)


# --- player ---------------------------------------------------------------------------


class _Table:
    """EVs for every player total against one dealer upcard and one fixed shoe.

    The methods call each other recursively; results are stored in plain dicts
    so each (total, is_soft) is worked out only once.
    """

    def __init__(self, upcard: str, probs: dict[int, float], rules: RuleSet):
        self.probs = probs
        self.rules = rules
        self.dealer = dealer_distribution(upcard, probs, rules)
        self._best_after_hit: dict[tuple[int, bool], float] = {}

    def stand(self, total: int) -> float:
        """EV of standing on `total`: win if the dealer busts or ends lower, lose if higher."""
        if total > 21:
            return -1.0
        ev = self.dealer[BUST]
        for dealer_total in (17, 18, 19, 20, 21):
            if total > dealer_total:
                ev += self.dealer[dealer_total]
            elif total < dealer_total:
                ev -= self.dealer[dealer_total]
        return ev

    def hit(self, total: int, is_soft: bool) -> float:
        """EV of taking one card and then playing on optimally (hit or stand only)."""
        return sum(p * self.best_after_hit(*add_card(total, is_soft, value)) for value, p in self.probs.items())

    def best_after_hit(self, total: int, is_soft: bool) -> float:
        """Best EV once only hit and stand are left. 21 stands automatically, as in the engine."""
        if total > 21:
            return -1.0
        key = (total, is_soft)
        if key not in self._best_after_hit:
            stand_ev = self.stand(total)
            self._best_after_hit[key] = stand_ev if total == 21 else max(stand_ev, self.hit(total, is_soft))
        return self._best_after_hit[key]

    def double(self, total: int, is_soft: bool) -> float:
        """Twice the EV of taking exactly one card and standing."""
        return 2 * sum(p * self.stand(add_card(total, is_soft, value)[0]) for value, p in self.probs.items())

    def split(self, pair_rank: str) -> float:
        """Two independent split hands, each starting with one pair card plus a new card."""
        start = add_card(0, False, card_points(pair_rank))
        one_card_only = pair_rank == "A" and self.rules.split_aces_one_card

        one_hand = 0.0
        for value, p in self.probs.items():
            total, is_soft = add_card(*start, value)
            if one_card_only or total == 21:
                hand_ev = self.stand(total)
            else:
                options = [self.stand(total), self.hit(total, is_soft)]
                if self.rules.double_after_split:
                    options.append(self.double(total, is_soft))
                hand_ev = max(options)
            one_hand += p * hand_ev
        return 2 * one_hand


def action_evs(
    player_cards: list[str],
    upcard: str,
    can_double: bool,
    can_split: bool,
    num_decks: int | None = DEFAULT_RULES.num_decks,
    extra_removed: tuple[str, ...] = (),
    rules: RuleSet = DEFAULT_RULES,
) -> dict[str, float]:
    """EV of every legal action at one decision, e.g. {"hit": -0.54, "stand": -0.54, "double": -1.08}.

    `extra_removed` lists other known cards to take out of the shoe (e.g. the
    other split card on a split hand). Results are cached, so calling this for
    the same situation again is instant.
    """
    key_cards = tuple(sorted(player_cards, key=card_points))
    return dict(_action_evs(key_cards, upcard, can_double, can_split, num_decks, tuple(extra_removed), rules))


@lru_cache(maxsize=None)
def _action_evs(player_cards, upcard, can_double, can_split, num_decks, extra_removed, rules) -> tuple:
    removed = list(player_cards) + [upcard] + list(extra_removed)
    table = _Table(upcard, shoe_probabilities(removed, num_decks), rules)
    total, is_soft = hand_value(list(player_cards))

    evs = {HIT: table.hit(total, is_soft), STAND: table.stand(total)}
    if can_double:
        evs[DOUBLE] = table.double(total, is_soft)
    if can_split:
        evs[SPLIT] = table.split(player_cards[0])
    return tuple(evs.items())


def best_action(evs: dict[str, float]) -> str:
    """The action with the highest EV."""
    return max(evs, key=evs.get)
