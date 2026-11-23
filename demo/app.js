/* Showcase demo: "Can you beat the AI?"
 *
 * A Visitor plays three random deals from the scenario set, one first decision each,
 * against two agent Seats that played the exact same cards earlier: Baseline and the
 * Full harness. After the third hand the page reveals, hand by hand, what each Seat
 * chose, what basic strategy says, and how each Seat's hand played out.
 *
 * Data: demo_data.json (scripts/export_demo_data.py). Live board: /api/board and
 * /api/results (scripts/demo_server.py). Engine: engine.js (window.BJ).
 *
 * Every async flow (a game, the reveal, attract mode) runs under a generation number;
 * starting a new flow bumps it and every pending wait in the old flow throws ABORT.
 */
(function () {
  "use strict";

  var HANDS_PER_GAME = 3;
  var IDLE_MS = 30000;          // results / menus -> attract
  var IDLE_GAME_MS = 120000;    // a game left mid-hand -> attract
  var BOARD_POLL_MS = 15000;
  var SUITS = ["♠", "♥", "♦", "♣"];
  var ACT_LABEL = { hit: "Hit", stand: "Stand", double: "Double", split: "Split" };
  var SEAT_NAME = { you: "You", baseline: "Baseline", full: "Full harness" };
  var ABORT = { abort: true };

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  var canvas = $("#canvas");
  // the canvas is a fixed stage: never let focus or scrollIntoView shift it
  canvas.addEventListener("scroll", function () { canvas.scrollTop = 0; canvas.scrollLeft = 0; });
  var DATA = null, READY = [], BY_ID = {};
  var state = {
    mode: "loading",       // loading | attract | play | reveal | tally | results | empty
    presenter: false,
    session: [],           // presenter: [{s, action, payout}]
    game: [],              // visitor: same shape
    lastGameIds: [],
    board: null, online: false,
    localResults: [],      // when the server is not there (file://), the board is this session's
    lastInput: Date.now(),
  };
  var scale = 1;
  function setMode(m) { state.mode = m; canvas.dataset.mode = m; }

  // ---------- generations, waits ----------
  var gen = 0, pending = [];
  function newFlow() {
    gen++;
    var old = pending; pending = [];
    old.forEach(function (p) { p.reject(ABORT); });
    return gen;
  }
  function ck(g) { if (g !== gen) throw ABORT; }
  function sleep(ms, g) {
    return new Promise(function (resolve, reject) {
      var entry = { reject: reject };
      pending.push(entry);
      setTimeout(function () {
        pending = pending.filter(function (p) { return p !== entry; });
        if (g !== gen) reject(ABORT); else resolve();
      }, ms);
    });
  }
  function swallow(e) { if (e !== ABORT) { console.error(e); } }

  // One "advance" at a time: the big Next button, a tap anywhere, Space/Enter/→.
  var advanceHook = null;
  function waitAdvance(label, g, opts) {
    opts = opts || {};
    return new Promise(function (resolve, reject) {
      var entry = { reject: function (e) { advanceHook = null; hideCtas(); reject(e); } };
      pending.push(entry);
      setCtas([{ label: label, cls: "next", fn: go }].concat(opts.extra || []));
      $("#tapnote").classList.toggle("hide", !!opts.noTap);
      advanceHook = opts.noTap ? null : go;
      function go() {
        if (g !== gen) return;
        pending = pending.filter(function (p) { return p !== entry; });
        advanceHook = null; hideCtas();
        resolve();
      }
    });
  }
  function setCtas(list) {
    var box = $("#ctas"); box.innerHTML = "";
    list.forEach(function (b) {
      var el = document.createElement("button");
      el.className = "cta " + (b.cls || "");
      el.textContent = b.label;
      el.addEventListener("click", function (e) { e.stopPropagation(); b.fn(); });
      box.appendChild(el);
    });
  }
  function hideCtas() { $("#ctas").innerHTML = ""; $("#tapnote").classList.add("hide"); }

  // ---------- scaling ----------
  function fit() {
    scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    canvas.style.transform = "translate(-50%,-50%) scale(" + scale + ")";
  }
  window.addEventListener("resize", fit);
  fit();

  // ---------- cards ----------
  function suitOf(card) { return SUITS[(card.i * 7 + 3) % 4]; }
  function cardEl(card, down) {
    var c = document.createElement("div");
    c.className = "card" + (down ? " down" : "");
    var r = card.r === "10" ? "10" : card.r, s = suitOf(card), red = s === "♥" || s === "♦";
    var court = r === "J" || r === "Q" || r === "K";
    c.innerHTML = '<div class="in"><div class="face front' + (red ? " red" : "") + '">' +
      '<div class="cn tl">' + r + "<small>" + s + "</small></div>" +
      (court ? '<div class="court">' + r + "</div>" : '<div class="pip">' + s + "</div>") +
      '<div class="cn br">' + r + "<small>" + s + "</small></div></div>" +
      '<div class="face back"></div></div>';
    return c;
  }
  function flyFrom(el, fromEl, opts) {
    opts = opts || {};
    var a = fromEl.getBoundingClientRect(), b = el.getBoundingClientRect();
    var dx = (a.left + a.width / 2 - (b.left + b.width / 2)) / scale;
    var dy = (a.top + a.height / 2 - (b.top + b.height / 2)) / scale;
    if (!el.animate) return Promise.resolve();
    return el.animate([
      { transform: "translate(" + dx + "px," + dy + "px) rotate(" + (opts.spin == null ? -25 : opts.spin) + "deg) scale(.7)", opacity: 0 },
      { opacity: 1, offset: 0.15 },
      { transform: "translate(0,0) rotate(0) scale(1)", opacity: 1 },
    ], { duration: opts.dur || 560, easing: "cubic-bezier(.15,.75,.25,1)", fill: "backwards" }).finished.catch(function () {});
  }
  function flyTo(el, toEl, dur) {
    var a = el.getBoundingClientRect(), b = toEl.getBoundingClientRect();
    var dx = (b.left + b.width / 2 - (a.left + a.width / 2)) / scale;
    var dy = (b.top + b.height / 2 - (a.top + a.height / 2)) / scale;
    if (!el.animate) return Promise.resolve();
    return el.animate([
      { transform: "none", opacity: 1 },
      { transform: "translate(" + dx + "px," + dy + "px) rotate(18deg) scale(.6)", opacity: 0 },
    ], { duration: dur || 420, easing: "cubic-bezier(.5,0,.75,0)", fill: "forwards" }).finished.catch(function () {});
  }

  // ---------- table views ----------
  var dealer = { el: $("#dealerHand"), cards: [], down: null };
  var seats = {};
  ["you", "baseline", "full"].forEach(function (k) {
    var el = $('.seat[data-seat="' + k + '"]');
    seats[k] = { key: k, el: el, handsEl: $(".hands", el), slotEl: $(".slot", el), thinkEl: $(".think", el), hands: [] };
  });

  function handView(seat, index) {
    var el = document.createElement("div");
    el.className = "hand";
    el.innerHTML = '<div class="tot"></div><div class="cards"></div><div class="badge"></div>';
    var view = { el: el, cardsEl: $(".cards", el), totEl: $(".tot", el), badgeEl: $(".badge", el), ranks: [] };
    var after = seat.hands[index - 1];
    if (after && after.el.nextSibling) seat.handsEl.insertBefore(el, after.el.nextSibling);
    else seat.handsEl.appendChild(el);
    seat.hands.splice(index, 0, view);
    return view;
  }

  function showTotal(totEl, ranks, opts) {
    opts = opts || {};
    if (!ranks.length) { totEl.classList.remove("on"); return; }
    var t = BJ.handTotal(ranks);
    var bj = ranks.length === 2 && t.total === 21 && !opts.noBJ;
    totEl.textContent = bj ? "BJ" : String(t.total);
    totEl.classList.toggle("soft", t.soft && t.total < 21 && !bj);
    totEl.classList.toggle("bust", t.total > 21);
    totEl.classList.add("on");
  }

  function clearSeat(seat) {
    seat.handsEl.innerHTML = "";
    seat.handsEl.classList.remove("split");
    seat.hands = [];
    seat.slotEl.innerHTML = "";
    if (seat.thinkEl) seat.thinkEl.classList.remove("on");
    seat.el.classList.remove("dim");
  }
  function clearDealer() {
    $(".cards", dealer.el).innerHTML = "";
    $(".tot", dealer.el).classList.remove("on");
    dealer.cards = []; dealer.down = null;
    $("#dealerFor").textContent = "";
  }

  /** Sweep every card on the table into the discard tray. */
  function clearTable(g, keepSlots) {
    var cards = $$(".seat .card, #dealerHand .card");
    var discard = $("#discard");
    var anims = cards.map(function (c) { return flyTo(c, discard, 380); });
    $$(".badge.on, .tot.on").forEach(function (b) { b.classList.remove("on"); });
    $("#seal").classList.remove("on");
    $("#situation").style.opacity = 0;
    return Promise.all(anims).then(function () {
      ck(g);
      Object.keys(seats).forEach(function (k) {
        var slot = seats[k].slotEl.innerHTML;
        clearSeat(seats[k]);
        if (keepSlots) seats[k].slotEl.innerHTML = slot;
      });
      clearDealer();
    });
  }

  function speedOf(opts) { return (opts && opts.speed) || 1; }

  /** Animate engine events [from, to) for one seat and the dealer. */
  async function playEvents(seat, events, from, g, opts) {
    var sp = speedOf(opts), shoe = $("#shoe");
    for (var k = from; k < events.length; k++) {
      var ev = events[k];
      ck(g);
      if (ev.type === "deal" && ev.to === "player") {
        var view = seat.hands[ev.hand] || handView(seat, ev.hand);
        var el = cardEl(ev.card, false);
        view.cardsEl.appendChild(el);
        view.ranks.push(ev.card.r);
        await flyFrom(el, shoe, { dur: 520 * sp });
        showTotal(view.totEl, view.ranks, { noBJ: seat.hands.length > 1 });
        await sleep(120 * sp, g);
      } else if (ev.type === "deal") {
        var del = cardEl(ev.card, !!ev.down);
        $(".cards", dealer.el).appendChild(del);
        dealer.cards.push(ev.card.r);
        if (ev.down) dealer.down = del;
        await flyFrom(del, shoe, { dur: 520 * sp });
        showDealerTotal();
        await sleep(160 * sp, g);
      } else if (ev.type === "split") {
        var src = seat.hands[ev.hand];
        seat.handsEl.classList.add("split");
        var moved = src.cardsEl.lastElementChild;
        var nv = handView(seat, ev.hand + 1);
        nv.cardsEl.appendChild(moved);
        nv.ranks.push(src.ranks.pop());
        if (moved.animate) moved.animate([{ transform: "translateX(-60px)" }, { transform: "none" }], { duration: 380 * sp, easing: "ease-out" });
        showTotal(src.totEl, src.ranks); showTotal(nv.totEl, nv.ranks);
        await sleep(450 * sp, g);
      } else if (ev.type === "turn") {
        setActive(seat, ev.hand);
      } else if (ev.type === "reveal") {
        setActive(seat, -1);
        if (dealer.down) { dealer.down.classList.remove("down"); dealer.down = null; }
        dealer.revealed = true;
        showDealerTotal();
        await sleep(650 * sp, g);
      } else if (ev.type === "settle") {
        setActive(seat, -1);
      }
    }
    return events.length;
  }
  function setActive(seat, index) {
    seat.hands.forEach(function (h, i) { h.el.classList.toggle("active", i === index && seat.hands.length > 1); });
  }
  function showDealerTotal() {
    var tot = $(".tot", dealer.el);
    if (!dealer.cards.length) { tot.classList.remove("on"); return; }
    var visible = dealer.down ? dealer.cards.slice(0, 1) : dealer.cards;
    showTotal(tot, visible);
  }
  function showOutcome(seat, round) {
    round.hands.forEach(function (h, i) {
      var v = seat.hands[i];
      if (!v) return;
      var word = h.result, amt = h.payout;
      var text = word === "win" ? (amt === 1.5 ? "Blackjack +1.5" : "Win +" + amt) : word === "loss" ? "Lose " + amt : "Push";
      if (BJ.handTotal(v.ranks).total > 21) text = "Bust " + amt;
      v.badgeEl.className = "badge " + word;
      v.badgeEl.textContent = text;
      v.badgeEl.classList.add("on");
    });
  }

  // ---------- chips on the slots ----------
  function miniChip(action, invalid) {
    var el = document.createElement("div");
    if (invalid || !action) { el.className = "mini-chip inv"; el.textContent = "invalid"; return el; }
    el.className = "mini-chip";
    el.style.setProperty("--chip", "var(--" + action + ")");
    el.textContent = ACT_LABEL[action];
    return el;
  }
  function placeChip(seat, action) {
    seat.slotEl.innerHTML = "";
    var chip = miniChip(action);
    seat.slotEl.appendChild(chip);
    if (chip.animate) chip.animate([{ transform: "translateY(160px) scale(1.3)", opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 380, easing: "cubic-bezier(.2,1.4,.4,1)" });
  }
  function sealedChip(seat, entry) {
    seat.slotEl.innerHTML = "";
    var wrap = document.createElement("div");
    wrap.className = "sealed";
    var back = document.createElement("div"); back.className = "s-back"; back.textContent = "?";
    var front = document.createElement("div"); front.className = "s-front";
    var answered = entry && entry.status === "answered";
    front.appendChild(miniChip(answered ? entry.action : null, answered ? entry.invalid : false));
    if (!answered) $(".mini-chip", front).textContent = "n/a";
    wrap.appendChild(back); wrap.appendChild(front);
    seat.slotEl.appendChild(wrap);
    return wrap;
  }
  function mark(seat, ok) {
    var m = document.createElement("div");
    m.className = "mark " + (ok ? "ok" : "no");
    m.textContent = ok ? "✓" : "✗";
    seat.slotEl.appendChild(m);
    requestAnimationFrame(function () { requestAnimationFrame(function () { m.classList.add("on"); }); });
  }

  // ---------- banner, pips, situation ----------
  async function banner(text, g, ms) {
    var b = $("#banner");
    b.textContent = text;
    b.classList.add("on");
    try { await sleep(ms || 1100, g); } finally { b.classList.remove("on"); }
    await sleep(300, g);
  }
  function setPips(done, total, label) {
    var p = $("#pips");
    if (total == null) { p.innerHTML = label ? "<em>" + label + "</em>" : ""; return; }
    var html = label ? label + " " : "Hand ";
    for (var k = 0; k < total; k++) html += '<span class="' + (k < done ? "on" : "") + '"></span>';
    p.innerHTML = html;
  }
  function showSituation(s) {
    var el = $("#situation");
    el.innerHTML = esc(s.label) + ' <small>vs dealer ' + (s.upcard === "A" ? "ace" : esc(s.upcard)) + "</small>";
    el.style.opacity = 1;
  }

  // ---------- chips (the visitor's buttons) ----------
  var chipResolve = null;
  function setChips(legal) {
    $("#chips").style.display = legal ? "flex" : "none";
    $$("#chips .chip").forEach(function (b) {
      var act = b.dataset.act;
      b.disabled = !legal || legal.indexOf(act) < 0;
      b.classList.toggle("hide", act === "split" && (!legal || legal.indexOf("split") < 0));
    });
  }
  function waitChip(legal, g) {
    setChips(legal);
    return new Promise(function (resolve, reject) {
      var entry = { reject: function (e) { chipResolve = null; setChips(null); reject(e); } };
      pending.push(entry);
      chipResolve = function (act) {
        if (g !== gen || legal.indexOf(act) < 0) return;
        pending = pending.filter(function (p) { return p !== entry; });
        chipResolve = null; setChips(null);
        resolve(act);
      };
    });
  }
  $$("#chips .chip").forEach(function (b) {
    b.addEventListener("click", function (e) { e.stopPropagation(); if (chipResolve) chipResolve(b.dataset.act); });
  });

  // ---------- playing one deal (visitor or presenter) ----------
  async function playDeal(s, g, index, total) {
    await clearTable(g);
    hideCtas();
    if (state.presenter) setPips(null, null, "Presenter · hand " + (index + 1));
    else setPips(index, total);
    await banner(state.presenter ? "Hand " + (index + 1) : "Hand " + (index + 1) + " of " + total, g, 900);

    // The agents have already bet on this exact deal: their chips sit face down.
    ["baseline", "full"].forEach(function (k) {
      sealedChip(seats[k], s.seats[k]);
      seats[k].el.classList.add("dim");
    });
    var round = BJ.newRound(s.shoe, DATA.rule_set);
    var shown = await playEvents(seats.you, round.events, 0, g);
    showSituation(s);
    if (round.done) {       // a natural (scenario deals never are, but the engine allows it)
      showOutcome(seats.you, round);
      return { s: s, action: null, payout: round.payout };
    }
    var first = null;
    while (!round.done) {
      var act = await waitChip(BJ.legal(round), g);
      if (first === null) { first = act; placeChip(seats.you, act); }
      BJ.act(round, act);
      shown = await playEvents(seats.you, round.events, shown, g);
    }
    showOutcome(seats.you, round);
    return { s: s, action: first, payout: round.payout };
  }

  function pickDeals(n) {
    var pool = READY.filter(function (s) { return state.lastGameIds.indexOf(s.id) < 0; });
    if (pool.length < n) pool = READY.slice();
    var out = [];
    while (out.length < n && pool.length) out.push(pool.splice(Math.floor(Math.random() * pool.length), 1)[0]);
    return out;
  }

  async function startGame() {
    if (!READY.length) return showEmpty();
    var g = newFlow();
    setMode("play"); state.presenter = false; state.game = [];
    setPresenterUi(false);
    leaveOverlays();
    var deals = pickDeals(HANDS_PER_GAME);
    state.lastGameIds = deals.map(function (s) { return s.id; });
    try {
      for (var k = 0; k < deals.length; k++) {
        var hand = await playDeal(deals[k], g, k, deals.length);
        state.game.push(hand);
        setPips(k + 1, deals.length);
        await waitAdvance(k + 1 < deals.length ? "Next hand" : "See how you did", g);
      }
      postResults(state.game);
      await runReveal(state.game, g);
    } catch (e) { swallow(e); }
  }

  // ---------- the reveal ----------
  function seatEntry(s, k) { var e = s.seats[k]; return e && e.status === "answered" ? e : null; }

  async function revealHand(hand, g, index, total) {
    var s = hand.s;
    await clearTable(g);
    setPips(index, total, "Reveal");
    await banner("Hand " + (index + 1) + (total > 1 ? " of " + total : ""), g, 900);

    // 1. Re-deal the same starting cards to all three seats, the visitor's move on its chip.
    var start = BJ.newRound(s.shoe, DATA.rule_set);
    var opening = start.events.filter(function (ev) { return ev.type === "deal"; }).slice(0, 4);
    for (var k = 0; k < opening.length; k++) {
      var ev = opening[k];
      if (ev.to === "player") {
        for (var j = 0; j < 3; j++) {
          var key = ["baseline", "you", "full"][j];
          await playEvents(seats[key], [ev], 0, g, { speed: 0.6 });
        }
      } else {
        await playEvents(seats.you, [ev], 0, g, { speed: 0.7 });
      }
    }
    showSituation(s);
    placeChip(seats.you, hand.action);
    var chips = { baseline: sealedChip(seats.baseline, s.seats.baseline), full: sealedChip(seats.full, s.seats.full) };
    seats.baseline.thinkEl.classList.add("on"); seats.full.thinkEl.classList.add("on");
    await waitAdvance("Flip the AI chips", g);

    // 2. Baseline flips, then the Full harness.
    seats.baseline.thinkEl.classList.remove("on");
    chips.baseline.classList.add("open");
    await sleep(900, g);
    seats.full.thinkEl.classList.remove("on");
    chips.full.classList.add("open");
    await sleep(900, g);
    await waitAdvance("Show basic strategy", g);

    // 3. The basic strategy seal stamps in.
    $("#sealAct").textContent = ACT_LABEL[s.basic];
    $("#seal").classList.add("on");
    await sleep(700, g);
    await waitAdvance("Score it", g);

    // 4. ✓ / ✗ on each seat.
    mark(seats.you, hand.action === s.basic);
    await sleep(380, g);
    ["baseline", "full"].forEach(function (k2, n) {
      var e = seatEntry(s, k2);
      setTimeout(function () { if (e) mark(seats[k2], !!e.correct); }, 380 * n);
    });
    await sleep(900, g);
    await waitAdvance("Play it out", g);

    // 5. Each agent seat's hand plays out card by card against its own dealer draws.
    $("#seal").classList.remove("on");
    for (var n = 0; n < 2; n++) {
      var seatKey = ["baseline", "full"][n], entry = seatEntry(s, seatKey);
      if (!entry) continue;
      var round = BJ.replay(s.shoe, entry.decisions.map(function (d) { return d.action; }), DATA.rule_set);
      resetDealerTo(start);
      $("#dealerFor").textContent = "· vs " + SEAT_NAME[seatKey];
      seats[seatKey].el.classList.remove("dim");
      var other = seats[seatKey === "baseline" ? "full" : "baseline"];
      other.el.classList.add("dim"); seats.you.el.classList.add("dim");
      // skip the four opening deals, already on the table
      var evs = round.events, skip = 0, seen = 0;
      while (seen < 4) { if (evs[skip].type === "deal") seen++; skip++; }
      resetSeatHand(seats[seatKey], s);
      await playEvents(seats[seatKey], evs, skip, g, { speed: 1.15 });
      showOutcome(seats[seatKey], round);
      await sleep(1300, g);
    }
    Object.keys(seats).forEach(function (k3) { seats[k3].el.classList.remove("dim"); });
    $("#dealerFor").textContent = "";
  }
  function resetDealerTo(start) {
    var cards = $(".cards", dealer.el);
    cards.innerHTML = "";
    dealer.cards = []; dealer.down = null; dealer.revealed = false;
    start.dealer.slice(0, 2).forEach(function (c, i) {
      var el = cardEl(c, i === 1);
      cards.appendChild(el);
      dealer.cards.push(c.r);
      if (i === 1) dealer.down = el;
    });
    showDealerTotal();
  }
  function resetSeatHand(seat, s) {
    // back to the two opening cards (a fresh view, so a split builds from scratch)
    var opening = BJ.newRound(s.shoe, DATA.rule_set).hands[0].cards;
    seat.handsEl.innerHTML = ""; seat.handsEl.classList.remove("split"); seat.hands = [];
    var v = handView(seat, 0);
    opening.forEach(function (c) { v.cardsEl.appendChild(cardEl(c, false)); v.ranks.push(c.r); });
    showTotal(v.totEl, v.ranks);
  }

  async function runReveal(hands, g) {
    setMode("reveal");
    $("#attract").classList.add("hide");
    for (var k = 0; k < hands.length; k++) {
      await revealHand(hands[k], g, k, hands.length);
      await waitAdvance(k + 1 < hands.length ? "Next hand" : "See the score", g);
    }
    await clearTable(g);
    setPips(null, null, "");
    await showTally(hands, g);
    showResults(hands);
  }

  // ---------- score tally and results ----------
  function scoreOf(hands) {
    var out = { you: 0, baseline: 0, full: 0, n: hands.length };
    hands.forEach(function (h) {
      if (h.action === h.s.basic) out.you++;
      ["baseline", "full"].forEach(function (k) { var e = seatEntry(h.s, k); if (e && e.correct) out[k]++; });
    });
    return out;
  }
  function verdictOf(sc) {
    var best = Math.max(sc.baseline, sc.full);
    if (sc.you > best) return "You beat the AI!";
    if (sc.you === best && sc.you === sc.n) return "Perfect. You matched basic strategy every time.";
    if (sc.you === best) return "Dead even with the AI.";
    if (sc.full > sc.baseline) return "The Full harness takes it.";
    if (sc.baseline > sc.full) return "Baseline takes it.";
    return "The AI takes this one.";
  }
  async function showTally(hands, g) {
    setMode("tally");
    var sc = scoreOf(hands);
    $("#scrim").classList.add("on");
    var row = $("#tallyRow"); row.innerHTML = "";
    ["you", "baseline", "full"].forEach(function (k) {
      var d = document.createElement("div");
      d.className = "who";
      d.innerHTML = '<span style="color:var(--' + (k === "you" ? "you" : k === "baseline" ? "base" : "full") + ')">' + SEAT_NAME[k] +
        "</span><b>" + sc[k] + "<small>/" + sc.n + "</small></b>";
      row.appendChild(d);
    });
    $("#verdict").textContent = verdictOf(sc);
    $("#verdict").classList.remove("on");
    $("#tally").classList.add("on");
    var whos = $$("#tallyRow .who");
    for (var k = 0; k < whos.length; k++) { await sleep(450, g); whos[k].classList.add("on"); }
    await sleep(600, g);
    $("#verdict").classList.add("on");
    await waitAdvance("See every hand", g);
    $("#tally").classList.remove("on");
  }

  function actCell(action, basic, invalid) {
    if (invalid) return '<span class="act inv">invalid ✗</span>';
    if (!action) return '<span class="act na">—</span>';
    return '<span class="act ' + (action === basic ? "ok" : "no") + '">' + ACT_LABEL[action] + "</span>";
  }
  function miniCards(ranks) {
    return ranks.map(function (r) { return "<span>" + (r === "10" ? "10" : r) + "</span>"; }).join("");
  }
  function seatCell(s, k) {
    var e = seatEntry(s, k);
    if (!e) return '<span class="act na">not run yet</span>';
    return actCell(e.action, s.basic, e.invalid);
  }
  function reasoningBox(s, k) {
    var e = seatEntry(s, k), c = k === "baseline" ? "var(--base)" : "var(--full)";
    if (!e) return '<div class="why" style="--c:' + c + '"><h4>' + SEAT_NAME[k] + "</h4>Not run yet.</div>";
    var html = '<div class="why" style="--c:' + c + '"><h4>' + SEAT_NAME[k] + " said</h4>" + esc(e.reasoning || "(no reply)");
    if (e.invalid) html += '<span class="flip">No valid action in this reply (' + esc(e.invalid_reason || "invalid") + "), so the hand stood.</span>";
    var se = e.self_eval;
    if (se) {
      if (se.flipped) html += '<span class="flip">Flip: first said ' + esc(ACT_LABEL[se.first_action] || "nothing valid") + ", changed to " + esc(ACT_LABEL[se.second_action] || "nothing valid") + " on the re-check.</span>";
      html += '<span class="first">First answer, before the re-check: ' + esc(se.first_raw || "") + "</span>";
    }
    return html + "</div>";
  }
  function oddsBox(s) {
    var e = seatEntry(s, "full");
    if (!e || !e.odds) return '<div class="why odds" style="--c:var(--gold)"><h4>The odds</h4>' + (e && e.odds_text ? esc(e.odds_text) : "Not available.") + "</div>";
    var o = e.odds, html = '<div class="why odds" style="--c:var(--gold)"><h4>The odds the Full harness saw</h4>';
    if (o.bust_if_hit != null) html += '<div class="oddsline"><span>Bust if you hit</span><span class="bustbig">' + fmtPct(o.bust_if_hit) + "</span></div>";
    if (o.dealer && o.dealer.length) {
      html += '<div>Dealer ends on</div><div class="dist">';
      o.dealer.forEach(function (d) {
        html += "<span>" + esc(d[0]) + '</span><span class="b"><i class="' + (d[0] === "bust" ? "bust" : "") + '" data-w="' + d[1] + '"></i></span><span>' + fmtPct(d[1]) + "</span>";
      });
      html += "</div>";
    }
    if (o.stand) html += '<div class="standrow">If you stand: <span>win <b>' + fmtPct(o.stand.win) + "</b></span><span>push <b>" + fmtPct(o.stand.push) + "</b></span><span>lose <b>" + fmtPct(o.stand.lose) + "</b></span></div>";
    return html + "</div>";
  }
  function fmtPct(v) { return v == null ? "—" : (Math.round(v * 10) / 10) + "%"; }

  function showResults(hands) {
    setMode("results");
    var sc = scoreOf(hands);
    $("#score").innerHTML = ["you", "baseline", "full"].map(function (k) {
      return '<span style="color:var(--' + (k === "you" ? "you" : k === "baseline" ? "base" : "full") + ')">' + SEAT_NAME[k] + "<b>" + sc[k] + "/" + sc.n + "</b></span>";
    }).join("");
    var body = $("#resBody"); body.innerHTML = "";
    hands.forEach(function (h) {
      var s = h.s, tr = document.createElement("tr");
      tr.className = "row";
      tr.innerHTML = '<td><span class="minicards">' + miniCards(s.player) + "<em>vs</em>" + miniCards([s.upcard]) + '</span><span class="rowlabel">' + esc(s.label) + "</span></td>" +
        "<td>" + actCell(h.action, s.basic, false) + "</td><td>" + seatCell(s, "baseline") + "</td><td>" + seatCell(s, "full") +
        '</td><td class="basic">' + ACT_LABEL[s.basic] + "</td>";
      var det = document.createElement("tr");
      det.className = "detail";
      det.innerHTML = '<td colspan="5"><div class="detail-in"><div><div class="dgrid">' + reasoningBox(s, "baseline") + reasoningBox(s, "full") + oddsBox(s) + "</div></div></div></td>";
      tr.addEventListener("click", function () {
        var open = !tr.classList.contains("open");
        tr.classList.toggle("open", open); det.classList.toggle("open", open);
        if (open) setTimeout(function () { $$(".dist i", det).forEach(function (i) { i.style.width = Math.min(100, parseFloat(i.dataset.w)) + "%"; }); }, 60);
      });
      body.appendChild(tr); body.appendChild(det);
    });
    $("#againBtn").textContent = state.presenter ? "Back to presenter" : "Play again";
    renderBoard();
    $("#scrim").classList.add("on");
    $("#results").classList.add("on");
    hideCtas(); setChips(null);
  }
  function leaveOverlays() {
    $("#results").classList.remove("on");
    $("#tally").classList.remove("on");
    $("#scrim").classList.remove("on");
    $("#attract").classList.add("hide");
    $("#empty").classList.add("hide");
  }
  $("#againBtn").addEventListener("click", function (e) {
    e.stopPropagation();
    if (state.presenter) { leaveOverlays(); setMode("play"); openPanel(); }
    else startGame();
  });

  // ---------- live board ----------
  function localBoard() {
    var v = [0, 0], b = [0, 0], f = [0, 0];
    state.localResults.forEach(function (game) {
      game.forEach(function (h) {
        v[0] += h.action === h.s.basic ? 1 : 0; v[1]++;
        var eb = seatEntry(h.s, "baseline"), ef = seatEntry(h.s, "full");
        if (eb) { b[0] += eb.correct ? 1 : 0; b[1]++; }
        if (ef) { f[0] += ef.correct ? 1 : 0; f[1]++; }
      });
    });
    function t(x) { return { correct: x[0], total: x[1], accuracy: x[1] ? x[0] / x[1] : null }; }
    return { visitors: state.localResults.length, deals_played: v[1], visitor: t(v), baseline: t(b), full: t(f) };
  }
  function fetchBoard() {
    return fetch("api/board", { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("board " + r.status);
      return r.json();
    }).then(function (b) { state.board = b; state.online = true; renderBoard(); })
      .catch(function () { state.online = false; state.board = localBoard(); renderBoard(); });
  }
  function postResults(game) {
    if (state.presenter) return;
    var deals = game.filter(function (h) { return h.action; }).map(function (h) { return { id: h.s.id, action: h.action }; });
    if (!deals.length) return;
    state.localResults.push(game);
    fetch("api/results", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ deals: deals }) })
      .then(function (r) { if (!r.ok) throw new Error("post " + r.status); return r.json(); })
      .then(function (res) { state.board = res.board; state.online = true; renderBoard(); })
      .catch(function () { state.online = false; state.board = localBoard(); renderBoard(); });
  }
  function pctText(t) { return t && t.accuracy != null ? Math.round(t.accuracy * 100) + "%" : "—"; }
  function pctWidth(t) { return t && t.accuracy != null ? Math.round(t.accuracy * 100) + "%" : "0%"; }
  function renderBoard() {
    var b = state.board || localBoard();
    var live = $("#live");
    live.textContent = state.online ? "LIVE" : "OFFLINE";
    live.classList.toggle("off", !state.online);
    ["visitor", "baseline", "full"].forEach(function (k) {
      var st = $('.plaque .stat[data-who="' + k + '"]');
      $("em", st).textContent = pctText(b[k]);
      $(".bar b", st).style.width = pctWidth(b[k]);
    });
    var n = b.visitors || 0;
    $("#plaqueN").textContent = n + (n === 1 ? " visitor" : " visitors");
    var rows = [["visitor", "Visitors", "var(--you)"], ["baseline", "Baseline", "var(--base)"], ["full", "Full harness", "var(--full)"]];
    [$("#attractBoard"), $("#resultsBoard")].forEach(function (box) {
      if (!box.firstChild) {   // build once; later renders only move the bars
        var html = '<div class="title">Who plays it by the book? <small>First moves that match basic strategy, over the same hands</small></div>';
        rows.forEach(function (row) {
          html += '<div class="col" data-who="' + row[0] + '"><div class="top"><span class="who">' + row[1] + '</span><span class="pct" style="color:' + row[2] +
            '">—</span></div><div class="bar"><b style="background:' + row[2] + '"></b></div></div>';
        });
        box.innerHTML = html + '<div class="foot"><span class="info"></span><span>The agents played these exact hands earlier (' + esc(DATA && DATA.model || "qwen2.5:7b") + ").</span></div>";
      }
      rows.forEach(function (row) {
        var col = $('.col[data-who="' + row[0] + '"]', box);
        $(".pct", col).textContent = pctText(b[row[0]]);
        var bar = $(".bar b", col);
        requestAnimationFrame(function () { requestAnimationFrame(function () { bar.style.width = pctWidth(b[row[0]]); }); });
      });
      $(".foot .info", box).textContent = (state.online ? "Live board" : "Board offline: this screen only") + " · " + n + (n === 1 ? " visitor" : " visitors") +
        " · " + (b.deals_played || 0) + " hands";
    });
  }

  // ---------- attract mode ----------
  async function startAttract() {
    if (!READY.length) return showEmpty();
    var g = newFlow();
    setMode("attract"); state.presenter = false;
    setPresenterUi(false); closePanel();
    leaveOverlays(); hideCtas(); setChips(null);
    $("#attract").classList.remove("hide");
    setPips(null, null, "");
    fetchBoard();
    try {
      var sp = 1.8;
      for (;;) {
        var s = READY[Math.floor(Math.random() * READY.length)];
        await clearTable(g);
        seats.you.el.classList.add("dim");
        var start = BJ.newRound(s.shoe, DATA.rule_set);
        var opening = start.events.filter(function (ev) { return ev.type === "deal"; }).slice(0, 4);
        for (var k = 0; k < opening.length; k++) {
          var ev = opening[k];
          if (ev.to === "player") {
            await playEvents(seats.baseline, [ev], 0, g, { speed: sp });
            await playEvents(seats.full, [ev], 0, g, { speed: sp });
          } else await playEvents(seats.you, [ev], 0, g, { speed: sp });
        }
        showSituation(s);
        var chips = { baseline: sealedChip(seats.baseline, s.seats.baseline), full: sealedChip(seats.full, s.seats.full) };
        seats.baseline.thinkEl.classList.add("on"); seats.full.thinkEl.classList.add("on");
        await sleep(2600, g);
        seats.baseline.thinkEl.classList.remove("on"); chips.baseline.classList.add("open");
        await sleep(1400, g);
        seats.full.thinkEl.classList.remove("on"); chips.full.classList.add("open");
        await sleep(1800, g);
        $("#sealAct").textContent = ACT_LABEL[s.basic];
        $("#seal").classList.add("on");
        await sleep(1400, g);
        ["baseline", "full"].forEach(function (k2) { var e = seatEntry(s, k2); if (e) mark(seats[k2], !!e.correct); });
        await sleep(4200, g);
      }
    } catch (e) { swallow(e); }
  }

  // ---------- presenter mode ----------
  function setPresenterUi(on) {
    $("#presTag").classList.toggle("hide", !on);
  }
  async function enterPresenter() {
    if (!DATA) return;
    var g = newFlow();
    state.presenter = true; setMode("play"); state.session = [];
    setPresenterUi(true);
    leaveOverlays(); hideCtas(); setChips(null);
    try { await clearTable(g); } catch (e) { swallow(e); }
    setPips(null, null, "Presenter");
    updateSession();
    openPanel();
  }
  function exitPresenter() {
    state.presenter = false;
    closePanel();
    if (location.hash === "#presenter") history.replaceState(null, "", location.pathname + location.search);
    startAttract();
  }
  function openPanel() { $("#panel").classList.add("on"); setTimeout(function () { $("#search").focus(); }, 300); }
  function closePanel() { $("#panel").classList.remove("on"); $("#search").blur(); }
  function updateSession() {
    var n = state.session.length;
    $("#sessionInfo").textContent = n + (n === 1 ? " hand played" : " hands played") + " · not posted to the board";
    $("#seeResultsBtn").disabled = !n;
    $("#seeResultsBtn").style.opacity = n ? 1 : 0.4;
  }
  async function presenterPlay(s) {
    if (!s || !s.ready) return;
    closePanel();
    var g = newFlow();
    setMode("play");
    leaveOverlays();
    try {
      var hand = await playDeal(s, g, state.session.length);
      state.session.push(hand);
      updateSession();
      setCtas([
        { label: "Next deal", cls: "next", fn: function () { openPanel(); } },
        { label: "Random", cls: "ghost", fn: function () { presenterPlay(randomReady()); } },
        { label: "See results", cls: "ghost", fn: presenterResults },
      ]);
    } catch (e) { swallow(e); }
  }
  function presenterResults() {
    if (!state.session.length) return;
    closePanel();
    var g = newFlow();
    leaveOverlays(); hideCtas();
    runReveal(state.session.slice(), g).catch(swallow);
  }
  function randomReady() { return READY[Math.floor(Math.random() * READY.length)]; }

  function buildChart() {
    var ups = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"];
    var groups = [["hard", "Hard totals"], ["soft", "Soft totals"], ["pair", "Pairs"]];
    var html = '<table><thead><tr><th class="rh">You \\ dealer</th>' + ups.map(function (u) { return "<th>" + u + "</th>"; }).join("") + "</tr></thead><tbody>";
    groups.forEach(function (grp) {
      html += '<tr class="grp"><td colspan="11">' + grp[1] + "</td></tr>";
      var rows = [];
      DATA.scenarios.forEach(function (s) { if (s.kind === grp[0] && rows.indexOf(String(s.row)) < 0) rows.push(String(s.row)); });
      rows.forEach(function (row) {
        var label = null, cells = "";
        ups.forEach(function (u) {
          var s = DATA.scenarios.filter(function (x) { return x.kind === grp[0] && String(x.row) === row && x.upcard === u; })[0];
          if (!s) { cells += "<td></td>"; return; }
          label = label || s.label;
          var code = { hit: "H", stand: "S", double: "D", split: "P" }[s.basic];
          cells += '<td><button class="cell ' + code + '" data-id="' + esc(s.id) + '"' + (s.ready ? "" : " disabled") +
            ' title="' + esc(s.label + " vs " + u + (s.ready ? "" : " (Full harness not run yet)")) + '">' + code + "</button></td>";
        });
        html += '<tr><td class="rh">' + esc(label || row) + "</td>" + cells + "</tr>";
      });
    });
    $("#chart").innerHTML = html + "</tbody></table>";
  }
  $("#chart").addEventListener("click", function (e) {
    var b = e.target.closest("button.cell");
    if (b && !b.disabled) presenterPlay(BY_ID[b.dataset.id]);
  });
  function search(q) {
    q = q.toLowerCase().replace(/\bv\b|\bvs\.?\b|versus/g, " vs ").replace(/\s+/g, " ").trim();
    var box = $("#matches");
    $$("#chart button.cell.hl").forEach(function (b) { b.classList.remove("hl"); });
    if (!q) { box.innerHTML = ""; return; }
    var tokens = q.split(" ").filter(function (t) { return t && t !== "vs" && t !== "of" && t !== "dealer"; });
    var hits = DATA.scenarios.filter(function (s) {
      var up = s.upcard === "A" ? "a ace" : s.upcard;
      var hay = (s.label + " " + s.kind + " " + s.row + (s.kind === "pair" ? " pair pairs" : "") + " |" + up + " " + s.id).toLowerCase();
      var parts = hay.split("|"), left = parts[0].split(/\s+/), right = parts[1].split(/\s+/);
      // a token matches a whole word; the last number-like token is the upcard
      var nums = tokens.filter(function (t) { return /^(\d+|a|ace|aces)$/.test(t); });
      var words = tokens.filter(function (t) { return nums.indexOf(t) < 0; });
      var okWords = words.every(function (w) { return left.some(function (x) { return x.indexOf(w.replace(/s$/, "")) === 0; }); });
      if (!okWords) return false;
      if (nums.length >= 2) {
        var a = nums[0].replace(/s$/, "").replace("ace", "a"), b2 = nums[nums.length - 1].replace("ace", "a");
        return left.indexOf(a) >= 0 && right.indexOf(b2) >= 0;
      }
      if (nums.length === 1) { var n1 = nums[0].replace(/s$/, "").replace("ace", "a"); return left.indexOf(n1) >= 0; }
      return true;
    });
    var shown = hits.slice(0, 14);
    box.innerHTML = shown.map(function (s) {
      return '<button data-id="' + esc(s.id) + '"' + (s.ready ? "" : ' disabled style="opacity:.4"') + ">" + esc(s.label) + " vs " + esc(s.upcard) + "</button>";
    }).join("") + (hits.length > shown.length ? "<span>+" + (hits.length - shown.length) + " more</span>" : "") + (!hits.length ? "<span>No match</span>" : "");
    hits.forEach(function (s) { var c = $('#chart button.cell[data-id="' + s.id + '"]'); if (c) c.classList.add("hl"); });
  }
  $("#search").addEventListener("input", function (e) { search(e.target.value); });
  $("#search").addEventListener("keydown", function (e) {
    e.stopPropagation();
    if (e.key === "Enter") { var first = $("#matches button:not([disabled])"); if (first) presenterPlay(BY_ID[first.dataset.id]); }
    if (e.key === "Escape") closePanel();
  });
  $("#matches").addEventListener("click", function (e) { var b = e.target.closest("button"); if (b && !b.disabled) presenterPlay(BY_ID[b.dataset.id]); });
  $("#randomBtn").addEventListener("click", function () { presenterPlay(randomReady()); });
  $("#seeResultsBtn").addEventListener("click", presenterResults);
  $("#closePanelBtn").addEventListener("click", closePanel);
  $("#exitPresBtn").addEventListener("click", exitPresenter);
  $("#panel").addEventListener("click", function (e) { e.stopPropagation(); });

  // ---------- input ----------
  function touch() { state.lastInput = Date.now(); }
  document.addEventListener("pointerdown", touch, true);
  document.addEventListener("keydown", touch, true);

  document.addEventListener("keydown", function (e) {
    if (e.shiftKey && e.altKey && e.code === "KeyP") {
      e.preventDefault();
      if (state.presenter) exitPresenter(); else enterPresenter();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey || /^(Shift|Alt|Meta|Control|CapsLock|Tab)$/.test(e.key)) return;
    if (state.mode === "attract") { e.preventDefault(); startGame(); return; }
    var keyAct = { h: "hit", s: "stand", d: "double", p: "split" }[e.key.toLowerCase()];
    if (keyAct && chipResolve) { chipResolve(keyAct); return; }
    if ((e.key === " " || e.key === "Enter" || e.key === "ArrowRight") && advanceHook) { e.preventDefault(); advanceHook(); }
    if (e.key === "Escape" && state.presenter) openPanel();
  });
  canvas.addEventListener("click", function (e) {
    if (e.target.closest("button, .results, .panel, input")) return;
    if (state.mode === "attract") { startGame(); return; }
    if (state.mode === "empty") return;
    if (advanceHook) advanceHook();
  });
  window.addEventListener("hashchange", function () {
    if (location.hash !== "#presenter") return;
    if (!state.presenter) enterPresenter(); else openPanel();
  });

  setInterval(function () {
    if (state.presenter || state.mode === "attract" || state.mode === "empty" || state.mode === "loading") return;
    var limit = state.mode === "play" ? IDLE_GAME_MS : IDLE_MS;
    if (Date.now() - state.lastInput > limit) startAttract();
  }, 1000);
  setInterval(function () { if (!state.presenter) fetchBoard(); }, BOARD_POLL_MS);

  // ---------- empty / error ----------
  function showEmpty(title, text) {
    newFlow();
    setMode("empty");
    $("#emptyTitle").textContent = title || "No deals ready yet";
    $("#emptyText").innerHTML = text || "Neither agent seat has a deal both of them have answered.<br>Run <code>scripts/export_demo_data.py</code> again once the Full harness run has hands in it.";
    $("#empty").classList.remove("hide");
  }
  function esc(t) {
    return String(t).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }

  // ---------- boot ----------
  fetch("demo_data.json", { cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error("demo_data.json " + r.status);
    return r.json();
  }).then(function (data) {
    DATA = data;
    READY = data.scenarios.filter(function (s) { return s.ready; });
    data.scenarios.forEach(function (s) { BY_ID[s.id] = s; });
    if (data.model) $("#modelName").textContent = data.model;
    buildChart();
    fetchBoard();
    if (!READY.length) { showEmpty(); if (location.hash === "#presenter") enterPresenter(); return; }
    if (location.hash === "#presenter") enterPresenter(); else startAttract();
  }).catch(function (err) {
    console.warn(err);
    showEmpty("Demo data not found", "Start the demo with <code>.venv/bin/python scripts/demo_server.py</code> and open <code>http://localhost:8000</code>.<br>If it still fails, run <code>scripts/export_demo_data.py</code> first.");
  });

  // for the end-to-end check
  window.__demo = { state: state, get gen() { return gen; } };
})();
