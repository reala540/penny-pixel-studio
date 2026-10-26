import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CircleAlert, CircleCheck, CircleDashed, ExternalLink, LoaderCircle, Search, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApprovalModeNotice } from "../components/AutoPostToggle";
import DraftList from "../components/Drafts";
import IdeaCard from "../components/IdeaCard";
import ResearchIdeaCard from "../components/ResearchIdeaCard";
import { Empty, ErrorNote, Loading, NotConfirmed, PageHeader, useToast } from "../components/ui";
import { must, queueJob } from "../lib/api";
import { stageRows, useStageJobs } from "../lib/content";
import { safeUrl } from "../lib/format";
import { getDraft, newDraftId, saveDraft, useOwnerId, type CreateDraft } from "../lib/drafts";
import { draftUrl } from "../lib/draftStatus";
import { buildObjective } from "../lib/ideas";
import { useActiveIdeaJob, useIdeaActions } from "../lib/ideasApi";
import { useReadiness } from "../lib/readiness";
import { projectPath } from "../lib/routes";
import { supabase, workerUrl } from "../lib/supabase";
import type { GeneratedIdea, Idea } from "../lib/types";

type Step = "channel" | "idea" | "research" | "package" | "progress";
type Channel = "ai" | "money" | "both";
type Kind = "generated" | "research";
const STEPS: [Step | "review" | "schedule", string][] = [
  ["channel", "Channel"], ["idea", "Idea"], ["research", "Research"], ["package", "Package"], ["progress", "Progress"], ["review", "Review"], ["schedule", "Schedule"],
];
const CHANNEL_NAME: Record<Channel, string> = { ai: "Pixel · AI", money: "Penny · Money", both: "Both channels" };

type SaveState = "idle" | "saving" | "saved" | "failed";
// One id per visit (history entry) for a new draft: remounting the page never starts a second draft.
const visitDraftIds = new Map<string, string>();
const visitDraftId = (key: string) => { if (!visitDraftIds.has(key)) visitDraftIds.set(key, newDraftId()); return visitDraftIds.get(key)!; };

export default function Create() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const owner = useOwnerId();
  const step = (params.get("step") as Step) || "channel";
  const channel = params.get("channel") as Channel | null;
  const kind = params.get("kind") as Kind | null;
  const id = params.get("id");
  const draftId = params.get("draft");
  const go = (next: Partial<Record<"step" | "channel" | "kind" | "id", string | null>>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) v ? p.set(k, v) : p.delete(k);
    setParams(p);
  };

  // ---- the draft: every choice and the typed idea are kept on this device (never keys), so nothing is lost
  const saved = getDraft(owner, draftId);
  const [own, setOwn] = useState(() => saved?.own ?? "");
  const [depth, setDepth] = useState(() => saved?.depth ?? 3);
  const [ideaTitle, setIdeaTitle] = useState<string | null>(() => saved?.ideaTitle ?? null);
  const baseRev = useRef<number | null>(saved?.rev ?? null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [conflict, setConflict] = useState<CreateDraft | null>(null);
  const loadedFor = useRef(draftId);
  const visit = useLocation().key;
  useEffect(() => {  // opened another draft (or Start new) without leaving the page
    if (loadedFor.current === draftId) return;
    loadedFor.current = draftId;
    const d = getDraft(owner, draftId);
    setOwn(d?.own ?? ""); setDepth(d?.depth ?? 3); setIdeaTitle(d?.ideaTitle ?? null);
    baseRev.current = d?.rev ?? null; setConflict(null); setSaveState("idle");
  }, [draftId, owner]);

  const persist = (force = false) => {
    if (!owner) return;
    const body = { step, channel, kind, ideaId: id, ideaTitle: id ? ideaTitle : null, own, depth };
    if (!channel && !id && !own.trim()) return;  // nothing chosen yet
    const current = getDraft(owner, draftId);
    if (current && !force && JSON.stringify([current.step, current.channel, current.kind, current.ideaId, current.ideaTitle ?? null, current.own ?? "", current.depth])
      === JSON.stringify([step, channel, kind, id, id ? ideaTitle : null, own.trim() ? own : "", depth])) { baseRev.current = current.rev; setSaveState("saved"); return; }
    const draft = draftId ?? visitDraftId(visit);
    setSaveState("saving");
    const r = saveDraft(owner, { id: draft, ...body }, draftId ? baseRev.current : null, force);
    if (r.ok) {
      baseRev.current = r.draft.rev; setSaveState("saved"); setConflict(null);
      if (!draftId) { loadedFor.current = draft; const p = new URLSearchParams(params); p.set("draft", draft); setParams(p, { replace: true }); }
    } else if (r.reason === "conflict") { setConflict(r.newer); setSaveState("idle"); }
    else setSaveState("failed");
  };
  const conflictRef = useRef(conflict);
  conflictRef.current = conflict;
  const latest = useRef(persist);
  latest.current = persist;
  const pending = useRef(false);
  useEffect(() => {
    if (conflict) return;  // wait for the owner to choose which version to keep
    pending.current = true;
    if (own) setSaveState("saving");
    const t = setTimeout(() => { pending.current = false; latest.current(); }, own ? 500 : 0);
    return () => clearTimeout(t);
  }, [step, channel, kind, id, own, depth, ideaTitle, owner]); // eslint-disable-line react-hooks/exhaustive-deps
  // leaving the page or closing the tab saves at once: the last words typed are never lost
  useEffect(() => {
    const flush = () => { if (pending.current && !conflictRef.current) { pending.current = false; latest.current(); } };
    window.addEventListener("pagehide", flush);
    return () => { window.removeEventListener("pagehide", flush); flush(); };
  }, []);
  const useOther = (d: CreateDraft) => {
    setOwn(d.own ?? ""); setDepth(d.depth ?? 3); setIdeaTitle(d.ideaTitle ?? null);
    baseRev.current = d.rev; setConflict(null); setSaveState("saved");
    navigate(draftUrl(d), { replace: true });
  };

  const index = STEPS.findIndex(([k]) => k === step);
  const fresh = !draftId && !params.get("step");
  return (
    <>
      <PageHeader title="Create content" intro="Step by step from an idea to a package ready for review. You can go back at any time, and leave: your place is kept." />
      {fresh && <DraftList />}
      {conflict && (
        <div role="alert" className="mb-4 max-w-4xl rounded-lg bg-gold/15 px-3 py-2 text-sm text-ink">
          This draft was changed in another tab ({new Date(conflict.updatedAt).toLocaleTimeString()}). Which version do you want to keep?
          <div className="mt-2 flex flex-wrap gap-2">
            <button className="btn-quiet" onClick={() => useOther(conflict)}>Use the other tab's version</button>
            <button className="btn-quiet" onClick={() => persist(true)}>Keep this one</button>
          </div>
        </div>
      )}
      <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-2">
        <ol aria-label="Steps" className="flex flex-wrap gap-1.5 text-xs">
          {STEPS.map(([k, label], i) => (
            <li key={k} aria-current={i === index ? "step" : undefined}
              className={`rounded-full px-2.5 py-1 ${i === index ? "bg-ink text-surface" : i < index ? "bg-penny-soft text-penny" : "bg-sunken text-muted"}`}>
              {i + 1} {label}
            </li>
          ))}
        </ol>
        <p role="status" className={`text-xs ${saveState === "failed" ? "text-alert" : "text-muted"}`}>
          {saveState === "saving" ? "Saving…" : saveState === "saved" ? "Saved on this device" : saveState === "failed" ? "Couldn't save on this device (private browsing or storage full): don't close this tab" : ""}
        </p>
        {draftId && (
          <button type="button" className="text-xs text-muted underline-offset-2 hover:text-ink hover:underline"
            onClick={() => navigate("/create")}>Start new (this one stays in your drafts)</button>
        )}
      </div>
      {step !== "channel" && (
        <button className="btn-quiet mb-4" onClick={() => go({ step: STEPS[Math.max(0, index - 1)][0] as Step })}><ArrowLeft size={14} aria-hidden />Back</button>
      )}
      <div className="max-w-4xl">
        {step === "channel" && <ChannelStep onPick={(c) => go({ step: "idea", channel: c, kind: null, id: null })} />}
        {step === "idea" && channel && <IdeaStep channel={channel} own={own} setOwn={setOwn} depth={depth} setDepth={setDepth}
          onPick={(k, i, title) => { setIdeaTitle(title); go({ step: "research", kind: k, id: i }); }} />}
        {step === "research" && kind && id && <ResearchStep channel={channel} kind={kind} id={id}
          onContinue={(c) => go({ step: "package", channel: c })} onChooseAnother={() => go({ step: "idea", kind: null, id: null })} />}
        {step === "package" && kind && id && channel && channel !== "both" && <PackageStep channel={channel} kind={kind} id={id} onStarted={() => go({ step: "progress" })} />}
        {step === "progress" && kind && id && <ProgressStep kind={kind} id={id} channel={channel} />}
        {((step !== "channel" && !channel && step === "idea") || ((step === "research" || step === "package" || step === "progress") && (!kind || !id))) && (
          <Empty title="Start from the beginning">Choose a channel first. <button className="text-pixel underline" onClick={() => go({ step: "channel", kind: null, id: null })}>Choose a channel</button></Empty>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ 1 channel

function ChannelStep({ onPick }: { onPick: (c: Channel) => void }) {
  const card = (c: "ai" | "money", title: string, text: string, tone: string) => (
    <button type="button" onClick={() => onPick(c)} className={`rounded-xl border-l-4 ${tone} border border-line bg-surface p-5 text-left hover:bg-sunken`}>
      <span className="block font-display text-lg font-semibold">{title}</span>
      <span className="mt-1 block text-sm text-muted">{text}</span>
    </button>
  );
  return (
    <section aria-labelledby="ch-title">
      <h2 id="ch-title" className="section-title mb-3">Step 1 · Choose a channel</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {card("ai", "Pixel · Penny & Pixel AI", "AI tools, workflows and careers", "border-l-pixel")}
        {card("money", "Penny · Penny & Pixel Money", "Budgeting, prices and money skills", "border-l-penny")}
      </div>
      <p className="mt-4 text-sm text-muted">
        <button className="text-pixel underline-offset-2 hover:underline" onClick={() => onPick("both")}>Find ideas or research for both channels</button>
        {" "}(ideas only: a package is always made for one channel).
      </p>
    </section>
  );
}

// ------------------------------------------------------------------ 2 idea

function IdeaStep({ channel, onPick, own, setOwn, depth, setDepth }: { channel: Channel; onPick: (k: Kind, id: string, title: string) => void;
  own: string; setOwn: (v: string) => void; depth: number; setDepth: (n: number) => void }) {
  const toast = useToast();
  const [q, setQ] = useState("");
  const [source, setSource] = useState<"all" | Kind>("all");
  const job = useActiveIdeaJob();
  const { generate } = useIdeaActions();
  const generated = useQuery({
    queryKey: ["ideas", "create", channel],
    refetchInterval: job.data ? 8000 : false,
    queryFn: async () => {
      let qy = supabase.from("generated_ideas").select("*").in("status", ["new", "saved"]).order("total", { ascending: false }).limit(60);
      if (channel !== "both") qy = qy.or(`channel_slug.eq.${channel},channel_slug.eq.both,channel_slug.is.null`);
      return (await must(qy)) as GeneratedIdea[];
    },
  });
  const research = useQuery({
    queryKey: ["research-ideas", "create", channel],
    queryFn: async () => {
      let qy = supabase.from("content_ideas").select("*").in("status", ["proposed", "shortlisted", "saved"]).order("created_at", { ascending: false }).limit(60);
      if (channel !== "both") qy = qy.eq("channel_slug", channel);
      return (await must(qy)) as Idea[];
    },
  });
  const research_job = useMutation({
    mutationFn: () => queueJob("run_research", { input: { brief: own.trim().slice(0, 2000), channel: channel === "both" ? null : channel, models: depth } }),
    onSuccess: () => { toast("Research started. New ideas appear in this list when it finishes."); setOwn(""); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const needle = q.trim().toLowerCase();
  const match = (t: string) => !needle || t.toLowerCase().includes(needle);
  const gen = (generated.data ?? []).filter((i) => match(`${i.title} ${i.summary}`));
  const res = (research.data ?? []).filter((i) => match(`${i.title} ${i.angle ?? ""}`));
  const ideasOnly = channel === "both";
  const pick = (k: Kind, i: string, title: string) => onPick(k, i, title);
  return (
    <section aria-labelledby="idea-title">
      <h2 id="idea-title" className="section-title mb-1">Step 2 · Choose or generate an idea <span className="font-normal text-muted">· {CHANNEL_NAME[channel]}</span></h2>
      {ideasOnly && <p className="mb-3 text-sm text-muted">Ideas-only mode: generate ideas or research for both channels. To make a package, start again and choose one channel.</p>}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="min-w-[12rem] flex-1"><span className="sr-only">Search ideas</span>
          <input className="field" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search ideas" /></label>
        <label className="flex items-center gap-2 text-sm text-muted">Show
          <select aria-label="Show" className="field w-auto" value={source} onChange={(e) => setSource(e.target.value as "all" | Kind)}>
            <option value="all">All ideas</option><option value="generated">Idea Generator</option><option value="research">Weekly research</option>
          </select></label>
        <button className="btn-primary" disabled={Boolean(job.data) || generate.isPending}
          onClick={() => generate.mutate({ trigger: "manual", channel: channel === "both" ? undefined : channel },
            { onSuccess: () => toast("Finding new ideas. They appear here when ready."), onError: (e) => toast((e as Error).message, "bad") })}>
          <Sparkles size={14} aria-hidden />{job.data ? "Finding ideas…" : "Generate new ideas"}</button>
      </div>
      {job.data && <p role="status" className="mb-3 rounded-lg bg-pixel-soft px-3 py-2 text-sm text-pixel">{job.data.status === "queued" ? "Waiting to start (within 15 minutes)…" : "Finding and scoring ideas…"} The list updates by itself.</p>}
      {generated.isLoading || research.isLoading ? <Loading label="Loading ideas" /> : generated.isError || research.isError ? <NotConfirmed q={generated.isError ? generated : research} what="ideas" /> : (
        (source !== "research" ? gen.length : 0) + (source !== "generated" ? res.length : 0) === 0 ? (
          <Empty title={`No ideas for ${CHANNEL_NAME[channel]} yet`}>Press <strong>Generate new ideas</strong>, or write your own below.</Empty>
        ) : (
          <div className="space-y-3">
            {source !== "research" && gen.map((i) => <IdeaCard key={i.id} idea={i} onUse={ideasOnly ? undefined : (x) => pick("generated", x.id, x.title)} />)}
            {source !== "generated" && res.map((i) => <ResearchIdeaCard key={i.id} idea={i} showSources={false} onUse={ideasOnly ? undefined : (x) => pick("research", x.id, x.title)} />)}
          </div>
        )
      )}
      <form className="mt-6 rounded-xl border border-line bg-surface p-4" onSubmit={(e) => { e.preventDefault(); if (own.trim().length >= 12) research_job.mutate(); }}>
        <h3 className="text-sm font-semibold">Write my own idea</h3>
        <p className="mt-1 text-xs text-muted">The studio researches it with dated sources and adds the best angles to the list above as weekly research ideas.</p>
        <label className="mt-2 block"><span className="sr-only">Your idea</span>
          <textarea className="field min-h-20" maxLength={2000} value={own} onChange={(e) => setOwn(e.target.value)} placeholder="Example: Three practical AI tools that save small shops time each week" /></label>
        <details className="mt-2 text-sm"><summary className="cursor-pointer text-muted">More options</summary>
          <label className="mt-2 flex items-center gap-2">Council depth
            <select aria-label="Council depth" className="field w-auto" value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
              <option value={2}>Focused · 2 models</option><option value={3}>Balanced · 3 models</option><option value={5}>Wide · 5 models</option>
            </select></label>
        </details>
        <button className="btn-quiet mt-3" disabled={own.trim().length < 12 || research_job.isPending}><Search size={14} aria-hidden />Research this</button>
      </form>
    </section>
  );
}

// ------------------------------------------------------------------ shared: the selected idea and any package made from it

function useSelected(kind: Kind, id: string) {
  return useQuery({
    queryKey: ["create-selected", kind, id],
    queryFn: async () => {
      if (kind === "generated") {
        const g = ((await must(supabase.from("generated_ideas").select("*").eq("id", id))) as (GeneratedIdea & { content_idea_id?: string | null })[])[0];
        if (!g) throw new Error("That idea no longer exists.");
        const project = g.content_idea_id ? ((await must(supabase.from("content_projects").select("id, status, title").eq("idea_id", g.content_idea_id).is("parent_project_id", null))) as any[])[0] ?? null : null;
        return { kind, generated: g, research: null as Idea | null, project, title: g.title, channel: g.channel_slug };
      }
      const r = ((await must(supabase.from("content_ideas").select("*").eq("id", id))) as Idea[])[0];
      if (!r) throw new Error("That idea no longer exists.");
      const project = ((await must(supabase.from("content_projects").select("id, status, title").eq("idea_id", r.id).is("parent_project_id", null))) as any[])[0] ?? null;
      return { kind, generated: null as GeneratedIdea | null, research: r, project, title: r.title, channel: r.channel_slug };
    },
  });
}

// ------------------------------------------------------------------ 3 research

function ResearchStep({ channel, kind, id, onContinue, onChooseAnother }: { channel: Channel | null; kind: Kind; id: string;
  onContinue: (channel: string) => void; onChooseAnother: () => void }) {
  const toast = useToast();
  const sel = useSelected(kind, id);
  const sources = useQuery({
    queryKey: ["create-sources", kind, id],
    enabled: Boolean(sel.data?.research),
    queryFn: async () => (await must(supabase.from("research_sources").select("id, title, publisher, url, published_at, retrieved_at").in("id", sel.data!.research!.source_ids))) as any[],
  });
  const deeper = useMutation({
    mutationFn: () => queueJob("run_research", { input: {
      brief: (sel.data?.generated ? buildObjective(sel.data.generated, 1800) : `${sel.data?.title}\n${sel.data?.research?.angle ?? ""}`).slice(0, 2000),
      channel: pickChannel(), models: 3 } }),
    onSuccess: () => toast("Researching it deeper. New sources and angles appear as weekly research ideas."),
    onError: (e) => toast((e as Error).message, "bad"),
  });
  function pickChannel(): "ai" | "money" | null {
    const c = sel.data?.channel;
    if (c === "ai" || c === "money") return c;
    return channel === "ai" || channel === "money" ? channel : null;
  }
  if (sel.isLoading) return <Loading label="Loading the idea" />;
  if (sel.error) return <ErrorNote error={sel.error} onRetry={() => sel.refetch()} retrying={sel.isFetching} />;
  const d = sel.data!;
  const list = d.generated
    ? d.generated.trend_signals.map((s) => ({ key: s.source_id, title: s.title, url: s.url, meta: `${s.observed ?? ""}${s.published_at ? ` · ${s.published_at.slice(0, 10)}` : ""}` }))
    : (sources.data ?? []).map((s) => ({ key: s.id, title: s.title, url: s.url, meta: `${s.publisher ?? ""}${s.published_at ? ` · ${String(s.published_at).slice(0, 10)}` : ""}` }));
  const finalChannel = pickChannel();
  const noSources = list.length === 0 && !sources.isLoading;
  return (
    <section aria-labelledby="rs-title">
      <h2 id="rs-title" className="section-title mb-1">Step 3 · Check the research</h2>
      <p className="mb-3 font-display text-lg font-semibold">{d.title}</p>
      {d.project && (
        <p role="status" className="mb-3 rounded-lg bg-penny-soft px-3 py-2 text-sm text-ink">A package was already made from this idea. <Link className="font-medium text-pixel underline" to={projectPath(d.project.id)}>Open it</Link></p>
      )}
      <h3 className="text-sm font-semibold">Sources ({list.length})</h3>
      {sources.isLoading ? <Loading /> : sources.isError ? <NotConfirmed q={sources} what="this idea's sources" /> : noSources ? (
        <p className="mt-2 rounded-lg bg-alert-soft px-3 py-2 text-sm text-alert">This idea has no stored sources, so its facts can't be checked. Use <strong>Research it deeper</strong> first.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {list.map((s) => (
            <li key={s.key} className="text-sm">
              <a href={safeUrl(s.url)} target="_blank" rel="noopener noreferrer" className="inline-flex items-start gap-1 font-medium underline-offset-2 hover:underline">{s.title}<ExternalLink size={12} className="mt-1" aria-hidden /><span className="sr-only">(opens in a new tab)</span></a>
              <p className="text-xs text-muted">{s.meta}</p>
            </li>
          ))}
        </ul>
      )}
      {d.generated?.sensitivity_note && <p className="mt-3 text-sm"><strong>Care notes:</strong> {d.generated.sensitivity_note}</p>}
      {channel === "both" || !finalChannel ? (
        <p className="mt-4 text-sm text-muted">This idea fits both channels. To make a package, choose one:
          {" "}<button className="text-pixel underline" onClick={() => onContinue("ai")}>Pixel</button> or <button className="text-pixel underline" onClick={() => onContinue("money")}>Penny</button>.</p>
      ) : null}
      <div className="mt-5 flex flex-wrap gap-2">
        {channel !== "both" && finalChannel && <button className="btn-primary" disabled={noSources || Boolean(d.project)} onClick={() => onContinue(finalChannel)}>Looks good, continue</button>}
        <button className="btn-quiet" disabled={deeper.isPending} onClick={() => deeper.mutate()}><Search size={14} aria-hidden />Research it deeper</button>
        <button className="btn-quiet" onClick={onChooseAnother}>Choose another idea</button>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ 4 package (B1: exactly this idea)

function useIdeaJob(kind: Kind, id: string) {
  return useQuery({
    queryKey: ["produce-idea-job", kind, id],
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 5000 : 15_000),
    queryFn: async () => ((await must(supabase.from("generation_jobs").select("id, status, error_message, project_id, progress, created_at, updated_at, output")
      .eq("job_type", "produce_idea").eq(kind === "generated" ? "input->>generated_idea_id" : "input->>content_idea_id", id)
      .order("created_at", { ascending: false }).limit(1))) as any[])[0] ?? null,
  });
}

function PackageStep({ channel, kind, id, onStarted }: { channel: "ai" | "money"; kind: Kind; id: string; onStarted: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const sel = useSelected(kind, id);
  const ready = useReadiness();
  const job = useIdeaJob(kind, id);
  const busy = job.data && ["queued", "running"].includes(job.data.status);
  const start = useMutation({
    mutationFn: async () => {
      // check again right before queuing: another tab (or Telegram) may have started it a moment ago
      const latest = (await job.refetch()).data;
      if (latest && ["queued", "running"].includes(latest.status)) return { already: true };
      await queueJob("produce_idea", { input: { [kind === "generated" ? "generated_idea_id" : "content_idea_id"]: id, channel } });
      return { already: false };
    },
    onSuccess: (r) => { if (r.already) toast("This package was already being made, so nothing new was started."); qc.invalidateQueries({ queryKey: ["produce-idea-job", kind, id] }); onStarted(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  if (sel.isLoading) return <Loading />;
  if (sel.error) return <ErrorNote error={sel.error} onRetry={() => sel.refetch()} retrying={sel.isFetching} />;
  return (
    <section aria-labelledby="pk-title">
      <h2 id="pk-title" className="section-title mb-1">Step 4 · Create the package</h2>
      <p className="font-display text-lg font-semibold">{sel.data!.title} <span className="text-sm font-normal text-muted">· {CHANNEL_NAME[channel]}</span></p>
      <p className="mt-2 text-sm text-muted">Makes this idea only: a long video, its Shorts, thumbnails and a post for each enabled account that shares this channel's topics. Your weekly batch isn't affected.</p>
      <div className="mt-4"><ApprovalModeNotice /></div>
      {ready.blockers.map((b) => <p key={b.text} role="alert" className="mt-3 flex items-start gap-2 rounded-lg bg-alert-soft px-3 py-2 text-sm text-alert"><CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />{b.text} <Link to={b.to} className="underline">Fix it</Link></p>)}
      {ready.warnings.map((w) => <p key={w.text} className="mt-3 flex items-start gap-2 rounded-lg bg-gold/15 px-3 py-2 text-sm text-ink"><CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />{w.text} <Link to={w.to} className="underline">Check</Link></p>)}
      {sel.data!.project ? (
        <p className="mt-4 text-sm">Already made: <Link className="font-medium text-pixel underline" to={projectPath(sel.data!.project.id)}>open the package</Link>.</p>
      ) : busy ? (
        <p className="mt-4 text-sm">This package is already being made. <button className="text-pixel underline" onClick={onStarted}>See progress</button></p>
      ) : (
        <button className="btn-primary mt-5" disabled={!ready.canCreate || start.isPending} onClick={() => start.mutate()}>{start.isPending ? "Starting…" : "Create package"}</button>
      )}
      {!workerUrl && <p className="mt-2 text-xs text-muted">Without the Worker nothing can start. See Settings → Getting started.</p>}
    </section>
  );
}

// ------------------------------------------------------------------ 5 progress (only what the engine reports)

function ProgressStep({ kind, id, channel }: { kind: Kind; id: string; channel: Channel | null }) {
  const qc = useQueryClient();
  const toast = useToast();
  const sel = useSelected(kind, id);
  const job = useIdeaJob(kind, id);
  const projectId = job.data?.project_id ?? sel.data?.project?.id ?? null;
  const live = !job.data || ["queued", "running"].includes(job.data.status);
  const stages = useStageJobs(projectId, live);
  const project = useQuery({
    queryKey: ["create-project", projectId], enabled: Boolean(projectId), refetchInterval: live ? 10_000 : false,
    queryFn: async () => ((await must(supabase.from("content_projects").select("id, status, title").eq("id", projectId!))) as any[])[0] ?? null,
  });
  const rows = useMemo(() => stageRows(stages.data ?? []), [stages.data]);
  const retry = useMutation({
    mutationFn: async () => {
      const latest = (await job.refetch()).data;
      if (latest && ["queued", "running"].includes(latest.status)) return;  // already trying again
      await queueJob("produce_idea", { input: { [kind === "generated" ? "generated_idea_id" : "content_idea_id"]: id,
        ...(channel === "ai" || channel === "money" ? { channel } : {}) } });
    },
    onSuccess: () => { toast("Trying again from the step that didn't work."); qc.invalidateQueries({ queryKey: ["produce-idea-job", kind, id] }); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  if (job.isLoading || sel.isLoading) return <Loading label="Loading progress" />;
  const status = job.data?.status as string | undefined;
  const p = project.data;
  const ready = p && ["ready_for_review", "needs_attention", "approved", "scheduled", "published"].includes(p.status);
  return (
    <section aria-labelledby="pg-title">
      <h2 id="pg-title" className="section-title mb-1">Step 5 · Being made</h2>
      <p className="font-display text-lg font-semibold">{sel.data?.title}</p>
      {!job.data && !p && <p className="mt-3 text-sm text-muted">Nothing has been started for this idea yet.</p>}
      {status === "queued" && <p role="status" className="mt-3 rounded-lg bg-pixel-soft px-3 py-2 text-sm text-pixel">Waiting to start. The engine picks it up within 15 minutes.</p>}
      {status === "running" && job.data?.progress?.label && <p role="status" className="mt-3 rounded-lg bg-pixel-soft px-3 py-2 text-sm text-pixel"><LoaderCircle size={14} className="mr-1 inline animate-spin" aria-hidden />Now: {job.data.progress.label}</p>}
      {(job.data || p) && (
        <ol className="mt-4 space-y-2">
          {rows.map((r) => (
            <li key={r.key} className="flex items-start gap-2 text-sm">
              {r.state === "done" ? <CircleCheck size={17} className="mt-0.5 text-penny" aria-hidden /> : r.state === "failed" ? <CircleAlert size={17} className="mt-0.5 text-alert" aria-hidden />
                : r.state === "running" ? <LoaderCircle size={17} className="mt-0.5 animate-spin text-pixel" aria-hidden /> : <CircleDashed size={17} className="mt-0.5 text-muted" aria-hidden />}
              <span><span className="font-medium">{r.label}</span>{r.detail ? <span className="text-muted"> · {r.detail}</span> : null}
                <span className="sr-only"> ({r.state})</span>
                {r.error && <span className="block text-alert">{r.error.slice(0, 300)}</span>}</span>
            </li>
          ))}
        </ol>
      )}
      {(status === "failed" || status === "cancelled") && (
        <div className="mt-4 rounded-lg bg-alert-soft px-3 py-2 text-sm text-alert">
          <p><strong>{status === "cancelled" ? "Cancelled; completed work was kept:" : "This didn't work:"}</strong> {String(job.data?.error_message ?? "").slice(0, 400)}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button className="btn-quiet" disabled={retry.isPending} onClick={() => retry.mutate()}>{status === "cancelled" ? "Resume from checkpoint" : "Try again from this step"}</button>
            {/AI|provider|research_summarizer|role/i.test(job.data?.error_message ?? "") && <Link to="/settings/ai" className="btn-quiet">Check AI services</Link>}
          </div>
          <p className="mt-2 text-xs">Steps that already finished aren't redone.</p>
        </div>
      )}
      {ready && (
        <div className="mt-5 flex flex-wrap gap-2">
          <Link to={projectPath(p.id)} className="btn-primary">{p.status === "ready_for_review" || p.status === "needs_attention" ? "Step 6 · Review the package" : "Open the completed package"}</Link>
          <Link to={projectPath(p.id, "posts")} className="btn-quiet">Step 7 · Check the schedule</Link>
        </div>
      )}
      {p && !ready && status !== "failed" && <p className="mt-4 text-sm text-muted">You can leave this page; progress is saved. <Link to="/activity" className="text-pixel underline">Open Activity</Link></p>}
    </section>
  );
}
