// TikTok's required posting screen for Direct Post (Content Sharing Guidelines): the connected creator's name and
// picture, a preview, the caption, who can watch (no default), comments/Duet/Stitch (off unless chosen; greyed out
// when the creator turned them off in TikTok), commercial-content disclosure with its label, and the music consent.
// Confirming only saves the choices (checked again by the server and at posting time); the post goes out at its time.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { callWorker, MissingFileError, signedUrl } from "../lib/supabase";
import { caption as makeCaption } from "../lib/limits";
import { fmtDateTime } from "../lib/format";
import { useToast } from "./ui";
import type { TikTokPostSettings } from "../lib/types";

type Creator = {
  account_id: string; direct_post: boolean; creator_avatar_url?: string; creator_username?: string; creator_nickname?: string;
  privacy_level_options: string[]; comment_disabled: boolean; duet_disabled: boolean; stitch_disabled: boolean;
  max_video_post_duration_sec?: number; can_post?: boolean;
  content_snapshot?: NonNullable<TikTokPostSettings["content_snapshot"]>;
};

export const AUDIENCE: Record<string, string> = {
  PUBLIC_TO_EVERYONE: "Everyone", MUTUAL_FOLLOW_FRIENDS: "Friends", FOLLOWER_OF_CREATOR: "Followers", SELF_ONLY: "Only me",
};
const MUSIC = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en";
const BRANDED = "https://www.tiktok.com/legal/page/global/bc-policy/en";

export function TikTokPostPanel({ post, caption, dirty, locked, tz }: {
  post: { id: string; scheduled_at: string; status: string; tiktok_post?: TikTokPostSettings | null };
  caption: string; dirty: boolean; locked: boolean; tz: string;
}) {
  const saved = post.tiktok_post ?? null;
  const [editing, setEditing] = useState(false);
  const content = useQuery({ queryKey: ["tiktok-content", post.id], enabled: !locked, staleTime: 0,
    queryFn: () => callWorker<NonNullable<TikTokPostSettings["content_snapshot"]>>("/api/tiktok/content", { post_id: post.id }) });
  if (locked) return <p className="mt-3 text-sm text-muted">{post.status === "processing" ? "TikTok is processing this video. The studio will check again without uploading it again." : post.status === "publishing" ? "Uploading to TikTok…" : saved ? `Posted to TikTok for: ${AUDIENCE[saved.privacy_level] ?? saved.privacy_level}.` : "Sent to TikTok."}</p>;
  const changed = dirty || !content.data || JSON.stringify(saved?.content_snapshot) !== JSON.stringify(content.data);
  return (
    <section aria-label="TikTok posting settings" className="mt-4 rounded-lg border border-line bg-sunken/40 p-4">
      <h4 className="text-sm font-semibold">Post directly to TikTok</h4>
      {saved && content.isLoading && !editing ? <p className="mt-2 text-sm text-muted">Checking the confirmed TikTok content…</p> : saved && !editing && !changed ? (
        <div className="mt-2 text-sm">
          <p>✅ Confirmed: posts to <b>{saved.creator_nickname || "your TikTok"}</b>{saved.creator_username ? ` (@${saved.creator_username})` : ""} on{" "}
            <span className="tabular">{fmtDateTime(post.scheduled_at, tz)}</span>, visible to <b>{AUDIENCE[saved.privacy_level] ?? saved.privacy_level}</b>.</p>
          <p className="mt-1 text-muted">Comments {saved.allow_comment ? "on" : "off"} · Duet {saved.allow_duet ? "on" : "off"} · Stitch {saved.allow_stitch ? "on" : "off"}
            {saved.disclose ? ` · ${saved.branded_content ? "Paid partnership" : "Promotional content"} label` : ""}</p>
          <button className="btn-quiet mt-2" onClick={() => setEditing(true)}>Change TikTok settings</button>
        </div>
      ) : (
        <Form key={JSON.stringify(content.data ?? null)} post={post} caption={caption} dirty={dirty} saved={saved} onDone={() => setEditing(false)} />
      )}
    </section>
  );
}

function Form({ post, caption, dirty, saved, onDone }: {
  post: { id: string }; caption: string; dirty: boolean; saved: TikTokPostSettings | null; onDone: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const creator = useQuery({ queryKey: ["tiktok-creator", post.id], staleTime: 0, refetchOnMount: "always", retry: false, enabled: !dirty,
    queryFn: () => callWorker<Creator>("/api/tiktok/creator", { post_id: post.id }) });
  const previewKey = creator.data?.content_snapshot?.preview_key;
  const previewVersion = JSON.stringify(creator.data?.content_snapshot ?? null);
  const preview = useQuery({ queryKey: ["tiktok-preview", previewKey, previewVersion], staleTime: 50 * 60_000, enabled: Boolean(previewKey),
    retry: (n, e) => !(e instanceof MissingFileError) && n < 1,
    queryFn: () => signedUrl(previewKey!) });
  const [duration, setDuration] = useState<{ key: string; seconds: number } | null>(null);
  const seconds = duration && duration.key === previewVersion ? duration.seconds : null;
  // nothing is pre-selected: TikTok requires the owner to choose the audience and opt in to each interaction
  const [privacy, setPrivacy] = useState(saved?.privacy_level ?? "");
  const [comment, setComment] = useState(saved?.allow_comment ?? false);
  const [duet, setDuet] = useState(saved?.allow_duet ?? false);
  const [stitch, setStitch] = useState(saved?.allow_stitch ?? false);
  const [disclose, setDisclose] = useState(saved?.disclose ?? false);
  const [yourBrand, setYourBrand] = useState(saved?.your_brand ?? false);
  const [branded, setBranded] = useState(saved?.branded_content ?? false);
  const [consent, setConsent] = useState(false);

  const confirm = useMutation({
    mutationFn: () => {
      if (dirty) throw new Error("Save the edited post before confirming TikTok settings.");
      return callWorker("/api/tiktok/confirm", { post_id: post.id, seconds, content_snapshot: creator.data?.content_snapshot, choices: {
      privacy_level: privacy, allow_comment: comment, allow_duet: duet, allow_stitch: stitch,
      disclose, your_brand: yourBrand, branded_content: branded, consent } });
    },
    onSuccess: () => { qc.invalidateQueries(); toast("TikTok settings confirmed. It will post at its scheduled time."); onDone(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const clear = useMutation({
    mutationFn: () => callWorker("/api/tiktok/confirm", { post_id: post.id, clear: true }),
    onSuccess: () => { qc.invalidateQueries(); toast("Direct posting cancelled: this video will go to your TikTok inbox as a draft."); onDone(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });

  if (dirty && !creator.data) return <p role="status" className="mt-2 text-sm text-alert">Save the edited post below before confirming TikTok settings.</p>;
  if (creator.isLoading) return <p className="mt-2 text-sm text-muted">Checking your TikTok account…</p>;
  if (creator.error || !creator.data) return (
    <p className="mt-2 text-sm text-alert">{(creator.error as Error)?.message ?? "TikTok didn't answer."}{" "}
      <button className="underline" onClick={() => creator.refetch()}>Try again</button></p>
  );
  const c = creator.data;
  if (!c.direct_post) return (
    <p className="mt-2 text-sm text-muted">This video will go to your TikTok inbox as a draft. To post directly, switch on Direct Post
      (with <b>video.publish</b>) in your TikTok developer app, then connect TikTok again on the Setup page.</p>
  );
  const tooLong = Boolean(seconds && c.max_video_post_duration_sec && seconds > c.max_video_post_duration_sec);
  const brandedPrivate = disclose && branded && privacy === "SELF_ONLY";
  const disclosureMissing = disclose && !yourBrand && !branded;
  const label = disclose ? (branded ? "Paid partnership" : yourBrand ? "Promotional content" : "") : "";
  const snapshotCaption = c.content_snapshot ? makeCaption(c.content_snapshot.body, c.content_snapshot.hashtags) : null;
  const blocked = dirty || snapshotCaption !== caption || !preview.data || !seconds || c.can_post === false || !privacy || !consent || tooLong || brandedPrivate || disclosureMissing;

  return (
    <div className="mt-2 space-y-3 text-sm">
      {dirty && <p role="status" className="text-alert">Save the edited post below before confirming TikTok settings.</p>}
      {saved && <p className="text-muted">Confirm again after changing the video or caption.</p>}
      <p className="flex items-center gap-2">
        {c.creator_avatar_url && <img src={c.creator_avatar_url} alt="" className="h-8 w-8 rounded-full" />}
        <span>Posting to <b>{c.creator_nickname || "your TikTok account"}</b>{c.creator_username ? ` (@${c.creator_username})` : ""}</span>
      </p>
      {c.can_post === false && <p className="text-alert">TikTok says this account can't post more right now. Try again later.</p>}

      {preview.data
        ? <video key={previewVersion} src={preview.data} controls preload="metadata" onLoadedMetadata={(e) => setDuration({ key: previewVersion, seconds: e.currentTarget.duration || 0 })}
            className="aspect-[9/16] h-72 rounded-lg bg-ink" aria-label="Video that will be posted" />
        : <p className="text-muted">Preview not available.</p>}
      {tooLong && <p className="text-alert">This video is {Math.round(seconds!)} seconds; this account can post at most {c.max_video_post_duration_sec}.</p>}

      <div><span className="text-muted">Caption (edit it above and save the post)</span>
        <p className="mt-1 whitespace-pre-wrap rounded border border-line bg-surface p-2">{caption || "No caption"}</p></div>

      <label className="block">
        <span className="text-muted">Who can watch this video</span>
        <select className="field mt-1" value={privacy} onChange={(e) => setPrivacy(e.target.value)} required>
          <option value="" disabled>Choose…</option>
          {c.privacy_level_options.map((o) => (
            <option key={o} value={o} disabled={o === "SELF_ONLY" && disclose && branded}>
              {AUDIENCE[o] ?? o}{o === "SELF_ONLY" && disclose && branded ? " (not allowed for branded content)" : ""}
            </option>
          ))}
        </select>
      </label>

      <fieldset>
        <legend className="text-muted">Allow viewers to</legend>
        {([["Comment", comment, setComment, c.comment_disabled], ["Duet", duet, setDuet, c.duet_disabled],
           ["Stitch", stitch, setStitch, c.stitch_disabled]] as const).map(([name, val, set, off]) => (
          <label key={name} className="mr-4 inline-flex items-center gap-2">
            <input type="checkbox" checked={!off && val} disabled={off} onChange={(e) => set(e.target.checked)} />
            {name}{off ? " (turned off in your TikTok settings)" : ""}
          </label>
        ))}
      </fieldset>

      <fieldset className="rounded border border-line p-3">
        <label className="flex items-center gap-2 font-medium">
          <input type="checkbox" checked={disclose} onChange={(e) => { setDisclose(e.target.checked); if (!e.target.checked) { setYourBrand(false); setBranded(false); } }} />
          Disclose video content
        </label>
        <p className="mt-1 text-muted">Turn on to say this video promotes goods or services in exchange for something of value.</p>
        {disclose && (
          <div className="mt-2 space-y-1">
            <label className="flex items-start gap-2"><input type="checkbox" checked={yourBrand} onChange={(e) => setYourBrand(e.target.checked)} />
              <span><b>Your brand</b>: you're promoting yourself or your own business.</span></label>
            <label className="flex items-start gap-2"><input type="checkbox" checked={branded} onChange={(e) => setBranded(e.target.checked)} />
              <span><b>Branded content</b>: you're promoting another brand or a third party.</span></label>
            {label && <p>Your video will be labeled “{label}”.</p>}
            {disclosureMissing && <p className="text-alert">Choose at least one.</p>}
            {brandedPrivate && <p className="text-alert">Branded content can't be private. Choose another audience.</p>}
          </div>
        )}
      </fieldset>

      <label className="flex items-start gap-2">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span>By posting, I agree to TikTok's <a className="underline" href={MUSIC} target="_blank" rel="noopener noreferrer">Music Usage Confirmation</a>
          {disclose && branded && <> and <a className="underline" href={BRANDED} target="_blank" rel="noopener noreferrer">Branded Content Policy</a></>}.</span>
      </label>
      <p className="text-muted">After it posts, TikTok may take a few minutes to process the video before it appears on your profile.</p>

      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" disabled={blocked || confirm.isPending} onClick={() => confirm.mutate()}>
          {confirm.isPending ? "Checking with TikTok…" : "Confirm and post at the scheduled time"}
        </button>
        {saved && <button className="btn-quiet" disabled={clear.isPending} onClick={() => clear.mutate()}>Send to my TikTok inbox instead</button>}
        {saved && <button className="btn-quiet" onClick={onDone}>Cancel</button>}
      </div>
    </div>
  );
}
