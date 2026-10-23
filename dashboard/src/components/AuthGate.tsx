import type { Session } from "@supabase/supabase-js";
import { FormEvent, ReactNode, useEffect, useState } from "react";
import { configured, supabase } from "../lib/supabase";

type OwnerState = "checking" | "owner" | "not-owner";

export default function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [owner, setOwner] = useState<OwnerState>("checking");

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session) return;
    setOwner("checking");
    // The first account to sign in becomes the owner; everyone after that is refused by the database.
    supabase.rpc("claim_ownership").then(({ data, error }) => setOwner(!error && data ? "owner" : "not-owner"));
  }, [session?.user.id]);

  if (!configured) return <Shell><SetupNeeded /></Shell>;
  if (session === undefined) return <Shell><p className="text-muted">Loading…</p></Shell>;
  if (!session) return <Shell><SignIn /></Shell>;
  if (owner === "checking") return <Shell><p className="text-muted">Checking your access…</p></Shell>;
  if (owner === "not-owner")
    return (
      <Shell>
        <h1 className="font-display text-2xl font-bold">This studio already has an owner</h1>
        <p className="mt-2 text-muted">You're signed in as {session.user.email}, which isn't the owner account.</p>
        <button className="btn-quiet mt-6" onClick={() => supabase.auth.signOut()}>Sign out</button>
      </Shell>
    );
  return <>{children}</>;
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <svg width="40" height="40" viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" rx="8" className="fill-ink" />
            <circle cx="12" cy="16" r="6" className="fill-gold" />
            <rect x="17" y="10" width="11" height="12" rx="2" className="fill-cyan" />
          </svg>
          <p className="font-display text-xl font-bold">Penny &amp; Pixel Studio</p>
        </div>
        {children}
      </div>
    </div>
  );
}

function SetupNeeded() {
  return (
    <>
      <h1 className="font-display text-2xl font-bold">Almost there</h1>
      <p className="mt-2 text-muted">
        The dashboard doesn't know your Supabase project yet. Add <code>VITE_SUPABASE_URL</code> and{" "}
        <code>VITE_SUPABASE_ANON_KEY</code> to the Cloudflare Pages settings (GUIDE.md, step 8), then redeploy.
      </p>
    </>
  );
}

function SignIn() {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const { error, data } =
      mode === "in"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin } });
    setBusy(false);
    if (error) return setMsg({ text: error.message, bad: true });
    if (mode === "up" && !data.session) setMsg({ text: "Check your email and click the confirmation link, then sign in here." });
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="font-display text-2xl font-bold">{mode === "in" ? "Sign in" : "Create the owner account"}</h1>
      {mode === "up" && <p className="text-sm text-muted">Do this once. The first account becomes the studio owner.</p>}
      <label className="block text-sm font-medium">
        Email
        <input className="field mt-1" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="block text-sm font-medium">
        Password
        <input className="field mt-1" type="password" autoComplete={mode === "in" ? "current-password" : "new-password"} minLength={10} required
          value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {msg && <p role="alert" className={`text-sm ${msg.bad ? "text-alert" : "text-penny"}`}>{msg.text}</p>}
      <button className="btn-primary w-full" disabled={busy}>{busy ? "Please wait…" : mode === "in" ? "Sign in" : "Create account"}</button>
      <button type="button" className="w-full text-sm text-muted underline-offset-2 hover:underline" onClick={() => setMode(mode === "in" ? "up" : "in")}>
        {mode === "in" ? "First time? Create the owner account" : "Already have an account? Sign in"}
      </button>
    </form>
  );
}
