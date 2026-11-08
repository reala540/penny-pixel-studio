# Requested reliability, publishing and website changes

Scope: the owner's pasted instructions on 8 November 2026. Automatic approval/posting remains enabled; this release does not introduce a new manual approval mode or purchase any service.

## Ordered completion checklist

| Step | Result |
|---|---|
| 1. Money maths | Match signed results, units and displayed precision; do not accept an input as the result. An independent model also checks whether a formula answers the question. |
| 2. Automatic money workflow | Existing automation switches are preserved. Unsupported or sensitive content retains the existing holds; no new manual approval switch is enabled. |
| 3. YouTube visibility | Request public uploads independently of app audit status; record returned visibility and check it again through the API. No platform restrictions are bypassed. Existing private videos are not silently republished. |
| 4. Uploaded versus public | Calendar, content listings and history distinguish the two. Daily analytics reconciles actual YouTube visibility. |
| 5. Missing scripts | Resume research and production on the same package instead of attempting to repair a nonexistent script. |
| 6. Evidence before publishing | Final script checks run before production publishing. Article and translation changes require independent meaning checks. |
| 7. Better sources | Relevant official feeds are tried before Wikipedia and general discovery. |
| 8. Shorter videos | A three-minute floor and five-fact minimum allow concise explainers without disabling evidence checks. |
| 9. Independent articles | A website article can be automatically checked and approved before a video is rendered or posted. Snapshots are stored separately. |
| 10. Launch article | The minimum-wage launch article is corrected to a focused raise/inflation explanation at its existing address. Video and script history are preserved. |
| 11. One clear article question | Article meaning review rejects a title/body mismatch. The corrected article answers one question. |
| 12. Useful resources | Local-only calculator, downloadable wage worksheet and free AI workflow checklist. |
| 13. Audience | AI channel focuses on freelancers and small businesses. Existing money channel stays intact. |
| 14. Connected guides | Beginner guide, document-summary tutorial, workflow comparison and troubleshooting guide link to one another. |
| 15. Google discovery | Verification tag and sitemap remain; sitemap dates are corrected. Actual Search Console verification, submission and URL Inspection need account access. |
| 16. Stable URLs | Article registry preserves the first URL across edits; known historical URLs redirect to it. |
| 17. Honest dates/accountability | Original publication and real editorial modification dates are separate. Automated checks are not described as a named human review. |
| 18. Reliable models | Routing includes output validation, recent failures, latency, configured context and token limits. |
| 19. Failing models | Three recent failures rest the model for ten minutes; independent fallbacks remain required. |
| 20. Useful answers | Structured-output acceptance is recorded separately from transport success. Factual acceptance remains a separate preflight check. |
| 21. Meaning checks | Independent checks cover attribution, units, dates, causal statements, qualifications and formulas. |
| 22. English first | Automatic German generation is off by default. |
| 23. Newsletter | Form and consent remain; checklist is available without signup. Owner has no test address available, so confirmation/unsubscribe delivery cannot be verified. |
| 24. One revenue path | Existing affiliate integration is the initial prepared path. No paid service/product claims or invented checkout were added. |
| 25. Affiliate offers | Remain inactive: owner has no approved affiliate links. |
| 26. Measurements | Cloudflare Web Analytics was confirmed registered and recording page loads. It does not support custom events. Optional HTTPS event collector receives only event type and path for affiliate clicks, downloads and newsletter submission attempts. No email/form values or identifiers. Confirmation/sales require provider integration and are not inferred from clicks. |
| 27. Ads/domain | No ads, domain purchase or paid upgrade. |
| 28. Mobile speed | Local throttled browser checks and overflow checks are run. Direct Pages requests are blocked by this execution environment. Cloudflare RUM was accessible: 26 desktop events showed LCP P75 1.372 s; three mobile events showed 6.988 s, driven by one sample with 5.270 s TTFB (the other two grouped at 1.096 s LCP). This tiny sample does not establish a persistent site bottleneck. Asset URLs are content-versioned so returning browsers receive updated code. |
| 29. Manual posting | A public link is required server-side and in the dashboard before completion. Link provision is owner attestation; API reconciliation is used where supported. |
| 30. Security/backups | RLS policy optimization and trigger privileges checked. Backup includes public/Auth/Storage metadata and studio objects, authenticated encryption and an integrity manifest. Disposable database restore is verified. Supabase leaked-password protection requires Pro; current organization is Free, so no upgrade is made. |

## Deployment

Push to `main` starts repository CI and the Website workflow. Engine workflow setup applies pending versioned database migrations before updated code runs. The Vercel dashboard continues using its existing Git integration. Worker code is unchanged.

Tests call mocked external platforms; they do not upload test videos to real social accounts. A source push is not proof that remote deployments or external account approvals succeeded; inspect workflow/deployment status afterward.

## Restore procedure

Retain `TOKEN_ENCRYPTION_KEY` separately from the encrypted artifact. Never put it in an artifact or Git. Download `studio-backup.enc`, decrypt it with `studio.backup.decrypt_file`, and extract the authenticated tar archive into a private directory. `database.dump` contains public, auth, storage and studio metadata; `manifest.json` maps numbered object files back to bucket/key with SHA-256 checksums.

Restore first into a disposable database with the expected Supabase roles/extensions and clean target schemas. Check table data, RLS grants, functions and object hashes. Restore each object to the manifest's bucket/key through the Storage API. Never run a destructive restore on production without a separately reviewed recovery plan. Managed platform settings, external accounts and GitHub secrets are excluded and must be recovered separately.

## External dependencies still needed

- Search Console account access for the supplied `https://pennyandpixel.pages.dev/` property, to verify ownership, submit the sitemap and inspect URLs. The property URL alone does not grant access.
- A controlled test email for real newsletter confirmation/unsubscribe verification.
- Approved affiliate URLs before activating offers.
- A conversion collector/provider for confirmed signup and sale reporting. Cloudflare Web Analytics is retained; no Google Analytics account or `G-` measurement ID exists.
- Live-site network access for production mobile measurements.
- A separately authorized Supabase paid upgrade if leaked-password protection is wanted.

## Verification before push

The full engine run exercised 344 tests: 337 passed initially, with seven failures investigated. All failing cases passed after the fixes and updated fixtures; the focused publishing/Shorts/analytics regression group passed 34 tests plus the corrected retry case. Website/regression checks passed 33 tests, and the final requested-change/receipt group passed 19. Dashboard type checking, 103 unit tests and production build passed; Worker type checking and 66 tests passed. Browser dashboard sweep/quality checks and the throttled local website calculator/layout check passed. A disposable PostgreSQL restore preserved data, permissions and RLS after authenticated encryption/decryption. External platform calls in tests are mocked; live newsletter delivery and actual social publishing are not claimed verified.


## Deployment database review

The production migration and RLS grants were verified after push. Health advisors report no findings. Security advisors still flag the existing intentional deny-all secret tables and authenticated SECURITY DEFINER owner RPCs; their owner checks must remain intact. Leaked-password protection remains disabled on Free. See [Supabase password protection](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection) and [owner RPC advisory](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable). Existing informational index notices are unchanged; a covering index is supplied for the new article snapshot foreign key.
