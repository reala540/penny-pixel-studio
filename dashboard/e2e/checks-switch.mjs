// The "Full auto-posting" switch in a real browser against simulated services.
// Run: node e2e/checks-switch.mjs
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { openStudio, seed, startServer, withBrowser } from "./harness.mjs";

const OUT = `${process.env.E2E_SCREENSHOT_DIR ?? new URL("./screenshots", import.meta.url).pathname}/checks-switch/`;
mkdirSync(OUT, { recursive: true });
const results = [];
async function check(name, fn) {
  try { await fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name, String(e).slice(0, 600)]); }
}
const sw = (page) => page.getByRole("switch", { name: "Full auto-posting" }).first();
const writes = (calls) => calls.filter((c) => c.method !== "GET" && c.method !== "HEAD" && c.path.includes("/rest/v1/settings"));

const server = await startServer();
try {
  await withBrowser(async (browser) => {
    await check("Home shows ON when the switch is on with no end time, and one tap turns it OFF", async () => {
      const db = seed(); db.settings.publish_without_checks = { on: true, auto_approve: true, set_by: "owner" };
      const { page, calls, context } = await openStudio(browser, "/", { db });
      await sw(page).waitFor({ timeout: 15000 });
      assert.equal(await sw(page).getAttribute("aria-checked"), "true");
      await page.getByText("Full auto-posting: ON").first().waitFor();
      await page.screenshot({ path: `${OUT}home-on.png` });
      await sw(page).click();
      await page.getByText("Full auto-posting: OFF").first().waitFor({ timeout: 10000 });
      assert.equal(db.settings.publish_without_checks.on, false, "the setting was saved as off");
      assert.equal(db.settings.publish_without_checks.auto_approve, false, "automatic approval off too");
      assert.ok(writes(calls).length >= 1, "a settings write was sent");
      await context.close();
    });
    await check("Turning ON asks first; Cancel changes nothing; Turn on saves it with no end time", async () => {
      const db = seed(); db.settings.publish_without_checks = { on: false };
      const { page, context } = await openStudio(browser, "/settings/automation", { db });
      await sw(page).waitFor({ timeout: 15000 });
      assert.equal(await sw(page).getAttribute("aria-checked"), "false");
      await sw(page).click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      await dialog.getByRole("button", { name: "Cancel" }).click();
      assert.equal(db.settings.publish_without_checks.on, false);
      await sw(page).click();
      await page.getByRole("dialog").getByRole("button", { name: "Turn on" }).click();
      await page.getByText("Full auto-posting: ON").first().waitFor({ timeout: 10000 });
      assert.equal(db.settings.publish_without_checks.on, true);
      assert.equal(db.settings.publish_without_checks.auto_approve, true, "approves automatically");
      assert.equal(db.settings.publish_without_checks.until, undefined, "no end time");
      await page.screenshot({ path: `${OUT}settings-on.png` });
      await context.close();
    });
    await check("An expired end time shows OFF (same rule as the engine)", async () => {
      const db = seed(); db.settings.publish_without_checks = { on: true, auto_approve: true, until: "2026-11-16T21:00:00Z" };
      const { page, context } = await openStudio(browser, "/", { db });
      await sw(page).waitFor({ timeout: 15000 });
      assert.equal(await sw(page).getAttribute("aria-checked"), "false");
      await context.close();
    });
    await check("Checks off but approvals manual shows OFF with a short note", async () => {
      const db = seed(); db.settings.publish_without_checks = { on: true };
      const { page, context } = await openStudio(browser, "/", { db });
      await sw(page).waitFor({ timeout: 15000 });
      assert.equal(await sw(page).getAttribute("aria-checked"), "false");
      await page.getByText("last-minute checks are off, but you still approve", { exact: false }).first().waitFor();
      await context.close();
    });
    await check("Phone width: the switch is visible and usable without sideways scrolling", async () => {
      const db = seed(); db.settings.publish_without_checks = { on: true, auto_approve: true };
      const { page, context } = await openStudio(browser, "/", { db, viewport: { width: 360, height: 780 } });
      await sw(page).waitFor({ timeout: 15000 });
      const box = await sw(page).boundingBox();
      assert.ok(box && box.width >= 40 && box.x >= 0 && box.x + box.width <= 360);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      assert.equal(overflow, false, "no horizontal scroll");
      await page.screenshot({ path: `${OUT}home-phone.png` });
      await context.close();
    });
  });
} finally {
  server.kill();
}
for (const r of results) console.log(r.join(" | "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
