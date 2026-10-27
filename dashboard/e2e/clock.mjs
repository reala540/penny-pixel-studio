// Header world clock in a real browser against simulated services.
// Run: node e2e/clock.mjs   (screenshots go to e2e/screenshots/clock, or E2E_SCREENSHOT_DIR)
import { mkdirSync } from "node:fs";
import { openStudio, seed, startServer, withBrowser } from "./harness.mjs";

const OUT = `${process.env.E2E_SCREENSHOT_DIR ?? new URL("./screenshots", import.meta.url).pathname}/clock/`;
mkdirSync(OUT, { recursive: true });
const PHONE = { width: 360, height: 780 };
const results = [];
async function check(name, fn) {
  try { await fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name, String(e).slice(0, 600)]); }
}
const shot = (page, name) => page.screenshot({ path: `${OUT}${name}.png`, fullPage: false });
const clock = (page) => page.getByRole("group", { name: "World clock" });
async function read(page) {
  const g = clock(page);
  await g.waitFor({ timeout: 15000 });
  return g.innerText();
}
async function until(page, test, what, timeout = 10000) {
  const end = Date.now() + timeout;
  let last = "";
  while (Date.now() < end) {
    last = await read(page);
    if (test(last)) return last;
    await page.waitForTimeout(100);
  }
  throw new Error(`${what}; clock says: ${JSON.stringify(last)}`);
}
const withZone = (tz) => { const db = seed(); if (tz === undefined) delete db.settings.timezone; else db.settings.timezone = tz; return db; };

const server = await startServer();
try {
  await withBrowser(async (browser) => {
    await check("Both clocks from the saved setting, not the device (device set to Tokyo), on every page", async () => {
      const { page, errors } = await openStudio(browser, "/", { db: withZone("America/New_York"), timezoneId: "Asia/Tokyo",
        clock: new Date("2026-11-02T22:30:05Z") });
      const t = await until(page, (s) => /studio time/i.test(s) && s.includes("EST"), "studio clock didn't show New York");
      if (!/Mon 2 Nov/.test(t) || !/kenyan time/i.test(t) || !/Tue 3 Nov · GMT\+3/.test(t)) throw new Error(t);
      if (/GMT\+9|JST|Tokyo/.test(t)) throw new Error(`device timezone leaked: ${t}`);
      for (const path of ["/create", "/content", "/calendar", "/activity", "/settings", "/help"]) {
        await page.goto(`http://127.0.0.1:${process.env.E2E_PORT || 5179}${path}`);
        await until(page, (s) => s.includes("EST") && s.includes("GMT+3"), `clock missing on ${path}`);
      }
      await shot(page, "desktop");
      if (errors.length) throw new Error(errors.join("\n"));
    });

    await check("Ticks every second from one instant; survives sleep; daylight saving and midnight", async () => {
      // 05:59:58 UTC on 1 Nov 2026: New York is about to leave daylight saving
      const { page, context } = await openStudio(browser, "/", { db: withZone("America/New_York"), clock: new Date("2026-11-01T05:59:58Z") });
      await until(page, (s) => s.includes("01:59:58") && s.includes("EDT") && s.includes("08:59:58"), "start time wrong");
      await context.clock.runFor(1000);
      await until(page, (s) => s.includes("01:59:59") && s.includes("08:59:59"), "didn't tick to :59");
      await context.clock.runFor(1000);
      await until(page, (s) => s.includes("01:00:00") && s.includes("EST") && s.includes("09:00:00"), "daylight saving change not shown");
      // the laptop sleeps for 15 hours: the clock jumps straight to the right time when it wakes / the tab is shown
      await context.clock.fastForward("15:00:00");
      await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
      await until(page, (s) => s.includes("16:00:00") && s.includes("Sun 1 Nov") && s.includes("00:00:00") && s.includes("Mon 2 Nov"),
        "after sleep the clock is wrong (Kenya should have rolled over to Mon 2 Nov)");
      // both faces always show the same second
      for (let i = 0; i < 5; i++) {
        await context.clock.runFor(1000);
        const s = await read(page);
        const secs = [...s.matchAll(/\d\d:\d\d:(\d\d)/g)].map((m) => m[1]);
        if (secs.length !== 2 || secs[0] !== secs[1]) throw new Error(`faces disagree: ${s}`);
      }
    });

    await check("Changing the timezone in Settings updates the clock at once (no reload)", async () => {
      const { page, context, db } = await openStudio(browser, "/settings/appearance", { db: withZone("America/New_York") });
      await until(page, (s) => s.includes("New York"), "start");
      await page.locator('select[aria-label="Timezone"]').selectOption("Australia/Sydney");
      await until(page, (s) => s.includes("Sydney") && /AEDT|AEST|GMT\+1[01]/.test(s), "clock didn't follow the new setting");
      if (db.settings.timezone !== "Australia/Sydney") throw new Error("setting not saved");
      // another tab of the same browser follows too
      const other = await context.newPage();
      await other.goto(page.url().replace(/\/settings.*$/, "/"));
      await until(other, (s) => s.includes("Sydney"), "a new tab didn't show the saved zone");
      await shot(page, "after-change");
    });

    await check("Another device / private window gets the account's zone (fresh storage, different device zone)", async () => {
      const db = withZone("America/Chicago");
      const a = await openStudio(browser, "/", { db, timezoneId: "Europe/London" });
      const b = await openStudio(browser, "/", { db, timezoneId: "Pacific/Auckland" });
      for (const s of [await until(a.page, (x) => x.includes("Chicago"), "device A"), await until(b.page, (x) => x.includes("Chicago"), "device B")])
        if (!/C[SD]T/.test(s)) throw new Error(s);
    });

    await check("Settings fail to load: unavailable with Retry, never a guessed zone; Kenyan time still shown", async () => {
      let failing = true;
      const { page } = await openStudio(browser, "/", { db: withZone("America/New_York"), timezoneId: "Asia/Tokyo",
        fail: { get settings() { return failing ? 500 : undefined; } } });
      const s = await until(page, (x) => /Unavailable/.test(x), "no unavailable state", 20000);
      const studioPart = s.split(/Kenyan time/i)[0];
      if (/\d\d:\d\d:\d\d/.test(studioPart)) throw new Error(`studio clock guessed a time: ${s}`);
      if (!/GMT\+3/.test(s)) throw new Error(`Kenyan clock missing: ${s}`);
      await shot(page, "settings-failed");
      failing = false;
      await clock(page).getByRole("button", { name: "Retry" }).click();
      await until(page, (x) => x.includes("New York") && /E[SD]T/.test(x), "retry didn't recover");
    });

    await check("Loading state before settings answer; an unsaved zone is labelled as the default", async () => {
      const slow = await openStudio(browser, "/", { db: withZone("America/New_York"), slowSetting: { timezone: 4000 } });
      await until(slow.page, (x) => x.includes("Loading"), "no loading state");
      const unsaved = await openStudio(browser, "/", { db: withZone(undefined) });
      await until(unsaved.page, (x) => /default/i.test(x) && x.includes("Nairobi"), "unsaved zone not labelled default");
    });

    await check("Phone layout: both clocks visible, no sideways scroll, nav intact", async () => {
      const { page } = await openStudio(browser, "/", { db: withZone("America/New_York"), viewport: PHONE });
      await until(page, (s) => s.includes("EST") || s.includes("EDT"), "phone clock");
      const box = await clock(page).boundingBox();
      if (!box || box.x < 0 || box.x + box.width > PHONE.width + 1) throw new Error(`clock overflows: ${JSON.stringify(box)}`);
      const wide = await page.evaluate(() => document.documentElement.scrollWidth);
      if (wide > PHONE.width) throw new Error(`page scrolls sideways: ${wide}px`);
      await page.getByRole("navigation", { name: "Main" }).last().getByRole("link", { name: "Calendar" }).click();
      await page.waitForURL(/\/calendar/);
      await shot(page, "phone");
    });
  });
} finally {
  server.kill();
}
for (const r of results) console.log(r.join(" | "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
