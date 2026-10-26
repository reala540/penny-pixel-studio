import { useFormDraft } from "../lib/formDraft";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApprovalModeNotice } from "../components/AutoPostToggle";
import { Confirm, Empty, ErrorNote, HostTag, Loading, PageHeader, StatusBadge, useToast } from "../components/ui";
import { must, queueJob, useTimezone } from "../lib/api";
import { useProjectHistory } from "../lib/content";
import { safeUrl, estSeconds, fmtDateTime, fmtDuration, HOST, KIND_NAME, PLATFORM_NAME } from "../lib/format";
import { signedUrl, supabase } from "../lib/supabase";
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
  return useQuery({ queryKey: ["signed", key], enabled: Boolean(key), staleTime: 50 * 60_000, queryFn: () => signedUrl(key) });
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
  const [confirm, setConfirm] = useState<null | "approve" | "reject">(null);
  const [regen, setRegen] = useState(false);
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

  const approve = useMutation({
    mutationFn: async () => must(supabase.rpc("approve_project", { p_project_id: id, p_notes: null })),
    onSuccess: (n) => { qc.invalidateQueries(); toast(`Approved: ${n} post${n === 1 ? "" : "s"} scheduled`); },
    onError: (e) => toast((e as Error).message, "bad"),
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
  const issues = [...(project.quality_report?.issues ?? []), ...(project.quality_report?.package_problems ?? [])];
  const bad = claims.filter((c) => ["unsupported", "contradicted"].includes(c.status));
  const decided = ["approved", "rejected", "scheduled", "published"].includes(project.status);

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
        </div>
        <StatusBadge status={project.status} />
      </div>

      <div className="mt-5 grid gap-6 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="overflow-hidden rounded-xl bg-ink">
          {video.data ? (
            <><video key={video.data} src={video.data} controls preload="metadata" className={`mx-auto ${project.format === "short" ? "aspect-[9/16] h-[480px] max-w-full" : "aspect-video w-full"}`} /><button className="btn-quiet mt-2" onClick={() => video.refetch()} disabled={video.isFetching}>Refresh preview link</button></>
          ) : (
            <div className="grid aspect-video place-items-center text-sm text-surface/70">{video.isLoading ? "Loading preview…" : "No preview yet"}</div>
          )}
        </div>
        <aside className="space-y-4" aria-label="Approval">
          {!decided && <ApprovalModeNotice />}
          {issues.length > 0 || bad.length > 0 ? (
            <div className="rounded-xl border border-alert/40 bg-alert-soft p-4 text-sm">
              <p className="font-medium text-alert">Check before approving</p>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-ink">
                {bad.map((c) => <li key={c.id}>Claim not backed by a source: “{c.claim_text.slice(0, 90)}”</li>)}
                {issues.map((i) => <li key={i}>{i}</li>)}
              </ul>
            </div>
          ) : (
            <div className="rounded-xl border border-penny/30 bg-penny-soft p-4 text-sm text-penny">
              Passed every automatic check: structure, sources, wording and length.
            </div>
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
              <button className="btn-quiet" onClick={() => setRegen(true)}>Rewrite with a note</button>
              <button className="btn-danger" onClick={() => setConfirm("reject")}>Discard package</button>
            </div>
          )}
        </aside>
      </div>

      <Confirm open={confirm === "approve"} title="Approve this package?"
        body={<>The video, its Shorts and {variants.length} post{variants.length === 1 ? "" : "s"} go out at their scheduled times. You can still cancel single posts in Calendar.</>}
        confirmLabel="Approve package" onCancel={() => setConfirm(null)} onConfirm={() => { setConfirm(null); approve.mutate(); }} />
      <Confirm open={confirm === "reject"} title="Discard this package?" danger
        body="The video, its Shorts and all their posts are rejected and their slots freed. It stays in Content → Not used."
        confirmLabel="Discard package" onCancel={() => setConfirm(null)} onConfirm={() => { setConfirm(null); reject.mutate(); }} />
      {regen && <RegenerateDialog project={project} onClose={() => setRegen(false)} />}

      <div role="tablist" aria-label="Package parts" className="mt-8 flex gap-1 overflow-x-auto border-b border-line">
        {([["script", "Script"], ["facts", `Sources & checks (${claims.length})`], ["thumbs", "Thumbnails"], ["shorts", `Shorts (${children.length})`], ["posts", `Posts (${variants.length})`], ["history", "History"]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${tab === k ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink"}`}>{label}</button>
        ))}
      </div>
      <div className="pt-5">
        {tab === "script" && script && <ScriptEditor project={project} version={script} />}
        {tab === "facts" && <><Facts claims={claims} /><AutoChecks projectId={id} /></>}
        {tab === "thumbs" && <Thumbs thumbs={thumbs} projectId={id} />}
        {tab === "posts" && <Posts variants={variants} tz={tz} />}
        {tab === "shorts" && <Shorts shorts={children} />}
        {tab === "history" && <History projectId={id} />}
      </div>
    </article>
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
        <button className="btn-primary" disabled={!dirty || save.isPending || draft.conflict} onClick={() => save.mutate()}>Save and re-render</button>
        {dirty && <button className="btn-quiet" onClick={() => setBody(version.body)}>Undo changes</button>}
      </div>
    </div>
  );
}

function Facts({ claims }: { claims: Claim[] }) {
  if (!claims.length) return <p className="text-sm text-muted">No factual claims in this script.</p>;
  return (
    <ul className="space-y-3">
      {claims.map((c) => (
        <li key={c.id} className="rounded-xl border border-line bg-surface p-4">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm">{c.claim_text}</p>
            <StatusBadge status={c.status === "supported" ? "approved" : c.status === "opinion" ? "proposed" : c.status === "partially_supported" ? "needs_attention" : "failed"} />
          </div>
          <p className="mt-2 text-xs text-muted">
            {c.status.replace(/_/g, " ")}{c.data_period ? ` · data period ${c.data_period}` : ""}
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

function Posts({ variants, tz }: { variants: Variant[]; tz: string }) {
  return (
    <ul className="space-y-4">
      {variants.map((v) => <PostEditor key={v.id} v={v} tz={tz} />)}
    </ul>
  );
}

function PostEditor({ v, tz }: { v: Variant; tz: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm, draft] = useFormDraft(`post:${v.id}`, {title: v.title ?? "", body: v.body ?? ""});
  const {title, body} = form;
  const setTitle = (title: string) => setForm((f) => ({...f, title}));
  const setBody = (body: string) => setForm((f) => ({...f, body}));
  const platform = v.social_accounts?.platform ?? "x";
  const limit = platform === "x" ? 280 : platform === "youtube" ? 5000 : 2200;
  const post = v.scheduled_posts?.[0];
  const save = useMutation({
    mutationFn: async () => {
      if (draft.conflict) throw new Error("This post changed elsewhere. Reload the current version before saving.");
      let update=supabase.from("content_variants").update({title:title||null,body}).eq("id",v.id);
      update=v.body == null ? update.is("body",null) : update.eq("body",v.body);
      update=v.title == null ? update.is("title",null) : update.eq("title",v.title);
      return must(update.select("id").single());
    },
    onSuccess: () => { qc.invalidateQueries(); toast("Post text saved"); },
  });
  const skip = useMutation({
    mutationFn: async () => {
      const { data: user } = await supabase.auth.getUser();
      await must(supabase.from("approvals").insert({ target_type: "variant", target_id: v.id, decision: "skipped", decided_by: user.user?.id }));
      await must(supabase.from("content_variants").update({ status: "skipped" }).eq("id", v.id));
    },
    onSuccess: () => { qc.invalidateQueries(); toast("Skipped. This post won't go out."); },
  });
  const dirty = title !== (v.title ?? "") || body !== (v.body ?? "");
  return (
    <li className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">{v.social_accounts?.label} · {KIND_NAME[v.kind] ?? v.kind}</p>
        <span className="flex items-center gap-2 text-xs text-muted">
          {post && <span className="tabular">{fmtDateTime(post.scheduled_at, tz)}</span>}
          <StatusBadge status={v.status} />
        </span>
      </div>
      {v.kind !== "text_post" && (
        <label className="mt-3 block text-sm">
          <span className="text-muted">Title</span>
          <input className="field mt-1" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={100} />
        </label>
      )}
      <label className="mt-3 block text-sm">
        <span className="text-muted">{v.kind === "long_video" ? "Description" : platform === "x" ? `Post for ${PLATFORM_NAME[platform]}` : "Caption"}</span>
        <textarea className="field mt-1" rows={v.kind === "long_video" ? 6 : 3} value={body} onChange={(e) => setBody(e.target.value)} />
        <span className={`mt-1 block text-right text-xs tabular ${body.length > limit ? "text-alert" : "text-muted"}`}>{body.length} / {limit}</span>
      </label>
      {draft.message && <p role="status" className="mt-2 text-sm text-muted">{draft.message} <button className="underline" onClick={draft.reset}>Discard edits</button></p>}
      <div className="mt-2 flex gap-2">
        <button className="btn-quiet" disabled={!dirty || body.length > limit || save.isPending || draft.conflict} onClick={() => save.mutate()}>Save text</button>
        {!["skipped", "rejected", "published"].includes(v.status) && <button className="btn-quiet" onClick={() => {if(window.confirm("Skip this post? This account will not receive it; the rest of the package is unchanged."))skip.mutate();}} disabled={skip.isPending}>Skip this post</button>}
      </div>
    </li>
  );
}

function Shorts({ shorts }: { shorts: Project[] }) {
  if (!shorts.length) return <p className="text-sm text-muted">No Shorts for this package.</p>;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {shorts.map((s) => <ShortCard key={s.id} s={s} />)}
    </div>
  );
}

function ShortCard({ s }: { s: Project }) {
  const url = usePreview(s.recipe?.preview_key);
  return (
    <figure className="rounded-xl border border-line bg-surface p-2">
      {url.data ? <video src={url.data} controls preload="metadata" className="aspect-[9/16] w-full rounded-lg bg-ink object-cover" /> : <div className="aspect-[9/16] rounded-lg bg-sunken" />}
      <figcaption className="mt-2 flex items-start justify-between gap-2 px-1 text-sm">
        <span className="font-medium leading-snug">{s.title}</span>
        <StatusBadge status={s.status} />
      </figcaption>
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
