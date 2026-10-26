import type { Session } from "@supabase/supabase-js";
import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { friendlyError, rememberDestination, takeDestination } from "../lib/state";
import { configured, signedOutDeliberately, signOut, supabase } from "../lib/supabase";

// "failed" = the access check didn't get an answer (offline, server error): never treated as "not the owner".
type OwnerState = "checking" | "owner" | "not-owner" | "failed";

export default function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [owner, setOwner] = useState<OwnerState>("checking");
  const [checkError, setCheckError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const hadSession = useRef(false);
  const [endedMidway, setEndedMidway] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const here = `${location.pathname}${location.search}${location.hash}`;

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session)).catch(() => setSession(null));
    const { data } = supabase.auth.onAuthStateChange((_event, s) => {
      if (!s && hadSession.current && !signedOutDeliberately()) setEndedMidway(true);  // expired, not the Sign out button
      setSession(s);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (session) hadSession.current = true;
  }, [session]);

  // Signed out: remember where the owner was, so signing in (even via an emailed link) brings them back.
  useEffect(() => {
    if (session === null) rememberDestination(here);
  }, [session, here]);

  useEffect(() => {
    if (!session) return;
    let live = true;
    setOwner("checking");
    // The first account to sign in becomes the owner; everyone after that is refused by the database.
    Promise.resolve(supabase.rpc("claim_ownership"))
      .then(({ data, error }) => {
        if (!live) return;
        if (error) { setCheckError(friendlyError(error.message)); setOwner("failed"); return; }
        setOwner(data ? "owner" : "not-owner");
      })
      .catch((e) => { if (live) { setCheckError(friendlyError(e)); setOwner("failed"); } });
    return () => { live = false; };
  }, [session?.user.id, attempt]);

  // Access confirmed: go back to where the owner was heading, if it was somewhere else.
  useEffect(() => {
    if (owner !== "owner") return;
    const to = takeDestination();
    if (to && to !== here) navigate(to, { replace: true });
    setEndedMidway(false);
  }, [owner]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!configured) return <Shell><SetupNeeded /></Shell>;
  if (session === undefined) return <Shell><p className="text-muted" role="status">Loading…</p></Shell>;
  if (!session) return <Shell><SignIn notice={endedMidway ? "Your sign-in ended. Sign in again and you'll go back to the page you were on." : undefined} /></Shell>;
  if (owner === "checking") return <Shell><p className="text-muted" role="status">Checking your access…</p></Shell>;
  if (owner === "failed")
    return (
      <Shell>
        <h1 className="font-display text-2xl font-bold">Couldn't check your access</h1>
        <p role="alert" className="mt-2 text-muted">{checkError.replace(/[.!]?$/, ".")} This doesn't mean you've lost access: the studio just didn't answer.</p>
        <div className="mt-6 flex gap-2">
          <button className="btn-primary" onClick={() => setAttempt((n) => n + 1)}>Retry</button>
          <button className="btn-quiet" onClick={() => signOut()}>Sign out</button>
        </div>
      </Shell>
    );
  if (owner === "not-owner")
    return (
      <Shell>
        <h1 className="font-display text-2xl font-bold">This studio already has an owner</h1>
        <p className="mt-2 text-muted">You're signed in as {session.user.email}, which isn't the owner account.</p>
        <button className="btn-quiet mt-6" onClick={() => signOut()}>Sign out</button>
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
        <code>VITE_SUPABASE_ANON_KEY</code> to the Vercel project's Environment Variables, then redeploy.
      </p>
      <Link to="/demo" className="btn-quiet mt-6 w-full">Explore the interactive demo</Link>
    </>
  );
}

function SignIn({ notice }: { notice?: string }) {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;  // one attempt at a time
    setBusy(true);
    setMsg(null);
    let result: { error: { message: string } | null; data: { session: unknown } };
    try {
      result = mode === "in"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin } });
    } catch (err) {
      setBusy(false);
      return setMsg({ text: friendlyError(err), bad: true });  // the email stays filled in
    }
    setBusy(false);
    const { error, data } = result;
    if (error) return setMsg({ text: friendlyError(error.message), bad: true });
    if (mode === "up" && !data.session) setMsg({ text: "Check your email and click the confirmation link, then sign in here." });
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="font-display text-2xl font-bold">{mode === "in" ? "Sign in" : "Create the owner account"}</h1>
      {notice && <p role="status" className="rounded-lg bg-gold/15 px-3 py-2 text-sm text-ink">{notice}</p>}
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
      <Link to="/demo" className="block text-center text-sm text-muted underline-offset-2 hover:underline">Preview Mission Control with sample data</Link>
    </form>
  );
}
