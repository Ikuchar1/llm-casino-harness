/* Blackjack engine for the demo: a port of blackjack/engine.py.
 *
 * Every seat plays a scenario from the same forced shoe (demo_data.json "shoe"), so
 * the visitor draws exactly the cards the agents drew when they made the same moves.
 * Rules are the study's locked rule set (blackjack/rules.py): 6 decks, dealer stands
 * on soft 17, double after split, one split, split aces get one card, no surrender,
 * dealer peeks for blackjack, blackjack pays 3:2, a 1-unit bet.
 *
 * The round is a small state machine. Every change is pushed onto round.events so the
 * UI can animate it in order:
 *   {type:"deal", to:"player"|"dealer", hand, card, down}   card = {r: rank, i: shoe index}
 *   {type:"split", hand}           hand `hand` split; its second card moved to hand+1
 *   {type:"turn", hand}            hand `hand` now waits for a decision
 *   {type:"reveal"}                dealer turns the hole card over
 *   {type:"settle"}                payouts are final (round.done is true)
 *
 * Works in the browser (window.BJ) and in Node (module.exports) for the parity test.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.BJ = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var HIT = "hit", STAND = "stand", DOUBLE = "double", SPLIT = "split";
  var FALLBACK = STAND;
  var DEFAULT_RULES = {
    dealer_hits_soft_17: false, double_after_split: true, max_splits: 1,
    split_aces_one_card: true, blackjack_payout: 1.5, bet: 1,
  };

  function decodeShoe(text) {
    var out = [];
    for (var k = 0; k < text.length; k++) out.push(text[k] === "T" ? "10" : text[k]);
    return out;
  }

  function cardValue(rank) {
    if (rank === "A") return 11;
    if (rank === "J" || rank === "Q" || rank === "K") return 10;
    return parseInt(rank, 10);
  }

  function ranks(cards) {
    return cards.map(function (c) { return typeof c === "string" ? c : c.r; });
  }

  /** {total, soft} for a list of ranks or card objects (aces drop from 11 to 1 as needed). */
  function handTotal(cards) {
    var rs = ranks(cards), total = 0, elevens = 0;
    rs.forEach(function (r) { total += cardValue(r); if (r === "A") elevens++; });
    while (total > 21 && elevens > 0) { total -= 10; elevens--; }
    return { total: total, soft: elevens > 0 };
  }

  function isBlackjack(cards) {
    return cards.length === 2 && handTotal(cards).total === 21;
  }

  function newRound(shoe, rules) {
    var cards = typeof shoe === "string" ? decodeShoe(shoe) : shoe.slice();
    var round = {
      shoe: cards, next: 0, rules: Object.assign({}, DEFAULT_RULES, rules || {}),
      hands: [], dealer: [], active: 0, splits: 0, done: false, revealed: false,
      playerBlackjack: false, dealerBlackjack: false, decisions: [], events: [],
    };
    var p1 = draw(round), up = draw(round), p2 = draw(round), hole = draw(round);
    round.hands.push(makeHand([p1, p2], false, false));
    round.dealer = [up, hole];
    round.events.push({ type: "deal", to: "player", hand: 0, card: p1 });
    round.events.push({ type: "deal", to: "dealer", card: up });
    round.events.push({ type: "deal", to: "player", hand: 0, card: p2 });
    round.events.push({ type: "deal", to: "dealer", card: hole, down: true });

    round.playerBlackjack = isBlackjack(round.hands[0].cards);
    round.dealerBlackjack = isBlackjack(round.dealer);
    if (round.playerBlackjack || round.dealerBlackjack) {
      var hand = round.hands[0], r = round.rules;
      hand.finished = true;
      if (round.playerBlackjack && round.dealerBlackjack) hand.payout = 0;
      else if (round.dealerBlackjack) hand.payout = -r.bet;
      else hand.payout = r.bet * r.blackjack_payout;
      round.active = round.hands.length;
      reveal(round);
      finish(round);
      return round;
    }
    advance(round);
    return round;
  }

  function makeHand(cards, fromSplit, splitAces) {
    return { cards: cards, fromSplit: fromSplit, splitAces: splitAces, doubled: false, finished: false, payout: 0, result: null };
  }

  function draw(round) {
    var card = { r: round.shoe[round.next], i: round.next };
    round.next++;
    return card;
  }

  function drawTo(round, handIndex) {
    var card = draw(round);
    round.hands[handIndex].cards.push(card);
    round.events.push({ type: "deal", to: "player", hand: handIndex, card: card });
    return card;
  }

  /** Legal actions for the hand waiting on a decision ([] once the player is done). */
  function legal(round) {
    if (round.done || round.active >= round.hands.length) return [];
    var hand = round.hands[round.active], r = round.rules, actions = [HIT, STAND];
    if (hand.cards.length === 2) {
      if (!hand.fromSplit || r.double_after_split) actions.push(DOUBLE);
      if (cardValue(hand.cards[0].r) === cardValue(hand.cards[1].r) && round.splits < r.max_splits) actions.push(SPLIT);
    }
    return actions;
  }

  /** Apply one decision to the active hand. An illegal or missing action stands. */
  function act(round, requested) {
    var actions = legal(round);
    if (!actions.length) throw new Error("no decision is pending");
    var valid = actions.indexOf(requested) >= 0;
    var action = valid ? requested : FALLBACK;
    var index = round.active, hand = round.hands[index];
    round.decisions.push({
      hand: index, cards: ranks(hand.cards), legal: actions, requested: requested === undefined ? null : requested,
      taken: action, valid: valid,
    });

    if (action === HIT) {
      drawTo(round, index);
      if (handTotal(hand.cards).total >= 21) hand.finished = true;
    } else if (action === STAND) {
      hand.finished = true;
    } else if (action === DOUBLE) {
      hand.doubled = true;
      drawTo(round, index);
      hand.finished = true;
    } else if (action === SPLIT) {
      round.splits++;
      var splitAces = hand.cards[0].r === "A" && round.rules.split_aces_one_card;
      var moved = hand.cards.pop();
      hand.fromSplit = true;
      hand.splitAces = splitAces;
      round.hands.splice(index + 1, 0, makeHand([moved], true, splitAces));
      round.events.push({ type: "split", hand: index });
      drawTo(round, index);
      if (hand.splitAces || handTotal(hand.cards).total >= 21) hand.finished = true;
    }
    if (hand.finished) round.active++;
    advance(round);
    return action;
  }

  /** Move to the next hand that needs a decision, or play the dealer and settle. */
  function advance(round) {
    while (round.active < round.hands.length) {
      var hand = round.hands[round.active];
      if (hand.cards.length === 1) drawTo(round, round.active);
      if (hand.splitAces || handTotal(hand.cards).total >= 21) hand.finished = true;
      if (!hand.finished) {
        round.events.push({ type: "turn", hand: round.active });
        return;
      }
      round.active++;
    }
    reveal(round);
    var live = round.hands.some(function (h) { return handTotal(h.cards).total <= 21; });
    if (live) {
      for (;;) {
        var t = handTotal(round.dealer);
        if (t.total < 17 || (t.total === 17 && t.soft && round.rules.dealer_hits_soft_17)) {
          var card = draw(round);
          round.dealer.push(card);
          round.events.push({ type: "deal", to: "dealer", card: card });
        } else break;
      }
    }
    var dealerTotal = handTotal(round.dealer).total;
    round.hands.forEach(function (h) { h.payout = settle(h, dealerTotal, round.rules); });
    finish(round);
  }

  function reveal(round) {
    if (round.revealed) return;
    round.revealed = true;
    round.events.push({ type: "reveal" });
  }

  function settle(hand, dealerTotal, rules) {
    var bet = rules.bet * (hand.doubled ? 2 : 1), total = handTotal(hand.cards).total;
    if (total > 21) return -bet;
    if (dealerTotal > 21 || total > dealerTotal) return bet;
    if (total < dealerTotal) return -bet;
    return 0;
  }

  function resultWord(payout) {
    return payout > 0 ? "win" : payout < 0 ? "loss" : "push";
  }

  function finish(round) {
    round.done = true;
    round.hands.forEach(function (h) { h.result = resultWord(h.payout); });
    round.payout = round.hands.reduce(function (s, h) { return s + h.payout; }, 0);
    round.dealerTotal = handTotal(round.dealer).total;
    round.events.push({ type: "settle" });
  }

  /** Play a round with a fixed list of actions (one per decision), as an agent did. */
  function replay(shoe, actions, rules) {
    var round = newRound(shoe, rules), k = 0;
    while (!round.done) act(round, actions[k++]);
    return round;
  }

  /** The round's outcome in the same shape as a hands.jsonl row. */
  function summary(round) {
    return {
      player_hands: round.hands.map(function (h) {
        return { cards: ranks(h.cards), total: handTotal(h.cards).total, doubled: h.doubled, from_split: h.fromSplit, payout: h.payout, result: h.result };
      }),
      dealer_cards: ranks(round.dealer),
      dealer_total: round.dealerTotal,
      payout: round.payout,
    };
  }

  return {
    HIT: HIT, STAND: STAND, DOUBLE: DOUBLE, SPLIT: SPLIT, DEFAULT_RULES: DEFAULT_RULES,
    decodeShoe: decodeShoe, cardValue: cardValue, handTotal: handTotal, isBlackjack: isBlackjack,
    newRound: newRound, legal: legal, act: act, replay: replay, summary: summary, resultWord: resultWord,
  };
});
