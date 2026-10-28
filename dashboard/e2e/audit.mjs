// Audit fixes (26 Oct 2026) in a real browser against simulated services.
// Run: node e2e/audit.mjs   (screenshots go to e2e/screenshots/audit, or E2E_SCREENSHOT_DIR)
import { mkdirSync } from "node:fs";
import { openStudio, seed, startServer, withBrowser } from "./harness.mjs";

const OUT = `${process.env.E2E_SCREENSHOT_DIR ?? new URL("./screenshots", import.meta.url).pathname}/audit/`;
mkdirSync(OUT, { recursive: true });
const PHONE = { width: 390, height: 844 };
const results = [];
async function check(name, fn) {
  try { await fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name, String(e).slice(0, 500)]); }
}
const cors = { "access-control-allow-origin": "*", "content-type": "application/json" };
const expectText = (page, text, timeout = 15000) => page.getByText(text, { exact: false }).first().waitFor({ timeout });
const shot = (page, name) => page.screenshot({ path: `${OUT}${name}.png`, fullPage: true });

const server = await startServer();
try {
  await withBrowser(async (browser) => {
    await check("Approval sends the exact version shown; a changed version is refused and reported", async () => {
      const db = seed();
      db.content_projects.push({ ...db.content_projects[0], id: "proj-2", title: "Another package", current_script_version_id: "sv-2" });
      const { page, context } = await openStudio(browser, "/content", { db });
      const sent = [];
      await context.route("https://mock-supabase.test/rest/v1/rpc/approve_project", (route) => {
        const body = JSON.parse(route.request().postData());
        sent.push(body);
        const changed = body.p_project_id === "proj-2";  // the server says proj-2's script changed meanwhile
        return route.fulfill({ status: changed ? 400 : 200, headers: cors,
          body: changed ? JSON.stringify({ message: "The script changed after you opened it. Reload and review the current version before approving." }) : "1" });
      });
      await page.getByRole("button", { name: "Approve all 2 that passed every check" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Approve 2", exact: true }).click();
      const list = page.getByRole("list", { name: "Approval results" });
      await list.waitFor();
      const text = await list.innerText();
      if (!text.includes("Another package: Not approved") || !text.includes("script changed")) throw new Error(`results: ${text}`);
      const versions = Object.fromEntries(sent.map((b) => [b.p_project_id, b.p_expected_version]));
      if (versions["proj-1"] !== "sv-1" || versions["proj-2"] !== "sv-2") throw new Error(`versions sent: ${JSON.stringify(versions)}`);
      await shot(page, "bulk-version-refused-desktop");
      await context.close();
    });

    await check("Before migration 14 the version is checked in the browser, then the older approval is used", async () => {
      const db = seed();
      const { page, context } = await openStudio(browser, "/content", { db });
      const sent = [];
      await context.route("https://mock-supabase.test/rest/v1/rpc/approve_project", (route) => {
        const body = JSON.parse(route.request().postData());
        sent.push(body);
        if ("p_expected_version" in body) return route.fulfill({ status: 404, headers: cors, body: JSON.stringify({ code: "PGRST202", message: "Could not find the function public.approve_project(p_expected_version, p_notes, p_project_id)" }) });
        return route.fulfill({ status: 200, headers: cors, body: "1" });
      });
      await page.getByRole("button", { name: /Approve all 1 that passed every check/ }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Approve 1", exact: true }).click();
      await page.getByRole("list", { name: "Approval results" }).waitFor();
      if (sent.length !== 2 || "p_expected_version" in sent[1]) throw new Error(`calls: ${JSON.stringify(sent)}`);
      // and a version that changed meanwhile is refused before the older function is called
      db.content_projects[0].status = "ready_for_review"; db.content_projects[0].current_script_version_id = "sv-9";
      sent.length = 0;
      await page.reload();
      await context.route("https://mock-supabase.test/rest/v1/content_projects*", (route) => route.request().url().includes("select=status%2Ccurrent_script_version_id")
        ? route.fulfill({ status: 200, headers: cors, body: JSON.stringify([{ status: "ready_for_review", current_script_version_id: "sv-10" }]) }) : route.fallback());
      await page.getByRole("button", { name: /Approve all 1 that passed every check/ }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Approve 1", exact: true }).click();
      await expectText(page, "script changed after you opened it");
      if (sent.some((b) => !("p_expected_version" in b))) throw new Error("the older approval ran for a changed version");
      await context.close();
    });

    await check("A post can't be moved into the past (before or after migration 13)", async () => {
      for (const pre13 of [false, true]) {
        const db = seed();
        db.scheduled_posts = [{ id: "post-1", status: "scheduled", scheduled_at: new Date(Date.now() + 3 * 86400000).toISOString(), social_account_id: "acc-yt-ai",
          variant_id: "v1", content_variants: { project_id: "proj-1", title: "Prompts video", kind: "long_video", body: "x" }, social_accounts: { label: "YouTube AI", platform: "youtube" }, published_posts: null }];
        const { page, context, calls } = await openStudio(browser, "/calendar?post=post-1", { db, pre13 });
        await page.getByRole("heading", { name: "Prompts video", exact: true }).waitFor();
        await page.locator("#when").fill("2020-01-01T09:00");
        await page.getByRole("button", { name: "Change time" }).click();
        await expectText(page, "already passed");
        if (calls.some((c) => c.path.includes("reschedule_post") || (c.method === "PATCH" && c.path.includes("scheduled_posts")))) throw new Error("a past time was sent");
        if (!pre13) await shot(page, "past-time-refused-desktop");
        await context.close();
      }
    });

    await check("Without migration 13: no page-wide sync error, drafts say where they're kept, polling stops", async () => {
      for (const [vp, tag] of [[undefined, "desktop"], [PHONE, "phone"]]) {
        const { page, context, calls, errors } = await openStudio(browser, "/", { pre13: true, viewport: vp });
        await page.evaluate(() => localStorage.setItem("studio-create-drafts:00000000-0000-4000-8000-000000000001",
          JSON.stringify([{ id: "d1", rev: 1, updatedAt: new Date().toISOString(), step: "idea", channel: "ai", kind: null, ideaId: null, own: "An idea typed on this device", depth: 3 }])));
        await page.reload();
        await expectText(page, "Unfinished");
        await expectText(page, "sync unavailable until the latest database update");
        await page.waitForTimeout(3000);
        const body = await page.locator("body").innerText();
        if (/cloud recovery is unavailable|cloud sync needs Retry|Retry sync/.test(body)) throw new Error("misleading sync banner shown");
        const before = calls.filter((c) => c.path === "/rest/v1/studio_drafts").length;
        await page.waitForTimeout(16500);
        const after = calls.filter((c) => c.path === "/rest/v1/studio_drafts").length;
        if (after > before) throw new Error(`kept polling a missing table (${before} -> ${after})`);
        if (errors.length) throw new Error(errors.join("; "));
        await shot(page, `pre13-home-${tag}`);
        await context.close();
      }
    });
  });
} finally {
  server.kill();
}
for (const r of results) console.log(r.join(" | "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
