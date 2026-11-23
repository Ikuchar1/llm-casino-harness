// Replays blackjack rounds with demo/engine.js for tests/test_demo.py.
//
//   node tests/js/replay.js <cases.json>
//
// cases.json is a list of {shoe, actions}: shoe is the demo's one-character-per-card
// string (or a list of ranks), actions the requested action per decision (null means
// an invalid reply, which stands). Prints a JSON list with, per case, the hands.jsonl
// style summary plus every decision's cards, legal actions and taken action, so the
// Python test can compare it with blackjack/engine.py.
"use strict";
const fs = require("fs");
const path = require("path");
const BJ = require(path.join(__dirname, "..", "..", "demo", "engine.js"));

const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = cases.map((c) => {
  const round = BJ.replay(c.shoe, c.actions);
  const s = BJ.summary(round);
  s.decisions = round.decisions.map((d) => ({ hand: d.hand, cards: d.cards, legal: d.legal, taken: d.taken, valid: d.valid }));
  s.cards_drawn = round.next;
  return s;
});
process.stdout.write(JSON.stringify(out));
