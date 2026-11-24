// End-to-end check of the showcase demo in a real browser (Playwright + local Chrome).
//
//   NODE_PATH=<dir holding playwright> node tests/js/demo_e2e.js [--out DIR] [--python PY] [--sizes 1280x720,1920x1080]
//
// Starts scripts/demo_server.py on a free port with a throwaway results file (so the
// real demo/visitor_results.jsonl is never touched), then at each window size:
//   attract screen -> tap -> play 3 hands, each followed by the automatic in-place reveal
//   and the timed "Next hand" (never clicked: the test checks both run with no taps, and
//   taps once mid-reveal to check fast-forward) -> tally (5 s countdown) -> results (first
//   row opens on its own; at the first size, left idle it returns to attract) ->
//   presenter mode (Shift+Alt+P), search a deal, play it, a random one, See results ->
//   results -> forced deals from the presenter chart (a 9-card hand, split hands, agent
//   splits, a long dealer hand, a pair of 10s, a soft hand, a double, an AI reply with no
//   move) with a geometry check that nothing overlaps. Also an attract screen with an empty board.
// Fails on any page error or console error, if the board did not count exactly the
// one visitor game, if a presenter hand was posted, if a reveal needed a tap, or if any
// badge, name label, seat or control overlaps another. Screenshots go to --out.
"use strict";
const { spawn } = require("child_process");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");

let playwright;
try { playwright = require("playwright"); } catch (e) {
  console.error("playwright not found: set NODE_PATH to a node_modules dir that has it"); process.exit(2);
}

const ROOT = path.join(__dirname, "..", "..");
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const OUT = opt("--out", fs.mkdtempSync(path.join(os.tmpdir(), "demo-e2e-")));
// a git worktree (.claude/worktrees/<name>) has no .venv of its own: fall back to the main checkout's
const PY = opt("--python", [path.join(ROOT, ".venv", "bin", "python"), path.join(ROOT, "..", "..", "..", ".venv", "bin", "python")]
  .find((p) => fs.existsSync(p)) || "python3");
const SIZES = opt("--sizes", "1280x720,1920x1080,2560x1440").split(",").map((s) => s.split("x").map(Number));
fs.mkdirSync(OUT, { recursive: true });

function freePort() {
  return new Promise((resolve) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
}
const problems = [];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function startServer() {
  const port = await freePort();
  const results = path.join(OUT, "visitor_results.jsonl");
  if (fs.existsSync(results)) fs.unlinkSync(results);
  const proc = spawn(PY, [path.join(ROOT, "scripts", "demo_server.py"), "--port", String(port), "--results", results], { stdio: ["ignore", "pipe", "pipe"] });
  proc.stderr.on("data", () => {});
  for (let k = 0; k < 50; k++) {
    try { const r = await fetch(`http://127.0.0.1:${port}/api/board`); if (r.ok) return { proc, port }; } catch (e) { /* not up yet */ }
    await wait(100);
  }
  proc.kill(); throw new Error("demo server did not start");
}

// Click whatever moves the flow forward until `done()` is true.
async function drive(page, done, { label, chip = "stand", shots = {}, tag, limit = 240000, ctas = true } = {}) {
  const t0 = Date.now();
  while (!(await done())) {
    if (Date.now() - t0 > limit) throw new Error(`timed out driving ${label}`);
    const errs = problems.filter((p) => / (pageerror|console):/.test(p));
    if (errs.length) throw new Error(`page errors while driving ${label}:\n${errs.join("\n")}`);
    // ctas: false for presenter hands, whose "Next deal" opens the panel: the reveal can end
    // between the done() check and this one, and clicking it then would cover the CTAs
    const cta = page.locator("#ctas .cta.next");
    if (ctas && await cta.count()) {
      const text = (await cta.first().textContent()).trim();
      if (shots[text]) { await page.screenshot({ path: path.join(OUT, `${tag}-${shots[text]}.png`) }); delete shots[text]; }
      await cta.first().click();
      await wait(250);
      continue;
    }
    if (await clickChip(page, chip, shots, tag)) continue;
    await wait(150);
  }
}

// Click one enabled chip. `chip` is an action or a list of them used in order (the last one
// repeats); an action that is not legal falls back to the first enabled chip.
const chipCount = new WeakMap();
async function clickChip(page, chip, shots = {}, tag) {
  const enabled = page.locator("#chips .chip:not([disabled]):not(.hide)");
  if (!(await enabled.count())) return false;
  const seq = Array.isArray(chip) ? chip : [chip];
  const n = chipCount.get(page) || 0;
  chipCount.set(page, n + 1);
  const act = seq[Math.min(n, seq.length - 1)];
  const want = page.locator(`#chips .chip[data-act="${act}"]:not([disabled])`);
  if (shots.chips) { await page.screenshot({ path: path.join(OUT, `${tag}-${shots.chips}.png`) }); delete shots.chips; }
  await ((await want.count()) ? want : enabled.first()).click();
  await wait(250);
  return true;
}

const phase = (page) => page.evaluate(() => window.__demo.state.phase);
const revealing = (page) => page.evaluate(() => window.__demo.state.revealing);

// Everything that must not overlap once a reveal has finished: outcome badges, seat name
// labels, each seat's cards, the dealer's cards, the controls; and all of it on screen.
async function layoutProblems(page) {
  return page.evaluate(() => {
    const out = [], pad = 2;
    const R = (el) => el.getBoundingClientRect();
    const union = (els) => els.map(R).reduce((a, b) => a ? { left: Math.min(a.left, b.left), top: Math.min(a.top, b.top), right: Math.max(a.right, b.right), bottom: Math.max(a.bottom, b.bottom) } : b, null);
    const hit = (a, b) => a && b && a.left < b.right - pad && b.left < a.right - pad && a.top < b.bottom - pad && b.top < a.bottom - pad;
    const boxes = [];
    for (const seat of document.querySelectorAll(".seat")) {
      if (getComputedStyle(seat).display === "none") continue;
      const k = seat.dataset.seat;
      boxes.push([`${k} cards`, union([...seat.querySelectorAll(".card")]), k]);
      boxes.push([`${k} name`, R(seat.querySelector(".name")), k]);
      seat.querySelectorAll(".badge.on").forEach((b, i) => boxes.push([`${k} badge ${i}`, R(b), k]));
      seat.querySelectorAll(".slot").forEach((b) => boxes.push([`${k} chip`, R(b), k]));
    }
    boxes.push(["dealer cards", union([...document.querySelectorAll("#dealerHand .card")]), "dealer"]);
    document.querySelectorAll("#ctas .cta").forEach((b, i) => boxes.push([`button ${i}`, R(b), "controls"]));
    for (let i = 0; i < boxes.length; i++) {
      const [ni, ri, si] = boxes[i];
      if (!ri) continue;
      if (ri.left < -pad || ri.top < -pad || ri.right > innerWidth + pad || ri.bottom > innerHeight + pad) out.push(`${ni} off screen`);
      for (let j = i + 1; j < boxes.length; j++) {
        const [nj, rj, sj] = boxes[j];
        // inside one seat the badge sits on its cards by design; it must still clear the
        // name label, the chip and the other hand's badge
        const kind = (n) => n.split(" ")[1];
        if (si === sj) {
          const pair = [kind(ni), kind(nj)].sort().join("+");
          if (!["badge+name", "badge+chip", "badge+badge"].includes(pair)) continue;
        }
        if (hit(ri, rj)) out.push(`${ni} overlaps ${nj}`);
      }
    }
    return out;
  });
}

// Play the visitor's hand to the reveal, then let the reveal run with no taps.
// Returns how long the reveal took (ms) from the first chip flip to the hold.
async function playAndReveal(page, tag, { chip = "stand", shots = {}, ffAt = null, label }) {
  const t0 = Date.now();
  chipCount.set(page, 0);
  while (!(await revealing(page))) {
    if (Date.now() - t0 > 90000) throw new Error(`${tag}: ${label} never reached the reveal`);
    if (await clickChip(page, chip, shots, tag)) continue;
    await wait(80);
  }
  const start = Date.now(), seen = new Set();
  while ((await phase(page)) !== "hold") {
    if (Date.now() - start > 20000) throw new Error(`${tag}: ${label} reveal did not finish on its own`);
    const ph = await phase(page);
    if (!seen.has(ph)) {
      seen.add(ph);
      if (shots[ph]) { await wait(ph === "playout" ? 700 : 350); await page.screenshot({ path: path.join(OUT, `${tag}-${shots[ph]}.png`) }); }
      if (ph === ffAt) { const vp = page.viewportSize(); await page.mouse.click(vp.width * 0.5, vp.height * 0.06); }
    }
    await wait(40);
  }
  return Date.now() - start;
}

async function board(port) { return (await fetch(`http://127.0.0.1:${port}/api/board`)).json(); }

async function run() {
  const { proc, port } = await startServer();
  const browser = await playwright.chromium.launch({ channel: "chrome", headless: true });
  try {
    for (const [w, h] of SIZES) {
      const tag = `${w}x${h}`;
      const page = await browser.newPage({ viewport: { width: w, height: h } });
      page.on("pageerror", (e) => problems.push(`${tag} pageerror: ${e.message}`));
      page.on("console", (m) => { if (m.type() === "error") problems.push(`${tag} console: ${m.text()}`); });
      const before = (await board(port)).visitors;

      // attract with nobody on the board yet: "Be the first to play"
      const blank = await browser.newPage({ viewport: { width: w, height: h } });
      blank.on("pageerror", (e) => problems.push(`${tag} (empty board) pageerror: ${e.message}`));
      await blank.route("**/api/board", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ visitors: 0, visitor: null, baseline: null, full: null }) }));
      await blank.goto(`http://127.0.0.1:${port}/`);
      await blank.waitForSelector("#attract:not(.hide)");
      await wait(2500);
      await blank.screenshot({ path: path.join(OUT, `${tag}-0-attract-empty.png`) });
      if (!(await blank.locator("#attractBoard.zero .first").isVisible())) problems.push(`${tag}: empty board does not say "Be the first to play"`);
      await blank.close();

      await page.goto(`http://127.0.0.1:${port}/`);
      await page.waitForSelector("#attract:not(.hide)");
      await wait(3500);
      await page.screenshot({ path: path.join(OUT, `${tag}-1-attract.png`) });

      // a visitor game
      // Each hand: play it, then the reveal runs on its own and "Next hand" counts down and
      // advances on its own. Nothing here clicks the Next button. Hand 2 is tapped once
      // mid-reveal (fast-forward); hands 1 and 3 run untouched.
      await page.mouse.click(w / 2, h / 2);
      const times = [], decisions = [];
      for (let k = 0; k < 3; k++) {
        const shots = k === 0
          ? { chips: "2-play", flip: "3a-reveal-flip", seal: "3b-reveal-seal", marks: "3c-reveal-marks", playout: "3d-reveal-playout", dealer: "3e-reveal-dealer" }
          : {};
        // time from the hand starting to the chips lighting up (no decision on a dealt blackjack)
        const d0 = Date.now();
        await page.waitForFunction(() => document.querySelector("#yourMove.on") || window.__demo.state.revealing, null, { timeout: 15000 });
        if (await page.locator("#yourMove.on").count()) decisions.push(Date.now() - d0);
        const ms = await playAndReveal(page, tag, { label: `hand ${k + 1}`, shots, ffAt: k === 1 ? "seal" : null });
        const held = Date.now();
        times.push(ms);
        const badges = await page.locator(".seat.you .badge.on").count();
        if (!badges) problems.push(`${tag}: hand ${k + 1} reveal ended without an outcome on the You seat`);
        const ring = await page.locator("#ctas .cta.next.timed .ring").count();
        if (!ring) problems.push(`${tag}: hand ${k + 1} has no countdown ring on the Next button`);
        if (k === 0) { await wait(1500); await page.screenshot({ path: path.join(OUT, `${tag}-4-hold.png`) }); }
        const issues = await layoutProblems(page);
        if (issues.length) problems.push(`${tag}: hand ${k + 1} layout: ${issues.join("; ")}`);
        // the hold advances on its own
        if (k < 2) await page.waitForFunction(() => window.__demo.state.phase === "deal", null, { timeout: 8000 });
        else await page.waitForFunction(() => !!document.querySelector("#tally.on"), null, { timeout: 12000 });
        // 3 s hold; 1.2 s after a reveal the visitor tapped to speed up (hand 2)
        const hold = Date.now() - held, floor = k === 1 ? 1000 : 2600;
        if (hold < floor) problems.push(`${tag}: hand ${k + 1} hold was only ${hold} ms`);
        if (k === 1 && hold > 2400) problems.push(`${tag}: hold after a fast-forwarded reveal was ${hold} ms, expected about 1.2 s`);
      }
      console.log(`${tag}: reveal took ${times.map((t) => (t / 1000).toFixed(1) + " s").join(", ")} (hand 2 fast-forwarded); ` +
        `deal to decision ${decisions.map((t) => (t / 1000).toFixed(1) + " s").join(", ")}`);
      // hand 1 includes the tap on attract; later hands start at the end of the hold
      if (decisions.slice(1).some((t) => t > 3200)) problems.push(`${tag}: deal to decision too slow: ${decisions.join(", ")} ms`);
      if (times[0] > 9000 || times[2] > 9000) problems.push(`${tag}: reveal too slow: ${times.join(", ")} ms`);
      if (times[1] >= Math.min(times[0], times[2])) problems.push(`${tag}: fast-forward did not shorten the reveal (${times.join(", ")} ms)`);
      await page.waitForSelector("#ctas .cta.timed .ring", { timeout: 8000 }).catch(() => problems.push(`${tag}: tally has no countdown ring`));
      await page.screenshot({ path: path.join(OUT, `${tag}-6-tally.png`) });
      // the tally moves on by itself after 5 s
      const tallyAt = Date.now();
      await page.waitForSelector("#results.on", { timeout: 9000 }).catch(() => problems.push(`${tag}: tally did not move on by itself`));
      if (Date.now() - tallyAt < 3500) problems.push(`${tag}: tally left after only ${Date.now() - tallyAt} ms`);
      await wait(1500);
      if (!(await page.locator("#resBody tr.row").first().evaluate((r) => r.classList.contains("open")))) problems.push(`${tag}: first results row did not open on its own`);
      await page.screenshot({ path: path.join(OUT, `${tag}-7-results.png`) });
      const rows = await page.locator("#resBody tr.row").count();
      if (rows !== 3) problems.push(`${tag}: results table has ${rows} rows, expected 3`);
      const after = await board(port);
      if (after.visitors !== before + 1) problems.push(`${tag}: board went ${before} -> ${after.visitors} visitors, expected +1`);
      const plaque = await page.locator("#plaqueN").textContent();
      if (!plaque.includes(String(after.visitors))) problems.push(`${tag}: plaque says "${plaque}", board has ${after.visitors}`);

      // results left alone: a ring on Play again for the last 5 s, a touch restarts it, then attract
      if (tag === `${SIZES[0][0]}x${SIZES[0][1]}`) {
        await page.waitForSelector("#againBtn.timed .ring", { timeout: 16000 });
        await page.screenshot({ path: path.join(OUT, `${tag}-7b-results-idle.png`) });
        await page.mouse.click(w * 0.3, h * 0.08);
        await wait(300);
        if (await page.locator("#againBtn.timed").count()) problems.push(`${tag}: a touch did not restart the results timer`);
        const idleAt = Date.now();
        await page.waitForSelector("#attract:not(.hide)", { timeout: 24000 }).catch(() => problems.push(`${tag}: idle results never went back to attract`));
        if (Date.now() - idleAt < 18000) problems.push(`${tag}: idle results left after only ${Date.now() - idleAt} ms`);
        await wait(2000);
        await page.screenshot({ path: path.join(OUT, `${tag}-7c-attract-with-data.png`) });
      }

      // presenter mode
      await page.keyboard.press("Shift+Alt+KeyP");
      await page.waitForSelector("#panel.on");
      await page.fill("#search", "16 vs 10");
      await wait(300);
      await page.screenshot({ path: path.join(OUT, `${tag}-8-presenter.png`) });
      const matches = await page.locator("#matches button:not([disabled])").count();
      if (matches) await page.keyboard.press("Enter");
      else await page.locator("#randomBtn").click();
      await drive(page, () => page.locator("#ctas .cta", { hasText: "See results" }).count().then(Boolean), { label: "presenter hand 1", tag, chip: "hit", ctas: false });
      await page.locator("#ctas .cta", { hasText: "Random" }).click();
      await page.waitForFunction(() => !document.querySelector("#ctas .cta"));
      await drive(page, () => page.locator("#ctas .cta", { hasText: "See results" }).count().then(Boolean), { label: "presenter hand 2", tag, ctas: false });
      await page.screenshot({ path: path.join(OUT, `${tag}-9-presenter-hand.png`) });
      await page.locator("#ctas .cta", { hasText: "See results" }).click();
      await drive(page, () => page.locator("#results.on").count().then(Boolean), { label: "presenter reveal", tag });
      await wait(1200);
      await page.screenshot({ path: path.join(OUT, `${tag}-10-presenter-results.png`) });
      const prow = await page.locator("#resBody tr.row").count();
      if (prow !== 2) problems.push(`${tag}: presenter results have ${prow} rows, expected 2`);
      if ((await board(port)).visitors !== after.visitors) problems.push(`${tag}: a presenter hand was posted to the board`);

      // forced deals from the presenter chart: long hands and splits on every seat
      const forced = [
        ["soft14_vs_10", ["hit"], "visitor hits to 9 cards"],
        ["pair2_vs_6", ["split", "hit"], "visitor splits, hits both hands"],
        ["pair2_vs_8", ["split", "hit"], "both agents split"],
        ["hard6_vs_3", ["stand"], "dealer draws to 5 cards"],
        ["pair10_vs_6", ["stand"], "pair of 10s; Baseline doubles (sideways card)"],
        ["soft18_vs_9", ["stand"], "soft total"],
        ["hard11_vs_6", ["double"], "visitor doubles (sideways card)"],
        ["hard17_vs_2", ["stand"], "Baseline reply had no move"],
      ];
      await page.locator("#againBtn").click();
      for (const [id, chips, what] of forced) {
        await page.waitForSelector("#panel.on");
        await wait(400);
        await page.locator(`#chart button.cell[data-id="${id}"]`).click();
        await playAndReveal(page, tag, { label: `forced ${id}`, chip: chips, shots: { playout: `11-forced-${id}-playout` } });
        await wait(700);
        await page.screenshot({ path: path.join(OUT, `${tag}-11-forced-${id}.png`) });
        const issues = await layoutProblems(page);
        if (issues.length) problems.push(`${tag}: forced ${id} (${what}): ${issues.join("; ")}`);
        if (id === "hard17_vs_2" && !(await page.locator(".seat.baseline .mini-chip.inv").count())) problems.push(`${tag}: hard17_vs_2 shows no "No move" chip for Baseline`);
        if ((id === "pair10_vs_6" || id === "hard11_vs_6") && !(await page.locator(".card.sideways").count())) problems.push(`${tag}: forced ${id} has no sideways doubled card`);
        await page.locator("#ctas .cta", { hasText: "Next deal" }).click();
        if (await page.locator("#ctas .cta").count()) problems.push(`${tag}: presenter buttons stayed up after Next deal`);
      }
      // the presenter panel must leave the live board in the header visible
      await page.waitForSelector("#panel.on");
      await wait(700);
      const covered = await page.evaluate(() => {
        const a = document.querySelector(".plaque").getBoundingClientRect(), b = document.querySelector("#panel").getBoundingClientRect();
        return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
      });
      if (covered) problems.push(`${tag}: the presenter panel covers the live board`);
      await page.screenshot({ path: path.join(OUT, `${tag}-12-presenter-panel.png`) });

      // #presenter hash on a fresh load opens the panel straight away
      await page.goto("about:blank");
      await page.goto(`http://127.0.0.1:${port}/#presenter`);
      await page.waitForSelector("#panel.on");
      const pending = await page.locator("#chart button.cell[disabled]").count();
      const cells = await page.locator("#chart button.cell").count();
      if (cells !== 330) problems.push(`${tag}: presenter chart has ${cells} cells, expected 330`);
      console.log(`${tag}: ok (${cells - pending} deals ready, ${pending} pending)`);
      await page.close();
    }
  } finally {
    await browser.close();
    proc.kill();
  }
  console.log(`screenshots: ${OUT}`);
  if (problems.length) { console.error(problems.join("\n")); process.exit(1); }
  console.log("demo e2e: all good");
}

run().catch((e) => { console.error(e); if (problems.length) console.error(problems.join("\n")); process.exit(1); });
