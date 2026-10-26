// Every page, with every table and the Worker failing: nothing may crash or claim "nothing here" / "all fine".
// Run: node e2e/sweep.mjs   (screenshots go to e2e/screenshots/sweep)
import { mkdirSync } from "node:fs";
import { openStudio, startServer, withBrowser } from "./harness.mjs";

const OUT = (process.env.E2E_SCREENSHOT_DIR || new URL("./screenshots/sweep/", import.meta.url).pathname).replace(/\/?$/, "/");
mkdirSync(OUT, { recursive: true });
const SECTIONS = ["setup", "accounts", "schedule", "automation", "ideas", "ai", "voices", "notifications", "budget", "appearance"];
const PAGES = ["/", "/create", "/content", "/content/ideas", "/content/proj-1", "/calendar", "/activity", "/help", ...SECTIONS.map((s) => `/settings/${s}`)];
// wording that claims there is nothing / everything is fine: must never appear while the data failed to load
const EMPTY = /\b(nothing (is |needs|planned|running|here)|no (posts|ideas|packages|runs|accounts|problems|channels|jobs|automatic|research)\b|studio idle|all clear|not linked|not connected|not checked yet|haven't been checked|no ai service that passed|^\d+ of \d+ needed steps done)/i;

const server = await startServer();
let failures = 0;
try {
  await withBrowser(async (browser) => {
    for (const path of PAGES) {
      for (const [vp, tag] of [[{ width: 1366, height: 900 }, "desktop"], [{ width: 390, height: 844 }, "phone"]]) {
        const { page, context, errors } = await openStudio(browser, path, { viewport: vp, fail: { "*": 500, "worker:*": 500 } });
        await page.waitForTimeout(2500);
        const name = (path === "/" ? "home" : path.slice(1).replace(/\//g, "-")) + `-${tag}`;
        await page.screenshot({ path: `${OUT}${name}.png`, fullPage: true });
        const text = await page.locator("body").innerText();
        const crashed = /something went wrong|unexpected application error/i.test(text);
        const claims = text.split("\n").filter((l) => EMPTY.test(l)).map((l) => l.trim()).slice(0, 6);
        const bad = errors.length || crashed || claims.length;
        if (bad) failures++;
        if (tag === "desktop" || bad)
          console.log(`${bad ? "FAIL" : "ok  "} ${path} [${tag}]${errors.length ? ` errors: ${errors.join("; ")}` : ""}${claims.length ? `\n      claims: ${claims.join(" | ")}` : ""}`);
        await context.close();
      }
    }
  });
} finally {
  server.kill();
}
console.log(failures ? `${failures} page views failed` : "no page crashed or claimed an answer it didn't have");
process.exit(failures ? 1 : 0);
