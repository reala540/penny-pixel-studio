// Phase 1 checks in a real browser against simulated services, plus desktop and phone screenshots.
// Run: node e2e/phase1.mjs   (screenshots go to e2e/screenshots/phase1)
import { mkdirSync } from "node:fs";
import { openStudio, startServer, withBrowser } from "./harness.mjs";

const OUT = new URL("./screenshots/phase1/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });
const PHONE = { width: 390, height: 844 };
const results = [];

async function check(name, fn) {
  try { await fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name, String(e).slice(0, 400)]); }
}
const expectText = async (page, text, timeout = 15000) => page.getByText(text, { exact: false }).first().waitFor({ timeout });
const shot = (page, name) => page.screenshot({ path: `${OUT}${name}.png`, fullPage: false });

const server = await startServer();
try {
  await withBrowser(async (browser) => {
    await check("Home loads normally (desktop and phone)", async () => {
      for (const [vp, tag] of [[undefined, "desktop"], [PHONE, "phone"]]) {
        const { page, context, errors } = await openStudio(browser, "/", { viewport: vp });
        await expectText(page, "Needs you");
        await expectText(page, "How to write better prompts");
        await shot(page, `home-normal-${tag}`);
        if (errors.length) throw new Error(errors.join("; "));
        await context.close();
      }
    });

    await check("Access-check failure is not 'not the owner': Retry works", async () => {
      let failing = true;
      const { page, context } = await openStudio(browser, "/calendar", { fail: { "rpc:claim_ownership": 503 }, onRequest: () => {} });
      await expectText(page, "Couldn't check your access");
      if (await page.getByText("already has an owner").count()) throw new Error("showed not-owner");
      await shot(page, "access-check-failed-desktop");
      await context.unroute("**/rpc/claim_ownership").catch(() => {});
      failing = false;
      await context.route("https://mock-supabase.test/rest/v1/rpc/claim_ownership", (r) => r.fulfill({ status: 200, headers: { "access-control-allow-origin": "*", "content-type": "application/json" }, body: "true" }));
      await page.getByRole("button", { name: "Retry" }).click();
      await page.waitForURL("**/calendar");
      await expectText(page, "Calendar");
      void failing;
      await context.close();
    });

    await check("A confirmed non-owner is refused", async () => {
      const { page, context } = await openStudio(browser, "/", { owner: false });
      await expectText(page, "already has an owner");
      await context.close();
    });

    await check("Failed settings never read as OFF / not paused / not linked", async () => {
      const { page, context } = await openStudio(browser, "/", { fail: { settings: 500 } });
      await expectText(page, "Approval: couldn't check");
      await expectText(page, "Couldn't check whether publishing is paused");
      if (await page.getByText("Approval: You approve").count()) throw new Error("claimed You approve");
      if (await page.getByText("Link Telegram").count()) throw new Error("claimed Telegram not linked");
      if (await page.getByText("Welcome to your studio").count()) throw new Error("opened the tour on a failed check");
      await shot(page, "settings-failed-desktop");
      await context.close();
      const phone = await openStudio(browser, "/", { fail: { settings: 500 }, viewport: PHONE });
      await expectText(phone.page, "Couldn't check whether publishing is paused");
      await shot(phone.page, "settings-failed-phone");
      await phone.context.close();
    });

    await check("Failed lists say they failed, not 'nothing here'", async () => {
      const { page, context } = await openStudio(browser, "/", { fail: { generation_jobs: 500 } });
      await expectText(page, "Couldn't load what's being made");
      if (await page.getByText("Nothing is being made right now").count()) throw new Error("claimed nothing is being made");
      if (await page.getByText("Nothing needs you right now").count()) throw new Error("claimed nothing needs you");
      if (await page.getByText("Studio idle").count()) throw new Error("claimed the studio is idle");
      await expectText(page, "Couldn't check what's running");
      await shot(page, "lists-failed-desktop");
      await context.close();
      const act = await openStudio(browser, "/activity", { fail: { generation_jobs: 500 } });
      await expectText(act.page, "Couldn't load what's running");
      if (await act.page.getByText("Nothing is running").count()) throw new Error("Activity claimed nothing is running");
      await shot(act.page, "activity-failed-desktop");
      await act.context.close();
    });

    await check("Offline is shown, and reconnecting refreshes", async () => {
      const { page, context } = await openStudio(browser, "/");
      await expectText(page, "Needs you");
      await context.setOffline(true);
      await page.evaluate(() => window.dispatchEvent(new Event("offline")));
      await expectText(page, "You're offline");
      await shot(page, "offline-desktop");
      await context.setOffline(false);
      await page.evaluate(() => window.dispatchEvent(new Event("online")));
      await page.getByText("You're offline").first().waitFor({ state: "detached", timeout: 10000 });
      await context.close();
    });

    await check("Signed out: the destination is kept through sign-in", async () => {
      const { page, context } = await openStudio(browser, "/content/proj-1?tab=posts", { signedIn: false });
      await expectText(page, "Sign in");
      await shot(page, "signed-out-desktop");
      const stored = await page.evaluate(() => sessionStorage.getItem("studio-return-to"));
      if (stored !== "/content/proj-1?tab=posts") throw new Error(`remembered ${stored}`);
      await context.close();
    });

    await check("Expired sign-in that can't refresh: sign in again, then come back", async () => {
      const { page, context } = await openStudio(browser, "/calendar?week=1#post-x", { sessionSeconds: -60, fail: { "auth:refresh": 400 } });
      await expectText(page, "Sign in");
      await shot(page, "session-expired-desktop");
      const stored = await page.evaluate(() => sessionStorage.getItem("studio-return-to"));
      if (stored !== "/calendar?week=1#post-x") throw new Error(`remembered ${stored}`);
      await context.close();
    });

    await check("Failed save shows an error and keeps the old state (pause button)", async () => {
      const { page, context, db } = await openStudio(browser, "/settings/automation", { fail: {} });
      await expectText(page, "Pause publishing");
      await context.route("https://mock-supabase.test/rest/v1/settings*", (r) => r.request().method() === "POST"
        ? r.fulfill({ status: 500, headers: { "access-control-allow-origin": "*", "content-type": "application/json" }, body: JSON.stringify({ message: "simulated save failure" }) })
        : r.fallback());
      await page.getByRole("button", { name: "Pause publishing" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Pause publishing" }).click();
      await expectText(page, "Publishing was not paused");
      if (await page.getByText("simulated save failure", { exact: true }).count()) throw new Error("showed the same failure twice");
      if (db.settings.paused !== false) throw new Error("paused changed despite failure");
      await shot(page, "save-failed-desktop");
      await context.close();
    });

    await check("Another tab's change refreshes this tab", async () => {
      const a = await openStudio(browser, "/");
      await expectText(a.page, "Approval: You approve");
      const b = await a.context.newPage();
      await b.goto(a.page.url());
      await b.getByText("Approval: You approve").first().waitFor();
      a.db.settings.auto_review_post = true;
      await a.page.evaluate(() => new BroadcastChannel("penny-pixel-studio").postMessage({ kind: "changed" }));
      await b.getByText("Approval: Auto Review & Post").first().waitFor({ timeout: 10000 });
      await a.context.close();
    });

    await check("Old addresses and OAuth returns keep their query", async () => {
      const { page, context } = await openStudio(browser, "/settings?connected=youtube");
      await page.waitForURL("**/settings/accounts?connected=youtube");
      await context.close();
      const r = await openStudio(browser, "/review/proj-1");
      await r.page.waitForURL("**/content/proj-1");
      await r.context.close();
    });
  });
} finally {
  server.kill();
}

for (const r of results) console.log(r.join(" | "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
