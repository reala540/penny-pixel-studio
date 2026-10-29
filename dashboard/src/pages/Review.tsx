import { useFormDraft } from "../lib/formDraft";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApprovalModeNotice } from "../components/AutoPostToggle";
import { Confirm, Empty, ErrorNote, HostTag, Loading, PageHeader, StatusBadge, useToast } from "../components/ui";
import { approveProject, must, queueJob, useTimezone } from "../lib/api";
import { useProjectHistory } from "../lib/content";
import { safeUrl, estSeconds, fmtDateTime, fmtDuration, HOST, KIND_NAME, PLATFORM_NAME } from "../lib/format";
import { MissingFileError, signedUrl, supabase } from "../lib/supabase";
import { ANIMATIONS, asStill, unsaidNumbers } from "../lib/animations";
import { caption, limitProblems, parseHashtags, parseTags, rule } from "../lib/limits";
import { BAD_CLAIMS, checkState, claimProblems, groupFindings, includedPosts, droppedShorts, ownerState, REASON_MIN, reasonNeeded, SHORTS_WAITING, visibleIssues } from "../lib/packageParts";
import { TriangleAlert } from "lucide-react";
import type { Claim, Project, ScriptBody, Variant } from "../lib/types";

function AutoChecks({ projectId }: { projectId: string }) {
  const rows = useQuery({
    queryKey: ["auto-reviews", projectId],
    queryFn: async () => (await must(supabase.from("auto_reviews").select("id, verdict, attempt, fix, reasons, reviewer, confidence, created_at")
      .eq("project_id", projectId).order("created_at", { ascending: false }).limit(10))) as any[],
  });
  if (!rows.data?.length) return null;
  const label: Record<string, string> = { approved: "Approved automatically", needs_review: "Sent to you", error: "Couldn't check: sent to you", skipped: "Skipped", fixing: "Fixing, will check again" };
  return (
    <section className="mt-6" aria-labelledby="auto-title">
      <h3 id="auto-title" className="text-sm font-semibold">Automatic review</h3>
      <ul className="mt-2 divide-y divide-line rounded-xl border border-line bg-surface text-sm">
        {rows.data.map((r) => (
          <li key={r.id} className="px-4 py-2.5">
            <p className="font-medium">{label[r.verdict] ?? r.verdict}{r.attempt ? ` · attempt ${r.attempt}` : ""}<span className="ml-2 text-xs font-normal text-muted">{new Date(r.created_at).toLocaleString()}</span></p>
            {r.fix && <p className="text-xs">🔧 {r.fix}</p>}
            {(r.reasons ?? []).slice(0, 3).map((x: string) => <p key={x} className="text-xs text-muted">• {x}</p>)}
          </li>
        ))}
      </ul>
    </section>
  );
}

function History({ projectId }: { projectId: string }) {
  const h = useProjectHistory(projectId);
  if (h.isLoading) return <Loading />;
  if (h.error) return <ErrorNote error={h.error} onRetry={() => h.refetch()} retrying={h.isFetching} />;
  if (!h.data?.length) return <p className="text-sm text-muted">Nothing has happened to this package yet.</p>;
  return (
    <ol className="divide-y divide-line rounded-xl border border-line bg-surface">
      {h.data.map((i, n) => (
        <li key={n} className="px-4 py-2.5 text-sm">
          <p className={i.tone === "bad" ? "font-medium text-alert" : i.tone === "good" ? "font-medium text-penny" : "font-medium"}>{i.title}
            {i.url && <a href={safeUrl(i.url)} target="_blank" rel="noreferrer" className="ml-2 text-xs text-pixel underline">Open the post</a>}</p>
          {i.detail && <p className="text-xs text-muted">{i.detail}</p>}
          <time className="text-xs text-muted" dateTime={i.at}>{new Date(i.at).toLocaleString()}</time>
        </li>
      ))}
    </ol>
  );
}

function usePreview(key?: string) {
  return useQuery({ queryKey: ["signed", key], enabled: Boolean(key), staleTime: 50 * 60_000, queryFn: () => signedUrl(key),
    retry: (n, e) => !(e instanceof MissingFileError) && n < 1 });
}

type Tab = "script" | "facts" | "thumbs" | "posts" | "shorts" | "history";
const TABS: Tab[] = ["script", "facts", "thumbs", "posts", "shorts", "history"];

/** One project's page: video, approval, and every part of the package (the old Review Studio detail, kept whole). */
export function Detail({ id }: { id: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const tz = useTimezone();
  const [params, setParams] = useSearchParams();
  const wanted = params.get("tab") as Tab | null;
  const tab: Tab = wanted && TABS.includes(wanted) ? wanted : "script";
  const setTab = (t: Tab) => { const p = new URLSearchParams(params); p.set("tab", t); setParams(p, { replace: true }); };
  const [confirm, setConfirm] = useState<null | "approve" | "reject" | "repair">(null);
  const [regen, setRegen] = useState(false);
  const [reason, setReason] = useState("");
  const data = useQuery({
    queryKey: ["project", id],
    queryFn: async () => {
      const project = (await must(supabase.from("content_projects").select("*").eq("id", id).single())) as Project;
      const [script, children, variants, claims, thumbs] = await Promise.all([
        project.current_script_version_id
          ? must(supabase.from("script_versions").select("id, version, origin, body").eq("id", project.current_script_version_id).single())
          : Promise.resolve(null),
        must(supabase.from("content_projects").select("*").eq("parent_project_id", id)),
        must(supabase.from("content_variants").select("*, social_accounts(label, platform), scheduled_posts(id, scheduled_at, status)").or(`project_id.eq.${id}`)),
        must(supabase.from("research_claims").select("*, research_sources(title, publisher, url)").eq("script_version_id", project.current_script_version_id ?? "00000000-0000-0000-0000-000000000000")),
        must(supabase.from("thumbnails").select("*").eq("project_id", id).order("variant_label")),
      ]);
      const childIds = (children as Project[]).map((c) => c.id);
      const childVariants = childIds.length
        ? ((await must(supabase.from("content_variants").select("*, social_accounts(label, platform), scheduled_posts(id, scheduled_at, status)").in("project_id", childIds))) as Variant[])
        : [];
      return { project, script: script as any, children: children as Project[], variants: [...(variants as Variant[]), ...childVariants], claims: claims as Claim[], thumbs: thumbs as any[] };
    },
  });
  const video = usePreview(data.data?.project.recipe?.preview_key);
  // only on the owner's click: a preview whose file was removed is rebuilt from the saved script (no new script)
  const rebuild = useMutation({
    mutationFn: () => queueJob("rerender_preview", { projectId: id }),
    onSuccess: (r) => toast(r.startsSoon ? "Rebuilding the preview: it appears here in a few minutes." : "Preview rebuild saved: it starts within about 15 minutes."),
    onError: (e) => toast((e as Error).message, "bad"),
  });

  const approve = useMutation({
    mutationFn: async () => approveProject(id, data.data?.project.current_script_version_id ?? null, reason.trim() || null),
    onSuccess: (n) => { qc.invalidateQueries(); setReason(""); toast(`Approved: ${n} post${n === 1 ? "" : "s"} scheduled`); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const repair = useMutation({
    mutationFn: () => queueJob("repair_package", { projectId: id }),
    onSuccess: (r) => toast(r.startsSoon ? "Rechecking and repairing: the new version appears here in a few minutes." : "Repair saved: it starts within about 15 minutes."),
    onError: (e) => toast(/unsupported owner job/i.test((e as Error).message)
      ? "Recheck and repair needs the latest database update. Run GitHub → Actions → First-time setup (keys only)." : (e as Error).message, "bad"),
  });
  const reject = useMutation({
    mutationFn: async () => {
      const { data: user } = await supabase.auth.getUser();
      const ids = [id, ...(data.data?.children ?? []).map((c) => c.id)];
      await must(supabase.from("approvals").insert(ids.map((pid) => ({ target_type: "project", target_id: pid, decision: "rejected", decided_by: user.user?.id }))));
      await must(supabase.from("content_variants").update({ status: "rejected" }).in("project_id", ids));
      await must(supabase.from("content_projects").update({ status: "rejected" }).in("id", ids));
    },
    onSuccess: () => { qc.invalidateQueries(); toast("Discarded. Its posts were cancelled and their slots freed."); },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  if (data.isLoading) return <Loading />;
  if (!data.data) return <ErrorNote error={data.error} onRetry={() => data.refetch()} retrying={data.isFetching} />;
  const { project, script, children, variants, claims, thumbs } = data.data;
  const issues = [...visibleIssues(project), ...variants.filter((v) => !["skipped", "rejected", "published"].includes(v.status)).flatMap((v) =>
    limitProblems(v.social_accounts?.platform ?? "", v.kind, { title: v.title ?? "", body: v.body ?? "", tags: v.tags ?? [], hashtags: v.hashtags ?? [] })
      .map((p) => `${v.social_accounts?.label ?? "Post"} ${(KIND_NAME[v.kind] ?? v.kind).toLowerCase()}: ${p}`))];
  const counts = claimProblems(claims);
  const bad = claims.filter((c) => BAD_CLAIMS.includes(c.status));
  const found = groupFindings(project.quality_report?.findings);
  const decided = ["approved", "rejected", "scheduled", "published"].includes(project.status);
  const parts = [project, ...children];
  const checks = checkState(parts, bad.length, issues.length);
  const owner = ownerState(project.status);
  const needReason = reasonNeeded(parts, bad.length);
  const reasonOk = !needReason || reason.trim().length >= REASON_MIN;

  return (
    <article aria-labelledby="detail-title" className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <HostTag channel={project.channel_slug} />
          <h2 id="detail-title" className="mt-1 font-display text-2xl font-bold leading-tight">{project.title}</h2>
          <p className="mt-1 text-sm text-muted">
            {HOST[project.channel_slug].channel} · {fmtDuration(project.recipe?.preview_seconds)} preview
            {project.fresh_until && <> · facts fresh until {fmtDateTime(project.fresh_until, tz)}</>}
          </p>
          {project.format === "long" && (
            <p className="mt-1 text-sm" aria-label="What this package contains">
              <button type="button" className="underline-offset-2 hover:underline" onClick={() => setTab("script")}>Main video · {fmtDuration(project.recipe?.preview_seconds)}</button>
              {" · "}<button type="button" className={`underline-offset-2 hover:underline ${children.length ? "" : "font-medium text-alert"}`} onClick={() => setTab("shorts")}>Short videos · {children.length}</button>
              {" · "}<button type="button" className="underline-offset-2 hover:underline" onClick={() => setTab("posts")}>Platform posts · {variants.length}</button>
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-1" aria-label="Checks and approval">
          <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${checks === "passed" ? "bg-penny-soft text-penny" : "bg-alert-soft text-alert"}`}>
            {checks === "passed" ? "Passed checks" : "Needs corrections"}</span>
          <span className="inline-flex items-center rounded-md bg-sunken px-2 py-0.5 text-xs font-medium text-ink">
            {owner === "approved" ? "Approved by you" : owner === "published" ? "Approved and posted" : owner === "rejected" ? "Discarded" : "Waiting for your approval"}</span>
          <StatusBadge status={project.status} />
        </div>
      </div>

      <div className="mt-5 grid gap-6 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="overflow-hidden rounded-xl bg-ink">
          {video.data ? (
            <><video key={video.data} src={video.data} controls preload="metadata" className={`mx-auto ${project.format === "short" ? "aspect-[9/16] h-[480px] max-w-full" : "aspect-video w-full"}`} /><button className="btn-quiet mt-2" onClick={() => video.refetch()} disabled={video.isFetching}>Refresh preview link</button></>
          ) : (
            <div className="grid aspect-video place-items-center px-4 text-center text-sm text-surface/80">
              {video.isLoading ? "Loading preview…"
                : video.error instanceof MissingFileError ? (
                  <span>The preview file is no longer stored.{" "}
                    {!decided && <button className="underline" disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>{rebuild.isPending ? "Asking…" : "Rebuild the preview"}</button>}</span>)
                : video.isError ? <span>Couldn't load the preview: {(video.error as Error).message} <button className="underline" onClick={() => video.refetch()}>Retry</button></span>
                : project.recipe?.preview_key ? "Loading preview…" : "No preview yet"}
            </div>
          )}
        </div>
        <aside className="space-y-4" aria-label="Approval">
          {!decided && <ApprovalModeNotice />}
          {issues.length > 0 || bad.length > 0 ? (
            <div className="rounded-xl border border-alert/40 bg-alert-soft p-4 text-sm">
              <p className="font-medium text-alert">{decided ? "Approved with these warnings" : "Check before approving"}</p>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-ink">
                {bad.map((c) => <li key={c.id}>{CLAIM_PROBLEM[c.status] ?? "Claim not backed by a source"}: “{c.claim_text.slice(0, 90)}”</li>)}
                {issues.map((i) => <li key={i}>{i}</li>)}
              </ul>
              {project.quality_report?.findings && <p className="mt-2 text-xs text-muted">Facts listed here must be fixed before posting; the rest are an editor's notes.</p>}
            </div>
          ) : (
            <div className="rounded-xl border border-penny/30 bg-penny-soft p-4 text-sm text-penny">
              Passed every automatic check: structure, sources, wording and length.
            </div>
          )}
          {found.missing.length > 0 && (
            <div className="rounded-xl border border-gold/50 bg-gold/10 p-4 text-sm">
              <p className="font-medium">Missing parts</p>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-ink">{found.missing.map((f) => <li key={f.text}>{f.text}</li>)}</ul>
            </div>
          )}
          {found.info.length > 0 && (
            <details className="rounded-xl border border-line bg-surface p-4 text-sm">
              <summary className="cursor-pointer font-medium">What the studio changed or noticed ({found.info.length})</summary>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-muted">{found.info.map((f, i) => <li key={i}>{f.text}</li>)}</ul>
            </details>
          )}
          {project.quality_report?.critic && (
            <div className="rounded-xl border border-line bg-surface p-4">
              <p className="text-sm font-medium">Editor scores (out of 10)</p>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm tabular">
                {["hook", "originality", "clarity", "pacing", "value"].map((k) => (
                  <div key={k} className="flex justify-between"><dt className="capitalize text-muted">{k}</dt><dd className="font-medium">{project.quality_report.critic?.[k]}</dd></div>
                ))}
              </dl>
            </div>
          )}
          {!decided && (
            <div className="flex flex-col gap-2">
              <button className="btn-primary" onClick={() => setConfirm("approve")} disabled={approve.isPending}>Approve package</button>
              {project.format === "long" && ["needs_attention", "ready_for_review", "failed"].includes(project.status) && (
                <button className="btn-quiet" onClick={() => setConfirm("repair")} disabled={repair.isPending}>{repair.isPending ? "Asking…" : "Recheck and repair"}</button>
              )}
              <button className="btn-quiet" onClick={() => setRegen(true)}>Rewrite with a note</button>
              <button className="btn-danger" onClick={() => setConfirm("reject")}>Discard package</button>
            </div>
          )}
        </aside>
      </div>

      <Confirm open={confirm === "approve"} title="Approve this package?"
        body={<>
          <p>The main video, {children.length === 0 ? <strong>no short videos</strong> : <>{children.length} short video{children.length === 1 ? "" : "s"}</>} and {variants.length} platform post{variants.length === 1 ? "" : "s"} go out at their scheduled times. You can still cancel single posts in Calendar.</p>
          <p className="mt-2 font-medium text-ink">Included</p>
          <ul className="list-disc pl-4 text-ink">
            {includedPosts(variants, KIND_NAME).map((x) => <li key={x}>{x}</li>)}
            {includedPosts(variants, KIND_NAME).length === 0 && <li>No platform posts: nothing would be scheduled.</li>}
          </ul>
          {project.format === "long" && children.length === 0 && (
            <p className="mt-2 text-alert">Missing: short videos, so no Shorts, Reels, Stories or TikTok videos come from this package. Use "Make Shorts again" in Short videos first if you want them.</p>
          )}
          {(bad.length > 0 || issues.length > 0) && (
            <div className="mt-3 rounded-lg bg-alert-soft p-3 text-ink">
              <p className="font-medium text-alert">You're approving with {bad.length + issues.length} warning{bad.length + issues.length === 1 ? "" : "s"}:</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {counts.contradicted > 0 && <li>{counts.contradicted} claim{counts.contradicted === 1 ? " is" : "s are"} contradicted by the sources</li>}
                {counts.unsupported > 0 && <li>{counts.unsupported} claim{counts.unsupported === 1 ? " has" : "s have"} no source behind {counts.unsupported === 1 ? "it" : "them"}</li>}
                {counts.stale > 0 && <li>{counts.stale} old figure{counts.stale === 1 ? " is" : "s are"} said as if current</li>}
                {issues.slice(0, 6).map((i) => <li key={i}>{i}</li>)}
              </ul>
            </div>
          )}
          <p className="mt-3 text-ink">Approving means <strong>you</strong> decided it can go out. It doesn't mean every check passed{checks === "passed" ? " (here they did)" : ": here some didn't"}.</p>
          {needReason && (
            <label className="mt-3 block text-ink">
              <span className="font-medium">Why are you approving anyway? (required, kept permanently with the approval)</span>
              <textarea className="field mt-1" rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="For example: I checked the figure on the official site myself." />
              {!reasonOk && <span className="mt-1 block text-xs text-muted">At least {REASON_MIN} characters.</span>}
            </label>
          )}
        </>}
        confirmDisabled={!reasonOk}
        confirmLabel={bad.length + issues.length > 0 ? "Approve anyway" : "Approve package"}
        onCancel={() => { setConfirm(null); setReason(""); }} onConfirm={() => { setConfirm(null); approve.mutate(); }} />
      <Confirm open={confirm === "repair"} title="Recheck and repair this package?"
        body="The studio checks every statement against its evidence again, fixes what it can (sums, dates, repeated parts, failing scenes) and saves a new version. The current version is kept in History. It uses the free AI services for a few minutes. Nothing is approved, scheduled or posted."
        confirmLabel="Recheck and repair" onCancel={() => setConfirm(null)} onConfirm={() => { setConfirm(null); repair.mutate(); }} />
      <Confirm open={confirm === "reject"} title="Discard this package?" danger
        body="The video, its Shorts and all their posts are rejected and their slots freed. It stays in Content → Not used."
        confirmLabel="Discard package" onCancel={() => setConfirm(null)} onConfirm={() => { setConfirm(null); reject.mutate(); }} />
      {regen && <RegenerateDialog project={project} onClose={() => setRegen(false)} />}

      <div role="tablist" aria-label="Package parts" className="mt-8 flex gap-1 overflow-x-auto border-b border-line">
        {([["script", "Script"], ["facts", `Sources & checks (${claims.length})`], ["thumbs", "Thumbnails"], ["shorts", `Short videos (${children.length})`], ["posts", `Platform posts (${variants.length})`], ["history", "History"]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${tab === k ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink"}`}>{label}</button>
        ))}
      </div>
      <div className="pt-5">
        {tab === "script" && script && <ScriptEditor project={project} version={script} />}
        {tab === "facts" && <><Facts claims={claims} /><AutoChecks projectId={id} /></>}
        {tab === "thumbs" && <Thumbs thumbs={thumbs} projectId={id} />}
        {tab === "posts" && <><SearchBriefCard brief={project.recipe?.package?.search_brief} /><Posts variants={variants} tz={tz} mainId={project.id} /></>}
        {tab === "shorts" && <Shorts head={project} shorts={children} />}
        {tab === "history" && <History projectId={id} />}
      </div>
    </article>
  );
}

function AnimatedScene({ project, index, scene, dirty, versionId, onChange }: {
  project: Project; index: number; scene: ScriptBody["scenes"][number]; dirty: boolean; versionId: string;
  onChange: (v: ScriptBody["scenes"][number]["visual"]) => void;
}) {
  const toast = useToast();
  const v = scene.visual;
  const preview = project.recipe?.scene_previews?.[String(index)];
  const current = preview && preview.version === versionId ? preview : undefined;
  const url = usePreview(current?.key);
  const ask = useMutation({
    mutationFn: () => queueJob("preview_scene", { projectId: project.id, input: { scene: index } }),
    onSuccess: (r) => toast(r.startsSoon ? "Rendering this scene: it appears here in a minute or two." : "Scene preview requested: it starts within about 15 minutes."),
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const unsaid = unsaidNumbers(scene);
  const help = ANIMATIONS.find((a) => a.id === v.animation)?.help;
  return (
    <div className="mt-3 rounded-lg border border-line bg-sunken p-3 text-sm">
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-[14rem] flex-1">
          <span className="text-muted">Animation</span>
          <select className="field mt-1" value={v.animation ?? ""} disabled={project.status === "published"}
            onChange={(e) => onChange(e.target.value === "still" ? asStill(v) : { ...v, animation: e.target.value })}>
            {ANIMATIONS.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
            <option value="still">No animation (still picture)</option>
          </select>
        </label>
        <button type="button" className="btn-quiet" disabled={dirty || ask.isPending} onClick={() => ask.mutate()}
          title={dirty ? "Save your changes first, then preview" : undefined}>{ask.isPending ? "Asking…" : "Preview this scene"}</button>
      </div>
      {v.animation === "counter" ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <label><span className="text-muted">Number</span>
            <input className="field mt-1" value={v.stat_value ?? ""} onChange={(e) => onChange({ ...v, stat_value: e.target.value })} /></label>
          <label><span className="text-muted">Label</span>
            <input className="field mt-1" value={v.stat_label ?? ""} onChange={(e) => onChange({ ...v, stat_label: e.target.value })} /></label>
        </div>
      ) : (
        <label className="mt-2 block"><span className="text-muted">{help}</span>
          <textarea className="field mt-1 font-mono text-xs" rows={Math.max(2, (v.items ?? []).length)} value={(v.items ?? []).join("\n")}
            onChange={(e) => onChange({ ...v, items: e.target.value.split("\n") })} /></label>
      )}
      {unsaid.length > 0 && <p className="mt-2 text-alert">This animation shows {unsaid.join(", ")}, which the narration doesn't say. Every number shown must be said (and checked).</p>}
      {dirty && <p className="mt-2 text-xs text-muted">Save your changes to preview them. Only changed scenes are drawn again.</p>}
      {current && (url.data
        ? <video src={url.data} controls preload="metadata" className={`mt-3 w-full rounded-lg bg-ink ${project.format === "short" ? "aspect-[9/16] max-w-xs" : "aspect-video"}`} />
        : <p className="mt-2 text-xs text-muted">Loading the scene preview…</p>)}
      {preview && !current && <p className="mt-2 text-xs text-muted">The last scene preview was for an earlier version of the script.</p>}
    </div>
  );
}

function ScriptEditor({ project, version }: { project: Project; version: { id: string; version: number; origin: string; body: ScriptBody } }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [body, setBody, draft] = useFormDraft<ScriptBody>(`script:${project.id}`, version.body);
  const dirty = JSON.stringify(body) !== JSON.stringify(version.body);
  const total = estSeconds(body.hook) + body.scenes.reduce((a, s) => a + estSeconds(s.narration), 0) + estSeconds(body.cta ?? "");
  const save = useMutation({
    mutationFn: async () => {
      const latest = (await must(supabase.from("script_versions").select("version").eq("project_id", project.id).order("version", { ascending: false }).limit(1))) as { version: number }[];
      const words = body.scenes.reduce((a, s) => a + s.narration.split(/\s+/).length, 0);
      const created = (await must(supabase.from("script_versions").insert({ project_id: project.id, version: (latest[0]?.version ?? 0) + 1, origin: "owner_edit", hook: body.hook, body, word_count: words }).select("id").single())) as { id: string };
      await must(supabase.from("content_projects").update({ current_script_version_id: created.id, status: "rendering" }).eq("id", project.id).eq("current_script_version_id", version.id).select("id").single());
      await queueJob("rerender_preview", { projectId: project.id });
    },
    onSuccess: () => { qc.invalidateQueries(); toast("Saved as a new version. The preview is being re-rendered."); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <div className="space-y-4">
      {draft.message && <p role="status" className="text-sm text-muted">{draft.message} <button className="underline" onClick={draft.reset}>Discard edits</button></p>}
      <p className="text-sm text-muted">
        Version {version.version}{version.origin === "owner_edit" ? " (your edit)" : ""} · about {fmtDuration(total)} of narration. Edits save as a new version; earlier versions are kept.
      </p>
      {project.status === "published" && <p role="note" className="rounded-lg bg-sunken px-3 py-2 text-sm">This package is published, so its script can't be changed. Earlier versions are kept in History.</p>}
      {["approved", "scheduled"].includes(project.status) && <p role="note" className="rounded-lg bg-gold/15 px-3 py-2 text-sm text-ink">This package is approved. Saving an edit withdraws that approval: its posts wait for your approval again after the new version is checked and re-rendered.</p>}
      <label className="block">
        <span className="text-sm font-medium">Opening hook</span>
        <textarea className="field mt-1" rows={2} value={body.hook} onChange={(e) => setBody({ ...body, hook: e.target.value })} />
      </label>
      <ol className="space-y-3">
        {body.scenes.map((s, i) => (
          <li key={i} className="rounded-xl border border-line bg-surface p-3">
            <div className="mb-1.5 flex items-center justify-between text-xs text-muted">
              <span>Scene {i + 1} · {s.visual.type.replace(/_/g, " ")}{s.visual.headline ? `: ${s.visual.headline}` : ""}</span>
              <span className="tabular">{fmtDuration(estSeconds(s.narration))}</span>
            </div>
            <label className="sr-only" htmlFor={`scene-${i}`}>Narration for scene {i + 1}</label>
            <textarea id={`scene-${i}`} className="field" rows={3} value={s.narration}
              onChange={(e) => setBody({ ...body, scenes: body.scenes.map((x, j) => (j === i ? { ...x, narration: e.target.value } : x)) })} />
            {project.recipe?.render?.scenes?.[i + 1]?.visual?.fallback_reason && (  // the video's scene 0 is the opening hook
              <p role="note" className="mt-2 flex items-start gap-1.5 rounded-lg bg-gold/15 px-2.5 py-1.5 text-xs text-ink">
                <TriangleAlert size={13} className="mt-0.5 shrink-0 text-gold" aria-hidden />
                {project.recipe.render.scenes[i + 1].visual!.fallback_reason}
              </p>
            )}
            {s.visual.type === "animated" && (
              <AnimatedScene project={project} index={i} scene={s} dirty={dirty} versionId={version.id}
                onChange={(visual) => setBody({ ...body, scenes: body.scenes.map((x, j) => (j === i ? { ...x, visual } : x)) })} />
            )}
          </li>
        ))}
      </ol>
      {body.cta !== undefined && (
        <label className="block">
          <span className="text-sm font-medium">Ending</span>
          <textarea className="field mt-1" rows={2} value={body.cta} onChange={(e) => setBody({ ...body, cta: e.target.value })} />
        </label>
      )}
      <div className="sticky bottom-16 -mx-1 flex gap-2 rounded-xl bg-bg/95 px-1 py-2 backdrop-blur md:bottom-0">
        <button className="btn-primary" disabled={!dirty || save.isPending || draft.conflict || project.status === "published"} onClick={() => save.mutate()}>{["approved", "scheduled"].includes(project.status) ? "Save, withdraw approval and re-render" : "Save and re-render"}</button>
        {dirty && <button className="btn-quiet" onClick={() => setBody(version.body)}>Undo changes</button>}
      </div>
    </div>
  );
}

const CLAIM_PROBLEM: Record<string, string> = { stale: "Old figure said as current", contradicted: "Contradicted by its source", unsupported: "Not backed by a source" };
const CLAIM_LABEL: Record<string, string> = { general: "general principle (no specific figure)", stale: "old figure said as current: say when it applied", partially_supported: "partly supported" };

function Facts({ claims }: { claims: Claim[] }) {
  if (!claims.length) return <p className="text-sm text-muted">No factual claims in this script.</p>;
  return (
    <ul className="space-y-3">
      {claims.map((c) => (
        <li key={c.id} className="rounded-xl border border-line bg-surface p-4">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm">{c.claim_text}</p>
            <StatusBadge status={c.status === "supported" ? "approved" : ["opinion", "general"].includes(c.status) ? "proposed" : ["partially_supported", "stale"].includes(c.status) ? "needs_attention" : "failed"} />
          </div>
          <p className="mt-2 text-xs text-muted">
            {CLAIM_LABEL[c.status] ?? c.status.replace(/_/g, " ")}{c.data_period ? ` · data period ${c.data_period}` : ""}
            {c.checker_notes ? ` · ${c.checker_notes}` : ""}
          </p>
          {c.research_sources && (
            <a href={safeUrl(c.research_sources.url)} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs font-medium text-pixel underline-offset-2 hover:underline">
              {c.research_sources.publisher ?? "Source"}: {c.research_sources.title}
            </a>
          )}
        </li>
      ))}
    </ul>
  );
}

function Thumbs({ thumbs, projectId }: { thumbs: any[]; projectId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [headlines, setHeadlines] = useState(thumbs.map((t) => t.headline).join("\n"));
  const urls = useQuery({
    queryKey: ["thumb-urls", thumbs.map((t) => t.id).join()],
    queryFn: async () => Promise.all(thumbs.map(async (t) => ({ id: t.id, full: await signedUrl(t.options?.key), mobile: await signedUrl(t.options?.mobile_key) }))),
  });
  const pick = useMutation({
    mutationFn: async (tid: string) => {
      await must(supabase.from("thumbnails").update({ selected: false }).eq("project_id", projectId));
      await must(supabase.from("thumbnails").update({ selected: true }).eq("id", tid));
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["project", projectId] }); toast("Thumbnail chosen"); },
  });
  const redo = useMutation({
    mutationFn: () => queueJob("regenerate_thumbnails", { projectId, input: { headlines: headlines.split("\n").map((h) => h.trim()).filter(Boolean).slice(0, 3) } }),
    onSuccess: () => toast("New thumbnails requested"),
  });
  if (!thumbs.length) return <p className="text-sm text-muted">Shorts use the first frame as their cover.</p>;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        {thumbs.map((t) => {
          const u = urls.data?.find((x) => x.id === t.id);
          return (
            <figure key={t.id} className={`rounded-xl border p-2 ${t.selected ? "border-ink ring-2 ring-ink" : "border-line"} bg-surface`}>
              {u?.full ? <img src={u.full} alt={`Thumbnail option: ${t.headline}`} className="aspect-video w-full rounded-lg object-cover" /> : <div className="aspect-video rounded-lg bg-sunken" />}
              <figcaption className="mt-2 flex items-center justify-between gap-2 text-sm">
                <span className="flex items-center gap-2">
                  {u?.mobile && <img src={u.mobile} alt="" width={84} height={47} className="rounded" title="Phone feed size" />}
                  <span className="text-xs text-muted">Phone size</span>
                </span>
                <button className={t.selected ? "btn-primary px-2.5 py-1" : "btn-quiet px-2.5 py-1"} onClick={() => pick.mutate(t.id)} disabled={pick.isPending} aria-pressed={t.selected}>
                  {t.selected ? "Chosen" : "Choose"}
                </button>
              </figcaption>
            </figure>
          );
        })}
      </div>
      <div className="max-w-md">
        <label className="text-sm font-medium" htmlFor="thumb-text">Thumbnail words (one option per line)</label>
        <textarea id="thumb-text" className="field mt-1" rows={3} value={headlines} onChange={(e) => setHeadlines(e.target.value)} />
        <button className="btn-quiet mt-2" onClick={() => redo.mutate()} disabled={redo.isPending}>Make new thumbnails</button>
      </div>
    </div>
  );
}

function SearchBriefCard({ brief }: { brief?: { audience?: string; question?: string; primary_phrase?: string; supporting_phrases?: string[] } }) {
  if (!brief?.primary_phrase) return null;
  return (
    <section aria-label="Search brief" className="mb-5 rounded-xl border border-line bg-surface p-4 text-sm">
      <p className="font-medium">Search brief <span className="font-normal text-muted">· written from the topic and facts; search volumes aren't measured</span></p>
      <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-[10rem_1fr]">
        {brief.audience && <><dt className="text-muted">Who it's for</dt><dd>{brief.audience}</dd></>}
        {brief.question && <><dt className="text-muted">What they'd search</dt><dd>“{brief.question}”</dd></>}
        <dt className="text-muted">Main phrase</dt><dd className="font-medium">{brief.primary_phrase}</dd>
        {!!brief.supporting_phrases?.length && <><dt className="text-muted">Related phrases</dt><dd>{brief.supporting_phrases.join(" · ")}</dd></>}
      </dl>
      <p className="mt-2 text-xs text-muted">Edit the titles, captions, tags and hashtags below to change what each platform shows.</p>
    </section>
  );
}

function Posts({ variants, tz, mainId }: { variants: Variant[]; tz: string; mainId: string }) {
  const groups = [
    { title: "From the main video", items: variants.filter((v) => v.project_id === mainId) },
    { title: "From the short videos", items: variants.filter((v) => v.project_id !== mainId) },
  ].filter((g) => g.items.length);
  if (!groups.length) return <p className="text-sm text-muted">No platform posts for this package yet.</p>;
  return (
    <div className="space-y-6">
      {groups.map((g) => (
        <section key={g.title} aria-label={g.title}>
          <h3 className="mb-2 text-sm font-semibold">{g.title} · {g.items.length}</h3>
          <ul className="space-y-4">
            {g.items.map((v) => <PostEditor key={v.id} v={v} tz={tz} />)}
          </ul>
        </section>
      ))}
    </div>
  );
}

function PostEditor({ v, tz }: { v: Variant; tz: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm, draft] = useFormDraft(`post:${v.id}`, { title: v.title ?? "", body: v.body ?? "",
    tags: (v.tags ?? []).join(", "), hashtags: (v.hashtags ?? []).map((h) => `#${h.replace(/^#/, "")}`).join(" ") });
  const { title, body } = form;
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }));
  const platform = v.social_accounts?.platform ?? "x";
  const r = rule(platform, v.kind);
  const tags = parseTags(form.tags ?? ""), hashtags = parseHashtags(form.hashtags ?? "");
  const problems = limitProblems(platform, v.kind, { title, body, tags, hashtags });
  const showTags = r.tagsTotal !== undefined;
  const showHashtags = r.hashtags !== undefined;
  const textLimit = r.body ?? r.caption;
  const post = v.scheduled_posts?.[0];
  const save = useMutation({
    mutationFn: async () => {
      if (draft.conflict) throw new Error("This post changed elsewhere. Reload the current version before saving.");
      let update = supabase.from("content_variants").update({ title: title || null, body, tags, hashtags }).eq("id", v.id);
      update = v.body == null ? update.is("body", null) : update.eq("body", v.body);
      update = v.title == null ? update.is("title", null) : update.eq("title", v.title);
      return must(update.select("id").single());
    },
    onSuccess: () => { qc.invalidateQueries(); toast("Post saved"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const skip = useMutation({
    mutationFn: async () => {
      const { data: user } = await supabase.auth.getUser();
      await must(supabase.from("approvals").insert({ target_type: "variant", target_id: v.id, decision: "skipped", decided_by: user.user?.id }));
      await must(supabase.from("content_variants").update({ status: "skipped" }).eq("id", v.id));
    },
    onSuccess: () => { qc.invalidateQueries(); toast("Skipped. This post won't go out."); },
  });
  const dirty = title !== (v.title ?? "") || body !== (v.body ?? "") || tags.join("|") !== (v.tags ?? []).join("|")
    || hashtags.join("|") !== (v.hashtags ?? []).map((h) => h.replace(/^#/, "")).join("|");
  const locked = v.status === "published";
  return (
    <li className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">{v.social_accounts?.label} · {KIND_NAME[v.kind] ?? v.kind}</p>
        <span className="flex items-center gap-2 text-xs text-muted">
          {post && <span className="tabular">{fmtDateTime(post.scheduled_at, tz)}</span>}
          <StatusBadge status={v.status} />
        </span>
      </div>
      {v.kind === "story" ? (
        <p className="mt-3 text-sm text-muted">A Story shows the short video only, with no caption.</p>
      ) : <>
        {v.kind !== "text_post" && (
          <label className="mt-3 block text-sm">
            <span className="text-muted">Title</span>
            <input className="field mt-1" value={title} disabled={locked} onChange={(e) => set({ title: e.target.value })} maxLength={r.title ?? 100} />
          </label>
        )}
        <label className="mt-3 block text-sm">
          <span className="text-muted">{v.kind === "long_video" ? "Description" : platform === "x" ? `Post for ${PLATFORM_NAME[platform]}` : "Caption"}</span>
          <textarea className="field mt-1" rows={v.kind === "long_video" ? 6 : 3} value={body} disabled={locked} onChange={(e) => set({ body: e.target.value })} />
          {textLimit && <span className={`mt-1 block text-right text-xs tabular ${(r.caption ? caption(body, hashtags).length : body.length) > textLimit ? "text-alert" : "text-muted"}`}>
            {r.caption ? caption(body, hashtags).length : body.length} / {textLimit}{r.caption ? " with hashtags" : ""}</span>}
        </label>
        {showTags && (
          <label className="mt-3 block text-sm">
            <span className="text-muted">Search tags (separate with commas)</span>
            <input className="field mt-1" value={form.tags ?? ""} disabled={locked} onChange={(e) => set({ tags: e.target.value })} />
          </label>
        )}
        {showHashtags && (
          <label className="mt-3 block text-sm">
            <span className="text-muted">Hashtags (up to {r.hashtags}){platform === "youtube" ? " · in the description text above for YouTube" : ""}</span>
            <input className="field mt-1" value={form.hashtags ?? ""} disabled={locked} onChange={(e) => set({ hashtags: e.target.value })} />
          </label>
        )}
        {problems.length > 0 && (
          <ul className="mt-2 list-disc pl-5 text-sm text-alert" aria-label="Platform limits">
            {problems.map((p) => <li key={p}>{p}</li>)}
          </ul>
        )}
      </>}
      {draft.message && <p role="status" className="mt-2 text-sm text-muted">{draft.message} <button className="underline" onClick={draft.reset}>Discard edits</button></p>}
      <div className="mt-2 flex gap-2">
        {v.kind !== "story" && !locked && <button className="btn-quiet" disabled={!dirty || problems.length > 0 || save.isPending || draft.conflict} onClick={() => save.mutate()}>Save post</button>}
        {!["skipped", "rejected", "published"].includes(v.status) && <button className="btn-quiet" onClick={() => {if(window.confirm("Skip this post? This account will not receive it; the rest of the package is unchanged."))skip.mutate();}} disabled={skip.isPending}>Skip this post</button>}
      </div>
    </li>
  );
}

function Shorts({ head, shorts }: { head: Project; shorts: Project[] }) {
  const toast = useToast();
  const dropped = droppedShorts(head.quality_report);
  const decided = ["approved", "scheduled", "published"].includes(head.status);
  const canRemake = head.format === "long" && !["rejected", "archived", "failed"].includes(head.status);
  const remake = useMutation({
    mutationFn: () => queueJob("remake_shorts", { projectId: head.id }),
    onSuccess: (r) => toast(r.startsSoon ? "Making new Shorts: they appear here for your approval in a few minutes." : "New Shorts requested: they start within about 15 minutes."),
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">Short videos are made from the main video's checked facts. Facebook Reels and Stories, YouTube Shorts and TikTok videos all come from them.</p>
      {shorts.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {shorts.map((s) => <ShortCard key={s.id} s={s} approvable={decided && SHORTS_WAITING.includes(s.status)} />)}
        </div>
      )}
      {dropped.length > 0 && (
        <div className="rounded-xl border border-alert/40 bg-alert-soft p-4 text-sm">
          <p className="font-medium text-alert">{shorts.length ? "Some Shorts were dropped by the quality checks" : "No short videos: the quality checks dropped them"}</p>
          <ul className="mt-2 space-y-1 text-ink">
            {dropped.map((d, i) => <li key={`${d.title}-${i}`}><span className="font-medium">“{d.title}”</span>: {d.reasons.join("; ")}</li>)}
          </ul>
          {!shorts.length && <p className="mt-2 text-ink">Without short videos this package gets no Reel, Story, YouTube Short or TikTok post.</p>}
        </div>
      )}
      {!shorts.length && !dropped.length && <p className="text-sm text-muted">No Shorts for this package.</p>}
      {canRemake && (
        <div className="rounded-xl border border-line bg-surface p-4 text-sm">
          <p className="font-medium">Make Shorts again</p>
          <p className="mt-1 text-muted">Writes new Shorts from this video's checked facts only. The script, main video and existing posts stay as they are, and nothing already posted is posted again. New Shorts wait here for your approval{decided ? "" : " together with the package"}.</p>
          <button type="button" className="btn-quiet mt-3" disabled={remake.isPending} onClick={() => remake.mutate()}>{remake.isPending ? "Asking…" : "Make Shorts again"}</button>
        </div>
      )}
    </div>
  );
}

function ShortCard({ s, approvable }: { s: Project; approvable?: boolean }) {
  const url = usePreview(s.recipe?.preview_key);
  const qc = useQueryClient();
  const toast = useToast();
  const approve = useMutation({
    mutationFn: () => approveProject(s.id, s.current_script_version_id ?? null),
    onSuccess: (n) => { qc.invalidateQueries(); toast(`Short approved: ${n} post${n === 1 ? "" : "s"} scheduled`); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <figure className="rounded-xl border border-line bg-surface p-2">
      {url.data ? <video src={url.data} controls preload="metadata" className="aspect-[9/16] w-full rounded-lg bg-ink object-cover" /> : <div className="aspect-[9/16] rounded-lg bg-sunken" />}
      <figcaption className="mt-2 flex items-start justify-between gap-2 px-1 text-sm">
        <span className="font-medium leading-snug">{s.title}</span>
        <StatusBadge status={s.status} />
      </figcaption>
      {approvable && <button type="button" className="btn-primary mt-2 w-full" disabled={approve.isPending} onClick={() => approve.mutate()}>Approve this Short</button>}
    </figure>
  );
}

function RegenerateDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const go = useMutation({
    mutationFn: () => queueJob(project.format === "long" ? "regenerate_script" : "rerender_preview", { projectId: project.format === "long" ? project.id : project.parent_project_id ?? project.id, input: { instructions: note } }),
    onSuccess: () => { toast("Rewrite requested. You'll get a Telegram message when it's ready."); onClose(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-ink/40 p-4 sm:items-center" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="regen-title" className="w-full max-w-lg rounded-xl bg-surface p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 id="regen-title" className="font-display text-lg font-semibold">Rewrite this script</h2>
        <p className="mt-1 text-sm text-muted">Tell the writers what to change. The facts are re-checked and a new preview is made.</p>
        <textarea className="field mt-3" rows={4} autoFocus placeholder="For example: make the opening more personal and cut the history part" value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="mt-4 flex justify-end gap-2">
          <button className="btn-quiet" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!note.trim() || go.isPending} onClick={() => go.mutate()}>Rewrite script</button>
        </div>
      </div>
    </div>
  );
}
