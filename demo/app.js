/* Showcase demo: "Can you beat the AI?"
 *
 * A Visitor plays three random deals from the scenario set, one first decision each,
 * against two agent Seats that played the exact same cards earlier: Baseline and the
 * Full harness. All three Seats get the same opening cards. As soon as the visitor's hand
 * is done, the same table reveals, with no taps, what each agent chose, what basic
 * strategy says, and how each Seat's hand played out; then the next hand starts on its own.
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
    revealing: false,      // the automatic reveal sequence is running (a tap fast-forwards it)
    phase: "",             // reveal step, for the end-to-end check: flip seal marks playout dealer hold
  };
  var scale = 1;
  function setMode(m) { state.mode = m; canvas.dataset.mode = m; }

  // ---------- generations, waits ----------
  var gen = 0, pending = [];
  function newFlow() {
    gen++;
    var old = pending; pending = [];
    old.forEach(function (p) { p.reject(ABORT); });
    state.revealing = false;
    if (typeof ff !== "undefined" && ff) ff.on = false;
    var tn = document.getElementById("tapnote");
    if (tn) tn.classList.add("hide");
    return gen;
  }
  function ck(g) { if (g !== gen) throw ABORT; }
  function sleep(ms, g) {
    if (ff.on) { ms *= FF_TEMPO; hurryAnimations(); }
    return new Promise(function (resolve, reject) {
      var entry = { reject: reject };
      function done() {
        pending = pending.filter(function (p) { return p !== entry; });
        if (g !== gen) reject(ABORT); else resolve();
      }
      var t = setTimeout(done, ms);
      entry.wake = function () { clearTimeout(t); done(); };
      pending.push(entry);
    });
  }

  // ---------- fast-forward (a tap during the reveal sequence) ----------
  // The sequence keeps every step but runs them at FF_TEMPO: pending waits end now, and
  // running card/chip/seal animations finish fast.
  var FF_TEMPO = 0.3;
  var ff = { on: false };
  function tempo() { return ff.on ? FF_TEMPO : 1; }
  function hurryAnimations() {
    if (!document.getAnimations) return;
    document.getAnimations().forEach(function (a) {
      var t = a.effect && a.effect.target;
      if (!t || !t.closest || !t.closest(".seat, .dealer, .seal")) return;
      if (a.effect.getTiming().iterations === Infinity) return;
      a.playbackRate = 1 / FF_TEMPO;
    });
  }
  function fastForward() {
    if (!state.revealing || ff.on) return;
    ff.on = true;
    $("#tapnote").classList.add("hide");
    hurryAnimations();
    pending.slice().forEach(function (p) { if (p.wake) p.wake(); });
  }
  function swallow(e) { if (e !== ABORT) { console.error(e); } }

  // One "advance" at a time: the big Next button, Space/Enter/→, and (unless opts.noTap)
  // a tap anywhere. opts.countdown (ms) advances on its own and draws a ring on the button.
  var advanceHook = null, advanceTap = false;
  function waitAdvance(label, g, opts) {
    opts = opts || {};
    return new Promise(function (resolve, reject) {
      var timer = null;
      var entry = { reject: function (e) { clearTimeout(timer); advanceHook = null; hideCtas(); reject(e); } };
      pending.push(entry);
      setCtas([{ label: label, cls: "next", fn: go, countdown: opts.countdown }].concat(opts.extra || []));
      $("#tapnote").textContent = "or tap anywhere";
      $("#tapnote").classList.toggle("hide", !!opts.noTap);
      advanceHook = go; advanceTap = !opts.noTap;
      if (opts.countdown) timer = setTimeout(go, opts.countdown);
      function go() {
        if (g !== gen) return;
        clearTimeout(timer);
        pending = pending.filter(function (p) { return p !== entry; });
        advanceHook = null; hideCtas();
        resolve();
      }
    });
  }
  var RING = '<svg class="ring" viewBox="0 0 40 40" aria-hidden="true"><circle class="track" cx="20" cy="20" r="16"/><circle class="prog" cx="20" cy="20" r="16" pathLength="100"/></svg>';
  function setCtas(list) {
    var box = $("#ctas"); box.innerHTML = "";
    list.forEach(function (b) {
      var el = document.createElement("button");
      el.className = "cta " + (b.cls || "");
      el.textContent = b.label;
      if (b.countdown) {
        el.classList.add("timed");
        el.style.setProperty("--count", b.countdown + "ms");
        el.insertAdjacentHTML("beforeend", RING);
      }
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
      '<div class="cn tl' + (r === "10" ? " ten" : "") + '">' + r + "<small>" + s + "</small></div>" +
      (court ? '<div class="court">' + r + "</div>" : '<div class="pip">' + s + "</div>") +
      '<div class="cn br' + (r === "10" ? " ten" : "") + '">' + r + "<small>" + s + "</small></div></div>" +
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
    var loneAce = ranks.length === 1 && ranks[0] === "A";
    totEl.textContent = bj ? "BJ" : loneAce ? "A" : String(t.total);
    totEl.classList.toggle("soft", t.soft && t.total < 21 && !bj && !loneAce);
    totEl.classList.toggle("bust", t.total > 21);
    totEl.classList.add("on");
  }

  function clearSeat(seat) {
    seat.handsEl.innerHTML = "";
    seat.handsEl.classList.remove("split");
    seat.hands = [];
    seat.slotEl.innerHTML = "";
    seat.slotEl.classList.remove("out");
    if (seat.theirEl) seat.theirEl.classList.remove("on");
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
    $$(".badge.on, .tot.on, .seat > .their.on").forEach(function (b) { b.classList.remove("on"); });
    if (!keepSlots) Object.keys(seats).forEach(function (k) { seats[k].slotEl.classList.add("out"); });
    $("#seal").classList.remove("on");
    canvas.classList.remove("quiet");
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

  function speedOf(opts) { return ((opts && opts.speed) || 1) * tempo(); }

  /** Run `mutate`, then slide `els` from where they were to where the new layout puts
   * them (FLIP), so a seat that widens as cards land glides instead of jumping. */
  function glide(els, mutate, dur) {
    var before = els.map(function (e) { return e.getBoundingClientRect(); });
    mutate();
    els.forEach(function (e, i) {
      if (!e.isConnected || !e.animate) return;
      var a = before[i], b = e.getBoundingClientRect();
      var dx = (a.left - b.left) / scale, dy = (a.top - b.top) / scale;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      e.animate([{ transform: "translate(" + dx + "px," + dy + "px)" }, { transform: "none" }], { duration: dur || 320, easing: "cubic-bezier(.2,.8,.2,1)" });
    });
  }
  function seatMovers(seat) { return $$(".hand, .side", seat.el); }
  function setCount(cardsEl) { cardsEl.dataset.n = cardsEl.children.length; }

  // Widest each seat's cards may get before they start to collide with a neighbour seat
  // (canvas px): the agents' hands stack under their chip, the visitor's sit beside it.
  var SEAT_MAX = { you: 610, baseline: 460, full: 460 };
  /** Tighten the card overlap of a seat whose hands outgrow their room (many cards, or a
   * split), so a long hand fans tighter instead of running into the next seat. */
  function fitSeat(seat) {
    var el = seat.el, box = seat.key === "you" ? $(".seat-body", el) : seat.handsEl;
    var max = SEAT_MAX[seat.key] || 480, gaps = 0, cw = 0, margins = 0;
    // The overlap margins may be mid-transition, so take the width without them and
    // work out the overlap that brings the seat back inside its room.
    $$(".cards", el).forEach(function (c) {
      if (!cw && c.firstElementChild) cw = parseFloat(getComputedStyle(c.firstElementChild).width);
      // a sideways (doubled) card keeps its own fixed spacing, so only the upright ones can tighten
      for (var i = 1; i < c.children.length; i++) {
        if (c.children[i].classList.contains("sideways")) continue;
        gaps++;
        margins += parseFloat(getComputedStyle(c.children[i]).marginLeft) || 0;
      }
    });
    if (!gaps || !cw) { el.style.removeProperty("--ov"); return; }
    var bare = box.offsetWidth - margins;
    var ov = Math.max(-0.76, Math.min(-0.5, (max - bare) / (gaps * cw)));
    el.style.setProperty("--ov", ov.toFixed(3));
  }

  /** Animate engine events [from, ...) for one seat and the dealer. With opts.stopAtDealer
   * it stops at the dealer's turn (the hole card reveal) and returns that event's index. */
  async function playEvents(seat, events, from, g, opts) {
    var shoe = $("#shoe");
    for (var k = from; k < events.length; k++) {
      var ev = events[k], sp = speedOf(opts);
      ck(g);
      if (opts && opts.stopAtDealer && (ev.type === "reveal" || ev.type === "settle")) return k;
      if (ev.type === "deal" && ev.to === "player") {
        var view = seat.hands[ev.hand], el = cardEl(ev.card, false);
        // before the glide, so fitSeat already sees the doubled card as sideways
        var rh = opts && opts.round && opts.round.hands[ev.hand];
        if (rh && rh.doubled && view && view.ranks.length === 2) el.classList.add("sideways");
        glide(seatMovers(seat), function () {
          view = view || handView(seat, ev.hand);
          view.cardsEl.appendChild(el);
          setCount(view.cardsEl);
          fitSeat(seat);
        }, 380 * sp);
        view.ranks.push(ev.card.r);
        var landed = view.ranks.length;
        await flyFrom(el, shoe, { dur: 520 * sp });
        showTotal(view.totEl, view.ranks.slice(0, Math.max(landed, view.totEl.dataset.n | 0)), { noBJ: seat.hands.length > 1 });
        view.totEl.dataset.n = Math.max(landed, view.totEl.dataset.n | 0);
        await sleep(120 * sp, g);
      } else if (ev.type === "deal") {
        var del = cardEl(ev.card, !!ev.down), dcards = $(".cards", dealer.el);
        glide([dealer.el], function () { dcards.appendChild(del); setCount(dcards); }, 380 * sp);
        dealer.cards.push(ev.card.r);
        if (ev.down) dealer.down = del;
        await flyFrom(del, shoe, { dur: 520 * sp });
        showDealerTotal();
        await sleep(160 * sp, g);
      } else if (ev.type === "split") {
        var src = seat.hands[ev.hand], moved = src.cardsEl.lastElementChild, nv = null;
        glide(seatMovers(seat), function () {
          seat.handsEl.classList.add("split");
          nv = handView(seat, ev.hand + 1);
          nv.cardsEl.appendChild(moved);
          setCount(src.cardsEl); setCount(nv.cardsEl);
          fitSeat(seat);
        }, 420 * sp);
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
        await sleep(400 * sp, g);
        showDealerTotal();
        await sleep(250 * sp, g);
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
  /** Outcome badges under each of the seat's hands. `note` (optional) is a second line,
   * used when this seat's dealer drew different cards from the dealer on the table. */
  function showOutcome(seat, round, note) {
    round.hands.forEach(function (h, i) {
      var v = seat.hands[i];
      if (!v) return;
      var word = h.result, amt = h.payout, bust = BJ.handTotal(v.ranks).total > 21;
      var neg = "\u2212" + Math.abs(amt);
      var text = word === "win" ? (amt === 1.5 ? "Blackjack +1.5" : "Win +" + amt) : word === "loss" ? "Lose " + neg : "Push";
      if (bust) text = "Bust " + neg;
      v.badgeEl.className = "badge " + word;
      v.badgeEl.innerHTML = "<span>" + nums(text) + "</span>";
      v.badgeEl.classList.add("on");
    });
    // this seat's dealer drew different cards: one pill under the seat (unless every hand bust)
    var live = seat.hands.some(function (v) { return BJ.handTotal(v.ranks).total <= 21; });
    if (note && live) {
      if (!seat.theirEl) { seat.theirEl = document.createElement("div"); seat.theirEl.className = "their"; seat.el.appendChild(seat.theirEl); }
      seat.theirEl.innerHTML = nums(note);
      seat.theirEl.classList.add("on");
    }
  }

  // ---------- chips on the slots ----------
  function miniChip(action, invalid) {
    var el = document.createElement("div");
    if (invalid || !action) { el.className = "mini-chip inv"; el.innerHTML = "No<br>move"; return el; }
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
    b.innerHTML = nums(text);
    b.classList.add("on"); canvas.classList.add("quiet");
    try { await sleep(ms || 700, g); } finally {
      b.classList.remove("on");
      if (!$("#seal").classList.contains("on")) canvas.classList.remove("quiet");
    }
    await sleep(200, g);
  }
  /** Hand dots in the header. `cur` is the hand being played (its dot pulses until it is
   * done); the text beside the dots says which hand this is. */
  function setPips(done, total, label, cur) {
    var p = $("#pips");
    if (total == null) { p.innerHTML = label ? "<em>" + nums(label) + "</em>" : ""; return; }
    var html = "Hand ";
    for (var k = 0; k < total; k++) html += '<span class="' + (k < done ? "on" : k === cur ? "cur" : "") + '"></span>';
    var which = cur != null ? cur + 1 : done;
    if (which > 0) html += '<em class="of">' + nums(which + " of " + total) + "</em>";
    p.innerHTML = html;
  }
  /** Text with every run of digits wrapped in .n, so small-caps lines keep full-size figures. */
  function nums(t) {
    return String(t).split(/(\d+)/).map(function (part, i) { return i % 2 ? '<span class="n">' + part + "</span>" : esc(part); }).join("");
  }
  function showSituation(s) {
    var el = $("#situation");
    el.innerHTML = nums(s.label) + " <small>vs dealer " + (s.upcard === "A" ? "ace" : nums(s.upcard)) + "</small>";
    el.style.opacity = 1;
  }

  // ---------- chips (the visitor's buttons) ----------
  var chipResolve = null;
  function setChips(legal) {
    $("#chips").style.display = legal ? "flex" : "none";
    $("#yourMove").classList.toggle("on", !!legal);
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
  function seatEntry(s, k) { var e = s.seats[k]; return e && e.status === "answered" ? e : null; }

  /** Deal the opening cards (the round's first four events) to every seat in `keys` at
   * once, a short stagger between seats, then the dealer's card. */
  var DEAL_BEAT = 150;   // ms between cards leaving the shoe
  async function dealOpening(round, keys, g, opts) {
    var order = [];
    for (var k = 0; k < 4; k++) {
      var ev = round.events[k];
      if (ev.to === "player") keys.forEach(function (key) { order.push([seats[key], ev]); });
      else order.push([seats.you, ev]);
    }
    await Promise.all(order.map(function (x, i) {
      return sleep(DEAL_BEAT * i * tempo(), g).then(function () { return playEvents(x[0], [x[1]], 0, g, opts); });
    }));
  }

  /** The visitor's (or presenter's) hand: same opening cards on all three seats, the agents'
   * chips face down, then the visitor plays the hand out up to the dealer's turn. Only the
   * first decision is graded. The dealer's turn waits for the reveal sequence. */
  async function playDeal(s, g, index, total) {
    state.phase = "deal";
    hideCtas();
    if (state.presenter) setPips(null, null, "Presenter · hand " + (index + 1));
    else setPips(index, total, null, index);
    // the banner runs while the last hand's cards sweep away
    await Promise.all([clearTable(g), banner(state.presenter ? "Hand " + (index + 1) : "Hand " + (index + 1) + " of " + total, g, 700)]);

    // The agents have already bet on this exact deal: their chips sit face down.
    ["baseline", "full"].forEach(function (k) {
      sealedChip(seats[k], s.seats[k]);
      seats[k].el.classList.add("dim");
    });
    var round = BJ.newRound(s.shoe, DATA.rule_set);
    await dealOpening(round, ["you", "baseline", "full"], g, { speed: 0.8 });
    showSituation(s);
    var shown = await playEvents(seats.you, round.events, 4, g, { stopAtDealer: true, round: round });
    var first = null;
    while (!round.done) {
      $("#yourMoveSub").textContent = first === null && index === 0 && !state.presenter ? "We grade your first move" : "";
      var act = await waitChip(BJ.legal(round), g);
      if (first === null) { first = act; placeChip(seats.you, act); }
      BJ.act(round, act);
      shown = await playEvents(seats.you, round.events, shown, g, { stopAtDealer: true, round: round });
    }
    return { s: s, action: first, payout: round.payout, round: round, shown: shown };
  }

  function hasLive(round) { return round.hands.some(function (h) { return BJ.handTotal(h.cards).total <= 21; }); }
  function dealerNote(round) { return "their dealer: " + round.dealerTotal + (round.dealerTotal > 21 ? " bust" : ""); }

  /** The reveal, in place and with no taps: both agent chips flip, the basic strategy seal
   * stamps in, ✓/✗ on every seat, the agents play their recorded hands out side by side,
   * then the dealer resolves and the outcome badges land. About 6 s; a tap speeds it up.
   * `you` is the visitor's playDeal result, or null in attract mode. */
  async function revealSequence(s, you, g) {
    state.revealing = true; ff.on = false;
    var fast = false;
    var note = $("#tapnote");
    note.textContent = "tap to speed up"; note.classList.remove("hide");
    try {
      var keys = ["baseline", "full"], entries = {}, rounds = {};
      keys.forEach(function (k) {
        entries[k] = seatEntry(s, k);
        seats[k].el.classList.remove("dim");
        seats[k].thinkEl.classList.remove("on");
      });
      // 1. Baseline's chip flips, then the Full harness's.
      state.phase = "flip";
      await sleep(350, g);
      $(".sealed", seats.baseline.slotEl).classList.add("open");
      await sleep(380, g);
      $(".sealed", seats.full.slotEl).classList.add("open");
      await sleep(800, g);

      // 2. The basic strategy seal stamps in.
      state.phase = "seal";
      $("#sealAct").textContent = ACT_LABEL[s.basic];
      $("#seal").classList.add("on");
      canvas.classList.add("quiet");
      await sleep(650, g);

      // 3. ✓ / ✗ on every seat.
      state.phase = "marks";
      if (you) { mark(seats.you, you.action === s.basic); await sleep(160, g); }
      for (var n = 0; n < keys.length; n++) {
        if (entries[keys[n]]) mark(seats[keys[n]], !!entries[keys[n]].correct);
        await sleep(160, g);
      }
      await sleep(500, g);

      // 4. Both agents play their recorded hands out, side by side.
      state.phase = "playout";
      await Promise.all(keys.map(function (k, i) {
        var e = entries[k];
        if (!e) return null;
        rounds[k] = BJ.replay(s.shoe, e.decisions.map(function (d) { return d.action; }), DATA.rule_set);
        return sleep(260 * i, g).then(function () {
          return playEvents(seats[k], rounds[k].events, 4, g, { speed: 0.8, stopAtDealer: true, round: rounds[k] });
        }).then(function () { setActive(seats[k], -1); });
      }));
      await sleep(250, g);

      // 5. The dealer plays out once on the table, then every seat's outcome lands.
      state.phase = "dealer";
      var all = [];
      if (you) all.push(["you", you.round]);
      keys.forEach(function (k) { if (rounds[k]) all.push([k, rounds[k]]); });
      var center = all.filter(function (x) { return hasLive(x[1]); })[0] || all[0];
      if (center) {
        var evs = center[1].events, from = 0;
        while (from < evs.length && evs[from].type !== "reveal") from++;
        await playEvents(seats[center[0]], evs, from, g);
        var table = BJ.summary(center[1]).dealer_cards.join(",");
        for (var j = 0; j < all.length; j++) {
          var key = all[j][0], r = all[j][1];
          var other = BJ.summary(r).dealer_cards.join(",") !== table && hasLive(r);
          showOutcome(seats[key], r, other ? dealerNote(r) : null);
          await sleep(140, g);
        }
      }
      await sleep(300, g);
    } finally {
      fast = ff.on;
      state.revealing = false; ff.on = false;
      note.classList.add("hide");
      if (g === gen) state.phase = "hold";
    }
    return fast;
  }

  function pickDeals(n) {
    var pool = READY.filter(function (s) { return state.lastGameIds.indexOf(s.id) < 0; });
    if (pool.length < n) pool = READY.slice();
    var out = [];
    while (out.length < n && pool.length) out.push(pool.splice(Math.floor(Math.random() * pool.length), 1)[0]);
    return out;
  }

  var HOLD_MS = 3000;   // after the reveal, the next hand starts on its own
  var FAST_HOLD_MS = 1200;   // ...sooner when the visitor tapped to speed the reveal up

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
        var fast = await revealSequence(hand.s, hand, g);
        state.game.push(hand);
        setPips(k + 1, deals.length, null, k);
        await waitAdvance(k + 1 < deals.length ? "Next hand" : "See the score", g, { countdown: fast ? FAST_HOLD_MS : HOLD_MS });
      }
      postResults(state.game);
      await runSummary(state.game, g);
    } catch (e) { swallow(e); }
  }

  /** After the last hand: the score tally, then the results sheet. */
  async function runSummary(hands, g) {
    state.lastInput = Date.now();   // the reveal ran with no taps; give the results their full idle time
    state.phase = "summary";
    $("#attract").classList.add("hide");
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
        "</span><b><i>0</i><small>/" + sc.n + "</small></b>";
      d.dataset.k = k;
      row.appendChild(d);
    });
    $("#verdict").textContent = verdictOf(sc);
    $("#verdict").classList.remove("on");
    $("#tally").classList.add("on");
    var whos = $$("#tallyRow .who");
    for (var k = 0; k < whos.length; k++) {
      await sleep(450, g);
      whos[k].classList.add("on");
      countUp($("i", whos[k]), sc[whos[k].dataset.k], 700);
    }
    await sleep(700, g);
    var top = Math.max(sc.you, sc.baseline, sc.full);
    if (top > 0) whos.forEach(function (w) { if (sc[w.dataset.k] === top) w.classList.add("win"); });
    await sleep(400, g);
    $("#verdict").classList.add("on");
    await waitAdvance("See every hand", g, state.presenter ? {} : { countdown: 5000 });
    $("#tally").classList.remove("on");
  }

  /** Count a number up from 0 over `ms`. */
  function countUp(el, to, ms) {
    var t0 = null;
    function step(t) {
      if (t0 === null) t0 = t;
      var f = Math.min(1, (t - t0) / ms);
      el.textContent = String(Math.round(to * (1 - Math.pow(1 - f, 3))));
      if (f < 1) requestAnimationFrame(step);
    }
    if (!to) { el.textContent = "0"; return; }
    requestAnimationFrame(step);
  }

  function actCell(action, basic, invalid) {
    if (invalid) return '<span class="act inv">no move ✗</span>';
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
    var html = '<div class="why" style="--c:' + c + '"><h4>' + SEAT_NAME[k] + " said</h4>" + esc(stripAction(e.reasoning) || "(no reply)");
    if (e.invalid) html += '<span class="flip">' + esc(plainReason(e.invalid_reason)) + ", so the hand stood.</span>";
    var se = e.self_eval;
    if (se) {
      if (se.flipped) html += '<span class="flip">Flip: first said ' + esc(ACT_LABEL[se.first_action] || "nothing valid") + ", changed to " + esc(ACT_LABEL[se.second_action] || "nothing valid") + " on the re-check.</span>";
      html += '<span class="first">First answer, before the re-check: ' + esc(stripAction(se.first_raw)) + "</span>";
    }
    return html + "</div>";
  }
  // the parser's invalid_reason codes (agent/parser.py), in words a visitor can read
  var REASON = {
    no_action: "The AI never named a move",
    truncated_no_action: "The AI's reply was cut off before it named a move",
    empty_action: "The AI's move line was blank",
    unknown_word: "The AI named a move that isn't in blackjack",
    conflicting: "The AI named more than one move",
    illegal: "The AI picked a move that wasn't allowed here",
  };
  function plainReason(code) { return REASON[code] || "The AI's reply had no move we could use"; }
  /** The reply without its closing "ACTION: x" line (the move is shown in its own column). */
  function stripAction(t) { return String(t || "").replace(/\s*ACTION:\s*[a-z]+\s*$/i, "").trim(); }
  function oddsBox(s) {
    var e = seatEntry(s, "full");
    if (!e || !e.odds) return '<div class="why odds" style="--c:var(--gold)"><h4>The odds</h4>' + (e && e.odds_text ? esc(e.odds_text) : "Not available.") + "</div>";
    var o = e.odds, html = '<div class="why odds" style="--c:var(--gold)"><h4>The odds the Full harness saw</h4>';
    if (o.bust_if_hit != null) html += '<div class="oddsline"><span>Bust if you hit</span><span class="bustbig">' + fmtPct(o.bust_if_hit) + "</span></div>";
    if (o.dealer && o.dealer.length) {
      html += "<div>Dealer ends on" + (o.dealer_no_blackjack ? " (if no blackjack)" : "") + '</div><div class="dist">';
      o.dealer.forEach(function (d) {
        html += "<span>" + esc(d[0]) + '</span><span class="b"><i class="' + (d[0] === "bust" ? "bust" : "") + '" data-w="' + d[1] + '"></i></span><span>' + fmtPct(d[1]) + "</span>";
      });
      html += "</div>";
    }
    if (o.stand) html += '<div class="standrow"><span class="h">If you stand:</span><span>win <b>' + fmtPct(o.stand.win) + "</b></span><span>push <b>" + fmtPct(o.stand.push) + "</b></span><span>lose <b>" + fmtPct(o.stand.lose) + "</b></span></div>";
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
      tr.innerHTML = '<td><span class="minicards">' + miniCards(s.player) + "<em>vs</em>" + miniCards([s.upcard]) + '</span><span class="rowlabel">' + nums(s.label) + "</span></td>" +
        "<td>" + actCell(h.action, s.basic, false) + "</td><td>" + seatCell(s, "baseline") + "</td><td>" + seatCell(s, "full") +
        '</td><td class="basic">' + ACT_LABEL[s.basic] + "</td>";
      var det = document.createElement("tr");
      det.className = "detail";
      det.innerHTML = '<td colspan="5"><div class="detail-in"><div><div class="dgrid">' + reasoningBox(s, "baseline") + reasoningBox(s, "full") + oddsBox(s) + "</div></div></div></td>";
      function toggle(open) {
        tr.classList.toggle("open", open); det.classList.toggle("open", open);
        if (open) setTimeout(function () { $$(".dist i", det).forEach(function (i) { i.style.width = Math.min(100, parseFloat(i.dataset.w)) + "%"; }); }, 60);
      }
      tr.addEventListener("click", function () { toggle(!tr.classList.contains("open")); });
      body.appendChild(tr); body.appendChild(det);
      if (body.children.length === 2) toggle(true);   // the first hand opens on its own
    });
    $("#againBtn").textContent = state.presenter ? "Back to presenter" : "Play again";
    renderBoard();
    $("#scrim").classList.add("on");
    $("#results").classList.add("on");
    hideCtas(); setChips(null);
    armResultsIdle();
  }

  // Results left alone go back to attract: 15 s, then a ring on "Play again" runs the last
  // 5 s. Any touch, key or scroll starts the 20 s over. Presenter results never time out.
  var RES_IDLE_MS = 15000, RES_RING_MS = 5000, resIdle = [];
  function disarmResultsIdle() {
    resIdle.forEach(clearTimeout); resIdle = [];
    var b = $("#againBtn"), r = $(".ring", b);
    b.classList.remove("timed");
    if (r) r.remove();
  }
  function armResultsIdle() {
    disarmResultsIdle();
    if (state.presenter || state.mode !== "results") return;
    var g = gen;
    resIdle.push(setTimeout(function () {
      if (g !== gen || state.mode !== "results") return;
      var b = $("#againBtn");
      b.classList.add("timed");
      b.style.setProperty("--count", RES_RING_MS + "ms");
      b.insertAdjacentHTML("beforeend", RING);
      resIdle.push(setTimeout(function () {
        if (g === gen && state.mode === "results" && !state.presenter) startAttract();
      }, RES_RING_MS));
    }, RES_IDLE_MS));
  }
  function leaveOverlays() {
    disarmResultsIdle();
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
    $("#plaque").classList.toggle("zero", !n);
    $("#plaqueN").textContent = n ? n + (n === 1 ? " visitor" : " visitors") : "Be the first to play";
    var rows = [["visitor", "Visitors", "var(--you)"], ["baseline", "Baseline", "var(--base)"], ["full", "Full harness", "var(--full)"]];
    [$("#attractBoard"), $("#resultsBoard")].forEach(function (box) {
      if (!box.firstChild) {   // build once; later renders only move the bars
        var html = '<div class="title">Who plays it by the book? <small>First moves that match basic strategy, over the same hands</small></div>';
        rows.forEach(function (row) {
          html += '<div class="col" data-who="' + row[0] + '"><div class="top"><span class="who">' + row[1] + '</span><span class="pct" style="color:' + row[2] +
            '">—</span></div><div class="bar"><b style="background:' + row[2] + '"></b></div></div>';
        });
        box.innerHTML = html + '<div class="first">Be the first to play</div>' +
          '<div class="foot"><span class="info"></span><span>Both AI players are the same small open AI model. They played these exact hands earlier.</span></div>';
      }
      box.classList.toggle("zero", !n);
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
      for (;;) {
        var s = READY[Math.floor(Math.random() * READY.length)];
        await clearTable(g);
        seats.you.el.classList.add("dim");
        await dealOpening(BJ.newRound(s.shoe, DATA.rule_set), ["baseline", "full"], g, { speed: 1.2 });
        showSituation(s);
        ["baseline", "full"].forEach(function (k) { sealedChip(seats[k], s.seats[k]); seats[k].thinkEl.classList.add("on"); });
        await sleep(1800, g);
        await revealSequence(s, null, g);
        await sleep(4500, g);
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
    $("#sessionInfo").textContent = n + (n === 1 ? " hand played" : " hands played") + " · not posted to the board" + (DATA && DATA.model ? " · " + DATA.model : "");
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
      await revealSequence(s, hand, g);
      state.session.push(hand);
      updateSession();
      setCtas([
        { label: "Next deal", cls: "next", fn: function () { hideCtas(); openPanel(); } },
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
    runSummary(state.session.slice(), g).catch(swallow);
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
  function touch() {
    state.lastInput = Date.now();
    if (state.mode === "results" && resIdle.length) armResultsIdle();
  }
  document.addEventListener("pointerdown", touch, true);
  document.addEventListener("keydown", touch, true);
  document.addEventListener("wheel", touch, { capture: true, passive: true });

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
    if (e.key === " " || e.key === "Enter" || e.key === "ArrowRight") {
      if (state.revealing) { e.preventDefault(); fastForward(); }
      else if (advanceHook) { e.preventDefault(); advanceHook(); }
    }
    if (e.key === "Escape" && state.presenter) openPanel();
  });
  canvas.addEventListener("click", function (e) {
    if (e.target.closest("button, .results, .panel, input")) return;
    if (state.mode === "attract") { startGame(); return; }
    if (state.mode === "empty") return;
    if (state.revealing) { fastForward(); return; }
    if (advanceHook && advanceTap) advanceHook();
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
