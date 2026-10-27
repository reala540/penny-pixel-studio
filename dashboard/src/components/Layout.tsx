import DraftSync from "./DraftSync";
import { Activity, CalendarDays, ChevronDown, CircleHelp, Home, LayoutList, LogOut, Menu, PlusCircle, Settings, X } from "lucide-react";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useSetting } from "../lib/api";
import { known, useOnline, useOtherTabChanges } from "../lib/state";
import { useNeedsYouCount } from "../lib/content";
import { signOut, supabase } from "../lib/supabase";
import { AutoPostBadge } from "./AutoPostToggle";
import RunningNow from "./RunningNow";
import ThemeControl from "./ThemeControl";
import Tour from "./Tour";
import WorldClock from "./WorldClock";
import { Loading } from "./ui";

/** The five destinations never change, move or hide. */
const NAV = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/create", label: "Create", icon: PlusCircle },
  { to: "/content", label: "Content", icon: LayoutList },
  { to: "/calendar", label: "Calendar", icon: CalendarDays },
  { to: "/activity", label: "Activity", icon: Activity },
] as const;

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="Penny & Pixel Studio, Home">
      <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="8" className="fill-ink" />
        <circle cx="12" cy="16" r="6" className="fill-gold" />
        <rect x="17" y="10" width="11" height="12" rx="2" className="fill-cyan" />
      </svg>
      <span className="leading-tight">
        <span className="block whitespace-nowrap font-display text-base font-bold">Penny &amp; Pixel</span>
        <span className="block text-xs text-muted">Studio</span>
      </span>
    </Link>
  );
}

function CountBadge({ n }: { n: number }) {
  if (!n) return null;
  return <span className="ml-auto rounded-full bg-gold/25 px-2 py-0.5 text-xs font-semibold tabular text-ink" aria-label={`${n} need you`}>{n}</span>;
}

const secondaryLink = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm ${isActive ? "bg-sunken text-ink" : "text-muted hover:bg-sunken hover:text-ink"}`;

/** Connection and "is publishing paused?" — said only when known; a failed check says so instead of guessing. */
function StatusBanners() {
  const online = useOnline();
  const pausedQ = useSetting<boolean>("paused", false);
  const paused = known(pausedQ, online);
  return (
    <>
      {!online && (
        <div role="alert" className="bg-gold px-4 py-2 text-center text-sm font-medium text-ink">
          You're offline. What you see may be out of date, and changes can't be saved until you're back online.
        </div>
      )}
      {paused.state === "confirmed" && paused.value === true && (
        <div role="status" className="bg-alert px-4 py-2 text-center text-sm font-medium text-surface">
          Publishing is paused: nothing will be posted until you resume it. Making content still works.
        </div>
      )}
      {paused.state === "failed" && (
        <div role="alert" className="flex flex-wrap items-center justify-center gap-2 bg-alert-soft px-4 py-2 text-center text-sm text-alert">
          Couldn't check whether publishing is paused: {paused.error}
          <button type="button" className="rounded-md border border-alert/40 px-2 py-0.5 text-xs font-semibold" onClick={() => pausedQ.refetch()}>Retry</button>
        </div>
      )}
    </>
  );
}

export default function Layout() {
  const qc = useQueryClient();
  // another tab changed something: refresh what this tab shows
  useOtherTabChanges(useCallback((keys?: string[][]) => {
    if (keys?.length) keys.forEach((k) => qc.invalidateQueries({ queryKey: k }));
    else qc.invalidateQueries();
  }, [qc]));
  const needsYou = useNeedsYouCount().data ?? 0;
  const scroller = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  const [sheet, setSheet] = useState(false);
  const location = useLocation();
  useEffect(() => setSheet(false), [location.pathname]);
  const measure = useCallback(() => {
    const el = scroller.current;
    setMore(Boolean(el && el.scrollHeight - el.scrollTop - el.clientHeight > 4));
  }, []);
  useEffect(() => {
    measure();
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    Array.from(el.children).forEach((c) => ro.observe(c));
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, [measure]);

  return (
    <div className="min-h-screen md:grid md:grid-cols-[232px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <div className="hidden border-r border-line bg-surface md:block">
      <aside aria-label="Sidebar" className="sticky top-0 flex h-screen flex-col">
        <div ref={scroller} onScroll={measure} className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
          <Brand />
          <nav aria-label="Main" className="mt-5 flex flex-col gap-0.5">
            {NAV.map(({ to, label, icon: Icon, ...rest }) => (
              <NavLink key={to} to={to} end={"end" in rest}
                className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${isActive ? "bg-ink text-surface" : "text-muted hover:bg-sunken hover:text-ink"}`}>
                <Icon size={18} aria-hidden />
                {label}
                {to === "/content" && <CountBadge n={needsYou} />}
              </NavLink>
            ))}
          </nav>
          <div className="mt-5 flex flex-col gap-1 border-t border-line pt-3">
            <RunningNow />
            <AutoPostBadge />
          </div>
          <div className="min-h-4 flex-1" aria-hidden />
          <nav aria-label="More" className="flex flex-col gap-0.5 border-t border-line pt-3">
            <NavLink to="/settings" className={secondaryLink}><Settings size={17} aria-hidden /> Settings</NavLink>
            <div className="flex items-center justify-between gap-2">
              <NavLink to="/help" className={secondaryLink}><CircleHelp size={17} aria-hidden /> Help</NavLink>
              <ThemeControl compact />
            </div>
            <button onClick={() => signOut()} className="flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-1.5 text-left text-sm text-muted hover:bg-sunken hover:text-ink">
              <LogOut size={17} aria-hidden /> Sign out
            </button>
          </nav>
        </div>
        {more && (
          <button type="button" onClick={() => scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" })}
            className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-1 bg-gradient-to-t from-surface via-surface/95 to-transparent pb-2 pt-6 text-xs font-medium text-muted hover:text-ink"
            aria-label="Scroll the menu down to see more">
            More <ChevronDown size={14} aria-hidden />
          </button>
        )}
      </aside>
      </div>

      <div className="flex min-w-0 flex-col">
        <div className="flex items-center justify-between gap-2 border-b border-line bg-surface px-4 py-2.5 md:hidden">
          <Brand />
          <div className="flex min-w-0 items-center gap-1">
            <div className="min-w-0 max-w-[9rem]"><RunningNow /></div>
            <button type="button" onClick={() => setSheet(true)} aria-haspopup="dialog" aria-expanded={sheet}
              className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-2 text-sm text-muted"><Menu size={20} aria-hidden />More</button>
          </div>
        </div>
        <header aria-label="Clocks" className="border-b border-line bg-surface px-4 py-2 sm:px-6">
          <div className="mx-auto flex max-w-[1600px] justify-end"><WorldClock /></div>
        </header>
        <StatusBanners />
        <DraftSync />
        <main id="main" className="mx-auto w-full max-w-[1600px] flex-1 px-4 pb-28 pt-6 sm:px-6 md:pb-12">
          <Suspense fallback={<Loading label="Loading page" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-line bg-surface md:hidden">
        {NAV.map(({ to, label, icon: Icon, ...rest }) => (
          <NavLink key={to} to={to} end={"end" in rest}
            className={({ isActive }) => `relative flex flex-col items-center gap-0.5 px-1 py-2 text-xs font-medium ${isActive ? "text-pixel" : "text-muted"}`}>
            <Icon size={20} aria-hidden />
            {label}
            {to === "/content" && needsYou > 0 && <span className="absolute right-3 top-1 h-2 w-2 rounded-full bg-gold" aria-label={`${needsYou} need you`} />}
          </NavLink>
        ))}
      </nav>
      {sheet && createPortal(
        <div className="fixed inset-0 z-40 flex items-end bg-ink/40 md:hidden" onClick={() => setSheet(false)}>
          <div role="dialog" aria-modal="true" aria-label="More" className="w-full rounded-t-2xl bg-surface p-4 pb-8 shadow-xl" onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.key === "Escape" && setSheet(false)}>
            <div className="mb-3 flex items-center justify-between">
              <p className="font-display text-base font-semibold">More</p>
              <button className="rounded-lg p-2 text-muted" aria-label="Close" onClick={() => setSheet(false)} autoFocus><X size={18} /></button>
            </div>
            <div className="flex flex-col gap-1">
              <AutoPostBadge />
              <NavLink to="/settings" className={secondaryLink}><Settings size={17} aria-hidden /> Settings</NavLink>
              <NavLink to="/help" className={secondaryLink}><CircleHelp size={17} aria-hidden /> Help</NavLink>
              <div className="flex items-center justify-between px-3 py-1.5 text-sm text-muted">Theme <ThemeControl compact /></div>
              <button onClick={() => signOut()} className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm text-muted hover:bg-sunken">
                <LogOut size={17} aria-hidden /> Sign out
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
      <Tour />
    </div>
  );
}
