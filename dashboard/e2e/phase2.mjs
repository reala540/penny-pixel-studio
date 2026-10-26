// Phase 2: drafts and unfinished work, in a real browser against simulated services.
// Run: node e2e/phase2.mjs   (screenshots go to e2e/screenshots/phase2)
import { mkdirSync } from "node:fs";
import { BASE, newTab, openStudio, seed, startServer, withBrowser } from "./harness.mjs";

const OUT = new URL("./screenshots/phase2/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });
const PHONE = { width: 390, height: 844 };
const results = [];
async function check(name, fn) {
  try { await fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name, String(e).slice(0, 500)]); }
}
const expectText = (page, text, timeout = 15000) => page.getByText(text, { exact: false }).first().waitFor({ timeout });
const shot = (page, name) => page.screenshot({ path: `${OUT}${name}.png`, fullPage: true });
const iso = (m) => new Date(Date.now() + m * 60_000).toISOString();

function withIdeas() {
  const db = seed();
  db.generated_ideas = [{ id: "g1", run_id: "r1", rank: 1, title: "Three AI tools that save small shops time", summary: "Practical tools.", audience: "Small shops",
    markets: ["KE"], channel_slug: "ai", category: null, trend_verified: true, newest_evidence_at: iso(-600), total: 82, score_explanation: "", assessment_notes: {},
    trend_signals: [{ source_id: "s1", title: "Shops adopt AI", url: "https://example.com/a", observed: "news", published_at: iso(-1000) }],
    scores: { trend: 80, originality: 70, international: 60, feasibility: 90, engagement: 80 }, confidence: "high", sensitivity: "none", sensitivity_note: null,
    suggested_format: null, execution: null, generated_by: "m", assessed_by: "n", status: "new", status_history: [], owner_note: null, content_idea_id: null, created_at: iso(-60) }];
  db.generation_jobs = [];
  return db;
}
const jobInserts = (calls) => calls.filter((c) => c.method === "POST" && c.path === "/rest/v1/generation_jobs").length;
const drafts = (page) => page.evaluate(() => Object.entries(localStorage).filter(([k]) => k.startsWith("studio-create-drafts:")).map(([k, v]) => [k, JSON.parse(v)]));

const server = await startServer();
try {
  await withBrowser(async (browser) => {
    await check("Choices survive leaving the page; Continue goes back to the same idea without starting anything", async () => {
      const db = withIdeas();
      const { page, context, calls, errors } = await openStudio(browser, "/create", { db });
      await page.getByRole("button", { name: /Pixel · Penny & Pixel AI/ }).click();
      await expectText(page, "Three AI tools");
      await page.getByRole("button", { name: "Use this idea" }).click();
      await expectText(page, "Step 3 · Check the research");
      await expectText(page, "Saved on this device");
      await page.close();                                            // close the tab
      const again = await newTab(context, "/create");
      await expectText(again, "Continue where you left off");
      await expectText(again, "checking the research");
      await shot(again, "continue-list-desktop");
      await again.getByRole("link", { name: "Continue" }).click();
      await expectText(again, "Step 3 · Check the research");
      await expectText(again, "Three AI tools that save small shops time");
      if (jobInserts(calls)) throw new Error("opening or continuing queued a job");
      if (errors.length) throw new Error(errors.join("; "));
      await context.close();
    });

    await check("Typed idea is kept, shown on Home as Unfinished, and secrets are never stored", async () => {
      const { page, context } = await openStudio(browser, "/create?step=idea&channel=ai", { db: withIdeas() });
      await page.getByPlaceholder("Example: Three practical AI tools").fill("How Kenyan farmers use AI weather apps");
      await expectText(page, "Saved on this device");
      await page.goto(`${BASE}/`);
      await expectText(page, "Unfinished");
      await expectText(page, "How Kenyan farmers use AI weather apps");
      await shot(page, "home-unfinished-desktop");
      if ((await page.getByRole("link", { name: "Continue" }).count()) !== 1) throw new Error("one session made more than one draft");
      await page.getByRole("link", { name: "Continue" }).click();
      const box = page.getByPlaceholder("Example: Three practical AI tools");
      await box.waitFor();
      if ((await box.inputValue()) !== "How Kenyan farmers use AI weather apps") throw new Error(`text was ${await box.inputValue()}`);
      await box.fill("my key is sk-abcdefghijklmnopqrstuvwxyz123456");
      await page.waitForTimeout(1200);
      const stored = JSON.stringify(await drafts(page));
      if (stored.includes("sk-abc")) throw new Error("a secret-looking text was stored");
      await context.close();
    });

    await check("Phone: Unfinished and Continue work", async () => {
      const { page, context } = await openStudio(browser, "/create", { db: withIdeas(), viewport: PHONE });
      await page.getByRole("button", { name: /Penny · Penny & Pixel Money/ }).click();
      await expectText(page, "Saved on this device");
      await page.goto(`${BASE}/`);
      await expectText(page, "Unfinished");
      await shot(page, "home-unfinished-phone");
      await page.goto(`${BASE}/create`);
      await expectText(page, "Continue where you left off");
      await shot(page, "continue-list-phone");
      await context.close();
    });

    await check("Drafts belong to one owner", async () => {
      const { page, context } = await openStudio(browser, "/create?step=idea&channel=ai", { db: withIdeas() });
      await page.getByPlaceholder("Example: Three practical AI tools").fill("Owner A's private idea about AI");
      await expectText(page, "Saved on this device");
      const keys = (await drafts(page)).map(([k]) => k);
      if (!keys.length || !keys.every((k) => k.endsWith("00000000-0000-4000-8000-000000000001"))) throw new Error(`keys ${keys}`);
      await context.close();
      // same device storage, different account: simulate by seeding A's draft into B's browser
      const b = await openStudio(browser, "/", { db: withIdeas(), userId: "00000000-0000-4000-8000-00000000000b" });
      await b.page.evaluate(() => localStorage.setItem("studio-create-drafts:00000000-0000-4000-8000-000000000001",
        JSON.stringify([{ id: "x", rev: 1, updatedAt: new Date().toISOString(), step: "idea", channel: "ai", kind: null, ideaId: null, own: "Owner A's private idea about AI", depth: 3 }])));
      await b.page.reload();
      await expectText(b.page, "Needs you");
      if (await b.page.getByText("Owner A's private idea").count()) throw new Error("another account saw the draft");
      await b.context.close();
    });

    await check("Deleted idea: the draft says so and Continue goes back to choosing an idea", async () => {
      const db = withIdeas();
      const { page, context } = await openStudio(browser, "/", { db });
      await page.evaluate(() => localStorage.setItem("studio-create-drafts:00000000-0000-4000-8000-000000000001",
        JSON.stringify([{ id: "d-gone", rev: 1, updatedAt: new Date().toISOString(), step: "package", channel: "ai", kind: "generated", ideaId: "g-deleted", ideaTitle: "An idea that was deleted", own: "", depth: 3 }])));
      await page.reload();
      await expectText(page, "that idea no longer exists");
      await page.getByRole("link", { name: "Continue" }).click();
      await expectText(page, "Step 2 · Choose or generate an idea");
      await context.close();
    });

    await check("Failed package: Fix problem opens progress with Try again; opening starts nothing", async () => {
      const db = withIdeas();
      db.generation_jobs = [{ id: "j-failed", job_type: "produce_idea", status: "failed", error_message: "All providers failed for 'critic'", input: { generated_idea_id: "g1", channel: "ai" },
        project_id: null, progress: {}, created_at: iso(-30), updated_at: iso(-20), started_at: iso(-29), finished_at: iso(-20), requested_by: "owner", content_projects: null }];
      const { page, context, calls } = await openStudio(browser, "/", { db });
      await page.evaluate(() => localStorage.setItem("studio-create-drafts:00000000-0000-4000-8000-000000000001",
        JSON.stringify([{ id: "d-f", rev: 1, updatedAt: new Date().toISOString(), step: "progress", channel: "ai", kind: "generated", ideaId: "g1", ideaTitle: "Three AI tools that save small shops time", own: "", depth: 3 }])));
      await page.reload();
      await expectText(page, "a step didn't work");
      await shot(page, "home-failed-draft-desktop");
      await page.getByRole("link", { name: "Fix problem" }).first().click();
      await expectText(page, "This didn't work");
      await expectText(page, "Try again from this step");
      if (jobInserts(calls)) throw new Error("opening the failed package queued a job");
      await context.close();
    });

    await check("The same draft changed in two tabs: the second is asked which version to keep", async () => {
      const { page, context } = await openStudio(browser, "/create?step=idea&channel=ai", { db: withIdeas() });
      const box = page.getByPlaceholder("Example: Three practical AI tools");
      await box.fill("First version of my idea");
      await expectText(page, "Saved on this device");
      const url = page.url();
      const other = await newTab(context, url.replace(BASE, ""));
      const otherBox = other.getByPlaceholder("Example: Three practical AI tools");
      await otherBox.waitFor();
      await otherBox.fill("Changed in the other tab");
      await other.waitForTimeout(1200);
      await box.fill("Changed in the first tab too");
      await expectText(page, "This draft was changed in another tab");
      await shot(page, "conflict-desktop");
      await page.getByRole("button", { name: "Use the other tab's version" }).click();
      await page.waitForTimeout(500);
      if ((await box.inputValue()) !== "Changed in the other tab") throw new Error(`kept ${await box.inputValue()}`);
      await context.close();
    });

    await check("Create package from two tabs or two devices makes one job, not two", async () => {
      const db = withIdeas();
      db.settings.provider_check = { checked_at: iso(-10), results: [{ provider: "groq", status: "ok" }] };
      const path = "/create?step=package&channel=ai&kind=generated&id=g1";
      const { page, context, calls } = await openStudio(browser, path, { db });
      const tab = await newTab(context, path);
      const phone = await openStudio(browser, path, { db, viewport: PHONE });  // another device: can't hear this browser's tabs
      for (const p of [page, tab, phone.page]) await p.getByRole("button", { name: "Create package" }).waitFor();
      await page.getByRole("button", { name: "Create package" }).click();
      await page.waitForTimeout(800);
      for (const j of db.generation_jobs) if (j.job_type === "produce_idea") j.status = "queued";
      await expectText(tab, "already being made");                     // the other tab updated by itself
      await phone.page.getByRole("button", { name: "Create package" }).click();  // the other device still offers it
      await expectText(phone.page, "already being made");
      await shot(phone.page, "second-device-already-made-phone");
      const inserts = jobInserts(calls) + jobInserts(phone.calls);
      if (inserts !== 1) throw new Error(`${inserts} jobs queued`);
      await phone.context.close();
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
