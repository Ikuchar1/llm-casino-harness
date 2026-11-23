// End-to-end check of the showcase demo in a real browser (Playwright + local Chrome).
//
//   NODE_PATH=<dir holding playwright> node tests/js/demo_e2e.js [--out DIR] [--python PY] [--sizes 1280x720,1920x1080]
//
// Starts scripts/demo_server.py on a free port with a throwaway results file (so the
// real demo/visitor_results.jsonl is never touched), then at each window size:
//   attract screen -> tap -> play 3 hands -> reveal every step -> tally -> results
//   (expand a row) -> presenter mode (Shift+Alt+P), search a deal, play it, a random
//   one, See results -> reveal -> results.
// Fails on any page error or console error, if the board did not count exactly the
// one visitor game, or if a presenter hand was posted. Screenshots go to --out.
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
const PY = opt("--python", path.join(ROOT, ".venv", "bin", "python"));
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
async function drive(page, done, { label, chip = "stand", shots = {}, tag, limit = 240000 } = {}) {
  const t0 = Date.now();
  while (!(await done())) {
    if (Date.now() - t0 > limit) throw new Error(`timed out driving ${label}`);
    const errs = problems.filter((p) => / (pageerror|console):/.test(p));
    if (errs.length) throw new Error(`page errors while driving ${label}:\n${errs.join("\n")}`);
    const cta = page.locator("#ctas .cta.next");
    if (await cta.count()) {
      const text = (await cta.first().textContent()).trim();
      if (shots[text]) { await page.screenshot({ path: path.join(OUT, `${tag}-${shots[text]}.png`) }); delete shots[text]; }
      await cta.first().click();
      await wait(250);
      continue;
    }
    const enabled = page.locator("#chips .chip:not([disabled]):not(.hide)");
    if (await enabled.count()) {
      const want = page.locator(`#chips .chip[data-act="${chip}"]:not([disabled])`);
      if (shots.chips) { await page.screenshot({ path: path.join(OUT, `${tag}-${shots.chips}.png`) }); delete shots.chips; }
      await ((await want.count()) ? want : enabled.first()).click();
      await wait(250);
      continue;
    }
    await wait(150);
  }
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

      await page.goto(`http://127.0.0.1:${port}/`);
      await page.waitForSelector("#attract:not(.hide)");
      await wait(3500);
      await page.screenshot({ path: path.join(OUT, `${tag}-1-attract.png`) });

      // a visitor game
      await page.mouse.click(w / 2, h / 2);
      await drive(page, () => page.locator("#tally.on").count().then(Boolean), {
        label: "visitor game", tag,
        shots: { chips: "2-play", "Show basic strategy": "3-reveal-chips", "Play it out": "4-reveal-marks", "See the score": "5-reveal-played" },
      });
      await wait(2500);
      await page.screenshot({ path: path.join(OUT, `${tag}-6-tally.png`) });
      await drive(page, () => page.locator("#results.on").count().then(Boolean), { label: "tally", tag });
      await wait(1200);
      await page.locator("#resBody tr.row").first().click();
      await wait(900);
      await page.screenshot({ path: path.join(OUT, `${tag}-7-results.png`) });
      const rows = await page.locator("#resBody tr.row").count();
      if (rows !== 3) problems.push(`${tag}: results table has ${rows} rows, expected 3`);
      const after = await board(port);
      if (after.visitors !== before + 1) problems.push(`${tag}: board went ${before} -> ${after.visitors} visitors, expected +1`);
      const plaque = await page.locator("#plaqueN").textContent();
      if (!plaque.includes(String(after.visitors))) problems.push(`${tag}: plaque says "${plaque}", board has ${after.visitors}`);

      // presenter mode
      await page.keyboard.press("Shift+Alt+KeyP");
      await page.waitForSelector("#panel.on");
      await page.fill("#search", "16 vs 10");
      await wait(300);
      await page.screenshot({ path: path.join(OUT, `${tag}-8-presenter.png`) });
      const matches = await page.locator("#matches button:not([disabled])").count();
      if (matches) await page.keyboard.press("Enter");
      else await page.locator("#randomBtn").click();
      await drive(page, () => page.locator("#ctas .cta", { hasText: "See results" }).count().then(Boolean), { label: "presenter hand 1", tag, chip: "hit" });
      await page.locator("#ctas .cta", { hasText: "Random" }).click();
      await page.waitForFunction(() => !document.querySelector("#ctas .cta"));
      await drive(page, () => page.locator("#ctas .cta", { hasText: "See results" }).count().then(Boolean), { label: "presenter hand 2", tag });
      await page.screenshot({ path: path.join(OUT, `${tag}-9-presenter-hand.png`) });
      await page.locator("#ctas .cta", { hasText: "See results" }).click();
      await drive(page, () => page.locator("#results.on").count().then(Boolean), { label: "presenter reveal", tag });
      await wait(1200);
      await page.screenshot({ path: path.join(OUT, `${tag}-10-presenter-results.png`) });
      const prow = await page.locator("#resBody tr.row").count();
      if (prow !== 2) problems.push(`${tag}: presenter results have ${prow} rows, expected 2`);
      if ((await board(port)).visitors !== after.visitors) problems.push(`${tag}: a presenter hand was posted to the board`);

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

run().catch((e) => { console.error(e); process.exit(1); });
