# Automatic review and publishing recovery

Authorized scope: the six automation improvements requested on 8 November 2026. Automatic approval stays enabled; no credentials, paid services, platform permissions or published content are changed by this release.

## Before the changes

Read-only production baseline at 22:14 Nairobi time on 8 November: 16 packages, 24 review records, two repair jobs, zero automatic approvals and zero confirmed public packages attributable to automatic approval. Migration also freezes the actual deployment-time baseline in `automation_baseline_v2` rather than hard-coding live dashboard numbers.

## What changes

1. Partly supported claims enter the same bounded evidence-based repair path as unsupported statements. A model must qualify or remove the unsupported part, and an independent checker must pass the new saved version. The state is never changed to “supported” just to allow publication.
2. A failed final content check records claim-level reasons and queues a version-bound repair. Old approvals are withdrawn. Main narration, derivatives, post text, previews and thumbnails are rebuilt together and independently approved again. Published, uploading or ambiguous work is held rather than rewritten. Temporary checker outages get up to three publishing attempts with backoff; temporary repair-model outages can resume a saved script before rendering, with up to three attempts and delayed retries. Content repairs retain the owner's existing maximum (currently five). Irrecoverable failures remain visible.
3. The script editor always acts on low scores even when it supplies no weak-scene list. Rewrite instructions emphasize one question, concrete sourced examples and removal of repetition. A final claim check follows the last text cleanup. Optional repair polishing reuses an existing author or is skipped, preserving other companies for independent checking. Editorial score waivers never waive factual problems.
4. Financial topic words identify the subject, while actionable recommendations identify heightened risk. Neutral definitions and wage/inflation explanations are eligible; investment, loan or tax recommendations still trigger a hold. Generated sensitivity flags, trust settings and the independent publishing policy reviewer remain in force. Pattern detection is a conservative filter, not a complete financial-advice classifier.
5. Concrete document, spreadsheet and email tasks can use a small, spaced set of relevant illustrative stock scenes. Quantitative visuals, instructions and opening/closing cards remain intact. Pixabay query responses are cached for 24 hours without storing its API key. Media search rejects unrelated matches; no suitable licensed footage means a card fallback. No screenshots or hands-on demonstrations are invented. The existing Pixabay/Openverse/Pexels integrations are retained; no unavailable Pexels key is created.
6. Performance shows unique parent packages reviewed, sent for repair, automatically approved and confirmed public through an API. Review attempts and completed repair jobs are separate numbers; a completed repair is not claimed to have passed. Manual publication, private uploads and unknown visibility do not count as automatic public results. Public attribution uses the latest approval before publication. Stages overlap and represent all-time counts, not a conversion-rate cohort.

## Activation and verification

Repository workflow setup applies the versioned migration before updated code. An idempotent owner job revisits existing holds once under the corrected policy and considers existing final-check blocks for recovery. Subsequent unchanged holds do not loop indefinitely. Existing schedules, account permissions, duplicate-upload protection and the automatic-mode switch remain authoritative.

Tests exercise the full database journey from a partial claim to a repaired version, retired old derivatives, new automatic approval and a public receipt through a mocked external API. Additional cases cover model outages, resumable packaging, backoff, repair limits, changed versions, mode off, ambiguous uploads, financial wording, media relevance and owner-only metrics. Browser checks cover real zeros, unavailable metrics and phone layouts. Mocked publishing proves code behavior; actual account/provider availability still needs production observation.

## Local verification results

- Full engine regression run: 369 passed; one obsolete expectation that old Shorts stay scheduled failed. That expectation was corrected to require cancellation of superseded Shorts. The corrected test passed with real FFmpeg rendering; the final release run of that case and the cache-expiry test passed (2/2).
- Focused editor/script checks: 75 passed. Final recovery/media checks: 34 passed, including budget sharing, rejected/archived packages, outage resumption and the public-receipt journey. Additional version and author-reservation cases passed in the recovery checks.
- Dashboard type checking, all 103 unit tests and production build passed. The full browser page sweep passed; quality checks passed 10/10 including phone-sized automation counters and unavailable-data handling.
- No real social posts were uploaded during local testing. Production deployment, queue progress, account readiness and actual public receipts must be checked separately.

## Live deployment observations

The migration was applied in production, the owner-only funnel function exists, and Supabase health advisors returned no findings. Vercel reported successful dashboard and engine deployments for the main release. The activation review is queued. An older owner-request workflow was still running at deployment, so this is not yet evidence of a new live automatic approval or public post. Updated queue startup detects an activation review completed by older code without the new policy marker and replays it once; the handover regression and all recovery cases passed (26 tests).

## Follow-up verification, 9 November (Nairobi)

Both release CI runs, Vercel deployments and Cloudflare Pages deployment succeeded. The new activation policy executed and queued actual repairs. At 00:24 Nairobi, there were still no automatic approvals: free checker quota failures and unsupported statements remained. Two repairs had completed since activation; one package was ready for another review.

A live queue handoff issue was found: an `auto_review` job in a mixed batch suppressed the follow-up review for completed repairs. Completion now triggers review per package immediately (child jobs resolve to their parent), before the next long job. Queue startup also catches completed repairs left on a `fixing` verdict by an older process, without repeatedly reviewing terminal decisions. The mixed-batch, immediate-review and catch-up regression cases pass, along with all 29 focused recovery tests. The real FFmpeg repair-and-reapproval test also passes. This correction does not waive evidence checks, alter posting schedules or purchase model capacity.
