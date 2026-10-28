// Quality pack (28 Oct 2026) in a real browser against simulated services: separate "checks" and "approval" answers,
// a written reason for approving with problems, why a scene got a backup card, what each account can really do,
// choosing a Facebook Page, and Facebook Reels / text posts on their own times. Nothing real is called.
// Run: node e2e/quality.mjs   (screenshots go to e2e/screenshots/quality, or E2E_SCREENSHOT_DIR)
import { mkdirSync } from "node:fs";
import { openStudio, seed, startServer, withBrowser } from "./harness.mjs";

const OUT = `${process.env.E2E_SCREENSHOT_DIR ?? new URL("./screenshots", import.meta.url).pathname}/quality/`;
mkdirSync(OUT, { recursive: true });
const PHONE = { width: 390, height: 844 };
const results = [];
async function check(name, fn) {
  try { await fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name, String(e).slice(0, 500)]); }
}
const cors = { "access-control-allow-origin": "*", "content-type": "application/json" };
const expectText = (page, text, timeout = 15000) => page.getByText(text, { exact: false }).first().waitFor({ timeout });
const shot = (page, name) => page.screenshot({ path: `${OUT}${name}.png`, fullPage: true });
const iso = (m) => new Date(Date.now() + m * 60_000).toISOString();

function withProblems() {
  const db = seed();
  db.content_projects[0].recipe = { render: { scenes: [{ visual: { type: "title_card" } },
    { visual: { type: "title_card", fallback_reason: 'No matching photo for "coins in a jar" (pexels: nothing suitable), so this scene shows its words on a card.' } }] } };
  db.script_versions = [{ id: "sv-1", project_id: "proj-1", version: 1, origin: "ai", created_at: iso(-60),
    body: { title: "How to write better prompts", hook: "Prompts matter.", cta: "", scenes: [{ narration: "Save a little each week.", visual: { type: "stock", stock_query: "coins in a jar" } }] } }];
  db.research_claims = [{ id: "c1", project_id: "proj-1", script_version_id: "sv-1", claim_key: "k", claim_text: "Rates fell 9% last week", status: "unsupported", confidence: 0.2 }];
  return db;
}

const server = await startServer();
try {
  await withBrowser(async (browser) => {
    await check("Review says 'Needs corrections' and 'Waiting for your approval' separately, and shows why a scene got a card", async () => {
      const { page, context, errors } = await openStudio(browser, "/content/proj-1", { db: withProblems() });
      await expectText(page, "Needs corrections");
      await expectText(page, "Waiting for your approval");
      await page.getByRole("tab", { name: "Script" }).click().catch(() => {});
      await expectText(page, 'No matching photo for "coins in a jar"');
      if (errors.length) throw new Error(errors.join("; "));
      await shot(page, "review-badges-desktop");
      await context.close();
    });

    await check("Approving with an unsupported fact needs a written reason, which is sent with the approval", async () => {
      const { page, context } = await openStudio(browser, "/content/proj-1", { db: withProblems() });
      const sent = [];
      await context.route("https://mock-supabase.test/rest/v1/rpc/approve_project", (route) => {
        sent.push(JSON.parse(route.request().postData()));
        return route.fulfill({ status: 200, headers: cors, body: "1" });
      });
      await page.getByRole("button", { name: "Approve package" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByText("Why are you approving anyway?").waitFor();
      await dialog.getByText("Included").waitFor();
      const ok = dialog.getByRole("button", { name: "Approve anyway" });
      if (await ok.isEnabled()) throw new Error("approve was possible without a reason");
      await dialog.getByRole("textbox").fill("short");
      if (await ok.isEnabled()) throw new Error("a 5-letter reason was accepted");
      await dialog.getByRole("textbox").fill("I checked the rate on the central bank site myself.");
      await shot(page, "approve-reason-desktop");
      await ok.click();
      await expectText(page, "Approved:");
      if (sent.length !== 1 || !String(sent[0].p_notes).startsWith("I checked")) throw new Error(`sent: ${JSON.stringify(sent)}`);
      await context.close();
    });

    await check("Settings → Accounts shows what each connection can really do, and the next step", async () => {
      const db = seed();
      db.settings.account_capabilities = { checked_at: iso(-30), accounts: {
        "acc-yt-ai": { login_saved: true, connected_at: iso(-900), permissions_missing: [], can_publish: true, method: "api_draft",
          limitation: "API not yet audited by Google: uploads are private until you publish them in YouTube Studio", last_success_at: iso(-600),
          last_problem: null, last_problem_at: null, next_step: "API not yet audited by Google: uploads are private until you publish them in YouTube Studio" },
        "acc-x": { login_saved: false, connected_at: null, permissions_missing: ["tweet.write"], can_publish: false, method: "manual",
          limitation: "X account not connected", last_success_at: null, last_problem: null, last_problem_at: null, next_step: "Press Connect and sign in." } } };
      for (const vp of [null, PHONE]) {
        const { page, context, errors } = await openStudio(browser, "/settings/accounts", { db, viewport: vp ?? undefined });
        await expectText(page, "Posts as drafts you finish in the app");
        await expectText(page, "Missing permission: tweet.write");
        await expectText(page, "Next: Press Connect and sign in.");
        if (errors.length) throw new Error(errors.join("; "));
        await shot(page, `accounts-capabilities-${vp ? "phone" : "desktop"}`);
        await context.close();
      }
    });

    await check("With several Facebook Pages the owner chooses one; nothing is saved before", async () => {
      const { page, context, calls } = await openStudio(browser, "/settings/accounts?pick_page=sealed-list", { db: seed() });
      await context.route("https://mock-worker.test/api/oauth/facebook-pages", (route) => route.fulfill({ status: 200, headers: cors,
        body: JSON.stringify({ pages: [{ id: "111", name: "Penny & Pixel" }, { id: "222", name: "Old test page" }] }) }));
      await context.route("https://mock-worker.test/api/oauth/facebook-page", (route) => route.fulfill({ status: 200, headers: cors,
        body: JSON.stringify({ page: "Penny & Pixel", id: "111" }) }));
      await page.reload();
      await expectText(page, "Which Facebook Page should the studio post to?");
      await expectText(page, "Old test page");
      await shot(page, "pick-page-desktop");
      await page.getByRole("button", { name: /Penny & Pixel/ }).click();
      await expectText(page, "Facebook connected: Page Penny & Pixel (111)");
      if (page.url().includes("pick_page")) throw new Error("the choice stayed in the address");
      await context.close();
    });

    await check("Facebook Reels and text posts can get their own days and times; the week shows what's covered", async () => {
      const db = seed();
      db.social_accounts.push({ id: "acc-fb", platform: "facebook", label: "Facebook", handle: "Penny & Pixel", enabled: true, topic_mix: {},
        weekly_targets: { reel: 2, text_post: 1, posting_days: ["mon", "wed", "fri"], posting_times: ["12:30"] },
        oauth_connections: { status: "connected", last_error: null, token_expires_at: null, app_publish_mode: "unverified" } });
      const { page, context, errors } = await openStudio(browser, "/settings/schedule", { db });
      const card = page.getByRole("region", { name: /Facebook/ }).first();
      await card.getByText("Reels have their own days and times").click();
      await card.getByText("Reels: days").waitFor();
      await expectText(page, "Next 7 days: asked for, and really scheduled");
      await expectText(page, "not enough short videos made and approved yet");
      if (errors.length) throw new Error(errors.join("; "));
      await shot(page, "facebook-own-times-desktop");
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
