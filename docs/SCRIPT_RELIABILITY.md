# Script reliability: why no package was ready, and what changed

Owner's report (28 Oct 2026): every generated video arrived with unsupported claims, wrong sums, repetition and no
Shorts, so none could be posted. This is the investigation and the fix, phase by phase.

## Phase 1: diagnosis (read-only, live database)

Sample: the five most recent long packages, both channels. Penny: "Cash ISA or Invest?" (34 claims, 16 failing).
Pixel: "Microsoft's AI Spend", "GPT-6.1 Terra in Action", "Does AI Actually Make Work Better?", "Why Most Companies
Still Don't See ROI from AI". For each: its sources, the saved fact sheet, script versions and steps, every claim with
the checker's verdict and note, Shorts attempts, production jobs and final status.

Not every "unsupported" verdict was right, and not every claim the writer made was true. Both kinds of error were
found.

| # | Cause | Evidence | Kind |
|---|---|---|---|
| A1 | The checker saw only the first 1,500 characters of each source | The Guardian article states "the US Federal Reserve … anticipated raising rates three times in 2022" at character 2,061; the claim was marked "not in the source" | false failure |
| A2 | The checker never saw a source's date | "raised rates to 0.25% **in 2021**", "as of 2023-04-27": "source does not specify the year" (5 of the ISA's 14) | false failure |
| A3 | The fact sheet wasn't saved with the script | Script versions held claims citing F1…F12 with no record of those facts; only a job output had them, without passages | can't recheck |
| A4 | Sum checker too literal | "2.72 = 272 / 100" (invalid syntax), "six months" vs `6`, comparisons (`0.01 < 0.06`), "$1 million" vs `1000000` | false failure |
| B1 | Wrong sums, never fixed | "+58%" (the figures give +250%), "£300" (£480), "17.7%" with a sum giving 71% | real error |
| B2 | Invented inputs and leaked notes | "200,000 employees", "9.5", and the spoken line "The fact sheet does not provide the total number of employees" | real error |
| B3 | Old and off-topic sources | A 2026 ISA video built on 2021-2023 news and a currency-API product page | real error |
| B4 | General principles treated as unsourced facts | "Inflation reduces purchasing power": "opinion" in one place, "unsupported" in another | inconsistent |
| C1 | The final check ran after the last repair | Order was: fix claims → voice edit → critic rewrite → final check, with no repair after the last two | design |
| C2 | The critic's cuts couldn't be applied | "Delete scenes 10-15, merge 3-5": the fixer could only reword scenes, never remove them; pacing stayed at 2-4 | design |
| C3 | Padding to reach 8 minutes | 6-8 minutes from 30-34 scenes, the same example 3 times, the disclaimer 3 times | design |
| C4 | Shorts always dropped | 15 of 15 attempts "too thin" (4-15 s against 35-55 s); the retry regenerated from scratch | design |
| C5 | One busy polishing model failed the whole package | 5 runs ended "All providers failed for 'voice_editor'", discarding finished work | design |
| D1 | All notes looked like blockers | "Title marked as UK-specific" (a note) listed with unsupported facts | reporting |

Also found: automatic posting (`auto_review_post`) is **on** in the live settings. It approves only packages that
pass every check, so nothing has been posted automatically. It should stay off while this is rolled out:
**Settings → Automation**.

## Phases 2-5: the fix

**Evidence before writing** (`engine/studio/script/evidence.py`)
- Each fact keeps the sentence that states it (found in the source by code), the source's id and publication date,
  and a time kind: historical, current, forecast or general. A "current" figure from a source older than
  `stale_after_days` (config/research.yaml: AI 180, money 365) becomes historical.
- The fact sheet is saved with every script version (`facts` in the version body), so any later version is checked
  against the same evidence.
- Sources that share too few of the topic's words are set aside and listed (e.g. the currency-API page), never used
  silently.
- The checker gets, for each cited fact: the fact, its passage, publication date and data period, plus the parts of
  the full article that best match the claim (anywhere in it). Claims are checked in batches of 8 so each fits a free
  model.
- Too few checkable facts: the studio searches for more evidence once, then stops with an explanation and a next
  step ("narrow the topic to what the sources cover…") instead of writing.

**Achievable writing** (`pipeline.py`)
- Length follows the evidence: about 0.6 minute per checked fact, between 5 minutes (`min_long_minutes_floor`) and
  the 11-minute target. A shorter video is reported as a note (YouTube shows mid-video ads from 8 minutes).
- The writer is told to say history with its date, forecasts with whose they are, and to mark general principles
  (`kind=principle`, no figures, names or dates) and opinions as such. It must never mention the fact sheet.
- New claim rules, decided by code: a historical figure without a date → **stale** (a blocker); a forecast said as a
  fact → unsupported; a principle with no numbers → **general**; a principle with numbers → unsupported.

**Targeted repair** (`repair.py`, `pipeline.finish_long`), in this order, bounded:
1. Voice edit (skipped, not failed, if no model is free).
2. Code fixes: claim links (F3 used as C3), repeated sentences, the disclaimer kept once at the end, animation labels
   the narrator doesn't say.
3. Critic: its delete and merge lists are applied (never the first or last scene, never below 6 scenes or the
   shortest length), then the merged or weak scenes are rewritten (at most 8).
4. Up to 2 repair rounds: wrong sums recalculated by code and the number replaced in the claim, the narration and
   the visual; then only the scenes still carrying a failing claim or a blocking check are rewritten, with their
   evidence and an instruction to cite, qualify (date, attribution) or remove. Each round is rechecked.
5. Last resort: a scene whose statement still can't be backed is removed, if the video stays long enough.
6. Final check of the exact version that is saved: claims, structure, and one final critic score.

Shorts: each Short must be 90-130 words. A failed Short is repaired on its own (twice at most) before anything is
regenerated, and the main video is never touched.
Platform posts: numbers in the X post, Facebook post and YouTube title must come from the evidence.

**Status reporting**: every result is one of four kinds, saved as `findings`:
- blocker: unsupported, contradicted or stale claims, numbers without a source, invented tests, structure;
- warning: editor scores below 7 (each score with its stated criterion), long sentences;
- missing: Shorts that couldn't be made;
- info: what the studio changed or noticed.

A package needs attention only for blockers. Warnings still stop automatic approval, so no threshold was lowered.

## Phase 6: repairing existing packages

**Review → Recheck and repair** (job `repair_package`, migration 22):
- Only for unapproved packages (needs attention, ready for review, failed) with nothing posting or posted.
- It reuses the saved facts (from the version, or the original job's output) and adds passages, ids and dates by code.
- It runs the same repair flow on the current script, without redrafting it. It saves a new version (origin
  `repair`) and keeps the old ones.
- It re-renders only the preview, and makes Shorts only if the package has none.
- One run per script version: projects, posts and publishing attempts are never duplicated.
- If no independent checker is free, it waits and changes nothing.

## Phase 7: validation

**Mocked AI (scripted answers), real code and a real database:**
- `engine/tests/test_script_reliability.py`: 35 tests, one or more per cause above.
- Full engine suite; dashboard unit tests; browser suites including `e2e/quality.mjs` (Review findings and the
  repair button).

**Real data, no AI calls** (replay of the live Penny ISA package's actual sources, facts and claims):
- Sources: 3 of 6 kept; the currency-API page and two articles without the topic's words set aside.
- Facts: all 11 linked to the sentence that states them; ten marked historical (2021-2023 sources), one current.
- The 6 claims wrongly failed for A1/A2 (Fed "three times", ECB, "6% next spring", "0.25% in 2021", "as of 2023",
  Huw Pill): the evidence the checker now receives contains every specific they state.
- All 14 worked sums from the five packages:
  - 4 wrongly failed now pass: comparison, "2.72 = 272/100", "$1 million", and one already right;
  - 3 wrong results are corrected by code: £300→£480, 58%→250%, 17.7%→70.8%. Code trusts the writer's arithmetic
    and fixes the stated result; each change is listed under "What the studio changed" for the reviewer;
  - sums built on invented inputs still fail (200,000 employees, 9.5, an unstated $1 million, an unstated 20);
  - "six months" is no longer called a calculation; the writer is asked to cite the fact instead.

**Not yet done: actual AI provider responses.** The rewrites and verdicts above are scripted. Running the corrected
workflow on real packages uses the free AI services for a few minutes per package and needs the owner's approval
first (see the pull request). Nothing has been generated, approved or posted.
